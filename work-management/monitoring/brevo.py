import asyncio
import logging
import os
from typing import Iterable, List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _evaluate_recipients(source: Optional[Iterable[str]]) -> List[str]:
    recipients: List[str] = []
    if not source:
        return recipients

    for entry in source:
        if not entry:
            continue
        email = entry.strip()
        if email:
            recipients.append(email)
    return recipients


def _parse_recipients_from_env() -> List[str]:
    raw_env = os.getenv("BREVO_ALERT_RECIPIENTS", "")
    if not raw_env:
        return []
    return _evaluate_recipients(raw_env.split(","))


async def send_brevo_email(
    *,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None,
    recipients: Optional[Sequence[str]] = None,
    api_key: Optional[str] = None,
    sender_email: Optional[str] = None,
    sender_name: Optional[str] = None,
    tags: Optional[Sequence[str]] = None,
    timeout: float = 10.0,
) -> None:
    """Send an email notification through Brevo's transactional API."""
    api_key = api_key or os.getenv("BREVO_API_KEY")
    if not api_key:
        logger.warning("BREVO_API_KEY is not configured. Skipping email notification.")
        return

    sender_email = sender_email or os.getenv("BREVO_SENDER_EMAIL")
    if not sender_email:
        logger.warning("BREVO_SENDER_EMAIL is not configured. Skipping email notification.")
        return

    sender_name = sender_name or os.getenv("BREVO_SENDER_NAME", "Service Monitor")

    recipient_list = _evaluate_recipients(recipients or [])
    if not recipient_list:
        recipient_list = _parse_recipients_from_env()

    if not recipient_list:
        logger.warning("No alert recipients configured. Skipping email notification.")
        return

    payload: dict = {
        "sender": {"email": sender_email, "name": sender_name},
        "to": [{"email": email} for email in recipient_list],
        "subject": subject,
        "htmlContent": html_content,
    }

    if text_content:
        payload["textContent"] = text_content

    if tags:
        payload["tags"] = list(tags)

    headers = {
        "api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(BREVO_API_URL, headers=headers, json=payload)
            response.raise_for_status()
        logger.info("Successfully sent email alert to %s", recipient_list)
    except httpx.HTTPStatusError as exc:
        body_excerpt = exc.response.text[:500] if exc.response else "No response body"
        logger.error(
            "Brevo API responded with an error: status=%s body=%s", exc.response.status_code, body_excerpt
        )
        # Don't raise - just log the error and continue
        return
    except httpx.HTTPError as exc:
        logger.error("Failed to call Brevo API: %s", exc)
        # Don't raise - just log the error and continue
        return


def send_brevo_email_sync(**kwargs) -> None:
    """Synchronous helper that wraps the async Brevo email sender."""

    async def _runner():
        await send_brevo_email(**kwargs)

    asyncio.run(_runner())
