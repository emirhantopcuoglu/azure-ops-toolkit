#!/usr/bin/env bash
# Deletes everything the project created so ongoing cost drops to zero.
# provision.sh and setup-github-oidc.sh recreate the environment in a few minutes.
# Requires an authenticated Azure CLI (az login) and GitHub CLI (gh auth login).
# Usage: bash infra/teardown.sh [--yes]
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-ops-toolkit}"
APP_NAME="${APP_NAME:-sp-opsctl-gha}"
WORKFLOW_NAME="Nightly VM shutdown"

# Deletion cannot be undone, so require the resource group name unless --yes is passed
if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "This permanently deletes '${RESOURCE_GROUP}' and app '${APP_NAME}'. Type the resource group name to confirm: " CONFIRMATION
  if [[ "${CONFIRMATION}" != "${RESOURCE_GROUP}" ]]; then
    echo "Confirmation did not match; nothing was deleted."
    exit 1
  fi
fi

if [[ "$(az group exists --name "${RESOURCE_GROUP}")" == "true" ]]; then
  # Waits for completion (unlike --no-wait) so the script only reports success once
  # the billable resources are actually gone. Role assignments scoped to the group go with it.
  echo "Deleting resource group '${RESOURCE_GROUP}' (this takes several minutes)..."
  az group delete --name "${RESOURCE_GROUP}" --yes
else
  echo "Resource group '${RESOURCE_GROUP}' does not exist; skipping."
fi

APP_ID="$(az ad app list --display-name "${APP_NAME}" --query "[0].appId" --output tsv)"
if [[ -n "${APP_ID}" ]]; then
  # Deleting the app registration also removes its service principal and federated credential
  echo "Deleting app registration '${APP_NAME}'..."
  az ad app delete --id "${APP_ID}"
else
  echo "App registration '${APP_NAME}' does not exist; skipping."
fi

# Without its identity the scheduled workflow would fail every night
if [[ "$(gh workflow view "${WORKFLOW_NAME}" --json state --jq .state)" == "active" ]]; then
  echo "Disabling workflow '${WORKFLOW_NAME}'..."
  gh workflow disable "${WORKFLOW_NAME}"
fi

echo "Teardown complete."
