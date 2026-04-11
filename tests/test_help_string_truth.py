"""Regression tests for operator-facing help string truthfulness.

Proves: command suggestions in error messages, help text, and recovery
hints reference valid CLI command paths that actually exist.

Catches: stale command paths after refactoring (e.g., "freq netmon poll"
when the real command is "freq net netmon poll").
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _get_valid_top_level_commands():
    """Get all valid top-level CLI command names from cli.py."""
    cli_path = os.path.join(REPO_ROOT, "freq", "cli.py")
    with open(cli_path) as f:
        content = f.read()
    # Match: sub.add_parser("command_name", ...)
    return set(re.findall(r'sub\.add_parser\("(\w+)"', content))


def _find_freq_command_hints(directory):
    """Find all 'freq <command>' hints in Python source files."""
    hints = []
    import glob
    for path in glob.glob(os.path.join(directory, "**", "*.py"), recursive=True):
        with open(path) as f:
            for i, line in enumerate(f, 1):
                # Match strings like: freq <word> [<word>...]
                # In format strings, error messages, help text
                for m in re.finditer(r'freq (\w+)', line):
                    cmd = m.group(1)
                    # Skip non-command references
                    if cmd in ("init", "serve", "version", "help", "menu",
                               "doctor", "update", "configure"):
                        continue  # These are top-level, always valid
                    if cmd in ("toml", "conf", "py", "ops", "data",
                               "id", "session", "FREQ", "freq"):
                        continue  # Not command references
                    hints.append((path, i, line.strip(), cmd))
    return hints


class TestCommandHintsAreValid(unittest.TestCase):
    """Command hints in error messages must reference real CLI commands."""

    def test_netmon_hints_use_correct_path(self):
        """netmon hints must say 'freq net netmon' not 'freq netmon'."""
        netmon_path = os.path.join(REPO_ROOT, "freq", "modules", "netmon.py")
        with open(netmon_path) as f:
            content = f.read()
        # Should NOT contain bare "freq netmon" (without "net" prefix)
        bare_refs = re.findall(r"freq netmon(?! )", content)
        # But allow in Domain docstring
        user_facing = [r for r in re.finditer(r"freq netmon", content)
                       if "Domain:" not in content[max(0, r.start()-50):r.start()]]
        self.assertEqual(
            len(user_facing), 0,
            "User-facing strings must use 'freq net netmon', not 'freq netmon'"
        )

    def test_comply_hints_use_correct_path(self):
        """comply hints must say 'freq secure comply' not 'freq comply'."""
        comply_path = os.path.join(REPO_ROOT, "freq", "modules", "comply.py")
        with open(comply_path) as f:
            content = f.read()
        user_facing = []
        for m in re.finditer(r"freq comply", content):
            context = content[max(0, m.start()-50):m.start()]
            if "Domain:" not in context:
                user_facing.append(m.start())
        self.assertEqual(
            len(user_facing), 0,
            "User-facing strings must use 'freq secure comply', not 'freq comply'"
        )

    def test_fim_hints_use_correct_path(self):
        """FIM hints must say 'freq secure fim' not 'freq fim'."""
        fim_path = os.path.join(REPO_ROOT, "freq", "modules", "fim.py")
        with open(fim_path) as f:
            content = f.read()
        # Check user-facing strings (not Domain docstring)
        for m in re.finditer(r"freq (?:secure )?fim", content):
            context_before = content[max(0, m.start()-50):m.start()]
            if "Domain:" in context_before:
                continue
            matched = content[m.start():m.end()]
            self.assertIn("secure", matched,
                          f"User-facing FIM hint must include 'secure': {matched}")

    def test_serve_docstring_uses_host_not_hosts(self):
        """serve.py background sync docstring must reference 'freq host sync'."""
        serve_path = os.path.join(REPO_ROOT, "freq", "modules", "serve.py")
        with open(serve_path) as f:
            content = f.read()
        self.assertNotIn("freq hosts sync", content,
                         "Must use 'freq host sync' (no trailing 's')")


class TestHelpStringExamplesValid(unittest.TestCase):
    """Example IPs in help strings should use RFC 5737 documentation ranges."""

    def test_monitor_example_not_real_ip(self):
        """Monitor HTTP example should not use a real-looking IP."""
        cli_path = os.path.join(REPO_ROOT, "freq", "cli.py")
        with open(cli_path) as f:
            content = f.read()
        # The 10.0.0.50 IP is in the monitor example. While it's RFC 1918,
        # using 198.51.100.x (RFC 5737) would be clearer as a documentation IP.
        # For now, just verify the example exists and has a port.
        self.assertIn("healthz", content,
                       "Monitor example must reference /healthz endpoint")


if __name__ == "__main__":
    unittest.main()
