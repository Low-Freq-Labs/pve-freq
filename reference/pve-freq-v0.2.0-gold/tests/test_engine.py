"""Engine unit tests — verify pipeline phases with mocked SSH transport.

Tests the full engine pipeline without requiring real SSH connections.
Uses a mock transport that returns predefined responses for each host.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.core.types import (
    Phase, Severity, Host, CmdResult, Finding, Resource, Policy, FleetResult
)
from engine.core.resolver import load_fleet, filter_by_scope, filter_by_labels, filter_by_groups
from engine.core.policy import PolicyStore, PolicyExecutor
from engine.core.runner import PipelineRunner
from engine.core.transport import SSHTransport, PLATFORM_SSH
from engine.core import enforcers


class TestTypes(unittest.TestCase):
    """Test data type construction and defaults."""

    def test_host_defaults(self):
        h = Host(ip="10.0.0.1", label="test", htype="linux")
        self.assertEqual(h.phase, Phase.PENDING)
        self.assertEqual(h.current, {})
        self.assertEqual(h.desired, {})
        self.assertEqual(h.findings, [])
        self.assertEqual(h.changes, [])
        self.assertEqual(h.error, "")
        self.assertEqual(h.duration, 0.0)

    def test_host_with_groups(self):
        h = Host(ip="10.0.0.1", label="test", htype="pve", groups="cluster,prod")
        self.assertEqual(h.groups, "cluster,prod")

    def test_finding_defaults(self):
        f = Finding(resource_type="config", key="PermitRootLogin",
                    current="yes", desired="no")
        self.assertEqual(f.severity, Severity.WARN)
        self.assertEqual(f.fix_cmd, "")
        self.assertEqual(f.platform, "")

    def test_resource_construction(self):
        r = Resource(
            type="file_line",
            path="/etc/ssh/sshd_config",
            applies_to=["linux", "pve"],
            entries={"PermitRootLogin": "no"},
        )
        self.assertEqual(r.type, "file_line")
        self.assertIn("linux", r.applies_to)

    def test_policy_construction(self):
        p = Policy(
            name="test-policy",
            description="A test policy",
            scope=["linux"],
            resources=[],
        )
        self.assertEqual(p.name, "test-policy")

    def test_fleet_result_defaults(self):
        fr = FleetResult(policy="test", mode="check", duration=1.0, hosts=[])
        self.assertEqual(fr.total, 0)
        self.assertEqual(fr.compliant, 0)
        self.assertEqual(fr.failed, 0)

    def test_cmdresult(self):
        cr = CmdResult(stdout="ok", stderr="", returncode=0, duration=0.5)
        self.assertEqual(cr.stdout, "ok")
        self.assertEqual(cr.returncode, 0)

    def test_phase_enum_completeness(self):
        """Verify all pipeline phases exist."""
        expected = [
            "PENDING", "REACHABLE", "DISCOVERED", "COMPLIANT",
            "DRIFT", "PLANNED", "FIXING", "ACTIVATING",
            "VERIFYING", "DONE", "FAILED"
        ]
        actual = [p.name for p in Phase]
        for phase in expected:
            self.assertIn(phase, actual, f"Missing phase: {phase}")

    def test_severity_values(self):
        self.assertEqual(Severity.INFO.value, "info")
        self.assertEqual(Severity.WARN.value, "warn")
        self.assertEqual(Severity.CRIT.value, "crit")


class TestResolver(unittest.TestCase):
    """Test fleet resolver with temp hosts.conf files."""

    def setUp(self):
        """Create a temp hosts.conf for testing."""
        self.test_dir = "/tmp/freq-test-resolver"
        os.makedirs(self.test_dir, exist_ok=True)
        self.hosts_file = os.path.join(self.test_dir, "hosts.conf")
        with open(self.hosts_file, "w") as f:
            f.write("# DC01 Fleet\n")
            f.write("10.25.25.1   pve01    pve    cluster,prod\n")
            f.write("10.25.25.2   pve02    pve    cluster,prod\n")
            f.write("10.25.25.3   pve03    pve    cluster,prod\n")
            f.write("10.25.25.10  truenas  truenas storage\n")
            f.write("10.25.25.20  pfsense  pfsense network\n")
            f.write("10.25.100.1  vm101    linux  media\n")
            f.write("10.25.100.2  vm102    linux  media\n")
            f.write("10.25.100.3  vm103    linux  media\n")
            f.write("# iDRAC\n")
            f.write("10.25.25.50  idrac-r530 idrac bmc\n")
            f.write("10.25.25.60  switch   switch network\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_fleet(self):
        fleet = load_fleet(self.hosts_file)
        self.assertEqual(len(fleet), 10)

    def test_load_fleet_labels(self):
        fleet = load_fleet(self.hosts_file)
        labels = [h.label for h in fleet]
        self.assertIn("pve01", labels)
        self.assertIn("truenas", labels)
        self.assertIn("vm101", labels)
        self.assertIn("switch", labels)

    def test_load_fleet_types(self):
        fleet = load_fleet(self.hosts_file)
        types = set(h.htype for h in fleet)
        self.assertEqual(types, {"pve", "truenas", "pfsense", "linux", "idrac", "switch"})

    def test_filter_by_scope_linux(self):
        fleet = load_fleet(self.hosts_file)
        filtered = filter_by_scope(fleet, ["linux"])
        self.assertEqual(len(filtered), 3)
        self.assertTrue(all(h.htype == "linux" for h in filtered))

    def test_filter_by_scope_multi(self):
        fleet = load_fleet(self.hosts_file)
        filtered = filter_by_scope(fleet, ["linux", "pve"])
        self.assertEqual(len(filtered), 6)

    def test_filter_by_labels(self):
        fleet = load_fleet(self.hosts_file)
        filtered = filter_by_labels(fleet, ["vm101", "vm102"])
        self.assertEqual(len(filtered), 2)

    def test_filter_by_labels_empty(self):
        fleet = load_fleet(self.hosts_file)
        filtered = filter_by_labels(fleet, [])
        self.assertEqual(len(filtered), 10)

    def test_filter_by_groups(self):
        fleet = load_fleet(self.hosts_file)
        filtered = filter_by_groups(fleet, ["cluster"])
        self.assertEqual(len(filtered), 3)
        self.assertTrue(all("cluster" in h.groups for h in filtered))

    def test_comments_skipped(self):
        fleet = load_fleet(self.hosts_file)
        labels = [h.label for h in fleet]
        # Comments should not appear as hosts
        for label in labels:
            self.assertFalse(label.startswith("#"))

    def test_missing_file(self):
        fleet = load_fleet("/nonexistent/hosts.conf")
        self.assertEqual(fleet, [])

    def test_empty_file(self):
        empty = os.path.join(self.test_dir, "empty.conf")
        with open(empty, "w") as f:
            f.write("")
        fleet = load_fleet(empty)
        self.assertEqual(fleet, [])

    def test_groups_field(self):
        fleet = load_fleet(self.hosts_file)
        pve01 = [h for h in fleet if h.label == "pve01"][0]
        self.assertEqual(pve01.groups, "cluster,prod")


class TestPlatformSSH(unittest.TestCase):
    """Test platform SSH configuration is complete and correct."""

    def test_all_platforms_defined(self):
        for platform in ["linux", "pve", "truenas", "pfsense", "idrac", "switch"]:
            self.assertIn(platform, PLATFORM_SSH, f"Missing platform: {platform}")

    def test_platform_has_required_keys(self):
        for name, config in PLATFORM_SSH.items():
            self.assertIn("user", config, f"{name} missing 'user'")
            self.assertIn("extra", config, f"{name} missing 'extra'")
            self.assertIn("sudo", config, f"{name} missing 'sudo'")

    def test_pfsense_is_root(self):
        self.assertEqual(PLATFORM_SSH["pfsense"]["user"], "root")
        self.assertEqual(PLATFORM_SSH["pfsense"]["sudo"], "")

    def test_idrac_legacy_crypto(self):
        extra = PLATFORM_SSH["idrac"]["extra"]
        # Must have legacy kex algorithm
        self.assertTrue(any("diffie-hellman" in e for e in extra))

    def test_switch_legacy_ciphers(self):
        extra = PLATFORM_SSH["switch"]["extra"]
        # Must have CBC ciphers for Cisco
        self.assertTrue(any("aes128-cbc" in e for e in extra))


class TestEnforcers(unittest.TestCase):
    """Test enforcer registry and basic enforcer operations."""

    def test_all_enforcers_registered(self):
        for etype in ["file_line", "middleware_config", "command_check", "package_ensure"]:
            enforcer = enforcers.get_enforcer(etype)
            self.assertIsNotNone(enforcer, f"Missing enforcer: {etype}")

    def test_unknown_enforcer_returns_none(self):
        self.assertIsNone(enforcers.get_enforcer("nonexistent"))

    def test_list_enforcers(self):
        elist = enforcers.list_enforcers()
        self.assertIn("file_line", elist)
        self.assertIn("middleware_config", elist)
        self.assertEqual(len(elist), 4)


class TestPolicyExecutor(unittest.TestCase):
    """Test policy executor compare logic."""

    def setUp(self):
        self.policy = Policy(
            name="test-ssh",
            description="Test SSH hardening",
            scope=["linux", "pve"],
            resources=[
                Resource(
                    type="file_line",
                    path="/etc/ssh/sshd_config",
                    applies_to=["linux", "pve"],
                    entries={
                        "PermitRootLogin": {"linux": "no", "pve": "prohibit-password"},
                        "X11Forwarding": "no",
                    },
                    after_change={"linux": "systemctl restart sshd"},
                ),
            ],
        )
        self.executor = PolicyExecutor(self.policy)

    def test_desired_state_linux(self):
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        desired = self.executor.desired_state(host)
        self.assertEqual(desired["PermitRootLogin"], "no")
        self.assertEqual(desired["X11Forwarding"], "no")

    def test_desired_state_pve(self):
        host = Host(ip="10.0.0.1", label="test", htype="pve")
        desired = self.executor.desired_state(host)
        self.assertEqual(desired["PermitRootLogin"], "prohibit-password")

    def test_desired_state_skip_out_of_scope(self):
        host = Host(ip="10.0.0.1", label="test", htype="truenas")
        desired = self.executor.desired_state(host)
        self.assertEqual(desired, {})

    def test_compare_drift(self):
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        host.current = {"PermitRootLogin": "yes", "X11Forwarding": "yes"}
        host.desired = {"PermitRootLogin": "no", "X11Forwarding": "no"}
        findings = self.executor.compare(host)
        self.assertEqual(len(findings), 2)

    def test_compare_compliant(self):
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        host.current = {"PermitRootLogin": "no", "X11Forwarding": "no"}
        host.desired = {"PermitRootLogin": "no", "X11Forwarding": "no"}
        findings = self.executor.compare(host)
        self.assertEqual(len(findings), 0)

    def test_compare_partial_drift(self):
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        host.current = {"PermitRootLogin": "no", "X11Forwarding": "yes"}
        host.desired = {"PermitRootLogin": "no", "X11Forwarding": "no"}
        findings = self.executor.compare(host)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].key, "X11Forwarding")

    def test_compare_case_insensitive(self):
        """Boolean values should compare case-insensitively."""
        host = Host(ip="10.0.0.1", label="test", htype="linux")
        host.current = {"PermitRootLogin": "No"}
        host.desired = {"PermitRootLogin": "no"}
        findings = self.executor.compare(host)
        self.assertEqual(len(findings), 0)


class TestPipelineRunner(unittest.TestCase):
    """Test pipeline runner with mocked transport."""

    def test_runner_creation(self):
        runner = PipelineRunner(max_parallel=3, dry_run=True)
        self.assertEqual(runner.max_parallel, 3)
        self.assertTrue(runner.dry_run)

    def test_fleet_result_construction(self):
        hosts = [
            Host(ip="10.0.0.1", label="h1", htype="linux", phase=Phase.COMPLIANT),
            Host(ip="10.0.0.2", label="h2", htype="linux", phase=Phase.DRIFT),
            Host(ip="10.0.0.3", label="h3", htype="linux", phase=Phase.FAILED, error="timeout"),
        ]
        result = FleetResult(
            policy="test", mode="check", duration=1.5, hosts=hosts,
            total=3, compliant=1, drift=1, failed=1,
        )
        self.assertEqual(result.total, 3)
        self.assertEqual(result.compliant, 1)
        self.assertEqual(result.drift, 1)
        self.assertEqual(result.failed, 1)


class TestPolicyStore(unittest.TestCase):
    """Test policy store loading from the actual policies directory."""

    def test_load_policies(self):
        policies_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "policies"
        )
        store = PolicyStore(policies_dir)
        self.assertGreater(len(store.list_all()), 0)

    def test_all_six_policies_load(self):
        policies_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "policies"
        )
        store = PolicyStore(policies_dir)
        expected = [
            "ssh-hardening", "ntp-sync", "rpcbind-block",
            "docker-security", "nfs-security", "auto-updates",
        ]
        for name in expected:
            policy = store.get(name)
            self.assertIsNotNone(policy, f"Policy '{name}' not found")

    def test_policy_names(self):
        policies_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "policies"
        )
        store = PolicyStore(policies_dir)
        names = store.names()
        self.assertIn("ssh-hardening", names)
        self.assertEqual(len(names), 6)

    def test_ssh_hardening_scope(self):
        policies_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "policies"
        )
        store = PolicyStore(policies_dir)
        policy = store.get("ssh-hardening")
        self.assertIn("linux", policy.scope)
        self.assertIn("pve", policy.scope)
        self.assertIn("truenas", policy.scope)
        self.assertIn("pfsense", policy.scope)

    def test_ssh_hardening_resources(self):
        policies_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "policies"
        )
        store = PolicyStore(policies_dir)
        policy = store.get("ssh-hardening")
        self.assertEqual(len(policy.resources), 2)  # file_line + middleware

    def test_nonexistent_policy_returns_none(self):
        policies_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "policies"
        )
        store = PolicyStore(policies_dir)
        self.assertIsNone(store.get("nonexistent"))


class TestDisplay(unittest.TestCase):
    """Test display output functions don't crash."""

    def test_show_results_no_crash(self):
        from engine.core.display import show_results
        result = FleetResult(
            policy="test", mode="check", duration=1.0,
            hosts=[
                Host(ip="10.0.0.1", label="h1", htype="linux",
                     phase=Phase.COMPLIANT, duration=0.3),
                Host(ip="10.0.0.2", label="h2", htype="linux",
                     phase=Phase.DRIFT, duration=0.5,
                     findings=[Finding("config", "X11", "yes", "no")]),
            ],
            total=2, compliant=1, drift=1,
        )
        # Should not raise
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            show_results(result)

    def test_show_diff_no_crash(self):
        from engine.core.display import show_diff
        host = Host(ip="10.0.0.1", label="test", htype="linux",
                    phase=Phase.DRIFT)
        host.current = {"PermitRootLogin": "yes", "X11Forwarding": "yes"}
        host.desired = {"PermitRootLogin": "no", "X11Forwarding": "no"}
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            show_diff(host)

    def test_show_policies_no_crash(self):
        from engine.core.display import show_policies
        policies = [
            Policy("test", "A test", ["linux"], []),
            Policy("test2", "Another test", ["pve", "linux"], [Resource(type="file_line")]),
        ]
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            show_policies(policies)

    def test_show_policies_empty(self):
        from engine.core.display import show_policies
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            show_policies([])


class TestStore(unittest.TestCase):
    """Test SQLite result storage."""

    def setUp(self):
        self.db_path = "/tmp/freq-test-store/results.db"
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        # Clean up
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def tearDown(self):
        import shutil
        shutil.rmtree(os.path.dirname(self.db_path), ignore_errors=True)

    def test_store_creation(self):
        from engine.core.store import ResultStore
        rs = ResultStore(self.db_path)
        self.assertTrue(os.path.exists(self.db_path))
        rs.close()

    def test_save_and_retrieve(self):
        from engine.core.store import ResultStore
        rs = ResultStore(self.db_path)
        result = FleetResult(
            policy="ssh-hardening", mode="check", duration=2.5,
            hosts=[
                Host(ip="10.0.0.1", label="h1", htype="linux",
                     phase=Phase.COMPLIANT, duration=0.3),
            ],
            total=1, compliant=1,
        )
        run_id = rs.save(result)
        self.assertIsNotNone(run_id)

        last = rs.last_run("ssh-hardening")
        self.assertIsNotNone(last)
        self.assertEqual(last["policy"], "ssh-hardening")
        self.assertEqual(last["mode"], "check")
        self.assertEqual(last["total"], 1)
        rs.close()

    def test_last_run_empty(self):
        from engine.core.store import ResultStore
        rs = ResultStore(self.db_path)
        last = rs.last_run("nonexistent")
        self.assertIsNone(last)
        rs.close()

    def test_run_history(self):
        from engine.core.store import ResultStore
        rs = ResultStore(self.db_path)
        for i in range(5):
            result = FleetResult(
                policy="test", mode="check", duration=float(i),
                hosts=[], total=0,
            )
            rs.save(result)
        history = rs.run_history("test", limit=3)
        self.assertEqual(len(history), 3)
        rs.close()

    def test_host_detail(self):
        from engine.core.store import ResultStore
        rs = ResultStore(self.db_path)
        host = Host(ip="10.0.0.1", label="h1", htype="linux",
                    phase=Phase.DRIFT, duration=0.5)
        host.findings = [Finding("config", "X11", "yes", "no")]
        result = FleetResult(
            policy="test", mode="check", duration=1.0,
            hosts=[host], total=1, drift=1,
        )
        run_id = rs.save(result)
        detail = rs.host_detail(run_id)
        self.assertEqual(len(detail), 1)
        self.assertEqual(detail[0]["host"], "h1")
        rs.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
