import argparse
import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import httpx

from .brevo import send_brevo_email
from .config import ServiceDefinition, load_service_definitions

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class MonitorSettings:
    interval: float = 60.0
    down_notification_cooldown: float = 900.0
    recovery_notification_cooldown: float = 0.0
    send_recovery_alerts: bool = True


@dataclass
class ServiceState:
    consecutive_failures: int = 0
    is_down: bool = False
    last_error: str = ""
    last_status_code: Optional[int] = None
    last_down_notification: float = 0.0
    last_recovery_notification: float = 0.0


async def _check_service(
    client: httpx.AsyncClient, service: ServiceDefinition
) -> Tuple[bool, str, Optional[int]]:
    try:
        response = await client.request(
            service.method,
            service.url,
            headers=service.headers or None,
            timeout=service.timeout,
        )
    except httpx.TimeoutException:
        return False, f"Request timed out after {service.timeout} seconds.", None
    except httpx.RequestError as exc:
        return False, f"Request failed: {exc}", None

    status_code = response.status_code
    if status_code not in service.expected_statuses:
        return False, f"Unexpected status code {status_code}", status_code

    return True, f"Healthy (status {status_code})", status_code


async def _send_down_alert(
    service: ServiceDefinition, state: ServiceState, detail: str
) -> None:
    now = datetime.now(timezone.utc)
    subject = f"[ALERT] {service.label} is down"
    html = (
        f"<h2>Service downtime detected</h2>"
        f"<p><strong>Service:</strong> {service.label}</p>"
        f"<p><strong>Endpoint:</strong> {service.url}</p>"
        f"<p><strong>Detected at (UTC):</strong> {now.strftime('%Y-%m-%d %H:%M:%S')}</p>"
        f"<p><strong>Details:</strong> {detail}</p>"
    )
    if state.last_status_code:
        html += f"<p><strong>Status code:</strong> {state.last_status_code}</p>"

    text = (
        f"Service downtime detected\n"
        f"Service: {service.label}\n"
        f"Endpoint: {service.url}\n"
        f"Detected at (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Details: {detail}\n"
    )
    if state.last_status_code:
        text += f"Status code: {state.last_status_code}\n"

    await send_brevo_email(
        subject=subject,
        html_content=html,
        text_content=text,
        tags=["service-monitor", "downtime"],
    )


async def _send_recovery_alert(
    service: ServiceDefinition, state: ServiceState, detail: str
) -> None:
    now = datetime.now(timezone.utc)
    subject = f"[RECOVERY] {service.label} is back online"
    html = (
        f"<h2>Service recovery detected</h2>"
        f"<p><strong>Service:</strong> {service.label}</p>"
        f"<p><strong>Endpoint:</strong> {service.url}</p>"
        f"<p><strong>Recovered at (UTC):</strong> {now.strftime('%Y-%m-%d %H:%M:%S')}</p>"
        f"<p><strong>Latest check:</strong> {detail}</p>"
    )
    text = (
        f"Service recovery detected\n"
        f"Service: {service.label}\n"
        f"Endpoint: {service.url}\n"
        f"Recovered at (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Latest check: {detail}\n"
    )

    await send_brevo_email(
        subject=subject,
        html_content=html,
        text_content=text,
        tags=["service-monitor", "recovery"],
    )


async def _monitor_iteration(
    client: httpx.AsyncClient,
    services: Dict[str, ServiceDefinition],
    states: Dict[str, ServiceState],
    settings: MonitorSettings,
    *,
    timestamp: float,
) -> None:
    tasks = [asyncio.create_task(_check_service(client, service)) for service in services.values()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for service_key, result in zip(services.keys(), results):
        service = services[service_key]
        state = states.setdefault(service_key, ServiceState())

        if isinstance(result, Exception):
            is_up = False
            detail = f"Unhandled check error: {result}"
            status_code = None
        else:
            is_up, detail, status_code = result

        state.last_status_code = status_code

        if is_up:
            if state.is_down:
                logger.info("Service recovered: %s | %s", service.label, detail)
            state.consecutive_failures = 0
            state.last_error = ""

            if state.is_down and settings.send_recovery_alerts:
                if (
                    timestamp - state.last_recovery_notification
                    >= settings.recovery_notification_cooldown
                ):
                    await _send_recovery_alert(service, state, detail)
                    state.last_recovery_notification = timestamp
                state.is_down = False
                state.last_down_notification = 0.0
            else:
                state.is_down = False
            continue

        # Failure handling
        state.last_error = detail
        state.consecutive_failures += 1

        logger.warning(
            "Service check failed (%s/%s): %s | %s",
            state.consecutive_failures,
            service.failure_threshold,
            service.label,
            detail,
        )

        if state.consecutive_failures < service.failure_threshold:
            continue

        should_notify = False
        if not state.is_down:
            should_notify = True
        else:
            elapsed = timestamp - state.last_down_notification
            if elapsed >= settings.down_notification_cooldown:
                should_notify = True

        state.is_down = True

        if should_notify:
            await _send_down_alert(service, state, detail)
            state.last_down_notification = timestamp


async def run_monitor(run_once: bool = False, stop_event: Optional[asyncio.Event] = None) -> None:
    services_list = load_service_definitions()
    services = {service.name: service for service in services_list}
    states: Dict[str, ServiceState] = {}

    settings = MonitorSettings(
        interval=float(os.getenv("SERVICE_MONITOR_INTERVAL", "60")),
        down_notification_cooldown=float(
            os.getenv("SERVICE_MONITOR_DOWN_NOTIFY_COOLDOWN", "900")
        ),
        recovery_notification_cooldown=float(
            os.getenv("SERVICE_MONITOR_RECOVERY_NOTIFY_COOLDOWN", "0")
        ),
        send_recovery_alerts=_env_bool("SERVICE_MONITOR_SEND_RECOVERY", True),
    )

    logger.info(
        "Starting service monitor for %d services. Interval=%ss, failure_threshold=%s",
        len(services),
        settings.interval,
        ", ".join(f"{svc.name}:{svc.failure_threshold}" for svc in services.values()),
    )

    internal_stop_event = stop_event or asyncio.Event()

    if stop_event is None:
        def _handle_signal(signum, frame):  # noqa: D401, DAR101
            logger.info("Received signal %s, stopping monitor.", signum)
            internal_stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _handle_signal, sig, None)
            except NotImplementedError:
                signal.signal(sig, _handle_signal)  # type: ignore[arg-type]

    async with httpx.AsyncClient(timeout=None) as client:
        while not internal_stop_event.is_set():
            timestamp = time.time()
            await _monitor_iteration(client, services, states, settings, timestamp=timestamp)

            if run_once:
                break

            try:
                await asyncio.wait_for(internal_stop_event.wait(), timeout=settings.interval)
            except asyncio.TimeoutError:
                continue


def main() -> None:
    parser = argparse.ArgumentParser(description="Service downtime monitor with Brevo alerts.")
    parser.add_argument("--once", action="store_true", help="Run a single health check cycle and exit.")
    parser.add_argument(
        "--log-level",
        default=os.getenv("SERVICE_MONITOR_LOG_LEVEL", "INFO"),
        help="Logging level to use (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        asyncio.run(run_monitor(run_once=args.once))
    except KeyboardInterrupt:
        logger.info("Service monitor interrupted by user.")


if __name__ == "__main__":
    main()
