import os
import tempfile
import unittest


class TestProductIdentityContract(unittest.TestCase):
    def test_hosts_toml_round_trips_display_name(self):
        from freq.core.config import load_hosts_toml, save_hosts_toml
        from freq.core.types import Host

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            path = f.name
        try:
            save_hosts_toml(
                path,
                [
                    Host(
                        ip="192.0.2.10",
                        label="truenas",
                        htype="truenas",
                        display_name="TrueNAS-01",
                    )
                ],
            )
            hosts = load_hosts_toml(path)
            self.assertEqual(len(hosts), 1)
            self.assertEqual(hosts[0].label, "truenas")
            self.assertEqual(hosts[0].display_name, "TrueNAS-01")
        finally:
            os.unlink(path)

    def test_fleet_boundaries_loads_physical_display_name(self):
        from freq.core.config import load_fleet_boundaries

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[physical]\n")
            f.write('bmc_pve01 = { ip = "192.0.2.11", label = "bmc-11", display_name = "iDRAC-PVE01", type = "idrac" }\n')
            path = f.name
        try:
            boundaries = load_fleet_boundaries(path)
            dev = boundaries.physical["bmc_pve01"]
            self.assertEqual(dev.label, "bmc-11")
            self.assertEqual(dev.display_name, "iDRAC-PVE01")
        finally:
            os.unlink(path)

    def test_fleet_boundaries_writer_persists_operator_bmc_display_names(self):
        from ast import parse
        from pathlib import Path
        from types import SimpleNamespace

        from freq.core import host_identity
        from freq.core.types import FleetBoundaries
        from freq.modules import hosts

        _auto_populate_fleet_boundaries = hosts._auto_populate_fleet_boundaries
        _physical_display_name_for = host_identity.physical_display_name_for_mapping
        self.assertIs(hosts._physical_display_name_for, _physical_display_name_for)

        repo_root = Path(__file__).resolve().parents[1]
        hosts_tree = parse((repo_root / "freq/modules/hosts.py").read_text())
        core_tree = parse((repo_root / "freq/core/host_identity.py").read_text())
        hosts_removed_names = {
            "_ip_sort_key",
            "_generic_physical_label",
            "_bmc_display_prefix",
            "_node_display_name",
            "_physical_display_name_for",
        }
        core_owned_names = {
            "_physical_ip_sort_key",
            "_generic_physical_label",
            "_bmc_display_prefix",
            "_node_display_name",
            "physical_display_name_for_mapping",
        }
        hosts_defs = {node.name for node in hosts_tree.body if hasattr(node, "name")}
        core_defs = {node.name for node in core_tree.body if hasattr(node, "name")}
        self.assertFalse(hosts_removed_names & hosts_defs)
        self.assertTrue(core_owned_names <= core_defs)

        with tempfile.TemporaryDirectory(prefix="freq-identity-") as tmp:
            Path(tmp, "fleet-boundaries.toml").write_text("")
            cfg = SimpleNamespace(
                conf_dir=tmp,
                fleet_boundaries=FleetBoundaries(),
                pve_nodes=["192.0.2.26", "192.0.2.27"],
                pve_node_names=["pve01", "pve02"],
                pfsense_ip="",
                truenas_ip="",
                switch_ip="",
                vm_gateway="",
            )
            discovered = {
                "192.0.2.10": {
                    "label": "bmc-10",
                    "htype": "idrac",
                    "groups": "infrastructure",
                    "scope": "core",
                },
                "192.0.2.11": {
                    "label": "bmc-11",
                    "htype": "idrac",
                    "groups": "infrastructure",
                    "scope": "core",
                },
                "192.0.2.26": {"label": "pve01", "htype": "pve", "source": "pve-node"},
                "192.0.2.27": {"label": "pve02", "htype": "pve", "source": "pve-node"},
            }

            _auto_populate_fleet_boundaries(cfg, discovered)

            content = Path(tmp, "fleet-boundaries.toml").read_text()

        self.assertIn('label = "bmc-10"', content)
        self.assertIn('display_name = "iDRAC-PVE01"', content)
        self.assertIn('label = "bmc-11"', content)
        self.assertIn('display_name = "iDRAC-PVE02"', content)

        explicit = {
            "ip": "192.0.2.40",
            "label": "bmc-40",
            "type": "idrac",
            "display_name": "  Operator Chosen  ",
            "name": "Observed Name",
        }
        self.assertEqual(_physical_display_name_for(explicit, {}, {}), "Operator Chosen")
        self.assertEqual(
            _physical_display_name_for(
                {"ip": "192.0.2.41", "label": "bmc-41", "type": "idrac", "name": "Observed Name"},
                {},
                {},
            ),
            "Observed Name",
        )
        self.assertEqual(
            _physical_display_name_for(
                {"ip": "192.0.2.42", "label": "storage-primary", "type": "idrac"},
                {},
                {},
            ),
            "",
        )
        self.assertEqual(_physical_display_name_for([], {}, {}), "")

        reverse_physical = {
            "second": {"ip": "192.0.2.11", "label": "bmc-11", "type": "idrac"},
            "lab": {
                "ip": "192.0.2.9",
                "label": "bmc-9",
                "type": "idrac",
                "scope": "lab",
            },
            "first": {"ip": "192.0.2.10", "label": "bmc-10", "type": "idrac"},
        }
        reverse_pve = {
            "pve02": {"ip": "192.0.2.27"},
            "pve01": {"ip": "192.0.2.26"},
        }
        self.assertEqual(
            _physical_display_name_for(reverse_physical["first"], reverse_physical, reverse_pve),
            "iDRAC-PVE01",
        )
        self.assertEqual(
            _physical_display_name_for(reverse_physical["second"], reverse_physical, reverse_pve),
            "iDRAC-PVE02",
        )

        fallback_cases = (
            (
                {
                    "ip": "",
                    "label": "ilo",
                    "type": "ilo",
                    "hostname": " ilo rack/7 ",
                    "service_tag": "service tag",
                },
                "iLO-ILO-RACK-7",
            ),
            ({"ip": "", "label": "ipmi8", "type": "ipmi", "service_tag": " srv/42 "}, "IPMI-SRV-42"),
            ({"ip": "192.0.2.44", "label": "192.0.2.44", "type": "bmc"}, "BMC-44"),
            ({"ip": "192.0.2.45", "label": "bmc", "type": "bmc"}, "BMC-45"),
            ({"ip": "192.0.2.46", "label": "idrac", "type": "idrac"}, "iDRAC-46"),
            ({"ip": "192.0.2.47", "label": "ilo", "type": "ilo"}, "iLO-47"),
            ({"ip": "192.0.2.48", "label": "ipmi", "type": "ipmi"}, "IPMI-48"),
            ({"ip": "192.0.2.49", "label": "switch", "type": "switch"}, ""),
        )
        for fallback_device, expected in fallback_cases:
            with self.subTest(fallback_device=fallback_device):
                self.assertEqual(_physical_display_name_for(fallback_device, {}, {}), expected)

        configured_physical = {
            "second": {"ip": "192.0.2.51", "label": "idrac-51", "type": "idrac"},
            "first": {"ip": "192.0.2.50", "label": "idrac-50", "type": "idrac"},
            "malformed": {
                "ip": "not-an-ip",
                "label": "idrac-99",
                "type": "idrac",
                "service_tag": "srv 99",
            },
        }
        configured = SimpleNamespace(
            pve_nodes=["192.0.2.61", "192.0.2.60"],
            pve_node_names=["cluster b"],
        )
        self.assertEqual(
            _physical_display_name_for(configured_physical["first"], configured_physical, {}, configured),
            "iDRAC-PVE02",
        )
        self.assertEqual(
            _physical_display_name_for(configured_physical["second"], configured_physical, {}, configured),
            "iDRAC-CLUSTER-B",
        )
        self.assertEqual(
            _physical_display_name_for(configured_physical["malformed"], configured_physical, {}, configured),
            "iDRAC-SRV-99",
        )

    def test_runtime_physical_display_label_never_exposes_generic_bmc_primary_name(self):
        from ast import Import, ImportFrom, parse
        from pathlib import Path
        from types import SimpleNamespace

        from freq.core import host_identity
        from freq.core.types import FleetBoundaries, PhysicalDevice, PVENode
        from freq.modules import serve

        self.assertIs(
            serve._operator_physical_display_label,
            host_identity.operator_physical_display_label,
        )
        operator_physical_display_label = host_identity.operator_physical_display_label

        repo_root = Path(__file__).resolve().parents[1]
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        core_tree = parse((repo_root / "freq/core/host_identity.py").read_text())
        serve_moved_names = {
            "_physical_ip_sort_key",
            "_generic_physical_label",
            "_bmc_display_prefix",
            "_node_display_name",
            "_operator_physical_display_label",
        }
        core_moved_names = {
            "_physical_ip_sort_key",
            "_generic_physical_label",
            "_bmc_display_prefix",
            "_node_display_name",
            "operator_physical_display_label",
        }
        serve_defs = {node.name for node in serve_tree.body if hasattr(node, "name")}
        core_defs = {node.name for node in core_tree.body if hasattr(node, "name")}
        self.assertFalse(serve_moved_names & serve_defs)
        self.assertTrue(core_moved_names <= core_defs)

        core_imports = []
        for node in core_tree.body:
            if isinstance(node, Import):
                core_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom):
                core_imports.append(node.module or "")
        self.assertEqual(sorted(core_imports), ["ipaddress", "re"])

        def device(key, ip, label, device_type="idrac", **overrides):
            return PhysicalDevice(
                key=key,
                ip=ip,
                label=label,
                device_type=device_type,
                **overrides,
            )

        def config(fleet_boundaries, *, pve_nodes=None, pve_node_names=None):
            return SimpleNamespace(
                fleet_boundaries=fleet_boundaries,
                pve_nodes=list(pve_nodes or []),
                pve_node_names=list(pve_node_names or []),
            )

        fb = FleetBoundaries()
        fb.physical = {
            "lab_bmc": device("lab_bmc", "192.0.2.1", "bmc-1", scope="lab"),
            "bmc_10": device("bmc_10", "192.0.2.10", "bmc-10"),
            "bmc_11": device("bmc_11", "192.0.2.11", "bmc-11"),
        }
        fb.pve_nodes = {
            "pve02": PVENode(name="pve02", ip="192.0.2.27"),
            "pve01": PVENode(name="pve01", ip="192.0.2.26"),
        }
        cfg = config(fb)

        self.assertEqual(operator_physical_display_label(cfg, fb.physical["bmc_10"]), "iDRAC-PVE01")
        self.assertEqual(operator_physical_display_label(cfg, fb.physical["bmc_11"]), "iDRAC-PVE02")

        explicit = device(
            "explicit",
            "192.0.2.40",
            "bmc-40",
            display_name="  Operator Chosen  ",
        )
        self.assertEqual(
            operator_physical_display_label(config(FleetBoundaries()), explicit, "observed-name"),
            "  Operator Chosen  ",
        )

        custom = device("custom", "192.0.2.41", "storage-primary")
        self.assertEqual(
            operator_physical_display_label(config(FleetBoundaries()), custom, "observed-name"),
            "storage-primary",
        )

        observed = device("observed", "192.0.2.42", "idrac_42")
        self.assertEqual(
            operator_physical_display_label(config(FleetBoundaries()), observed, "Observed Rack BMC"),
            "Observed Rack BMC",
        )

        fallback_cases = (
            (
                device("ilo", "", "ilo-7", "ilo", hostname=" ilo rack/7 "),
                "iLO-ILO-RACK-7",
            ),
            (
                device("ipmi", "", "ipmi8", "ipmi", service_tag=" srv/42 "),
                "IPMI-SRV-42",
            ),
            (device("bmc", "192.0.2.44", "192.0.2.44", "bmc"), "BMC-44"),
            (device("bare-bmc", "192.0.2.45", "bmc", "bmc"), "BMC-45"),
            (device("bare-idrac", "192.0.2.46", "idrac", "idrac"), "iDRAC-46"),
            (device("bare-ilo", "192.0.2.47", "ilo", "ilo"), "iLO-47"),
            (device("bare-ipmi", "192.0.2.48", "ipmi", "ipmi"), "IPMI-48"),
            (device("empty", "", "bmc-9", "bmc"), "bmc-9"),
            (device("switch", "192.0.2.49", "switch", "switch"), "switch"),
        )
        for fallback_device, expected in fallback_cases:
            with self.subTest(fallback_device=fallback_device.key):
                self.assertEqual(
                    operator_physical_display_label(config(FleetBoundaries()), fallback_device),
                    expected,
                )

        fallback_fb = FleetBoundaries()
        fallback_fb.physical = {
            "second": device("second", "192.0.2.51", "idrac-51"),
            "first": device("first", "192.0.2.50", "idrac-50"),
            "malformed": device(
                "malformed",
                "not-an-ip",
                "idrac-99",
                service_tag="srv 99",
            ),
        }
        fallback_cfg = config(
            fallback_fb,
            pve_nodes=["192.0.2.61", "192.0.2.60"],
            pve_node_names=["cluster b"],
        )
        self.assertEqual(
            operator_physical_display_label(fallback_cfg, fallback_fb.physical["first"]),
            "iDRAC-PVE02",
        )
        self.assertEqual(
            operator_physical_display_label(fallback_cfg, fallback_fb.physical["second"]),
            "iDRAC-CLUSTER-B",
        )
        self.assertEqual(
            operator_physical_display_label(fallback_cfg, fallback_fb.physical["malformed"]),
            "iDRAC-SRV-99",
        )

    def test_vm_create_network_catalog_does_not_infer_site_from_private_ips(self):
        from freq.api import vm as vm_api
        from freq.core.config import FreqConfig
        from freq.core.types import Host

        cfg = FreqConfig()
        cfg.pve_nodes = ["192.168.50.10"]
        cfg.pve_node_names = ["pve-a"]
        cfg.hosts = [
            Host(ip="192.168.50.20", label="app", htype="linux", all_ips=["192.168.50.20", "172.16.10.20"]),
            Host(ip="10.42.7.30", label="db", htype="linux"),
        ]

        payload = vm_api._vm_create_options_payload(cfg)

        self.assertEqual(payload["schema_version"], 4)
        self.assertEqual(payload["vlans"], [])
        self.assertEqual(payload["network_profiles"], [])
        self.assertTrue(payload["network_policy"]["network_setup_required"])
        self.assertFalse(payload["network_policy"]["site_inference"])


if __name__ == "__main__":
    unittest.main()
