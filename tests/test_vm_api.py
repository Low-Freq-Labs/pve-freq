"""Targeted VM API trust tests.

These cover runtime paths that must never turn malformed cluster data or
bad operator input into silent fallback or 500s.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.api import vm as vm_api
from freq.api import fleet as fleet_api
from freq.core.types import CmdResult


class _Handler:
    def __init__(self, path="/api/test", method="POST", body=None):
        self.path = path
        self.command = method
        raw = b""
        if body is not None:
            raw = json.dumps(body).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
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
            conf_dir = "/tmp"
            ssh_key_path = "/tmp/fake"
            ssh_connect_timeout = 3
            nic_bridge = "vmbr0"
            nic_profiles = {}
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
            vm_gateway = "10.25.255.1"
            vm_nameserver = "10.25.255.1"

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
    @patch("freq.api.vm._get_fleet_vms", return_value=[])
    @patch("freq.api.vm.load_config")
    def test_vm_create_options_exposes_first_class_contract(self, mock_load, _mock_vms, _mock_role):
        from freq.core.types import VLAN, Distro

        cfg = self._cfg()
        cfg.vlans = [VLAN(id=255, name="prod", subnet="10.25.255.0/24", prefix="10.25.255", gateway="10.25.255.1")]
        cfg.distros = [Distro(key="debian12", name="Debian 12", url="", filename="", family="debian")]
        mock_load.return_value = cfg
        handler = _Handler("/api/vm/create/options", method="GET")

        vm_api.handle_vm_create_options(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertIn("nodes", data)
        self.assertIn("storage", data)
        self.assertIn("templates", data)
        self.assertIn("vlans", data)
        self.assertIn("network_profiles", data)
        self.assertEqual(data["schema_version"], 3)
        self.assertEqual(data["network_policy"]["primary_input"], "network_profile")
        self.assertEqual(data["network_policy"]["bridge_input"], "advanced")
        self.assertEqual(data["vlans"][0]["gateway"], "10.25.255.1")
        self.assertTrue(data["vlans"][0]["gateway_in_subnet"])
        self.assertEqual(data["cpu"]["default"], cfg.vm_cpu)
        self.assertEqual(data["lifecycle"]["start_on_boot_default"], False)
        self.assertIn("start_on_boot", data["lifecycle"]["accepted_keys"])

    def test_vm_create_options_exposes_configured_network_profiles(self):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.nic_profiles = {
            "tenant-prod": {
                "name": "Tenant Prod",
                "vlan": 25,
                "bridge": "vmbr25",
                "purpose": "storage",
                "gateway_role": "none",
            }
        }
        cfg.vlans = [VLAN(id=25, name="storage", subnet="10.25.25.0/24", prefix="10.25.25", gateway="10.25.25.1")]

        with patch("freq.api.vm._get_fleet_vms", return_value=[]):
            payload = vm_api._vm_create_options_payload(cfg)

        profile = next(row for row in payload["network_profiles"] if row["id"] == "tenant-prod")
        self.assertEqual(profile["bridge"], "vmbr25")
        self.assertEqual(profile["vlan_id"], 25)
        self.assertEqual(profile["gateway_role"], "none")

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    def test_vm_network_profiles_endpoint_persists_settings_mapping(self, mock_load, _mock_role):
        from freq.core.config import load_network_profiles
        from freq.core.types import VLAN

        cfg = self._cfg()
        with tempfile.TemporaryDirectory() as tmp:
            cfg.conf_dir = tmp
            cfg.vlans = [VLAN(id=66, name="dirty", subnet="10.25.66.0/24", prefix="10.25.66", gateway="10.25.66.1")]
            mock_load.return_value = cfg
            handler = _Handler(
                "/api/vm/network-profiles",
                body={
                    "profiles": [
                        {
                            "id": "dirty-public",
                            "name": "Dirty / Public",
                            "vlan": 66,
                            "bridge": "vmbr0",
                            "purpose": "dirty",
                            "gateway_role": "default",
                        }
                    ]
                },
            )

            vm_api.handle_vm_network_profiles(handler)

            self.assertEqual(handler.status, 200)
            data = _json(handler)
            self.assertTrue(data["ok"])
            saved = load_network_profiles(os.path.join(tmp, "network-profiles.toml"))
            self.assertEqual(saved["dirty-public"]["bridge"], "vmbr0")
            self.assertEqual(saved["dirty-public"]["vlan"], 66)

    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm.load_config")
    def test_vm_network_profiles_endpoint_rejects_invalid_bridge(self, mock_load, _mock_role):
        cfg = self._cfg()
        mock_load.return_value = cfg
        handler = _Handler(
            "/api/vm/network-profiles",
            body={"profiles": [{"id": "bad", "vlan": 10, "bridge": "vmbr0;rm"}]},
        )

        vm_api.handle_vm_network_profiles(handler)

        self.assertEqual(handler.status, 400)
        data = _json(handler)
        self.assertFalse(data["ok"])
        self.assertTrue(any("valid bridge" in err for err in data["errors"]))

    @patch("freq.api.vm._candidate_ip_available", return_value=True)
    def test_vm_create_plan_derives_bridge_from_network_profile(self, _mock_ip):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.nic_profiles = {
            "dirty-public": {
                "name": "Dirty / Public",
                "vlan": 66,
                "bridge": "vmbr66",
                "purpose": "public-egress",
                "gateway_role": "default",
            }
        }
        cfg.vlans = [VLAN(id=66, name="dirty", subnet="10.25.66.0/24", prefix="10.25.66", gateway="10.25.66.1")]

        result = vm_api._vm_create_plan(
            cfg,
            {"name": "new-vm", "node": "pve01", "network_profile": "dirty-public", "ip": "auto"},
        )

        self.assertTrue(result["ok"], result)
        net = result["plan"]["network"]
        self.assertEqual(net["network_profile"], "dirty-public")
        self.assertEqual(net["bridge"], "vmbr66")
        self.assertEqual(net["bridge_source"], "profile")
        self.assertEqual(net["tag"], "66")

    @patch("freq.api.vm._candidate_ip_available", return_value=True)
    @patch("freq.api.vm._check_session_role", return_value=("operator", None))
    @patch("freq.api.vm._get_fleet_vms", return_value=[])
    @patch("freq.api.vm.load_config")
    def test_vm_create_plan_derives_static_ip_and_gateway_from_vlan(self, mock_load, _mock_vms, _mock_role, _mock_ip):
        from freq.core.types import Host, VLAN

        cfg = self._cfg()
        cfg.hosts = [Host(ip="10.25.255.10", label="used", htype="linux")]
        cfg.vlans = [VLAN(id=255, name="prod", subnet="10.25.255.0/24", prefix="10.25.255", gateway="10.25.255.1")]
        mock_load.return_value = cfg
        handler = _Handler(
            "/api/vm/create/plan",
            body={"name": "new-vm", "node": "pve01", "vlan": "prod", "ip_mode": "static", "ip": "auto"},
        )

        vm_api.handle_vm_create_plan(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["plan"]["network"]["gateway"], "10.25.255.1")
        self.assertEqual(data["plan"]["network"]["cidr"], "10.25.255.11/24")
        self.assertEqual(data["plan"]["network"]["tag"], "255")
        self.assertTrue(data["plan"]["network"]["gateway_in_subnet"])
        self.assertEqual(len(data["plan"]["networks"]), 1)

    def test_vm_create_plan_accepts_start_on_boot_aliases(self):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.vlans = [VLAN(id=10, name="lab", subnet="10.25.10.0/24", prefix="10.25.10", gateway="10.25.10.1")]

        result = vm_api._vm_create_plan(
            cfg,
            {"name": "new-vm", "node": "pve01", "vlan": "10", "start_on_boot": True},
            allocate_vmid=False,
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["plan"]["start_on_boot"])
        self.assertTrue(result["plan"]["onboot"])

        result = vm_api._vm_create_plan(
            cfg,
            {"name": "new-vm", "node": "pve01", "vlan": "10", "onboot": "off"},
            allocate_vmid=False,
        )
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["plan"]["start_on_boot"])
        self.assertFalse(result["plan"]["onboot"])

    @patch("freq.api.vm._candidate_ip_available", return_value=True)
    def test_vm_create_plan_reserves_host_octets_across_networks(self, _mock_ip):
        from freq.core.types import Host, VLAN

        cfg = self._cfg()
        cfg.hosts = [Host(ip="10.25.255.10", label="pve01", htype="pve")]
        cfg.vlans = [VLAN(id=10, name="lab", subnet="10.25.10.0/24", prefix="10.25.10", gateway="10.25.10.1")]

        result = vm_api._vm_create_plan(
            cfg,
            {"name": "new-vm", "node": "pve01", "vlan": "lab", "ip_mode": "static", "ip": "auto"},
        )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["plan"]["network"]["cidr"], "10.25.10.11/24")

    @patch("freq.api.vm._candidate_ip_available", return_value=True)
    @patch("freq.api.vm._check_session_role", return_value=("operator", None))
    @patch("freq.api.vm._get_fleet_vms", return_value=[])
    @patch("freq.api.vm.load_config")
    def test_vm_create_plan_accepts_configured_gateway_outside_vlan_subnet_with_warning(self, mock_load, _mock_vms, _mock_role, _mock_ip):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.vm_gateway = "10.25.255.1"
        cfg.vlans = [VLAN(id=25, name="vlan25", subnet="10.25.25.0/24", prefix="10.25.25", gateway="")]
        mock_load.return_value = cfg
        handler = _Handler(
            "/api/vm/create/plan",
            body={"name": "new-vm", "node": "pve01", "vlan": "vlan25", "ip_mode": "static", "ip": "auto"},
        )

        vm_api.handle_vm_create_plan(handler)

        self.assertEqual(handler.status, 200)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["plan"]["network"]["gateway"], "10.25.255.1")
        self.assertEqual(data["plan"]["network"]["cidr"], "10.25.25.10/24")
        self.assertFalse(data["plan"]["network"]["gateway_in_subnet"])
        self.assertTrue(any("outside selected IP network" in warning for warning in data["warnings"]))

    @patch("freq.api.vm._check_session_role", return_value=("operator", None))
    @patch("freq.api.vm._get_fleet_vms", return_value=[])
    @patch("freq.api.vm.load_config")
    def test_vm_create_plan_rejects_gateway_outside_static_network(self, mock_load, _mock_vms, _mock_role):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.vlans = [VLAN(id=10, name="lab", subnet="10.25.10.0/24", prefix="10.25.10", gateway="10.25.10.1")]
        mock_load.return_value = cfg
        handler = _Handler(
            "/api/vm/create/plan",
            body={"name": "new-vm", "node": "pve01", "vlan": "lab", "ip_mode": "static", "ip": "10.25.10.50", "gateway": "10.25.255.1"},
        )

        vm_api.handle_vm_create_plan(handler)

        self.assertEqual(handler.status, 400)
        data = _json(handler)
        self.assertFalse(data["ok"])
        self.assertTrue(any("gateway" in err for err in data["errors"]))

    def test_vm_create_plan_rejects_explicit_out_of_contract_vmid(self):
        cfg = self._cfg()

        with patch("freq.api.vm._pve_cmd") as mock_pve:
            result = vm_api._vm_create_plan(
                cfg,
                {"name": "new-vm", "node": "pve01", "ip_mode": "dhcp", "vmid": 107},
                allocate_vmid=True,
            )

        self.assertFalse(result["ok"])
        self.assertTrue(any("target VMID blocked" in err for err in result["errors"]))
        mock_pve.assert_not_called()

    def test_vm_create_plan_uses_allowed_cluster_nextid(self):
        cfg = self._cfg()
        commands = []

        def fake_pve(_cfg, node_ip, command, timeout=60):
            commands.append((node_ip, command))
            return ("5005", True)

        with patch("freq.api.vm._pve_cmd", side_effect=fake_pve):
            result = vm_api._vm_create_plan(
                cfg,
                {"name": "new-vm", "node": "pve01", "ip_mode": "dhcp"},
                allocate_vmid=True,
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["plan"]["vmid"], 5005)
        self.assertEqual(result["plan"]["vmid_source"], "cluster-nextid")
        self.assertEqual(commands, [("10.0.0.1", "pvesh get /cluster/nextid")])

    def test_vm_create_plan_allocates_lab_range_when_cluster_nextid_is_blocked(self):
        cfg = self._cfg()
        commands = []

        def fake_pve(_cfg, node_ip, command, timeout=60):
            commands.append((node_ip, command))
            if command == "pvesh get /cluster/nextid":
                return ("107", True)
            if command == "pvesh get /cluster/resources --type vm --output-format json":
                return (json.dumps([{"vmid": 5000}, {"vmid": "5001"}]), True)
            return ("", False)

        with patch("freq.api.vm._pve_cmd", side_effect=fake_pve):
            result = vm_api._vm_create_plan(
                cfg,
                {"name": "new-vm", "node": "pve01", "ip_mode": "dhcp"},
                allocate_vmid=True,
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["plan"]["vmid"], 5002)
        self.assertEqual(result["plan"]["vmid_source"], "lab-range")
        self.assertIn(("10.0.0.1", "pvesh get /cluster/resources --type vm --output-format json"), commands)

    def test_vm_create_plan_replaces_disabled_explicit_storage_with_target_storage(self):
        cfg = self._cfg()
        cfg.pve_nodes = ["10.0.0.1", "10.0.0.2"]
        cfg.pve_node_names = ["pve01", "pve02"]
        cfg.pve_storage = {}

        def fake_pve(_cfg, node_ip, command, timeout=60):
            if command == "pvesh get /cluster/nextid":
                return ("5005", True)
            if command == "pvesh get /nodes/pve02/storage --content images --output-format json":
                return (
                    json.dumps(
                        [
                            {"storage": "local-lvm", "enabled": 0, "active": 0, "content": "images,rootdir", "type": "lvmthin"},
                            {"storage": "truenas-os-drive", "enabled": 1, "active": 1, "shared": 1, "content": "images,rootdir", "type": "nfs"},
                            {"storage": "os-pool-ssd", "enabled": 1, "active": 1, "shared": 0, "content": "images,rootdir", "type": "zfspool"},
                        ]
                    ),
                    True,
                )
            return ("[]", True)

        with patch("freq.api.vm._pve_cmd", side_effect=fake_pve):
            result = vm_api._vm_create_plan(
                cfg,
                {"name": "new-vm", "node": "pve02", "ip_mode": "dhcp", "storage": "local-lvm"},
                allocate_vmid=True,
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["plan"]["storage"], "os-pool-ssd")
        self.assertTrue(any("local-lvm" in warning and "os-pool-ssd" in warning for warning in result["warnings"]))

    def test_vm_create_job_clones_template_from_source_node_then_configures_target(self):
        cfg = self._cfg()
        cfg.pve_nodes = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
        cfg.pve_node_names = ["pve01", "pve02", "pve03"]
        cfg.fleet_boundaries.categories["sandbox"] = {"range_start": 6000, "range_end": 6099, "tier": "admin"}
        cfg.fleet_boundaries.categories["templates"] = {"vmids": [9001], "tier": "probe"}
        calls = []

        def fake_pve(_cfg, node_ip, command, timeout=60):
            calls.append((node_ip, command))
            if command == "pvesh get /cluster/nextid":
                return ("107", True)
            if command == "pvesh get /cluster/resources --type vm --output-format json":
                return ("[]", True)
            return ("", True)

        job_id = "job-source-node"
        with vm_api._vm_create_jobs_lock:
            vm_api._vm_create_jobs[job_id] = {
                "id": job_id,
                "state": "queued",
                "created_at": 0,
                "updated_at": 0,
                "lines": [],
            }

        with patch("freq.api.vm.load_config", return_value=cfg), \
             patch("freq.api.vm._find_vm_node_ip", return_value="10.0.0.3"), \
             patch("freq.api.vm._pve_cmd", side_effect=fake_pve), \
             patch("freq.api.vm._refresh_fleet_overview_after_mutation"):
            vm_api._run_vm_create_job(
                job_id,
                {
                    "name": "new-vm",
                    "node": "pve02",
                    "template_vmid": 9001,
                    "storage": "local-lvm",
                    "ip_mode": "dhcp",
                    "cores": 4,
                    "ram": 4096,
                    "balloon": 1024,
                },
            )

        with vm_api._vm_create_jobs_lock:
            job = dict(vm_api._vm_create_jobs.pop(job_id))

        self.assertEqual(job["state"], "succeeded", job)
        self.assertTrue(
            any(
                node == "10.0.0.3"
                and cmd == "qm clone 9001 6000 --name new-vm --full 1"
                for node, cmd in calls
            ),
            calls,
        )
        self.assertTrue(
            any(
                node == "10.0.0.3"
                and cmd == "qm migrate 6000 pve02 --with-local-disks --targetstorage local-lvm"
                for node, cmd in calls
            ),
            calls,
        )
        self.assertIn(("10.0.0.2", "qm resize 6000 scsi0 32G"), calls)
        self.assertIn(("10.0.0.2", "qm set 6000 --cores 4 --memory 4096 --cpu x86-64-v2-AES"), calls)
        self.assertIn(("10.0.0.2", "qm set 6000 --balloon 1024"), calls)
        self.assertTrue(any(node == "10.0.0.2" and cmd.startswith("qm set 6000") for node, cmd in calls), calls)

    def test_vm_create_plan_accepts_multiple_static_nics(self):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.vlans = [
            VLAN(id=10, name="mgmt", subnet="10.25.10.0/24", prefix="10.25.10", gateway="10.25.10.1"),
            VLAN(id=66, name="app", subnet="10.25.66.0/24", prefix="10.25.66", gateway="10.25.66.1"),
        ]

        with patch("freq.api.vm._candidate_ip_available", return_value=True):
            result = vm_api._vm_create_plan(
                cfg,
                {
                    "name": "new-vm",
                    "node": "pve01",
                    "nics": [
                        {"vlan": "mgmt", "ip": "auto"},
                        {"vlan": "app", "ip": "10.25.66.44"},
                    ],
                },
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["plan"]["networks"]), 2)
        self.assertEqual(result["plan"]["networks"][0]["tag"], "10")
        self.assertEqual(result["plan"]["networks"][1]["cidr"], "10.25.66.44/24")
        self.assertEqual(result["plan"]["network"], result["plan"]["networks"][0])

    def test_vm_create_plan_infers_dc01_single_gateway_nic_policy(self):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.vlans = [
            VLAN(id=2550, name="management", subnet="10.25.255.0/24", prefix="10.25.255", gateway="10.25.255.1"),
            VLAN(id=25, name="storage", subnet="10.25.25.0/24", prefix="10.25.25", gateway="10.25.25.1"),
            VLAN(id=10, name="compute", subnet="10.25.10.0/24", prefix="10.25.10", gateway="10.25.10.1"),
            VLAN(id=5, name="public", subnet="10.25.5.0/24", prefix="10.25.5", gateway="10.25.5.1"),
            VLAN(id=66, name="dirty", subnet="10.25.66.0/24", prefix="10.25.66", gateway="10.25.66.1"),
        ]

        with patch("freq.api.vm._candidate_ip_available", return_value=True):
            result = vm_api._vm_create_plan(
                cfg,
                {
                    "name": "new-vm",
                    "node": "pve01",
                    "nics": [
                        {"vlan": "2550", "ip": "auto"},
                        {"vlan": "25", "ip": "auto"},
                        {"vlan": "5", "ip": "auto"},
                    ],
                },
            )

        self.assertTrue(result["ok"], result)
        nets = result["plan"]["networks"]
        self.assertEqual([n["cidr"].split("/", 1)[0].rsplit(".", 1)[-1] for n in nets], ["10", "10", "10"])
        self.assertEqual(nets[0]["gateway"], "")
        self.assertEqual(nets[1]["gateway"], "")
        self.assertEqual(nets[2]["gateway"], "10.25.5.1")

    def test_vm_create_plan_rejects_multiple_internet_egress_nics(self):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.vlans = [
            VLAN(id=5, name="public", subnet="10.25.5.0/24", prefix="10.25.5", gateway="10.25.5.1"),
            VLAN(id=10, name="compute", subnet="10.25.10.0/24", prefix="10.25.10", gateway="10.25.10.1"),
            VLAN(id=25, name="storage", subnet="10.25.25.0/24", prefix="10.25.25", gateway="10.25.25.1"),
            VLAN(id=66, name="dirty", subnet="10.25.66.0/24", prefix="10.25.66", gateway="10.25.66.1"),
        ]

        with patch("freq.api.vm._candidate_ip_available", return_value=True):
            result = vm_api._vm_create_plan(
                cfg,
                {
                    "name": "new-vm",
                    "node": "pve01",
                    "nics": [
                        {"vlan": "5", "ip": "auto"},
                        {"vlan": "66", "ip": "auto"},
                    ],
                },
            )

        self.assertFalse(result["ok"], result)
        self.assertTrue(any("multiple internet-egress" in err for err in result["errors"]))

    def test_vm_create_options_derives_observed_network_catalog(self):
        from freq.core.types import Host

        cfg = self._cfg()
        cfg.vlans = []
        cfg.hosts = [
            Host(ip="10.25.255.50", label="freq", htype="linux", all_ips=["10.25.255.50", "10.25.25.50", "10.25.10.50", "10.25.5.50"]),
            Host(ip="10.25.66.37", label="web", htype="linux", all_ips=["10.25.66.37"]),
        ]

        with patch("freq.api.vm._get_fleet_vms", return_value=[]):
            payload = vm_api._vm_create_options_payload(cfg)

        vlan_ids = {row["id"] for row in payload["vlans"]}
        self.assertTrue({2550, 25, 10, 5, 66}.issubset(vlan_ids))
        self.assertEqual(payload["network_policy"]["gateway_source"], "single_egress")
        self.assertEqual(set(payload["network_policy"]["internet_vlans"]), {"5", "66"})

    def test_vm_create_job_writes_all_requested_nics(self):
        cfg = self._cfg()
        cfg.fleet_boundaries.categories["sandbox"] = {"range_start": 6000, "range_end": 6099, "tier": "admin"}
        calls = []

        def fake_pve(_cfg, node_ip, command, timeout=60):
            calls.append((node_ip, command))
            if command == "pvesh get /cluster/nextid":
                return ("107", True)
            if command == "pvesh get /cluster/resources --type vm --output-format json":
                return ("[]", True)
            return ("", True)

        job_id = "job-multi-nic"
        with vm_api._vm_create_jobs_lock:
            vm_api._vm_create_jobs[job_id] = {
                "id": job_id,
                "state": "queued",
                "created_at": 0,
                "updated_at": 0,
                "lines": [],
            }

        with patch("freq.api.vm.load_config", return_value=cfg), \
             patch("freq.api.vm._pve_cmd", side_effect=fake_pve), \
             patch("freq.api.vm._refresh_fleet_overview_after_mutation"):
            vm_api._run_vm_create_job(
                job_id,
                {
                    "name": "new-vm",
                    "node": "pve01",
                    "start_on_boot": True,
                    "nics": [
                        {"vlan": "10", "ip": "10.25.10.44/24", "gateway": "10.25.10.1"},
                        {"vlan": "66", "ip": "10.25.66.44/24", "gateway": "10.25.66.1"},
                    ],
                },
            )

        with vm_api._vm_create_jobs_lock:
            job = dict(vm_api._vm_create_jobs.pop(job_id))

        self.assertEqual(job["state"], "succeeded", job)
        commands = [cmd for _node, cmd in calls]
        self.assertIn("qm set 6000 --cores 2 --memory 2048 --cpu x86-64-v2-AES", commands)
        self.assertIn("qm set 6000 --balloon 0", commands)
        self.assertIn("qm set 6000 --onboot 1", commands)
        self.assertIn("qm set 6000 --net0 virtio,bridge=vmbr0,tag=10", commands)
        self.assertIn("qm set 6000 --ipconfig0 ip=10.25.10.44/24,gw=10.25.10.1", commands)
        self.assertIn("qm set 6000 --net1 virtio,bridge=vmbr0,tag=66", commands)
        self.assertIn("qm set 6000 --ipconfig1 ip=10.25.66.44/24,gw=10.25.66.1", commands)

    def test_vm_create_job_uses_profile_derived_bridge(self):
        from freq.core.types import VLAN

        cfg = self._cfg()
        cfg.fleet_boundaries.categories["sandbox"] = {"range_start": 6000, "range_end": 6099, "tier": "admin"}
        cfg.nic_profiles = {
            "tenant": {"name": "Tenant", "vlan": 25, "bridge": "vmbr25", "gateway_role": "none"}
        }
        cfg.vlans = [VLAN(id=25, name="tenant", subnet="10.25.25.0/24", prefix="10.25.25", gateway="10.25.25.1")]
        calls = []

        def fake_pve(_cfg, node_ip, command, timeout=60):
            calls.append((node_ip, command))
            if command == "pvesh get /cluster/nextid":
                return ("6000", True)
            if command == "pvesh get /cluster/resources --type vm --output-format json":
                return ("[]", True)
            return ("", True)

        job_id = "job-profile-net"
        with vm_api._vm_create_jobs_lock:
            vm_api._vm_create_jobs[job_id] = {"id": job_id, "state": "queued", "created_at": 0, "updated_at": 0, "lines": []}

        with patch("freq.api.vm.load_config", return_value=cfg), \
             patch("freq.api.vm._pve_cmd", side_effect=fake_pve), \
             patch("freq.api.vm._refresh_fleet_overview_after_mutation"):
            vm_api._run_vm_create_job(
                job_id,
                {"name": "new-vm", "node": "pve01", "network_profile": "tenant", "ip": "10.25.25.44/24"},
            )

        with vm_api._vm_create_jobs_lock:
            job = dict(vm_api._vm_create_jobs.pop(job_id))

        self.assertEqual(job["state"], "succeeded", job)
        commands = [cmd for _node, cmd in calls]
        self.assertIn("qm set 6000 --net0 virtio,bridge=vmbr25,tag=25", commands)

    @patch("freq.api.vm.threading.Thread")
    @patch("freq.api.vm._check_session_role", return_value=("admin", None))
    @patch("freq.api.vm._get_fleet_vms", return_value=[])
    @patch("freq.api.vm.load_config")
    def test_vm_create_submit_queues_async_job(self, mock_load, _mock_vms, _mock_role, mock_thread):
        cfg = self._cfg()
        mock_load.return_value = cfg
        handler = _Handler("/api/vm/create/submit", body={"name": "new-vm", "node": "pve01", "ip_mode": "dhcp"})

        vm_api.handle_vm_create_submit(handler)

        self.assertEqual(handler.status, 202)
        data = _json(handler)
        self.assertTrue(data["ok"])
        self.assertEqual(data["job"]["state"], "queued")
        mock_thread.assert_called()

    def test_vm_create_routes_registered(self):
        routes = {}
        vm_api.register(routes)
        for path in (
            "/api/vm/create/options",
            "/api/vm/network-profiles",
            "/api/vm/create/plan",
            "/api/vm/create/submit",
            "/api/vm/create/job",
        ):
            self.assertIn(path, routes)

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
