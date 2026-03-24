"""Policy validation tests — verify all 6 policy dicts parse correctly.

Tests that every policy:
- Has required keys (name, description, scope, resources)
- Has valid scope entries (known host types)
- Has valid resource types (registered enforcers)
- Has valid applies_to entries
- Has after_change matching applies_to platforms
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.core.types import Policy, Resource
from engine.core.policy import PolicyStore
from engine.core import enforcers

VALID_HOST_TYPES = {"linux", "pve", "truenas", "pfsense", "idrac", "switch"}
VALID_ENFORCER_TYPES = set(enforcers.list_enforcers())

POLICIES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "engine", "policies"
)


class TestPolicyValidation(unittest.TestCase):
    """Validate all policies in the policies directory."""

    @classmethod
    def setUpClass(cls):
        cls.store = PolicyStore(POLICIES_DIR)
        cls.policies = cls.store.list_all()

    def test_policies_exist(self):
        """At least 6 policies should be loaded."""
        self.assertGreaterEqual(len(self.policies), 6)

    def test_expected_policies_present(self):
        """All expected policies must be loadable."""
        expected = [
            "ssh-hardening", "ntp-sync", "rpcbind-block",
            "docker-security", "nfs-security", "auto-updates",
        ]
        names = self.store.names()
        for name in expected:
            self.assertIn(name, names, f"Missing policy: {name}")

    def test_policy_names_unique(self):
        """No duplicate policy names."""
        names = [p.name for p in self.policies]
        self.assertEqual(len(names), len(set(names)))

    def test_policy_has_description(self):
        """Every policy must have a non-empty description."""
        for p in self.policies:
            self.assertTrue(p.description, f"{p.name} has empty description")
            self.assertGreater(len(p.description), 10,
                               f"{p.name} description too short")

    def test_policy_scope_valid(self):
        """Every policy scope must contain valid host types."""
        for p in self.policies:
            self.assertGreater(len(p.scope), 0,
                               f"{p.name} has empty scope")
            for htype in p.scope:
                self.assertIn(htype, VALID_HOST_TYPES,
                              f"{p.name} has invalid scope type: {htype}")

    def test_policy_has_resources(self):
        """Every policy must have at least one resource."""
        for p in self.policies:
            self.assertGreater(len(p.resources), 0,
                               f"{p.name} has no resources")

    def test_resource_type_valid(self):
        """Every resource must have a valid enforcer type."""
        for p in self.policies:
            for r in p.resources:
                self.assertIn(r.type, VALID_ENFORCER_TYPES,
                              f"{p.name} resource has invalid type: {r.type}")

    def test_resource_applies_to_valid(self):
        """Resource applies_to must contain valid host types."""
        for p in self.policies:
            for r in p.resources:
                self.assertGreater(len(r.applies_to), 0,
                                   f"{p.name} resource has empty applies_to")
                for htype in r.applies_to:
                    self.assertIn(htype, VALID_HOST_TYPES,
                                  f"{p.name} resource applies_to invalid: {htype}")

    def test_resource_applies_to_within_scope(self):
        """Resource applies_to must be a subset of policy scope."""
        for p in self.policies:
            for r in p.resources:
                for htype in r.applies_to:
                    self.assertIn(htype, p.scope,
                                  f"{p.name} resource applies to {htype} "
                                  f"but policy scope is {p.scope}")

    def test_file_line_has_path(self):
        """file_line resources must have a path."""
        for p in self.policies:
            for r in p.resources:
                if r.type == "file_line":
                    self.assertTrue(r.path,
                                    f"{p.name} file_line resource has no path")

    def test_command_check_has_check_cmd(self):
        """command_check resources must have a check_cmd."""
        for p in self.policies:
            for r in p.resources:
                if r.type == "command_check":
                    self.assertTrue(r.check_cmd,
                                    f"{p.name} command_check has no check_cmd")

    def test_package_ensure_has_package(self):
        """package_ensure resources must have a package name."""
        for p in self.policies:
            for r in p.resources:
                if r.type == "package_ensure":
                    self.assertTrue(r.package,
                                    f"{p.name} package_ensure has no package")

    def test_after_change_platforms_match_applies_to(self):
        """after_change keys must be valid platforms from applies_to."""
        for p in self.policies:
            for r in p.resources:
                for platform in r.after_change.keys():
                    self.assertIn(platform, r.applies_to,
                                  f"{p.name} after_change has {platform} "
                                  f"but applies_to is {r.applies_to}")


class TestSSHHardeningPolicy(unittest.TestCase):
    """Deep validation of the ssh-hardening reference policy."""

    @classmethod
    def setUpClass(cls):
        cls.store = PolicyStore(POLICIES_DIR)
        cls.policy = cls.store.get("ssh-hardening")

    def test_policy_exists(self):
        self.assertIsNotNone(self.policy)

    def test_scope_covers_all_ssh_platforms(self):
        self.assertIn("linux", self.policy.scope)
        self.assertIn("pve", self.policy.scope)
        self.assertIn("truenas", self.policy.scope)
        self.assertIn("pfsense", self.policy.scope)

    def test_has_file_line_resource(self):
        file_resources = [r for r in self.policy.resources if r.type == "file_line"]
        self.assertEqual(len(file_resources), 1)

    def test_has_middleware_resource(self):
        mw_resources = [r for r in self.policy.resources if r.type == "middleware_config"]
        self.assertEqual(len(mw_resources), 1)

    def test_file_line_targets_sshd_config(self):
        r = [r for r in self.policy.resources if r.type == "file_line"][0]
        self.assertEqual(r.path, "/etc/ssh/sshd_config")

    def test_pve_permit_root_login_is_prohibit_password(self):
        """PVE MUST be prohibit-password (cluster SSH requirement)."""
        r = [r for r in self.policy.resources if r.type == "file_line"][0]
        prl = r.entries["PermitRootLogin"]
        self.assertEqual(prl["pve"], "prohibit-password")

    def test_middleware_targets_truenas(self):
        r = [r for r in self.policy.resources if r.type == "middleware_config"][0]
        self.assertEqual(r.applies_to, ["truenas"])

    def test_truenas_root_login_false(self):
        r = [r for r in self.policy.resources if r.type == "middleware_config"][0]
        self.assertFalse(r.entries["rootlogin"])

    def test_after_change_restarts_sshd(self):
        r = [r for r in self.policy.resources if r.type == "file_line"][0]
        self.assertIn("sshd", r.after_change["linux"])
        self.assertIn("sshd", r.after_change["pve"])


class TestNTPPolicy(unittest.TestCase):
    """Validate NTP sync policy."""

    @classmethod
    def setUpClass(cls):
        cls.store = PolicyStore(POLICIES_DIR)
        cls.policy = cls.store.get("ntp-sync")

    def test_scope_linux_only(self):
        self.assertEqual(self.policy.scope, ["linux"])

    def test_targets_timesyncd(self):
        r = self.policy.resources[0]
        self.assertEqual(r.path, "/etc/systemd/timesyncd.conf")

    def test_has_ntp_server(self):
        r = self.policy.resources[0]
        self.assertIn("NTP", r.entries)

    def test_has_fallback(self):
        r = self.policy.resources[0]
        self.assertIn("FallbackNTP", r.entries)


class TestAutoUpdatesPolicy(unittest.TestCase):
    """Validate auto-updates policy."""

    @classmethod
    def setUpClass(cls):
        cls.store = PolicyStore(POLICIES_DIR)
        cls.policy = cls.store.get("auto-updates")

    def test_is_package_ensure(self):
        r = self.policy.resources[0]
        self.assertEqual(r.type, "package_ensure")

    def test_package_name(self):
        r = self.policy.resources[0]
        self.assertEqual(r.package, "unattended-upgrades")

    def test_applies_to_linux_and_pve(self):
        r = self.policy.resources[0]
        self.assertIn("linux", r.applies_to)
        self.assertIn("pve", r.applies_to)


if __name__ == "__main__":
    unittest.main(verbosity=2)
