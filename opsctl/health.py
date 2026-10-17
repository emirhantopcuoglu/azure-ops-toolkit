"""External health checks: DNS resolution and HTTP status of the health endpoint."""

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

HEALTH_PATH = "/healthz"
HTTP_TIMEOUT_SECONDS = 5
HTTP_STATUS_OK = 200
MILLISECONDS_PER_SECOND = 1000


@dataclass(frozen=True)
class DnsResult:
    host: str
    ip_address: str | None
    error: str | None

    @property
    def is_healthy(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class HttpResult:
    url: str
    status_code: int | None
    elapsed_ms: float | None
    error: str | None

    @property
    def is_healthy(self) -> bool:
        return self.status_code == HTTP_STATUS_OK


def check_dns(host: str, resolve: Callable[[str], str] = socket.gethostbyname) -> DnsResult:
    """Resolve the host to an IPv4 address; failures are returned, not raised."""
    try:
        return DnsResult(host=host, ip_address=resolve(host), error=None)
    except OSError as error:
        return DnsResult(host=host, ip_address=None, error=str(error))


def check_http(
    url: str,
    get: Callable[..., requests.Response] = requests.get,
    clock: Callable[[], float] = time.perf_counter,
) -> HttpResult:
    """Request the URL and measure the response time; failures are returned, not raised."""
    started_at = clock()
    try:
        response = get(url, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as error:
        return HttpResult(url=url, status_code=None, elapsed_ms=None, error=type(error).__name__)
    elapsed_ms = (clock() - started_at) * MILLISECONDS_PER_SECOND
    return HttpResult(url=url, status_code=response.status_code, elapsed_ms=elapsed_ms, error=None)


def health_url(host: str) -> str:
    return f"http://{host}{HEALTH_PATH}"
