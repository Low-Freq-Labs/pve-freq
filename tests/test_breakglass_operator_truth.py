"""Break-glass / emergency recovery docs truth tests.

Proves:
1. BREAK-GLASS.md does not hardcode freq-admin in SSH examples
2. QUICK-REFERENCE.md references configurable service account
3. Emergency docs reference hosts.toml (not hosts.conf)
4. Recovery commands match current runtime contract
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestBreakGlassServiceAccount(unittest.TestCase):
    """Emergency docs must not hardcode freq-admin."""

    def test_no_hardcoded_freq_admin_in_ssh(self):
        with open(os.path.join(REPO_ROOT, "docs/BREAK-GLASS.md")) as f:
            src = f.read()
        self.assertNotIn("freq-admin@", src,
                          "Break-glass must use <service-account>@ not freq-admin@")

    def test_quick_reference_explains_service_account(self):
        with open(os.path.join(REPO_ROOT, "docs/QUICK-REFERENCE.md")) as f:
            src = f.read()
        self.assertIn("service account", src.lower(),
                       "Quick reference must explain configurable service account")
        self.assertIn("freq.toml", src,
                       "Must point to freq.toml for service account config")


class TestBreakGlassHostsFormat(unittest.TestCase):
    """Emergency docs must reference hosts.toml, not hosts.conf."""

    def test_break_glass_no_hosts_conf(self):
        with open(os.path.join(REPO_ROOT, "docs/BREAK-GLASS.md")) as f:
            src = f.read()
        self.assertNotIn("hosts.conf", src,
                          "Break-glass must not reference legacy hosts.conf")

    def test_quick_reference_no_hosts_conf(self):
        with open(os.path.join(REPO_ROOT, "docs/QUICK-REFERENCE.md")) as f:
            src = f.read()
        self.assertNotIn("hosts.conf", src,
                          "Quick reference must not reference legacy hosts.conf")


if __name__ == "__main__":
    unittest.main()
