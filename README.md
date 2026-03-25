<div align="center">

# PVE FREQ

**Datacenter management CLI for Proxmox homelabbers.**

83 commands. Zero dependencies. Pure Python. Works offline.

[![Tests](https://github.com/Low-Freq-Labs/pve-freq/actions/workflows/test.yml/badge.svg)](https://github.com/Low-Freq-Labs/pve-freq/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-7B2FBE.svg)](#requirements)
[![LOC](https://img.shields.io/badge/LOC-31%2C100-7B2FBE.svg)](ARCHITECTURE.md)

*Drop the bass, not the uptime.*

</div>

## Try It Now

No fleet needed. See what FREQ looks like in 10 seconds:

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git
cd pve-freq && python3 -m freq demo
```

## What It Does

- **Fleet Operations** — SSH into any host, run commands across your fleet in parallel, view system info, diagnose issues
- **VM Management** — Create, clone, destroy, resize, snapshot, migrate, power control, NIC management — all from one CLI
- **Security** — Automated auditing, SSH hardening, encrypted credential vault, RBAC, policy engine with drift detection
- **Infrastructure** — pfSense, TrueNAS, Dell iDRAC, network switches, ZFS — unified interface
- **Monitoring** — Real-time fleet health, web dashboard at `http://localhost:8888`, continuous patrol with auto-remediation
- **Media Stack** — Plex, Sonarr, Radarr, Tdarr, qBittorrent, SABnzbd, Prowlarr — status, health, actions

<details>
<summary>Screenshots</summary>

> Screenshots go in `docs/screenshots/`. See the [capture guide](docs/screenshots/README.md) for instructions.

<!-- ![Dashboard](docs/screenshots/dashboard-home.png) -->
<!-- ![TUI Menu](docs/screenshots/tui-menu.png) -->
<!-- ![Fleet Status](docs/screenshots/cli-status.png) -->
<!-- ![Doctor](docs/screenshots/cli-doctor.png) -->
<!-- ![Demo Mode](docs/screenshots/cli-demo.png) -->

</details>

## The Personality System

FREQ isn't just a tool. It has vibes.

Every successful operation gets a random celebration:
> "The bass just hit different."
> "808s and server states."
> "Holy shit, first try."

Random vibe drops appear at 1/47 probability:
> `# tip: freq doctor is free. run it more than you think you need to.`
> `# zeds dead has been making bass music since 2009. consistency is the move.`

Legendary vibe drops tell stories:
```
+-----------------------------------------------+
|  the first version of this was 300 lines       |
|  and only did 'qm list'                        |
|  now it runs a cluster, a NAS,                 |
|  a firewall, a switch, and a dream             |
+-----------------------------------------------+
```

Customize everything in `conf/personality/`. Ship your own pack.

## Install

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Low-Freq-Labs/pve-freq/main/install.sh | sudo bash
```

### pip install

```bash
pip install --no-deps pve-freq
```

### Docker Compose

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git
cd pve-freq
docker compose up -d
```

Dashboard runs at `http://localhost:8888`. Config and data persist in `./conf/` and `./data/`.

### From source

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git /opt/pve-freq
cd /opt/pve-freq
sudo bash install.sh --from-local . --yes
```

### Systemd (bare-metal daemon)

```bash
sudo bash install.sh --from-local . --yes --with-systemd
systemctl start freq-serve
```

## First Run

```bash
# Try the demo (no fleet needed)
freq demo

# Check your system
freq doctor

# Edit your cluster config
sudo nano /opt/pve-freq/conf/freq.toml

# Deploy to your fleet
sudo freq init

# See your fleet
freq status
```

## Features

### 83 CLI Commands

| Category | Count | Highlights |
|----------|-------|------------|
| Fleet Operations | 11 | Parallel SSH, fleet-wide exec, deep host inventory |
| VM Management | 16 | Create, clone, migrate, snapshot, NIC, resize, power |
| Host Management | 5 | Discovery, bootstrap, onboard, groups |
| Security & Policy | 7 | AES-256 vault, policy engine, drift detection |
| Infrastructure | 6 | pfSense, TrueNAS, iDRAC, Cisco switch, ZFS |
| Media Stack | 40+ | Plex, Sonarr, Radarr, Tdarr, qBit, SABnzbd |
| Monitoring | 5 | Health checks, patrol mode, NTP, OS updates |
| Smart Commands | 4 | Knowledge base, risk analysis, sweep, patrol |
| Deployment | 2 | 8-phase init wizard, configuration |

Run `freq help` for the full command reference.

### Web Dashboard

89 API endpoints. 7 views. Single-file SPA. Zero JavaScript dependencies.
Start with `freq serve` — runs at `http://localhost:8888`.

### Interactive TUI

97 menu entries. Risk-tagged operations. Color-coded categories. 14 submenus.
Launch with `freq menu` or just `freq`.

### Policy Engine

Declarative policies (dicts, not code). Async pipeline runner.
`freq check ssh-hardening` → `freq diff ssh-hardening` → `freq fix ssh-hardening`

### 16-Point Self-Diagnostic

`freq doctor` checks Python, platform, prerequisites, install directory, config, data directories, personality pack, SSH binary, SSH key, fleet connectivity, fleet data, fleet validity, VLANs, distros, and PVE cluster.

## Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Debian 12-13, Ubuntu 24.04+, Rocky/RHEL/AlmaLinux 9+ |
| **Python** | 3.11+ (ships with all supported distros) |
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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design philosophy and code structure.

## License

[MIT](LICENSE)
