# Contributing to PVE FREQ

Thanks for looking at the code. Here's how to work with it.

## Development Setup

```bash
git clone https://github.com/Low-Freq-Labs/pve-freq.git
cd pve-freq
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

All 1,281 tests run without a fleet — SSH calls are mocked, configs are synthetic.

## Architecture

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the full design. Quick summary:

```
freq/core/       # The spine — config, fmt, ssh, types, personality. Survives everything.
freq/modules/    # The muscles — one per command group. Independently removable.
freq/engine/     # The brain — policy executor + async runner.
freq/tui/        # Interactive menu.
freq/jarvis/     # Smart commands (learn, risk, sweep, patrol).
```

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

## Adding a New Command

1. **Module:** Create or extend a file in `freq/modules/`. Follow the `(cfg, pack, args) -> int` signature.
2. **Parser:** Register in `freq/cli.py` under `_build_parser()`. Add a subparser and a dispatcher function.
3. **Help:** Add the command to the appropriate category in `cmd_help()`.
4. **Tests:** Add tests in `tests/`. Mock SSH with `unittest.mock.patch`. Use synthetic `FreqConfig` objects.
5. **TUI (optional):** Add a menu entry in `freq/tui/menu.py` if the command should appear in the interactive menu.
6. **Web UI (optional):** Add an API endpoint in `freq/modules/serve.py` and a dashboard component in `freq/modules/web_ui.py`.

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
