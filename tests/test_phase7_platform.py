"""Phase 7 Platform Kills — Tests.

Tests for: map (depmap), netmon, cost-analysis
"""
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestDepmapModule(unittest.TestCase):

    def test_map_roundtrip(self):
        from freq.modules.depmap import _load_map, _save_map
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            depmap = {
                "nodes": {"h1": {"ip": "10.0.0.1", "listens": []}},
                "edges": [{"from": "h1", "to": "h2", "port": "5432", "type": "tcp"}],
                "scan_time": "now",
            }
            _save_map(cfg, depmap)
            loaded = _load_map(cfg)
            self.assertEqual(len(loaded["edges"]), 1)

    def test_get_impact(self):
        from freq.modules.depmap import _get_impact
        depmap = {
            "nodes": {"db": {"listens": [{"port": "5432", "process": "postgres"}]}},
            "edges": [
                {"from": "web", "to": "db", "port": "5432", "type": "tcp"},
                {"from": "api", "to": "db", "port": "5432", "type": "tcp"},
            ],
        }
        impact = _get_impact(depmap, "db")
        self.assertEqual(impact["target"], "db")
        self.assertEqual(len(impact["dependents"]), 2)
        self.assertIn("web", impact["dependents"])
        self.assertIn("api", impact["dependents"])
        self.assertEqual(impact["impact_score"], 2)

    def test_get_impact_no_dependents(self):
        from freq.modules.depmap import _get_impact
        depmap = {"nodes": {}, "edges": [{"from": "web", "to": "db", "port": "5432", "type": "tcp"}]}
        impact = _get_impact(depmap, "web")
        self.assertEqual(len(impact["dependents"]), 0)
        self.assertEqual(len(impact["dependencies"]), 1)


class TestNetmonModule(unittest.TestCase):

    def test_format_bytes(self):
        from freq.modules.netmon import _format_bytes
        self.assertEqual(_format_bytes(500), "500B")
        self.assertEqual(_format_bytes(1500), "1.5K")
        self.assertEqual(_format_bytes(1500000), "1.4M")
        self.assertEqual(_format_bytes(1500000000), "1.4G")

    def test_data_roundtrip(self):
        from freq.modules.netmon import _load_data, _save_data
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir
            data = {"snapshots": [{"epoch": 1000, "hosts": {}}], "topology": {}}
            _save_data(cfg, data)
            loaded = _load_data(cfg)
            self.assertEqual(len(loaded["snapshots"]), 1)


class TestCostAnalysisModule(unittest.TestCase):

    def test_estimate_vm_cost(self):
        from freq.modules.cost_analysis import _estimate_vm_monthly_cost
        cost = _estimate_vm_monthly_cost(4, 8, 0.12, 1.2)
        self.assertGreater(cost, 0)

    def test_estimate_aws_cost(self):
        from freq.modules.cost_analysis import _estimate_aws_cost
        # 4 vCPU, 16 GB RAM should map to t3.xlarge (~$120/mo)
        cost = _estimate_aws_cost(4, 16)
        self.assertEqual(cost, 120.00)

    def test_estimate_aws_cost_small(self):
        from freq.modules.cost_analysis import _estimate_aws_cost
        cost = _estimate_aws_cost(1, 1)
        self.assertEqual(cost, 8.50)

    def test_onprem_cheaper_than_aws(self):
        from freq.modules.cost_analysis import _estimate_vm_monthly_cost, _estimate_aws_cost
        onprem = _estimate_vm_monthly_cost(4, 16)
        aws = _estimate_aws_cost(4, 16)
        self.assertLess(onprem, aws)

    def test_aws_pricing_table(self):
        from freq.modules.cost_analysis import AWS_PRICING
        self.assertGreaterEqual(len(AWS_PRICING), 8)


class TestPhase7CommandCount(unittest.TestCase):
    def test_command_count_at_least_38(self):
        """Domain-based CLI: 38+ top-level domains."""
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 38,
                                f"Expected 38+, got {len(registered)}")


if __name__ == "__main__":
    unittest.main()
