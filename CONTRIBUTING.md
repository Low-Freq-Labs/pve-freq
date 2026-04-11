# Contributing to PVE FREQ

Thanks for looking at the code. Here's how to work with it.

## Development Setup

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git
cd pve-freq
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Verify it works:

```bash
freq --version
freq demo        # no fleet needed
freq doctor      # checks your environment
```

Run tests:

```bash
python3 -m pytest tests/ -v
```

The test suite runs without a fleet — SSH calls are mocked, configs are synthetic.

## Project Structure

```
freq/
├── __init__.py              # Version string + brand constants
├── __main__.py              # Entry point for python -m freq
├── cli.py                   # CLI dispatcher — argparse, domain routing, plugin discovery
│
├── core/                    # THE SPINE — survives everything
│   ├── config.py            # FreqConfig dataclass, TOML loader, safe defaults
│   ├── types.py             # Data classes: Host, VLAN, Distro, Container, etc.
│   ├── ssh.py               # Parallel SSH executor (run, run_many)
│   ├── fmt.py               # Output formatting: colors, tables, ANSI
│   ├── log.py               # Logger wrapper
│   ├── personality.py       # Vibes, celebrations, splash screen
│   ├── plugins.py           # Plugin discovery and loading
│   ├── resolve.py           # Host/resource resolution helpers
│   ├── validate.py          # Input validation
│   ├── preflight.py         # Pre-operation checks
│   ├── compat.py            # Proxmox version compatibility
│   └── doctor.py            # Self-diagnostic implementation
│
├── modules/                 # THE MUSCLES — one per feature, independently removable
│   ├── fleet.py             # Fleet ops: status, exec, info, diagnose
│   ├── vm.py                # VM management: create, clone, destroy, resize, power
│   ├── pve.py               # Proxmox-specific operations
│   ├── hosts.py             # Host registry management
│   ├── users.py             # User management and RBAC
│   ├── infrastructure.py    # pfSense, TrueNAS, iDRAC, switches
│   ├── media.py             # Media stack: Plex, Sonarr, Radarr, etc.
│   ├── serve.py             # HTTP server: dashboard and API routing
│   ├── init_cmd.py          # freq init — setup wizard
│   ├── demo.py              # Demo mode
│   └── ...                  # More feature modules
│
├── data/web/                # Embedded dashboard assets
│   ├── app.html             # Dashboard shell
│   ├── css/app.css          # Dashboard styles
│   └── js/app.js            # Dashboard client logic
│
├── engine/                  # THE BRAIN — policy engine
│   ├── policy.py            # PolicyExecutor: discover → desired → compare → fix
│   ├── runner.py            # Async policy runner
│   └── policies/            # Built-in policies (ssh_hardening, ntp_sync, rpcbind)
│
├── tui/                     # Interactive terminal menu
│   └── menu.py              # ANSI keyboard navigation, no external deps
│
├── jarvis/                  # SMART COMMANDS — automation + intelligence
│   ├── agent.py             # Agent orchestration
│   ├── rules.py             # Alert rules engine
│   ├── playbook.py          # Recovery playbooks
│   ├── patrol.py            # Continuous monitoring
│   ├── capacity.py          # Capacity planning
│   ├── chaos.py             # Chaos engineering
│   ├── risk.py              # Risk analysis
│   ├── federation.py        # Multi-site federation
│   ├── gitops.py            # Config-as-code
│   └── ...                  # More smart modules
│
├── deployers/               # DEVICE-SPECIFIC — pluggable hardware support
│   ├── bmc/                 # iDRAC, iLO
│   ├── firewall/            # pfSense, OPNsense
│   ├── nas/                 # TrueNAS
│   ├── server/              # Linux provisioning
│   └── switch/              # Cisco, Ubiquiti
│
└── data/                    # BUNDLED ASSETS
    ├── conf-templates/      # Config file templates (.example files)
    ├── knowledge/            # Built-in knowledge base (gotchas, lessons)
    └── web/                 # Dashboard HTML, CSS, JS
```

### Key Principles

- **Spine survives everything:** If any module is broken or missing, `freq doctor` still works. Modules are imported lazily inside handler functions.
- **Muscles are independently removable:** Delete `media.py` and everything else still works.
- **Config survives broken code:** Every `FreqConfig` field has safe defaults before any file is read. A corrupted `freq.toml` never prevents `freq doctor` from running.

## Code Style

Follow the patterns already established in the codebase:

- **Formatting:** Every visual output goes through `freq.core.fmt`. Use `fmt.header()`, `fmt.step_ok()`, `fmt.table_row()`, `fmt.badge()`. Never raw `print()` for user-facing output.
- **Command handlers:** `def cmd_something(cfg: FreqConfig, pack: PersonalityPack, args: Namespace) -> int`. Return `0` for success.
- **Lazy imports:** Commands import their modules inside the handler function, not at the top of `cli.py`. This keeps FREQ bootable even if a module is broken.
- **Error handling:** Use `fmt.error()` and `fmt.warn()`. Return non-zero, don't raise unless it's truly exceptional.

## Zero Dependencies Rule

**No external Python packages. Ever. This is non-negotiable.**

FREQ runs on hardened Proxmox hosts — air-gapped, minimal installs, no pip. If you need something, write it or find it in stdlib. The installer uses `pip3 install --no-deps` specifically to guarantee it never touches PyPI.

Before submitting: verify your code imports nothing outside the Python standard library.

## Adding a New CLI Command

1. **Module:** Create or extend a file in `freq/modules/`. Follow the `(cfg, pack, args) -> int` signature.

2. **Parser:** Register in `freq/cli.py` under `_build_parser()`:

   ```python
   p = sub.add_parser("my-command", help="What it does")
   p.add_argument("target", help="Host label or IP")
   p.set_defaults(func=_cmd_my_command)
   ```

3. **Dispatcher:** Add the lazy-import handler:

   ```python
   def _cmd_my_command(cfg, pack, args):
       from freq.modules.my_module import cmd_my_command
       return cmd_my_command(cfg, pack, args)
   ```

4. **Help:** Add the command to the appropriate category in `cmd_help()`.

5. **Tests:** Add tests in `tests/`. Mock SSH with `unittest.mock.patch`. Use synthetic `FreqConfig` objects.

6. **TUI (optional):** Add a menu entry in `freq/tui/menu.py`.

7. **Web UI (optional):** Add an API endpoint in `serve.py` and update the dashboard.

## Adding a New API Endpoint

API endpoints are defined in `freq/modules/serve.py`. The pattern is:

1. **Add the route** to the `_ROUTES` dict:

   ```python
   _ROUTES = {
       # ...existing routes...
       "/api/my-feature": ("_handle_my_feature", ["GET"]),
   }
   ```

2. **Write the handler** method on the HTTP handler class:

   ```python
   def _handle_my_feature(self, params):
       """Handle GET /api/my-feature."""
       # params = parsed query string dict
       cfg = self.server.cfg
       pack = self.server.pack

       # Do work
       result = {"status": "ok", "data": [...]}

       self._json_response(result)
   ```

3. **Add tests** in `tests/test_serve_handlers.py`:

   ```python
   def test_my_feature_endpoint(self):
       handler = self._make_handler("/api/my-feature")
       handler._handle_my_feature({})
       response = handler._get_response()
       self.assertEqual(response["status"], "ok")
   ```

4. **Update docs** — add the endpoint to `docs/API-REFERENCE.md`.

## Writing a Plugin

Plugins let users add custom commands without modifying FREQ. Drop a `.py` file in `conf/plugins/`:

```python
# conf/plugins/my_plugin.py

NAME = "my-plugin"
DESCRIPTION = "Does something useful"

def run(cfg, pack, args):
    """
    Entry point. Called when user runs: freq my-plugin

    Args:
        cfg: FreqConfig — full configuration
        pack: PersonalityPack — personality/vibes
        args: argparse.Namespace — parsed CLI args

    Returns:
        int: 0 for success, non-zero for failure
    """
    from freq.core import fmt

    fmt.header("My Plugin")
    fmt.step_ok("It works!")

    return 0
```

The plugin will appear in `freq help` and the TUI menu automatically.

### Plugin guidelines

- Follow the `(cfg, pack, args) -> int` pattern
- Use `freq.core.fmt` for output — never raw `print()`
- Use `freq.core.ssh` for remote operations
- Import FREQ modules inside `run()`, not at the top (lazy import pattern)
- Access config values through the `cfg` object
- Access vault secrets through `freq.modules.vault`
- Return `0` for success, non-zero for failure

## Testing

Every new command needs tests. The test suite runs without a fleet:

```python
from unittest.mock import MagicMock, patch

def test_my_command():
    cfg = MagicMock()
    cfg.hosts = [Host(ip="10.0.0.1", label="test", htype="linux")]
    pack = PersonalityPack()
    args = MagicMock()

    with patch("freq.core.ssh.run") as mock_ssh:
        mock_ssh.return_value = CmdResult(stdout="ok", stderr="", returncode=0)
        result = cmd_my_thing(cfg, pack, args)
        assert result == 0
```

### Running tests

```bash
# Full suite
python3 -m pytest tests/ -v

# Specific test file
python3 -m pytest tests/test_foundation.py -v

# Specific test
python3 -m pytest tests/test_cli.py::TestCLI::test_help -v

# With coverage
python3 -m pytest tests/ --cov=freq --cov-report=term-missing
```

See `tests/test_foundation.py` for patterns.

## Personality

Celebrations and vibes are welcome in PRs. The personality system is the product — it's what makes FREQ different from every other CLI tool. If your change adds a command, consider adding a premier celebration for it in the personality pack.

## Commit Messages

Keep them descriptive. One feature per commit. Use present tense:

```
Add fleet NTP check/fix command
Fix SSH timeout handling for unreachable hosts
```

## Pull Requests

- Describe what changed and why
- Include test results
- Note which commands are affected
- Update CHANGELOG.md for user-facing changes

## Questions?

Open an issue. We read them all.
