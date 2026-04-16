<div align="center">

# PVE FREQ

**One tool. Every device. Your entire infrastructure.**

You built a homelab because you love this stuff. You shouldn't need 12 different CLIs, 6 web UIs, and a mass of YAML to run it.

[![Tests](https://github.com/Low-Freq-Labs/pve-freq/actions/workflows/test.yml/badge.svg)](https://github.com/Low-Freq-Labs/pve-freq/actions/workflows/test.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-8b5cf6.svg)](https://www.python.org/downloads/)
[![LOC](https://img.shields.io/badge/lines_of_code-81K-8b5cf6.svg)](#)
[![License: AGPL v3](https://img.shields.io/badge/license-AGPL_v3-8b5cf6.svg)](LICENSE)
[![20 Distros](https://img.shields.io/badge/tested_on-20_distros-8b5cf6.svg)](#every-linux-distro)

</div>

---

## See It

```bash
$ freq fleet status

  VMID  Status   Node    Name
  ─────────────────────────────────────
   100  running  pve01   freq-prod
   101  running  pve01   media-stack
   102  running  pve02   docker-swarm
   103  stopped  pve02   win11-gaming
   200  running  pve03   truenas
   201  running  pve03   pihole
  ─────────────────────────────────────
  6 VMs  ·  5 running · 1 stopped  ·  3 nodes  ·  fleet reachable
```

That's your entire fleet. One command. No YAML. No agent. No cloud account.

---

## Install It

```bash
curl -fsSL https://raw.githubusercontent.com/Low-Freq-Labs/pve-freq/main/install.sh | sudo bash
```

Two minutes later:

```bash
freq init          # discovers your fleet, deploys keys, sets up API access
freq fleet status  # see everything
freq serve         # web dashboard at localhost:8888
```

Check `freq fleet status` for host reachability — init deploys keys but not all hosts may be online yet.

---

## Why FREQ Exists

Every homelabber hits the same wall.

You start with Proxmox. Then you add TrueNAS for storage. pfSense for firewall. A managed switch for VLANs. Docker for containers. WireGuard for VPN. Certbot for TLS. Grafana for monitoring. Ansible for automation.

Now you're managing 10 different tools with 10 different interfaces, and none of them talk to each other.

**FREQ puts all of it behind one CLI.** VMs, containers, switches, firewalls, storage, DNS, VPN, certificates, backups, security scanning, monitoring, and incident response. One tool. One config directory. One way to do things.

No third-party runtime dependencies. No node_modules. No Docker required. Just Python and SSH.

---

## What You Get

### 23 Domains. 250+ Commands. Everything.

| Domain | What It Does | Try It |
|--------|-------------|--------|
| `freq vm` | Create, clone, migrate, snapshot VMs | `freq vm create --name dev --cores 4 --ram 8192` |
| `freq fleet` | Fleet-wide operations and health | `freq fleet status` |
| `freq docker` | Container discovery, fleet views, and stack operations | `freq docker containers <host>` |
| `freq net` | Switches, network mapping, and IPAM | `freq net ip list` |
| `freq fw` | Firewall operations across supported platforms | `freq fw <action>` |
| `freq dns` | Internal DNS management | `freq dns scan` |
| `freq vpn` | VPN peer management | `freq vpn wg status` |
| `freq cert` | TLS certificate tracking and renewal | `freq cert scan --expiring 30` |
| `freq store` | TrueNAS and storage operations | `freq store nas <action>` |
| `freq dr` | Backups, policies, journals, and migration tooling | `freq dr backup list` |
| `freq observe` | Metrics, logs, monitors, alerts | `freq observe alert list` |
| `freq secure` | Audit, hardening, secrets, and compliance work | `freq secure audit` |
| `freq ops` | On-call and operational risk analysis | `freq ops risk <target>` |
| `freq hw` | iDRAC access, power cost, and drive wiping | `freq hw cost` |
| `freq state` | Baselines, plan/apply, and policy checks | `freq state policies` |
| `freq event` | Event network lifecycle management | `freq event list` |
| `freq media` | Media stack management and library workflows | `freq media status` |

Plus `freq proxy`, `freq auto`, `freq user`, `freq plugin`, `freq lab`, `freq agent`, and more.

Run `freq help` for the complete reference.

### Multi-Vendor. Out of the Box.

Built-in support covers **Cisco IOS/IOS-XE**, **pfSense**, **Dell iDRAC**, **TrueNAS**, and **Linux servers**. Synology has API read support, and the plugin architecture allows additional vendor integrations.

If it has an IP address, FREQ can probably talk to it.

### Web Dashboard

`freq serve` gives you a full web dashboard at `localhost:8888`. Eight navigation groups. Live updates via Server-Sent Events. Fleet health, VM management, Docker stacks, network topology, security posture — all in one view.

Embedded web assets. No frontend build step. Pure Python HTTP server.

### Interactive TUI

200+ menu entries. Risk-tagged operations. Color-coded categories. Launch with `freq menu` or just `freq` with no arguments.

### Plugin Ecosystem

Seven plugin types: command, deployer, importer, exporter, notification, widget, policy. Drop a `.py` file in `conf/plugins/` or install with `freq plugin install <url>`.

---

## What FREQ Replaces

| What You're Using | FREQ Equivalent | What You Save |
|-------------------|----------------|---------------|
| Ansible + Terraform | `freq state plan/apply` | Complexity |
| SolarWinds NCM | `freq net config backup` | $2.5K+/year |
| Datadog | `freq observe metrics` | $15/host/month |
| PagerDuty | `freq ops oncall` | $21/user/month |
| Nessus | `freq secure vuln scan` | $3.5K/year |
| Cisco DNA Center | `freq net switch/topology` | $15K+ |
| Veeam | `freq dr backup/policy` | License fees |
| CertBot + spreadsheets | `freq cert scan/renew` | Hours/month |
| 12 browser tabs | One terminal | Your sanity |

---

## Zero Dependencies

This matters more than you think.

FREQ uses **only the Python standard library**. Every single import is stdlib. No pip packages. No compiled extensions. No supply chain risk.

Why? Because the machine running FREQ is your management host. It has SSH keys to your entire fleet. It should have the smallest possible attack surface.

81K lines of Python in `freq/`. Zero external dependencies. Auditable by one person.

---

## Every Linux Distro

Tested on **20 distributions** in CI on `main` pushes and nightly runs:

**Debian** 12 · 13 · sid | **Ubuntu** 24.04 · 25.04 | **Rocky** 8 · 9 | **Alma** 8 · 9 | **CentOS** Stream 9 | **Oracle** 8 · 9 | **Fedora** 40 · 41 · 42 | **Arch** (rolling) | **openSUSE** Tumbleweed | **Alpine** 3.19 · 3.20 · 3.21

If Python 3.11 runs on it, FREQ runs on it. Platform abstraction handles package managers, init systems, and shell differences automatically.

---

## Architecture

```
freq/
├── core/           # SSH transport, config, platform detection, formatting
├── modules/        # 80+ CLI feature modules
├── deployers/      # Device-specific drivers (cisco, pfsense, truenas, ...)
├── engine/         # Declarative policy compliance engine
├── jarvis/         # Smart operations (chaos, capacity, federation)
├── api/            # REST API domain handlers
├── tui/            # Interactive terminal menu system
└── data/web/       # Dashboard SPA (HTML + CSS + JS)
```

```
                          ┌──────────────┐
                     ┌───>│  PVE Node 1  │
                     │    └──────────────┘
┌──────────────┐     │    ┌──────────────┐
│  Management  │─SSH─┼───>│  PVE Node 2  │
│    Host      │     │    └──────────────┘
│   (freq)     │     │    ┌──────────────┐
└──────────────┘     ├───>│  Docker VM   │
                     │    └──────────────┘
                     │    ┌──────────────┐
                     ├───>│  pfSense     │
                     │    └──────────────┘
                     │    ┌──────────────┐
                     ├───>│  Cisco SW    │
                     │    └──────────────┘
                     │    ┌──────────────┐
                     └───>│  TrueNAS     │
                          └──────────────┘
```

Everything over SSH. No agents on your fleet. No cloud. No phone-home.

---

## Configuration

All config lives in `conf/`. TOML format. Safe defaults — missing config never crashes.

| File | Purpose |
|------|---------|
| `freq.toml` | Main config — cluster, SSH, VM defaults, safety rules |
| `hosts.conf` | Fleet host registry — IP, label, type, groups |
| `vlans.toml` | VLAN definitions |
| `switch-profiles.toml` | Switch port profiles |
| `fleet-boundaries.toml` | VM permission tiers |
| `rules.toml` | Alert rules for health monitoring |
| `personality/` | Celebrations, vibes, branding |
| `plugins/` | Custom command plugins |

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the complete reference.

---

## Install

### One-liner (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/Low-Freq-Labs/pve-freq/main/install.sh | sudo bash
```

### pip

```bash
pip install --no-deps pve-freq
```

### Docker Compose

See [pve-freq-docker](https://github.com/Low-Freq-Labs/pve-freq-docker) for the recommended Docker deployment.

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git
cd pve-freq && docker compose up -d
```

Dashboard at `http://localhost:8888`.

### From source

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git /opt/pve-freq
cd /opt/pve-freq && sudo bash install.sh --from-local . --yes
```

### Requirements

| | |
|---|---|
| **OS** | Any Linux with Python 3.11+ (see [20 tested distros](#every-linux-distro)) |
| **Python** | 3.11+ |
| **SSH** | openssh-client (pre-installed on all Linux) |
| **Optional** | sshpass (for initial password-based fleet deployment) |

---

## First Run

```bash
freq version        # see the branding
freq doctor         # 20-point self-diagnostic — system, install, SSH, fleet, PVE
freq init           # interactive wizard — discovers your fleet
freq fleet status   # see your entire infrastructure
freq vm list        # every VM across every node
```

By minute five, you've seen your entire infrastructure without editing a single config file.

---

## The Personality System

FREQ isn't just a tool. It has vibes.

Every successful operation gets a random celebration:
> "The bass just hit different."
> "808s and server states."

Customize everything in `conf/personality/`. Ship your own pack.

---

## Uninstall

```bash
sudo freq init --uninstall         # remove from fleet hosts
sudo bash install.sh --uninstall   # remove from management host
```

Linux/PVE/TrueNAS/Docker hosts and iDRAC/switch devices get full removal of the FREQ service account. pfSense hosts get **full removal only when you supply admin credentials** via `--device-credentials` — without them, FREQ revokes the service-account SSH key and reports the host as needing manual cleanup (the FreeBSD account itself cannot delete itself). The management-host uninstall removes the wrapper, `pve-freq.pth` site-packages files, the `freq-serve.service` systemd unit (if installed), and `$INSTALL_DIR`.

---

## Documentation

| Doc | Description |
|-----|-------------|
| [CLI Reference](docs/CLI-REFERENCE.md) | CLI commands with examples |
| [API Reference](docs/API-REFERENCE.md) | REST API endpoints |
| [Configuration](docs/CONFIGURATION.md) | Every config key documented |
| [Quick Reference](docs/QUICK-REFERENCE.md) | Common commands cheat sheet |
| [Changelog](CHANGELOG.md) | Version history |
| [Contributing](CONTRIBUTING.md) | Development setup and guidelines |
| [Security Policy](SECURITY.md) | Vulnerability reporting |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR process.

---

<div align="center">

**Built by [LOW FREQ Labs](https://github.com/Low-Freq-Labs)**

[AGPL v3](LICENSE)

</div>
