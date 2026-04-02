# Changelog

All notable changes to PVE FREQ will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [3.0.0] - Unreleased

### The Conquest — Complete Platform Rewrite

**156 files changed, +23,622 / -1,973 lines across 26 commits on v3-rewrite.**

### Added

#### Phase 0 — Foundation
- **Domain dispatch CLI** — `freq <domain> <action>` replaces 126 flat commands with 25 organized domains
- **Platform abstraction layer** — `freq/core/platform.py`, `remote_platform.py`, `packages.py`, `services.py` for multi-distro support
- **Domain-based API router** — `freq/api/` with 15 domain modules, 163+ routes extracted from serve.py
- **SOURCE-CODE-STANDARDS** — 5-question header docstrings applied to all 91 .py files

#### Phase 1 — The Network (WS1-2)
- `freq net switch` — 10 switch management commands (facts, interfaces, vlans, mac, arp, neighbors, config, environment, exec, save)
- `freq net port` — port management with TOML-based profiles (status, configure, find, poe)
- `freq net config` — Oxidized-style config backup, diff, search, restore
- `freq event` — full event network lifecycle (create, plan, deploy, verify, wipe, archive, delete)
- `freq net snmp/topology/find-mac/find-ip/troubleshoot/ip-util/ip-conflict` — 15 network intelligence commands
- Cisco IOS/IOS-XE deployer with 20+ getter/setter functions
- `conf/switch-profiles.toml` — 4 default port profiles

#### Phase 2 — The Gateway (WS3-7)
- `freq fw` — 7 firewall management commands (rules, nat, states, interfaces, aliases, logs, backup)
- `freq dns` — internal DNS management (scan, check, list, add, remove)
- `freq vpn` — WireGuard and OpenVPN management (wg status/peers/audit, ovpn status)
- `freq cert` — TLS certificate lifecycle (scan, list, check, renew, inventory)
- `freq proxy` — reverse proxy management (status, list, add, remove, health, drain)

#### Phase 3 — The Foundation (WS8-9)
- `freq store` — 7 storage management commands (nas status, zfs pool/snapshot/scrub, capacity, health, volumes)
- `freq dr` — disaster recovery with SLA tracking and runbooks (backup, policy, sla, runbook, journal, test)

#### Phase 4 — The Eyes (WS10-11)
- `freq observe metrics` — fleet-wide metrics collection (top, history, export, alerts)
- `freq observe monitor` — synthetic HTTP/TCP endpoint monitoring (list, add, check, status)
- `freq secure vuln` — vulnerability scanning (scan, report, track, fix)
- `freq secure fim` — file integrity monitoring (baseline, check, report, watch)

#### Phase 5 — The Brain (WS12, 15-16)
- `freq ops incident` — incident management (create, list, update, resolve, timeline)
- `freq state export/drift` — IaC state management (export, drift, reconcile)
- `freq auto react/workflow/job` — automation engine with reactors, workflows, scheduled jobs

#### Phase 6 — The Fleet (WS13-14)
- `freq docker` — fleet-wide Docker management (list, images, prune, update-check)
- `freq hw` — hardware monitoring (smart, ups, power, inventory)

#### Phase 7 — The Ecosystem (WS19)
- `freq plugin` — 8 plugin management commands (list, info, install, remove, create, search, update, types)
- 7 plugin types: command, deployer, importer, exporter, notification, widget, policy
- Plugin scaffold templates with correct interfaces per type
- Plugin registry in `conf/plugins/registry.json`

#### Phase 8 — The Face (WS20)
- 11 new dashboard views: Network, Firewall, Certificates, DNS, VPN, DR, Incidents, Metrics, Automation, Plugins
- Sub-tab navigation under Fleet (Network), Security (Firewall, Certs, VPN), System (DNS, DR, Incidents, Metrics, Automation, Plugins)
- Shared JS helpers: `_fetchAndRender`, `_statCards`, `_statusBadge`, `_esc`
- Every view has stat cards, tables, and API-driven data loading

#### Phase 9 — The Proof (WS21)
- E2E test framework with 75 tests covering all 22 domains
- Domain --help smoke tests, dispatch verification, convergence checks
- Module import validation for all 23 new modules
- API route completeness verification
- Read-only safe command catalog for live fleet testing

#### Phase 10 — GIT-READY
- 16-test codebase audit: credential scrubbing, DC01 IP scan, distro assumption detection
- SOURCE-CODE-STANDARDS compliance verification
- Deployer registry completeness checks
- Python 3.11+ syntax validation across all files
- Clean file inventory (no .env, .sqlite, .pem)

### Changed
- CLI grammar: `freq create` → `freq vm create`, `freq status` → `freq fleet status`, etc.
- All 126 flat commands reorganized into 25 domains
- serve.py: 163/209 API routes extracted to domain modules
- cert_management.py, hardware.py: distro-specific install hints replaced with generic guidance
- Test suite expanded from ~1,670 to ~2,100+ tests

### Fixed
- 6 hardcoded Debian/apt assumptions in core modules (P0 ship blockers)
- MIN_PYTHON mismatch (3.7 → 3.11) aligned across all files
- 2 distro-assumption violations in Phase 1-7 modules

### Architecture
- **Zero external dependencies** — pure Python stdlib, as always
- **Python 3.11+ minimum** — tomllib, modern asyncio, all stdlib features
- **Plugin ecosystem** — formalized interface for community extensions
- **Universal distro support** — platform detection, package manager abstraction, init system detection
- **License: AGPL v3** — same as Proxmox, proven by Grafana at $6B valuation

## [2.2.0] - 2026-03-31

### Added
- **Web asset extraction** — HTML, CSS, JS moved from Python strings to `freq/data/web/` directory
- **SSE live updates** — `GET /api/events` endpoint with `cache_update`, `health_change`, `vm_state`, `alert` event types; dashboard auto-updates via EventSource
- **Config unification** — `hosts.toml` format alongside legacy `hosts.conf`; inline `[users]` section in `freq.toml`
- **PVE REST API client** — Token-based auth with automatic SSH fallback when API is unreachable
- **Documentation** — `docs/CLI-REFERENCE.md` (88 commands), `docs/API-REFERENCE.md` (146 endpoints), `docs/CONFIGURATION.md` (every config key)
- **25 edge case tests** — SSH transport errors, PVE API fallback, zero-host fleet, dashboard error states, config corruption, validation boundaries
- **TUI commands** — `ssh`, `test-connection`, `serve`, `update` added to interactive menu
- **Dashboard empty states** — Keys, policies, distros, groups, config sections show helpful messages when no data
- **Dashboard error handling** — 21 silent `.catch()` blocks replaced with user-visible error messages and loading skeletons
- **Dashboard: VM Management** — ADD DISK and TAGS tabs, inline tag button in VM list
- **Dashboard: Docker Compose** — COMPOSE sub-tab with Up/Down/View per Docker VM
- **Dashboard: Host Discovery** — full onboarding UI with subnet scanner and manual host add form
- **Dashboard: Backup Management** — structured backup list (snapshots + exports), create/restore via dedicated API
- **VM API endpoints** — `/api/vm/add-disk`, `/api/vm/tag`, `/api/vm/clone`, `/api/vm/migrate`
- **Docker Compose API** — `/api/containers/compose-up`, `compose-down`, `compose-view`
- **Backup API** — `/api/backup/list`, `/api/backup/create`, `/api/backup/restore`
- **Setup API** — `/api/setup/test-ssh` for SSH connectivity testing, `/api/setup/reset` to re-enable wizard
- **Auto-discovery** — PVE nodes discovered from cluster API, VM tags for protection/categorization, container IP auto-resolve from hosts.conf
- **48 auto-discovery tests** — sanitize_label, is_protected_vmid, update_host_label, resolve_host_ip, VM tag cache, container VM IP resolve
- **CLI commands implemented** — `freq keys rotate`, `freq groups add`, `freq groups remove`
- Loading skeletons on containers, downloads, and streams sections
- Error toasts on all major view loaders (fleet, infra, media, docker)
- Empty states with action hints for backup and risk tables

### Changed
- README overhauled with documentation table, accurate endpoint counts (146 API endpoints), linked references
- CONTRIBUTING expanded with project structure map, API endpoint guide, plugin writing guide
- TUI back key standardized — all 15 submenus now accept `[b]` for back
- Test suite expanded from 1,281 to 1,325 tests
- `vmtClone()` rewired to dedicated `/api/vm/clone` endpoint (was `/api/vm/create?clone=X` workaround)
- `vmtMigrate()` rewired to dedicated `/api/vm/migrate` endpoint (was raw `qm migrate` via `/api/exec`)
- VM migrate UI now has live migration checkbox
- Backup restore UI takes explicit snapshot name instead of guessing "latest"
- Network scanner expanded into Host Discovery & Onboarding section
- Dashboard nav restructured to 7 items: HOME, FLEET, DOCKER, MEDIA, SECURITY, TOOLS, SETTINGS
- SSH health probes now include `last_error` field for debugging unreachable hosts

### Fixed
- Missing `log.debug()` function — PVE API client called it but it didn't exist (would crash on any API error with a real token)
- 10 bare `except: pass` blocks replaced with proper logging (agent_collector, serve, init_cmd)
- 17 silent API exception handlers now log errors
- `_resolve_container_vm_ip()` logs resolution failures
- `_is_first_run()` logs user-check errors
- Config template: 19 missing fields added, 2 default value mismatches corrected (vm_cpu, vm_bios)
- Stub deployers (opnsense, ilo, ubiquiti) now show clear "community plugin" messaging
- Discovery URL fixed — token parameter now correctly appended with `?` separator

### Removed
- Internal agent identity file (`CLAUDE.md`) removed from tracking

## [2.1.0] - 2026-03-25

### Added
- Docker packaging — Dockerfile, docker-compose.yml, entrypoint script
- Systemd unit (`contrib/freq-serve.service`) for bare-metal daemon installs
- Package data (`freq/data/`) — config templates, personality packs, knowledge base ship with pip install
- First-run config bootstrap — `load_config()` seeds `conf/` from package data when directories are empty
- `install.sh --with-systemd` flag to install and enable systemd unit
- CI: Docker build step in release workflow, package-data verification in test workflow
- `.dockerignore` for clean Docker builds

### Changed
- **Python requirement raised to >=3.11** — `tomllib` is always available, removed fragile fallback TOML parser (~90 lines)
- Single-source version — `freq/__init__.py` is the sole version source, `pyproject.toml` reads it via setuptools dynamic
- CI test matrix updated: Debian 13/12, Ubuntu 24.04, Rocky Linux 9
- Release tarball now includes Docker files, contrib/, and data/knowledge/
- README: added pip install, Docker Compose, and systemd install methods

### Removed
- `_parse_toml_basic()` and `_parse_toml_value()` — fallback TOML parser no longer needed with Python 3.11+
- DC01-specific data scrubbed from all tracked files — repo is safe for public distribution
- `reference/` directory untracked (development workspace, not product)

### Fixed
- `.gitignore` `data/` rule changed to `/data/` to avoid blocking `freq/data/` package data

## [2.0.0] - 2026-03-24

### Added
- Complete Python rewrite — 30,700 lines, zero external dependencies, pure stdlib
- 65 CLI commands covering fleet, VM, security, infrastructure, media, and monitoring
- Interactive TUI menu system with 97 entries across 14 submenus
- Web dashboard (`freq serve`) — single-file SPA with 89 API endpoints and 7 views
- One-line installer (`install.sh`) with pre-flight validation and post-install verification
- Plugin system — drop `.py` files in `conf/plugins/` for custom commands
- Personality pack system — customizable celebrations, vibes, and branding
- Policy engine with drift detection (`freq diff`) and auto-remediation (`freq fix`)
- Encrypted credential vault (`freq vault`) with AES-256-CBC
- RBAC user management with fleet-wide deployment (`freq users`, `freq roles`)
- Cloud image importing and VM provisioning (`freq import`, `freq provision`)
- Media stack management — Plex, Sonarr, Radarr, Tdarr, qBittorrent, SABnzbd, Prowlarr
- Fleet boundaries — tier-based VM permission system (probe/operator/admin)
- `freq doctor` — 13-point self-diagnostic
- `freq init` — 8-phase deployment wizard (accounts, SSH keys, PVE deploy, fleet deploy)
- `freq init --uninstall` — fleet-wide teardown
- `freq update` — self-update with install method detection
- 867+ tests across 22 test files
- `freq demo` — interactive demo mode, works without a fleet
- ARCHITECTURE.md — design philosophy and code structure documentation
- CONTRIBUTING.md — contributor guide with development setup
- SECURITY.md — security policy and vulnerability reporting
- GitHub issue templates (bug report, feature request) and PR template
- CI test workflow — pytest matrix on push to main (Debian 12, Ubuntu 22.04, Rocky 9)
- README badges (tests, Python version, license, zero dependencies, LOC)
- Screenshot capture guide in docs/screenshots/

### Changed
- Rewrote from 17,720 lines of bash to pure Python
- TOML configuration replaces bash-sourced config files
- SSH key type: ed25519 primary, RSA-4096 fallback for legacy devices (iDRAC, switches)
- Async SSH execution via `concurrent.futures` (4x faster than sequential)

### Requirements
- Python 3.11+ (raised from 3.7 in v2.1.0)
- openssh-client (pre-installed on all Linux)
- Optional: sshpass (for initial fleet deployment with password auth)
- Supported: Debian 12-13, Ubuntu 24.04+, Rocky/RHEL/AlmaLinux 9+
