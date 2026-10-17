import socket
from types import SimpleNamespace

import requests

from opsctl.health import check_dns, check_http, health_url


def _fake_clock(*readings):
    """Return a clock that yields the given readings (in seconds) one per call."""
    remaining = iter(readings)
    return lambda: next(remaining)


def test_check_dns_returns_resolved_address():
    result = check_dns("vm.example.com", resolve=lambda host: "20.0.0.1")

    assert result.ip_address == "20.0.0.1"
    assert result.is_healthy


def test_check_dns_reports_failure_instead_of_raising():
    def failing_resolve(host):
        raise socket.gaierror("Name or service not known")

    result = check_dns("missing.example.com", resolve=failing_resolve)

    assert result.ip_address is None
    assert result.error == "Name or service not known"
    assert not result.is_healthy


def test_check_http_measures_response_time_and_uses_timeout():
    # Arrange: the clock reads 10.000s before the request and 10.042s after it
    requested = {}

    def fake_get(url, timeout):
        requested.update(url=url, timeout=timeout)
        return SimpleNamespace(status_code=200)

    # Act
    result = check_http("http://vm/healthz", get=fake_get, clock=_fake_clock(10.000, 10.042))

    # Assert
    assert requested == {"url": "http://vm/healthz", "timeout": 5}
    assert result.status_code == 200
    assert round(result.elapsed_ms) == 42
    assert result.is_healthy


def test_check_http_is_unhealthy_for_non_200_status():
    result = check_http(
        "http://vm/healthz",
        get=lambda url, timeout: SimpleNamespace(status_code=502),
        clock=_fake_clock(0.0, 0.1),
    )

    assert result.status_code == 502
    assert not result.is_healthy


def test_check_http_reports_timeout_instead_of_raising():
    def timing_out_get(url, timeout):
        raise requests.Timeout()

    result = check_http("http://vm/healthz", get=timing_out_get, clock=_fake_clock(0.0))

    assert result.status_code is None
    assert result.error == "Timeout"
    assert not result.is_healthy


def test_health_url_points_at_health_endpoint():
    assert health_url("20.0.0.1") == "http://20.0.0.1/healthz"
