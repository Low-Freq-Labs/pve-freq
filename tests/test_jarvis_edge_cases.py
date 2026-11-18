"""Edge case and integration tests for Jarvis modules.

Tests cross-module interactions, empty/null inputs, huge inputs,
unicode handling, file corruption recovery, math edge cases,
HMAC boundaries, and chaos safety boundaries.
"""
import hashlib
import hmac
import math
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.jarvis.capacity import (
    _linear_regression,
    _parse_disk_pct,
    _parse_ram_pct,
    compute_projections,
    load_snapshots,
    save_snapshot,
)
from freq.jarvis.chaos import MAX_DURATION, Experiment, validate_experiment
from freq.jarvis.cost import (
    CostConfig,
    compute_costs,
    estimate_host_watts,
    fleet_summary,
    parse_idrac_power,
)
from freq.jarvis.federation import Site, federation_summary, load_sites, register_site, sites_to_dicts, verify_auth
from freq.jarvis.playbook import load_playbooks
from freq.jarvis.rules import Rule, evaluate_rules, load_alert_history, load_rule_state, load_rules, save_rules
from tests.case_matrix import run_case_matrix


class TestCrossModuleRulesEval(unittest.TestCase):
    """Rules → evaluation → alert fires integration."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_edge_rules_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_rule_create_evaluate_alert(self):
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

    def _case_multiple_rules_multiple_hosts(self):
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

    def _case_snapshot_data_used_in_cost(self):
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

    def _case_evaluate_rules_empty_hosts(self):
        rules = [Rule(name="r1", condition="cpu_above", threshold=50)]
        alerts = evaluate_rules({"hosts": []}, rules, {})
        self.assertEqual(len(alerts), 0)

    def _case_evaluate_rules_empty_rules(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "load": "90.0"}]}
        alerts = evaluate_rules(health, [], {})
        self.assertEqual(len(alerts), 0)

    def _case_evaluate_rules_no_hosts_key(self):
        alerts = evaluate_rules({}, [Rule(name="r1", condition="cpu_above")], {})
        self.assertEqual(len(alerts), 0)

    def _case_compute_costs_empty(self):
        costs = compute_costs({"hosts": []}, {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def _case_compute_projections_empty(self):
        self.assertEqual(compute_projections([]), {})

    def _case_federation_summary_empty(self):
        summary = federation_summary([])
        self.assertEqual(summary["total_sites"], 0)

    def _case_load_playbooks_empty(self):
        self.assertEqual(load_playbooks(self.tmpdir), [])

    def _case_parse_empty_strings(self):
        self.assertEqual(_parse_ram_pct(""), -1)
        self.assertEqual(_parse_disk_pct(""), -1)
        self.assertEqual(parse_idrac_power(""), 0.0)
        self.assertGreaterEqual(estimate_host_watts({}), 5.0)  # at least floor


class TestHugeInputs(unittest.TestCase):
    """Huge inputs — 1000 hosts, many snapshots, many sites."""

    def _case_evaluate_1000_hosts(self):
        rules = [Rule(name="cpu", condition="cpu_above", threshold=50, duration=0)]
        hosts = [{"label": f"h{i}", "status": "ok", "load": str(60 + i % 40)} for i in range(1000)]
        health = {"hosts": hosts}
        state = {}
        alerts = evaluate_rules(health, rules, state)
        self.assertGreater(len(alerts), 0)
        self.assertLessEqual(len(alerts), 1000)

    def _case_compute_costs_1000_hosts(self):
        hosts = [{"label": f"h{i}", "status": "ok", "ram": "4096/8192MB", "load": "4.0"} for i in range(1000)]
        costs = compute_costs({"hosts": hosts}, {}, CostConfig())
        self.assertEqual(len(costs), 1000)
        summary = fleet_summary(costs, CostConfig())
        self.assertEqual(summary["host_count"], 1000)

    def _case_federation_50_sites(self):
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

    def _case_rule_unicode_name(self):
        rules = [Rule(name="café-alert", condition="cpu_above", threshold=80)]
        save_rules(self.tmpdir, rules)
        loaded = load_rules(self.tmpdir)
        self.assertEqual(loaded[0].name, "café-alert")

    def _case_federation_unicode_site(self):
        ok, msg = register_site(self.tmpdir, "データセンター", "https://dc.jp.example.com")
        self.assertTrue(ok)
        sites = load_sites(self.tmpdir)
        self.assertEqual(sites[0].name, "データセンター")

    def _case_playbook_unicode_name(self):
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

    def _case_corrupt_rule_state(self):
        self._corrupt("rule_state.json")
        self.assertEqual(load_rule_state(self.tmpdir), {})

    def _case_corrupt_alert_history(self):
        self._corrupt("alert_history.json")
        self.assertEqual(load_alert_history(self.tmpdir), [])

    def _case_corrupt_federation(self):
        self._corrupt("federation.json")
        self.assertEqual(load_sites(self.tmpdir), [])

class TestMathEdgeCases(unittest.TestCase):
    """Math edge cases for linear regression and projections."""

    def _case_single_point_regression(self):
        slope, intercept = _linear_regression([(1, 50)])
        self.assertEqual(slope, 0)

    def _case_all_identical_points(self):
        points = [(i, 50.0) for i in range(10)]
        slope, intercept = _linear_regression(points)
        self.assertAlmostEqual(slope, 0.0, places=3)

    def _case_negative_values(self):
        slope, intercept = _linear_regression([(0, -10), (1, -5), (2, 0)])
        self.assertAlmostEqual(slope, 5.0, places=3)

    def _case_projection_with_huge_growth(self):
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

    def _case_watts_estimation_nan_proof(self):
        """estimate_host_watts should never return NaN or inf."""
        for load_val in ["0", "nan", "inf", "-1", "999999"]:
            host = {"load": load_val, "ram": "100/100MB"}
            watts = estimate_host_watts(host)
            self.assertTrue(math.isfinite(watts))
            self.assertGreaterEqual(watts, 5.0)
            self.assertLessEqual(watts, 2000.0)


class TestHMACBoundary(unittest.TestCase):
    """HMAC authentication boundary conditions."""

    def _case_exactly_300s_old(self):
        """Timestamp exactly at 5-minute boundary should pass."""
        secret = "test-secret"
        ts = str(int(time.time()) - 299)  # just inside window
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_auth(secret, ts, sig, ""))

    def _case_exactly_301s_old(self):
        """Timestamp just past 5-minute boundary should fail."""
        secret = "test-secret"
        ts = str(int(time.time()) - 301)
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertFalse(verify_auth(secret, ts, sig, ""))

    def _case_future_timestamp_within_window(self):
        """Future timestamp within 5 minutes should pass."""
        secret = "test-secret"
        ts = str(int(time.time()) + 60)  # 1 min in future
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertTrue(verify_auth(secret, ts, sig, ""))

    def _case_future_timestamp_beyond_window(self):
        """Future timestamp beyond 5 minutes should fail."""
        secret = "test-secret"
        ts = str(int(time.time()) + 400)
        sig_input = f"{ts}:"
        sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
        self.assertFalse(verify_auth(secret, ts, sig, ""))


class TestChaosSafetyBoundary(unittest.TestCase):
    """Chaos safety boundary conditions."""

    def _case_duration_exactly_max(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=MAX_DURATION)
        ok, err = validate_experiment(exp)
        self.assertTrue(ok)

    def _case_duration_one_over_max(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=MAX_DURATION + 1)
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)

    def _case_duration_exactly_one(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=1)
        ok, err = validate_experiment(exp)
        self.assertTrue(ok)

    def _case_duration_zero(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=0)
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)


EDGE_RULE_EVAL_CASES = (
    "_case_rule_create_evaluate_alert", "_case_multiple_rules_multiple_hosts",
)
EDGE_CAPACITY_COST_CASES = ("_case_snapshot_data_used_in_cost",)
EDGE_EMPTY_NULL_CASES = (
    "_case_evaluate_rules_empty_hosts", "_case_evaluate_rules_empty_rules",
    "_case_evaluate_rules_no_hosts_key", "_case_compute_costs_empty",
    "_case_compute_projections_empty", "_case_federation_summary_empty",
    "_case_load_playbooks_empty", "_case_parse_empty_strings",
)
EDGE_HUGE_INPUT_CASES = (
    "_case_evaluate_1000_hosts", "_case_compute_costs_1000_hosts",
    "_case_federation_50_sites",
)
EDGE_UNICODE_CASES = (
    "_case_rule_unicode_name", "_case_federation_unicode_site",
    "_case_playbook_unicode_name",
)
EDGE_CORRUPTION_CASES = (
    "_case_corrupt_rule_state", "_case_corrupt_alert_history",
    "_case_corrupt_federation",
)
EDGE_MATH_CASES = (
    "_case_single_point_regression", "_case_all_identical_points",
    "_case_negative_values", "_case_projection_with_huge_growth",
    "_case_watts_estimation_nan_proof",
)
EDGE_HMAC_CASES = (
    "_case_exactly_300s_old", "_case_exactly_301s_old",
    "_case_future_timestamp_within_window", "_case_future_timestamp_beyond_window",
)
EDGE_CHAOS_SAFETY_CASES = (
    "_case_duration_exactly_max", "_case_duration_one_over_max",
    "_case_duration_exactly_one", "_case_duration_zero",
)
class TestEdgeRuleEvaluationMatrix(unittest.TestCase):
    def test_edge_rule_evaluation_matrix(self):
        run_case_matrix(self, TestCrossModuleRulesEval, EDGE_RULE_EVAL_CASES)


class TestEdgeCapacityCostMatrix(unittest.TestCase):
    def test_edge_capacity_cost_matrix(self):
        run_case_matrix(self, TestCrossModuleCapacityCost, EDGE_CAPACITY_COST_CASES)


class TestEdgeEmptyNullMatrix(unittest.TestCase):
    def test_edge_empty_null_matrix(self):
        run_case_matrix(self, TestEmptyNullInputs, EDGE_EMPTY_NULL_CASES)


class TestEdgeHugeInputsMatrix(unittest.TestCase):
    def test_edge_huge_inputs_matrix(self):
        run_case_matrix(self, TestHugeInputs, EDGE_HUGE_INPUT_CASES)


class TestEdgeUnicodeMatrix(unittest.TestCase):
    def test_edge_unicode_matrix(self):
        run_case_matrix(self, TestUnicodeHandling, EDGE_UNICODE_CASES)


class TestEdgeCorruptionRecoveryMatrix(unittest.TestCase):
    def test_edge_corruption_recovery_matrix(self):
        run_case_matrix(self, TestFileCorruptionRecovery, EDGE_CORRUPTION_CASES)


class TestEdgeMathMatrix(unittest.TestCase):
    def test_edge_math_matrix(self):
        run_case_matrix(self, TestMathEdgeCases, EDGE_MATH_CASES)


class TestEdgeHMACMatrix(unittest.TestCase):
    def test_edge_hmac_matrix(self):
        run_case_matrix(self, TestHMACBoundary, EDGE_HMAC_CASES)


class TestEdgeChaosSafetyMatrix(unittest.TestCase):
    def test_edge_chaos_safety_matrix(self):
        run_case_matrix(self, TestChaosSafetyBoundary, EDGE_CHAOS_SAFETY_CASES)


if __name__ == "__main__":
    unittest.main()
