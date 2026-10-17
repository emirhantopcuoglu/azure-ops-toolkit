"""Resource inventory: list what exists in the resource group and export it."""

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from azure.mgmt.resource.resources import ResourceManagementClient

from opsctl.formatting import format_tags, render_table

TABLE_HEADERS = ("NAME", "TYPE", "LOCATION", "TAGS")
CSV_FIELDS = ("name", "type", "location", "tags")
REPORT_FILENAME_PREFIX = "inventory"
JSON_INDENT = 2


@dataclass(frozen=True)
class ResourceRecord:
    name: str
    type: str
    location: str
    tags: dict[str, str]


def list_resources(client: ResourceManagementClient, resource_group: str) -> list[ResourceRecord]:
    """Return every resource in the group, sorted by type and then name."""
    records = [
        ResourceRecord(
            name=resource.name,
            type=resource.type,
            location=resource.location,
            # Azure returns None rather than {} for untagged resources
            tags=dict(resource.tags or {}),
        )
        for resource in client.resources.list_by_resource_group(resource_group)
    ]
    return sorted(records, key=lambda record: (record.type, record.name))


def format_table(records: list[ResourceRecord]) -> str:
    return render_table(TABLE_HEADERS, [_to_row(record) for record in records])


def to_csv(records: list[ResourceRecord]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_FIELDS)
    writer.writerows(_to_row(record) for record in records)
    return buffer.getvalue()


def to_json(records: list[ResourceRecord]) -> str:
    return json.dumps([asdict(record) for record in records], indent=JSON_INDENT) + "\n"


REPORT_SERIALIZERS = {"csv": to_csv, "json": to_json}


def save_report(content: str, report_format: str, reports_dir: Path, generated_at_utc: datetime) -> Path:
    """Write the report to a timestamped file and return its path."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = generated_at_utc.strftime("%Y%m%dT%H%M%SZ")
    report_path = reports_dir / f"{REPORT_FILENAME_PREFIX}-{timestamp}.{report_format}"
    report_path.write_text(content, encoding="utf-8", newline="\n")
    return report_path


def _to_row(record: ResourceRecord) -> tuple[str, str, str, str]:
    return (record.name, record.type, record.location, format_tags(record.tags))
