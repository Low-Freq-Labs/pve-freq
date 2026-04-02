<!-- INTERNAL — Not for public distribution -->

# README BLUEPRINT

**What the Public-Facing README Looks Like When FREQ Hits GitHub**

**Author:** Morty (Lead Dev)
**Created:** 2026-04-01
**Purpose:** The README is the front door. Most people will decide in 30 seconds whether to star or close the tab. This document designs those 30 seconds.

---

## THE 30-SECOND RULE

A developer lands on the GitHub page. They see:

1. **The name and one-liner** (2 seconds) — what is this?
2. **The hero screenshot** (5 seconds) — what does it look like?
3. **The value prop** (10 seconds) — why should I care?
4. **The install command** (5 seconds) — how fast can I try it?
5. **The feature list** (8 seconds) — what can it actually do?

If any of these are missing or weak, they close the tab. Every section below is designed for this flow.

---

## README STRUCTURE

### 1. Hero Section

```markdown
# PVE FREQ

**One CLI to manage your entire infrastructure.**

Proxmox VMs. Docker stacks. Network switches. Firewalls. Storage. DNS. VPN. Certificates. Security. Monitoring. All from one tool. Zero dependencies. Works on every Linux distro.

[Screenshot: freq fleet status showing a healthy fleet with colored output]
```

**Rules:**
- Name is big and bold.
- One-liner is under 15 words.
- Expanded description is under 3 lines.
- Screenshot is the first visual. Not a logo. A real screenshot of real output that makes someone think "I want that."
- No badges spam. Maybe 3 max: version, license, Python version.

### 2. The "Holy Shit" Section

This is where we show what FREQ does that nothing else can. Three examples max, each one a single command with output:

```markdown
## What FREQ Does

**See your entire fleet in one command:**
```
$ freq fleet status
```
[Screenshot: fleet status with 14 hosts, all UP, colored by type]

**Deploy an event network to 200 switches:**
```
$ freq event deploy --site stadium-a --template superbowl.toml
```
[Screenshot or example output showing switches configured]

**Know every certificate in your infrastructure:**
```
$ freq cert inventory --expiring 30d
```
[Screenshot: cert inventory showing certs across fleet with expiry dates]
```

**Rules:**
- Real commands. Real output. Not mockups.
- Show the output, not just the command. People need to see what they GET.
- Three examples. Not ten. Three. Each one a different domain to show breadth.
- Pick the three that make people say "holy shit, I need that."

### 3. Quick Start

```markdown
## Quick Start

### Install
```bash
curl -fsSL https://get.pve-freq.dev/install.sh | bash
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
freq net switch show sw1   # What's on my switch?
freq secure audit host1    # How secure is this host?
freq observe metrics top   # What's using the most resources?
```
```

**Rules:**
- Install is ONE command. Not "clone the repo, install dependencies, configure..."
- Init is ONE command. The "2 minutes" sets expectations.
- Explore shows 5 commands across 5 different domains. Shows breadth immediately.
- No configuration file editing in the quick start. `freq init` handles it interactively.

### 4. Feature Overview

```markdown
## Features

### 25 Command Domains

| Domain | What It Manages | Example |
|---|---|---|
| `freq vm` | Virtual machine lifecycle | `freq vm create --name myvm --cores 4 --ram 8192` |
| `freq fleet` | Fleet operations and health | `freq fleet status` |
| `freq net` | Switches, SNMP, topology, IPAM | `freq net switch vlans sw1` |
| `freq fw` | Firewall rules, NAT, DHCP, IDS | `freq fw rules list` |
| `freq dns` | Pi-hole, AdGuard, internal DNS | `freq dns sync --dry-run` |
| `freq vpn` | WireGuard, OpenVPN, Tailscale | `freq vpn wg peers qr --name phone` |
| `freq cert` | TLS certificates, ACME, private CA | `freq cert inventory --expiring 30d` |
| `freq proxy` | NPM, Caddy, Traefik, HAProxy | `freq proxy add --domain app.local --upstream 10.0.0.5:3000` |
| `freq store` | TrueNAS, ZFS, Ceph, shares | `freq store nas smart status` |
| `freq dr` | Backup, replication, failover, SLA | `freq dr sla status` |
| `freq observe` | Metrics, logs, monitors, alerts | `freq observe metrics predict pve01 disk 90d` |
| `freq secure` | Vuln scanning, CIS, FIM, hardening | `freq secure comply scan --level 2` |
| `freq ops` | Incidents, changes, postmortems | `freq ops incident create "Disk failure on pve01"` |
| `freq docker` | Stacks, containers, auto-update | `freq docker update check` |
| `freq hw` | iDRAC, IPMI, SMART, UPS, power | `freq hw smart failing` |
| `freq state` | IaC, plan/apply, drift detection | `freq state drift detect` |
| `freq auto` | Events, reactors, workflows, chaos | `freq auto react add --on vm/stopped --do vm/restart` |
| `freq event` | Live event network lifecycle | `freq event deploy --site stadium-a` |
| `freq user` | User and role management | `freq user list` |
| `freq host` | Fleet host registry and discovery | `freq host discover` |
| `freq media` | Media stack (40+ subcommands) | `freq media status` |
| `freq agent` | AI specialist VMs | `freq agent create infra-manager` |
| `freq lab` | Lab fleet management | `freq lab status` |
| `freq cmdb` | Configuration management DB | `freq cmdb impact truenas` |

### What FREQ Replaces

| You Currently Use | FREQ Equivalent | Annual Cost Saved |
|---|---|---|
| Ansible + Terraform | `freq state plan/apply` | $0-15K |
| SolarWinds NCM | `freq net config backup/compliance` | $2.5K+ |
| Datadog | `freq observe metrics` | $15/host/mo |
| PagerDuty | `freq ops incident/oncall` | $21/user/mo |
| Nessus | `freq secure vuln scan` | $3.5K |
| ServiceNow | `freq ops incident/change/cmdb` | $100/user/mo |
| Cisco DNA Center | `freq net health/template deploy` | $15K+ |
| Veeam | `freq dr backup/replicate/failover` | $$$$  |
| 12 more tools... | One `freq` command | See docs |

### Zero Dependencies

FREQ uses only the Python standard library. No pip packages. No node_modules. No Docker required (but supported). Install it and it works.

### Every Linux Distro

Tested on Debian, Ubuntu, RHEL, Rocky, Fedora, Arch, Alpine, openSUSE, and more. If Python 3.11 runs on it, FREQ runs on it.
```

**Rules:**
- Feature table shows every domain with a real example command. Scannable.
- "What it replaces" table hits the competitive angle. Show the cost.
- Zero dependencies and distro support are selling points — call them out explicitly.

### 5. Architecture (For Developers)

```markdown
## Architecture

- **CLI:** argparse with domain-based dispatch. 25 domains, ~810 actions.
- **Transport:** All remote operations over SSH. Platform-aware for Linux, FreeBSD, network appliances.
- **API:** Every CLI command available as REST endpoint at `/api/v1/<domain>/<action>`.
- **Dashboard:** Pure Python stdlib web server. SPA with Server-Sent Events for live updates.
- **Config:** TOML-based. Safe defaults — missing config never crashes.
- **Plugins:** Drop a `.py` file in `conf/plugins/` or install via `freq plugin install`.
- **Multi-vendor:** Switch deployers for Cisco, Juniper, HPE Aruba, Ubiquiti, Arista.

```
freq/
├── core/           # SSH transport, config, platform detection, abstractions
├── modules/        # CLI command implementations (one per domain)
├── deployers/      # Device-specific drivers (switch/cisco.py, firewall/pfsense.py, ...)
├── engine/         # Declarative policy compliance engine
├── jarvis/         # Smart operations (chaos, capacity, federation, ...)
├── api/            # REST API handlers (one per domain)
└── data/web/       # Dashboard SPA
```
```

### 6. Documentation Links

```markdown
## Documentation

- [Getting Started Guide](docs/getting-started.md)
- [Command Reference](docs/commands.md) — all 810 actions
- [Configuration Guide](docs/configuration.md)
- [Supported Platforms](docs/platforms.md)
- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
```

### 7. Contributing + License

```markdown
## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR process.

## License

[License type TBD by Sonny]
```

---

## SCREENSHOTS TO CAPTURE

Before release, capture these real screenshots from the live fleet:

| Screenshot | What It Shows | Used Where |
|---|---|---|
| `freq fleet status` | Full fleet health with 14+ hosts, colored by type/status | Hero section, README |
| `freq vm list` | VM list across cluster with cores/RAM/status | Features section |
| `freq net switch vlans` | VLAN table from Cisco switch | Network features |
| `freq cert inventory` | Certificate inventory with expiry dates | Cert features |
| `freq secure comply scan` | CIS compliance scores per host | Security features |
| `freq observe metrics top` | Fleet resource usage ranked | Observability features |
| Dashboard login page | The web UI | Dashboard section |
| Dashboard fleet view | Live fleet dashboard with SSE updates | Dashboard section |
| `freq help` | The 25-domain help screen | Architecture section |
| `freq event deploy` output | Event network deployment | Event networking (the differentiator) |

**Screenshot rules:**
- Real data, not fake. Real hosts, real VMs, real output.
- Terminal with dark background, decent font. Not a raw white terminal.
- Crop to content — no desktop, no taskbar, no other windows.
- Save to repo at `docs/screenshots/` and reference in README.
- Save source to Nexus SMB share at `/mnt/nexus/ss/` per CLAUDE.md convention.

---

## THE ONBOARDING EXPERIENCE

The first 5 minutes with FREQ should feel like this:

```
Minute 0:   curl install script → installs in 30 seconds
Minute 1:   freq version → branding, version, feels polished
Minute 1:   freq doctor → checks local system, all green
Minute 2:   freq init → interactive wizard, discovers fleet
Minute 3:   freq fleet status → "holy shit, it found everything"
Minute 4:   freq vm list → "it sees all my VMs across 3 nodes"
Minute 5:   freq secure audit myhost → "it just audited my host in 4 seconds"
```

By minute 5, the user has seen:
1. Fast install (no dependency hell)
2. Professional polish (branding, colors, formatting)
3. Smart discovery (found their fleet automatically)
4. Real value (fleet health, VM inventory, security audit)

They haven't edited a YAML file. They haven't read documentation. They haven't configured anything except answering the init wizard questions.

**That's the product.**

---

## WHAT THE GITHUB PAGE LOOKS LIKE

```
lowfreqlabs/pve-freq
★ 0 stars (for now)

Description: One CLI to manage your entire infrastructure. Proxmox, Docker, switches, firewalls, storage, security, monitoring. Zero dependencies.

Topics: proxmox, infrastructure, devops, homelab, network-automation, cli, sysadmin, monitoring, security, docker

Website: [TBD]

├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── PULL_REQUEST_TEMPLATE.md
├── freq/
├── conf/
├── tests/
├── docs/
│   ├── screenshots/
│   ├── getting-started.md
│   ├── commands.md
│   └── platforms.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── SECURITY.md
├── Dockerfile
├── docker-compose.yml
├── install.sh
└── pyproject.toml
```

Clean. Professional. Everything in its place.
