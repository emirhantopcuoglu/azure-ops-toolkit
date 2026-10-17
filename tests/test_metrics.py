from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.mgmt.monitor.models import MetricUnit

from opsctl.metrics import (
    METRIC_CPU,
    METRIC_DISK_READ,
    METRIC_NETWORK_IN,
    MetricStatus,
    MetricSummary,
    build_alert_message,
    evaluate,
    fetch_metric_summaries,
    fetch_vm_metrics,
    format_metrics_table,
)

END_TIME = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
CPU_THRESHOLD = 80.0


def _metric(name, unit, points):
    """Build an SDK-shaped Metric; points are (average, maximum) tuples."""
    data = [SimpleNamespace(average=average, maximum=maximum) for average, maximum in points]
    return SimpleNamespace(name=SimpleNamespace(value=name), unit=unit, timeseries=[SimpleNamespace(data=data)])


def _monitor_client(*metrics):
    client = Mock()
    client.metrics.list.return_value = SimpleNamespace(value=list(metrics))
    return client


def test_fetch_metric_summaries_requests_last_hour_in_five_minute_intervals():
    client = _monitor_client()

    fetch_metric_summaries(client, "/subscriptions/x/vm-a", END_TIME)

    client.metrics.list.assert_called_once_with(
        "/subscriptions/x/vm-a",
        timespan="2026-10-17T11:00:00Z/2026-10-17T12:00:00Z",
        interval="PT5M",
        metricnames="Percentage CPU,Network In Total,Disk Read Bytes",
        aggregation="Average,Maximum",
    )


def test_fetch_metric_summaries_ignores_empty_intervals_and_restores_requested_order():
    # Arrange: Azure returns metrics out of order, with None for intervals without data
    client = _monitor_client(
        _metric(METRIC_NETWORK_IN, "Bytes", [(None, None), (1000.0, 1500.0)]),
        _metric(METRIC_CPU, "Percent", [(None, None), (None, None), (10.0, 30.0), (20.0, 40.0)]),
    )

    # Act
    summaries = fetch_metric_summaries(client, "/subscriptions/x/vm-a", END_TIME)

    # Assert
    assert summaries == [
        MetricSummary(name=METRIC_CPU, unit="Percent", average=15.0, maximum=40.0),
        MetricSummary(name=METRIC_NETWORK_IN, unit="Bytes", average=1000.0, maximum=1500.0),
    ]


def test_fetch_metric_summaries_reports_none_when_metric_has_no_data():
    client = _monitor_client(_metric(METRIC_DISK_READ, "Bytes", [(None, None), (None, None)]))

    summaries = fetch_metric_summaries(client, "/subscriptions/x/vm-a", END_TIME)

    assert summaries == [MetricSummary(name=METRIC_DISK_READ, unit="Bytes", average=None, maximum=None)]


def test_fetch_vm_metrics_queries_each_vm_by_resource_id():
    compute_client = Mock()
    compute_client.virtual_machines.list.return_value = [
        SimpleNamespace(name="vm-b", id="/vms/vm-b"),
        SimpleNamespace(name="vm-a", id="/vms/vm-a"),
    ]
    monitor_client = _monitor_client()

    metrics_by_vm = fetch_vm_metrics(compute_client, monitor_client, "rg-test", END_TIME)

    assert list(metrics_by_vm) == ["vm-a", "vm-b"]
    queried_ids = [call.args[0] for call in monitor_client.metrics.list.call_args_list]
    assert queried_ids == ["/vms/vm-a", "/vms/vm-b"]


@pytest.mark.parametrize(
    ("average", "expected"),
    [
        (79.9, MetricStatus.OK),
        (80.0, MetricStatus.OK),
        (80.1, MetricStatus.WARN),
        (None, MetricStatus.NO_DATA),
    ],
)
def test_evaluate_warns_only_when_cpu_average_exceeds_threshold(average, expected):
    summary = MetricSummary(name=METRIC_CPU, unit="Percent", average=average, maximum=99.0)

    assert evaluate(summary, CPU_THRESHOLD) is expected


def test_evaluate_ignores_short_cpu_spikes_when_average_is_low():
    summary = MetricSummary(name=METRIC_CPU, unit="Percent", average=12.0, maximum=98.0)

    assert evaluate(summary, CPU_THRESHOLD) is MetricStatus.OK


def test_evaluate_does_not_apply_cpu_threshold_to_other_metrics():
    summary = MetricSummary(name=METRIC_NETWORK_IN, unit="Bytes", average=10_000_000.0, maximum=None)

    assert evaluate(summary, CPU_THRESHOLD) is MetricStatus.OK


def test_format_metrics_table_renders_units_and_status():
    metrics_by_vm = {
        "vm-a": [
            MetricSummary(name=METRIC_CPU, unit="Percent", average=85.04, maximum=97.0),
            MetricSummary(name=METRIC_NETWORK_IN, unit="Bytes", average=50381.6, maximum=None),
        ]
    }

    assert format_metrics_table(metrics_by_vm, CPU_THRESHOLD).splitlines() == [
        "VM    METRIC            AVG      MAX    STATUS",
        "vm-a  Percentage CPU    85.0%    97.0%  WARN",
        "vm-a  Network In Total  49.2 KB  -      OK",
    ]


def test_format_metrics_table_handles_sdk_unit_enums():
    # Regression: str(MetricUnit.PERCENT) is "MetricUnit.PERCENT", which would bypass unit formatting
    client = _monitor_client(_metric(METRIC_CPU, MetricUnit.PERCENT, [(42.0, 50.0)]))
    summaries = fetch_metric_summaries(client, "/subscriptions/x/vm-a", END_TIME)

    table = format_metrics_table({"vm-a": summaries}, CPU_THRESHOLD)

    assert "42.0%" in table


def test_build_alert_message_returns_none_when_nothing_is_in_warn_state():
    metrics_by_vm = {"vm-a": [MetricSummary(name=METRIC_CPU, unit="Percent", average=10.0, maximum=95.0)]}

    assert build_alert_message(metrics_by_vm, CPU_THRESHOLD) is None
