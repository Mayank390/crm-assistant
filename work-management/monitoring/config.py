import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ServiceDefinition:
    """Health check definition for a monitored service."""

    name: str
    url: str
    method: str = "GET"
    timeout: float = 10.0
    headers: Dict[str, str] = field(default_factory=dict)
    expected_statuses: Tuple[int, ...] = (200,)
    failure_threshold: int = 1
    description: Optional[str] = None

    def __post_init__(self) -> None:
        self.method = (self.method or "GET").upper()
        if isinstance(self.expected_statuses, int):
            self.expected_statuses = (int(self.expected_statuses),)
        else:
            try:
                self.expected_statuses = tuple(int(code) for code in self.expected_statuses)
            except TypeError as exc:
                raise ValueError("expected_statuses must be an int or an iterable of ints") from exc

        if not self.expected_statuses:
            self.expected_statuses = (200,)

        if self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")

        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")

        # Normalise header keys for consistency
        if self.headers:
            self.headers = {str(key): str(value) for key, value in self.headers.items()}

    @property
    def label(self) -> str:
        """Return a human-friendly label for the service."""
        return self.description or self.name


def _load_from_file(config_path: str) -> Sequence[dict]:
    with open(config_path, "r", encoding="utf-8") as fh:
        raw_content = fh.read()

    extension = os.path.splitext(config_path)[1].lower()

    if extension in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "PyYAML is required to load YAML configuration files. "
                "Install it with `pip install pyyaml` or provide a JSON configuration instead."
            ) from exc

        parsed = yaml.safe_load(raw_content) or []
    else:
        parsed = json.loads(raw_content)

    if isinstance(parsed, dict):
        services = parsed.get("services")
        if services is None:
            raise ValueError("Configuration dictionary must include a 'services' key")
        parsed = services

    if not isinstance(parsed, Iterable):
        raise ValueError("The configuration file must contain a list of service definitions")

    return list(parsed)


def _parse_inline_config(raw_value: str) -> List[dict]:
    """Parse inline configuration found in SERVICE_MONITOR_ENDPOINTS.

    Expected format:
        SERVICE_MONITOR_ENDPOINTS="Service A|https://api.example.com/health,Service B|https://..."

    Optionally the HTTP method can be provided as the third pipe-separated value.
    """
    services: List[dict] = []
    for entry in raw_value.split(","):
        entry = entry.strip()
        if not entry:
            continue

        parts = [part.strip() for part in entry.split("|") if part.strip()]
        if len(parts) < 2:
            logger.warning("Skipping malformed service monitor entry: %s", entry)
            continue

        name, url = parts[:2]
        method = parts[2] if len(parts) > 2 else "GET"

        services.append(
            {
                "name": name,
                "url": url,
                "method": method,
            }
        )

    return services


def _coerce_expected_statuses(record: dict) -> Sequence[int]:
    if "expected_statuses" in record and record["expected_statuses"] is not None:
        return record["expected_statuses"]
    if "expected_status" in record and record["expected_status"] is not None:
        return record["expected_status"]
    return record.get("expected", (200,))


def load_service_definitions() -> List[ServiceDefinition]:
    """Load service definitions from environment configuration.

    Priority:
        1. SERVICE_MONITOR_CONFIG pointing to a JSON/YAML file
        2. SERVICE_MONITOR_ENDPOINTS inline comma-separated value

    Returns:
        List of ServiceDefinition objects.
    """
    config_path = os.getenv("SERVICE_MONITOR_CONFIG")
    endpoints_inline = os.getenv("SERVICE_MONITOR_ENDPOINTS")

    default_timeout = float(os.getenv("SERVICE_MONITOR_DEFAULT_TIMEOUT", "10"))
    default_failure_threshold = int(os.getenv("SERVICE_MONITOR_DEFAULT_FAILURE_THRESHOLD", "1"))

    raw_records: List[dict] = []
    if config_path:
        raw_records.extend(_load_from_file(config_path))
    elif endpoints_inline:
        raw_records.extend(_parse_inline_config(endpoints_inline))
    else:
        raise RuntimeError(
            "No service monitor configuration found. "
            "Set either SERVICE_MONITOR_CONFIG or SERVICE_MONITOR_ENDPOINTS."
        )

    services: List[ServiceDefinition] = []
    for record in raw_records:
        if not isinstance(record, dict):
            logger.warning("Skipping malformed service configuration entry: %s", record)
            continue

        try:
            service = ServiceDefinition(
                name=str(record["name"]),
                url=str(record["url"]),
                method=str(record.get("method", "GET")),
                timeout=float(record.get("timeout", default_timeout)),
                headers=dict(record.get("headers", {})),
                expected_statuses=_coerce_expected_statuses(record),
                failure_threshold=int(record.get("failure_threshold", default_failure_threshold)),
                description=record.get("description"),
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Unable to parse service definition %s: %s", record, exc)
            continue

        services.append(service)

    if not services:
        raise RuntimeError("No valid service definitions were loaded for monitoring.")

    return services
