# Changelog

All notable changes to PVE FREQ will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [2.2.0] - 2026-03-27

### Added
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
- `vmtClone()` rewired to dedicated `/api/vm/clone` endpoint (was `/api/vm/create?clone=X` workaround)
- `vmtMigrate()` rewired to dedicated `/api/vm/migrate` endpoint (was raw `qm migrate` via `/api/exec`)
- VM migrate UI now has live migration checkbox
- Backup restore UI takes explicit snapshot name instead of guessing "latest"
- Network scanner expanded into Host Discovery & Onboarding section
- Dashboard nav restructured to 7 items: HOME, FLEET, DOCKER, MEDIA, SECURITY, TOOLS, SETTINGS
- SSH health probes now include `last_error` field for debugging unreachable hosts

### Fixed
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
- Python 3.7+ (ships with all supported distros)
- openssh-client (pre-installed on all Linux)
- Optional: sshpass (for initial fleet deployment with password auth)
- Supported: Debian 11-13, Ubuntu 20.04-24.04, Rocky/RHEL/AlmaLinux 8-9
