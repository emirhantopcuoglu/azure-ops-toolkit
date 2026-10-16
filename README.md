# azure-ops-toolkit

A small Azure infrastructure and a Python operations CLI (`opsctl`) that manages it.

The infrastructure is a single Ubuntu VM that configures itself on first boot: Docker runs a demo web container and Nginx sits in front of it as a reverse proxy. Everything is created by one script, so the environment can be torn down and rebuilt identically at any time.

## Architecture

```
Internet
   │  HTTP :80
   ▼
┌──────────────── Resource group: rg-ops-toolkit ────────────────┐
│  Network Security Group (allows 22/SSH, 80/HTTP)               │
│  ┌──────────────────── VM: vm-ops-01 (Ubuntu 22.04) ─────────┐ │
│  │  Nginx :80                                                │ │
│  │   ├── /healthz  →  200 "ok" (answered by Nginx itself)    │ │
│  │   └── /         →  proxy_pass 127.0.0.1:8080              │ │
│  │                       │                                   │ │
│  │                       ▼                                   │ │
│  │               Docker container "web" (nginxdemos/hello)   │ │
│  │                                                           │ │
│  │  System-assigned managed identity → Reader on the RG      │ │
│  └───────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

## Repository layout

```
infra/
  cloud-init.yaml   # First-boot configuration: Docker, Nginx, demo container
  provision.sh      # Creates the resource group, VM, firewall rule and identity
.env.example        # Environment variables the tooling expects
```

## Prerequisites

- An Azure subscription. A budget alert is strongly recommended (Cost Management → Budgets, e.g. 5 USD with alerts at 50/80/100%): a forgotten cloud resource keeps billing silently.
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli), logged in with `az login`
- Bash (Linux, macOS, or Git Bash on Windows)
- Python 3.11+

## Configuration

Copy `.env.example` to `.env` and fill in the values. `.env` is git-ignored and must never be committed.

| Variable | Purpose |
|---|---|
| `AZURE_SUBSCRIPTION_ID` | Subscription the tooling operates on (`az account show --query id -o tsv`) |
| `RESOURCE_GROUP` | Resource group holding all project resources (default `rg-ops-toolkit`) |
| `WEBHOOK_URL` | Discord/Slack webhook for notifications |

`provision.sh` reads its settings from environment variables with sensible defaults, so the same script works in a different region or size without editing it:

| Variable | Default |
|---|---|
| `RESOURCE_GROUP` | `rg-ops-toolkit` |
| `LOCATION` | `swedencentral` |
| `VM_NAME` | `vm-ops-01` |
| `VM_SIZE` | `Standard_B2ats_v2` |

## Provisioning

```bash
bash infra/provision.sh
# or override defaults:
LOCATION=uksouth VM_SIZE=Standard_B1s bash infra/provision.sh
```

The script runs with `set -euo pipefail`: it stops at the first failing command (`-e`), treats unset variables as errors (`-u`) and fails a pipeline if any command in it fails (`pipefail`). Without this, Bash would continue after a failed VM creation and produce a chain of confusing follow-up errors.

It performs these steps:

1. **Create the resource group** with `project` and `env` tags. A resource group is a container for related resources; deleting it deletes everything inside, which reduces cleanup to a single command. Tags are used for cost tracking and for selecting resources in automation.
2. **Create the VM** (Ubuntu 22.04 LTS) with SSH key authentication and the cloud-init file as custom data. The VM is tagged `env=dev auto-shutdown=true role=web`.
3. **Open port 80** by adding a rule to the VM's Network Security Group (Azure's firewall). SSH (22) is open by default on Linux VMs.
4. **Assign a managed identity** with the `Reader` role scoped to the resource group.
5. **Print the public IP** along with ready-to-use SSH and health check commands.

When it finishes the VM is running, but cloud-init needs a few more minutes to install packages. See [Verifying the deployment](#verifying-the-deployment).

## How it works

### cloud-init: configuration as code

[cloud-init](https://cloudinit.readthedocs.io/) ships with Ubuntu cloud images and runs **once, on the first boot**, applying the YAML passed as custom data. Instead of SSH-ing in and installing things by hand, the setup lives in version control: it is reviewable, repeatable and identical on every VM.

`infra/cloud-init.yaml`:

- `package_update` / `packages`: runs `apt update`, installs `docker.io` and `nginx`.
- `write_files`: writes the Nginx site configuration to disk.
- `runcmd`, executed in order:
  1. `systemctl enable --now docker`: start Docker now and on every boot.
  2. `usermod -aG docker azureuser`: allow the admin user to run Docker without `sudo`.
  3. `docker run -d --restart unless-stopped --name web -p 127.0.0.1:8080:80 nginxdemos/hello`: run the demo app in the background, restart it automatically after crashes or reboots.
  4. Copy the Nginx config into place.
  5. `nginx -t && systemctl reload nginx`: validate the configuration and reload only if it is valid, so a broken config never takes the server down.

### Reverse proxy and loopback binding

The container publishes its port as `127.0.0.1:8080`, not `8080`. Binding to the loopback interface means the container is reachable **only from inside the VM**; all external traffic has to go through Nginx. Nginx is the single public entry point, which is where TLS, rate limiting or access rules would be added later.

### Health endpoint

`/healthz` is answered by Nginx directly with `200 ok` and never reaches the container. It is a cheap liveness probe for monitoring.

The response type is set with `default_type text/plain;`. Using `add_header Content-Type text/plain` instead would send a second, conflicting `Content-Type` header next to the one Nginx already emits.

### Hiding the server version

`server_tokens off;` changes the `Server` response header from `nginx/1.18.0 (Ubuntu)` to `nginx`. Advertising exact versions helps an attacker look up known vulnerabilities.

### SSH key authentication

`--generate-ssh-keys` creates `~/.ssh/id_rsa` (private, stays on your machine) and `~/.ssh/id_rsa.pub` (copied to the VM) if they do not exist. Key-based login cannot be guessed or brute-forced like a password.

On the first connection SSH asks you to confirm the server's fingerprint and stores it in `~/.ssh/known_hosts`. If the fingerprint changes later, SSH warns you: someone may be impersonating the server (man-in-the-middle).

### Managed identity and least privilege

The VM gets a **system-assigned managed identity**: an Azure-managed identity tied to the VM's lifecycle. Code running on the VM can request short-lived tokens for Azure APIs without any password or key stored on disk, so there is nothing to leak, rotate or accidentally commit.

The identity is granted `Reader` only, and only on `rg-ops-toolkit`. This follows the **principle of least privilege**: the monitoring code only needs to read, so if the VM were compromised the attacker could neither change resources nor see anything outside this resource group.

## Verifying the deployment

From your machine:

```bash
curl -i http://<PUBLIC_IP>/healthz   # 200, Content-Type: text/plain, body "ok"
```

Opening `http://<PUBLIC_IP>` in a browser shows the demo page served by the container through Nginx.

On the VM (`ssh azureuser@<PUBLIC_IP>`):

```bash
cloud-init status --wait        # blocks until first-boot setup finishes; expect "status: done"
systemctl status nginx docker   # both should be "active (running)"
docker ps                       # "web" container with 127.0.0.1:8080->80/tcp
curl localhost/healthz          # ok
```

If cloud-init reports an error, the full log is in `/var/log/cloud-init-output.log`.

## Server health basics

Commands for a first look at a Linux server's resources, with observations from this VM (Standard_B2ats_v2, 1 GB RAM):

- **`df -h`**: disk usage per filesystem in human-readable units. The line to watch is `/` (root filesystem): 2.4 GB used out of 29 GB (9%) after installing Docker, Nginx and the demo image. `tmpfs` entries live in RAM and are cleared on reboot; they are not disk usage. A full root disk stops logging and crashes services.
- **`free -m`**: memory in MB. `total` is 891 rather than 1024 because the kernel reserves part of the memory at boot. `free` was only 116 but `available` was 437: Linux uses idle memory as disk cache (`buff/cache`) and releases it as soon as a process needs it, so `available` is the number that matters. There is no swap on Azure Ubuntu images by default; when memory runs out the kernel's OOM killer terminates the largest process.
- **`htop`**: live per-process CPU and memory usage, with per-core CPU bars at the top.
- **`sudo journalctl -u nginx`**: logs of the Nginx systemd unit. systemd collects the logs of every service in one place, queryable by unit.

## Region and VM size

Small, cheap VM sizes are in high demand and availability changes over time:

- `westeurope` rejected the deployment with `RequestDisallowedByAzure`: the region was not accepting new subscriptions.
- `Standard_B1s` failed with `SkuNotAvailable` (capacity restrictions) in several EU regions.

`az vm list-skus` only shows permanent restrictions, not current capacity. A reliable check that creates nothing is a preflight validation:

```bash
az vm create -g rg-ops-toolkit -n probe -l <region> --size <size> \
  --image Ubuntu2204 --admin-username azureuser \
  --ssh-key-values ~/.ssh/id_rsa.pub --validate
```

`Standard_B2ats_v2` (2 vCPU AMD, 1 GB RAM, burstable) in `swedencentral` passed, so it is the default. B-series sizes accumulate CPU credits while idle and spend them under load, which suits low-traffic workloads.

A resource group's location cannot be changed after creation. When switching regions, delete the (empty) group and run the script again.

## Running on Windows (Git Bash)

Git Bash converts arguments that start with `/` into Windows paths when calling Windows programs such as `az`. An Azure resource ID like `/subscriptions/...` would become `C:/Program Files/Git/subscriptions/...`. `provision.sh` disables this conversion with `MSYS_NO_PATHCONV=1` only for the role assignment, because the cloud-init file path *does* need converting. On Linux the variable has no effect.

In PowerShell, `bash` may resolve to WSL rather than Git Bash; WSL does not see the Windows Azure CLI installation.

## Cost control

Stop the VM when not in use:

```bash
az vm deallocate -g rg-ops-toolkit -n vm-ops-01   # releases the hardware; compute billing stops
az vm start      -g rg-ops-toolkit -n vm-ops-01
```

`az vm stop` only shuts down the OS: the hardware stays reserved and **is still billed**. Use `deallocate`. The disk and public IP keep incurring small charges while deallocated.

## Cleanup

Delete everything the project created:

```bash
az group delete -n rg-ops-toolkit --yes
```
