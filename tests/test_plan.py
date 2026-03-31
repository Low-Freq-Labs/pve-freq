"""Tests for freq plan / freq apply — declarative fleet management."""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from io import StringIO

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPlanParser(unittest.TestCase):
    """Test plan TOML loading and validation."""

    def test_load_plan_basic(self):
        from freq.modules.plan import _load_plan
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as f:
            f.write(b'[[vm]]\nname = "web-01"\ncores = 4\nram = 4096\ndisk = 64\n')
            f.flush()
            vms = _load_plan(f.name)
        os.unlink(f.name)
        self.assertEqual(len(vms), 1)
        self.assertEqual(vms[0]["name"], "web-01")
        self.assertEqual(vms[0]["cores"], 4)
        self.assertEqual(vms[0]["ram"], 4096)
        self.assertEqual(vms[0]["disk"], 64)

    def test_load_plan_defaults(self):
        from freq.modules.plan import _load_plan
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as f:
            f.write(b'[[vm]]\nname = "minimal"\n')
            f.flush()
            vms = _load_plan(f.name)
        os.unlink(f.name)
        self.assertEqual(vms[0]["cores"], 2)
        self.assertEqual(vms[0]["ram"], 2048)
        self.assertEqual(vms[0]["disk"], 32)
        self.assertTrue(vms[0]["start"])

    def test_load_plan_multiple_vms(self):
        from freq.modules.plan import _load_plan
        content = b'[[vm]]\nname = "a"\ncores = 2\n\n[[vm]]\nname = "b"\ncores = 8\n\n[[vm]]\nname = "c"\ncores = 16\n'
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as f:
            f.write(content)
            f.flush()
            vms = _load_plan(f.name)
        os.unlink(f.name)
        self.assertEqual(len(vms), 3)
        self.assertEqual(vms[0]["name"], "a")
        self.assertEqual(vms[2]["cores"], 16)

    def test_load_plan_missing_name_skipped(self):
        from freq.modules.plan import _load_plan
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as f:
            f.write(b'[[vm]]\ncores = 4\n\n[[vm]]\nname = "valid"\n')
            f.flush()
            vms = _load_plan(f.name)
        os.unlink(f.name)
        self.assertEqual(len(vms), 1)
        self.assertEqual(vms[0]["name"], "valid")

    def test_load_plan_file_not_found(self):
        from freq.modules.plan import _load_plan
        vms = _load_plan("/nonexistent/plan.toml")
        self.assertEqual(vms, [])

    def test_load_plan_with_all_fields(self):
        from freq.modules.plan import _load_plan
        content = (
            b'[[vm]]\n'
            b'name = "full-spec"\n'
            b'cores = 8\n'
            b'ram = 16384\n'
            b'disk = 256\n'
            b'node = "pve01"\n'
            b'image = "debian-13"\n'
            b'vlan = "mgmt"\n'
            b'ip = "10.0.0.50/24"\n'
            b'start = false\n'
            b'tags = "prod,web"\n'
            b'profile = "prod"\n'
        )
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".toml", delete=False) as f:
            f.write(content)
            f.flush()
            vms = _load_plan(f.name)
        os.unlink(f.name)
        self.assertEqual(vms[0]["node"], "pve01")
        self.assertEqual(vms[0]["image"], "debian-13")
        self.assertFalse(vms[0]["start"])
        self.assertEqual(vms[0]["tags"], "prod,web")


class TestPlanDiff(unittest.TestCase):
    """Test diff computation between desired and current state."""

    def test_all_create(self):
        from freq.modules.plan import _compute_diff
        desired = [
            {"name": "new-01", "cores": 4, "ram": 4096, "disk": 64},
            {"name": "new-02", "cores": 2, "ram": 2048, "disk": 32},
        ]
        current = []
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["create"]), 2)
        self.assertEqual(len(diff["resize"]), 0)
        self.assertEqual(len(diff["unchanged"]), 0)

    def test_all_unchanged(self):
        from freq.modules.plan import _compute_diff
        desired = [
            {"name": "vm-01", "cores": 4, "ram": 4096, "disk": 64},
        ]
        current = [
            {"vmid": 100, "name": "vm-01", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01"},
        ]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["create"]), 0)
        self.assertEqual(len(diff["resize"]), 0)
        self.assertEqual(len(diff["unchanged"]), 1)

    def test_resize_cores(self):
        from freq.modules.plan import _compute_diff
        desired = [{"name": "vm-01", "cores": 8, "ram": 4096, "disk": 64}]
        current = [{"vmid": 100, "name": "vm-01", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01"}]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["resize"]), 1)
        self.assertIn("cores", diff["resize"][0]["changes"])
        self.assertEqual(diff["resize"][0]["changes"]["cores"]["from"], 4)
        self.assertEqual(diff["resize"][0]["changes"]["cores"]["to"], 8)

    def test_resize_ram(self):
        from freq.modules.plan import _compute_diff
        desired = [{"name": "vm-01", "cores": 4, "ram": 8192, "disk": 64}]
        current = [{"vmid": 100, "name": "vm-01", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01"}]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["resize"]), 1)
        self.assertIn("ram", diff["resize"][0]["changes"])

    def test_resize_disk_grow_only(self):
        from freq.modules.plan import _compute_diff
        # Disk can only grow — shrink should be ignored
        desired = [{"name": "vm-01", "cores": 4, "ram": 4096, "disk": 32}]
        current = [{"vmid": 100, "name": "vm-01", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01"}]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["resize"]), 0)  # No shrink

    def test_disk_expand(self):
        from freq.modules.plan import _compute_diff
        desired = [{"name": "vm-01", "cores": 4, "ram": 4096, "disk": 128}]
        current = [{"vmid": 100, "name": "vm-01", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01"}]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["resize"]), 1)
        self.assertIn("disk", diff["resize"][0]["changes"])

    def test_unmanaged_vms(self):
        from freq.modules.plan import _compute_diff
        desired = [{"name": "managed-01", "cores": 2, "ram": 2048, "disk": 32}]
        current = [
            {"vmid": 100, "name": "managed-01", "cores": 2, "ram": 2048, "disk": 32, "node": "pve01"},
            {"vmid": 200, "name": "other-vm", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01"},
        ]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["unmanaged"]), 1)
        self.assertEqual(diff["unmanaged"][0]["name"], "other-vm")

    def test_mixed_operations(self):
        from freq.modules.plan import _compute_diff
        desired = [
            {"name": "keep", "cores": 2, "ram": 2048, "disk": 32},
            {"name": "grow", "cores": 8, "ram": 2048, "disk": 32},
            {"name": "brand-new", "cores": 4, "ram": 4096, "disk": 64},
        ]
        current = [
            {"vmid": 100, "name": "keep", "cores": 2, "ram": 2048, "disk": 32, "node": "pve01"},
            {"vmid": 101, "name": "grow", "cores": 4, "ram": 2048, "disk": 32, "node": "pve01"},
            {"vmid": 200, "name": "orphan", "cores": 1, "ram": 512, "disk": 8, "node": "pve01"},
        ]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["create"]), 1)
        self.assertEqual(diff["create"][0]["name"], "brand-new")
        self.assertEqual(len(diff["resize"]), 1)
        self.assertEqual(diff["resize"][0]["vm"]["name"], "grow")
        self.assertEqual(len(diff["unchanged"]), 1)
        self.assertEqual(len(diff["unmanaged"]), 1)

    def test_empty_plan_empty_cluster(self):
        from freq.modules.plan import _compute_diff
        diff = _compute_diff([], [])
        self.assertEqual(len(diff["create"]), 0)
        self.assertEqual(len(diff["resize"]), 0)
        self.assertEqual(len(diff["unchanged"]), 0)
        self.assertEqual(len(diff["unmanaged"]), 0)

    def test_multiple_changes_same_vm(self):
        from freq.modules.plan import _compute_diff
        desired = [{"name": "vm-01", "cores": 8, "ram": 8192, "disk": 128}]
        current = [{"vmid": 100, "name": "vm-01", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01"}]
        diff = _compute_diff(desired, current)
        self.assertEqual(len(diff["resize"]), 1)
        changes = diff["resize"][0]["changes"]
        self.assertIn("cores", changes)
        self.assertIn("ram", changes)
        self.assertIn("disk", changes)


class TestPlanCLI(unittest.TestCase):
    """Test CLI registration for plan/apply commands."""

    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()

    def test_plan_registered(self):
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertIn("plan", registered)

    def test_apply_registered(self):
        import argparse
        registered = set()
        for action in self.parser._subparsers._actions:
            if isinstance(action, argparse._SubParsersAction):
                registered.update(action.choices.keys())
        self.assertIn("apply", registered)

    def test_plan_file_arg(self):
        args = self.parser.parse_args(["plan", "--file", "/tmp/my-plan.toml"])
        self.assertEqual(args.file, "/tmp/my-plan.toml")

    def test_plan_default(self):
        args = self.parser.parse_args(["plan"])
        self.assertTrue(hasattr(args, "func"))

    def test_apply_dry_run(self):
        args = self.parser.parse_args(["apply", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_apply_yes_flag(self):
        args = self.parser.parse_args(["apply", "--yes"])
        self.assertTrue(args.yes)


class TestPlanRender(unittest.TestCase):
    """Test plan output rendering."""

    def test_render_no_changes(self):
        from freq.modules.plan import _render_plan
        diff = {"create": [], "resize": [], "unchanged": [{"desired": {}, "current": {}}], "unmanaged": []}
        old = sys.stdout
        sys.stdout = StringIO()
        _render_plan(diff)
        output = sys.stdout.getvalue()
        sys.stdout = old
        self.assertIn("No changes", output)

    def test_render_creates(self):
        from freq.modules.plan import _render_plan
        diff = {
            "create": [{"name": "new-vm", "cores": 4, "ram": 4096, "disk": 64, "node": "pve01", "image": "debian-13", "ip": ""}],
            "resize": [],
            "unchanged": [],
            "unmanaged": [],
        }
        old = sys.stdout
        sys.stdout = StringIO()
        _render_plan(diff)
        output = sys.stdout.getvalue()
        sys.stdout = old
        self.assertIn("new-vm", output)
        self.assertIn("1 to create", output)

    def test_render_resizes(self):
        from freq.modules.plan import _render_plan
        diff = {
            "create": [],
            "resize": [{"vm": {"name": "grow-vm"}, "changes": {"cores": {"from": 2, "to": 8}}}],
            "unchanged": [],
            "unmanaged": [],
        }
        old = sys.stdout
        sys.stdout = StringIO()
        _render_plan(diff)
        output = sys.stdout.getvalue()
        sys.stdout = old
        self.assertIn("grow-vm", output)
        self.assertIn("1 to resize", output)


class TestPlanCache(unittest.TestCase):
    """Test plan cache save/load."""

    def test_save_plan_cache(self):
        from freq.modules.plan import _save_plan_cache
        from unittest.mock import MagicMock
        cfg = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            cfg.data_dir = td
            diff = {
                "create": [{"name": "a"}],
                "resize": [],
                "unchanged": [{"desired": {}}],
                "unmanaged": [],
            }
            _save_plan_cache(cfg, diff, "/tmp/test.toml")
            cache_path = os.path.join(td, "cache", "last_plan.json")
            self.assertTrue(os.path.isfile(cache_path))
            with open(cache_path) as f:
                data = json.load(f)
            self.assertEqual(data["create_count"], 1)
            self.assertEqual(data["unchanged_count"], 1)


if __name__ == "__main__":
    unittest.main()
