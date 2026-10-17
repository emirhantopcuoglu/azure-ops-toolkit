from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError

import opsctl.__main__ as cli
from opsctl.health import DnsResult, HttpResult

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


def _set_vms(compute_client, power_states_by_name, tags):
    compute_client.virtual_machines.list.return_value = [
        SimpleNamespace(name=name, tags=tags) for name in power_states_by_name
    ]
    compute_client.virtual_machines.instance_view.side_effect = lambda resource_group, vm_name: (
        SimpleNamespace(statuses=[SimpleNamespace(code=f"PowerState/{power_states_by_name[vm_name]}")])
    )


def test_vm_stop_dry_run_reports_plan_without_changing_anything(compute_client, capsys):
    _set_vms(compute_client, {"vm-ops-01": "running"}, tags={"auto-shutdown": "true"})

    exit_code = cli.main(["vm", "stop", "--tag", "auto-shutdown=true", "--dry-run"])

    assert exit_code == cli.EXIT_SUCCESS
    assert "[dry-run] would deallocate vm-ops-01 (currently running)" in capsys.readouterr().out
    compute_client.virtual_machines.begin_deallocate.assert_not_called()


def test_vm_stop_deallocates_only_vms_that_are_not_already_deallocated(compute_client, capsys):
    _set_vms(
        compute_client,
        {"vm-running": "running", "vm-idle": "deallocated"},
        tags={"auto-shutdown": "true"},
    )

    exit_code = cli.main(["vm", "stop", "--tag", "auto-shutdown=true"])

    assert exit_code == cli.EXIT_SUCCESS
    compute_client.virtual_machines.begin_deallocate.assert_called_once_with("rg-test", "vm-running")
    output = capsys.readouterr().out
    assert "vm-idle: already deallocated, skipping" in output
    assert "Deallocating vm-running..." in output


def test_vm_start_ignores_vms_without_the_tag(compute_client, capsys):
    _set_vms(compute_client, {"vm-ops-01": "deallocated"}, tags={"auto-shutdown": "false"})

    exit_code = cli.main(["vm", "start", "--tag", "auto-shutdown=true"])

    assert exit_code == cli.EXIT_SUCCESS
    assert "No VMs tagged auto-shutdown=true in rg-test" in capsys.readouterr().out
    compute_client.virtual_machines.begin_start.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        ["vm", "stop"],
        ["vm", "stop", "--tag", "auto-shutdown"],
        ["vm", "stop", "--tag", "=true"],
        ["vm", "stop", "--tag", "auto-shutdown="],
    ],
)
def test_vm_power_commands_require_a_key_value_tag(arguments):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(arguments)

    assert exit_info.value.code == 2


def test_metrics_prints_table_and_flags_cpu_above_threshold(compute_client, monkeypatch, capsys):
    # Arrange
    compute_client.virtual_machines.list.return_value = [SimpleNamespace(name="vm-ops-01", id="/vms/vm-ops-01")]
    monitor_client = MagicMock()
    monitor_client.__enter__.return_value = monitor_client
    monitor_client.metrics.list.return_value = SimpleNamespace(
        value=[
            SimpleNamespace(
                name=SimpleNamespace(value="Percentage CPU"),
                unit="Percent",
                timeseries=[SimpleNamespace(data=[SimpleNamespace(average=92.0, maximum=99.0)])],
            )
        ]
    )
    monkeypatch.setattr(cli, "MonitorManagementClient", Mock(return_value=monitor_client))

    # Act
    exit_code = cli.main(["metrics"])

    # Assert
    assert exit_code == cli.EXIT_SUCCESS
    output = capsys.readouterr().out
    assert "vm-ops-01  Percentage CPU  92.0%  99.0%  WARN" in output
    assert "CPU average above 80% threshold" in output


def test_health_succeeds_when_dns_and_http_are_healthy(monkeypatch, capsys):
    monkeypatch.setattr(cli, "check_dns", lambda host: DnsResult(host=host, ip_address="20.0.0.1", error=None))
    monkeypatch.setattr(
        cli, "check_http", lambda url: HttpResult(url=url, status_code=200, elapsed_ms=38.4, error=None)
    )

    exit_code = cli.main(["health", "--host", "vm.example.com"])

    assert exit_code == cli.EXIT_SUCCESS
    output = capsys.readouterr().out
    assert "DNS   vm.example.com -> 20.0.0.1: OK" in output
    assert "HTTP  http://vm.example.com/healthz: OK (200, 38 ms)" in output


def test_health_fails_without_http_check_when_dns_fails(monkeypatch, capsys):
    monkeypatch.setattr(cli, "check_dns", lambda host: DnsResult(host=host, ip_address=None, error="not known"))
    check_http = Mock()
    monkeypatch.setattr(cli, "check_http", check_http)

    exit_code = cli.main(["health", "--host", "missing.example.com"])

    assert exit_code == cli.EXIT_FAILURE
    assert "DNS   missing.example.com: FAIL (not known)" in capsys.readouterr().out
    check_http.assert_not_called()


def test_health_fails_when_endpoint_does_not_return_200(monkeypatch, capsys):
    monkeypatch.setattr(cli, "check_dns", lambda host: DnsResult(host=host, ip_address=host, error=None))
    monkeypatch.setattr(
        cli, "check_http", lambda url: HttpResult(url=url, status_code=502, elapsed_ms=12.0, error=None)
    )

    exit_code = cli.main(["health", "--host", "20.0.0.1"])

    assert exit_code == cli.EXIT_FAILURE
    assert "HTTP  http://20.0.0.1/healthz: FAIL (status 502)" in capsys.readouterr().out


@pytest.mark.parametrize("host", ["", "http://20.0.0.1", "20.0.0.1/healthz", "20.0.0.1:80"])
def test_health_rejects_host_with_scheme_path_or_port(host):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["health", "--host", host])

    assert exit_info.value.code == 2
