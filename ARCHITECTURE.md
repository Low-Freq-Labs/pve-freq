# Architecture — PVE FREQ v2.2.0

> 39,500+ lines of Python. Zero external dependencies. Every import is stdlib.

## Design Philosophy

### Zero Dependencies

FREQ depends on nothing outside the Python standard library. No pip packages, no vendored libs, no node_modules. This is a hard constraint, not a preference.

**Why:** FREQ runs on Proxmox hosts — hardened, air-gapped, minimal installs. Requiring `pip install requests` on a production hypervisor is a non-starter. The installer (`install.sh`) uses `pip3 install --no-deps` specifically to guarantee it never touches PyPI.

**What it costs:** We write our own parallel SSH executor, our own HTTP server for the dashboard, our own TOML-based config system. About 800 lines of code that a dependency would have saved.

**What it buys:** `python3 -m freq` works on any Linux box with Python 3.11+. No venv, no internet, no package manager. Copy the directory, run it.

### Config Survives Broken Code

Every `FreqConfig` field has a safe default set *before* any config file is read. If `freq.toml` is corrupted, missing, or has invalid values, FREQ still loads and `freq doctor` still runs. This is the "Trap #4" principle from `config.py`: a broken config file should never prevent you from diagnosing the broken config file.

### Lazy Module Imports

Commands import their modules on demand:

```python
def _cmd_status(cfg, pack, args):
    from freq.modules.fleet import cmd_status
    return cmd_status(cfg, pack, args)
```

If `fleet.py` has a syntax error, `freq doctor` still works. If `media.py` is deleted, `freq status` still works. This is the "muscles can be missing" principle — the spine survives anything.

### Python 3.11+ Required

- `tomllib` (3.11+ stdlib) for TOML config parsing — no fallback needed
- `concurrent.futures` for parallel SSH
- `asyncio` for the policy engine runner

---

## Package Layout

```
freq/                          # 39,500+ lines across 50+ files
├── __init__.py                # Version string + brand constants
├── __main__.py                # Entry point for python -m freq
├── cli.py                     # 1,148 LOC — argparse dispatcher, 88 commands
│
├── core/                      # THE SPINE — survives everything
│   ├── config.py              # TOML loader, FreqConfig dataclass, safe defaults, bootstrap
│   ├── fmt.py                 # ANSI colors, Unicode borders, tables, badges
│   ├── personality.py         # Celebrations, vibes, taglines, splash, logos
│   ├── ssh.py                 # Sync/async SSH, single/parallel execution
│   ├── types.py               # All dataclasses (Host, Finding, Policy, VLAN, ...)
│   ├── doctor.py              # 15-point self-diagnostic
│   ├── preflight.py           # Pre-install environment validation
│   ├── resolve.py             # Host/target resolution (label, IP, group, type)
│   ├── validate.py            # Input validation (IPs, labels, VMIDs)
│   ├── log.py                 # Structured logging
│   ├── plugins.py             # Plugin discovery from conf/plugins/
│   └── compat.py              # Distro detection, platform-aware install hints
│
├── modules/                   # THE MUSCLES — independently removable
│   ├── fleet.py               # Fleet ops: status, exec, info, detail, diagnose, SSH, docker
│   ├── vm.py                  # VM lifecycle: create, clone, destroy, resize, rename, tags, disks
│   ├── pve.py                 # Proxmox API: list, power, snapshot, config, rescue
│   ├── media.py               # Media stack: 40+ subcommands for Plex/Sonarr/Radarr/Tdarr/etc.
│   ├── infrastructure.py      # pfSense, TrueNAS, iDRAC, Cisco switch
│   ├── serve.py               # 6,323 LOC — HTTP server, 100+ API endpoints, background polling
│   ├── web_ui.py              # 7,234 LOC — single-file SPA (HTML/CSS/JS embedded in Python)
│   ├── init_cmd.py            # 10-phase deployment wizard
│   ├── demo.py                # Interactive demo mode (works without fleet)
│   ├── vault.py               # AES-256-CBC encrypted credential store
│   ├── users.py               # RBAC: create, promote, demote, install across fleet
│   ├── audit.py               # Security audit
│   ├── harden.py              # Security hardening application
│   ├── selfupdate.py          # freq update — git pull / tarball / dpkg detection
│   ├── backup.py              # Snapshot and backup management
│   ├── discover.py            # Host and PVE node auto-discovery
│   ├── hosts.py               # Host management, groups, onboarding
│   └── ...                    # 10 more modules (journal, lab, specialist, ...)
│
├── engine/                    # THE BRAIN — policy & compliance
│   ├── policy.py              # PolicyExecutor: discover → compare → fix → verify
│   ├── runner.py              # Async pipeline runner (semaphore-bounded concurrency)
│   └── policies/              # Declarative policy definitions
│       ├── ssh_hardening.py   # SSH config desired state
│       ├── ntp_sync.py        # NTP/chrony compliance
│       └── rpcbind.py         # Disable rpcbind on non-NFS hosts
│
├── tui/                       # Interactive terminal UI
│   └── menu.py                # 1,315 LOC — 168 entries, 15 submenus, risk tags, color keys
│
├── deployers/                 # Vendor-specific device deployers
│   ├── server/linux.py        # Linux server deployment
│   ├── firewall/pfsense.py    # pfSense deployment
│   ├── nas/truenas.py         # TrueNAS deployment
│   ├── bmc/idrac.py           # Dell iDRAC BMC
│   └── switch/cisco.py        # Cisco switch deployment
│
├── jarvis/                    # Smart commands
│   ├── agent.py               # AI specialist VM management
│   ├── federation.py          # Multi-site federation
│   ├── learn.py               # Proxmox operational knowledge base search
│   ├── risk.py                # Kill-chain blast radius analysis
│   ├── sweep.py               # Full audit + policy sweep pipeline
│   ├── patrol.py              # Continuous monitoring + drift detection
│   ├── provision.py           # Cloud-init VM provisioning
│   └── notify.py              # Discord/Slack/Telegram/SMTP/ntfy/Gotify/Pushover notifications
│
└── data/                      # Package data (ships with pip install)
    ├── conf-templates/        # Default config files seeded on first run
    └── knowledge/             # Operational knowledge base (lessons + gotchas)
```

---

## The Spine (`core/`)

The survival layer. If every module in `modules/`, `engine/`, `tui/`, and `jarvis/` were deleted, `core/` would still:

- Load configuration with safe defaults
- Show the ASCII splash screen
- Run the 15-point self-diagnostic (`freq doctor`)
- Resolve hosts from `hosts.conf`
- Execute SSH commands
- Validate user input
- Log operations

### `config.py` — The Configuration Loader

`FreqConfig` is a dataclass with ~40 fields. Every field has a default. The loading sequence:

1. Set defaults (install_dir, conf_dir, data_dir from `$FREQ_DIR` or `/opt/pve-freq`)
2. Bootstrap from package data if first run (seed `conf/` and `data/` from `freq/data/`)
3. Read `freq.toml` (stdlib `tomllib`)
4. Read `hosts.conf` (custom line format: `IP LABEL TYPE [GROUPS]`)
5. Read `vlans.toml`, `distros.toml`, `fleet-boundaries.toml`
6. Override from environment variables (`$FREQ_DIR`, `$FREQ_DEBUG`)

If any step fails, the previous defaults survive. Config loading never raises.

### `fmt.py` — The Visual Identity

Every character on screen goes through `fmt`. Colors (`C` class), symbols (`S` class with Unicode/ASCII fallback), box-drawing characters, step indicators, table helpers, badges. The FREQ purple (`\033[38;5;93m`) and the Unicode borders (`╭─╮│╰─╯`) are defined here.

### `personality.py` — Not Decoration, The Product

The personality system is what makes someone choose FREQ over Ansible for their homelab. It's the reason people show it to friends.

**PersonalityPack** dataclass holds:
- `celebrations` — random success messages ("The bass just hit different.")
- `premier` — operation-specific messages (e.g., init gets its own)
- `taglines` — splash screen rotation
- `quotes` — closing wisdom
- `vibe_common/rare/legendary` — tiered random drops

**Vibes** fire after every successful command with 1/47 probability (prime number for less predictable patterns). When triggered: 60% common (tips), 25% rare (music references), 15% legendary (multi-line stories).

Two packs ship: `default.toml` (professional, vibes disabled) and `personal.toml` (bass/dubstep themed, 139 celebrations, legendary stories).

### `ssh.py` — The Fleet Interface

Two execution modes:
- **Single host:** `ssh.run()` — subprocess with connect/command timeouts, optional sudo, key-based auth
- **Parallel fleet:** `ssh.run_many()` — `concurrent.futures.ThreadPoolExecutor` with configurable max workers

The engine uses `ssh.run_async()` for asyncio-based execution in the policy pipeline.

---

## The Muscles (`modules/`)

Each module handles one command group. Every command handler follows the same signature:

```python
def cmd_status(cfg: FreqConfig, pack: PersonalityPack, args: Namespace) -> int:
```

Return `0` for success, non-zero for failure. The dispatcher in `cli.py` catches exceptions and logs them — a crashing module doesn't take down FREQ.

### The Dashboard (`serve.py` + `web_ui.py`)

`web_ui.py` is a 7,234-line Python file that contains an entire single-page application: HTML structure, CSS styles, and JavaScript — all as Python string templates. No external JS libraries, no build step, no npm.

`serve.py` subclasses `http.server.HTTPServer` with `ThreadingMixIn` for concurrent requests. A background thread refreshes fleet data every 60 seconds into a cache. 100+ API endpoints serve JSON for the 7 dashboard views: Home, Fleet, Docker, Media, Security, Tools, Settings.

Start it: `freq serve` → `http://localhost:8888`

---

## The Brain (`engine/`)

### Declarative Policies

Policies are Python dicts, not imperative code. `ssh_hardening.py` is 39 lines:

```python
POLICY = {
    "name": "ssh-hardening",
    "description": "SSH server configuration hardening",
    "scope": ["linux", "pve", "docker"],
    "resources": [
        {
            "type": "file_entries",
            "path": "/etc/ssh/sshd_config",
            "entries": {
                "PermitRootLogin": "no",
                "PasswordAuthentication": "no",
                "X11Forwarding": "no",
                ...
            },
            "after_change": {"service": "sshd", "action": "restart"}
        }
    ]
}
```

### The Pipeline

`PolicyExecutor` runs a 5-stage pipeline per host:

1. **Discover** — SSH to host, read current state of each resource
2. **Compare** — Diff current vs desired, generate `Finding` objects
3. **Plan** — Determine fix commands from findings
4. **Fix** — Apply fixes (only in `fix` mode, not `check`)
5. **Verify** — Re-read state, confirm fixes took effect

`runner.py` runs this pipeline across the fleet using `asyncio` with a semaphore-bounded concurrency pool. 10 hosts finish in ~2.7s vs ~30s serial.

User-facing commands:
- `freq check ssh-hardening` — dry run, show findings
- `freq diff ssh-hardening` — git-style diff of current vs desired
- `freq fix ssh-hardening` — apply remediations

---

## The Personality System

### Pack Architecture

```
conf/personality/
├── default.toml     # Professional mode — neutral celebrations, vibes disabled
└── personal.toml    # Bass/dubstep theme — 139 celebrations, tiered vibes
```

Select pack in `freq.toml`:
```toml
[freq]
build = "personal"
```

### Vibe Drop Mechanics

```python
vibe_probability = 47  # 1/47 chance per command (prime = less predictable)
```

When triggered (via `show_vibe()` after every successful command):
- Roll 1-100
- 1-60: common vibe (operational tips)
- 61-85: rare vibe (artist/music references)
- 86-100: legendary vibe (multi-line stories with box borders)

The probability being prime (47) means the pattern doesn't align with common loop counts, making drops feel genuinely random.

---

## Testing

**1,281 tests** across 33 test files. All tests run without a fleet — SSH calls are mocked, configs are synthetic.

```
tests/
├── test_foundation.py       # Core types, config loading, fmt output, validate
├── test_cli.py              # Parser registration, command dispatch, output patterns
├── test_demo.py             # Demo command (splash, doctor, status, personality)
├── test_auto_discovery.py   # PVE node discovery, VM tags, host resolution (48 tests)
├── test_admin_api.py        # Admin API endpoints, host management
├── test_serve_handlers.py   # Dashboard API handler coverage
├── test_serve_helpers.py    # Serve utility functions
├── test_serve_cache.py      # Background cache behavior
├── test_hosts_sync.py       # Host sync and label management
├── test_install.py          # Pre-flight, installer syntax, entry points
├── test_parity.py           # CLI/TUI/Web UI feature parity verification
├── test_policies.py         # Policy engine (executor, runner, findings)
├── test_security.py         # Security audit and hardening
├── test_modules.py          # Module-level tests (knowledge base, risk, etc.)
└── ...                      # 19 more test files (jarvis, edge cases, overnight tiers)
```

CI matrix: Debian 13, Debian 12, Ubuntu 24.04, Rocky Linux 9.

---

## Configuration Files

```
conf/
├── freq.toml              # Main config: cluster, SSH, VM defaults, notifications, safety
├── freq.toml.example      # Template for new installs
├── hosts.conf             # Fleet host registry (IP LABEL TYPE GROUPS)
├── hosts.conf.example     # Template
├── vlans.toml             # VLAN definitions (ID, name, subnet, gateway)
├── distros.toml           # Cloud image catalog (URL, checksum, family)
├── fleet-boundaries.toml  # Permission tiers, VM categories, physical devices
├── containers.toml        # Docker container registry
├── rules.toml             # Custom automation rules
├── risk.toml              # Dependency and kill-chain definitions
├── personality/           # Personality packs
│   ├── default.toml
│   └── personal.toml
├── playbooks/             # Automated recovery playbooks
└── plugins/               # Custom command plugins (auto-discovered)
```

```
data/
├── log/                   # Operation logs
├── vault/                 # AES-256-CBC encrypted credentials
├── keys/                  # SSH keys for fleet access
├── cache/                 # Dashboard cache, fleet state
└── knowledge/             # Operational knowledge base (lessons + gotchas)
```

---

## Key Design Decisions

| Decision | Why |
|----------|-----|
| `/opt/pve-freq` install dir | FHS standard for self-contained app bundles. Source + config + data in one directory. Easy backup, migration, uninstall. |
| Single-file SPA dashboard | No build step, no npm, no webpack. `cat web_ui.py` shows you the entire frontend. Deployed by copying one file. |
| Policies as dicts | Declarative > imperative. A policy author doesn't need to know Python — just define desired state. The executor handles the rest. |
| Personality as first-class | CLI tools are commodities. The personality system is the moat. It makes FREQ memorable and shareable. |
| `concurrent.futures` over asyncio everywhere | Simpler mental model for SSH parallelism. asyncio is reserved for the engine pipeline where true async matters. |
| TOML config | Human-readable, unambiguous, stdlib in Python 3.11+. No YAML ambiguity, no JSON comment hacks. |
| Package data bootstrap | `freq/data/` ships config templates and knowledge base. First run auto-seeds `conf/` and `data/` — zero manual file copying. |
