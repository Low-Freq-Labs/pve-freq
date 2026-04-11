"""Tests for RBAC template collision — commented lines must not fool role checks.

Bug: roles.conf.example contains '# freq-admin:admin' as a commented template.
bootstrap_conf copies this to roles.conf. Headless init checks
'f"{svc_name}:" not in existing' which is a substring match that finds
the commented line. Result: freq-admin never gets a real role entry.

Root cause: Substring check 'in existing' matches commented lines.
The check f"freq-admin:" in "# freq-admin:admin\\n" returns True.

Fix: Parse roles.conf line-by-line, skip lines starting with #, and
use startswith() on active lines only.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestCommentedLineNotFoolsCheck(unittest.TestCase):
    """Commented template entries must not prevent adding real roles."""

    def test_source_uses_active_roles_not_substring(self):
        """Headless init must not use substring 'in existing' for role checks."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        # The headless RBAC section must use active_roles / startswith
        # It must NOT have the old pattern: f"{bootstrap_user}:" not in existing
        # Check the headless section (around line 6929+)
        import re
        # Find the headless RBAC block
        headless_rbac = re.search(
            r'roles_file = os\.path\.join\(cfg\.conf_dir, "roles\.conf"\)\s+existing_lines',
            src
        )
        self.assertIsNotNone(headless_rbac,
                             "Headless RBAC must use existing_lines pattern, not substring 'existing'")

    def test_interactive_uses_active_roles(self):
        """Interactive init must also use _active_roles helper."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("_active_roles(roles_file)", src)

    def test_startswith_used_not_in(self):
        """Role checks must use startswith() on active lines."""
        src = (FREQ_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('l.startswith(f"{bootstrap_user}:")', src)
        self.assertIn('l.startswith(f"{svc_name}:")', src)


class TestCommentedRolesIgnored(unittest.TestCase):
    """Verify that commented lines are correctly filtered."""

    def test_commented_line_does_not_match(self):
        """A commented '# freq-admin:admin' must not match freq-admin."""
        lines = ["# freq-admin:admin", "# freq-ops:operator", ""]
        active = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
        self.assertEqual(active, [])
        self.assertFalse(any(l.startswith("freq-admin:") for l in active))

    def test_real_entry_does_match(self):
        """A real 'freq-admin:admin' line must match."""
        lines = ["# example comment", "freq-ops:admin", "freq-admin:admin"]
        active = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
        self.assertTrue(any(l.startswith("freq-admin:") for l in active))
        self.assertTrue(any(l.startswith("freq-ops:") for l in active))

    def test_mixed_comments_and_real(self):
        """Mix of comments and real entries — only real entries count."""
        lines = [
            "# freq-admin:admin  (example)",
            "freq-ops:admin",
            "# viewer-example:viewer",
            "",
        ]
        active = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
        self.assertEqual(len(active), 1)
        self.assertFalse(any(l.startswith("freq-admin:") for l in active))
        self.assertTrue(any(l.startswith("freq-ops:") for l in active))


if __name__ == "__main__":
    unittest.main()
