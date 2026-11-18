"""Tests for freq.jarvis.cost — fleet cost tracking."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix

from freq.jarvis.cost import (
    CostConfig, HostCost, load_cost_config,
    parse_idrac_power, _parse_ram_mb, estimate_host_watts,
    compute_costs, costs_to_dicts, fleet_summary,
    cmd_cost,
    WATTS_PER_VCPU, WATTS_PER_GB_RAM, HOURS_PER_MONTH,
)


class TestCostConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_cost_cfg_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_defaults(self):
        cfg = CostConfig()
        self.assertEqual(cfg.rate_per_kwh, 0.12)
        self.assertEqual(cfg.currency, "USD")
        self.assertEqual(cfg.pue, 1.2)

    def _case_load_missing_file_returns_defaults(self):
        cfg = load_cost_config(self.tmpdir)
        self.assertEqual(cfg.rate_per_kwh, 0.12)

    def _case_load_valid_toml(self):
        toml = b'[cost]\nrate_per_kwh = 0.15\ncurrency = "EUR"\npue = 1.5\n'
        with open(os.path.join(self.tmpdir, "freq.toml"), "wb") as f:
            f.write(toml)
        cfg = load_cost_config(self.tmpdir)
        self.assertEqual(cfg.rate_per_kwh, 0.15)
        self.assertEqual(cfg.currency, "EUR")
        self.assertEqual(cfg.pue, 1.5)

    def _case_load_no_cost_section_returns_defaults(self):
        toml = b'[server]\nport = 8888\n'
        with open(os.path.join(self.tmpdir, "freq.toml"), "wb") as f:
            f.write(toml)
        cfg = load_cost_config(self.tmpdir)
        self.assertEqual(cfg.rate_per_kwh, 0.12)


class TestIdracParsing(unittest.TestCase):
    def _case_pwr_consumption(self):
        output = "System Board Pwr Consumption | 220 W | ok"
        self.assertEqual(parse_idrac_power(output), 220.0)

    def _case_input_wattage(self):
        output = "PS1 Input Wattage | 180 W | ok"
        self.assertEqual(parse_idrac_power(output), 180.0)

    def _case_power_consumption_variant(self):
        output = "Power Consumption | 350 W | ok"
        self.assertEqual(parse_idrac_power(output), 350.0)

    def _case_no_match(self):
        self.assertEqual(parse_idrac_power("Temperature | 42 C | ok"), 0.0)

    def _case_empty(self):
        self.assertEqual(parse_idrac_power(""), 0.0)


class TestRamParsing(unittest.TestCase):
    def _case_valid(self):
        self.assertEqual(_parse_ram_mb("4096/8192MB"), 8192.0)

    def _case_invalid(self):
        self.assertEqual(_parse_ram_mb("invalid"), 0.0)

    def _case_empty(self):
        self.assertEqual(_parse_ram_mb(""), 0.0)

    def _case_none(self):
        self.assertEqual(_parse_ram_mb(None), 0.0)


class TestWattEstimation(unittest.TestCase):
    def _case_normal_host(self):
        host = {"ram": "4096/8192MB", "load": "4.0", "docker": "5"}
        watts = estimate_host_watts(host)
        self.assertGreater(watts, 5.0)
        self.assertLessEqual(watts, 2000.0)

    def _case_minimal_floor(self):
        host = {"ram": "0/0MB", "load": "0"}
        watts = estimate_host_watts(host)
        self.assertGreaterEqual(watts, 5.0)

    def _case_huge_values_capped(self):
        host = {"ram": "999999/999999MB", "load": "500"}
        watts = estimate_host_watts(host)
        self.assertLessEqual(watts, 2000.0)

    def _case_missing_fields(self):
        host = {}
        watts = estimate_host_watts(host)
        self.assertGreaterEqual(watts, 5.0)

    def _case_invalid_load(self):
        host = {"load": "invalid"}
        watts = estimate_host_watts(host)
        self.assertGreaterEqual(watts, 5.0)

    def _case_docker_contribution(self):
        host_no_docker = {"ram": "4096/8192MB", "load": "2.0", "docker": "0"}
        host_with_docker = {"ram": "4096/8192MB", "load": "2.0", "docker": "10"}
        w1 = estimate_host_watts(host_no_docker)
        w2 = estimate_host_watts(host_with_docker)
        self.assertGreater(w2, w1)


class TestComputeCosts(unittest.TestCase):
    def _case_with_idrac(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2.0"}]}
        idrac = {"h1": 250.0}
        cfg = CostConfig(rate_per_kwh=0.12, pue=1.2)
        costs = compute_costs(health, idrac, cfg)
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0].watts_source, "idrac")
        self.assertEqual(costs[0].watts, 250.0)
        self.assertGreater(costs[0].cost_month, 0)

    def _case_without_idrac(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2.0"}]}
        idrac = {}
        cfg = CostConfig()
        costs = compute_costs(health, idrac, cfg)
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0].watts_source, "estimate")

    def _case_unreachable_skipped(self):
        health = {"hosts": [{"label": "h1", "status": "unreachable"}]}
        costs = compute_costs(health, {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def _case_empty_hosts(self):
        costs = compute_costs({"hosts": []}, {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def _case_none_health_returns_empty_costs(self):
        costs = compute_costs(None, {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def _case_legacy_host_list_shape(self):
        health = [{"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2.0"}]
        costs = compute_costs(health, {}, CostConfig())
        self.assertEqual(len(costs), 1)
        self.assertEqual(costs[0].label, "h1")

    def _case_unknown_health_shape_returns_empty_costs(self):
        costs = compute_costs("bad-cache-shape", {}, CostConfig())
        self.assertEqual(len(costs), 0)

    def _case_null_resource_fields_do_not_crash(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": None, "load": None, "docker": None}]}
        costs = compute_costs(health, {}, CostConfig())
        self.assertEqual(len(costs), 1)
        self.assertGreaterEqual(costs[0].watts, 5.0)

    def _case_sorted_by_cost_descending(self):
        health = {"hosts": [
            {"label": "cheap", "status": "ok", "ram": "512/1024MB", "load": "0.5"},
            {"label": "expensive", "status": "ok", "ram": "16384/32768MB", "load": "16.0"},
        ]}
        costs = compute_costs(health, {}, CostConfig())
        self.assertEqual(costs[0].label, "expensive")

    def _case_pue_clamped(self):
        health = {"hosts": [{"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2"}]}
        # PUE > 3.0 should be clamped
        cfg = CostConfig(pue=10.0)
        costs = compute_costs(health, {}, cfg)
        # With PUE=3.0 (clamped), cost should be less than with PUE=10.0
        cfg2 = CostConfig(pue=1.0)
        costs2 = compute_costs(health, {}, cfg2)
        # PUE 3.0 (clamped from 10) should produce higher cost than PUE 1.0
        self.assertGreater(costs[0].cost_month, costs2[0].cost_month)


COMPUTE_COST_CASES = (
    "_case_with_idrac",
    "_case_without_idrac",
    "_case_unreachable_skipped",
    "_case_empty_hosts",
    "_case_none_health_returns_empty_costs",
    "_case_legacy_host_list_shape",
    "_case_unknown_health_shape_returns_empty_costs",
    "_case_null_resource_fields_do_not_crash",
    "_case_sorted_by_cost_descending",
    "_case_pue_clamped",
)


class TestComputeCostsMatrix(unittest.TestCase):
    def test_compute_costs_matrix(self):
        run_case_matrix(self, TestComputeCosts, COMPUTE_COST_CASES)


class TestSerialization(unittest.TestCase):
    def _case_costs_to_dicts(self):
        costs = [HostCost(label="h1", watts=200, kwh_month=146, cost_month=17.52)]
        dicts = costs_to_dicts(costs)
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]["label"], "h1")
        self.assertIn("watts_source", dicts[0])

    def _case_fleet_summary(self):
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

    def _case_fleet_summary_empty(self):
        summary = fleet_summary([], CostConfig())
        self.assertEqual(summary["host_count"], 0)
        self.assertEqual(summary["total_cost_month"], 0)


class _LockProbe:
    def __init__(self):
        self.active = False
        self.entries = 0
        self.exits = 0

    def __enter__(self):
        if self.active:
            raise AssertionError("cost cache lock entered recursively")
        self.active = True
        self.entries += 1
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.active = False
        self.exits += 1


class _GuardedCache:
    def __init__(self, lock, values):
        self.lock = lock
        self.values = values
        self.keys = []

    def get(self, key):
        if not self.lock.active:
            raise AssertionError("cost cache read without its owner lock")
        self.keys.append(key)
        return self.values.get(key)


class TestCostCommandCacheContract(unittest.TestCase):
    def _run_cost(self, values, computed_costs):
        from freq.modules import serve
        from freq.services import dashboard_state

        lock = _LockProbe()
        cache = _GuardedCache(lock, values)
        cfg = SimpleNamespace(conf_dir="/etc/freq-test")
        args = SimpleNamespace()
        cost_cfg = CostConfig(rate_per_kwh=0.17, currency="EUR", pue=1.4)

        with (
            mock.patch.object(serve, "_bg_cache", cache),
            mock.patch.object(serve, "_bg_lock", lock),
            mock.patch.object(dashboard_state, "background_cache", cache),
            mock.patch.object(dashboard_state, "background_cache_lock", lock),
            mock.patch("freq.jarvis.cost.load_cost_config", return_value=cost_cfg) as load,
            mock.patch("freq.jarvis.cost.compute_costs", return_value=computed_costs) as compute,
            mock.patch("freq.core.fmt.header") as header,
            mock.patch("freq.core.fmt.line") as line,
            mock.patch("freq.core.fmt.blank") as blank,
            mock.patch("freq.core.fmt.footer") as footer,
        ):
            result = cmd_cost(cfg, None, args)

        self.assertEqual(lock.entries, lock.exits)
        self.assertFalse(lock.active)
        load.assert_called_once_with(cfg.conf_dir)
        header.assert_called_once_with("Fleet Power Costs")
        footer.assert_called_once_with()
        return result, cache, lock, cost_cfg, compute, line, blank

    def _case_missing_health_stops_after_one_locked_read(self):
        result, cache, lock, _, compute, line, blank = self._run_cost(
            {"health": None, "infra_quick": {"devices": []}}, []
        )

        self.assertEqual(result, 0)
        self.assertEqual(cache.keys, ["health"])
        self.assertEqual(lock.entries, 1)
        compute.assert_not_called()
        self.assertEqual(line.call_count, 2)
        self.assertIn("No health data available.", line.call_args_list[0].args[0])
        self.assertIn("Run freq serve first", line.call_args_list[1].args[0])
        self.assertEqual(blank.call_count, 2)

    def _case_health_and_idrac_are_handed_to_cost_engine_exactly(self):
        health = {"hosts": [{"label": "pve1", "status": "ok"}]}
        infra = {"devices": [
            {"type": "idrac", "label": "pve1", "power_watts": 180},
            {"type": "idrac", "label": "pve2", "power_watts": 0},
            {"type": "idrac", "label": "pve3", "power_watts": -25},
            {"type": "switch", "label": "sw1", "power_watts": 40},
        ]}
        result, cache, lock, cost_cfg, compute, line, blank = self._run_cost(
            {"health": health, "infra_quick": infra}, []
        )

        self.assertEqual(result, 0)
        self.assertEqual(cache.keys, ["health", "infra_quick"])
        self.assertEqual(lock.entries, 2)
        self.assertIs(compute.call_args.args[0], health)
        compute.assert_called_once_with(health, {"pve1": 180, "pve3": -25}, cost_cfg)
        self.assertEqual(line.call_count, 1)
        self.assertIn("No hosts to estimate costs for.", line.call_args.args[0])
        self.assertEqual(blank.call_count, 2)

    def _case_missing_infra_uses_empty_idrac_map(self):
        health = {"hosts": [{"label": "pve1", "status": "ok"}]}
        result, cache, lock, cost_cfg, compute, line, blank = self._run_cost(
            {"health": health, "infra_quick": None}, []
        )

        self.assertEqual(result, 0)
        self.assertEqual(cache.keys, ["health", "infra_quick"])
        self.assertEqual(lock.entries, 2)
        compute.assert_called_once_with(health, {}, cost_cfg)
        self.assertEqual(line.call_count, 1)
        self.assertIn("No hosts to estimate costs for.", line.call_args.args[0])
        self.assertEqual(blank.call_count, 2)


COST_CONFIG_CASES = (
    "_case_defaults", "_case_load_missing_file_returns_defaults",
    "_case_load_valid_toml", "_case_load_no_cost_section_returns_defaults",
)
IDRAC_POWER_PARSING_CASES = (
    "_case_pwr_consumption", "_case_input_wattage",
    "_case_power_consumption_variant", "_case_no_match", "_case_empty",
)
RAM_PARSING_CASES = ("_case_valid", "_case_invalid", "_case_empty", "_case_none")
WATT_ESTIMATION_CASES = (
    "_case_normal_host", "_case_minimal_floor", "_case_huge_values_capped",
    "_case_missing_fields", "_case_invalid_load", "_case_docker_contribution",
)
COST_SERIALIZATION_CASES = (
    "_case_costs_to_dicts", "_case_fleet_summary", "_case_fleet_summary_empty",
)
COST_COMMAND_CACHE_CASES = (
    "_case_missing_health_stops_after_one_locked_read",
    "_case_health_and_idrac_are_handed_to_cost_engine_exactly",
    "_case_missing_infra_uses_empty_idrac_map",
)


class TestCostConfigMatrix(unittest.TestCase):
    def test_cost_config_matrix(self):
        run_case_matrix(self, TestCostConfig, COST_CONFIG_CASES)


class TestIdracPowerParsingMatrix(unittest.TestCase):
    def test_idrac_power_parsing_matrix(self):
        run_case_matrix(self, TestIdracParsing, IDRAC_POWER_PARSING_CASES)


class TestRamParsingMatrix(unittest.TestCase):
    def test_ram_parsing_matrix(self):
        run_case_matrix(self, TestRamParsing, RAM_PARSING_CASES)


class TestWattEstimationMatrix(unittest.TestCase):
    def test_watt_estimation_matrix(self):
        run_case_matrix(self, TestWattEstimation, WATT_ESTIMATION_CASES)


class TestCostSerializationMatrix(unittest.TestCase):
    def test_cost_serialization_matrix(self):
        run_case_matrix(self, TestSerialization, COST_SERIALIZATION_CASES)


class TestCostCommandCacheMatrix(unittest.TestCase):
    def test_cost_command_cache_matrix(self):
        run_case_matrix(self, TestCostCommandCacheContract, COST_COMMAND_CACHE_CASES)


if __name__ == "__main__":
    unittest.main()
