"""Tests for FREQ policy modules and PolicyExecutor/PolicyStore.

Covers:
  - freq/engine/policies/ntp_sync.py
  - freq/engine/policies/rpcbind.py
  - freq/engine/policies/ssh_hardening.py
  - freq/engine/policy.py (PolicyExecutor, PolicyStore)

~20 tests covering policy data structures, scope matching, desired state
resolution, comparison logic, fix command generation, and diff output.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.core.types import Host, Finding, Severity, Phase
from freq.engine.policy import PolicyExecutor, PolicyStore
from freq.engine.policies.ntp_sync import POLICY as NTP_POLICY
from freq.engine.policies.rpcbind import POLICY as RPCBIND_POLICY
from freq.engine.policies.ssh_hardening import POLICY as SSH_POLICY
from freq.engine.policies import ALL_POLICIES


# --- Helpers ---

def _host(htype="linux", label="test-host", ip="10.0.0.1"):
    return Host(ip=ip, label=label, htype=htype)


# === Policy Data Tests ===

class TestNTPPolicyData(unittest.TestCase):
    """Validate the NTP sync policy dict structure."""

    def test_name(self):
        self.assertEqual(NTP_POLICY["name"], "ntp-sync")

    def test_scope_includes_linux_pve_docker(self):
        scope = NTP_POLICY["scope"]
        self.assertIn("linux", scope)
        self.assertIn("pve", scope)
        self.assertIn("docker", scope)

    def test_resource_type_is_file_line(self):
        res = NTP_POLICY["resources"][0]
        self.assertEqual(res["type"], "file_line")
        self.assertEqual(res["path"], "/etc/systemd/timesyncd.conf")

    def test_ntp_entries(self):
        entries = NTP_POLICY["resources"][0]["entries"]
        self.assertEqual(entries["NTP"], "2.debian.pool.ntp.org")
        self.assertEqual(entries["FallbackNTP"], "ntp.ubuntu.com")

    def test_after_change_restarts_timesyncd(self):
        after = NTP_POLICY["resources"][0]["after_change"]
        self.assertIn("linux", after)
        self.assertIn("systemctl restart systemd-timesyncd", after["linux"])


class TestRPCBindPolicyData(unittest.TestCase):
    """Validate the rpcbind policy dict structure."""

    def test_name(self):
        self.assertEqual(RPCBIND_POLICY["name"], "rpcbind-disable")

    def test_scope_excludes_pve(self):
        scope = RPCBIND_POLICY["scope"]
        self.assertIn("linux", scope)
        self.assertIn("docker", scope)
        self.assertNotIn("pve", scope)

    def test_resource_type_is_command_check(self):
        res = RPCBIND_POLICY["resources"][0]
        self.assertEqual(res["type"], "command_check")
        self.assertEqual(res["key"], "rpcbind")

    def test_fix_cmd_disables_rpcbind(self):
        res = RPCBIND_POLICY["resources"][0]
        self.assertIn("systemctl disable rpcbind", res["fix_cmd"])


class TestSSHHardeningPolicyData(unittest.TestCase):
    """Validate the SSH hardening policy dict structure."""

    def test_name(self):
        self.assertEqual(SSH_POLICY["name"], "ssh-hardening")

    def test_scope_covers_all_platforms(self):
        scope = SSH_POLICY["scope"]
        for p in ("linux", "pve", "docker"):
            self.assertIn(p, scope)

    def test_max_auth_tries_platform_specific(self):
        entries = SSH_POLICY["resources"][0]["entries"]
        mat = entries["MaxAuthTries"]
        self.assertIsInstance(mat, dict)
        self.assertEqual(mat["linux"], "3")
        self.assertEqual(mat["pve"], "5")
        self.assertEqual(mat["docker"], "3")

    def test_password_auth_is_uniform(self):
        entries = SSH_POLICY["resources"][0]["entries"]
        self.assertEqual(entries["PasswordAuthentication"], "no")


# === PolicyExecutor Tests ===

class TestPolicyExecutorApplies(unittest.TestCase):
    """Test PolicyExecutor.applies_to and applicable_resources."""

    def test_ntp_applies_to_linux(self):
        ex = PolicyExecutor(NTP_POLICY)
        self.assertTrue(ex.applies_to(_host("linux")))

    def test_ntp_applies_to_docker(self):
        ex = PolicyExecutor(NTP_POLICY)
        self.assertTrue(ex.applies_to(_host("docker")))

    def test_rpcbind_does_not_apply_to_pve(self):
        ex = PolicyExecutor(RPCBIND_POLICY)
        self.assertFalse(ex.applies_to(_host("pve")))

    def test_ssh_applies_to_pve(self):
        ex = PolicyExecutor(SSH_POLICY)
        self.assertTrue(ex.applies_to(_host("pve")))

    def test_applies_to_is_case_insensitive(self):
        ex = PolicyExecutor(SSH_POLICY)
        h = _host("PVE")
        self.assertTrue(ex.applies_to(h))

    def test_applicable_resources_returns_list(self):
        ex = PolicyExecutor(NTP_POLICY)
        res = ex.applicable_resources(_host("linux"))
        self.assertIsInstance(res, list)
        self.assertEqual(len(res), 1)


class TestPolicyExecutorDesiredState(unittest.TestCase):
    """Test desired_state resolution including platform overrides."""

    def test_ntp_desired_state_linux(self):
        ex = PolicyExecutor(NTP_POLICY)
        desired = ex.desired_state(_host("linux"))
        self.assertEqual(desired["NTP"], "2.debian.pool.ntp.org")
        self.assertEqual(desired["FallbackNTP"], "ntp.ubuntu.com")

    def test_ssh_desired_state_linux_max_auth(self):
        ex = PolicyExecutor(SSH_POLICY)
        desired = ex.desired_state(_host("linux"))
        self.assertEqual(desired["MaxAuthTries"], "3")

    def test_ssh_desired_state_pve_max_auth(self):
        ex = PolicyExecutor(SSH_POLICY)
        desired = ex.desired_state(_host("pve"))
        self.assertEqual(desired["MaxAuthTries"], "5")

    def test_ssh_desired_state_uniform_values(self):
        ex = PolicyExecutor(SSH_POLICY)
        desired = ex.desired_state(_host("linux"))
        self.assertEqual(desired["PasswordAuthentication"], "no")
        self.assertEqual(desired["X11Forwarding"], "no")
        self.assertEqual(desired["PermitEmptyPasswords"], "no")
        self.assertEqual(desired["ClientAliveInterval"], "300")
        self.assertEqual(desired["ClientAliveCountMax"], "2")

    def test_rpcbind_desired_state(self):
        ex = PolicyExecutor(RPCBIND_POLICY)
        desired = ex.desired_state(_host("linux"))
        self.assertEqual(desired["rpcbind"], "disabled")


class TestPolicyExecutorCompare(unittest.TestCase):
    """Test the compare method — finding drift between current and desired."""

    def test_compliant_returns_no_findings(self):
        ex = PolicyExecutor(NTP_POLICY)
        current = {"NTP": "2.debian.pool.ntp.org", "FallbackNTP": "ntp.ubuntu.com"}
        desired = {"NTP": "2.debian.pool.ntp.org", "FallbackNTP": "ntp.ubuntu.com"}
        findings = ex.compare(current, desired)
        self.assertEqual(len(findings), 0)

    def test_drift_returns_findings(self):
        ex = PolicyExecutor(NTP_POLICY)
        current = {"NTP": "pool.ntp.org", "FallbackNTP": "ntp.ubuntu.com"}
        desired = {"NTP": "2.debian.pool.ntp.org", "FallbackNTP": "ntp.ubuntu.com"}
        findings = ex.compare(current, desired)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].key, "NTP")
        self.assertEqual(findings[0].current, "pool.ntp.org")
        self.assertEqual(findings[0].desired, "2.debian.pool.ntp.org")
        self.assertEqual(findings[0].severity, Severity.WARN)

    def test_missing_key_shows_not_set(self):
        ex = PolicyExecutor(SSH_POLICY)
        current = {}
        desired = {"PasswordAuthentication": "no"}
        findings = ex.compare(current, desired)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].current, "(not set)")

    def test_whitespace_normalized(self):
        ex = PolicyExecutor(NTP_POLICY)
        current = {"NTP": " 2.debian.pool.ntp.org "}
        desired = {"NTP": "2.debian.pool.ntp.org"}
        findings = ex.compare(current, desired)
        self.assertEqual(len(findings), 0)


class TestPolicyExecutorFixCommands(unittest.TestCase):
    """Test fix command generation."""

    def test_file_line_generates_sed_command(self):
        ex = PolicyExecutor(SSH_POLICY)
        finding = Finding(
            resource_type="config",
            key="PasswordAuthentication",
            current="yes",
            desired="no",
        )
        cmds = ex.fix_commands(_host("linux"), [finding])
        self.assertTrue(len(cmds) >= 1)
        # Should reference sshd_config path and sed
        cmd = cmds[0]
        self.assertIn("sed", cmd)
        self.assertIn("/etc/ssh/sshd_config", cmd)

    def test_command_check_uses_fix_cmd(self):
        ex = PolicyExecutor(RPCBIND_POLICY)
        finding = Finding(
            resource_type="config",
            key="rpcbind",
            current="enabled",
            desired="disabled",
        )
        cmds = ex.fix_commands(_host("linux"), [finding])
        self.assertTrue(len(cmds) >= 1)
        self.assertIn("systemctl disable rpcbind", cmds[0])


class TestPolicyExecutorActivateCommands(unittest.TestCase):
    """Test activate (after_change) command generation."""

    def test_ntp_activate_linux(self):
        ex = PolicyExecutor(NTP_POLICY)
        cmds = ex.activate_commands(_host("linux"))
        self.assertEqual(len(cmds), 1)
        self.assertIn("systemctl restart systemd-timesyncd", cmds[0])

    def test_ssh_activate_pve(self):
        ex = PolicyExecutor(SSH_POLICY)
        cmds = ex.activate_commands(_host("pve"))
        self.assertEqual(len(cmds), 1)
        self.assertIn("systemctl restart sshd", cmds[0])

    def test_rpcbind_activate_is_empty(self):
        ex = PolicyExecutor(RPCBIND_POLICY)
        cmds = ex.activate_commands(_host("linux"))
        self.assertEqual(len(cmds), 0)


class TestPolicyExecutorDiff(unittest.TestCase):
    """Test diff_text output."""

    def test_diff_with_drift(self):
        ex = PolicyExecutor(NTP_POLICY)
        current = {"NTP": "pool.ntp.org"}
        desired = {"NTP": "2.debian.pool.ntp.org"}
        diff = ex.diff_text(current, desired)
        self.assertIn("-NTP = pool.ntp.org", diff)
        self.assertIn("+NTP = 2.debian.pool.ntp.org", diff)

    def test_diff_no_drift(self):
        ex = PolicyExecutor(NTP_POLICY)
        current = {"NTP": "2.debian.pool.ntp.org"}
        desired = {"NTP": "2.debian.pool.ntp.org"}
        diff = ex.diff_text(current, desired)
        self.assertEqual(diff, "")


# === PolicyStore Tests ===

class TestPolicyStore(unittest.TestCase):
    """Test the PolicyStore registry."""

    def test_register_and_get(self):
        store = PolicyStore()
        store.register(NTP_POLICY)
        result = store.get("ntp-sync")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "ntp-sync")

    def test_get_nonexistent_returns_none(self):
        store = PolicyStore()
        self.assertIsNone(store.get("no-such-policy"))

    def test_list_all(self):
        store = PolicyStore()
        for p in ALL_POLICIES:
            store.register(p)
        listed = store.list()
        self.assertEqual(len(listed), 3)
        names = {p["name"] for p in listed}
        self.assertEqual(names, {"ntp-sync", "rpcbind-disable", "ssh-hardening"})

    def test_for_host_filters_by_type(self):
        store = PolicyStore()
        for p in ALL_POLICIES:
            store.register(p)
        # PVE host should NOT match rpcbind
        pve_policies = store.for_host(_host("pve"))
        pve_names = {p["name"] for p in pve_policies}
        self.assertIn("ntp-sync", pve_names)
        self.assertIn("ssh-hardening", pve_names)
        self.assertNotIn("rpcbind-disable", pve_names)

    def test_for_host_linux_gets_all_three(self):
        store = PolicyStore()
        for p in ALL_POLICIES:
            store.register(p)
        linux_policies = store.for_host(_host("linux"))
        self.assertEqual(len(linux_policies), 3)


class TestALLPoliciesRegistry(unittest.TestCase):
    """Test the ALL_POLICIES list from __init__.py."""

    def test_all_policies_has_three(self):
        self.assertEqual(len(ALL_POLICIES), 3)

    def test_all_policies_are_dicts(self):
        for p in ALL_POLICIES:
            self.assertIsInstance(p, dict)
            self.assertIn("name", p)
            self.assertIn("scope", p)
            self.assertIn("resources", p)


if __name__ == "__main__":
    unittest.main()
