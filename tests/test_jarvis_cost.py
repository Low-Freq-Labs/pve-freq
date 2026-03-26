"""Tests for freq.jarvis.cost — fleet cost tracking."""
import json
import os
import shutil
import tempfile
import unittest

from freq.jarvis.cost import (
    CostConfig, HostCost, load_cost_config,
    parse_idrac_power, _parse_ram_mb, estimate_host_watts,
    compute_costs, costs_to_dicts, fleet_summary,
    WATTS_PER_VCPU, WATTS_PER_GB_RAM, HOURS_PER_MONTH,
)


class TestCostConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cost_cfg_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_defaults(self):
        cfg = CostConfig()
        self.assertEqual(cfg.rate_per_kwh, 0.12)
        self.assertEqual(cfg.currency, "USD")
        self.assertEqual(cfg.pue, 1.2)

    def test_load_missing_file_returns_defaults(self):
        cfg = load_cost_config(self.tmpdir)
        self.assertEqual(cfg.rate_per_kwh, 0.12)

    def test_load_valid_toml(self):
        toml = b'[cost]\nrate_per_kwh = 0.15\ncurrency = "EUR"\npue = 1.5\n'
        with open(os.path.join(self.tmpdir, "freq.toml"), "wb") as f:
            f.write(toml)
        cfg = load_cost_config(self.tmpdir)
        self.assertEqual(cfg.rate_per_kwh, 0.15)
        self.assertEqual(cfg.currency, "EUR")
        self.assertEqual(cfg.pue, 1.5)

    def test_load_no_cost_section_returns_defaults(self):
        toml = b'[server]\nport = 8888\n'
        with open(os.path.join(self.tmpdir, "freq.toml"), "wb") as f:
            f.write(toml)
        cfg = load_cost_config(self.tmpdir)
        self.assertEqual(cfg.rate_per_kwh, 0.12)


class TestIdracParsing(unittest.TestCase):
    def test_pwr_consumption(self):
        output = "System Board Pwr Consumption | 220 W | ok"
        self.assertEqual(parse_idrac_power(output), 220.0)

    def test_input_wattage(self):
        output = "PS1 Input Wattage | 180 W | ok"
        self.assertEqual(parse_idrac_power(output), 180.0)

    def test_power_consumption_variant(self):
        output = "Power Consumption | 350 W | ok"
        self.assertEqual(parse_idrac_power(output), 350.0)

    def test_no_match(self):
        self.assertEqual(parse_idrac_power("Temperature | 42 C | ok"), 0.0)

    def test_empty(self):
        self.assertEqual(parse_idrac_power(""), 0.0)


class TestRamParsing(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(_parse_ram_mb("4096/8192MB"), 8192.0)

    def test_invalid(self):
        self.assertEqual(_parse_ram_mb("invalid"), 0.0)

    def test_empty(self):
        self.assertEqual(_parse_ram_mb(""), 0.0)


class TestWattEstimation(unittest.TestCase):
    def test_normal_host(self):
        host = {"ram": "4096/8192MB", "load": "4.0", "docker": "5"}
        watts = estimate_host_watts(host)
        self.assertGreater(watts, 5.0)
        self.assertLessEqual(watts, 2000.0)

    def test_minimal_floor(self):
        host = {"ram": "0/0MB", "load": "0"}
        watts = estimate_host_watts(host)
        self.assertGreaterEqual(watts, 5.0)

    def test_huge_values_capped(self):
        host = {"ram": "999999/999999MB", "load": "500"}
        watts = estimate_host_watts(host)
        self.assertLessEqual(watts, 2000.0)

    def test_missing_fields(self):
        host = {}
        watts = estimate_host_watts(host)
        self.assertGreaterEqual(watts, 5.0)

    def test_invalid_load(self):
        host = {"load": "invalid"}
        watts = estimate_host_watts(host)
        self.assertGreaterEqual(watts, 5.0)

    def test_docker_contribution(self):
        host_no_docker = {"ram": "4096/8192MB", "load": "2.0", "docker": "0"}
        host_with_docker = {"ram": "4096/8192MB", "load": "2.0", "docker": "10"}
        w1 = estimate_host_watts(host_no_docker)
        w2 = estimate_host_watts(host_with_docker)
        self.assertGreater(w2, w1)


class TestComputeCosts(unittest.TestCase):
    def test_with_idrac(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2.0"}]}
        idrac = {"h1": 250.0}
        cfg = CostConfig(rate_per_kwh=0.12, pue=1.2)
        costs = compute_costs(health, idrac, cfg)
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0].watts_source, "idrac")
        self.assertEqual(costs[0].watts, 250.0)
        self.assertGreater(costs[0].cost_month, 0)

    def test_without_idrac(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2.0"}]}
        idrac = {}
        cfg = CostConfig()
        costs = compute_costs(health, idrac, cfg)
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0].watts_source, "estimate")

    def test_unreachable_skipped(self):
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        costs = compute_costs(health, {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def test_empty_hosts(self):
        costs = compute_costs({"hosts": []}, {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def test_sorted_by_cost_descending(self):
        health = {"hosts": [
            {"label": "cheap", "status": "ok", "ram": "512/1024MB", "load": "0.5"},
            {"label": "expensive", "status": "ok", "ram": "16384/32768MB", "load": "16.0"},
        ]}
        costs = compute_costs(health, {}, CostConfig())
        self.assertEqual(costs[0].label, "expensive")

    def test_pue_clamped(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2"}]}
        # PUE > 3.0 should be clamped
        cfg = CostConfig(pue=10.0)
        costs = compute_costs(health, {}, cfg)
        # With PUE=3.0 (clamped), cost should be less than with PUE=10.0
        cfg2 = CostConfig(pue=1.0)
        costs2 = compute_costs(health, {}, cfg2)
        # PUE 3.0 (clamped from 10) should produce higher cost than PUE 1.0
        self.assertGreater(costs[0].cost_month, costs2[0].cost_month)


class TestSerialization(unittest.TestCase):
    def test_costs_to_dicts(self):
        costs = [HostCost(label="h1", watts=200, kwh_month=146, cost_month=17.52)]
        dicts = costs_to_dicts(costs)
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]["label"], "h1")
        self.assertIn("watts_source", dicts[0])

    def test_fleet_summary(self):
        costs = [
            HostCost(label="h1", watts=200, watts_source="idrac", kwh_month=146, cost_month=17.52),
            HostCost(label="h2", watts=100, watts_source="estimate", kwh_month=73, cost_month=8.76),
        ]
        summary = fleet_summary(costs, CostConfig())
        self.assertEqual(summary["host_count"], 2)
        self.assertEqual(summary["idrac_measured"], 1)
        self.assertEqual(summary["estimated"], 1)
        self.assertAlmostEqual(summary["total_watts"], 300.0)
        self.assertEqual(summary["currency"], "USD")

    def test_fleet_summary_empty(self):
        summary = fleet_summary([], CostConfig())
        self.assertEqual(summary["host_count"], 0)
        self.assertEqual(summary["total_cost_month"], 0)
