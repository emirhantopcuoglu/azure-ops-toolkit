"""Azure Monitor platform metrics for VMs, with a CPU threshold check."""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient

from opsctl.formatting import format_bytes, render_table

METRIC_CPU = "Percentage CPU"
METRIC_NETWORK_IN = "Network In Total"
METRIC_DISK_READ = "Disk Read Bytes"
METRIC_NAMES = (METRIC_CPU, METRIC_NETWORK_IN, METRIC_DISK_READ)
AGGREGATIONS = ("Average", "Maximum")
LOOKBACK_WINDOW = timedelta(hours=1)
# ISO 8601 duration: one data point per 5 minutes
SAMPLING_INTERVAL = "PT5M"
AZURE_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
UNIT_PERCENT = "Percent"
UNIT_BYTES = "Bytes"
MISSING_VALUE = "-"
TABLE_HEADERS = ("VM", "METRIC", "AVG", "MAX", "STATUS")


class MetricStatus(Enum):
    OK = "OK"
    WARN = "WARN"
    NO_DATA = "NO DATA"


@dataclass(frozen=True)
class MetricSummary:
    name: str
    unit: str
    average: float | None
    maximum: float | None


def fetch_vm_metrics(
    compute_client: ComputeManagementClient,
    monitor_client: MonitorManagementClient,
    resource_group: str,
    end_time_utc: datetime,
) -> dict[str, list[MetricSummary]]:
    """Return metric summaries for the last hour, keyed by VM name."""
    return {
        vm.name: fetch_metric_summaries(monitor_client, vm.id, end_time_utc)
        for vm in sorted(compute_client.virtual_machines.list(resource_group), key=lambda vm: vm.name)
    }


def fetch_metric_summaries(
    client: MonitorManagementClient, resource_id: str, end_time_utc: datetime
) -> list[MetricSummary]:
    start_time_utc = end_time_utc - LOOKBACK_WINDOW
    response = client.metrics.list(
        resource_id,
        timespan=f"{start_time_utc:{AZURE_TIMESTAMP_FORMAT}}/{end_time_utc:{AZURE_TIMESTAMP_FORMAT}}",
        interval=SAMPLING_INTERVAL,
        metricnames=",".join(METRIC_NAMES),
        aggregation=",".join(AGGREGATIONS),
    )
    summaries_by_name = {metric.name.value: _summarize(metric) for metric in response.value}
    # Azure does not return metrics in the requested order
    return [summaries_by_name[name] for name in METRIC_NAMES if name in summaries_by_name]


def evaluate(summary: MetricSummary, cpu_threshold_percent: float) -> MetricStatus:
    """Classify a metric; only CPU has a threshold.

    The hourly average is compared rather than the maximum: short spikes are normal,
    sustained load is what signals a capacity problem.
    """
    if summary.average is None:
        return MetricStatus.NO_DATA
    if summary.name == METRIC_CPU and summary.average > cpu_threshold_percent:
        return MetricStatus.WARN
    return MetricStatus.OK


def format_metrics_table(metrics_by_vm: dict[str, list[MetricSummary]], cpu_threshold_percent: float) -> str:
    rows = [
        (
            vm_name,
            summary.name,
            _format_value(summary.average, summary.unit),
            _format_value(summary.maximum, summary.unit),
            evaluate(summary, cpu_threshold_percent).value,
        )
        for vm_name, summaries in metrics_by_vm.items()
        for summary in summaries
    ]
    return render_table(TABLE_HEADERS, rows)


def _summarize(metric) -> MetricSummary:
    points = [point for series in metric.timeseries for point in series.data]
    # Intervals before the VM started have no value; None means "no data", not zero
    averages = [point.average for point in points if point.average is not None]
    maxima = [point.maximum for point in points if point.maximum is not None]
    return MetricSummary(
        name=metric.name.value,
        # MetricUnit is a str enum: comparing it to "Percent" works, but str() would
        # return "MetricUnit.PERCENT", so keep the value as-is
        unit=metric.unit,
        # Every interval covers the same 5 minutes, so the mean of means is unbiased
        average=statistics.fmean(averages) if averages else None,
        maximum=max(maxima) if maxima else None,
    )


def _format_value(value: float | None, unit: str) -> str:
    if value is None:
        return MISSING_VALUE
    if unit == UNIT_PERCENT:
        return f"{value:.1f}%"
    if unit == UNIT_BYTES:
        return format_bytes(value)
    return f"{value:.1f}"
