"""Tests for freq/modules/engine_cmds.py.

Covers dispatch logic and command routing for:
  - cmd_policies: list available policies
  - cmd_check: policy compliance check (dry run)
  - cmd_fix: apply policy remediation
  - cmd_diff: show drift as diff
  - _build_store: store construction
  - _resolve_hosts: host filtering

All SSH/subprocess calls are mocked. Tests exercise the pure routing
logic, argument handling, and return codes.
"""
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.core.types import Host, Phase, FleetResult, Finding, Severity
from freq.modules.engine_cmds import (
    _build_store,
    _resolve_hosts,
    cmd_policies,
    cmd_check,
    cmd_fix,
    cmd_diff,
)


# --- Helpers ---

def _cfg(hosts=None):
    """Build a minimal FreqConfig-like object."""
    cfg = SimpleNamespace()
    if hosts is not None:
        cfg.hosts = hosts
    else:
        cfg.hosts = [
            Host(ip="10.0.0.1", label="web01", htype="linux", groups="web"),
            Host(ip="10.0.0.2", label="pve01", htype="pve", groups="cluster"),
            Host(ip="10.0.0.3", label="dock01", htype="docker", groups="docker"),
        ]
    cfg.ssh_key_path = "/tmp/fake_key"
    cfg.ssh_max_parallel = 5
    return cfg


def _args(**kwargs):
    """Build a minimal args namespace."""
    return SimpleNamespace(**kwargs)


def _fleet_result(hosts=None, compliant=0, drift=0, failed=0, fixed=0, duration=0.5):
    """Build a FleetResult for mocking run_sync."""
    return FleetResult(
        policy="test-policy",
        mode="check",
        duration=duration,
        hosts=hosts or [],
        total=compliant + drift + failed + fixed,
        compliant=compliant,
        drift=drift,
        fixed=fixed,
        failed=failed,
        skipped=0,
    )


# === _build_store Tests ===

class TestBuildStore(unittest.TestCase):
    """Test the _build_store helper."""

    def test_store_contains_all_policies(self):
        store = _build_store()
        policies = store.list()
        self.assertEqual(len(policies), 3)

    def test_store_can_get_each_policy(self):
        store = _build_store()
        for name in ("ntp-sync", "rpcbind-disable", "ssh-hardening"):
            p = store.get(name)
            self.assertIsNotNone(p, f"Policy {name} not found in store")
            self.assertEqual(p["name"], name)

    def test_store_get_nonexistent(self):
        store = _build_store()
        self.assertIsNone(store.get("does-not-exist"))


# === _resolve_hosts Tests ===

class TestResolveHosts(unittest.TestCase):
    """Test the _resolve_hosts helper."""

    def test_no_filter_returns_all(self):
        cfg = _cfg()
        args = _args()
        result = _resolve_hosts(cfg, args)
        self.assertEqual(len(result), 3)

    def test_filter_by_label(self):
        cfg = _cfg()
        args = _args(hosts="web01")
        result = _resolve_hosts(cfg, args)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].label, "web01")

    def test_filter_multiple_labels(self):
        cfg = _cfg()
        args = _args(hosts="web01,pve01")
        result = _resolve_hosts(cfg, args)
        self.assertEqual(len(result), 2)
        labels = {h.label for h in result}
        self.assertEqual(labels, {"web01", "pve01"})

    def test_filter_no_match_returns_empty(self):
        cfg = _cfg()
        args = _args(hosts="nonexistent")
        result = _resolve_hosts(cfg, args)
        self.assertEqual(len(result), 0)


# === cmd_policies Tests ===

class TestCmdPolicies(unittest.TestCase):
    """Test the cmd_policies command."""

    @patch("freq.modules.engine_cmds.fmt")
    def test_returns_zero(self, mock_fmt):
        cfg = _cfg()
        rc = cmd_policies(cfg, None, _args())
        self.assertEqual(rc, 0)

    @patch("freq.modules.engine_cmds.fmt")
    def test_calls_header_and_footer(self, mock_fmt):
        cfg = _cfg()
        cmd_policies(cfg, None, _args())
        mock_fmt.header.assert_called_once_with("Policies")
        mock_fmt.footer.assert_called_once()

    @patch("freq.modules.engine_cmds.fmt")
    def test_displays_table_rows(self, mock_fmt):
        cfg = _cfg()
        cmd_policies(cfg, None, _args())
        # Should call table_row for each of the 3 policies
        self.assertEqual(mock_fmt.table_row.call_count, 3)


# === cmd_check Tests ===

class TestCmdCheck(unittest.TestCase):
    """Test the cmd_check command."""

    @patch("freq.modules.engine_cmds.fmt")
    def test_no_policy_name_returns_1(self, mock_fmt):
        cfg = _cfg()
        rc = cmd_check(cfg, None, _args())
        self.assertEqual(rc, 1)
        mock_fmt.error.assert_called()

    @patch("freq.modules.engine_cmds.fmt")
    def test_unknown_policy_returns_1(self, mock_fmt):
        cfg = _cfg()
        rc = cmd_check(cfg, None, _args(policy="no-such-policy"))
        self.assertEqual(rc, 1)
        mock_fmt.error.assert_called()

    @patch("freq.modules.engine_cmds.fmt")
    def test_no_hosts_returns_1(self, mock_fmt):
        cfg = _cfg(hosts=[])
        rc = cmd_check(cfg, None, _args(policy="ntp-sync"))
        self.assertEqual(rc, 1)

    @patch("freq.modules.engine_cmds.run_sync")
    @patch("freq.modules.engine_cmds.fmt")
    def test_all_compliant_returns_0(self, mock_fmt, mock_run):
        h = Host(ip="10.0.0.1", label="web01", htype="linux")
        h.phase = Phase.COMPLIANT
        h.findings = []
        h.duration = 0.3
        mock_run.return_value = _fleet_result(hosts=[h], compliant=1)
        mock_fmt.badge = MagicMock(return_value="[compliant]")

        cfg = _cfg()
        rc = cmd_check(cfg, None, _args(policy="ntp-sync"))
        self.assertEqual(rc, 0)
        mock_run.assert_called_once()

    @patch("freq.modules.engine_cmds.run_sync")
    @patch("freq.modules.engine_cmds.fmt")
    def test_failures_returns_1(self, mock_fmt, mock_run):
        h = Host(ip="10.0.0.1", label="web01", htype="linux")
        h.phase = Phase.FAILED
        h.error = "unreachable"
        h.findings = []
        h.duration = 0.1
        mock_run.return_value = _fleet_result(hosts=[h], failed=1)
        mock_fmt.badge = MagicMock(return_value="[failed]")

        cfg = _cfg()
        rc = cmd_check(cfg, None, _args(policy="ntp-sync"))
        self.assertEqual(rc, 1)


# === cmd_fix Tests ===

class TestCmdFix(unittest.TestCase):
    """Test the cmd_fix command."""

    @patch("freq.modules.engine_cmds.fmt")
    def test_no_policy_returns_1(self, mock_fmt):
        cfg = _cfg()
        rc = cmd_fix(cfg, None, _args())
        self.assertEqual(rc, 1)

    @patch("freq.modules.engine_cmds.fmt")
    def test_unknown_policy_returns_1(self, mock_fmt):
        cfg = _cfg()
        rc = cmd_fix(cfg, None, _args(policy="bogus"))
        self.assertEqual(rc, 1)

    @patch("freq.modules.engine_cmds.fmt")
    def test_no_hosts_returns_1(self, mock_fmt):
        cfg = _cfg(hosts=[])
        rc = cmd_fix(cfg, None, _args(policy="ntp-sync"))
        self.assertEqual(rc, 1)

    @patch("freq.modules.engine_cmds.run_sync")
    @patch("freq.modules.engine_cmds.fmt")
    def test_fix_with_yes_flag_skips_confirm(self, mock_fmt, mock_run):
        h = Host(ip="10.0.0.1", label="web01", htype="linux")
        h.phase = Phase.DONE
        h.changes = ["NTP: pool.ntp.org -> 2.debian.pool.ntp.org"]
        h.duration = 0.5
        mock_run.return_value = _fleet_result(hosts=[h], fixed=1)

        cfg = _cfg()
        rc = cmd_fix(cfg, None, _args(policy="ntp-sync", yes=True))
        self.assertEqual(rc, 0)
        mock_run.assert_called_once()

    @patch("builtins.input", return_value="n")
    @patch("freq.modules.engine_cmds.fmt")
    def test_fix_declined_returns_0(self, mock_fmt, mock_input):
        cfg = _cfg()
        rc = cmd_fix(cfg, None, _args(policy="ntp-sync", yes=False))
        self.assertEqual(rc, 0)

    @patch("builtins.input", side_effect=EOFError)
    @patch("freq.modules.engine_cmds.fmt")
    def test_fix_eof_returns_1(self, mock_fmt, mock_input):
        cfg = _cfg()
        rc = cmd_fix(cfg, None, _args(policy="ntp-sync", yes=False))
        self.assertEqual(rc, 1)


# === cmd_diff Tests ===

class TestCmdDiff(unittest.TestCase):
    """Test the cmd_diff command."""

    @patch("freq.modules.engine_cmds.fmt")
    def test_no_policy_returns_1(self, mock_fmt):
        cfg = _cfg()
        rc = cmd_diff(cfg, None, _args())
        self.assertEqual(rc, 1)

    @patch("freq.modules.engine_cmds.fmt")
    def test_unknown_policy_returns_1(self, mock_fmt):
        cfg = _cfg()
        rc = cmd_diff(cfg, None, _args(policy="nope"))
        self.assertEqual(rc, 1)

    @patch("freq.modules.engine_cmds.run_sync")
    @patch("freq.modules.engine_cmds.fmt")
    def test_all_compliant_returns_0(self, mock_fmt, mock_run):
        h = Host(ip="10.0.0.1", label="web01", htype="linux")
        h.phase = Phase.COMPLIANT
        h.findings = []
        h.duration = 0.2
        h.current = {}
        h.desired = {}
        mock_run.return_value = _fleet_result(hosts=[h], compliant=1)

        cfg = _cfg()
        rc = cmd_diff(cfg, None, _args(policy="ntp-sync"))
        self.assertEqual(rc, 0)

    @patch("freq.modules.engine_cmds.run_sync")
    @patch("freq.modules.engine_cmds.fmt")
    def test_drift_prints_diff_returns_0(self, mock_fmt, mock_run):
        h = Host(ip="10.0.0.1", label="web01", htype="linux")
        h.phase = Phase.PLANNED
        h.findings = [Finding(
            resource_type="config", key="NTP",
            current="pool.ntp.org", desired="2.debian.pool.ntp.org",
        )]
        h.duration = 0.3
        h.current = {"NTP": "pool.ntp.org"}
        h.desired = {"NTP": "2.debian.pool.ntp.org"}
        mock_run.return_value = _fleet_result(hosts=[h], drift=1)

        cfg = _cfg()
        rc = cmd_diff(cfg, None, _args(policy="ntp-sync"))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
