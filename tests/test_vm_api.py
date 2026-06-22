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
from freq.api import fleet as fleet_api
from freq.core.types import CmdResult


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
            pve_storage = {"pve01": {"pool": "local-zfs", "type": "SSD"}}
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
            vm_default_cores = 2
            vm_default_ram = 2048
            vm_default_disk = 32
            vm_cpu = "x86-64-v2-AES"
            vlans = []
            distros = []
            template_profiles = {}

            class FB:
                categories = {
                    "lab": {"range_start": 5000, "range_end": 7999, "tier": "admin"},
                    "templates": {"vmids": [9000], "tier": "probe"},
                }
                tiers = {
                    "probe": ["view"],
                    "admin": ["view", "start", "stop", "restart", "snapshot", "destroy", "clone", "resize", "migrate", "configure"],
                }

                def categorize(self, vmid):
                    for name, cat in self.categories.items():
                        if vmid in cat.get("vmids", []):
                            return name, cat.get("tier", "probe")
                        start = cat.get("range_start")
                        end = cat.get("range_end")
                        if start is not None and end is not None and start <= vmid <= end:
                            return name, cat.get("tier", "probe")
                    return "unknown", "probe"

                def can_action(self, vmid, action):
                    _, tier = self.categorize(vmid)
                    return action in self.tiers.get(tier, ["view"])

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
    @patch("freq.api.vm._refresh_fleet_overview_after_mutation")
    def test_vm_create_honors_selected_node(self, _mock_refresh, mock_load, _mock_role):
        cfg = self._cfg()
        cfg.pve_nodes = ["10.0.0.1", "10.0.0.2"]
        cfg.pve_node_names = ["pve01", "pve02"]
        mock_load.return_value = cfg
        commands = []

        def fake_pve(_cfg, node_ip, command, timeout=60):
            commands.append((node_ip, command))
            if command == "pvesh get /cluster/nextid":
                return ("5005", True)
            if command.startswith("qm create"):
                return ("", True)
            return ("[]", True)

        with patch("freq.api.vm._find_reachable_node", return_value="10.0.0.1"), \
             patch("freq.api.vm._pve_cmd", side_effect=fake_pve):
            handler = _Handler("/api/vm/create?name=testvm&node=pve02")
            vm_api.handle_vm_create(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["node"], "pve02")
        self.assertIn(("10.0.0.2", "pvesh get /cluster/nextid"), commands)
        self.assertTrue(any(node == "10.0.0.2" and cmd.startswith("qm create 5005") for node, cmd in commands))

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
    @patch("freq.api.vm._check_vm_permission", return_value=(True, ""))
    @patch("freq.api.vm.ssh_single")
    @patch("freq.api.vm._pve_cmd")
    def test_change_id_preserves_vm_name_on_clone(
        self, mock_pve_cmd, mock_ssh, _mock_permission, _mock_find_node, mock_load, _mock_role
    ):
        mock_load.return_value = self._cfg()
        commands = []

        def fake_pve(_cfg, _node_ip, command, timeout=60):
            commands.append(command)
            if command.startswith("qm config"):
                return ("name: e2e-freq-controls-6000-renamed\n", True)
            return ("", True)

        def fake_ssh(**kwargs):
            commands.append(kwargs["command"])
            return CmdResult(returncode=0, stdout="stopped", stderr="")

        mock_pve_cmd.side_effect = fake_pve
        mock_ssh.side_effect = fake_ssh
        handler = _Handler("/api/vm/change-id?vmid=6000&newid=6001")

        vm_api.handle_vm_change_id(handler)

        self.assertEqual(handler.status, 200)
        self.assertIn(
            "sudo qm clone 6000 6001 --full --name e2e-freq-controls-6000-renamed",
            commands,
        )
        self.assertIn("sudo qm destroy 6000 --purge", commands)

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
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._pve_cmd")
    def test_clone_allows_template_source_into_lab_target(self, mock_pve_cmd, _mock_find_node, mock_load, _mock_role):
        mock_load.return_value = self._cfg()
        commands = []

        def fake_pve(_cfg, _node_ip, command, timeout=60):
            commands.append(command)
            return ("", True)

        mock_pve_cmd.side_effect = fake_pve
        handler = _Handler(
            "/api/vm/clone?vmid=9000&newid=7000&name=freq-lifecycle-7000&target_node=pve03&storage=os-drive-ssd"
        )

        vm_api.handle_vm_clone(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["new_vmid"], 7000)
        self.assertIn(
            "qm clone 9000 7000 --name freq-lifecycle-7000 --target pve03 --storage os-drive-ssd --full 1",
            commands,
        )

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._pve_cmd")
    def test_clone_blocks_template_source_into_unmanaged_target(
        self, mock_pve_cmd, _mock_find_node, mock_load, _mock_role
    ):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/clone?vmid=9000&newid=101&name=bad-target")

        vm_api.handle_vm_clone(handler)

        self.assertEqual(handler.status, 403)
        data = _json(handler)
        self.assertIn("Target VMID blocked", data["error"])
        mock_pve_cmd.assert_not_called()

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._pve_cmd")
    def test_add_disk_uses_configured_node_storage_not_local_lvm(
        self, mock_pve_cmd, _mock_find_node, mock_load, _mock_role
    ):
        mock_load.return_value = self._cfg()
        commands = []

        def fake_pve(_cfg, _node_ip, command, timeout=60):
            commands.append(command)
            if command.startswith("qm config"):
                return ("", True)
            return ("", True)

        mock_pve_cmd.side_effect = fake_pve
        handler = _Handler("/api/vm/add-disk?vmid=7000&size=1G")

        with patch("freq.api.vm._check_vm_permission", return_value=(True, "")):
            vm_api.handle_vm_add_disk(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["storage"], "local-zfs")
        self.assertIn("qm set 7000 --scsi0 local-zfs:1", commands)

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._pve_cmd")
    def test_add_disk_inherits_existing_vm_disk_storage_when_unconfigured(
        self, mock_pve_cmd, _mock_find_node, mock_load, _mock_role
    ):
        cfg = self._cfg()
        cfg.pve_storage = {}
        mock_load.return_value = cfg
        commands = []

        def fake_pve(_cfg, _node_ip, command, timeout=60):
            commands.append(command)
            if command.startswith("qm config"):
                return ("scsi0: os-drive-ssd:vm-7000-disk-0,size=3G\n", True)
            return ("", True)

        mock_pve_cmd.side_effect = fake_pve
        handler = _Handler("/api/vm/add-disk?vmid=7000&size=1G")

        with patch("freq.api.vm._check_vm_permission", return_value=(True, "")):
            vm_api.handle_vm_add_disk(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["storage"], "os-drive-ssd")
        self.assertIn("qm set 7000 --scsi1 os-drive-ssd:1", commands)

    @patch("freq.api.vm._check_session_role", return_value=("operator", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._check_vm_permission", return_value=(True, ""))
    @patch("freq.api.vm._refresh_fleet_overview_after_mutation")
    @patch("freq.api.vm._pve_cmd")
    def test_update_nic_preserves_existing_model_mac(
        self, mock_pve_cmd, _mock_refresh, _mock_permission, _mock_find_node, mock_load, _mock_role
    ):
        mock_load.return_value = self._cfg()
        commands = []

        def fake_pve(_cfg, _node_ip, command, timeout=60):
            commands.append(command)
            if command.startswith("qm config"):
                return ("net1: virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,tag=10,firewall=1\n", True)
            return ("", True)

        mock_pve_cmd.side_effect = fake_pve
        handler = _Handler("/api/vm/update-nic?vmid=7000&nic=1&bridge=vmbr1&vlan=20&ip=192.168.20.44/24&gw=192.168.20.1")

        vm_api.handle_vm_update_nic(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertTrue(any("virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1,tag=20,firewall=1" in cmd for cmd in commands))
        self.assertTrue(any("ip=192.168.20.44/24,gw=192.168.20.1" in cmd for cmd in commands))

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    @patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.1")
    @patch("freq.api.vm._check_vm_permission", return_value=(True, ""))
    @patch("freq.api.vm._refresh_fleet_overview_after_mutation")
    @patch("freq.api.vm._pve_cmd")
    def test_delete_nic_deletes_selected_net_and_ipconfig(
        self, mock_pve_cmd, _mock_refresh, _mock_permission, _mock_find_node, mock_load, _mock_role
    ):
        mock_load.return_value = self._cfg()
        commands = []

        def fake_pve(_cfg, _node_ip, command, timeout=60):
            commands.append(command)
            if command.startswith("qm config"):
                return ("net1: virtio,bridge=vmbr0\nipconfig1: ip=192.168.10.55/24\n", True)
            return ("", True)

        mock_pve_cmd.side_effect = fake_pve
        handler = _Handler("/api/vm/delete-nic?vmid=7000&nic=1")

        vm_api.handle_vm_delete_nic(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["deleted"], ["net1", "ipconfig1"])
        self.assertIn("qm set 7000 --delete net1", commands)
        self.assertIn("qm set 7000 --delete ipconfig1", commands)

    def test_snapshot_parser_strips_proxmox_tree_markers(self):
        raw = (
            "`-> e2e-1781340291951           2026-06-13 03:44:52     no-description\n"
            " `-> current                                            You are here!\n"
        )

        self.assertEqual(vm_api._parse_qm_snapshot_names(raw), ["e2e-1781340291951"])

    @patch("freq.api.vm.load_config")
    def test_wizard_defaults_expose_configured_storage(self, mock_load):
        mock_load.return_value = self._cfg()
        handler = _Handler("/api/vm/wizard-defaults", method="GET")

        vm_api.handle_vm_wizard_defaults(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertEqual(data["defaults"]["storage"], "local-zfs")

    @patch("freq.api.fleet._check_session_role", return_value=("admin", None))
    @patch("freq.api.fleet.load_config")
    @patch("freq.api.fleet.ssh_run_many")
    def test_exec_accepts_direct_guest_ip_for_dashboard_vm_tools(
        self, mock_ssh_many, mock_load, _mock_role
    ):
        cfg = self._cfg()
        cfg.hosts = []
        mock_load.return_value = cfg
        mock_ssh_many.return_value = {
            "10.25.255.222": CmdResult(stdout="ok\n", stderr="", returncode=0)
        }
        handler = _Handler("/api/exec?target=10.25.255.222&cmd=hostname")

        fleet_api.handle_exec(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertEqual(data["results"][0]["host"], "10.25.255.222")
        self.assertTrue(data["results"][0]["ok"])
        host_arg = mock_ssh_many.call_args.kwargs["hosts"][0]
        self.assertEqual(host_arg.ip, "10.25.255.222")
        self.assertEqual(host_arg.htype, "linux")

    @patch("freq.api.fleet.load_config")
    @patch("freq.api.fleet.ssh_single")
    def test_log_accepts_direct_guest_ip_for_dashboard_vm_tools(
        self, mock_ssh, mock_load
    ):
        cfg = self._cfg()
        cfg.hosts = []
        mock_load.return_value = cfg
        mock_ssh.return_value = CmdResult(stdout="log line\n", stderr="", returncode=0)
        handler = _Handler("/api/log?target=10.25.255.222&lines=5", method="GET")

        fleet_api.handle_log(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertEqual(data["ip"], "10.25.255.222")
        self.assertEqual(data["lines"], ["log line", ""])
        self.assertEqual(mock_ssh.call_args.kwargs["host"], "10.25.255.222")

    @patch("freq.api.fleet.load_config")
    @patch("freq.api.fleet.ssh_single")
    def test_diagnose_accepts_direct_guest_ip_for_dashboard_vm_tools(
        self, mock_ssh, mock_load
    ):
        cfg = self._cfg()
        cfg.hosts = []
        mock_load.return_value = cfg
        mock_ssh.return_value = CmdResult(stdout="ok\n", stderr="", returncode=0)
        handler = _Handler("/api/diagnose?target=10.25.255.222", method="GET")

        fleet_api.handle_diagnose(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertEqual(data["ip"], "10.25.255.222")
        self.assertIn("uptime", data["checks"])
        self.assertEqual(mock_ssh.call_args.kwargs["host"], "10.25.255.222")

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
