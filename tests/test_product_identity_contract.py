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
        from pathlib import Path
        from types import SimpleNamespace

        from freq.core.types import FleetBoundaries
        from freq.modules.hosts import _auto_populate_fleet_boundaries

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

    def test_runtime_physical_display_label_never_exposes_generic_bmc_primary_name(self):
        from types import SimpleNamespace

        from freq.core.types import FleetBoundaries, PhysicalDevice, PVENode
        from freq.modules.serve import _operator_physical_display_label

        fb = FleetBoundaries()
        fb.physical = {
            "bmc_10": PhysicalDevice(key="bmc_10", ip="192.0.2.10", label="bmc-10", device_type="idrac"),
            "bmc_11": PhysicalDevice(key="bmc_11", ip="192.0.2.11", label="bmc-11", device_type="idrac"),
        }
        fb.pve_nodes = {
            "pve01": PVENode(name="pve01", ip="192.0.2.26"),
            "pve02": PVENode(name="pve02", ip="192.0.2.27"),
        }
        cfg = SimpleNamespace(fleet_boundaries=fb, pve_nodes=[], pve_node_names=[])

        self.assertEqual(_operator_physical_display_label(cfg, fb.physical["bmc_10"]), "iDRAC-PVE01")
        self.assertEqual(_operator_physical_display_label(cfg, fb.physical["bmc_11"]), "iDRAC-PVE02")

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
