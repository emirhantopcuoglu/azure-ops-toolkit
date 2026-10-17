"""Application settings loaded from environment variables."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_RESOURCE_GROUP = "rg-ops-toolkit"
DEFAULT_CPU_THRESHOLD_PERCENT = 80.0
MIN_CPU_THRESHOLD_PERCENT = 0.0
MAX_CPU_THRESHOLD_PERCENT = 100.0


class ConfigError(Exception):
    """Raised when a required setting is missing or has an invalid value."""


@dataclass(frozen=True)
class Config:
    subscription_id: str
    resource_group: str
    webhook_url: str | None
    cpu_threshold_percent: float


def load_config(environ: Mapping[str, str]) -> Config:
    """Build a validated Config from environment variables.

    The environment is passed in rather than read from os.environ so the function
    stays pure and can be tested with a plain dict.
    """
    return Config(
        subscription_id=_parse_subscription_id(environ.get("AZURE_SUBSCRIPTION_ID", "")),
        resource_group=environ.get("RESOURCE_GROUP", "").strip() or DEFAULT_RESOURCE_GROUP,
        webhook_url=environ.get("WEBHOOK_URL", "").strip() or None,
        cpu_threshold_percent=_parse_cpu_threshold(environ.get("CPU_THRESHOLD", "")),
    )


def _parse_subscription_id(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise ConfigError(
            "AZURE_SUBSCRIPTION_ID is not set. "
            "Find it with `az account show --query id -o tsv` and add it to .env"
        )
    try:
        uuid.UUID(value)
    except ValueError as error:
        raise ConfigError(f"AZURE_SUBSCRIPTION_ID must be a GUID, got {value!r}") from error
    return value


def _parse_cpu_threshold(raw_value: str) -> float:
    value = raw_value.strip()
    if not value:
        return DEFAULT_CPU_THRESHOLD_PERCENT
    try:
        threshold = float(value)
    except ValueError as error:
        raise ConfigError(f"CPU_THRESHOLD must be a number, got {value!r}") from error
    if not MIN_CPU_THRESHOLD_PERCENT < threshold <= MAX_CPU_THRESHOLD_PERCENT:
        raise ConfigError(
            f"CPU_THRESHOLD must be greater than {MIN_CPU_THRESHOLD_PERCENT:g} "
            f"and at most {MAX_CPU_THRESHOLD_PERCENT:g}, got {threshold:g}"
        )
    return threshold
