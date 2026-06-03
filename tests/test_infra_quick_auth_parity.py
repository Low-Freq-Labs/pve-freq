"""Infra quick auth parity tests.

Proves:
1. _is_auth_failure detects SSH permission denied errors
2. Infra quick probe marks auth failures with auth_failed=true
3. Infra quick separates network reachability from SSH/API auth failures
4. probe_method field is set for all probe outcomes
5. Unknown device types note that /api/health has authoritative SSH state

Fixes Finn-reported divergence: /api/fleet/overview marked the firewall
network-reachable, then /api/infra/quick overwrote the Core Systems card
as unreachable because SSH metrics auth failed. Infrastructure cards must
show reachable network state and auth/metrics failure separately.
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
        self.assertIn('"network" if d["reachable"] else "none"', src,
                       "Network fallback must set probe_method='network' or 'none'")

    def test_pfsense_probe_uses_runtime_device_credentials(self):
        src = self._probe_src()
        block = src.split('if dt == "pfsense":')[1].split('\n            elif dt == "truenas":')[0]
        self.assertIn("pfsense_auth", block)
        self.assertIn('user=pfsense_auth["user"]', block)
        self.assertIn('key_path=pfsense_auth["key_path"]', block)
        self.assertNotIn("user=svc_user", block)


class TestInfraAuthFailureKeepsNetworkTruth(unittest.TestCase):
    """SSH auth failure must not erase network reachability."""

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
        # Each "elif _is_auth_failure" branch must set d["auth_failed"] = True.
        # Skip non-elif occurrences (e.g. idrac's retry gate which triggers
        # a sshpass fallback rather than being the terminal handler).
        pattern = re.compile(r'elif _is_auth_failure\(r\.stderr\):(.*?)(?=\n                (?:else|elif |\Z))', re.DOTALL)
        for m in pattern.finditer(src):
            self.assertIn('d["auth_failed"] = True', m.group(1),
                           "elif _is_auth_failure branch must set auth_failed=True")

    def test_auth_failure_rechecks_network_reachability(self):
        """Auth failure branches must classify network reachability separately."""
        src = self._probe_src()
        pattern = re.compile(r'elif _is_auth_failure\(r\.stderr\):(.*?)(?=\n                (?:else|elif |\Z))', re.DOTALL)
        for m in pattern.finditer(src):
            block = m.group(1)
            self.assertIn('d["reachable"] = _network_reachable(dev)', block,
                          "Auth failure branch must preserve network reachability truth")
            self.assertNotIn('d["reachable"] = False', block,
                             "Auth failure branch must not force network unreachable")

    def test_dashboard_renders_auth_failed_as_warning_not_reachable(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        self.assertIn("statusLabel='AUTH FAILED'", src)
        self.assertIn("dotClass='warn'", src)
        self.assertIn("authFailed?'AUTH FAILED'", src)
        self.assertNotIn("if(dev.reachable&&dev.auth_failed)statusLabel='REACHABLE'", src)


class TestIdracProbeParity(unittest.TestCase):
    """iDRAC probe MUST mirror init._verify_host to stay in parity with
    `freq init --check` and `freq fleet status`. Finn filed a hard-E2E bug
    where infra_quick reported auth_failed on BMCs while init/fleet both
    verified them UP as freq-admin. The root cause: old probe used sshpass
    with SUDO_USER as the SSH user and a hardcoded credential path, then
    fell back to root@ via key. Fix: use cfg.ssh_service_account + RSA key
    first (matching init), then cfg.legacy_password_file as sshpass fallback."""

    def _probe_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _probe_device")[1].split("\n    devices = ")[0]

    def _idrac_block(self):
        src = self._probe_src()
        return src.split('elif dt == "idrac":')[1].split("\n            else:")[0]

    def test_uses_svc_user_not_bootstrap_user(self):
        """iDRAC probe MUST use cfg.ssh_service_account, not SUDO_USER."""
        block = self._idrac_block()
        self.assertIn("cfg.ssh_service_account", block,
                       "iDRAC probe must use cfg.ssh_service_account (freq-admin)")
        # No bootstrap_user reference in the idrac block — that's the operator
        # running the web UI, not the BMC account
        self.assertNotIn("bootstrap_user", block,
                          "iDRAC probe must NOT use bootstrap_user (operator, not BMC account)")

    def test_does_not_use_root_user(self):
        """iDRAC probe must NOT use user=root (init verifies as svc_user)."""
        block = self._idrac_block()
        self.assertNotIn('user="root"', block,
                          "iDRAC probe must not hardcode user=root")
        self.assertNotIn("user='root'", block,
                          "iDRAC probe must not hardcode user=root")

    def test_does_not_hardcode_switch_password_path(self):
        """iDRAC probe must not hardcode credentials/switch-password path.
        Must use cfg.legacy_password_file like init._verify_host does."""
        block = self._idrac_block()
        self.assertNotIn('"credentials"', block,
                          "iDRAC probe must not hardcode credentials/switch-password")
        self.assertNotIn("switch-password", block,
                          "iDRAC probe must not hardcode switch-password filename")

    def test_key_auth_tried_first(self):
        """Key auth must be tried FIRST (matching init), sshpass as fallback."""
        block = self._idrac_block()
        ssh_idx = block.find('"ssh"')
        sshpass_idx = block.find('"sshpass"')
        # Key auth ssh command must appear before sshpass fallback
        self.assertGreaterEqual(ssh_idx, 0, "Key auth ssh command must be present")
        if sshpass_idx >= 0:
            self.assertLess(ssh_idx, sshpass_idx,
                             "Key auth must be attempted BEFORE sshpass fallback (matches init)")

    def test_sshpass_fallback_uses_legacy_password_file(self):
        """Sshpass fallback must read from cfg.legacy_password_file."""
        block = self._idrac_block()
        self.assertIn("legacy_password_file", block,
                       "iDRAC probe must use cfg.legacy_password_file for fallback")

    def test_fallback_is_conditional_on_auth_failure(self):
        """Sshpass fallback must only trigger on auth failure, not every
        failure (avoids wasting sshpass calls against down hosts)."""
        block = self._idrac_block()
        self.assertIn("_is_auth_failure", block,
                       "iDRAC fallback must be gated on _is_auth_failure")

    def test_idrac_cipher_opts_applied(self):
        """Both key and password attempts must pass iDRAC extra_opts so the
        cipher/kex/pubkey negotiation matches what init uses."""
        block = self._idrac_block()
        self.assertIn("idrac_opts", block,
                       "iDRAC probe must apply PLATFORM_SSH idrac extra_opts")
        # idrac_opts must be sourced from PLATFORM_SSH
        self.assertIn("PLATFORM_SSH", block,
                       "idrac_opts must come from PLATFORM_SSH (single source of truth)")


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
