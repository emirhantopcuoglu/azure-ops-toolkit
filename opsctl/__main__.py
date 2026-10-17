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
from azure.mgmt.resource.resources import ResourceManagementClient
from dotenv import load_dotenv

from opsctl.config import Config, ConfigError, load_config
from opsctl.inventory import REPORT_SERIALIZERS, format_table, list_resources, save_report

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
REPORTS_DIR = Path("reports")


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

    inventory_parser = subcommands.add_parser("inventory", help="list resources in the resource group")
    inventory_parser.add_argument(
        "--output",
        choices=sorted(REPORT_SERIALIZERS),
        help=f"also save the report to {REPORTS_DIR}/ in this format",
    )
    inventory_parser.set_defaults(handler=_run_inventory)

    return parser


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


def _print_error(message: str) -> None:
    print(f"opsctl: error: {message}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
