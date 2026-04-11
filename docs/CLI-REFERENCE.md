# CLI Reference — PVE FREQ

FREQ is organized around domain commands. Run `freq help` for the live command map or `freq <domain> --help` for a focused view.

## Top-Level Utilities

| Command | Description |
|---------|-------------|
| `freq version` | Show version and branding |
| `freq help` | Show the domain-based command reference |
| `freq doctor` | Run the self-diagnostic |
| `freq menu` | Launch the interactive terminal UI |
| `freq demo` | Run the interactive demo |
| `freq init` | Bootstrap a new installation |
| `freq configure` | Reconfigure settings |
| `freq serve` | Start the web dashboard |
| `freq update` | Check for updates |
| `freq docs <action>` | Generate or verify docs output |
| `freq distros` | List cloud image presets |
| `freq notify <message>` | Send a notification |
| `freq agent <action>` | Manage AI specialist features |

## Core Domains

| Domain | What It Covers | Example |
|--------|----------------|---------|
| `freq vm` | VM lifecycle, snapshots, networking, files, provisioning | `freq vm list` |
| `freq fleet` | Fleet health, exec, reports, NTP, updates, comms | `freq fleet status` |
| `freq host` | Host registry, groups, bootstrap, onboarding, keys | `freq host list` |
| `freq docker` | Container discovery, fleet views, stack operations | `freq docker containers <host>` |
| `freq secure` | Audit, hardening, secrets, compliance | `freq secure audit` |
| `freq observe` | Alerts, logs, trends, capacity, watch mode | `freq observe alert list` |
| `freq state` | Baselines, plan/apply, policy checks, drift | `freq state policies` |
| `freq auto` | Rules, schedules, playbooks, patrol, chaos | `freq auto schedule list` |
| `freq ops` | On-call and risk analysis | `freq ops risk <target>` |
| `freq hw` | iDRAC, cost, drive wiping | `freq hw cost` |
| `freq store` | NAS and storage operations | `freq store nas <action>` |
| `freq dr` | Backup, policy, journal, migration flows | `freq dr backup list` |
| `freq net` | Switch, network map, bandwidth, IPAM | `freq net ip list` |
| `freq user` | User lifecycle and role management | `freq user list` |
| `freq vpn` | VPN peer management | `freq vpn list` |
| `freq event` | Event network lifecycle | `freq event list` |
| `freq specialist` | Specialist environment operations | `freq specialist <action>` |
| `freq lab` | Lab environments and tooling | `freq lab list` |
| `freq engine` | Policy engine commands | `freq engine list` |
| `freq plugin` | Plugin discovery, install, update, creation | `freq plugin list` |
| `freq config` | Configuration validation | `freq config validate` |

## Standalone Domains

| Domain | Description |
|--------|-------------|
| `freq fw` | Firewall operations across supported platforms |
| `freq cert` | TLS certificate visibility and checks |
| `freq dns` | DNS validation and inventory |
| `freq proxy` | Reverse-proxy management |
| `freq media` | Media stack management |

## Useful Patterns

```bash
# VM work
freq vm list
freq vm create --name web01 --image ubuntu-2404
freq vm power start 200

# Fleet work
freq fleet status
freq fleet test pve01
freq fleet exec all "uptime"

# Security and drift
freq secure audit
freq state check ssh-hardening
freq state diff ssh-hardening

# Dashboard and docs
freq serve
freq docs generate
```

## Source of Truth

This file is intentionally high-level. The live source of truth is the installed command map exposed by `freq help`, because that reflects the actual shipped CLI.
