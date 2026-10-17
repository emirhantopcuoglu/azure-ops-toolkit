from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError

import opsctl.__main__ as cli

VALID_SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # Never read the developer's real .env or talk to Azure from unit tests
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "DefaultAzureCredential", MagicMock())
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", VALID_SUBSCRIPTION_ID)
    monkeypatch.setenv("RESOURCE_GROUP", "rg-test")
    monkeypatch.delenv("CPU_THRESHOLD", raising=False)


@pytest.fixture
def resource_client(monkeypatch):
    """Replace ResourceManagementClient with a mock and return that mock."""
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(cli, "ResourceManagementClient", Mock(return_value=client))
    return client


def test_inventory_prints_resource_table(resource_client, capsys):
    resource_client.resources.list_by_resource_group.return_value = [
        SimpleNamespace(
            name="vm-ops-01",
            type="Microsoft.Compute/virtualMachines",
            location="swedencentral",
            tags={"role": "web"},
        )
    ]

    exit_code = cli.main(["inventory"])

    assert exit_code == cli.EXIT_SUCCESS
    output = capsys.readouterr().out
    assert "vm-ops-01" in output
    assert "role=web" in output


def test_inventory_reports_empty_resource_group(resource_client, capsys):
    resource_client.resources.list_by_resource_group.return_value = []

    exit_code = cli.main(["inventory"])

    assert exit_code == cli.EXIT_SUCCESS
    assert "No resources found in rg-test" in capsys.readouterr().out


def test_returns_failure_with_hint_when_configuration_is_invalid(monkeypatch, capsys):
    monkeypatch.delenv("AZURE_SUBSCRIPTION_ID")

    exit_code = cli.main(["inventory"])

    assert exit_code == cli.EXIT_FAILURE
    assert "AZURE_SUBSCRIPTION_ID is not set" in capsys.readouterr().err


def test_returns_failure_with_login_hint_when_authentication_fails(resource_client, capsys):
    resource_client.resources.list_by_resource_group.side_effect = ClientAuthenticationError(
        "no credential available"
    )

    exit_code = cli.main(["inventory"])

    assert exit_code == cli.EXIT_FAILURE
    assert "az login" in capsys.readouterr().err


def test_returns_failure_when_azure_rejects_the_request(resource_client, capsys):
    resource_client.resources.list_by_resource_group.side_effect = ResourceNotFoundError(
        "Resource group 'rg-test' could not be found."
    )

    exit_code = cli.main(["inventory"])

    assert exit_code == cli.EXIT_FAILURE
    assert "Azure request failed: Resource group 'rg-test' could not be found." in capsys.readouterr().err


def test_rejects_unknown_output_format():
    # argparse exits with status 2 on invalid arguments
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["inventory", "--output", "xml"])

    assert exit_info.value.code == 2


@pytest.fixture
def compute_client(monkeypatch):
    """Replace ComputeManagementClient with a mock and return that mock."""
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr(cli, "ComputeManagementClient", Mock(return_value=client))
    return client


def test_vm_status_prints_power_state_table(compute_client, capsys):
    compute_client.virtual_machines.list.return_value = [SimpleNamespace(name="vm-ops-01", tags={})]
    compute_client.virtual_machines.instance_view.return_value = SimpleNamespace(
        statuses=[SimpleNamespace(code="PowerState/deallocated")]
    )

    exit_code = cli.main(["vm", "status"])

    assert exit_code == cli.EXIT_SUCCESS
    assert "vm-ops-01  deallocated" in capsys.readouterr().out


def test_vm_status_reports_resource_group_without_vms(compute_client, capsys):
    compute_client.virtual_machines.list.return_value = []

    exit_code = cli.main(["vm", "status"])

    assert exit_code == cli.EXIT_SUCCESS
    assert "No virtual machines found in rg-test" in capsys.readouterr().out
