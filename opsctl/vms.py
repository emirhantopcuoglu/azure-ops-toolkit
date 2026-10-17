"""Virtual machine power management."""

from collections.abc import Iterable
from dataclasses import dataclass

from azure.mgmt.compute import ComputeManagementClient

from opsctl.formatting import format_tags, render_table

POWER_STATE_PREFIX = "PowerState/"
UNKNOWN_POWER_STATE = "unknown"
STATUS_TABLE_HEADERS = ("NAME", "POWER STATE", "TAGS")


@dataclass(frozen=True)
class VmState:
    name: str
    power_state: str
    tags: dict[str, str]


def list_vm_states(client: ComputeManagementClient, resource_group: str) -> list[VmState]:
    """Return the power state of every VM in the group, sorted by name.

    This makes one instance_view request per VM (an N+1 pattern). The single-request
    alternatives either require a $filter we cannot express (list with expand) or scan
    the whole subscription (list_all with status_only), which needs wider permissions
    than the Reader role scoped to this resource group. N is a handful of VMs here.
    """
    states = [
        VmState(
            name=vm.name,
            power_state=_read_power_state(
                client.virtual_machines.instance_view(resource_group, vm.name).statuses
            ),
            tags=dict(vm.tags or {}),
        )
        for vm in client.virtual_machines.list(resource_group)
    ]
    return sorted(states, key=lambda state: state.name)


def format_status_table(states: list[VmState]) -> str:
    rows = [(state.name, state.power_state, format_tags(state.tags)) for state in states]
    return render_table(STATUS_TABLE_HEADERS, rows)


def _read_power_state(statuses: Iterable | None) -> str:
    # Statuses mix codes such as "ProvisioningState/succeeded" and "PowerState/running";
    # the power state can be absent while a VM is still being created.
    for status in statuses or []:
        if status.code and status.code.startswith(POWER_STATE_PREFIX):
            return status.code.removeprefix(POWER_STATE_PREFIX)
    return UNKNOWN_POWER_STATE
