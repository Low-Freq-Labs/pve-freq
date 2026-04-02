<div align="center">

# PVE FREQ

**One CLI to manage your entire infrastructure.**

Proxmox VMs. Docker stacks. Network switches. Firewalls. Storage. DNS. VPN. Certificates. Security. Monitoring. All from one tool. Zero dependencies. Works on every Linux distro.

[![Tests](https://github.com/Low-Freq-Labs/pve-freq/actions/workflows/test.yml/badge.svg)](https://github.com/Low-Freq-Labs/pve-freq/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<!-- ![freq fleet status](docs/screenshots/fleet-status.png) -->

</div>

## What FREQ Does

**See your entire fleet in one command:**
```bash
$ freq fleet status
```
<!-- ![Fleet Status](docs/screenshots/fleet-status.png) -->

**Deploy an event network to your switches:**
```bash
$ freq event deploy --site stadium-a --template superbowl.toml
```

**Know every certificate in your infrastructure:**
```bash
$ freq cert scan --expiring 30
```

## Quick Start

### Install

```bash
curl -fsSL https://raw.githubusercontent.com/Low-Freq-Labs/pve-freq/main/install.sh | sudo bash
```

Or with Docker:
```bash
docker run -v ~/.ssh:/home/freq/.ssh:ro ghcr.io/lowfreqlabs/pve-freq freq version
```

### Initialize

```bash
freq init
```

This deploys FREQ's service account to your fleet, configures Proxmox API access, and discovers your hosts. Takes about 2 minutes.

### Explore

```bash
freq fleet status          # What's in my fleet?
freq vm list               # What VMs do I have?
freq net switch facts sw1  # What's on my switch?
freq secure audit host1    # How secure is this host?
freq observe metrics top   # What's using the most resources?
```

## Features

### 25 Command Domains — 290 Actions

| Domain | What It Manages | Example |
|--------|----------------|---------|
| `freq vm` | Virtual machine lifecycle | `freq vm create --name myvm --cores 4 --ram 8192` |
| `freq fleet` | Fleet operations and health | `freq fleet status` |
| `freq host` | Fleet host registry and discovery | `freq host discover` |
| `freq net` | Switches, SNMP, topology, IPAM | `freq net switch vlans sw1` |
| `freq fw` | Firewall rules, NAT, states | `freq fw rules list` |
| `freq dns` | Internal DNS management | `freq dns scan` |
| `freq vpn` | WireGuard and OpenVPN | `freq vpn wg peers` |
| `freq cert` | TLS certificates and expiry tracking | `freq cert scan --expiring 30` |
| `freq proxy` | Reverse proxy management | `freq proxy status` |
| `freq store` | TrueNAS, ZFS, storage health | `freq store nas status` |
| `freq dr` | Backup, policies, SLA, runbooks | `freq dr sla status` |
| `freq observe` | Metrics, logs, monitors, alerts | `freq observe alert list` |
| `freq secure` | Vuln scanning, CIS, FIM, hardening | `freq secure comply scan` |
| `freq ops` | Incidents, changes, on-call | `freq ops incident create "Disk failure on pve01"` |
| `freq docker` | Stacks, containers, fleet-wide | `freq docker fleet ps` |
| `freq hw` | iDRAC, SMART, UPS, power | `freq hw smart` |
| `freq state` | IaC, plan/apply, drift detection | `freq state drift` |
| `freq auto` | Reactors, workflows, chaos | `freq auto rules list` |
| `freq event` | Live event network lifecycle | `freq event deploy --site stadium-a` |
| `freq user` | User and role management | `freq user list` |
| `freq media` | Media stack (40+ subcommands) | `freq media status` |
| `freq plugin` | Plugin ecosystem management | `freq plugin list` |
| `freq lab` | Lab fleet management | `freq lab status` |
| `freq agent` | AI specialist VMs | `freq agent create infra-manager` |

Run `freq help` for a complete reference organized by domain.

### What FREQ Replaces

| You Currently Use | FREQ Equivalent | Annual Cost Saved |
|-------------------|----------------|-------------------|
| Ansible + Terraform | `freq state plan/apply` | $0–15K |
| SolarWinds NCM | `freq net config backup` | $2.5K+ |
| Datadog | `freq observe metrics` | $15/host/mo |
| PagerDuty | `freq ops oncall` | $21/user/mo |
| Nessus | `freq secure vuln scan` | $3.5K |
| Cisco DNA Center | `freq net switch/topology` | $15K+ |
| Veeam | `freq dr backup/policy` | $$$$ |
| CertBot + manual tracking | `freq cert scan/renew` | Hours/month |
| 12 more tools... | One `freq` command | [See docs](docs/CLI-REFERENCE.md) |

### Zero Dependencies

FREQ uses only the Python standard library. No pip packages. No node_modules. No Docker required (but supported). Install it and it works.

### Every Linux Distro

Tested on Debian, Ubuntu, RHEL, Rocky, Fedora, Arch, Alpine, openSUSE, and more. Platform abstraction detects your package manager, init system, and shell. If Python 3.11 runs on it, FREQ runs on it.

### Web Dashboard

Start with `freq serve` — runs at `http://localhost:8888`.

- 7 navigation groups with sub-tab views for every domain
- Live updates via Server-Sent Events
- Fleet health, VM management, Docker stacks, security posture, storage, network topology
- Single-file SPA. Zero JavaScript dependencies. Pure Python HTTP server.

<!-- ![Dashboard](docs/screenshots/dashboard-home.png) -->

### Interactive TUI

168 menu entries. Risk-tagged operations. Color-coded categories. 15 submenus. Launch with `freq menu` or just `freq`.

### Plugin Ecosystem

7 plugin types: command, deployer, importer, exporter, notification, widget, policy. Drop a `.py` file in `conf/plugins/` or install via `freq plugin install <url>`. Create scaffolds with `freq plugin create --name my-plugin --type deployer`.

### Multi-Vendor Device Support

Built-in deployers for Cisco IOS/IOS-XE, pfSense, OPNsense, Dell iDRAC, TrueNAS, and Linux servers. Community deployers installable as plugins — MikroTik, Juniper, Aruba, and more.

## Architecture

```
freq/
├── core/           # SSH transport, config, platform detection, abstractions
├── modules/        # 81 CLI command modules (one per feature area)
├── deployers/      # Device-specific drivers (switch/cisco.py, firewall/pfsense.py, ...)
├── engine/         # Declarative policy compliance engine
├── jarvis/         # Smart operations (chaos, capacity, federation, ...)
├── api/            # 16 REST API domain handlers
├── tui/            # Interactive terminal menu system
└── data/web/       # Dashboard SPA (HTML + CSS + JS)
```

- **CLI:** argparse with domain-based dispatch. 25 domains, 290 actions.
- **Transport:** All remote operations over SSH. Platform-aware for Linux, FreeBSD, network appliances.
- **API:** Every CLI domain has matching REST endpoints at `/api/v1/<domain>/<action>`.
- **Dashboard:** Pure Python stdlib web server. SPA with Server-Sent Events for live updates.
- **Config:** TOML-based. Safe defaults — missing config never crashes.
- **Plugins:** Drop a `.py` file in `conf/plugins/` or install via `freq plugin install`.

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
                     ├───>│  Cisco SW    │
                     │    └─────────────┘
                     │    ┌─────────────┐
                     └───>│  TrueNAS     │
                          └─────────────┘
```

## Configuration

All config lives in `conf/`. FREQ uses TOML format with safe defaults.

| File | Purpose |
|------|---------|
| `freq.toml` | Main config — cluster, SSH, VM defaults, safety rules, services |
| `hosts.conf` | Fleet host registry — IP, label, type, groups |
| `vlans.toml` | VLAN definitions |
| `switch-profiles.toml` | Switch port profiles |
| `fleet-boundaries.toml` | VM permission tiers (probe/operator/admin) |
| `rules.toml` | Alert rules for health monitoring |
| `risk.toml` | Infrastructure dependency/risk map |
| `playbooks/` | Recovery playbooks (automated remediation) |
| `personality/` | Personality packs — celebrations, vibes, branding |
| `plugins/` | Custom command plugins |

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the complete reference.

## Requirements

| Requirement | Details |
|-------------|---------|
| **OS** | Debian 12–13, Ubuntu 24.04+, RHEL/Rocky/Alma 9+, Fedora, Arch, Alpine, openSUSE |
| **Python** | 3.11+ |
| **SSH** | openssh-client (pre-installed on all Linux) |
| **Optional** | sshpass (for initial fleet deployment with password auth) |

Zero external Python packages. Every import is stdlib. No pip dependencies. No compiled extensions.

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

See [pve-freq-docker](https://github.com/Low-Freq-Labs/pve-freq-docker) for the recommended Docker deployment.

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git
cd pve-freq && docker compose up -d
```

Dashboard at `http://localhost:8888`. Config and data persist in `./conf/` and `./data/`.

### From source

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git /opt/pve-freq
cd /opt/pve-freq && sudo bash install.sh --from-local . --yes
```

## First Run

```bash
freq version     # Branding, version — feels polished
freq doctor      # Self-diagnostic — checks everything
freq init        # Interactive wizard — discovers your fleet
freq fleet status   # See your entire fleet
freq vm list     # Every VM across every node
```

By minute 5, you've seen your entire infrastructure without editing a single config file.

## Uninstall

```bash
sudo freq init --uninstall   # Remove from fleet hosts
sudo bash install.sh --uninstall   # Remove from management host
```

## Documentation

| Doc | Description |
|-----|-------------|
| [CLI Reference](docs/CLI-REFERENCE.md) | All 290 commands with examples |
| [API Reference](docs/API-REFERENCE.md) | REST API endpoints |
| [Configuration](docs/CONFIGURATION.md) | Every config key documented |
| [Architecture](ARCHITECTURE.md) | Design philosophy and code structure |
| [Quick Reference](docs/QUICK-REFERENCE.md) | Common commands cheat sheet |
| [Changelog](CHANGELOG.md) | Version history |
| [Contributing](CONTRIBUTING.md) | Development setup and guidelines |
| [Security Policy](SECURITY.md) | Vulnerability reporting |

## The Personality System

FREQ isn't just a tool. It has vibes.

Every successful operation gets a random celebration:
> "The bass just hit different."
> "808s and server states."

Customize everything in `conf/personality/`. Ship your own pack.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR process.

## License

[MIT](LICENSE)
