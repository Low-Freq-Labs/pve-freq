# CLI Reference — PVE FREQ

All 88 commands, grouped by category. Run `freq help` for a summary or `freq <command> --help` for detailed usage.

---

## Utilities

| Command | Description |
|---------|-------------|
| `freq version` | Show version and branding |
| `freq help` | Show all commands by category |
| `freq doctor` | 15-point self-diagnostic |
| `freq why` | Explain VM permissions and protections |
| `freq test-connection` | Test host connectivity (TCP + SSH + sudo) |
| `freq menu` | Launch interactive TUI menu |
| `freq demo` | Interactive demo — no fleet required |

## Fleet Operations

| Command | Description |
|---------|-------------|
| `freq status` | Fleet health summary |
| `freq dashboard` | Fleet dashboard overview |
| `freq exec` | Run command across fleet hosts in parallel |
| `freq info` | System info for a host |
| `freq detail` | Deep host inventory (CPU, RAM, disk, NICs, services) |
| `freq boundaries` | Fleet boundary tiers and VM categories |
| `freq diagnose` | Deep diagnostic for a host |
| `freq ssh` | SSH to a fleet host |
| `freq docker` | Container discovery and management |
| `freq log` | View logs for a host |

## Host Management

| Command | Description |
|---------|-------------|
| `freq hosts` | List and manage fleet hosts |
| `freq keys` | SSH key management |
| `freq discover` | Discover hosts on the network |
| `freq groups` | Manage host groups |
| `freq bootstrap` | Bootstrap a new host (install deps, push keys) |
| `freq onboard` | Onboard a host to the fleet |

## VM Management

| Command | Description |
|---------|-------------|
| `freq list` | List VMs across PVE cluster |
| `freq create` | Create a new VM |
| `freq clone` | Clone a VM with optional network config |
| `freq destroy` | Destroy a VM (respects safety rules) |
| `freq resize` | Resize VM resources (CPU, RAM, disk) |
| `freq snapshot` | Snapshot management (create/list/delete) |
| `freq power` | VM power control (start/stop/reboot/shutdown/status) |
| `freq nic` | VM NIC management (add/clear/change-ip/change-id/check-ip) |
| `freq import` | Import a cloud image as a VM template |
| `freq migrate` | Migrate a VM between PVE nodes |
| `freq template` | Convert a VM to a template |
| `freq rename` | Rename a VM |
| `freq add-disk` | Add disk(s) to a VM |
| `freq tag` | Set/view PVE tags on a VM |
| `freq pool` | PVE pool management |
| `freq sandbox` | Spawn a VM from template |
| `freq file` | Send files to fleet hosts |

## Proxmox

| Command | Description |
|---------|-------------|
| `freq vm-overview` | VM inventory across cluster |
| `freq vmconfig` | View/edit VM configuration |
| `freq rescue` | Rescue a stuck VM |

## User Management

| Command | Description |
|---------|-------------|
| `freq users` | List users |
| `freq new-user` | Create a new user |
| `freq passwd` | Change user password |
| `freq roles` | View role assignments |
| `freq promote` | Promote user to higher role |
| `freq demote` | Demote user to lower role |
| `freq install-user` | Install user across fleet hosts |

## Security

| Command | Description |
|---------|-------------|
| `freq vault` | Encrypted credential store (AES-256) |
| `freq audit` | Security audit |
| `freq harden` | Apply security hardening |

## Infrastructure

| Command | Description |
|---------|-------------|
| `freq pfsense` | pfSense management |
| `freq truenas` | TrueNAS management |
| `freq zfs` | ZFS operations |
| `freq switch` | Network switch management |
| `freq idrac` | Dell iDRAC management |
| `freq media` | Media stack management (40+ subcommands) |

### Media Subcommands

`freq media <action>` supports:

| Action | Description |
|--------|-------------|
| `status` | All container status across VMs |
| `health` | API health checks for all services |
| `restart` | Restart a container |
| `stop` | Stop a container |
| `start` | Start a container |
| `logs` | View container logs |
| `stats` | Container resource stats |
| `update` | Update container image |
| `prune` | Prune unused images |
| `backup` | Backup container configs |
| `restore` | Restore container configs |
| `doctor` | Media stack diagnostic |
| `queue` | Sonarr/Radarr queue |
| `streams` | Active Plex streams |
| `vpn` | VPN status for download clients |
| `disk` | Disk usage for media paths |
| `missing` | Missing media search |
| `search` | Search across indexers |
| `scan` | Library scan |
| `activity` | Recent activity |
| `wanted` | Wanted/missing items |
| `indexers` | Indexer status |
| `downloads` | Active downloads |
| `transcode` | Tdarr transcode status |
| `subtitles` | Subtitle status |
| `requests` | Overseerr/Ombi requests |
| `nuke` | Remove and recreate container |
| `export` | Export config |
| `dashboard` | Media dashboard summary |
| `report` | Full media stack report |
| `compose` | View docker-compose |
| `mounts` | Check mount points |
| `cleanup` | Cleanup orphaned files |
| `gpu` | GPU transcode status |

## Specialist & Lab

| Command | Description |
|---------|-------------|
| `freq specialist` | Specialist VM workspace deployment |
| `freq lab` | Lab environment management |
| `freq distros` | List available cloud images |
| `freq provision` | Cloud-init VM provisioning |

## Fleet Extended

| Command | Description |
|---------|-------------|
| `freq ntp` | Fleet NTP check/fix |
| `freq fleet-update` | Fleet OS update check/apply |
| `freq comms` | Inter-VM communication |
| `freq backup` | VM snapshots, config export, retention |

## Monitoring

| Command | Description |
|---------|-------------|
| `freq health` | Comprehensive fleet health |
| `freq watch` | Monitoring daemon |

## Policy Engine

| Command | Description |
|---------|-------------|
| `freq check` | Check policy compliance (dry run) |
| `freq fix` | Apply policy remediation |
| `freq diff` | Show policy drift as git-style diff |
| `freq policies` | List available policies |

## Deployment

| Command | Description |
|---------|-------------|
| `freq init` | First-run 10-phase setup wizard |
| `freq configure` | Reconfigure FREQ settings |

## Agent Platform

| Command | Description |
|---------|-------------|
| `freq agent` | AI specialist management |
| `freq deploy-agent` | Deploy metrics collector to fleet |

## Smart Commands (JARVIS)

| Command | Description |
|---------|-------------|
| `freq learn` | Search Proxmox operational knowledge base |
| `freq risk` | Kill-chain blast radius analysis |
| `freq sweep` | Full audit + policy check pipeline |
| `freq patrol` | Continuous monitoring + drift detection |

## Other

| Command | Description |
|---------|-------------|
| `freq notify` | Send notifications (Discord/Slack/Telegram/etc.) |
| `freq journal` | Operation history |
| `freq gwipe` | Drive sanitization station |
| `freq serve` | Start web dashboard (default port 8888) |
| `freq update` | Check for updates and upgrade FREQ |

---

## Examples

### Fleet operations

```bash
# Check fleet health
freq status

# Run a command on all hosts
freq exec "uptime"

# Run on a specific group
freq exec --group docker "df -h"

# Deep detail on a host
freq detail node1
```

### VM management

```bash
# List all VMs
freq list

# Create a VM from a cloud image
freq create --name webserver --distro ubuntu-2404 --profile standard --node pve01

# Clone with a new IP
freq clone 200 --name clone-200 --ip 10.0.1.50

# Snapshot before changes
freq snapshot 200 --name pre-upgrade

# Power control
freq power 200 start
freq power 200 shutdown
```

### Security

```bash
# Run a security audit
freq audit

# Check SSH hardening compliance
freq check ssh-hardening

# See what would change
freq diff ssh-hardening

# Apply the fix
freq fix ssh-hardening
```

### Infrastructure

```bash
# pfSense status
freq pfsense status

# TrueNAS pool info
freq truenas pools

# Media stack health
freq media health
```

### Monitoring

```bash
# Start the dashboard
freq serve

# Run continuous patrol
freq patrol start

# Risk analysis
freq risk node1
```
