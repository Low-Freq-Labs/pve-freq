# Configuration Reference — PVE FREQ

All configuration lives in `/opt/pve-freq/conf/` (or `./conf/` in dev). FREQ uses TOML format for all config files.

Run `freq init` to generate config files from templates, or copy the `.example` files from `conf/` and remove the `.example` suffix.

---

## freq.toml — Main Configuration

The primary config file. Controls cluster settings, SSH, VM defaults, safety rules, and services.

### [freq] — General

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `version` | string | — | FREQ version identifier |
| `brand` | string | `"PVE FREQ"` | Display branding name |
| `build` | string | `"default"` | Personality pack: `"default"` or `"personal"` |
| `ascii` | bool | `false` | ASCII box drawing mode (PuTTY-safe) |
| `debug` | bool | `false` | Enable debug logging |

### [ssh] — SSH Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `service_account` | string | `"freq-admin"` | SSH user for fleet operations |
| `connect_timeout` | int | `5` | Connection timeout in seconds |
| `max_parallel` | int | `5` | Maximum parallel SSH connections |
| `mode` | string | `"sudo"` | Auth mode: `"root"` or `"sudo"` |
| `legacy_password_file` | string | `""` | Path to password file for iDRAC/switch auth |

### [pve] — Proxmox VE

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `nodes` | list | `[]` | Proxmox node IP addresses |
| `node_names` | list | `[]` | Proxmox node hostnames |
| `ssh_user` | string | `"freq-admin"` | SSH user for PVE operations (legacy) |
| `api_token_id` | string | `""` | PVE API token ID (e.g. `"freq@pve!dashboard"`) |
| `api_token_secret_path` | string | `""` | Path to file containing PVE API token secret |
| `api_verify_ssl` | bool | `false` | Verify SSL for PVE API (false for self-signed certs) |

#### [pve.storage.\<node\>] — Per-Node Storage

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `pool` | string | `""` | Storage pool name (e.g. `"local-lvm"`) |
| `type` | string | `""` | Storage type (e.g. `"SSD"`, `"HDD"`) |

### [vm.defaults] — VM Defaults

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cores` | int | `2` | Default CPU cores |
| `ram` | int | `2048` | Default RAM in MB |
| `disk` | int | `32` | Default disk size in GB |
| `cpu` | string | `"x86-64-v2-AES"` | CPU type/emulation |
| `machine` | string | `"q35"` | Machine type |
| `scsihw` | string | `"virtio-scsi-single"` | SCSI hardware controller |
| `gateway` | string | `""` | Default gateway IP (**required**) |
| `nameserver` | string | `"1.1.1.1"` | Default DNS nameserver |

### [safety] — Safety Rules

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `protected_vmids` | list | `[]` | VM IDs that cannot be destroyed |
| `protected_ranges` | list | `[[900, 999]]` | VM ID ranges protected from deletion |
| `max_failure_percent` | int | `50` | Max host failure percentage before abort |

### [infrastructure] — Infrastructure

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `cluster_name` | string | `""` | Proxmox cluster name |
| `timezone` | string | `"UTC"` | System timezone (IANA format) |
| `truenas_ip` | string | `""` | TrueNAS IP address |
| `pfsense_ip` | string | `""` | pfSense IP address |
| `switch_ip` | string | `""` | Network switch IP address |
| `docker_dev_ip` | string | `""` | Docker dev host IP |
| `docker_config_base` | string | `""` | Base path for Docker container configs |
| `docker_backup_dir` | string | `""` | Path for Docker container backups |

### [templates.profiles] — VM Profiles

Named presets for `freq vm create --profile <name>`:

| Profile | Cores | RAM | Disk |
|---------|-------|-----|------|
| `minimal` | 1 | 1024 MB | 8 GB |
| `standard` | 2 | 2048 MB | 32 GB |
| `dev` | 4 | 4096 MB | 64 GB |
| `prod` | 4 | 8192 MB | 128 GB |
| `docker` | 4 | 4096 MB | 64 GB |

### [nic] — Network Interface Defaults

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bridge` | string | `"vmbr0"` | Default bridge interface |
| `mtu` | int | `1500` | Default MTU |

#### [nic.profiles.\<name\>]

Named NIC profiles mapping to VLAN ID lists:

```toml
[nic.profiles]
standard = [100, 200]
public = [100, 200, 300]
minimal = [100]
```

### [pfsense] — pfSense (optional)

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `host` | string | `""` | pfSense hostname/IP |
| `user` | string | `"freq-admin"` | pfSense SSH user |
| `config_path` | string | `"/cf/conf/config.xml"` | pfSense config file path |

### [services] — Service Ports

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `dashboard_port` | int | `8888` | HTTP port for dashboard |
| `watchdog_port` | int | `9900` | Watchdog service port |
| `agent_port` | int | `9990` | Agent service port |

### [notifications] — Notification Channels

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `discord_webhook` | string | `""` | Discord webhook URL |
| `slack_webhook` | string | `""` | Slack webhook URL |
| `telegram_bot_token` | string | `""` | Telegram bot token |
| `telegram_chat_id` | string | `""` | Telegram chat ID |
| `smtp_host` | string | `""` | SMTP server hostname |
| `smtp_port` | int | `587` | SMTP server port |
| `smtp_user` | string | `""` | SMTP user |
| `smtp_password` | string | `""` | SMTP password |
| `smtp_to` | string | `""` | Email recipient |
| `smtp_tls` | bool | `true` | Enable TLS |
| `ntfy_url` | string | `""` | ntfy.sh server URL |
| `ntfy_topic` | string | `""` | ntfy.sh topic |
| `gotify_url` | string | `""` | Gotify server URL |
| `gotify_token` | string | `""` | Gotify app token |
| `pushover_user` | string | `""` | Pushover user key |
| `pushover_token` | string | `""` | Pushover app token |
| `webhook_url` | string | `""` | Generic webhook URL |

### [users.\<username\>] — Inline Users (optional)

Users can be defined inline instead of in a separate file:

```toml
[users.freq-admin]
role = "admin"
groups = ""

[users.operator1]
role = "operator"
groups = "fleet"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `role` | string | `"viewer"` | Role: `"admin"`, `"operator"`, or `"viewer"` |
| `groups` | string | `""` | Comma-separated group memberships |

---

## hosts.toml — Fleet Host Registry

Defines all hosts managed by FREQ.

### TOML Format

```toml
[[host]]
ip = "192.168.1.10"
label = "node1"
type = "pve"
groups = "prod,cluster"
all_ips = ["192.168.1.10", "10.0.1.10"]

[[host]]
ip = "192.168.1.20"
label = "nas"
type = "truenas"
groups = "prod,storage"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ip` | string | — | Primary IP address |
| `label` | string | — | Hostname/label |
| `type` | string | `"linux"` | Host type: `linux`, `pve`, `truenas`, `pfsense`, `idrac`, `switch`, `docker` |
| `groups` | string | `""` | Comma-separated group memberships |
| `all_ips` | list | `[]` | All IPv4 addresses (multi-NIC hosts) |

### Legacy Format (hosts.conf)

```
# IP            LABEL       TYPE        GROUPS
192.168.1.10    node1       pve         prod,cluster
192.168.1.20    nas         truenas     prod,storage
```

FREQ reads `hosts.toml` first. If not found, falls back to `hosts.conf`.

---

## vlans.toml — VLAN Definitions

```toml
[vlan.mgmt]
id = 100
name = "Management"
subnet = "192.168.10.0/24"
prefix = "192.168.10"
gateway = "192.168.10.1"

[vlan.storage]
id = 30
name = "Storage"
subnet = "192.168.30.0/24"
prefix = "192.168.30"
# No gateway — storage-only VLAN
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `id` | int | `0` | VLAN ID (0 = untagged) |
| `name` | string | `""` | Human-readable name |
| `subnet` | string | `""` | CIDR subnet |
| `prefix` | string | `""` | IP prefix |
| `gateway` | string | `""` | Gateway IP (omit for isolated VLANs) |

---

## distros.toml — Cloud Image Catalog

Pre-populated with 10+ distributions. Used by `freq vm import` and `freq vm create --image`.

```toml
[distro.ubuntu-2404]
name = "Ubuntu 24.04 LTS Noble"
url = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
filename = "ubuntu-24.04-cloud.img"
sha_url = "https://cloud-images.ubuntu.com/noble/current/SHA256SUMS"
family = "debian"
tier = "priority"
aliases = ["ubuntu"]
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | — | Display name |
| `url` | string | — | Download URL for cloud image |
| `filename` | string | — | Local cached filename |
| `sha_url` | string | `""` | URL to SHA256 checksums |
| `family` | string | — | OS family: `debian`, `rhel`, `arch`, `suse` |
| `tier` | string | `"supported"` | Support tier: `priority`, `supported`, `rolling` |
| `aliases` | list | `[]` | Alternative names |

---

## containers.toml — Docker Container Registry

Tracks Docker containers across VMs for monitoring and management.

```toml
[vm.200]
ip = "192.168.1.50"
label = "app-server"
compose_path = "/opt/configs"

[vm.200.containers.nginx]
compose = "web/docker-compose.yml"
port = 80
critical = true

[vm.200.containers.postgres]
compose = "db/docker-compose.yml"
port = 5432
vault_key = "postgres_password"
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `ip` | string | — | VM IP address |
| `label` | string | — | VM label |
| `compose_path` | string | — | Base path for compose files |
| `compose` | string | — | Relative path to docker-compose.yml |
| `port` | int | `0` | Container port for monitoring |
| `api_path` | string | `""` | Health check endpoint |
| `auth_type` | string | `""` | Auth type: `bearer`, `api_key` |
| `auth_header` | string | `""` | Authorization header name |
| `vault_key` | string | `""` | Vault key for auth secrets |
| `critical` | bool | `false` | Affects risk assessment when down |

---

## fleet-boundaries.toml — Permission Tiers

Defines what operations are allowed on which VMs.

```toml
[tiers]
probe    = ["view"]
operator = ["view", "start", "stop", "restart", "snapshot", "destroy", "clone", "resize", "migrate", "configure"]
admin    = ["view", "start", "stop", "restart", "snapshot", "destroy", "clone", "resize", "migrate", "configure"]

[categories.production]
description = "Production workloads"
tier = "operator"
vmids = [200, 201, 202]

[categories.lab]
description = "Lab/dev playground"
tier = "admin"
range_start = 5000
range_end = 5099
```

### Tiers

Valid actions: `view`, `start`, `stop`, `restart`, `snapshot`, `destroy`, `clone`, `resize`, `migrate`, `configure`

### Categories

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `description` | string | `""` | Category description |
| `tier` | string | `"probe"` | Access tier |
| `vmids` | list | `[]` | Specific VM IDs |
| `range_start` | int | — | Start of VM ID range |
| `range_end` | int | — | End of VM ID range |

### Physical Devices

```toml
[physical.firewall]
ip = "192.168.1.1"
label = "firewall"
type = "pfsense"
tier = "probe"
detail = "Gateway"
```

### PVE Nodes

```toml
[pve_nodes.node1]
ip = "192.168.1.10"
detail = "Proxmox Node 1"
```

---

## rules.toml — Alert Rules

```toml
[rule."host-unreachable"]
condition = "host_unreachable"
target = "*"
threshold = 0
duration = 300
severity = "critical"
cooldown = 600
enabled = true
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `condition` | string | — | Condition: `host_unreachable`, `disk_above`, `ram_above`, `cpu_above`, `docker_down` |
| `target` | string | `"*"` | Target hosts: `*` = all, or host label/pattern |
| `threshold` | int/float | `0` | Threshold value (percentage or count) |
| `duration` | int | `0` | Seconds condition must persist before alerting |
| `severity` | string | `"warning"` | Alert severity: `critical`, `warning`, `info` |
| `cooldown` | int | `600` | Seconds between re-alerts |
| `enabled` | bool | `true` | Enable this rule |

---

## risk.toml — Infrastructure Risk Map

```toml
[target.firewall]
label = "Firewall/Gateway"
risk = "CRITICAL"
impact = ["ALL remote management access lost", "ALL inter-VLAN routing stops"]
recovery = "Physical console access required."
depends_on = []
depended_by = ["all hosts", "all VMs"]
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `label` | string | — | Component name |
| `risk` | string | — | Risk level: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` |
| `impact` | list | `[]` | Consequences if component fails |
| `recovery` | string | `""` | Recovery instructions |
| `depends_on` | list | `[]` | What this component needs |
| `depended_by` | list | `[]` | What breaks when this fails |

---

## Playbooks — Automated Recovery

Stored in `conf/playbooks/`. Each file defines a recovery procedure.

```toml
[playbook]
name = "Host Recovery"
description = "Verify and recover an unresponsive host"
trigger = "host_unreachable"

[[step]]
name = "Ping check"
type = "check"
command = "echo pong"
target = "docker-media"
expect = "pong"
timeout = 10

[[step]]
name = "Restart critical services"
type = "action"
command = "systemctl restart docker"
target = "docker-media"
confirm = true
timeout = 60
```

### Step Fields

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `name` | string | — | Step name |
| `type` | string | — | `"check"` (verify) or `"action"` (execute) |
| `command` | string | — | Shell command to run |
| `target` | string | — | Target host label |
| `expect` | string | `""` | Expected output (check steps) |
| `confirm` | bool | `false` | Require confirmation (action steps) |
| `timeout` | int | `30` | Command timeout in seconds |

---

## Personality Packs

Stored in `conf/personality/`. Two built-in packs:

- **default.toml** — Professional, no theming
- **personal.toml** — Bass/dubstep themed with vibes

Select with `build = "personal"` in `[freq]` section of `freq.toml`.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `subtitle` | string | `""` | Subtitle under main heading |
| `vibe_enabled` | bool | `false` | Enable random vibe drops |
| `vibe_probability` | int | `47` | 1/N chance per command |
| `dashboard_header` | string | `""` | Dashboard page header |
| `celebrations` | list | `[]` | Success messages |
| `taglines` | list | `[]` | Splash screen taglines |
| `quotes` | list | `[]` | MOTD quotes |

---

## Plugins

Drop `.py` files in `conf/plugins/` to add custom commands.

Each plugin must define:

```python
NAME = "my-command"
DESCRIPTION = "What it does"

def run(cfg, pack, args):
    """Entry point. Return 0 for success."""
    return 0
```

Plugins are auto-discovered at startup and appear in `freq help` and the TUI menu.

---

## File Summary

| File | Purpose |
|------|---------|
| `freq.toml` | Main config — cluster, SSH, VMs, safety, services |
| `hosts.toml` | Fleet host registry |
| `vlans.toml` | VLAN definitions |
| `distros.toml` | Cloud image catalog |
| `containers.toml` | Docker container registry |
| `fleet-boundaries.toml` | Permission tiers and VM categories |
| `risk.toml` | Infrastructure dependency/risk map |
| `rules.toml` | Alert rules |
| `playbooks/*.toml` | Recovery playbooks |
| `personality/*.toml` | Personality packs |
| `plugins/*.py` | Custom command plugins |
