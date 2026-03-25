# Architecture — PVE FREQ v2.0

> 30,700 lines of Python. Zero external dependencies. Every import is stdlib.

## Design Philosophy

### Zero Dependencies

FREQ depends on nothing outside the Python standard library. No pip packages, no vendored libs, no node_modules. This is a hard constraint, not a preference.

**Why:** FREQ runs on Proxmox hosts — hardened, air-gapped, minimal installs. Requiring `pip install requests` on a production hypervisor is a non-starter. The installer (`install.sh`) uses `pip3 install --no-deps` specifically to guarantee it never touches PyPI.

**What it costs:** We write our own TOML parser fallback (for Python <3.11 without `tomllib`), our own parallel SSH executor, our own HTTP server for the dashboard. About 800 lines of code that a dependency would have saved.

**What it buys:** `python3 -m freq` works on any Linux box with Python 3.7+. No venv, no internet, no package manager. Copy the directory, run it.

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

### Python 3.7+ Compatibility

- `tomllib` (3.11+) with hand-rolled fallback parser
- `concurrent.futures` for parallel SSH (3.7+)
- `asyncio` for the policy engine runner (3.7+)
- No walrus operator, no `match` statements, no f-string `=` debug syntax

---

## Package Layout

```
freq/                          # 30,766 lines across 50+ files
├── __init__.py                # Version string + brand constants
├── __main__.py                # Entry point for python -m freq
├── cli.py                     # 1,357 LOC — argparse dispatcher, 65+ commands
│
├── core/                      # THE SPINE — survives everything (2,642 LOC)
│   ├── config.py              # 578 LOC — TOML loader, FreqConfig dataclass, safe defaults
│   ├── fmt.py                 # 324 LOC — ANSI colors, Unicode borders, tables, badges
│   ├── personality.py         # 158 LOC — celebrations, vibes, taglines, splash, logos
│   ├── ssh.py                 # 362 LOC — sync/async SSH, single/parallel execution
│   ├── types.py               # 258 LOC — all dataclasses (Host, Finding, Policy, VLAN, ...)
│   ├── doctor.py              # 376 LOC — 16-point self-diagnostic
│   ├── preflight.py           # 153 LOC — pre-install environment validation
│   ├── resolve.py             # 127 LOC — host/target resolution (label, IP, group, type)
│   ├── validate.py            # 108 LOC — input validation (IPs, labels, VMIDs)
│   ├── log.py                 # 95 LOC — structured logging
│   ├── plugins.py             # 72 LOC — plugin discovery from conf/plugins/
│   └── compat.py              # 30 LOC — distro detection, platform-aware install hints
│
├── modules/                   # THE MUSCLES — independently removable (27 files)
│   ├── fleet.py               # Fleet ops: status, exec, info, detail, diagnose, SSH, docker
│   ├── vm.py                  # VM lifecycle: create, clone, destroy, resize, rename
│   ├── pve.py                 # Proxmox API: list, power, snapshot, config, rescue
│   ├── media.py               # Media stack: 40+ subcommands for Plex/Sonarr/Radarr/Tdarr/etc.
│   ├── infrastructure.py      # pfSense, TrueNAS, iDRAC, Cisco switch
│   ├── serve.py               # HTTP server for the web dashboard
│   ├── web_ui.py              # 5,244 LOC — single-file SPA (HTML/CSS/JS embedded in Python)
│   ├── init_cmd.py            # 8-phase deployment wizard
│   ├── demo.py                # Interactive demo mode (works without fleet)
│   ├── vault.py               # AES-256-CBC encrypted credential store
│   ├── users.py               # RBAC: create, promote, demote, install across fleet
│   ├── audit.py               # Security audit
│   ├── harden.py              # Security hardening application
│   ├── selfupdate.py          # freq update — git pull / tarball / dpkg detection
│   └── ...                    # 13 more modules (backup, journal, lab, specialist, ...)
│
├── engine/                    # THE BRAIN — policy & compliance
│   ├── policy.py              # PolicyExecutor: discover → compare → fix → verify
│   ├── runner.py              # Async pipeline runner (semaphore-bounded concurrency)
│   └── policies/              # Declarative policy definitions
│       ├── ssh_hardening.py   # 39 lines — SSH config desired state
│       ├── ntp_sync.py        # NTP/chrony compliance
│       └── rpcbind.py         # Disable rpcbind on non-NFS hosts
│
├── tui/                       # Interactive terminal UI
│   └── menu.py                # 1,314 LOC — 97 entries, 14 submenus, risk tags, color keys
│
└── jarvis/                    # Smart commands
    ├── agent.py               # AI specialist VM management
    ├── learn.py               # Proxmox operational knowledge base search
    ├── risk.py                # Kill-chain blast radius analysis
    ├── sweep.py               # Full audit + policy sweep pipeline
    ├── patrol.py              # Continuous monitoring + drift detection
    ├── provision.py           # Cloud-init VM provisioning
    └── notify.py              # Discord/Slack notifications
```

---

## The Spine (`core/`)

The survival layer. If every module in `modules/`, `engine/`, `tui/`, and `jarvis/` were deleted, `core/` would still:

- Load configuration with safe defaults
- Show the ASCII splash screen
- Run the 16-point self-diagnostic (`freq doctor`)
- Resolve hosts from `hosts.conf`
- Execute SSH commands
- Validate user input
- Log operations

### `config.py` — The Configuration Loader

`FreqConfig` is a dataclass with ~40 fields. Every field has a default. The loading sequence:

1. Set defaults (install_dir, conf_dir, data_dir from `$FREQ_DIR` or `/opt/pve-freq`)
2. Read `freq.toml` (TOML with fallback parser for Python <3.11)
3. Read `hosts.conf` (custom line format: `IP LABEL TYPE [GROUPS]`)
4. Read `vlans.toml`, `distros.toml`, `fleet-boundaries.toml`
5. Override from environment variables (`$FREQ_DIR`, `$FREQ_DEBUG`)

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

`web_ui.py` is a 5,244-line Python file that contains an entire single-page application: HTML structure, CSS styles, and JavaScript — all as Python string templates. No external JS libraries, no build step, no npm.

`serve.py` subclasses `http.server.HTTPServer` with `ThreadingMixIn` for concurrent requests. A background thread refreshes fleet data every 60 seconds into a cache. 89 API endpoints serve JSON for the dashboard views.

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
[build]
personality = "personal"
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

**867 tests** across 21 test files. All tests run without a fleet — SSH calls are mocked, configs are synthetic.

```
tests/
├── test_foundation.py    # Core types, config loading, fmt output, validate
├── test_cli.py           # Parser registration, command dispatch, output patterns
├── test_demo.py          # Demo command (splash, doctor, status, personality)
├── test_fleet.py         # Fleet operations (status, exec, info, diagnose)
├── test_vm.py            # VM management (create, clone, destroy, resize)
├── test_pve.py           # Proxmox operations
├── test_engine.py        # Policy engine (executor, runner, findings)
├── test_install.py       # Pre-flight, installer syntax, entry points
├── test_parity.py        # CLI/TUI/Web UI feature parity verification
├── test_media.py         # Media stack operations
└── ...                   # 11 more test files
```

CI matrix: Debian 12, Ubuntu 22.04, Rocky Linux 9.

---

## Configuration Files

```
conf/
├── freq.toml              # Main config: hosts file path, SSH settings, personality
├── freq.toml.example      # Template for new installs
├── hosts.conf             # Fleet host registry (IP LABEL TYPE GROUPS)
├── hosts.conf.example     # Template
├── vlans.toml             # VLAN definitions (ID, name, subnet, gateway)
├── distros.toml           # Cloud image catalog (URL, checksum, family)
├── fleet-boundaries.toml  # Permission tiers, VM categories, physical devices
├── personality/           # Personality packs
│   ├── default.toml
│   └── personal.toml
└── plugins/               # Plugin modules (auto-discovered)
```

```
data/
├── log/                   # Operation logs
├── vault/                 # AES-256-CBC encrypted credentials
├── keys/                  # SSH keys for fleet access
└── cache/                 # Dashboard cache, fleet state
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
| TOML over YAML/JSON | Human-readable, unambiguous, stdlib in Python 3.11+. Our fallback parser handles the subset we need. |
