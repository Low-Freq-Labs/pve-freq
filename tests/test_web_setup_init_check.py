"""Tests for web setup vs CLI init --check contract.

Bug: Web setup wrote .initialized marker with a comment claiming CLI
compatibility ("so freq init --check passes"), but _init_check() requires
service account, SSH keys, and vault — none of which web setup creates.
After web-only setup, init --check would report hard FAILs for missing
fleet infrastructure that isn't relevant to dashboard-only usage.

Fix: _init_check() now detects "web setup" in the marker content and
downgrades fleet-specific checks (service account, SSH keys) from FAIL
to WARN. Web setup comment updated to be honest about what it provides.

Contract:
- Full CLI init: all checks are FAIL-level (fleet ops expected)
- Web-only setup: fleet checks are WARN-level (dashboard-only is valid)
- Marker content distinguishes: "web setup" in text → web-only mode
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMarkerDetection(unittest.TestCase):
    """The .initialized marker must honestly indicate which path set it."""

    def test_cli_marker_does_not_contain_web_setup(self):
        """CLI init marker format must NOT contain 'web setup'."""
        # CLI format: "PVE FREQ {version} — initialized {timestamp}"
        cli_marker = "PVE FREQ 1.0.0 — initialized 2026-04-11 05:00"
        self.assertNotIn("web setup", cli_marker.lower())

    def test_web_marker_contains_web_setup(self):
        """Web setup marker format must contain 'web setup' for detection."""
        # Web format: "PVE FREQ {version} — web setup {timestamp}"
        web_marker = "PVE FREQ 1.0.0 — web setup 2026-04-11T06:00:00"
        self.assertIn("web setup", web_marker.lower())


class TestInitCheckSeverity(unittest.TestCase):
    """init --check must adjust severity based on initialization path."""

    def test_web_only_comment_is_honest(self):
        """serve.py setup complete comment must NOT claim init --check passes."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "serve.py"
        with open(path) as f:
            content = f.read()
        # The old comment said "so freq init --check passes" — that was a lie
        self.assertNotIn("so freq init --check passes", content,
                         "serve.py must not claim web setup makes init --check pass")

    def test_init_check_detects_web_setup(self):
        """_init_check source must check for 'web setup' in marker."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("web setup", content,
                      "_init_check must detect web-only setup from marker content")
        self.assertIn("web_only", content,
                      "_init_check must use web_only flag for severity adjustment")

    def test_fleet_severity_variable_exists(self):
        """_init_check must have fleet_severity that differs by init path."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("fleet_severity", content)
        # Must downgrade to warn for web-only
        self.assertIn('"warn" if web_only else "fail"', content)


if __name__ == "__main__":
    unittest.main()
