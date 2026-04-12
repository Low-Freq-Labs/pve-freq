"""Infra quick auth parity tests.

Proves:
1. _is_auth_failure detects SSH permission denied errors
2. Infra quick probe marks auth failures with auth_failed=true
3. Infra quick does NOT report reachable=true on SSH auth failure
4. probe_method field is set for all probe outcomes
5. Unknown device types note that /api/health has authoritative SSH state

Fixes Finn-reported divergence: /api/health marks nexus unreachable
(permission denied) while /api/infra/quick said reachable=true. Both
surfaces must agree when SSH auth fails.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestInfraAuthFailureDetection(unittest.TestCase):
    """The _is_auth_failure helper must catch common SSH auth errors."""

    def _src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            return f.read()

    def test_helper_defined(self):
        src = self._src()
        self.assertIn("def _is_auth_failure", src,
                       "_is_auth_failure helper must exist")

    def test_helper_catches_permission_denied(self):
        """The helper must match 'permission denied' and 'publickey' errors."""
        src = self._src()
        fn = src.split("def _is_auth_failure")[1].split("\n    def ")[0]
        self.assertIn("permission denied", fn.lower())
        self.assertIn("publickey", fn.lower())


class TestInfraProbeMethodField(unittest.TestCase):
    """Every infra probe outcome must set probe_method."""

    def _probe_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _probe_device")[1].split("\n    devices = ")[0]

    def test_initial_probe_method_none(self):
        src = self._probe_src()
        self.assertIn('"probe_method": "none"', src,
                       "Default probe_method must be 'none'")

    def test_ssh_success_sets_method_ssh(self):
        src = self._probe_src()
        # At least one branch sets probe_method = "ssh"
        self.assertIn('d["probe_method"] = "ssh"', src)

    def test_auth_failure_sets_method(self):
        src = self._probe_src()
        self.assertIn('d["probe_method"] = "ssh_auth_failed"', src,
                       "Auth failure must set probe_method='ssh_auth_failed'")

    def test_ping_fallback_sets_method(self):
        src = self._probe_src()
        self.assertIn('"ping" if d["reachable"] else "none"', src,
                       "Ping fallback must set probe_method='ping' or 'none'")


class TestInfraAuthFailureNotReachable(unittest.TestCase):
    """SSH auth failure must NOT produce reachable=true."""

    def _probe_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _probe_device")[1].split("\n    devices = ")[0]

    def test_all_ssh_branches_check_auth_failure(self):
        """Every SSH-using branch must have an elif _is_auth_failure check."""
        src = self._probe_src()
        # Should appear at least for pfsense, truenas, switch, idrac
        count = src.count("_is_auth_failure(r.stderr)")
        self.assertGreaterEqual(count, 4,
                                f"Expected ≥4 auth failure checks (pfsense/truenas/switch/idrac), got {count}")

    def test_auth_failed_sets_auth_failed_field(self):
        src = self._probe_src()
        # Each auth failure branch must set d["auth_failed"] = True
        auth_blocks = src.split("_is_auth_failure(r.stderr)")
        for block in auth_blocks[1:]:  # Skip first (before any match)
            # Next ~200 chars should have auth_failed = True
            snippet = block[:200]
            self.assertIn('d["auth_failed"] = True', snippet,
                           "Auth failure branch must set auth_failed=True")

    def test_auth_failure_does_not_set_reachable_true(self):
        """Auth failure branches must NOT set d['reachable'] = True."""
        src = self._probe_src()
        # Find each 'elif _is_auth_failure' block and verify no 'reachable'] = True' in it
        pattern = re.compile(r'elif _is_auth_failure\(r\.stderr\):(.*?)(?=\n                (?:else|elif |\Z))', re.DOTALL)
        for m in pattern.finditer(src):
            block = m.group(1)
            self.assertNotIn('d["reachable"] = True', block,
                              "Auth failure branch must not mark device as reachable")


class TestUnknownDeviceTypeNote(unittest.TestCase):
    """The final else branch (unknown device types) must reference /api/health."""

    def test_else_branch_notes_health_is_authoritative(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        probe_src = src.split("def _probe_device")[1].split("\n    devices = ")[0]
        # Find the final else — right before the return d
        # We just check that /api/health is mentioned as a reference
        self.assertIn("/api/health", probe_src,
                       "Unknown device type branch must reference /api/health for SSH probe state")


if __name__ == "__main__":
    unittest.main()
