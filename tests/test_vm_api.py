"""Targeted VM API trust tests.

These cover runtime paths that must never turn malformed cluster data or
bad operator input into silent fallback or 500s.
"""

import io
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.api import vm as vm_api


class _Handler:
    def __init__(self, path="/api/test", method="POST"):
        self.path = path
        self.command = method
        self.headers = {}
        self.wfile = io.BytesIO()
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, *args):
        pass

    def end_headers(self):
        pass


def _json(handler):
    handler.wfile.seek(0)
    return json.loads(handler.wfile.read().decode())


class TestVmApiTrust(unittest.TestCase):
    def _cfg(self):
        class Cfg:
            pve_nodes = ["10.0.0.1"]
            pve_node_names = ["pve01"]
            ssh_key_path = "/tmp/fake"
            ssh_connect_timeout = 3
            nic_bridge = "vmbr0"
            vm_cpu = "x86-64-v2-AES"
            vm_machine = "q35"
            vm_scsihw = "virtio-scsi-single"
            pve_api_token_id = ""
            pve_api_token_secret = ""
            protected_vmids = []
            protected_ranges = []

            class FB:
                categories = {"lab": {"range_start": 5000}}

            fleet_boundaries = FB()

        return Cfg()

    def test_parse_next_vmid_rejects_garbage(self):
        self.assertEqual(vm_api._parse_next_vmid("abc"), 0)
        self.assertEqual(vm_api._parse_next_vmid(""), 0)
        self.assertEqual(vm_api._parse_next_vmid("123"), 123)

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    def test_vm_create_returns_502_on_bad_nextid(self, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/create?name=testvm")

        with patch("freq.api.vm._find_reachable_node", return_value="10.0.0.1"), \
             patch("freq.api.vm._pve_cmd", return_value=("garbage", True)):
            vm_api.handle_vm_create(handler)

        self.assertEqual(handler.status, 502)
        data = _json(handler)
        self.assertIn("Invalid next VMID", data["error"])

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    def test_vm_create_requires_name_with_400(self, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/create")

        vm_api.handle_vm_create(handler)

        self.assertEqual(handler.status, 400)
        data = _json(handler)
        self.assertEqual(data["error"], "Name required")

    @patch("freq.api.vm._check_session_role", return_value=("operator", None))
    @patch("freq.api.vm.load_config")
    def test_vm_power_rejects_invalid_action(self, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/power?vmid=101&action=explode")

        vm_api.handle_vm_power(handler)

        self.assertEqual(handler.status, 400)
        data = _json(handler)
        self.assertEqual(data["error"], "Invalid action: explode")

    @patch("freq.api.vm._check_session_role", return_value=("operator", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._check_vm_permission", return_value=(True, ""))
    @patch("freq.api.vm._pve_cmd", return_value=("qm failed", False))
    def test_vm_power_backend_failure_returns_502(
        self, _mock_pve_cmd, _mock_permission, _mock_find_node, mock_load, _mock_role
    ):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/power?vmid=101&action=start")

        vm_api.handle_vm_power(handler)

        self.assertEqual(handler.status, 502)
        data = _json(handler)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "qm failed")

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._pve_cmd")
    def test_rollback_returns_404_when_no_snapshots_exist(self, mock_pve_cmd, _mock_find_node, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/rollback?vmid=101")
        mock_pve_cmd.return_value = ("", True)

        vm_api.handle_rollback(handler)

        self.assertEqual(handler.status, 404)
        data = _json(handler)
        self.assertIn("No snapshots found", data["error"])

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._pve_cmd")
    def test_rollback_returns_404_when_named_snapshot_missing(self, mock_pve_cmd, _mock_find_node, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/rollback?vmid=101&name=missing")
        mock_pve_cmd.return_value = ("snap1 2026-01-01 00:00:00\n", True)

        vm_api.handle_rollback(handler)

        self.assertEqual(handler.status, 404)
        data = _json(handler)
        self.assertIn("not found", data["error"])

    @patch("freq.api.vm._check_session_role", return_value=("operator", None))
    @patch("freq.api.vm.load_config")
    def test_snapshot_invalid_name_returns_400(self, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/snapshot?vmid=101&name=bad/name")

        vm_api.handle_vm_snapshot(handler)

        self.assertEqual(handler.status, 400)
        data = _json(handler)
        self.assertIn("Invalid snapshot name", data["error"])

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    def test_destroy_protected_vm_returns_403(self, mock_load, _mock_role):
        cfg = self._cfg()
        cfg.protected_vmids = [101]
        mock_load.return_value = cfg
        handler = _Handler("/api/vm/destroy?vmid=101")

        with patch("freq.api.vm._check_vm_permission", return_value=(True, "")), \
             patch("freq.api.vm.get_vm_tags", return_value=[]):
            vm_api.handle_vm_destroy(handler)

        self.assertEqual(handler.status, 403)
        data = _json(handler)
        self.assertIn("PROTECTED", data["error"])

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    def test_migrate_snapshots_block_returns_409(self, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/migrate?vmid=101&target_node=pve02")

        fake_vm_module = type(
            "FakeVmModule",
            (),
            {
                "_find_vm_node": staticmethod(lambda cfg, vmid: "10.0.0.1"),
                "_find_best_local_storage": staticmethod(lambda cfg, source_ip, target_node: "local-lvm"),
                "_check_snapshots": staticmethod(lambda cfg, source_ip, vmid: ["snap1"]),
                "_delete_snapshots": staticmethod(lambda cfg, source_ip, vmid, snaps: None),
            },
        )

        with patch("freq.api.vm._check_vm_permission", return_value=(True, "")), \
             patch.dict(sys.modules, {"freq.modules.vm": fake_vm_module}):
            vm_api.handle_vm_migrate(handler)

        self.assertEqual(handler.status, 409)
        data = _json(handler)
        self.assertEqual(data["error"], "snapshots_block_migration")


if __name__ == "__main__":
    unittest.main()
