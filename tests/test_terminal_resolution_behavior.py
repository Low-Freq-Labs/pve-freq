"""Behavior ownership for terminal target resolution and SSH preflight."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from freq.api import terminal


class TestTerminalResolutionBehavior(unittest.TestCase):
    def _cfg(self):
        return SimpleNamespace(
            pve_node_names=["pve03"],
            pve_nodes=["10.25.255.28"],
            fleet_boundaries=SimpleNamespace(
                pve_nodes={
                    "pve04": SimpleNamespace(name="pve04", ip="10.25.255.29"),
                }
            ),
        )

    def test_node_and_vm_resolution_follows_live_then_configured_fallbacks(self):
        cfg = self._cfg()
        discovered = Mock(
            return_value=[
                {"name": "pve01", "ip": "10.25.255.26"},
                {"name": "pve02", "ip": "10.25.255.27"},
            ]
        )
        with patch.object(terminal, "_get_discovered_nodes", discovered):
            self.assertEqual(terminal._resolve_pve_node_ip(cfg, ""), "")
            discovered.assert_not_called()
            self.assertEqual(
                terminal._resolve_pve_node_ip(cfg, "10.25.255.30"),
                "10.25.255.30",
            )
            discovered.assert_not_called()
            self.assertEqual(terminal._resolve_pve_node_ip(cfg, "pve01"), "10.25.255.26")
            self.assertEqual(terminal._resolve_pve_node_ip(cfg, "pve03"), "10.25.255.28")
            self.assertEqual(terminal._resolve_pve_node_ip(cfg, "pve04"), "10.25.255.29")
            self.assertEqual(terminal._resolve_pve_node_ip(cfg, "missing"), "")

        collision_cfg = SimpleNamespace(
            pve_node_names=["pve01"],
            pve_nodes=["192.0.2.10"],
            fleet_boundaries=SimpleNamespace(
                pve_nodes={
                    "pve01": SimpleNamespace(name="pve01", ip="192.0.2.11"),
                }
            ),
        )
        with patch.object(
            terminal,
            "_get_discovered_nodes",
            return_value=[{"name": "pve01", "ip": "10.25.255.26"}],
        ):
            self.assertEqual(
                terminal._resolve_pve_node_ip(collision_cfg, "pve01"),
                "10.25.255.26",
            )

        configured_boundary_collision = SimpleNamespace(
            pve_node_names=["pve06"],
            pve_nodes=["10.25.255.31"],
            fleet_boundaries=SimpleNamespace(
                pve_nodes={
                    "pve06": SimpleNamespace(name="pve06", ip="192.0.2.12"),
                }
            ),
        )
        with patch.object(terminal, "_get_discovered_nodes", return_value=[]):
            self.assertEqual(
                terminal._resolve_pve_node_ip(configured_boundary_collision, "pve06"),
                "10.25.255.31",
            )

        with (
            patch.object(terminal, "_get_discovered_nodes", side_effect=RuntimeError("offline")),
            patch.object(terminal.logger, "warn") as warn,
        ):
            self.assertEqual(terminal._resolve_pve_node_ip(cfg, "pve03"), "10.25.255.28")
        warn.assert_called_once_with(
            "terminal: live node discovery lookup failed for pve03: offline"
        )

        with (
            patch.object(terminal, "_get_discovered_nodes", return_value=[
                {"name": "pve02", "ip": "10.25.255.27"},
            ]),
            patch.object(terminal, "_get_fleet_vms") as fleet,
        ):
            self.assertEqual(
                terminal._find_live_vm_node_ip(cfg, 201, "pve03"),
                ("10.25.255.28", "pve03"),
            )
            fleet.assert_not_called()

        with (
            patch.object(terminal, "_get_discovered_nodes", return_value=[
                {"name": "pve02", "ip": "10.25.255.27"},
            ]),
            patch.object(
                terminal,
                "_get_fleet_vms",
                return_value=[
                    {"vmid": "201", "node": "pve02"},
                    {"vmid": 202, "node": "pve01"},
                ],
            ),
            patch("freq.modules.pve._find_vm_node") as fallback,
        ):
            self.assertEqual(
                terminal._find_live_vm_node_ip(cfg, 201),
                ("10.25.255.27", "pve02"),
            )
        fallback.assert_not_called()

        with (
            patch.object(terminal, "_get_fleet_vms", side_effect=RuntimeError("inventory")),
            patch("freq.modules.pve._find_vm_node", return_value="10.25.255.26") as fallback,
            patch.object(terminal.logger, "warn") as warn,
        ):
            self.assertEqual(
                terminal._find_live_vm_node_ip(cfg, 999),
                ("10.25.255.26", ""),
            )
        fallback.assert_called_once_with(cfg, 999, "")
        warn.assert_called_once_with(
            "terminal: live VM ownership lookup failed for VMID 999: inventory"
        )

        with (
            patch.object(terminal, "_get_fleet_vms", return_value=[]),
            patch("freq.modules.pve._find_vm_node", side_effect=RuntimeError("fallback")),
            patch.object(terminal.logger, "warn") as warn,
        ):
            self.assertEqual(terminal._find_live_vm_node_ip(cfg, 404), ("", ""))
        warn.assert_called_once_with(
            "terminal: fallback VM node lookup failed for VMID 404: fallback"
        )

        no_boundaries = SimpleNamespace(
            pve_node_names=["pve05"],
            pve_nodes=[],
            fleet_boundaries=None,
        )
        with (
            patch.object(terminal, "_get_discovered_nodes", return_value=[]),
            patch.object(
                terminal,
                "_get_fleet_vms",
                return_value=[{"vmid": 405, "node": "unknown-node"}],
            ),
            patch("freq.modules.pve._find_vm_node", return_value="10.25.255.32") as fallback,
        ):
            self.assertEqual(
                terminal._resolve_pve_node_ip(no_boundaries, "pve05"),
                "",
            )
            self.assertEqual(
                terminal._find_live_vm_node_ip(no_boundaries, 405),
                ("10.25.255.32", ""),
            )
        fallback.assert_called_once_with(no_boundaries, 405, "")

        with (
            patch.object(terminal, "_get_fleet_vms", return_value=[]),
            patch("freq.modules.pve._find_vm_node", return_value="") as fallback,
        ):
            self.assertEqual(
                terminal._find_live_vm_node_ip(no_boundaries, 406),
                ("", ""),
            )
        fallback.assert_called_once_with(no_boundaries, 406, "")

    def test_guest_agent_transport_and_ipv4_extraction_are_fail_closed(self):
        cfg = self._cfg()
        api_result = [{"name": "ens18", "ip-addresses": []}]
        with (
            patch("freq.modules.pve._pve_api_call", return_value=(api_result, True)) as api,
            patch("freq.modules.pve._pve_cmd") as ssh,
        ):
            self.assertEqual(
                terminal._guest_agent_network_json(cfg, 201, "10.25.255.27", "pve02"),
                (json.dumps(api_result), True, "pve_api"),
            )
        api.assert_called_once_with(
            cfg,
            "10.25.255.27",
            "/nodes/pve02/qemu/201/agent/network-get-interfaces",
            timeout=10,
        )
        ssh.assert_not_called()

        with (
            patch("freq.modules.pve._pve_api_call", return_value=(None, False)) as api,
            patch("freq.modules.pve._pve_cmd", return_value=("ssh-json", True)) as ssh,
        ):
            self.assertEqual(
                terminal._guest_agent_network_json(cfg, 201, "10.25.255.27", "pve02"),
                ("ssh-json", True, "pve_ssh"),
            )
        api.assert_called_once()
        ssh.assert_called_once_with(
            cfg,
            "10.25.255.27",
            "qm agent 201 network-get-interfaces 2>/dev/null",
            timeout=10,
        )

        with (
            patch("freq.modules.pve._pve_api_call", side_effect=RuntimeError("api")),
            patch("freq.modules.pve._pve_cmd", return_value=("fallback-json", False)),
            patch.object(terminal.logger, "warn") as warn,
        ):
            self.assertEqual(
                terminal._guest_agent_network_json(cfg, 202, "10.25.255.27", "pve02"),
                ("fallback-json", False, "pve_ssh"),
            )
        warn.assert_called_once_with(
            "terminal: PVE API guest-agent lookup failed for VMID 202: api"
        )

        with (
            patch("freq.modules.pve._pve_api_call") as api,
            patch("freq.modules.pve._pve_cmd", side_effect=RuntimeError("ssh")),
            patch.object(terminal.logger, "warn") as warn,
        ):
            self.assertEqual(
                terminal._guest_agent_network_json(cfg, 203, "10.25.255.27", ""),
                ("ssh", False, "pve_ssh"),
            )
        api.assert_not_called()
        warn.assert_called_once_with(
            "terminal: SSH guest-agent lookup failed for VMID 203: ssh"
        )

        usable = {
            "name": "ens18",
            "ip-addresses": [
                {"ip-address-type": "ipv6", "ip-address": "::1"},
                {"ip-address-type": "ipv4", "ip-address": "127.0.0.2"},
                {"ip-address-type": "ipv4", "ip-address": "10.25.255.201"},
            ],
        }
        cases = (
            ("", ""),
            ("not-json", ""),
            ("{}", ""),
            ('{"result": {}}', ""),
            (json.dumps(["bad", {"name": "lo", "ip-addresses": []}, usable]), "10.25.255.201"),
            (json.dumps({"result": [usable]}), "10.25.255.201"),
            (json.dumps([{"name": "ens18", "ip-addresses": [None, {}]}]), ""),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(terminal._extract_guest_ipv4(raw), expected)

    def test_ssh_identity_and_truenas_preflight_preserve_operator_truth(self):
        cfg = SimpleNamespace(
            ssh_service_account="svc-freq",
            ssh_key_path="/keys/ed25519",
            ssh_rsa_key_path="/keys/rsa",
            legacy_password_file="/secrets/legacy",
        )
        staged = {"user": "device-user", "key_path": "/staged/key"}
        with patch.object(
            terminal,
            "resolve_staged_device_ssh_auth",
            return_value=staged,
        ) as resolve:
            for htype in ("pfsense", "IDRAC", "switch", "truenas"):
                with self.subTest(staged=htype):
                    self.assertIs(terminal._terminal_ssh_auth(cfg, htype), staged)
        self.assertEqual(
            resolve.call_args_list,
            [call(cfg, name) for name in ("pfsense", "idrac", "switch", "truenas")],
        )

        self.assertEqual(
            terminal._terminal_ssh_auth(cfg, "linux"),
            {
                "user": "svc-freq",
                "key_path": "/keys/ed25519",
                "password_file": None,
                "sudo_password_file": False,
                "local_user": None,
            },
        )
        self.assertEqual(
            terminal._terminal_ssh_auth(SimpleNamespace(), ""),
            {
                "user": "freq-admin",
                "key_path": "",
                "password_file": None,
                "sudo_password_file": False,
                "local_user": None,
            },
        )

        auth = {
            "user": "truenas-user",
            "key_path": "/key",
            "local_user": "freq-admin",
            "password_file": "/password",
            "sudo_password_file": True,
        }
        with patch.object(terminal, "ssh_single") as ssh:
            self.assertEqual(terminal._terminal_preflight(cfg, "linux", "host", auth), (True, ""))
        ssh.assert_not_called()

        expected_call = call(
            host="10.25.100.20",
            command="true",
            user="truenas-user",
            key_path="/key",
            connect_timeout=4,
            command_timeout=6,
            htype="truenas",
            use_sudo=False,
            local_user="freq-admin",
            password_file="/password",
            sudo_password_file=True,
            cfg=cfg,
            failure_log_level="warn",
        )
        cases = (
            (SimpleNamespace(returncode=0, stderr="", stdout=""), (True, "")),
            (
                SimpleNamespace(returncode=255, stderr="Permission denied", stdout=""),
                (
                    False,
                    "Terminal unavailable: TrueNAS SSH credentials were rejected. TrueNAS reads are API-backed; stage working SSH credentials to open an interactive shell.",
                ),
            ),
            (
                SimpleNamespace(returncode=255, stderr="", stdout="no supported publickey"),
                (
                    False,
                    "Terminal unavailable: TrueNAS SSH credentials were rejected. TrueNAS reads are API-backed; stage working SSH credentials to open an interactive shell.",
                ),
            ),
            (
                SimpleNamespace(returncode=1, stderr="x" * 200, stdout=""),
                (False, f"Terminal unavailable: TrueNAS SSH preflight failed ({'x' * 180})."),
            ),
            (
                SimpleNamespace(returncode=1, stderr="connection reset", stdout="permission denied"),
                (
                    False,
                    "Terminal unavailable: TrueNAS SSH preflight failed (connection reset).",
                ),
            ),
            (
                SimpleNamespace(returncode=1, stderr="", stdout=""),
                (False, "Terminal unavailable: TrueNAS SSH preflight failed (no output)."),
            ),
        )
        for result, expected in cases:
            with (
                self.subTest(preflight=expected),
                patch.object(terminal, "ssh_single", return_value=result) as ssh,
            ):
                self.assertEqual(
                    terminal._terminal_preflight(cfg, "truenas", "10.25.100.20", auth),
                    expected,
                )
            self.assertEqual(ssh.call_args_list, [expected_call])


if __name__ == "__main__":
    unittest.main()
