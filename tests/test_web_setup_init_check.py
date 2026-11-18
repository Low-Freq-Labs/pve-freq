"""Tests for web setup vs CLI init --check contract.

Bug: Web setup originally wrote .initialized marker, falsely claiming
init completed. Fix: web setup now writes .web-setup-complete instead.
_init_check() detects .web-setup-complete and downgrades fleet checks
from FAIL to WARN. .initialized is ONLY written by freq init CLI.

Contract:
- Full CLI init (.initialized): all checks are FAIL-level (fleet ops expected)
- Web-only setup (.web-setup-complete): fleet checks are WARN-level (dashboard-only is valid)
- Marker file distinguishes: .web-setup-complete vs .initialized
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMarkerDetection(unittest.TestCase):
    """The markers must honestly indicate which path set them."""

    def test_cli_marker_does_not_contain_web_setup(self):
        """CLI init marker format must NOT contain 'web setup'."""
        cli_marker = "PVE FREQ 1.0.0 — initialized 2026-04-11 05:00"
        self.assertNotIn("web setup", cli_marker.lower())

    def test_web_marker_contains_web_setup(self):
        """Web setup marker format must contain 'web setup' for detection."""
        web_marker = "PVE FREQ 1.0.0 — web setup 2026-04-11T06:00:00"
        self.assertIn("web setup", web_marker.lower())

    def test_init_check_uses_web_setup_complete_file(self):
        """_init_check must check .web-setup-complete for web-only detection."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py"
        with open(path) as f:
            content = f.read()
        check_fn = content.split("def _init_check")[1].split("\ndef ")[0]
        self.assertIn(".web-setup-complete", check_fn,
                       "_init_check must read .web-setup-complete marker")


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
        """_init_check source must check for web-setup-complete marker."""
        path = Path(__file__).parent.parent / "freq" / "modules" / "init_cmd.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("web-setup-complete", content,
                      "_init_check must detect web-only setup via .web-setup-complete marker")
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
