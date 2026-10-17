#!/usr/bin/env bash
# Creates the resource group and an Ubuntu VM that configures itself via cloud-init.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-ops-toolkit}"
# Capacity varies by region; dry-run with `az vm create ... --validate` before changing these
LOCATION="${LOCATION:-swedencentral}"
VM_NAME="${VM_NAME:-vm-ops-01}"
VM_SIZE="${VM_SIZE:-Standard_B2ats_v2}"
VM_IMAGE="Ubuntu2204"
ADMIN_USERNAME="azureuser"
HTTP_PORT=80

# Resolve paths relative to this script so it works from any working directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_INIT_FILE="${SCRIPT_DIR}/cloud-init.yaml"

echo "Creating resource group '${RESOURCE_GROUP}' in '${LOCATION}'..."
az group create \
  --name "${RESOURCE_GROUP}" \
  --location "${LOCATION}" \
  --tags project=azure-ops-toolkit env=dev \
  --output none

# New subscriptions do not have Azure Monitor registered; without it metric queries
# fail with a misleading "resource mapping not found" error. No-op if already registered.
echo "Registering the Microsoft.Insights resource provider (Azure Monitor)..."
az provider register --namespace Microsoft.Insights --wait

echo "Creating VM '${VM_NAME}' (${VM_SIZE})..."
az vm create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VM_NAME}" \
  --location "${LOCATION}" \
  --image "${VM_IMAGE}" \
  --size "${VM_SIZE}" \
  --admin-username "${ADMIN_USERNAME}" \
  --generate-ssh-keys \
  --custom-data "${CLOUD_INIT_FILE}" \
  --tags env=dev auto-shutdown=true role=web \
  --output none

echo "Opening port ${HTTP_PORT} on the network security group..."
az vm open-port \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VM_NAME}" \
  --port "${HTTP_PORT}" \
  --output none

echo "Assigning a managed identity with Reader access on the resource group..."
RESOURCE_GROUP_ID="$(az group show --name "${RESOURCE_GROUP}" --query id --output tsv)"
# Git Bash on Windows rewrites arguments starting with "/" into file paths, which corrupts
# the "/subscriptions/..." scope. Disabling the conversion is a no-op on Linux.
MSYS_NO_PATHCONV=1 az vm identity assign \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VM_NAME}" \
  --role Reader \
  --scope "${RESOURCE_GROUP_ID}" \
  --output none

PUBLIC_IP="$(az vm show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${VM_NAME}" \
  --show-details \
  --query publicIps \
  --output tsv)"

echo "Done. Public IP: ${PUBLIC_IP}"
echo "SSH:    ssh ${ADMIN_USERNAME}@${PUBLIC_IP}"
echo "Health: curl http://${PUBLIC_IP}/healthz"
