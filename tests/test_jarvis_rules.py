"""Tests for freq.jarvis.rules — alert rules engine."""
import json
import os
import shutil
import tempfile
import time
import unittest

from freq.jarvis.rules import (
    Rule, Alert, load_rules, save_rules, _default_rules,
    load_rule_state, save_rule_state,
    load_alert_history, save_alert_history, MAX_HISTORY,
    _matches_target, _parse_ram_percent, _parse_disk_percent,
    evaluate_rules, _check_condition,
)


class TestRuleDataTypes(unittest.TestCase):
    def test_rule_defaults(self):
        r = Rule(name="test", condition="cpu_above")
        self.assertEqual(r.target, "*")
        self.assertEqual(r.threshold, 0.0)
        self.assertEqual(r.duration, 0)
        self.assertEqual(r.severity, "warning")
        self.assertEqual(r.cooldown, 300)
        self.assertTrue(r.enabled)

    def test_alert_defaults(self):
        a = Alert(rule_name="r1", host="h1", message="msg", severity="critical")
        self.assertEqual(a.fired_at, 0.0)

    def test_default_rules_returns_three(self):
        rules = _default_rules()
        self.assertEqual(len(rules), 3)
        names = [r.name for r in rules]
        self.assertIn("host-unreachable", names)
        self.assertIn("disk-critical", names)
        self.assertIn("ram-pressure", names)


class TestRuleLoading(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_rules_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_load_missing_file_returns_defaults(self):
        rules = load_rules(self.tmpdir)
        self.assertEqual(len(rules), 3)

    def test_load_valid_toml(self):
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

    def test_load_empty_rules_returns_defaults(self):
        with open(os.path.join(self.tmpdir, "rules.toml"), "wb") as f:
            f.write(b"# empty\n")
        rules = load_rules(self.tmpdir)
        self.assertEqual(len(rules), 3)  # defaults

    def test_load_malformed_toml_returns_defaults(self):
        with open(os.path.join(self.tmpdir, "rules.toml"), "wb") as f:
            f.write(b"{{{{invalid toml!!")
        rules = load_rules(self.tmpdir)
        self.assertEqual(len(rules), 3)  # defaults

    def test_save_and_reload_roundtrip(self):
        rules = [Rule(name="test", condition="disk_above", threshold=90)]
        save_rules(self.tmpdir, rules)
        reloaded = load_rules(self.tmpdir)
        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].name, "test")
        self.assertEqual(reloaded[0].condition, "disk_above")


class TestRuleState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_rstate_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_rule_state(self.tmpdir), {})

    def test_save_and_load_roundtrip(self):
        state = {"rule1:host1": {"first_seen": 1000, "last_alerted": 1100}}
        save_rule_state(self.tmpdir, state)
        loaded = load_rule_state(self.tmpdir)
        self.assertEqual(loaded["rule1:host1"]["first_seen"], 1000)

    def test_load_corrupt_json_returns_empty(self):
        path = os.path.join(self.tmpdir, "rule_state.json")
        os.makedirs(self.tmpdir, exist_ok=True)
        with open(path, "w") as f:
            f.write("{{{invalid")
        self.assertEqual(load_rule_state(self.tmpdir), {})


class TestAlertHistory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_ahist_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_load_missing_returns_empty(self):
        self.assertEqual(load_alert_history(self.tmpdir), [])

    def test_save_and_load_roundtrip(self):
        history = [{"rule": "r1", "host": "h1", "ts": 1000}]
        save_alert_history(self.tmpdir, history)
        loaded = load_alert_history(self.tmpdir)
        self.assertEqual(len(loaded), 1)

    def test_save_caps_at_max_history(self):
        history = [{"i": i} for i in range(150)]
        save_alert_history(self.tmpdir, history)
        loaded = load_alert_history(self.tmpdir)
        self.assertEqual(len(loaded), MAX_HISTORY)
        self.assertEqual(loaded[0]["i"], 50)  # kept last 100


class TestTargetMatching(unittest.TestCase):
    def test_wildcard_matches_all(self):
        self.assertTrue(_matches_target("anything", "*"))

    def test_prefix_glob_matches(self):
        self.assertTrue(_matches_target("web-01", "web*"))
        self.assertTrue(_matches_target("web", "web*"))

    def test_prefix_glob_no_match(self):
        self.assertFalse(_matches_target("db-01", "web*"))

    def test_exact_match(self):
        self.assertTrue(_matches_target("host1", "host1"))
        self.assertFalse(_matches_target("host1", "host2"))


class TestParsing(unittest.TestCase):
    def test_parse_ram_percent_valid(self):
        self.assertAlmostEqual(_parse_ram_percent("4096/8192MB"), 50.0, places=1)

    def test_parse_ram_percent_invalid(self):
        self.assertIsNone(_parse_ram_percent("invalid"))
        self.assertIsNone(_parse_ram_percent(""))

    def test_parse_ram_percent_zero_total(self):
        self.assertIsNone(_parse_ram_percent("0/0MB"))

    def test_parse_disk_percent_valid(self):
        self.assertEqual(_parse_disk_percent("45%"), 45.0)

    def test_parse_disk_percent_invalid(self):
        self.assertIsNone(_parse_disk_percent("unknown"))
        self.assertIsNone(_parse_disk_percent(""))


class TestEvaluation(unittest.TestCase):
    def test_host_unreachable_fires(self):
        rules = [Rule(name="down", condition="host_unreachable", duration=0)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        state = {}
        alerts = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].host, "h1")

    def test_host_reachable_no_alert(self):
        rules = [Rule(name="down", condition="host_unreachable")]
        health = {"hosts": [{"label": "h1", "status": "ok"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 0)

    def test_cpu_above_fires(self):
        rules = [Rule(name="cpu", condition="cpu_above", threshold=5.0, duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "load": "8.5"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def test_ram_above_fires(self):
        rules = [Rule(name="ram", condition="ram_above", threshold=90, duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "7500/8192MB"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def test_disk_above_fires(self):
        rules = [Rule(name="disk", condition="disk_above", threshold=80, duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "disk": "95%"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def test_docker_down_fires(self):
        rules = [Rule(name="docker", condition="docker_down", duration=0)]
        health = {"hosts": [{"label": "h1", "status": "ok", "type": "docker", "docker": "0"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 1)

    def test_disabled_rule_skipped(self):
        rules = [Rule(name="off", condition="host_unreachable", enabled=False)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        alerts = evaluate_rules(health, rules, {})
        self.assertEqual(len(alerts), 0)

    def test_duration_gate_blocks(self):
        rules = [Rule(name="slow", condition="host_unreachable", duration=600)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        state = {}
        alerts = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts), 0)  # not enough time elapsed

    def test_cooldown_gate_blocks(self):
        rules = [Rule(name="cool", condition="host_unreachable", duration=0, cooldown=600)]
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        state = {}
        # First evaluation fires
        alerts1 = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts1), 1)
        # Second evaluation blocked by cooldown
        alerts2 = evaluate_rules(health, rules, state)
        self.assertEqual(len(alerts2), 0)

    def test_condition_cleared_resets_state(self):
        rules = [Rule(name="r1", condition="host_unreachable", duration=0)]
        state = {"r1:h1": {"first_seen": 1000, "last_alerted": 1100}}
        health = {"hosts": [{"label": "h1", "status": "ok"}]}
        evaluate_rules(health, rules, state)
        self.assertNotIn("r1:h1", state)
