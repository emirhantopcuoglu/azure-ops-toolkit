#!/usr/bin/env bash
# Lets GitHub Actions sign in to Azure through OIDC federation: GitHub presents a
# short-lived token for this repository and branch, so no client secret exists.
# The identity can only manage VMs in the project resource group.
# Requires an authenticated Azure CLI (az login) and GitHub CLI (gh auth login).
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-ops-toolkit}"
APP_NAME="${APP_NAME:-sp-opsctl-gha}"
GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-emirhantopcuoglu/azure-ops-toolkit}"
# Scheduled workflows only run on the repository's default branch
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
ROLE="Virtual Machine Contributor"
FEDERATED_CREDENTIAL_NAME="github-${GITHUB_BRANCH}"
GITHUB_OIDC_ISSUER="https://token.actions.githubusercontent.com"
AZURE_TOKEN_EXCHANGE_AUDIENCE="api://AzureADTokenExchange"

# Look up existing objects first so re-running the script does not create duplicates
APP_ID="$(az ad app list --display-name "${APP_NAME}" --query "[0].appId" --output tsv)"
if [[ -z "${APP_ID}" ]]; then
  echo "Creating app registration '${APP_NAME}'..."
  APP_ID="$(az ad app create --display-name "${APP_NAME}" --query appId --output tsv)"
fi

SP_OBJECT_ID="$(az ad sp list --filter "appId eq '${APP_ID}'" --query "[0].id" --output tsv)"
if [[ -z "${SP_OBJECT_ID}" ]]; then
  echo "Creating service principal..."
  SP_OBJECT_ID="$(az ad sp create --id "${APP_ID}" --query id --output tsv)"
fi

echo "Granting '${ROLE}' on resource group '${RESOURCE_GROUP}'..."
RESOURCE_GROUP_ID="$(az group show --name "${RESOURCE_GROUP}" --query id --output tsv)"
# Passing the object ID and principal type avoids waiting for directory replication.
# MSYS_NO_PATHCONV stops Git Bash rewriting the "/subscriptions/..." scope (no-op on Linux).
MSYS_NO_PATHCONV=1 az role assignment create \
  --assignee-object-id "${SP_OBJECT_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "${ROLE}" \
  --scope "${RESOURCE_GROUP_ID}" \
  --output none

# Ask GitHub for the exact subject prefix instead of assuming "repo:<owner>/<name>".
# Repositories using immutable subjects embed the owner and repository IDs
# ("repo:owner@123/name@456"), so a renamed or re-created repository cannot reuse the trust.
SUBJECT_PREFIX="$(gh api "repos/${GITHUB_REPOSITORY}/actions/oidc/customization/sub" --jq .sub_claim_prefix)"
FEDERATED_CREDENTIAL_JSON="{
  \"name\": \"${FEDERATED_CREDENTIAL_NAME}\",
  \"issuer\": \"${GITHUB_OIDC_ISSUER}\",
  \"subject\": \"${SUBJECT_PREFIX}:ref:refs/heads/${GITHUB_BRANCH}\",
  \"audiences\": [\"${AZURE_TOKEN_EXCHANGE_AUDIENCE}\"]
}"

echo "Trusting GitHub Actions tokens with subject '${SUBJECT_PREFIX}:ref:refs/heads/${GITHUB_BRANCH}'..."
if az ad app federated-credential show --id "${APP_ID}" \
  --federated-credential-id "${FEDERATED_CREDENTIAL_NAME}" --output none 2>/dev/null; then
  az ad app federated-credential update --id "${APP_ID}" \
    --federated-credential-id "${FEDERATED_CREDENTIAL_NAME}" --parameters "${FEDERATED_CREDENTIAL_JSON}" --output none
else
  az ad app federated-credential create --id "${APP_ID}" --parameters "${FEDERATED_CREDENTIAL_JSON}" --output none
fi

echo
echo "Done. Store these as GitHub repository secrets (they identify, they do not authenticate):"
echo "  AZURE_CLIENT_ID=${APP_ID}"
echo "  AZURE_TENANT_ID=$(az account show --query tenantId --output tsv)"
echo "  AZURE_SUBSCRIPTION_ID=$(az account show --query id --output tsv)"
