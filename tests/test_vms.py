from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from opsctl.vms import (
    UNKNOWN_POWER_STATE,
    PowerAction,
    VmState,
    apply_power_action,
    format_status_table,
    list_vm_states,
    needs_power_action,
    select_vms_by_tag,
)


def _azure_vm(name, tags=None):
    return SimpleNamespace(name=name, tags=tags)


def _instance_view(*status_codes):
    return SimpleNamespace(statuses=[SimpleNamespace(code=code) for code in status_codes])


def _compute_client(vms, instance_views_by_name):
    client = Mock()
    client.virtual_machines.list.return_value = vms
    client.virtual_machines.instance_view.side_effect = (
        lambda resource_group, vm_name: instance_views_by_name[vm_name]
    )
    return client


def test_list_vm_states_reads_power_state_for_each_vm_sorted_by_name():
    # Arrange
    client = _compute_client(
        vms=[_azure_vm("vm-b"), _azure_vm("vm-a", tags={"role": "web"})],
        instance_views_by_name={
            "vm-a": _instance_view("ProvisioningState/succeeded", "PowerState/running"),
            "vm-b": _instance_view("ProvisioningState/succeeded", "PowerState/deallocated"),
        },
    )

    # Act
    states = list_vm_states(client, "rg-test")

    # Assert
    client.virtual_machines.list.assert_called_once_with("rg-test")
    assert states == [
        VmState(name="vm-a", power_state="running", tags={"role": "web"}),
        VmState(name="vm-b", power_state="deallocated", tags={}),
    ]


def test_list_vm_states_reports_unknown_when_power_state_is_missing():
    client = _compute_client(
        vms=[_azure_vm("vm-new")],
        instance_views_by_name={"vm-new": _instance_view("ProvisioningState/creating")},
    )

    states = list_vm_states(client, "rg-test")

    assert states[0].power_state == UNKNOWN_POWER_STATE


def test_format_status_table_shows_name_power_state_and_tags():
    states = [VmState(name="vm-ops-01", power_state="running", tags={"role": "web", "env": "dev"})]

    assert format_status_table(states).splitlines() == [
        "NAME       POWER STATE  TAGS",
        "vm-ops-01  running      env=dev;role=web",
    ]


def test_select_vms_by_tag_matches_key_and_value():
    tagged = VmState(name="vm-a", power_state="running", tags={"auto-shutdown": "true"})
    other_value = VmState(name="vm-b", power_state="running", tags={"auto-shutdown": "false"})
    untagged = VmState(name="vm-c", power_state="running", tags={})

    selected = select_vms_by_tag([tagged, other_value, untagged], "auto-shutdown", "true")

    assert selected == [tagged]


@pytest.mark.parametrize(
    ("power_state", "action", "expected"),
    [
        ("running", PowerAction.START, False),
        ("deallocated", PowerAction.START, True),
        ("stopped", PowerAction.START, True),
        ("deallocated", PowerAction.DEALLOCATE, False),
        ("running", PowerAction.DEALLOCATE, True),
        # A powered-off VM is still billed, so it must still be deallocated
        ("stopped", PowerAction.DEALLOCATE, True),
    ],
)
def test_needs_power_action_compares_current_and_target_state(power_state, action, expected):
    state = VmState(name="vm-a", power_state=power_state, tags={})

    assert needs_power_action(state, action) is expected


def test_apply_power_action_starts_every_operation_before_waiting_on_any():
    # Arrange: record the order of begin_* and result() calls in one shared log
    calls = []
    client = Mock()

    def begin_start(resource_group, vm_name):
        calls.append(f"begin {vm_name}")
        return Mock(result=lambda: calls.append(f"wait {vm_name}"))

    client.virtual_machines.begin_start.side_effect = begin_start

    # Act
    apply_power_action(client, "rg-test", ["vm-a", "vm-b"], PowerAction.START)

    # Assert
    assert calls == ["begin vm-a", "begin vm-b", "wait vm-a", "wait vm-b"]


def test_apply_power_action_deallocates_instead_of_powering_off():
    client = Mock()

    apply_power_action(client, "rg-test", ["vm-a"], PowerAction.DEALLOCATE)

    client.virtual_machines.begin_deallocate.assert_called_once_with("rg-test", "vm-a")
    client.virtual_machines.begin_power_off.assert_not_called()
