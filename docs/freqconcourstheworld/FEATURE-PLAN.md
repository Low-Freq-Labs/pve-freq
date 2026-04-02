<!-- INTERNAL — Not for public distribution -->

# PVE FREQ — The Conquest: Master Feature Plan

**Version:** 2.2.0 → 3.0.0
**Author:** Morty (Lead Dev)
**Created:** 2026-04-01
**Status:** DRAFT — Sonny reviews, then we execute in order
**Research:** 6 parallel deep-research agents across 50+ enterprise tools, 1,400+ command ideas distilled

---

## The Thesis

FREQ replaces 15+ separate tools with one CLI. One state model, one auth system, one command language. Every layer of the stack — physical hardware, storage, virtualization, containers, networking, security, observability — managed from one tool.

**Current state:** 126 CLI commands, 212 API endpoints, 1,674 tests
**Target state:** ~810 actions across ~25 domains, ~900 API endpoints, covering every IT domain that matters
**Prerequisites:** Before WS1, complete Phase 0 (CLI refactor + abstractions) described in THE-REWRITE-EXECUTION-PLAYBOOK.md

---

## What Already Exists (The Foundation We're Building On)

Before diving into workstreams, here's the architecture that EVERY new feature plugs into. New code follows these patterns — no exceptions.

### The Module System

Every CLI command lives in `freq/modules/<name>.py` and exports `cmd_<name>(cfg, pack, args)`. The CLI in `freq/cli.py` registers commands via argparse and dispatches through lazy-import wrappers:

```python
# freq/cli.py — lazy import wrapper pattern (one per command)
def _cmd_switch(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_switch
    return cmd_switch(cfg, pack, args)
```

**50+ modules** already exist (34,175 total lines). The biggest are serve.py (7,676 — web dashboard + API), init_cmd.py (4,164 — bootstrap/deployers), and media.py (2,378 — media stack management). New workstreams add new module files following this exact pattern.

### The SSH Transport (`freq/core/ssh.py` — 372 lines)

**Every remote operation goes through here.** No exceptions. Two modes:
- `run(host, cmd, cfg)` — single host, sync
- `run_many(hosts, cmd, cfg)` — parallel fleet execution via asyncio with semaphore-bounded concurrency (default 5)

Platform-aware for 6 host types. Legacy cipher support for iDRAC/switch (`LEGACY_HTYPES`). SSH multiplexing for connection reuse. This is the muscle behind every fleet command.

New features that talk to remote hosts use `ssh_run()` and `ssh_run_many()`. Nothing else.

### The Deployer Registry (`freq/deployers/` — 189 lines)

Category-based plugin system for device types:
```
freq/deployers/{category}/{vendor}.py
  → 5 categories: server, firewall, switch, bmc, nas
  → Resolution: resolve_htype("pfsense") → ("firewall", "pfsense")
  → Fallback: if vendor module not found, try {category}/generic.py
```

Each deployer exports `deploy()` and `remove()`. Currently thin wrappers (20-26 lines) that delegate to init_cmd.py. **Workstream 1 extends this pattern by adding getter methods to deployers** — same registry, same resolution, new capabilities.

### The Infrastructure Device Pattern (`freq/modules/infrastructure.py` — 289 lines)

Shared `_device_cmd()` handler that ALL infrastructure appliances use:
```python
_device_cmd(cfg, args, title, ip, htype, actions, timeout)
```

Takes an `actions` dict mapping action names to `(description, ssh_command)` tuples. Handles: help display, SSH execution, output formatting. Used by pfSense (7 actions), TrueNAS (7 actions), switch (6 actions), iDRAC (5 actions). **New workstreams extend the actions dicts or graduate to their own module files when they outgrow this pattern.**

### The Config System (`freq/core/config.py` — 694 lines)

`FreqConfig` dataclass loaded from `conf/freq.toml` (TOML). 30+ fields with safe defaults — config failure never crashes the tool ("Trap #4" pattern). Infrastructure IPs live in `[infrastructure]` section. Fleet hosts in `hosts.conf` (flat text: `IP LABEL TYPE [GROUPS]`). VLANs in `vlans.toml`.

**New workstreams add config sections to freq.toml** (e.g., `[snmp]`, `[certificates.acme]`) and **new config files** where needed (e.g., `conf/switch-profiles.toml`).

### The Policy Engine (`freq/engine/` — 388 lines)

Declarative compliance: policies are dicts of data, not code. `PolicyExecutor` runs a 5-phase pipeline: PING → DISCOVER → COMPARE → FIX → VERIFY. Commands: `freq check` (dry-run), `freq fix` (apply), `freq diff` (git-style), `freq policies` (list). Platform overrides per host type.

**New compliance features (CIS benchmarks, network config compliance) extend this engine** with new policy definitions rather than building separate compliance systems.

### The Jarvis System (`freq/jarvis/` — 4,724 lines)

"Smart" operations: capacity projections, alert rules, chaos engineering, GitOps sync, notifications (Discord/Slack/email), federation, cost analysis, playbooks, knowledge base, patrol (continuous monitoring), risk analysis, sweep (audit pipeline). **New automation features (reactors, workflows, auto-remediation) extend jarvis rather than creating parallel systems.**

### The Web Dashboard (`freq/modules/serve.py` — 7,676 lines)

Pure stdlib `http.server` + SSE. SPA frontend in `freq/data/web/app.html` (63KB). Login with 8-hour sessions. Background cache thread refreshes data on intervals. API endpoints at `/api/*`. Role-based UI (viewer/operator/admin). **Every new command that produces data gets a dashboard page and an API endpoint in serve.py.**

### The Data Storage Pattern

Modules store persistent data as JSON files in `conf/` subdirectories:
```
conf/alerts/alert-rules.json      — alert module
conf/dns/dns-inventory.json        — dns module  
conf/certs/cert-inventory.json     — cert module
conf/proxy/routes.json             — proxy module
```

**New workstreams follow this pattern** — JSON in `conf/<domain>/`. No databases, no external storage.

### The Zero-Dependency Constraint

**Only Python stdlib.** No pip packages. SSH for remote execution, `subprocess` for local commands, `http.server` for web, `tomllib` for config, `json` for storage, `ssl`/`socket` for network checks. SNMP uses `snmpget`/`snmpwalk` shell commands. This is non-negotiable.

### Existing Modules That New Workstreams Extend

| Existing Module | Lines | What It Does Now | What New Workstreams Add |
|---|---|---|---|
| `infrastructure.py` | 289 | pfSense (7 actions), TrueNAS (7), switch (6), iDRAC (5) | WS1 graduates switch to own module. WS3 graduates pfSense. WS8 graduates TrueNAS. WS14 graduates iDRAC. |
| `proxy.py` | 268 | proxy status/list/add/remove/certs | WS7 adds NPM/Caddy/Traefik/HAProxy API integration |
| `dns.py` | 303 | dns scan/check/list (forward/reverse validation) | WS4 adds Pi-hole, AdGuard, Unbound, BIND management |
| `cert.py` | 382 | cert scan/list/check (TLS endpoint scanning) | WS6 adds ACME issuance, private CA, fleet deployment |
| `alert.py` | 712 | alert create/list/delete/history/test/silence | WS10 extends with metric-based alerting, anomaly detection |
| `audit.py` | 329 | security audit (SSH, ports, sudo, services) | WS11 adds CIS benchmarks, STIG, vuln scanning, FIM |
| `harden.py` | 142 | basic hardening (SSH config, sysctl) | WS11 extends with full CIS remediation |
| `logs.py` | 280 | logs tail/search/stats | WS10 adds fleet-wide aggregation, pattern detection |
| `sla.py` | 262 | sla show/check | WS9 extends with RTO/RPO tracking per VM |
| `trend.py` | 328 | trend show/snapshot (capacity sparklines) | WS10 extends with predictive analytics |
| `baseline.py` | 379 | baseline capture/compare (config drift) | WS15 extends into full IaC state management |
| `compare.py` | 261 | compare host-a host-b | WS2 extends with network device comparison |
| `rollback.py` | 199 | rollback vmid (snapshot restore) | WS9 extends with full DR failover |
| `depmap.py` | 356 | map discover/impact/export (service dependencies) | WS2 extends with LLDP/CDP network topology |
| `netmon.py` | 347 | netmon interfaces/poll/bandwidth/topology | WS2 extends with SNMP polling, flow analysis |
| `report.py` | 374 | report (fleet health report) | WS10 extends with observability reports |
| `secrets.py` | 356 | secrets scan/audit/generate/lease | WS11 extends with container scanning |
| `vault.py` | 339 | vault encrypt/decrypt/list/delete | WS16 extends as secrets backend for automation |
| `schedule.py` | 432 | schedule list/create/delete/run/templates/install | WS16 extends as job scheduler for automation |
| `backup.py` | 251 | backup status/prune | WS9 extends with full backup orchestration |
| `backup_policy.py` | 375 | backup-policy list/create/apply | WS9 extends with RPO/RTO enforcement |
| `patch.py` | 432 | patch status/check/apply/compliance | WS11 extends with vuln-scan-driven patching |
| `stack.py` | 427 | stack status/update/health (Docker Compose fleet) | WS13 extends with rolling deploys, auto-update |
| `comply.py` | 384 | comply scan/report (CIS Level 1) | WS11 extends with full CIS/STIG implementation |
| `ipam.py` | 374 | ip next/list/check | WS2 extends with subnet utilization, conflict detection |
| `hosts.py` | 806 | hosts list/add/remove/sync/discover/groups | Foundation for all fleet targeting |

### The Jarvis Modules That New Workstreams Extend

| Existing Jarvis Module | Lines | What It Does Now | What New Workstreams Add |
|---|---|---|---|
| `chaos.py` | 437 | chaos list/run/log (experiments) | Already exists — WS needs E2E testing only |
| `capacity.py` | 458 | capacity show/snapshot (projections) | WS10 extends with predictive analytics |
| `rules.py` | 466 | rules list/create/delete (alert rules) | WS16 extends into event-driven reactors |
| `notify.py` | 356 | Discord/Slack/email notifications | Foundation for all alerting workstreams |
| `federation.py` | 315 | federation list/register/poll (multi-site) | WS15 extends with cross-cluster management |
| `gitops.py` | 379 | gitops status/sync/apply/diff | WS15 extends into full IaC |
| `patrol.py` | 166 | patrol (continuous monitoring + drift) | WS16 extends with beacon/reactor pattern |
| `playbook.py` | 273 | playbook list/run (incident playbooks) | WS16 extends into full workflow engine |
| `risk.py` | 161 | risk (blast radius analysis) | WS12 extends with change risk assessment |
| `sweep.py` | 114 | sweep (full audit pipeline) | WS11 extends with comprehensive scanning |
| `cost.py` | 281 | cost (power estimates) | WS14 extends with real iDRAC/IPMI power data |
| `learn.py` | 278 | learn (knowledge base search) | Foundation — no extension needed |

---

## Execution Philosophy

1. Build in workstreams. Each workstream is a complete domain.
2. **Extend existing modules first** — only create new module files when the existing one would exceed ~800 lines or the domain is truly distinct.
3. Each command gets: CLI, API endpoint, unit tests, --help.
4. Follow existing patterns: `_device_cmd()` for appliance commands, JSON in `conf/<domain>/` for state, `ssh_run()`/`ssh_run_many()` for remote ops.
5. Dashboard pages come AFTER all CLI commands exist.
6. E2E testing is LAST — after everything is built.

---

## WORKSTREAM OVERVIEW

| # | Workstream | New Cmds | Priority | Builds On |
|---|---|---|---|---|
| 1 | Switch Orchestration & Event Networking | ~40 | HIGHEST | `infrastructure.py` switch actions, `deployers/switch/`, `vlans.toml`, `ssh.py` LEGACY_HTYPES |
| 2 | Network Intelligence | ~35 | HIGHEST | `netmon.py`, `depmap.py`, `ipam.py`, `discover.py`, `compare.py` |
| 3 | Firewall & Gateway Deep | ~50 | HIGH | `infrastructure.py` pfSense actions, `deployers/firewall/pfsense.py` |
| 4 | DNS Management | ~25 | HIGH | `dns.py` (scan/check/list already exist), `infrastructure.py` pfSense DNS |
| 5 | VPN Management | ~30 | HIGH | `infrastructure.py` pfSense, new — no existing VPN module |
| 6 | Certificate & PKI | ~20 | HIGH | `cert.py` (scan/list/check already exist) |
| 7 | Reverse Proxy Management | ~25 | HIGH | `proxy.py` (status/list/add/remove/certs already exist) |
| 8 | Storage Deep Dive | ~50 | HIGH | `infrastructure.py` TrueNAS actions, `modules/zfs.py` (if exists), `backup.py` |
| 9 | Disaster Recovery | ~35 | HIGH | `backup.py`, `backup_policy.py`, `rollback.py`, `sla.py`, `snapshot` commands |
| 10 | Observability Platform | ~60 | HIGH | `alert.py`, `logs.py`, `trend.py`, `report.py`, `health.py`, `netmon.py`, `jarvis/capacity.py` |
| 11 | Security & Compliance | ~55 | HIGH | `audit.py`, `harden.py`, `comply.py`, `secrets.py`, `patch.py`, `jarvis/sweep.py` |
| 12 | Incident & Change Mgmt | ~30 | MEDIUM | `jarvis/playbook.py`, `jarvis/risk.py`, `jarvis/notify.py`, `alert.py` |
| 13 | Docker Fleet Deep | ~40 | MEDIUM | `stack.py`, `fleet.py` docker actions, `modules/docker_fleet.py` (if exists) |
| 14 | Hardware Management | ~35 | MEDIUM | `infrastructure.py` iDRAC actions, `deployers/bmc/idrac.py`, `jarvis/cost.py` |
| 15 | Infrastructure as Code | ~25 | MEDIUM | `baseline.py`, `plan.py`, `engine/` policy system, `jarvis/gitops.py`, `jarvis/federation.py` |
| 16 | Automation Engine | ~30 | MEDIUM | `jarvis/rules.py`, `jarvis/patrol.py`, `jarvis/playbook.py`, `schedule.py`, `vault.py`, `jarvis/notify.py` |
| 17 | Fleet Commands (Easy Builds) | ~25 | MEDIUM | `fleet.py`, `ssh.py` run_many, `hosts.py` targeting |
| 18 | Public Access Wizard | ~5 | MEDIUM | `proxy.py`, `cert.py`, `infrastructure.py` pfSense NAT/DNS |
| 19 | Plugin System | ~10 | LOWER | `cli.py` already discovers plugins from `conf/plugins/`, `deployers/` registry pattern |
| 20 | Dashboard Pages | 0 (UI) | LAST | `serve.py` (7,676 lines — SPA + SSE + API pattern) |
| 21 | E2E Testing | 0 (test) | LAST | `tests/` (45+ test files, organized by phase) |

**Projected totals:** ~810 actions across ~25 domains, ~900 API endpoints (see THE-CONVERGENCE-OF-PVE-FREQ.md for how these features map to the converged domain structure)

**NOTE:** This document uses FEATURE names (e.g., `freq switch show`, `freq certs issue`). THE-CONVERGENCE-OF-PVE-FREQ.md maps these to their FINAL domain names (e.g., `freq net switch show`, `freq cert issue`). When building, use the converged names — this doc describes WHAT to build, Convergence describes HOW to name it.

---

## WORKSTREAM 1: Switch Orchestration & Event Networking

### Why This Is THE Feature

Sonny programmed hundreds of switches weekly — Cisco, Juniper, HPE Aruba, Ubiquiti — for nationally televised events (NFL, FIFA, F1, USGA, LIV). Built entire event networks from ISP handoff to every endpoint in 3 weeks, then wiped and repeated. No tool existed to automate this. FREQ will be that tool.

### How It Connects to What Exists

**Starting point:** `infrastructure.py` has 6 switch actions via the shared `_device_cmd()` handler — `status`, `vlans`, `interfaces`, `mac`, `arp`, `trunk`. These SSH to the switch and run show commands. The deployer at `deployers/switch/cisco.py` (26 lines) only handles `deploy()` and `remove()` for the freq-admin service account.

**What changes:**
1. **Switch graduates from infrastructure.py to its own module** `freq/modules/switch_orchestration.py` — the 6 existing actions move there and expand to ~40 commands
2. **Deployers get a getter interface** — each vendor deployer adds `get_facts()`, `get_interfaces()`, `get_vlans()`, `get_mac_table()`, `get_config()`, etc. alongside the existing `deploy()`/`remove()`
3. **New deployers** — `juniper.py`, `aruba.py`, `arista.py` join the existing `cisco.py` and `ubiquiti.py` stubs
4. **New config file** `conf/switch-profiles.toml` — port profile definitions (the key differentiator)
5. **New config directory** `conf/event-templates/` — event network blueprints
6. **New module** `freq/modules/event_network.py` — event lifecycle (create/deploy/verify/wipe/archive)
7. **Uses:** `ssh.py` with LEGACY_HTYPES for switch SSH, `vlans.toml` for VLAN definitions, `hosts.conf` for switch registration (type=switch), `fmt.py` for table output

### Architecture

```
freq/modules/switch_orchestration.py    — Core switch + port management (~40 commands)
freq/modules/event_network.py           — Event lifecycle management (~15 commands)
freq/deployers/switch/base.py           — Abstract getter+setter interface
freq/deployers/switch/cisco.py          — Cisco IOS (extend existing 26 lines → ~300)
freq/deployers/switch/juniper.py        — Juniper JunOS (new)
freq/deployers/switch/aruba.py          — HPE Aruba AOS-CX (new)
freq/deployers/switch/ubiquiti.py       — EdgeSwitch (extend existing stub)
freq/deployers/switch/arista.py         — Arista EOS (new)
freq/deployers/switch/generic.py        — Generic SSH fallback (new)
conf/switch-profiles.toml               — Port profile templates
conf/event-templates/                   — Event network blueprints
conf/switch-configs/                    — Backed-up device configs (Oxidized-style)
```

**Every deployer implements a standard interface:**
- `get_facts(ip, key_path)` — hostname, model, serial, OS version, uptime
- `get_interfaces(ip, key_path)` — name, status, speed, description, MTU, counters
- `get_vlans(ip, key_path)` — VLAN ID, name, port membership
- `get_mac_table(ip, key_path)` — MAC, VLAN, interface, static/dynamic
- `get_arp_table(ip, key_path)` — IP, MAC, interface
- `get_neighbors(ip, key_path)` — LLDP/CDP neighbor data
- `get_config(ip, key_path)` — running-config text
- `get_environment(ip, key_path)` — temp, fans, power, CPU, memory
- `push_config(ip, key_path, lines)` — send config lines in config mode
- `save_config(ip, key_path)` — write running to startup

Each deployer implements these by SSH-ing the vendor-specific show commands and parsing output into a common dict structure. Same `ssh.py` transport, same LEGACY_HTYPES cipher handling that already works for the Cisco switch in DC01.

### Commands — Core Switch Management

| Command | What It Does | Builds On |
|---|---|---|
| `freq switch show <target>` | All interfaces, VLANs, status (vendor-agnostic) | Extends existing `switch status` action |
| `freq switch facts <target>` | Device facts: hostname, model, serial, OS, uptime | New getter, via deployer |
| `freq switch interfaces <target>` | Interface table with status, speed, errors | Extends existing `switch interfaces` action |
| `freq switch counters <target>` | Per-interface TX/RX, errors, discards, drops | New getter |
| `freq switch vlans <target>` | All VLANs with port membership | Extends existing `switch vlans` action |
| `freq switch mac <target>` | MAC address table | Extends existing `switch mac` action |
| `freq switch arp <target>` | ARP table | Extends existing `switch arp` action |
| `freq switch neighbors <target>` | LLDP/CDP neighbors (--detail for full) | New getter, feeds `depmap.py` topology |
| `freq switch environment <target>` | Temperature, fans, PSU, CPU, memory | New getter |
| `freq switch config <target>` | Display running-config | New getter, foundation for config backup |
| `freq switch exec <target> "<command>"` | Run arbitrary show command | New — raw SSH pass-through |
| `freq switch exec --all "<command>"` | Run across ALL switches in parallel | Uses `ssh_run_many()` with switch hosts from `hosts.conf` |

### Commands — Port Management

| Command | What It Does |
|---|---|
| `freq port status <target>` | Per-port: link, speed, VLAN, PoE, connected device |
| `freq port configure <target> <port> [--vlan N] [--mode access/trunk] [--shutdown/--no-shutdown]` | Configure a single port |
| `freq port desc <target> <port> --description "Camera-Lobby-1"` | Set port description |
| `freq port poe <target>` | PoE status per port (watts, budget remaining) |
| `freq port poe <target> --port N --off/--on` | Toggle PoE on a port (bounce a device) |
| `freq port find <target> --mac XX:XX` | Find which port a MAC is on |
| `freq port flap <target> --port N` | Bounce a port (shut/no shut) |
| `freq port mirror <target> --source N --destination N` | Configure port mirroring |
| `freq port security status/enable/violations <target>` | Port security management |

### Commands — Port Profiles (The Key Differentiator)

Stored in `conf/switch-profiles.toml`, loaded via `tomllib` (same pattern as `vlans.toml`):

```toml
# conf/switch-profiles.toml
[profile.media-access]
description = "Media workstation — single VLAN access"
mode = "access"
vlan = 100
speed = "auto"
spanning_tree = "portfast"

[profile.trunk-uplink]
description = "Uplink to distribution switch"
mode = "trunk"
allowed_vlans = [1, 10, 25, 100, 200, 2550]
native_vlan = 1

[profile.camera]
description = "IP camera — isolated VLAN, PoE enabled"
mode = "access"
vlan = 50
poe = true
port_security = { max_mac = 1, violation = "restrict" }

[profile.dead]
description = "Unused port — shutdown"
shutdown = true
```

| Command | What It Does |
|---|---|
| `freq switch profile create <name>` | Create reusable port profile |
| `freq switch profile apply <profile> <port-range>` | Apply to range (Gi1/1-24 → 24 ports) |
| `freq switch profile list/show/delete` | Profile management |

### Commands — Config Backup & Compliance (Oxidized-style)

Configs stored in `conf/switch-configs/` as timestamped text files:

| Command | What It Does | Integration |
|---|---|---|
| `freq config backup <target>/--all` | Pull and store running-config | Uses deployer `get_config()` |
| `freq config history <target>` | Config change history | Local file diffs |
| `freq config diff <target>` | Diff running vs last backup | |
| `freq config search "<pattern>"` | Search across ALL device configs | |
| `freq config compliance` | Check devices against rules | **Extends `engine/` policy system** with network-device policies |
| `freq config restore <target> --version N` | Push previous config back | Uses deployer `push_config()` |

### Commands — Network Protocol Management

| Command | What It Does |
|---|---|
| `freq stp status/root/topology/check` | STP monitoring, root verification |
| `freq qos status/policy create/apply` | QoS management |
| `freq acl list/create/apply/test/audit` | ACL management |
| `freq dot1x status/sessions/enable` | 802.1X port authentication |

### Commands — Event Network Lifecycle

Stored in `conf/event-templates/<name>.toml`:

| Command | What It Does | Integration |
|---|---|---|
| `freq event create "<name>"` | Create event project | Creates TOML template in `conf/event-templates/` |
| `freq event plan` | Generate IP plan, VLAN allocation | Uses `ipam.py` for IP allocation, `vlans.toml` |
| `freq event deploy --site <name>` | Push configs to all site switches | Uses deployer `push_config()` in parallel via `ssh_run_many()` |
| `freq event verify --site <name>` | Verify all switches correct | Uses getters to validate against template |
| `freq event preflight --report` | Full checklist with pass/fail | Combines switch + DNS + DHCP + firewall checks |
| `freq event wipe --confirm` | Reset ALL switches to default | Uses deployer `push_config()` with factory defaults |
| `freq event archive "<name>"` | Archive configs + reports | Saves to `conf/event-archives/` |

---

## WORKSTREAM 2: Network Intelligence

### How It Connects

**Starting points:**
- `netmon.py` (347 lines) — already has `interfaces`, `poll`, `bandwidth`, `topology` via `/sys/class/net` on Linux hosts
- `depmap.py` (356 lines) — already has `map discover`, `map impact`, `map export` for service dependency mapping
- `ipam.py` (374 lines) — already has `ip next`, `ip list`, `ip check`
- `discover.py` (276 lines) — already has ping sweep + SSH fingerprinting
- `compare.py` (261 lines) — already has side-by-side host comparison

**What changes:**
1. **netmon.py extends** with SNMP polling (shells out to `snmpget`/`snmpwalk` from net-snmp package) and NetFlow/sFlow collection
2. **depmap.py extends** with LLDP/CDP-based topology from switch getters (WS1)
3. **ipam.py extends** with subnet utilization, conflict detection, visual IP maps
4. **New module** `freq/modules/snmp.py` if SNMP features exceed ~200 lines
5. **New config section** `[snmp]` in freq.toml for community strings, SNMPv3 credentials
6. **Data stored** in `conf/snmp/` (poll results) and `conf/topology/` (discovered maps)

### Commands

| Command | What It Does | Builds On |
|---|---|---|
| `freq snmp poll <target>/--all` | SNMP poll (interfaces, CPU, mem, uptime) | New — shells to `snmpget`/`snmpwalk` |
| `freq snmp interfaces/errors/optics/cpu <target>` | Specific SNMP data | New |
| `freq snmp discover <subnet>` | SNMP-based device discovery | Extends `discover.py` |
| `freq topology discover` | Crawl network via LLDP/CDP | Extends `depmap.py` using WS1 switch getters |
| `freq topology show/export/diff/verify` | Topology management | Extends `depmap.py` export format |
| `freq flow enable/top-talkers/protocols/search/anomaly` | Traffic analysis | New module or extend `netmon.py` |
| `freq net health/find-mac/find-ip/trace/rogue` | Network intelligence | New — combines SNMP + switch MAC tables |
| `freq ip utilization/conflict/map/calc` | Enhanced IPAM | Extends `ipam.py` |
| `freq troubleshoot <ip-or-mac>` | Automated debug workflow | New — chains switch/DHCP/DNS/ping checks |

---

## WORKSTREAM 3: Firewall & Gateway Deep

### How It Connects

**Starting point:** `infrastructure.py` has 7 pfSense actions via `_device_cmd()`: `status`, `rules`, `nat`, `states`, `interfaces`, `gateways`, `services`. These run predefined SSH commands on pfSense.

**What changes:**
1. **pfSense graduates to its own module** `freq/modules/firewall.py` — the 7 existing actions move there and expand to ~50 commands
2. **REST API integration** — pfSense has the `pfrest` package REST API. New commands use `urllib.request` (stdlib) to hit REST endpoints instead of SSH-only
3. **New deployer** `deployers/firewall/opnsense.py` (OPNsense has a first-party REST API)
4. **New config section** `[pfsense]` in freq.toml expands with API token path
5. **Data stored** in `conf/firewall/` (rule backups, DHCP exports)

### Commands — Firewall Rules (extends existing `freq pfsense rules`)

| Command | What It Does |
|---|---|
| `freq fw rules list/create/delete/enable/disable/move` | Full CRUD + reorder |
| `freq fw rules apply/diff/audit/test` | Apply pending, preview changes, find shadowed rules, simulate traffic |
| `freq fw rules export/import` | Backup/restore |

### Commands — NAT (extends existing `freq pfsense nat`)

| Command | What It Does |
|---|---|
| `freq fw nat list/forward create/delete/enable/disable` | Port forward management |
| `freq fw nat test --external-port 8443` | Where does this forward to? |

### Commands — DHCP, DNS, QoS, pfBlockerNG, IDS, Gateways, HA, Captive Portal

See full command tables in workstream detail (same as previous plan version). Each group follows the `_device_cmd()` action-dict pattern or REST API calls.

---

## WORKSTREAM 4: DNS Management

### How It Connects

**Starting point:** `dns.py` (303 lines) already has `dns scan` (fleet-wide forward/reverse validation), `dns check` (single host), `dns list` (DNS inventory). Uses `socket.getaddrinfo()` and `socket.gethostbyaddr()` from stdlib. Stores results in `conf/dns/dns-inventory.json`.

**What changes:**
1. **dns.py extends** with Pi-hole/AdGuard/Unbound/BIND backends via their HTTP APIs (`urllib.request`) or SSH
2. **New config section** `[dns]` in freq.toml with backend type, API URLs, credentials path
3. **Unified internal DNS interface** — `freq dns internal sync` takes fleet inventory from `hosts.conf` and pushes A/PTR records to whichever DNS backend is configured
4. **Data stored** in existing `conf/dns/` directory

### Commands

| Command | What It Does | Builds On |
|---|---|---|
| `freq dns internal list/add/remove/sync/audit` | Unified DNS management | Extends `dns.py` with write operations |
| `freq dns internal bulk-register --from-dhcp/--from-inventory` | Bulk DNS from fleet data | Uses `hosts.conf` and DHCP lease data |
| `freq dns pihole status/blocking/lists/whitelist/query-log/test` | Pi-hole management | New — Pi-hole v6 REST API via `urllib` |
| `freq dns adguard status/rewrites/clients/filters/tls` | AdGuard Home management | New — AdGuard REST API via `urllib` |
| `freq dns unbound local-data/cache/forward-zone/rpz` | Unbound management | New — SSH to pfSense/host, edit unbound.conf |

---

## WORKSTREAM 5: VPN Management

### How It Connects

**Starting point:** No existing VPN module. pfSense VPN is mentioned in `infrastructure.py` but not implemented. WireGuard peer creation was on the feature wishlist (see memory: `project_freq_feature_wishlist.md`).

**What changes:**
1. **New module** `freq/modules/vpn.py`
2. **pfSense WireGuard** via REST API (if pfrest package installed) or SSH
3. **pfSense OpenVPN** via REST API or config.xml parsing over SSH
4. **Tailscale/Headscale** via their REST APIs (`urllib`)
5. **New config section** `[vpn]` in freq.toml

### Commands (highlights)

| Command | What It Does |
|---|---|
| `freq vpn wg peers add/remove/qr/export/provision` | WireGuard peer lifecycle |
| `freq vpn wg status [--watch]/audit` | Live status, stale peer detection |
| `freq vpn ovpn certs list/create/revoke/export` | OpenVPN certificate lifecycle |
| `freq vpn tailscale devices/routes/dns/keys/acl` | Tailscale/Headscale management |
| `freq vpn ipsec tunnels/status/logs/debug/audit` | IPsec tunnel management |

---

## WORKSTREAM 6: Certificate & PKI

### How It Connects

**Starting point:** `cert.py` (382 lines) already has `cert scan` (connect to fleet hosts on common ports, check TLS), `cert list` (show inventory), `cert check` (single endpoint). Uses `ssl` and `socket` from stdlib. Stores in `conf/certs/cert-inventory.json`.

**What changes:**
1. **cert.py extends** with ACME issuance (shells to `certbot` or uses stdlib `urllib` against ACME API), private CA management (shells to `step-ca`), and fleet cert deployment (SCP via `ssh.py`)
2. **New data** in `conf/certs/` — issued certs, CA config, renewal hooks
3. **Integration:** `freq certs acme deploy --target proxmox` uses PVE API to upload cert. `--target pfsense` uses pfSense REST API. `--target nginx` uses SSH to copy files.

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq certs inventory/fleet-check` | All certs everywhere | Extends existing `cert scan` |
| `freq certs acme issue/renew/deploy/audit` | Let's Encrypt lifecycle | New — `certbot` CLI or ACME protocol |
| `freq certs ca issue/revoke/distribute/ssh-cert` | Private CA | New — `step-ca` CLI |
| `freq certs inspect/convert/audit/report` | Certificate tooling | Extends existing `cert.py` |

---

## WORKSTREAM 7: Reverse Proxy Management

### How It Connects

**Starting point:** `proxy.py` (268 lines) already has `proxy status` (detect running proxies on fleet), `proxy list` (show managed routes from `conf/proxy/routes.json`), `proxy add/remove` (manage routes), `proxy certs` (cert status for proxy routes).

**What changes:**
1. **proxy.py extends** with backend-specific API integration — NPM, Caddy, Traefik, and HAProxy all have HTTP APIs that `urllib.request` can hit
2. **Auto-detection** — `proxy status` already detects which proxy is running; new code uses the detected backend's API
3. **New config section** `[proxy]` in freq.toml with backend type and API URL

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq proxy npm hosts create/ssl provision/streams/access-lists` | NPM API | Extends `proxy.py` with NPM REST calls |
| `freq proxy caddy hosts create/tls/middleware` | Caddy admin API | New backend in `proxy.py` |
| `freq proxy traefik routers/services/middlewares/health` | Traefik API | New backend |
| `freq proxy haproxy stats/servers drain/set-weight` | HAProxy stats socket | New backend |

---

## WORKSTREAM 8: Storage Deep Dive

### How It Connects

**Starting point:** `infrastructure.py` has 7 TrueNAS actions via `_device_cmd()`: `status`, `pools`, `datasets`, `snapshots`, `disks`, `alerts`, `replication`. These SSH to TrueNAS and run `midclt call` commands. Also `zfs.py` may exist for direct ZFS operations.

**What changes:**
1. **TrueNAS graduates to its own module** `freq/modules/truenas.py` — 7 existing actions expand to ~50 commands covering datasets, snapshots, replication, SMART, scrubs, shares (SMB/NFS/iSCSI)
2. **ZFS module extends** with direct ZFS commands on any fleet host (not just TrueNAS) — pool ops, send/receive, encryption
3. **New modules** for Ceph (`freq/modules/ceph.py`) and MinIO (`freq/modules/minio.py`) if needed
4. **Fleet-wide share audit** — NFS/SMB discovery across all hosts via SSH

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq truenas dataset/snap/repl/smart/scrub/alert/share` | Full TrueNAS API | Extends existing infrastructure.py actions |
| `freq zfs pool/ds/snap/send/encrypt/arc` | Direct ZFS on any host | Extends via `ssh_run()` to fleet hosts |
| `freq share list/nfs/smb/audit/mount test` | Fleet-wide share management | New — `ssh_run_many()` with `showmount`/`smbclient` |

---

## WORKSTREAM 9: Disaster Recovery

### How It Connects

**Starting points:**
- `backup.py` (251 lines) — `backup status`, `backup prune`
- `backup_policy.py` (375 lines) — `backup-policy list/create/apply` (declarative backup rules)
- `rollback.py` (199 lines) — `rollback <vmid>` (restore VM from latest snapshot)
- `sla.py` (262 lines) — `sla show/check` (uptime tracking)
- `snapshot` commands in `vm.py` — `snapshot create/list/delete`

**What changes:**
1. **New module** `freq/modules/dr.py` — orchestrates backup/restore/failover using PVE API + PBS API
2. **sla.py extends** with RTO/RPO targets per VM (stored in `conf/dr/sla-targets.json`)
3. **backup_policy.py extends** with RPO enforcement (check: "when was the last backup? does it meet the RPO?")
4. **New concept: DR runbooks** — ordered recovery procedures stored in `conf/dr/runbooks/`
5. **PBS integration** via REST API (`urllib`) for datastore management, verification, pruning

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq dr backup list/create/verify/restore/sla` | Backup orchestration | Extends `backup.py` + PVE API |
| `freq dr backup instant-restore <id>` | Boot VM from backup for verification | New — PVE API |
| `freq dr replicate/failover/failback` | VM replication and failover | New — PVE replication API |
| `freq dr runbook list/create/execute/test` | Ordered recovery procedures | New — extends `jarvis/playbook.py` pattern |
| `freq dr sla list/set/status/report/alert` | RTO/RPO tracking | Extends `sla.py` |
| `freq dr test tabletop/simulation/failover` | DR testing at every level | New |
| `freq pbs status/backup/verify/prune/gc/sync` | PBS management | New — PBS REST API via `urllib` |

---

## WORKSTREAM 10: Observability Platform

### How It Connects

**Starting points:**
- `alert.py` (712 lines) — full alert engine with rules, history, silence, test, escalation
- `logs.py` (280 lines) — `logs tail/search/stats`
- `trend.py` (328 lines) — `trend show/snapshot` with sparklines
- `report.py` (374 lines) — fleet health reports
- `health.py` (223 lines) — comprehensive fleet health
- `netmon.py` (347 lines) — interface monitoring
- `jarvis/capacity.py` (458 lines) — capacity projections
- `jarvis/notify.py` (356 lines) — notification delivery

**What changes:**
1. **New module** `freq/modules/metrics.py` — time-series metric collection, storage in `conf/metrics/` as JSON per host, query interface
2. **logs.py extends** with fleet-wide aggregation, pattern detection, rate queries
3. **trend.py extends** with predictive analytics (`predict_linear` style)
4. **alert.py extends** with metric-based alerting (not just condition checks)
5. **New module** `freq/modules/monitors.py` — synthetic monitoring (HTTP, TCP, DNS, SSL checks)
6. **New module** `freq/modules/status_page.py` — public/private status page generation
7. **Metrics collection** via `ssh_run_many()` reading `/proc/stat`, `/proc/meminfo`, `df`, etc. — same pattern health.py already uses

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq metrics collect/show/history/top/query` | Time-series metrics | New — pattern from `health.py` data collection |
| `freq metrics predict/anomalies/baseline/drift` | Analytics | Extends `trend.py` and `jarvis/capacity.py` |
| `freq logs tail --fleet/search/count/errors/rate/pattern` | Enhanced log management | Extends `logs.py` |
| `freq monitor http/ssl/dns/port/ping/list/schedule` | Synthetic monitoring | New module |
| `freq uptime report/sla/mttr/mttf` | Uptime analytics | Extends `sla.py` |
| `freq status-page create/show/incident/maintenance/generate` | Status pages | New module |
| `freq cron list/register/ping/wrap/audit` | Cron job monitoring | New — dead man's switch pattern |

---

## WORKSTREAM 11: Security & Compliance

### How It Connects

**Starting points:**
- `audit.py` (329 lines) — `audit [--fix]` checks SSH config, open ports, sudo, services, world-writable files
- `harden.py` (142 lines) — `harden <target>` applies SSH hardening, sysctl tuning
- `comply.py` (384 lines) — `comply scan/report` does CIS Level 1 scanning
- `secrets.py` (356 lines) — `secrets scan/audit/generate/lease`
- `patch.py` (432 lines) — `patch status/check/apply/compliance`
- `jarvis/sweep.py` (114 lines) — full audit + policy pipeline

**What changes:**
1. **comply.py extends massively** — from basic CIS L1 to full CIS L1+L2 with per-section scanning, auto-remediation with dry-run, exception tracking, STIG compliance
2. **audit.py extends** with Lynis-style scoring (0-100 hardening index), category-specific audits
3. **New module** `freq/modules/vuln.py` — vulnerability scanning (checks installed package versions against CVE databases via `apt list --installed` + offline CVE data or online API)
4. **New module** `freq/modules/fim.py` — file integrity monitoring (baseline file hashes in `conf/fim/`, detect changes)
5. **secrets.py extends** with container image scanning (parse `docker inspect` output for env vars)
6. **harden.py extends** with full CIS remediation (not just SSH+sysctl)
7. **All security checks register as policies** in the `engine/` policy system where possible

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq vuln scan/results/cves/exploitable/trend/sla` | Vulnerability scanning | New module |
| `freq cis scan/results/score/fix/exceptions` | Full CIS benchmarks | Extends `comply.py` |
| `freq audit score/ssh/firewall/docker/kernel/users` | Category auditing | Extends `audit.py` |
| `freq harden --auto/--preview/ssh/kernel/network` | Targeted hardening | Extends `harden.py` |
| `freq fim status/changes/baseline/whochanged` | File integrity | New module |
| `freq ban status/list/top-offenders/add/remove` | Fail2ban/CrowdSec | New — SSH to fleet hosts |
| `freq container scan/images/sbom/secret scan` | Container security | New — shells to `trivy` or parses package lists |

---

## WORKSTREAM 12: Incident & Change Management

### How It Connects

**Starting points:**
- `jarvis/playbook.py` (273 lines) — `playbook list/run` (incident playbooks)
- `jarvis/risk.py` (161 lines) — `risk <target>` (blast radius analysis)
- `jarvis/notify.py` (356 lines) — notification delivery to Discord/Slack/email

**What changes:**
1. **New module** `freq/modules/incident.py` — incident tracking stored in `conf/incidents/`
2. **New module** `freq/modules/change.py` — change management stored in `conf/changes/`
3. **risk.py extends** with change risk assessment (link incidents to changes)
4. **playbook.py extends** with postmortem generation from incident timeline
5. **New module** `freq/modules/cmdb.py` — auto-discovered CMDB from fleet data

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq incident create/list/update/close/timeline/stats` | Incident tracking | New — uses `jarvis/notify.py` for alerts |
| `freq change create/approve/implement/rollback/freeze` | Change management | New |
| `freq change window list/create/active` | Maintenance windows | New — integrates with `alert.py` silence |
| `freq problem create/rca/workaround/close` | Problem management | New |
| `freq postmortem create/list/show` | Post-mortem generation | Extends `jarvis/playbook.py` |
| `freq cmdb list/detail/impact/scan/diff` | Auto-discovered CMDB | New — pulls from `hosts.conf` + PVE API + fleet data |
| `freq asset list/warranty/lifecycle/age report` | Asset tracking | New — stored in `conf/assets/` |

---

## WORKSTREAM 13: Docker Fleet Deep

### How It Connects

**Starting points:**
- `stack.py` (427 lines) — `stack status/update/health` (Docker Compose fleet management)
- `fleet.py` (1,500 lines) — `docker <host>` action for container management on individual hosts
- `docker-fleet` commands may exist for fleet-wide container operations

**What changes:**
1. **stack.py extends** with rolling deploys, blue-green, canary patterns
2. **New module** `freq/modules/docker_mgmt.py` — fleet-wide container/volume/network/image management
3. **Auto-update** — Watchtower-replacement functionality (check for image updates, apply with rollback)
4. **All Docker commands use** `ssh_run_many()` to Docker hosts (identified by `type=docker` in `hosts.conf`)

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq docker stack list/deploy/update/destroy/logs/health/diff` | Stack management | Extends `stack.py` |
| `freq docker container list/inspect/restart/logs/exec/stats` | Container ops | Extends `fleet.py` docker actions |
| `freq docker volume/network/image list/prune/backup` | Resource management | New |
| `freq docker update check/apply/rollback/schedule/policy` | Auto-update | New — replaces Watchtower |
| `freq docker deploy rolling/blue-green/canary` | Deploy strategies | New |
| `freq docker secrets list/create/rotate` | Secret management | New |

---

## WORKSTREAM 14: Hardware Management

### How It Connects

**Starting point:** `infrastructure.py` has 5 iDRAC actions via `_device_cmd()`: `status`, `sel`, `sensors`, `power`, `storage`. These SSH to iDRAC and run `racadm` commands. Deployer at `deployers/bmc/idrac.py` handles `deploy()`/`remove()`.

**What changes:**
1. **iDRAC graduates to its own module** `freq/modules/idrac.py` — 5 actions expand to ~35 using Redfish REST API (`urllib.request` to `https://<idrac-ip>/redfish/v1/`)
2. **New module** `freq/modules/ipmi.py` — for non-Dell servers, shells to `ipmitool`
3. **New module** `freq/modules/smart.py` — fleet-wide SMART monitoring via `ssh_run_many()` + `smartctl`
4. **UPS/PDU management** — new section using NUT (`upsc`/`upscmd` commands via SSH)
5. **jarvis/cost.py extends** with real power data from iDRAC/IPMI sensors instead of estimates

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq idrac status/power/thermal/storage/firmware/sel/bios/inventory` | Full Redfish | Extends existing infrastructure.py |
| `freq ipmi power/sensor/sel/boot/sol/fru` | Generic BMC | New — `ipmitool` via SSH/local |
| `freq smart status/detail/test/failing/predict/report` | Disk health | New — `smartctl` via `ssh_run_many()` |
| `freq ups status/battery/load/runtime/test` | UPS monitoring | New — NUT `upsc` commands |
| `freq pdu list/status/outlet on/off/cycle` | PDU management | New — SNMP or NUT |

---

## WORKSTREAM 15: Infrastructure as Code

### How It Connects

**Starting points:**
- `baseline.py` (379 lines) — `baseline capture/compare` (config drift detection)
- `plan.py` (549 lines) — `plan/apply` (declarative VM desired state from `fleet-plan.toml`)
- `engine/` (388 lines) — policy engine with declarative compliance
- `jarvis/gitops.py` (379 lines) — `gitops status/sync/apply/diff`
- `jarvis/federation.py` (315 lines) — multi-site management

**What changes:**
1. **plan.py extends** from VM-only to full infrastructure (VMs + network + firewall + DNS)
2. **baseline.py extends** into infrastructure-wide snapshots (not just host config)
3. **gitops.py extends** with infrastructure state export/import
4. **New concept: state file** — `conf/state/infrastructure.toml` as the single source of truth
5. **Drift detection** across ALL device types (VMs, switches, firewalls, DNS) — combines policy engine + device getters

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq state export/snapshot/history/rollback` | Infrastructure state | Extends `baseline.py` + `jarvis/gitops.py` |
| `freq plan --state infrastructure.toml` | Diff desired vs actual | Extends `plan.py` from VM-only to everything |
| `freq apply --state infrastructure.toml` | Execute the plan | Extends `plan.py` |
| `freq drift detect/fix [--dry-run]` | Cross-device drift | Extends `baseline.py` + `engine/` policies |
| `freq import vm/ct/switch/all` | Bring existing infra under management | New |

---

## WORKSTREAM 16: Automation Engine

### How It Connects

**Starting points:**
- `jarvis/rules.py` (466 lines) — `rules list/create/delete` (alert rules)
- `jarvis/patrol.py` (166 lines) — continuous monitoring + drift detection
- `jarvis/playbook.py` (273 lines) — `playbook list/run`
- `schedule.py` (432 lines) — `schedule list/create/delete/run/templates/install` (cron job management)
- `vault.py` (339 lines) — encrypted credential store
- `jarvis/notify.py` (356 lines) — notification delivery

**What changes:**
1. **rules.py evolves** into a full event-driven reactor (if event X, then action Y)
2. **patrol.py extends** with beacon-style monitoring (watch conditions, emit events)
3. **playbook.py extends** into a full workflow engine (DAGs, not just linear steps)
4. **New concept: event bus** — events emitted by all freq operations, reactors subscribe
5. **New concept: auto-remediation** — detect + fix + verify + notify loop with cooldowns
6. **Human-in-the-loop** — approval gates for destructive operations

### Commands (highlights)

| Command | What It Does | Builds On |
|---|---|---|
| `freq events tail/history` | Live event stream | New — foundation for reactive automation |
| `freq react add/list/disable/test/log` | Self-healing rules | Extends `jarvis/rules.py` |
| `freq workflow create/run/status/resume/cancel` | DAG orchestration | Extends `jarvis/playbook.py` |
| `freq approve list/approve/deny` | Human-in-the-loop | New |
| `freq job list/run/create/schedule/history` | Named operations | Extends `schedule.py` |
| `freq runbook capture/list/replay` | Record + replay CLI sessions | New |
| `freq remediate configure/history/test` | Self-healing playbooks | New — uses reactor + notify |
| `freq anomaly detect/watch/explain` | Statistical anomaly detection | Extends `jarvis/capacity.py` trend analysis |
| `freq predict disk/capacity/failures` | Predictive maintenance | Extends `trend.py` + `jarvis/capacity.py` |

---

## WORKSTREAM 17: Fleet Commands (Easy Builds)

### How It Connects

All of these are straightforward `ssh_run()` or `ssh_run_many()` calls to fleet hosts. They follow the exact same pattern as existing fleet commands in `fleet.py`. Each is ~100-300 lines.

| Command | What It Does | Pattern |
|---|---|---|
| `freq service list/control/watch <host>` | Remote systemd management | `ssh_run()` + `systemctl` |
| `freq session list/kill` | SSH sessions fleet-wide | `ssh_run_many()` + `who`/`pkill` |
| `freq bandwidth test <host-a> <host-b>` | iperf3 test | `ssh_run()` on both hosts |
| `freq traceroute <target>` | Traceroute | `ssh_run()` + `traceroute` |
| `freq arp scan [--vlan N]` | ARP scan subnet | `ssh_run()` + `arp-scan` |
| `freq config push/pull/diff <host> --file <path>` | Config file management | `ssh_run()` + SCP pattern from `file send` |
| `freq backup now/list/restore <vmid>` | Immediate VM backup | PVE API (`vzdump`) |
| `freq metric collect/query/alert/export` | Time-series metrics | `ssh_run_many()` + `/proc` parsing |

---

## WORKSTREAM 18: Public Access Wizard

### How It Connects

Chains together features from WS3 (firewall NAT), WS4 (DNS), WS6 (certificates), and WS7 (reverse proxy) into one guided flow.

| Command | What It Does | Uses |
|---|---|---|
| `freq publish setup` | Interactive wizard | `proxy.py` + `cert.py` + `infrastructure.py` pfSense NAT/DNS |
| `freq publish status` | Current state | Checks proxy + cert + firewall + DNS |
| `freq publish teardown` | Remove everything | Reverses all of the above |

---

## WORKSTREAM 19: Plugin System

### How It Connects

**Starting point:** `cli.py` already discovers plugins from `conf/plugins/` and loads them dynamically. The `deployers/` registry already supports adding new vendors by dropping a file.

**What changes:**
1. **Formalize the plugin interface** — document required exports, provide scaffold template
2. **Plugin manager commands** — install from URL, list installed, update
3. **Community deployers** — MikroTik, Palo Alto, F5 as installable plugins

| Command | What It Does |
|---|---|
| `freq plugin list/install/remove/update/search` | Plugin management |
| `freq plugin create --name my-plugin` | Scaffold new plugin |

---

## WORKSTREAM 20: Dashboard Pages

### How It Connects

All pages follow the existing `serve.py` pattern:
1. **Backend:** Add API endpoint(s) to serve.py that call the relevant module functions
2. **Frontend:** Add a page section to `app.html` SPA with data fetching from the new API endpoints
3. **Live updates:** SSE events for real-time data (existing pattern)

20 new dashboard pages planned (see previous plan version for full table).

---

## WORKSTREAM 21: E2E Testing

Follows existing test structure in `tests/` (45+ files organized by phase). Each new workstream gets a corresponding test file. See `E2E-TEST-PLAN.md` in this directory.

---

## EXECUTION ORDER

```
PHASE 1 — The Network (WS 1-2)
  Switch Orchestration + Event Networking    ← THE differentiator
  Network Intelligence (SNMP, topology, flow)
  
  WHY FIRST: Sonny's killer feature. Builds the deployer getter
  interface that all other device management uses.

PHASE 2 — The Gateway (WS 3-7)
  Firewall Deep → DNS → VPN → Certs → Proxy
  
  WHY SECOND: These all talk to pfSense and web services.
  WS3 establishes the REST API pattern that WS4-7 reuse.

PHASE 3 — The Foundation (WS 8-9)
  Storage Deep Dive → Disaster Recovery
  
  WHY THIRD: DR depends on storage management. Storage
  extends existing TrueNAS/ZFS commands.

PHASE 4 — The Eyes (WS 10-11)
  Observability → Security & Compliance
  
  WHY FOURTH: Monitoring and security need the device
  management from Phases 1-3 to be complete.

PHASE 5 — The Brain (WS 12, 15-16)
  Incident/Change Mgmt → IaC → Automation Engine
  
  WHY FIFTH: Automation needs everything else to exist
  first — it orchestrates the features from Phases 1-4.

PHASE 6 — The Fleet (WS 13-14, 17-18)
  Docker Deep → Hardware → Fleet Commands → Public Access
  
  WHY SIXTH: Easy builds and extensions. Docker and hardware
  follow established patterns.

PHASE 7 — The Ecosystem (WS 19)
  Plugin System
  
  WHY SEVENTH: Formalize what already works (conf/plugins/,
  deployer registry) after the architecture is proven.

PHASE 8 — The Face (WS 20)
  Dashboard Pages for everything

PHASE 9 — The Proof (WS 21)
  E2E Testing against live infrastructure
```

---

## WHAT THIS MAKES FREQ

When complete, FREQ replaces:

| Tool | $ Cost | What FREQ Does Instead | Which Workstream |
|---|---|---|---|
| Ansible/Salt/Puppet | Free-$15K | `freq state apply`, config push, rolling updates | WS15, WS16, WS17 |
| Terraform | Free-$$$  | `freq plan`/`freq apply` for VMs + network + firewall | WS15 |
| Oxidized/RANCID | Free | `freq config backup/diff/history/search` | WS1 |
| NetBox/phpIPAM | Free-$7.5K | `freq ip`, `freq cable`, `freq cmdb` | WS2, WS12 |
| LibreNMS/Zabbix | Free | `freq snmp poll`, `freq metrics`, `freq monitor` | WS2, WS10 |
| Datadog | $15/host/mo | `freq metrics collect/query/predict/anomalies` | WS10 |
| Splunk/ELK | Free-$$$  | `freq logs search/rate/pattern` | WS10 |
| Nessus/OpenVAS | Free-$3.5K | `freq vuln scan`, `freq cis scan` | WS11 |
| Wazuh/OSSEC | Free | `freq fim`, `freq rootkit scan` | WS11 |
| PagerDuty/Opsgenie | $21/user/mo | `freq incident`, `freq oncall`, `freq escalation` | WS12 |
| Uptime Kuma | Free | `freq monitor`, `freq status-page` | WS10 |
| Veeam | $$$$ | `freq dr backup/replicate/failover/sla` | WS9 |
| Portainer | Free-$$$  | `freq docker stack/container/volume` fleet-wide | WS13 |
| ServiceNow | $100/user/mo | `freq incident/change/problem/cmdb/asset` | WS12 |
| Gremlin | $10K+/yr | `freq chaos monkey/experiment/partition` | Already built (jarvis/chaos.py) |
| Let's Encrypt CLI | Free | `freq certs acme issue/renew/deploy` | WS6 |
| NPM/Caddy/Traefik | Free | `freq proxy npm/caddy/traefik/haproxy` | WS7 |
| Pi-hole/AdGuard | Free | `freq dns pihole/adguard` | WS4 |
| Cisco DNA Center | $15K+ | `freq net health`, `freq firmware`, `freq template deploy` | WS1, WS2 |
| SolarWinds NCM | $2.5K+ | `freq config compliance`, `freq config watch` | WS1 |

**One CLI. One state model. One auth system. Every layer of the stack.**

---

## WHAT I WILL NOT DO

- I will not start testing before features are complete.
- I will not create new patterns when existing ones work — extend, don't reinvent.
- I will not add pip dependencies — everything uses stdlib + system commands.
- I will not touch freq-ops. Ever.
- I will not call TrueNAS, switches, pfSense, or iDRAC "edge cases." They are core infrastructure.
- I will not hand-deploy anything. freq's tools do the deploying.
- I will not skip the plan. This document is the plan. Follow it.
- I will not let perfect be the enemy of shipped. Build, test, ship, iterate.
