"""Command-line entry point: python -m opsctl <command>."""

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from azure.core.credentials import TokenCredential
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.resource.resources import ResourceManagementClient
from dotenv import load_dotenv

from opsctl.config import Config, ConfigError, load_config
from opsctl.inventory import REPORT_SERIALIZERS, format_table, list_resources, save_report
from opsctl.metrics import MetricStatus, evaluate, fetch_vm_metrics, format_metrics_table
from opsctl.vms import (
    PowerAction,
    apply_power_action,
    format_status_table,
    list_vm_states,
    needs_power_action,
    select_vms_by_tag,
)

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
REPORTS_DIR = Path("reports")
PROGRESS_MESSAGES = {
    PowerAction.START: "Starting",
    PowerAction.DEALLOCATE: "Deallocating",
}


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    load_dotenv()
    try:
        config = load_config(os.environ)
        with DefaultAzureCredential() as credential:
            args.handler(args, config, credential)
    except ConfigError as error:
        _print_error(f"configuration error: {error}")
        return EXIT_FAILURE
    # ClientAuthenticationError subclasses HttpResponseError, so it must be caught first
    except ClientAuthenticationError as error:
        _print_error(
            "could not authenticate to Azure. Run `az login` locally; on a VM or in CI, "
            f"check the managed identity or service principal.\n{error.message}"
        )
        return EXIT_FAILURE
    except HttpResponseError as error:
        _print_error(f"Azure request failed: {error.message}")
        return EXIT_FAILURE
    return EXIT_SUCCESS


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opsctl",
        description="Operations toolkit for the azure-ops-toolkit environment.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    _add_inventory_command(subcommands)
    _add_vm_commands(subcommands)
    _add_metrics_command(subcommands)
    return parser


def _add_metrics_command(subcommands: argparse._SubParsersAction) -> None:
    metrics_parser = subcommands.add_parser(
        "metrics", help="show last-hour CPU, network and disk metrics with a CPU threshold check"
    )
    metrics_parser.set_defaults(handler=_run_metrics)


def _add_inventory_command(subcommands: argparse._SubParsersAction) -> None:
    inventory_parser = subcommands.add_parser("inventory", help="list resources in the resource group")
    inventory_parser.add_argument(
        "--output",
        choices=sorted(REPORT_SERIALIZERS),
        help=f"also save the report to {REPORTS_DIR}/ in this format",
    )
    inventory_parser.set_defaults(handler=_run_inventory)


def _add_vm_commands(subcommands: argparse._SubParsersAction) -> None:
    vm_parser = subcommands.add_parser("vm", help="inspect and control virtual machines")
    vm_subcommands = vm_parser.add_subparsers(dest="vm_command", required=True)

    status_parser = vm_subcommands.add_parser("status", help="show the power state of each VM")
    status_parser.set_defaults(handler=_run_vm_status)

    power_commands = (
        ("start", PowerAction.START, "start VMs that have the given tag"),
        ("stop", PowerAction.DEALLOCATE, "deallocate VMs that have the given tag (stops compute billing)"),
    )
    for command_name, power_action, help_text in power_commands:
        power_parser = vm_subcommands.add_parser(command_name, help=help_text)
        # Required on purpose: acting on every VM must never be the default
        power_parser.add_argument(
            "--tag", required=True, type=_parse_tag, metavar="KEY=VALUE", help="only act on VMs with this tag"
        )
        power_parser.add_argument(
            "--dry-run", action="store_true", help="print what would change without changing anything"
        )
        power_parser.set_defaults(handler=_run_vm_power_action, power_action=power_action)


def _parse_tag(text: str) -> tuple[str, str]:
    key, separator, value = text.partition("=")
    if not separator or not key.strip() or not value.strip():
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    return key.strip(), value.strip()


def _run_inventory(args: argparse.Namespace, config: Config, credential: TokenCredential) -> None:
    with ResourceManagementClient(credential, config.subscription_id) as client:
        records = list_resources(client, config.resource_group)

    if not records:
        print(f"No resources found in {config.resource_group}.")
        return

    print(format_table(records))
    if args.output:
        content = REPORT_SERIALIZERS[args.output](records)
        report_path = save_report(content, args.output, REPORTS_DIR, datetime.now(timezone.utc))
        print(f"\nSaved {args.output.upper()} report to {report_path}")


def _run_vm_status(args: argparse.Namespace, config: Config, credential: TokenCredential) -> None:
    with ComputeManagementClient(credential, config.subscription_id) as client:
        states = list_vm_states(client, config.resource_group)

    if not states:
        print(f"No virtual machines found in {config.resource_group}.")
        return

    print(format_status_table(states))


def _run_vm_power_action(args: argparse.Namespace, config: Config, credential: TokenCredential) -> None:
    action: PowerAction = args.power_action
    tag_key, tag_value = args.tag
    with ComputeManagementClient(credential, config.subscription_id) as client:
        states = select_vms_by_tag(list_vm_states(client, config.resource_group), tag_key, tag_value)
        if not states:
            print(f"No VMs tagged {tag_key}={tag_value} in {config.resource_group}.")
            return

        pending_states = [state for state in states if needs_power_action(state, action)]
        for state in states:
            if not needs_power_action(state, action):
                print(f"{state.name}: already {state.power_state}, skipping")

        if args.dry_run:
            for state in pending_states:
                print(f"[dry-run] would {action.value} {state.name} (currently {state.power_state})")
            return

        if pending_states:
            vm_names = [state.name for state in pending_states]
            print(f"{PROGRESS_MESSAGES[action]} {', '.join(vm_names)}...")
            apply_power_action(client, config.resource_group, vm_names, action)
            print("Done.")


def _run_metrics(args: argparse.Namespace, config: Config, credential: TokenCredential) -> None:
    with (
        ComputeManagementClient(credential, config.subscription_id) as compute_client,
        MonitorManagementClient(credential, config.subscription_id) as monitor_client,
    ):
        metrics_by_vm = fetch_vm_metrics(
            compute_client, monitor_client, config.resource_group, datetime.now(timezone.utc)
        )

    if not metrics_by_vm:
        print(f"No virtual machines found in {config.resource_group}.")
        return

    print(format_metrics_table(metrics_by_vm, config.cpu_threshold_percent))
    statuses = {
        evaluate(summary, config.cpu_threshold_percent)
        for summaries in metrics_by_vm.values()
        for summary in summaries
    }
    if MetricStatus.WARN in statuses:
        print(f"\nCPU average above {config.cpu_threshold_percent:g}% threshold.")
    if MetricStatus.NO_DATA in statuses:
        print("\nSome metrics have no data yet; a VM that just started needs a few minutes.")


def _print_error(message: str) -> None:
    print(f"opsctl: error: {message}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
