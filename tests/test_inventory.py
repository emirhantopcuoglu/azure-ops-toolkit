import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from opsctl.inventory import (
    ResourceRecord,
    format_table,
    list_resources,
    save_report,
    to_csv,
    to_json,
)

VM = ResourceRecord(
    name="vm-ops-01",
    type="Microsoft.Compute/virtualMachines",
    location="swedencentral",
    tags={"role": "web", "env": "dev"},
)
NSG = ResourceRecord(
    name="vm-ops-01NSG",
    type="Microsoft.Network/networkSecurityGroups",
    location="swedencentral",
    tags={},
)


def _azure_resource(name, resource_type, tags):
    # Stand-in for the SDK's GenericResource: only the attributes list_resources reads
    return SimpleNamespace(name=name, type=resource_type, location="swedencentral", tags=tags)


def test_list_resources_queries_the_given_resource_group_and_sorts_by_type_then_name():
    # Arrange: the SDK returns resources in arbitrary order
    client = Mock()
    client.resources.list_by_resource_group.return_value = [
        _azure_resource("vm-b", "Microsoft.Compute/virtualMachines", {}),
        _azure_resource("nic-a", "Microsoft.Network/networkInterfaces", {}),
        _azure_resource("vm-a", "Microsoft.Compute/virtualMachines", {}),
    ]

    # Act
    records = list_resources(client, "rg-test")

    # Assert
    client.resources.list_by_resource_group.assert_called_once_with("rg-test")
    assert [record.name for record in records] == ["vm-a", "vm-b", "nic-a"]


def test_list_resources_converts_missing_tags_to_empty_dict():
    client = Mock()
    client.resources.list_by_resource_group.return_value = [
        _azure_resource("disk-a", "Microsoft.Compute/disks", None),
    ]

    records = list_resources(client, "rg-test")

    assert records[0].tags == {}


def test_format_table_aligns_columns_and_sorts_tags():
    table = format_table([VM, NSG])

    assert table.splitlines() == [
        "NAME          TYPE                                     LOCATION       TAGS",
        "vm-ops-01     Microsoft.Compute/virtualMachines        swedencentral  env=dev;role=web",
        "vm-ops-01NSG  Microsoft.Network/networkSecurityGroups  swedencentral",
    ]


def test_format_table_with_no_records_returns_only_headers():
    assert format_table([]) == "NAME  TYPE  LOCATION  TAGS"


def test_to_csv_writes_header_and_flattened_tags():
    assert to_csv([VM]) == (
        "name,type,location,tags\n"
        "vm-ops-01,Microsoft.Compute/virtualMachines,swedencentral,env=dev;role=web\n"
    )


def test_to_json_keeps_tags_as_objects():
    parsed = json.loads(to_json([VM]))

    assert parsed == [
        {
            "name": "vm-ops-01",
            "type": "Microsoft.Compute/virtualMachines",
            "location": "swedencentral",
            "tags": {"role": "web", "env": "dev"},
        }
    ]


def test_save_report_writes_timestamped_file_and_creates_directory(tmp_path):
    # Arrange: tmp_path is a fresh per-test directory provided by pytest
    reports_dir = tmp_path / "reports"
    generated_at = datetime(2026, 10, 17, 13, 25, 0, tzinfo=timezone.utc)

    # Act
    report_path = save_report("a,b\n", "csv", reports_dir, generated_at)

    # Assert
    assert report_path == reports_dir / "inventory-20261017T132500Z.csv"
    assert report_path.read_text(encoding="utf-8") == "a,b\n"
