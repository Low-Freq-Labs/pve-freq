"""Executed-journey owners for fleet materialization and PVE API readiness."""

import hashlib
import json
import os
import tempfile
import types
import unittest
from unittest import mock


class TestConfiguredPveNodeMaterialization(unittest.TestCase):
    def test_headless_discovery_persists_configured_nodes_when_inventory_is_empty(self):
        from freq.modules.init_cmd import _phase_fleet_discover

        with tempfile.TemporaryDirectory() as root:
            hosts_path = os.path.join(root, "hosts.toml")
            with open(os.path.join(root, "freq.toml"), "w", encoding="utf-8") as handle:
                handle.write("[freq]\nversion = \"test\"\n\n[infrastructure]\n")

            cfg = mock.MagicMock()
            cfg.conf_dir = root
            cfg.hosts_file = hosts_path
            cfg.hosts = []
            cfg.pve_nodes = ["10.25.10.202", "10.25.10.203"]
            cfg.pve_node_names = ["lab-pve1", "lab-pve2"]
            cfg.pve_api_token_id = ""
            cfg.pve_api_token_secret = ""
            cfg.vlans = []
            cfg.vm_gateway = ""
            cfg.pfsense_ip = ""
            cfg.truenas_ip = ""
            cfg.switch_ip = ""
            cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})
            args = types.SimpleNamespace(
                headless=True,
                hosts_file=None,
                device_credentials=None,
                core_devices=None,
                lab_devices=None,
            )
            ctx = {"key_path": "/synthetic/key", "svc_name": "freq-admin"}

            with mock.patch("freq.modules.init_cmd.fmt"), mock.patch(
                "freq.modules.init_cmd._run", return_value=(1, "", "synthetic miss")
            ), mock.patch(
                "freq.modules.discover.scan_and_identify", return_value=([], [])
            ), mock.patch(
                "freq.modules.hosts._auto_populate_fleet_boundaries"
            ):
                _phase_fleet_discover(cfg, ctx, args)

            self.assertEqual(
                [(host.ip, host.label, host.htype, host.managed) for host in cfg.hosts],
                [
                    ("10.25.10.202", "lab-pve1", "pve", True),
                    ("10.25.10.203", "lab-pve2", "pve", True),
                ],
            )
            with open(hosts_path, encoding="utf-8") as handle:
                persisted = handle.read()
            self.assertIn('ip = "10.25.10.202"', persisted)
            self.assertIn('ip = "10.25.10.203"', persisted)

    def test_discovery_aggregates_inventory_from_independent_pve_nodes(self):
        from freq.modules.init_cmd import _phase_fleet_discover

        with tempfile.TemporaryDirectory() as root:
            hosts_path = os.path.join(root, "hosts.toml")
            with open(os.path.join(root, "freq.toml"), "w", encoding="utf-8") as handle:
                handle.write("[freq]\nversion = \"test\"\n\n[infrastructure]\n")

            cfg = mock.MagicMock()
            cfg.conf_dir = root
            cfg.hosts_file = hosts_path
            cfg.hosts = []
            cfg.pve_nodes = ["10.25.10.202", "10.25.10.203"]
            cfg.pve_node_names = ["lab-pve1", "lab-pve2"]
            cfg.pve_api_token_id = "freq-admin@pam!freq-rw"
            cfg.pve_api_token_secret = "synthetic-secret"
            cfg.vlans = []
            cfg.vm_gateway = ""
            cfg.pfsense_ip = ""
            cfg.truenas_ip = ""
            cfg.switch_ip = ""
            cfg.fleet_boundaries = types.SimpleNamespace(categories={}, physical={})
            args = types.SimpleNamespace(
                headless=True,
                hosts_file=None,
                device_credentials=None,
                core_devices=None,
                lab_devices=None,
            )
            ctx = {"key_path": "/synthetic/key", "svc_name": "freq-admin"}
            inventory_calls = []

            def api_call(_cfg, node_ip, endpoint):
                if endpoint == "/cluster/resources?type=vm":
                    inventory_calls.append(node_ip)
                    vmid = 5002 if node_ip.endswith(".202") else 5003
                    node = "lab-pve1" if node_ip.endswith(".202") else "lab-pve2"
                    return [
                        {
                            "vmid": vmid,
                            "name": f"guest-{vmid}",
                            "status": "running",
                            "type": "qemu",
                            "node": node,
                        }
                    ], True
                vmid = 5002 if node_ip.endswith(".202") else 5003
                self.assertEqual(
                    endpoint,
                    f"/nodes/{'lab-pve1' if vmid == 5002 else 'lab-pve2'}/qemu/{vmid}/agent/network-get-interfaces",
                )
                return {
                    "result": [
                        {
                            "name": "eth0",
                            "ip-addresses": [
                                {
                                    "ip-address-type": "ipv4",
                                    "ip-address": f"192.0.2.{vmid - 4900}",
                                }
                            ],
                        }
                    ]
                }, True

            with mock.patch("freq.modules.init_cmd.fmt"), mock.patch(
                "freq.modules.init_cmd._run", return_value=(1, "", "synthetic miss")
            ), mock.patch(
                "freq.modules.discover.scan_and_identify", return_value=([], [])
            ), mock.patch(
                "freq.modules.hosts._auto_populate_fleet_boundaries"
            ) as auto_boundaries, mock.patch(
                "freq.modules.pve._pve_api_call", side_effect=api_call
            ):
                _phase_fleet_discover(cfg, ctx, args)

            self.assertEqual(inventory_calls, ["10.25.10.202", "10.25.10.203"])
            discovered = auto_boundaries.call_args.args[1]
            self.assertEqual(discovered["192.0.2.102"]["vmid"], 5002)
            self.assertEqual(discovered["192.0.2.103"]["vmid"], 5003)


class TestIndependentPveNodeTokenRepair(unittest.TestCase):
    def test_phase_repairs_second_node_401_with_node_scoped_token(self):
        from freq.modules.init_cmd import _phase_pve_api_token

        with tempfile.TemporaryDirectory() as root:
            key_path = os.path.join(root, "id_ed25519")
            with open(key_path, "w", encoding="utf-8") as handle:
                handle.write("synthetic-key")
            conf_dir = os.path.join(root, "conf")
            credentials_dir = os.path.join(root, "credentials")
            os.makedirs(conf_dir)
            with open(os.path.join(conf_dir, "freq.toml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "[ssh]\nservice_account = \"freq-admin\"\n\n"
                    "[pve]\nnodes = [\"10.25.10.202\", \"10.25.10.203\"]\n"
                    "# api_token_id = \"\"\n# api_token_secret_path = \"\"\n"
                )

            cfg = types.SimpleNamespace(
                pve_nodes=["10.25.10.202", "10.25.10.203"],
                pve_node_names=["lab-pve1", "lab-pve2"],
                ssh_key_path=key_path,
                ssh_service_account="freq-admin",
                credentials_dir=credentials_dir,
                conf_dir=conf_dir,
                pve_api_token_id="",
                pve_api_token_secret="",
                pve_api_verify_ssl=False,
            )
            ctx = {"key_path": key_path, "svc_name": "freq-admin"}
            commands = []

            def run(command, timeout=30):
                commands.append(list(command))
                rendered = " ".join(command)
                if rendered.endswith("echo ok"):
                    return 0, "ok\n", ""
                if "pveum user list" in rendered:
                    return 0, "[]", ""
                if "pveum user add" in rendered or "pveum acl modify" in rendered:
                    return 0, "", ""
                if "pveum user token add" in rendered:
                    token_name = rendered.split("pveum user token add freq-admin@pam ", 1)[1].split()[0]
                    return 0, json.dumps(
                        {
                            "full-tokenid": f"freq-admin@pam!{token_name}",
                            "value": f"synthetic-{token_name}-secret",
                        }
                    ), ""
                return 1, "", "synthetic miss"

            calls = {"10.25.10.202": 0, "10.25.10.203": 0}

            def api_call(_cfg, node_ip, endpoint):
                self.assertEqual(endpoint, "/version")
                calls[node_ip] += 1
                if node_ip == "10.25.10.203" and calls[node_ip] == 1:
                    return "HTTP Error 401: Authentication failed!", False
                return {"version": "8.4.19"}, True

            with mock.patch("freq.modules.init_cmd._run", side_effect=run), mock.patch(
                "freq.modules.init_cmd._chown"
            ), mock.patch("freq.modules.init_cmd.fmt"), mock.patch(
                "freq.modules.init_cmd.audit.record"
            ), mock.patch("freq.modules.pve._pve_api_call", side_effect=api_call):
                _phase_pve_api_token(cfg, ctx)

            suffix = hashlib.sha256(b"10.25.10.203").hexdigest()[:12]
            node_token_name = f"freq-rw-{suffix}"
            self.assertTrue(ctx["api_token_verified"])
            self.assertGreaterEqual(calls["10.25.10.203"], 2)
            self.assertTrue(
                os.path.isfile(os.path.join(credentials_dir, f"pve-token-rw-{suffix}"))
            )
            self.assertTrue(
                any(node_token_name in " ".join(command) for command in commands)
            )

    def test_runtime_and_doctor_select_the_node_scoped_pair(self):
        from freq.core import doctor
        from freq.services.pve_transport import (
            _pve_api_credentials,
            _pve_node_token_name,
            _pve_node_token_path,
        )

        with tempfile.TemporaryDirectory() as root:
            cfg = types.SimpleNamespace(
                pve_nodes=["10.25.10.202", "10.25.10.203"],
                pve_api_token_id="freq-admin@pam!freq-rw",
                pve_api_token_secret="shared-secret",
                credentials_dir=root,
                ssh_service_account="freq-admin",
            )
            second_path = _pve_node_token_path(cfg, "10.25.10.203")
            with open(second_path, "w", encoding="utf-8") as handle:
                handle.write("second-node-secret")

            self.assertEqual(
                _pve_api_credentials(cfg, "10.25.10.202"),
                ("freq-admin@pam!freq-rw", "shared-secret"),
            )
            self.assertEqual(
                _pve_api_credentials(cfg, "10.25.10.203"),
                (
                    f"freq-admin@pam!{_pve_node_token_name('10.25.10.203')}",
                    "second-node-secret",
                ),
            )

            observed = []

            def probe(ip, token_id, token_secret):
                observed.append((ip, token_id, token_secret))
                return 200, '{"data":{"version":"8.4.19"}}'

            with mock.patch.object(doctor, "_probe_pve_api_token", side_effect=probe), mock.patch.object(
                doctor, "fmt"
            ):
                self.assertEqual(doctor._check_pve_token_drift(cfg), 0)

            self.assertEqual(
                observed,
                [
                    ("10.25.10.202", "freq-admin@pam!freq-rw", "shared-secret"),
                    (
                        "10.25.10.203",
                        f"freq-admin@pam!{_pve_node_token_name('10.25.10.203')}",
                        "second-node-secret",
                    ),
                ],
            )


if __name__ == "__main__":
    unittest.main()
