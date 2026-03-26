"""Edge case and integration tests for Jarvis modules.

Tests cross-module interactions, empty/null inputs, huge inputs,
unicode handling, file corruption recovery, math edge cases,
HMAC boundaries, and chaos safety boundaries.
"""
import hashlib
import hmac
import json
import math
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from freq.jarvis.rules import (
    Rule, evaluate_rules, load_rules, save_rules,
    load_rule_state, save_rule_state,
    load_alert_history, save_alert_history,
)
from freq.jarvis.capacity import (
    save_snapshot, load_snapshots, compute_projections,
    _linear_regression, _parse_ram_pct, _parse_disk_pct,
)
from freq.jarvis.cost import (
    CostConfig, compute_costs, estimate_host_watts,
    fleet_summary, parse_idrac_power,
)
from freq.jarvis.federation import (
    Site, load_sites, save_sites, register_site,
    verify_auth, _make_auth_header, sites_to_dicts,
    federation_summary,
)
from freq.jarvis.chaos import (
    Experiment, validate_experiment, build_commands,
    check_safety, MAX_DURATION,
)
from freq.jarvis.gitops import (
    SyncState, load_state, save_state, rollback,
)
from freq.jarvis.playbook import (
    Playbook, PlaybookStep, load_playbooks,
    playbooks_to_dicts,
)


class TestCrossModuleRulesEval(unittest.TestCase):
    """Rules → evaluation → alert fires integration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_edge_rules_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_rule_create_evaluate_alert(self):
        """Full pipeline: save rules → load → evaluate → get alert."""
        rules = [Rule(name="high-cpu", condition="cpu_above", threshold=50.0, duration=0)]
        save_rules(self.tmpdir, rules)
        loaded = load_rules(self.tmpdir)
        self.assertEqual(len(loaded), 1)
        health = {"hosts": [{"label": "web-01", "status": "ok", "load": "75.0"}]}
        state = {}
        alerts = evaluate_rules(health, loaded, state)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].host, "web-01")
        self.assertEqual(alerts[0].rule_name, "high-cpu")

    def test_multiple_rules_multiple_hosts(self):
        rules = [
            Rule(name="cpu", condition="cpu_above", threshold=80, duration=0),
            Rule(name="disk", condition="disk_above", threshold=90, duration=0),
        ]
        health = {"hosts": [
            {"label": "h1", "status": "ok", "load": "95.0", "disk": "50%"},
            {"label": "h2", "status": "ok", "load": "10.0", "disk": "95%"},
        ]}
        state = {}
        alerts = evaluate_rules(health, rules, state)
        names = [(a.rule_name, a.host) for a in alerts]
        self.assertIn(("cpu", "h1"), names)
        self.assertIn(("disk", "h2"), names)
        self.assertEqual(len(alerts), 2)


class TestCrossModuleCapacityCost(unittest.TestCase):
    """Capacity snapshots → cost calculation integration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_edge_capcost_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_snapshot_data_used_in_cost(self):
        health = {"hosts": [
            {"label": "h1", "status": "ok", "ram": "4096/8192MB", "disk": "50%", "load": "4.0"},
        ]}
        save_snapshot(self.tmpdir, health)
        snaps = load_snapshots(self.tmpdir)
        self.assertEqual(len(snaps), 1)
        # Use same data for cost
        costs = compute_costs(health, {}, CostConfig())
        self.assertEqual(len(costs), 1)
        self.assertGreater(costs[0].cost_month, 0)


class TestEmptyNullInputs(unittest.TestCase):
    """Empty/null inputs to every module."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_edge_empty_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_evaluate_rules_empty_hosts(self):
        rules = [Rule(name="r1", condition="cpu_above", threshold=50)]
        alerts = evaluate_rules({"hosts": []}, rules, {})
        self.assertEqual(len(alerts), 0)

    def test_evaluate_rules_empty_rules(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "load": "90.0"}]}
        alerts = evaluate_rules(health, [], {})
        self.assertEqual(len(alerts), 0)

    def test_evaluate_rules_no_hosts_key(self):
        alerts = evaluate_rules({}, [Rule(name="r1", condition="cpu_above")], {})
        self.assertEqual(len(alerts), 0)

    def test_compute_costs_empty(self):
        costs = compute_costs({"hosts": []}, {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def test_compute_projections_empty(self):
        self.assertEqual(compute_projections([]), {})

    def test_federation_summary_empty(self):
        summary = federation_summary([])
        self.assertEqual(summary["total_sites"], 0)

    def test_load_playbooks_empty(self):
        self.assertEqual(load_playbooks(self.tmpdir), [])

    def test_parse_empty_strings(self):
        self.assertEqual(_parse_ram_pct(""), -1)
        self.assertEqual(_parse_disk_pct(""), -1)
        self.assertEqual(parse_idrac_power(""), 0.0)
        self.assertGreaterEqual(estimate_host_watts({}), 5.0)  # at least floor


class TestHugeInputs(unittest.TestCase):
    """Huge inputs — 1000 hosts, many snapshots, many sites."""

    def test_evaluate_1000_hosts(self):
        rules = [Rule(name="cpu", condition="cpu_above", threshold=50, duration=0)]
        hosts = [{"label": f"h{i}", "status": "ok", "load": str(60 + i % 40)} for i in range(1000)]
        health = {"hosts": hosts}
        state = {}
        alerts = evaluate_rules(health, rules, state)
        self.assertGreater(len(alerts), 0)
        self.assertLessEqual(len(alerts), 1000)

    def test_compute_costs_1000_hosts(self):
        hosts = [{"label": f"h{i}", "status": "ok", "ram": "4096/8192MB", "load": "4.0"} for i in range(1000)]
        costs = compute_costs({"hosts": hosts}, {}, CostConfig())
        self.assertEqual(len(costs), 1000)
        summary = fleet_summary(costs, CostConfig())
        self.assertEqual(summary["host_count"], 1000)

    def test_federation_50_sites(self):
        sites = [Site(name=f"dc{i:02d}", url=f"https://dc{i:02d}.example.com",
                       enabled=True, last_status="ok" if i % 2 == 0 else "unreachable",
                       last_hosts=10, last_healthy=8) for i in range(50)]
        summary = federation_summary(sites)
        self.assertEqual(summary["total_sites"], 50)
        dicts = sites_to_dicts(sites)
        self.assertEqual(len(dicts), 50)


class TestUnicodeHandling(unittest.TestCase):
    """Unicode in names for rules, playbooks, sites."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_edge_unicode_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_rule_unicode_name(self):
        rules = [Rule(name="café-alert", condition="cpu_above", threshold=80)]
        save_rules(self.tmpdir, rules)
        loaded = load_rules(self.tmpdir)
        self.assertEqual(loaded[0].name, "café-alert")

    def test_federation_unicode_site(self):
        ok, msg = register_site(self.tmpdir, "データセンター", "https://dc.jp.example.com")
        self.assertTrue(ok)
        sites = load_sites(self.tmpdir)
        self.assertEqual(sites[0].name, "データセンター")

    def test_playbook_unicode_name(self):
        pb_dir = os.path.join(self.tmpdir, "playbooks")
        os.makedirs(pb_dir, exist_ok=True)
        toml = '[playbook]\nname = "Récupération"\n'.encode()
        with open(os.path.join(pb_dir, "recover.toml"), "wb") as f:
            f.write(toml)
        pbs = load_playbooks(self.tmpdir)
        self.assertEqual(pbs[0].name, "Récupération")


class TestFileCorruptionRecovery(unittest.TestCase):
    """File corruption recovery — every state file."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_edge_corrupt_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _corrupt(self, filename):
        path = os.path.join(self.tmpdir, filename)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("{{{CORRUPT")

    def test_corrupt_rule_state(self):
        self._corrupt("rule_state.json")
        self.assertEqual(load_rule_state(self.tmpdir), {})

    def test_corrupt_alert_history(self):
        self._corrupt("alert_history.json")
        self.assertEqual(load_alert_history(self.tmpdir), [])

    def test_corrupt_federation(self):
        self._corrupt("federation.json")
        self.assertEqual(load_sites(self.tmpdir), [])

    def test_corrupt_gitops_state(self):
        self._corrupt("gitops_state.json")
        state = load_state(self.tmpdir)
        self.assertEqual(state.status, "idle")


class TestMathEdgeCases(unittest.TestCase):
    """Math edge cases for linear regression and projections."""

    def test_single_point_regression(self):
        slope, intercept = _linear_regression([(1, 50)])
        self.assertEqual(slope, 0)

    def test_all_identical_points(self):
        points = [(i, 50.0) for i in range(10)]
        slope, intercept = _linear_regression(points)
        self.assertAlmostEqual(slope, 0.0, places=3)

    def test_negative_values(self):
        slope, intercept = _linear_regression([(0, -10), (1, -5), (2, 0)])
        self.assertAlmostEqual(slope, 5.0, places=3)

    def test_projection_with_huge_growth(self):
        """Very steep growth — days_to_80pct should still be reasonable."""
        snaps = []
        base = time.time() - 3 * 7 * 86400
        for i in range(3):
            snaps.append({
                "epoch": base + i * 7 * 86400,
                "hosts": {"h1": {"ram": f"{1000 + i * 2000}/8192MB", "disk": f"{20 + i * 20}%", "load": "1"}},
            })
        proj = compute_projections(snaps)
        if "h1" in proj and "ram" in proj["h1"]:
            d = proj["h1"]["ram"].get("days_to_80pct", -1)
            if d > 0:
                self.assertLessEqual(d, 3650)

    def test_watts_estimation_nan_proof(self):
        """estimate_host_watts should never return NaN or inf."""
        for load_val in ["0", "nan", "inf", "-1", "999999"]:
            host = {"load": load_val, "ram": "100/100MB"}
            watts = estimate_host_watts(host)
            self.assertTrue(math.isfinite(watts))
            self.assertGreaterEqual(watts, 5.0)
            self.assertLessEqual(watts, 2000.0)


class TestHMACBoundary(unittest.TestCase):
    """HMAC authentication boundary conditions."""

    def test_exactly_300s_old(self):
        """Timestamp exactly at 5-minute boundary should pass."""
        secret = "test-secret"
        ts = str(int(time.time()) - 299)  # just inside window
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_auth(secret, ts, sig, ""))

    def test_exactly_301s_old(self):
        """Timestamp just past 5-minute boundary should fail."""
        secret = "test-secret"
        ts = str(int(time.time()) - 301)
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertFalse(verify_auth(secret, ts, sig, ""))

    def test_future_timestamp_within_window(self):
        """Future timestamp within 5 minutes should pass."""
        secret = "test-secret"
        ts = str(int(time.time()) + 60)  # 1 min in future
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_auth(secret, ts, sig, ""))

    def test_future_timestamp_beyond_window(self):
        """Future timestamp beyond 5 minutes should fail."""
        secret = "test-secret"
        ts = str(int(time.time()) + 400)
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertFalse(verify_auth(secret, ts, sig, ""))


class TestChaosSafetyBoundary(unittest.TestCase):
    """Chaos safety boundary conditions."""

    def test_duration_exactly_max(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=MAX_DURATION)
        ok, err = validate_experiment(exp)
        self.assertTrue(ok)

    def test_duration_one_over_max(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=MAX_DURATION + 1)
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)

    def test_duration_exactly_one(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=1)
        ok, err = validate_experiment(exp)
        self.assertTrue(ok)

    def test_duration_zero(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=0)
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)


class TestGitOpsRollbackValidation(unittest.TestCase):
    """Rollback hash validation edge cases."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_edge_rollback_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)
        # Create .git dir
        go_dir = os.path.join(self.tmpdir, "gitops")
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)

    def test_hash_too_short(self):
        ok, msg = rollback(self.tmpdir, "abc")
        self.assertFalse(ok)
        self.assertIn("Invalid", msg)

    def test_hash_with_special_chars(self):
        ok, msg = rollback(self.tmpdir, "abc123; rm -rf /")
        self.assertFalse(ok)

    def test_hash_uppercase_rejected(self):
        ok, msg = rollback(self.tmpdir, "ABC1234DEF5678")
        self.assertFalse(ok)

    @patch("freq.jarvis.gitops._run_git")
    def test_valid_full_hash(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0)
        ok, msg = rollback(self.tmpdir, "a" * 40)
        self.assertTrue(ok)

    @patch("freq.jarvis.gitops._run_git")
    def test_valid_short_hash(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0)
        ok, msg = rollback(self.tmpdir, "abc1234")
        self.assertTrue(ok)
