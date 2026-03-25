# PVE FREQ

Datacenter management CLI for Proxmox homelabbers. One tool to manage your entire fleet.

**65 commands. Zero dependencies. Pure Python. Works offline.**

## What It Does

- **Fleet Operations** — SSH into any host, run commands across your fleet in parallel, view system info, diagnose issues
- **VM Management** — Create, clone, destroy, resize, snapshot, migrate, power control, NIC management — all from one CLI
- **Security** — Automated auditing, SSH hardening, encrypted credential vault, RBAC user management, policy engine with drift detection
- **Infrastructure** — pfSense, TrueNAS, Dell iDRAC, network switches, ZFS — unified interface
- **Monitoring** — Real-time fleet health, web dashboard at `http://localhost:8888`, continuous patrol with auto-remediation
- **Media Stack** — Plex, Sonarr, Radarr, Tdarr, qBittorrent, SABnzbd, Prowlarr — status, health, actions

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/Low-Freq-Labs/pve-freq/main/install.sh | sudo bash
```

Or install manually:

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git /opt/pve-freq
cd /opt/pve-freq
sudo pip3 install --no-deps .
```

Or from local source:

```bash
sudo bash install.sh --from-local /path/to/pve-freq
```

## First Run

```bash
# Check your system
freq doctor

# Edit your cluster config (PVE nodes, service account, VLANs)
sudo nano /opt/pve-freq/conf/freq.toml

# Deploy to your fleet — creates service account, SSH keys, deploys to all hosts
sudo freq init

# See your fleet
freq status
```

## Commands

### Utilities
| Command | Description |
|---------|-------------|
| `freq version` | Show version and branding |
| `freq help` | Full command reference |
| `freq doctor` | 13-point self-diagnostic |
| `freq menu` | Interactive TUI menu |

### Fleet Operations
| Command | Description |
|---------|-------------|
| `freq status` | Fleet health summary (parallel SSH ping) |
| `freq dashboard` | Fleet dashboard overview |
| `freq exec <target> <cmd>` | Run command across fleet |
| `freq info <host>` | System info for a host |
| `freq detail <host>` | Deep host inventory (30+ data points) |
| `freq diagnose <host>` | Deep diagnostic scan |
| `freq ssh <host>` | SSH to a fleet host |
| `freq docker <host>` | Container discovery and management |
| `freq log <host>` | View remote host logs |
| `freq keys` | SSH key management |
| `freq boundaries` | Fleet permission tiers and categories |

### VM Management
| Command | Description |
|---------|-------------|
| `freq list` | List VMs across PVE cluster |
| `freq create` | Create a new VM |
| `freq clone <source>` | Clone with optional network config |
| `freq destroy <target>` | Destroy a VM |
| `freq resize <target>` | Resize cores, RAM, disk |
| `freq power <action> <vmid>` | Start, stop, reboot, shutdown, status |
| `freq snapshot [create\|list\|delete]` | Snapshot management |
| `freq nic <action> <vmid>` | NIC add, clear, change-ip, change-id, check-ip |
| `freq migrate <target> --node` | Live migration between nodes |
| `freq import` | Import cloud image as VM |
| `freq template <vmid>` | Convert to template |
| `freq rename <vmid> --name` | Rename a VM |
| `freq sandbox <template>` | Quick-spawn from template |

### Host Management
| Command | Description |
|---------|-------------|
| `freq hosts` | List and manage fleet hosts |
| `freq discover` | Scan network for new hosts |
| `freq groups` | Manage host groups |
| `freq bootstrap <host>` | Bootstrap a new host |
| `freq onboard <host>` | Onboard to fleet |

### Security & Policy
| Command | Description |
|---------|-------------|
| `freq vault <action>` | Encrypted credential store (AES-256-CBC) |
| `freq audit` | Security audit |
| `freq harden <target>` | Apply SSH hardening |
| `freq check <policy>` | Check compliance (dry run) |
| `freq fix <policy>` | Apply remediation |
| `freq diff <policy>` | Show drift as git-style diff |
| `freq policies` | List available policies |

### Infrastructure
| Command | Description |
|---------|-------------|
| `freq pfsense` | pfSense firewall management |
| `freq truenas` | TrueNAS pool/share management |
| `freq zfs` | ZFS operations |
| `freq switch` | Cisco Catalyst VLAN/port management |
| `freq idrac` | Dell iDRAC BMC management |
| `freq media <action>` | Media stack (40+ subcommands) |

### Monitoring
| Command | Description |
|---------|-------------|
| `freq health` | Comprehensive fleet health check |
| `freq sweep` | Full audit + policy sweep pipeline |
| `freq patrol` | Continuous monitoring + drift detection |
| `freq ntp` | Fleet NTP check/fix |
| `freq fleet-update` | Fleet OS update check/apply |

### Web Dashboard
| Command | Description |
|---------|-------------|
| `freq serve` | Start web dashboard on port 8888 |

The dashboard provides 89 API endpoints, 7 views (Home, Fleet, Docker, Security, Lab, Policies, Ops), and real-time fleet monitoring — all as a single-file SPA with zero JavaScript dependencies.

## Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Debian 11-13, Ubuntu 20.04-24.04, Rocky/RHEL/AlmaLinux 8-9 |
| **Python** | 3.7+ (ships with all supported distros) |
| **SSH** | openssh-client (pre-installed on all Linux) |
| **Optional** | sshpass (for initial fleet deployment with password auth) |

Zero external Python packages. Every import is stdlib. No pip dependencies. No compiled extensions.

## How It Works

FREQ runs on a single management host. It SSHs into your Proxmox nodes and fleet VMs to manage them. No agents on managed hosts — just SSH access.

```
                          ┌─────────────┐
                     ┌───>│  PVE Node 1  │
                     │    └─────────────┘
┌──────────────┐     │    ┌─────────────┐
│  Management  │─SSH─┼───>│  PVE Node 2  │
│    Host      │     │    └─────────────┘
│   (freq)     │     │    ┌─────────────┐
└──────────────┘     ├───>│  Docker VM   │
                     │    └─────────────┘
                     │    ┌─────────────┐
                     ├───>│  pfSense     │
                     │    └─────────────┘
                     │    ┌─────────────┐
                     └───>│  TrueNAS     │
                          └─────────────┘
```

## Configuration

All config lives in `/opt/pve-freq/conf/`:

| File | Purpose |
|------|---------|
| `freq.toml` | Main config — cluster, SSH, VM defaults, safety rules |
| `hosts.conf` | Fleet host registry — IP, label, type, groups |
| `fleet-boundaries.toml` | VM permission tiers (probe/operator/admin) |
| `vlans.toml` | VLAN definitions |
| `distros.toml` | Cloud image definitions for `freq import` |
| `containers.toml` | Docker container registry |
| `personality/` | Personality packs — celebrations, vibes, branding |
| `plugins/` | Custom command plugins (drop .py files here) |

## Uninstall

```bash
# Remove FREQ from fleet hosts first
sudo freq init --uninstall

# Remove FREQ from management host
sudo bash install.sh --uninstall
```

## License

MIT
