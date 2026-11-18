"""Tests for freq.jarvis.rules — alert rules engine."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix

from freq.jarvis.rules import (
    Rule, Alert, load_rules, save_rules, _default_rules,
    load_rule_state, save_rule_state,
    load_alert_history, save_alert_history, MAX_HISTORY,
    _matches_target, _parse_ram_percent, _parse_disk_percent,
    evaluate_rules, _check_condition,
)


class TestRuleDataTypes(unittest.TestCase):
    def _case_rule_defaults(self):
        r = Rule(name="test", condition="cpu_above")
        self.assertEqual(r.target, "*")
        self.assertEqual(r.threshold, 0.0)
        self.assertEqual(r.duration, 0)
        self.assertEqual(r.severity, "warning")
        self.assertEqual(r.cooldown, 300)
        self.assertTrue(r.enabled)
        self.assertEqual(r.exclude_types, ())
        self.assertEqual(r.exclude_groups, ())
        self.assertEqual(r.exclude_categories, ())

    def _case_alert_defaults(self):
        a = Alert(rule_name="r1", host="h1", message="msg", severity="critical")
        self.assertEqual(a.fired_at, 0.0)

    def _case_default_rules_returns_three(self):
        rules = _default_rules()
        self.assertEqual(len(rules), 3)
        names = [r.name for r in rules]
        self.assertIn("host-unreachable", names)
        self.assertIn("disk-critical", names)
        self.assertIn("ram-pressure", names)
        ram_rule = next(r for r in rules if r.name == "ram-pressure")
        self.assertIn("truenas", ram_rule.exclude_types)
        self.assertIn("lab", ram_rule.exclude_groups)
        self.assertIn("lab", ram_rule.exclude_categories)


class TestRuleLoading(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_rules_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_load_missing_file_returns_defaults(self):
        rules = load_rules(self.tmpdir)
        self.assertEqual(len(rules), 3)

    def _case_load_valid_toml(self):
        toml_content = b"""
[rule.test-rule]
condition = "cpu_above"
target = "web*"
threshold = 80
duration = 60
severity = "critical"
cooldown = 600
enabled = true
"""
        with open(os.path.join(self.tmpdir, "rules.toml"), "wb") as f:
            f.write(toml_content)
        rules = load_rules(self.tmpdir)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, "test-rule")
        self.assertEqual(rules[0].condition, "cpu_above")
        self.assertEqual(rules[0].threshold, 80.0)

    def _case_load_empty_rules_returns_defaults(self):
        with open(os.path.join(self.tmpdir, "rules.toml"), "wb") as f:
            f.write(b"# empty\n")
        rules = load_rules(self.tmpdir)
        self.assertEqual(len(rules), 3)  # defaults

    def _case_load_malformed_toml_returns_defaults(self):
        with open(os.path.join(self.tmpdir, "rules.toml"), "wb") as f:
            f.write(b"{{{{invalid toml!!")
        rules = load_rules(self.tmpdir)
        self.assertEqual(len(rules), 3)  # defaults

    def _case_save_and_reload_roundtrip(self):
        rules = [Rule(name="test", condition="disk_above", threshold=90)]
        save_rules(self.tmpdir, rules)
        reloaded = load_rules(self.tmpdir)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].name, "test")
        self.assertEqual(reloaded[0].condition, "disk_above")

    def _case_save_and_reload_exclusions(self):
        rules = [
            Rule(
                name="safe-ram",
                condition="ram_above",
                threshold=95,
                exclude_types=("truenas",),
                exclude_groups=("lab",),
                exclude_categories=("lab",),
            )
        ]
        save_rules(self.tmpdir, rules)
        reloaded = load_rules(self.tmpdir)
        self.assertEqual(reloaded[0].exclude_types, ("truenas",))
        self.assertEqual(reloaded[0].exclude_groups, ("lab",))
        self.assertEqual(reloaded[0].exclude_categories, ("lab",))


class TestRuleState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_rstate_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_load_missing_returns_empty(self):
        self.assertEqual(load_rule_state(self.tmpdir), {})

    def _case_save_and_load_roundtrip(self):
        state = {"rule1:host1": {"first_seen": 1000, "last_alerted": 1100}}
        save_rule_state(self.tmpdir, state)
        loaded = load_rule_state(self.tmpdir)
        self.assertEqual(loaded["rule1:host1"]["first_seen"], 1000)

    def _case_load_corrupt_json_returns_empty(self):
        path = os.path.join(self.tmpdir, "rule_state.json")
        os.makedirs(self.tmpdir, exist_ok=True)
        with open(path, "w") as f:
            f.write("{{{invalid")
        self.assertEqual(load_rule_state(self.tmpdir), {})


class TestAlertHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_ahist_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_load_missing_returns_empty(self):
        self.assertEqual(load_alert_history(self.tmpdir), [])

    def _case_save_and_load_roundtrip(self):
        history = [{"rule": "r1", "host": "h1", "ts": 1000}]
        save_alert_history(self.tmpdir, history)
        loaded = load_alert_history(self.tmpdir)
        self.assertEqual(len(loaded), 1)

    def _case_save_caps_at_max_history(self):
        history = [{"i": i} for i in range(150)]
        save_alert_history(self.tmpdir, history)
        loaded = load_alert_history(self.tmpdir)
        self.assertEqual(len(loaded), MAX_HISTORY)
        self.assertEqual(loaded[0]["i"], 50)  # kept last 100


class TestTargetMatching(unittest.TestCase):
    def _case_wildcard_matches_all(self):
        self.assertTrue(_matches_target("anything", "*"))

    def _case_prefix_glob_matches(self):
        self.assertTrue(_matches_target("web-01", "web*"))
        self.assertTrue(_matches_target("web", "web*"))

    def _case_prefix_glob_no_match(self):
        self.assertFalse(_matches_target("db-01", "web*"))

    def _case_exact_match(self):
        self.assertTrue(_matches_target("host1", "host1"))
        self.assertFalse(_matches_target("host1", "host2"))


class TestParsing(unittest.TestCase):
    def _case_parse_ram_percent_valid(self):
        self.assertAlmostEqual(_parse_ram_percent("4096/8192MB"), 50.0, places=1)

    def _case_parse_ram_percent_invalid(self):
        self.assertIsNone(_parse_ram_percent("invalid"))
        self.assertIsNone(_parse_ram_percent(""))

    def _case_parse_ram_percent_zero_total(self):
        self.assertIsNone(_parse_ram_percent("0/0MB"))

    def _case_parse_disk_percent_valid(self):
        self.assertEqual(_parse_disk_percent("45%"), 45.0)

    def _case_parse_disk_percent_invalid(self):
        self.assertIsNone(_parse_disk_percent("unknown"))
        self.assertIsNone(_parse_disk_percent(""))


class TestEvaluation(unittest.TestCase):
    def _case_host_unreachable_fires(self):
        rules = [Rule(name="down", condition="host_unreachable", duration=0)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        state = {}
        alerts = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].host, "h1")

    def _case_host_reachable_no_alert(self):
        rules = [Rule(name="down", condition="host_unreachable")]
        health = {"hosts": [{"label": "h1", "status": "ok"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 0)

    def _case_cpu_above_fires(self):
        rules = [Rule(name="cpu", condition="cpu_above", threshold=5.0, duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "load": "8.5"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def _case_ram_above_fires(self):
        rules = [Rule(name="ram", condition="ram_above", threshold=90, duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "7500/8192MB"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def _case_custom_ram_rule_can_target_truenas(self):
        rules = [Rule(name="ram", condition="ram_above", threshold=95, duration=0)]
        health = {"hosts": [{"label": "truenas", "type": "truenas", "status": "ok", "ram": "1879/1974MB"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def _case_default_ram_pressure_excludes_truenas_and_lab(self):
        rules = _default_rules()
        health = {
            "hosts": [
                {"label": "truenas", "type": "truenas", "status": "ok", "ram": "1879/1974MB"},
                {"label": "truenas-lab", "type": "truenas", "groups": "lab", "status": "ok", "ram": "1879/1974MB"},
                {"label": "lab-vm", "type": "linux", "groups": ["lab"], "status": "ok", "ram": "1879/1974MB"},
            ]
        }
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual([a.rule_name for a in alerts if a.rule_name == "ram-pressure"], [])

    def _case_null_resource_metrics_do_not_crash_rule_evaluation(self):
        rules = _default_rules()
        health = {
            "hosts": [
                {
                    "label": "bmc-10",
                    "type": "idrac",
                    "status": "healthy",
                    "state": "live",
                    "ram": None,
                    "disk": None,
                    "load": "-",
                }
            ]
        }
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(alerts, [])

    def _case_disk_above_fires(self):
        rules = [Rule(name="disk", condition="disk_above", threshold=80, duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "disk": "95%"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def _case_docker_down_fires(self):
        rules = [Rule(name="docker", condition="docker_down", duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "type": "docker", "docker": "0"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def _case_disabled_rule_skipped(self):
        rules = [Rule(name="off", condition="host_unreachable", enabled=False)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 0)

    def _case_duration_gate_blocks(self):
        rules = [Rule(name="slow", condition="host_unreachable", duration=600)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        state = {}
        alerts = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts), 0)  # not enough time elapsed

    def _case_cooldown_gate_blocks(self):
        rules = [Rule(name="cool", condition="host_unreachable", duration=0, cooldown=600)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        state = {}
        # First evaluation fires
        alerts1 = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts1), 1)
        # Second evaluation blocked by cooldown
        alerts2 = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts2), 0)

    def _case_condition_cleared_resets_state(self):
        rules = [Rule(name="r1", condition="host_unreachable", duration=0)]
        state = {"r1:h1": {"first_seen": 1000, "last_alerted": 1100}}
        health = {"hosts": [{"label": "h1", "status": "ok"}]}
        evaluate_rules(health, rules, state)
        self.assertNotIn("r1:h1", state)


RULE_EVALUATION_CASES = (
    "_case_host_unreachable_fires",
    "_case_host_reachable_no_alert",
    "_case_cpu_above_fires",
    "_case_ram_above_fires",
    "_case_custom_ram_rule_can_target_truenas",
    "_case_default_ram_pressure_excludes_truenas_and_lab",
    "_case_null_resource_metrics_do_not_crash_rule_evaluation",
    "_case_disk_above_fires",
    "_case_docker_down_fires",
    "_case_disabled_rule_skipped",
    "_case_duration_gate_blocks",
    "_case_cooldown_gate_blocks",
    "_case_condition_cleared_resets_state",
)


class TestEvaluationMatrix(unittest.TestCase):
    def test_rule_evaluation_matrix(self):
        run_case_matrix(self, TestEvaluation, RULE_EVALUATION_CASES)


RULE_DATA_TYPE_CASES = (
    "_case_rule_defaults", "_case_alert_defaults", "_case_default_rules_returns_three",
)
RULE_LOADING_CASES = (
    "_case_load_missing_file_returns_defaults", "_case_load_valid_toml",
    "_case_load_empty_rules_returns_defaults",
    "_case_load_malformed_toml_returns_defaults", "_case_save_and_reload_roundtrip",
    "_case_save_and_reload_exclusions",
)
RULE_STATE_CASES = (
    "_case_load_missing_returns_empty", "_case_save_and_load_roundtrip",
    "_case_load_corrupt_json_returns_empty",
)
ALERT_HISTORY_CASES = (
    "_case_load_missing_returns_empty", "_case_save_and_load_roundtrip",
    "_case_save_caps_at_max_history",
)
TARGET_MATCHING_CASES = (
    "_case_wildcard_matches_all", "_case_prefix_glob_matches",
    "_case_prefix_glob_no_match", "_case_exact_match",
)
RULE_PARSING_CASES = (
    "_case_parse_ram_percent_valid", "_case_parse_ram_percent_invalid",
    "_case_parse_ram_percent_zero_total", "_case_parse_disk_percent_valid",
    "_case_parse_disk_percent_invalid",
)


class TestRuleDataTypesMatrix(unittest.TestCase):
    def test_rule_data_types_matrix(self):
        run_case_matrix(self, TestRuleDataTypes, RULE_DATA_TYPE_CASES)


class TestRuleLoadingMatrix(unittest.TestCase):
    def test_rule_loading_matrix(self):
        run_case_matrix(self, TestRuleLoading, RULE_LOADING_CASES)


class TestRuleStateMatrix(unittest.TestCase):
    def test_rule_state_matrix(self):
        run_case_matrix(self, TestRuleState, RULE_STATE_CASES)


class TestAlertHistoryMatrix(unittest.TestCase):
    def test_alert_history_matrix(self):
        run_case_matrix(self, TestAlertHistory, ALERT_HISTORY_CASES)


class TestTargetMatchingMatrix(unittest.TestCase):
    def test_target_matching_matrix(self):
        run_case_matrix(self, TestTargetMatching, TARGET_MATCHING_CASES)


class TestRuleParsingMatrix(unittest.TestCase):
    def test_rule_parsing_matrix(self):
        run_case_matrix(self, TestParsing, RULE_PARSING_CASES)


if __name__ == "__main__":
    unittest.main()
