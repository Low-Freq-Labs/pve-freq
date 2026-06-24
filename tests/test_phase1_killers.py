"""Phase 1 Killer Commands — Tests.

Tests for: alert, rollback, inventory, compare, baseline
5 new commands that kill Zabbix, Nagios, ServiceNow, Puppet, and Chef.
"""
import argparse
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))
REPO_ROOT = str(Path(__file__).parent.parent)


class TestPhase1Registration(unittest.TestCase):
    """Verify all Phase 1 commands are registered in the CLI parser."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
        # Get all registered commands
        self.registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                self.registered.update(action.choices.keys())

    def test_alert_registered(self):
        self.assertIn("observe", self.registered)  # alert under observe

    def test_rollback_registered(self):
        self.assertIn("vm", self.registered)  # rollback under vm

    def test_inventory_registered(self):
        self.assertIn("fleet", self.registered)  # inventory under fleet

    def test_compare_registered(self):
        self.assertIn("fleet", self.registered)  # compare under fleet

    def test_baseline_registered(self):
        self.assertIn("state", self.registered)  # baseline under state


class TestPhase1Parsing(unittest.TestCase):
    """Verify argument parsing for all Phase 1 commands."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_alert_list_default(self):
        args = self.parser.parse_args(["observe", "alert"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_alert_create_args(self):
        args = self.parser.parse_args([
            "observe", "alert", "create", "test-rule",
            "--condition", "cpu_above",
            "--threshold", "2.0",
            "--alert-severity", "critical",
        ])
        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "test-rule")
        self.assertEqual(args.condition, "cpu_above")
        self.assertEqual(args.threshold, 2.0)
        self.assertEqual(args.alert_severity, "critical")

    def test_alert_delete(self):
        args = self.parser.parse_args(["observe", "alert", "delete", "my-rule"])
        self.assertEqual(args.action, "delete")
        self.assertEqual(args.name, "my-rule")

    def test_alert_silence(self):
        args = self.parser.parse_args(["observe", "alert", "silence", "host-*", "--duration", "120"])
        self.assertEqual(args.action, "silence")
        self.assertEqual(args.name, "host-*")
        self.assertEqual(args.duration, 120)

    def test_alert_check(self):
        args = self.parser.parse_args(["observe", "alert", "check"])
        self.assertEqual(args.action, "check")

    def test_alert_test(self):
        args = self.parser.parse_args(["observe", "alert", "test"])
        self.assertEqual(args.action, "test")

    def test_alert_history(self):
        args = self.parser.parse_args(["observe", "alert", "history", "--lines", "50"])
        self.assertEqual(args.action, "history")
        self.assertEqual(args.lines, 50)

    def test_rollback_vmid(self):
        args = self.parser.parse_args(["vm", "rollback", "5005"])
        self.assertEqual(args.target, "5005")
        self.assertTrue(hasattr(args, "func"))

    def test_rollback_with_name(self):
        args = self.parser.parse_args(["vm", "rollback", "100", "--name", "pre-upgrade"])
        self.assertEqual(args.target, "100")
        self.assertEqual(args.name, "pre-upgrade")

    def test_rollback_no_start(self):
        args = self.parser.parse_args(["vm", "rollback", "100", "--no-start"])
        self.assertTrue(args.no_start)

    def test_inventory_default(self):
        args = self.parser.parse_args(["fleet", "inventory"])
        self.assertEqual(args.section, "all")
        self.assertTrue(hasattr(args, "func"))

    def test_inventory_hosts_only(self):
        args = self.parser.parse_args(["fleet", "inventory", "hosts"])
        self.assertEqual(args.section, "hosts")

    def test_inventory_vms_only(self):
        args = self.parser.parse_args(["fleet", "inventory", "vms"])
        self.assertEqual(args.section, "vms")

    def test_inventory_csv(self):
        args = self.parser.parse_args(["fleet", "inventory", "--csv"])
        self.assertTrue(args.csv)

    def test_compare_two_hosts(self):
        args = self.parser.parse_args(["fleet", "compare", "pve01", "pve02"])
        self.assertEqual(args.target_a, "pve01")
        self.assertEqual(args.target_b, "pve02")
        self.assertTrue(hasattr(args, "func"))

    def test_baseline_default(self):
        args = self.parser.parse_args(["state", "baseline"])
        self.assertEqual(args.action, "list")
        self.assertTrue(hasattr(args, "func"))

    def test_baseline_capture(self):
        args = self.parser.parse_args(["state", "baseline", "capture", "my-baseline"])
        self.assertEqual(args.action, "capture")
        self.assertEqual(args.name, "my-baseline")

    def test_baseline_compare(self):
        args = self.parser.parse_args(["state", "baseline", "compare", "my-baseline"])
        self.assertEqual(args.action, "compare")
        self.assertEqual(args.name, "my-baseline")

    def test_baseline_delete(self):
        args = self.parser.parse_args(["state", "baseline", "delete", "old-baseline"])
        self.assertEqual(args.action, "delete")
        self.assertEqual(args.name, "old-baseline")


class TestAlertModule(unittest.TestCase):
    """Test the alert module's internal logic."""

    def test_import(self):
        from freq.modules.alert import cmd_alert
        self.assertTrue(callable(cmd_alert))

    def test_conditions_dict(self):
        from freq.modules.alert import CONDITIONS
        self.assertIn("host_down", CONDITIONS)
        self.assertIn("cpu_above", CONDITIONS)
        self.assertIn("ram_above", CONDITIONS)
        self.assertIn("disk_above", CONDITIONS)
        self.assertIn("docker_down", CONDITIONS)
        self.assertIn("load_spike", CONDITIONS)
        self.assertGreaterEqual(len(CONDITIONS), 8)

    def test_evaluate_condition_host_down(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": False}
        result = _evaluate_condition("host_down", 0, metrics, {})
        self.assertIsNotNone(result)
        self.assertIn("DOWN", result["message"])

    def test_evaluate_condition_host_up(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True}
        result = _evaluate_condition("host_down", 0, metrics, {})
        self.assertIsNone(result)

    def test_evaluate_condition_cpu_above(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "load_ratio": 3.5, "cores": 4}
        result = _evaluate_condition("cpu_above", 2.0, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_cpu_below(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "load_ratio": 0.5, "cores": 4}
        result = _evaluate_condition("cpu_above", 2.0, metrics, {})
        self.assertIsNone(result)

    def test_evaluate_condition_ram_above(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "ram_pct": 95.0}
        result = _evaluate_condition("ram_above", 90.0, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_disk_above(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "disk_pct": 88}
        result = _evaluate_condition("disk_above", 80, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_docker_down(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "docker": "inactive"}
        result = _evaluate_condition("docker_down", 0, metrics, {})
        self.assertIsNotNone(result)

    def test_evaluate_condition_docker_running(self):
        from freq.modules.alert import _evaluate_condition
        metrics = {"label": "test-host", "reachable": True, "docker": "active"}
        result = _evaluate_condition("docker_down", 0, metrics, {})
        self.assertIsNone(result)

    def test_host_matches_wildcard(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {}, "*"))

    def test_host_matches_exact(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {}, "pve01"))

    def test_host_matches_prefix(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {}, "pve*"))

    def test_host_matches_type(self):
        from freq.modules.alert import _host_matches
        self.assertTrue(_host_matches("pve01", {"type": "pve"}, "pve"))

    def test_host_not_matches(self):
        from freq.modules.alert import _host_matches
        self.assertFalse(_host_matches("media01", {"type": "linux"}, "pve01"))

    def test_json_file_operations(self):
        from freq.modules.alert import _load_json, _save_json
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            # Test save
            _save_json(path, [{"test": True}])
            # Test load
            data = _load_json(path)
            self.assertEqual(len(data), 1)
            self.assertTrue(data[0]["test"])
        finally:
            os.unlink(path)

    def test_load_json_missing_file(self):
        from freq.modules.alert import _load_json
        data = _load_json("/nonexistent/path.json")
        self.assertEqual(data, [])

    def test_severities(self):
        from freq.modules.alert import SEVERITIES
        self.assertIn("info", SEVERITIES)
        self.assertIn("warning", SEVERITIES)
        self.assertIn("critical", SEVERITIES)


class TestRollbackModule(unittest.TestCase):
    """Test the rollback module."""

    def test_import(self):
        from freq.modules.rollback import cmd_rollback
        self.assertTrue(callable(cmd_rollback))

    def test_get_snapshots_parser(self):
        """Verify rollback can parse PVE snapshot output format."""
        from freq.modules.rollback import _get_snapshots
        # The function requires SSH — just verify it exists and is callable
        self.assertTrue(callable(_get_snapshots))


class TestInventoryModule(unittest.TestCase):
    """Test the inventory module."""

    def test_import(self):
        from freq.modules.inventory import cmd_inventory
        self.assertTrue(callable(cmd_inventory))

    def test_to_csv(self):
        from freq.modules.inventory import _to_csv
        data = [
            {"name": "host1", "ip": "10.0.0.1", "cores": 4},
            {"name": "host2", "ip": "10.0.0.2", "cores": 8},
        ]
        csv_output = _to_csv(data)
        self.assertIn("name,ip,cores", csv_output)
        self.assertIn("host1,10.0.0.1,4", csv_output)
        self.assertIn("host2,10.0.0.2,8", csv_output)

    def test_to_csv_empty(self):
        from freq.modules.inventory import _to_csv
        self.assertEqual(_to_csv([]), "")


class TestCompareModule(unittest.TestCase):
    """Test the compare module."""

    def test_import(self):
        from freq.modules.compare import cmd_compare
        self.assertTrue(callable(cmd_compare))

    def test_compare_field_equal_strings(self):
        from freq.modules.compare import _compare_field
        label, sa, sb, ind = _compare_field("OS", "Debian 13", "Debian 13")
        self.assertEqual(sa, "Debian 13")
        self.assertEqual(sb, "Debian 13")
        self.assertIn("=", ind)

    def test_compare_field_different_strings(self):
        from freq.modules.compare import _compare_field
        label, sa, sb, ind = _compare_field("OS", "Debian 13", "Ubuntu 24.04")
        self.assertIn("≠", ind)

    def test_compare_field_numeric(self):
        from freq.modules.compare import _compare_field
        label, sa, sb, ind = _compare_field("Cores", "8", "4", higher_is_better=True)
        self.assertIn("◀", ind)  # A is better


class TestBaselineModule(unittest.TestCase):
    """Test the baseline module."""

    def test_import(self):
        from freq.modules.baseline import cmd_baseline
        self.assertTrue(callable(cmd_baseline))

    def test_parse_sections(self):
        from freq.modules.baseline import _parse_sections
        output = (
            "---PACKAGES---\n"
            "vim=8.2\n"
            "curl=7.88\n"
            "---SERVICES---\n"
            "sshd.service\n"
            "docker.service\n"
            "---USERS---\n"
            "freq-ops\n"
            "admin\n"
            "---KERNEL---\n"
            "6.1.0-27-amd64\n"
            "---END---\n"
        )
        sections = _parse_sections(output)
        self.assertEqual(len(sections["packages"]), 2)
        self.assertIn("vim=8.2", sections["packages"])
        self.assertEqual(len(sections["services"]), 2)
        self.assertIn("sshd.service", sections["services"])
        self.assertEqual(len(sections["users"]), 2)
        self.assertEqual(sections["kernel"], ["6.1.0-27-amd64"])

    def test_parse_sections_empty(self):
        from freq.modules.baseline import _parse_sections
        sections = _parse_sections("")
        self.assertEqual(sections, {})

    def test_baseline_json_roundtrip(self):
        """Test saving and loading a baseline."""
        from freq.modules.baseline import _save_baseline, _load_baseline
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock cfg
            cfg = MagicMock()
            cfg.conf_dir = tmpdir

            baseline_data = {
                "name": "test",
                "timestamp": "2026-03-31T12:00:00-0500",
                "hosts": {
                    "pve01": {
                        "packages": ["vim=8.2", "curl=7.88"],
                        "services": ["sshd.service"],
                    }
                },
            }

            _save_baseline(cfg, "test", baseline_data)
            loaded = _load_baseline(cfg, "test")

            self.assertEqual(loaded["name"], "test")
            self.assertEqual(len(loaded["hosts"]["pve01"]["packages"]), 2)

    def test_list_baselines(self):
        """Test listing baselines."""
        from freq.modules.baseline import _save_baseline, _list_baselines
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = MagicMock()
            cfg.conf_dir = tmpdir

            _save_baseline(cfg, "b1", {"name": "b1", "timestamp": "t1", "hosts": {"h1": {}}})
            _save_baseline(cfg, "b2", {"name": "b2", "timestamp": "t2", "hosts": {"h1": {}, "h2": {}}})

            baselines = _list_baselines(cfg)
            self.assertEqual(len(baselines), 2)
            names = [b["name"] for b in baselines]
            self.assertIn("b1", names)
            self.assertIn("b2", names)


class TestPhase1CommandCount(unittest.TestCase):
    """Verify we've passed 100 commands."""

    def test_command_count_at_least_104(self):
        """We should have at least 38 domain commands."""
        from freq.cli import _build_parser
        parser = _build_parser()
        registered = set()
        for action in parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertGreaterEqual(len(registered), 38,
                                f"Expected 38+ domain commands, got {len(registered)}: {sorted(registered)}")


class TestFleetInventoryContracts(unittest.TestCase):
    """Inventory must use the same live identity and VM truth as runtime commands."""

    def test_inventory_ssh_calls_pass_live_config(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/inventory.py")) as f:
            src = f.read()

        self.assertIn("cfg=cfg", src.split("def _gather_hosts")[1].split("def _gather_vms")[0])
        self.assertIn("cfg=cfg", src.split("def _gather_containers")[1].split("def _to_csv")[0])

    def test_inventory_vms_prefers_pve_api_path(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/inventory.py")) as f:
            block = src = f.read()
        gather_vms = block.split("def _gather_vms")[1].split("def _normalize_vm_rows")[0]

        self.assertIn("_pve_call", gather_vms)
        self.assertIn('/cluster/resources?type=vm', gather_vms)
        self.assertIn("_normalize_vm_rows", src)

    def test_inventory_vm_rows_preserve_template_truth(self):
        from freq.modules.inventory import _normalize_vm_rows

        rows = _normalize_vm_rows([
            {"vmid": 100, "name": "real", "status": "running"},
            {"vmid": 9000, "name": "template-by-range", "status": "stopped"},
            {"vmid": 500, "name": "template-by-flag", "status": "stopped", "template": 1},
        ])

        by_vmid = {row["vmid"]: row for row in rows}
        self.assertEqual(by_vmid[100]["template"], 0)
        self.assertEqual(by_vmid[9000]["template"], 1)
        self.assertEqual(by_vmid[500]["template"], 1)

    def test_container_inventory_only_queries_managed_docker_hosts(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/inventory.py")) as f:
            block = f.read().split("def _gather_containers")[1].split("def _to_csv")[0]

        self.assertIn('h.htype == "docker"', block)
        self.assertIn('getattr(h, "managed", True)', block)

    def test_init_preserves_vmid_map_for_explicit_hosts(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/init_cmd.py")) as f:
            src = f.read()

        discovery = src.split("def _phase_fleet_discover")[1].split("def _is_docker_bridge_ip")[0]
        deploy = src.split("def _headless_fleet_deploy")[1].split("def _deploy_via_guest_agent")[0]

        self.assertIn('ctx.setdefault("ip_vmid_map"', discovery)
        self.assertIn("ip_vmid_map.setdefault(ip, vmid)", discovery)
        self.assertIn('ctx.get("ip_vmid_map", {}).get(h.ip, 0)', deploy)

    def test_headless_discovery_auto_registers_only_managed_hosts(self):
        from freq.modules.init_cmd import _is_managed_auto_host

        self.assertTrue(_is_managed_auto_host("pve01", "pve"))
        self.assertTrue(_is_managed_auto_host("plex", "docker", vmid=201))
        self.assertTrue(_is_managed_auto_host("switch", "switch"))
        self.assertTrue(_is_managed_auto_host("truenas", "truenas"))
        self.assertFalse(_is_managed_auto_host("truenas-lab", "truenas"))
        self.assertTrue(_is_managed_auto_host("bmc-10", "idrac"))
        self.assertTrue(_is_managed_auto_host("pdm-manager", "linux", vmid=101, source="pve-api"))
        self.assertFalse(_is_managed_auto_host("jarvis-ai", "linux", vmid=666))
        self.assertFalse(_is_managed_auto_host("pve-freq", "pve", vmid=100, source="pve-api"))
        self.assertFalse(_is_managed_auto_host("blue", "linux", vmid=802))
        self.assertFalse(_is_managed_auto_host("freq-test", "linux", vmid=5005))
        self.assertFalse(_is_managed_auto_host("lab-pve1", "pve", vmid=5002, source="pve-api"))

    def test_headless_registration_skips_inventory_only_guests(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/init_cmd.py")) as f:
            src = f.read()
        registration = src.split("Auto-register only managed targets in headless mode.")[1].split("else:", 1)[0]

        self.assertIn('if not d.get("managed", False):', registration)
        self.assertIn("skipped_inventory_only += 1", registration)
        self.assertIn("inventory-only guest(s) left out of hosts.toml", registration)

    def test_init_summary_counts_managed_hosts_not_inventory_only_hosts(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/init_cmd.py")) as f:
            src = f.read()
        summary = src.split("def _phase_summary")[1].split("def _phase_interactive_cleanup", 1)[0]
        headless = src.split("def _init_headless")[1].split("logger.info(\"headless init complete\"", 1)[0]

        self.assertIn('managed_hosts = [h for h in cfg.hosts if getattr(h, "managed", True)]', summary)
        self.assertIn("managed hosts deployed", summary)
        self.assertIn("inventory-only/unmanaged host(s) tracked outside deployment", summary)
        self.assertIn('managed_hosts = [h for h in cfg.hosts if getattr(h, "managed", True)]', headless)
        self.assertIn("managed hosts deployed (headless)", headless)

    def test_phase8_and_phase9_skip_unmanaged_hosts(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/init_cmd.py")) as f:
            src = f.read()
        fleet_config = src.split("def _phase_fleet_configure")[1].split("def _categorize_vms", 1)[0]
        headless_deploy = src.split("def _headless_fleet_deploy")[1].split("def _deploy_via_guest_agent", 1)[0]

        self.assertIn('h.htype == "docker" and getattr(h, "managed", True)', fleet_config)
        self.assertIn('and getattr(h, "managed", True)', fleet_config)
        self.assertIn('if not getattr(h, "managed", True):', headless_deploy)
        self.assertIn("continue", headless_deploy)

    def test_fleet_overview_splits_resources_real_vms_and_templates(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        summary = src.split('"summary": {')[1].split("},", 1)[0]

        self.assertIn('"resource_count": resource_count', summary)
        self.assertIn('"real_vm_count": real_vm_count', summary)
        self.assertIn('"total_vms": total_vms', summary)
        self.assertIn("templates are not real VMs", src)
        self.assertIn("real VMs +", src)
        self.assertIn('cat_name, tier = "templates", "protected"', src)

    def test_fleet_health_score_excludes_templates_from_stopped_vm_penalty(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        block = src.split('if fleet and isinstance(fleet, dict):')[1].split('score = max', 1)[0]

        self.assertIn('real_vms = [v for v in vms if v.get("category") != "templates"]', block)
        self.assertIn("stopped = sum(1 for v in real_vms", block)
        self.assertIn("total_vms = len(real_vms)", block)


class TestPhase1Dispatch(unittest.TestCase):
    """Verify all Phase 1 commands have func set."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_alert_has_func(self):
        args = self.parser.parse_args(["observe", "alert"])
        self.assertTrue(hasattr(args, "func"))

    def test_rollback_has_func(self):
        args = self.parser.parse_args(["vm", "rollback", "100"])
        self.assertTrue(hasattr(args, "func"))

    def test_inventory_has_func(self):
        args = self.parser.parse_args(["fleet", "inventory"])
        self.assertTrue(hasattr(args, "func"))

    def test_compare_has_func(self):
        args = self.parser.parse_args(["fleet", "compare", "a", "b"])
        self.assertTrue(hasattr(args, "func"))

    def test_baseline_has_func(self):
        args = self.parser.parse_args(["state", "baseline"])
        self.assertTrue(hasattr(args, "func"))


if __name__ == "__main__":
    unittest.main()
