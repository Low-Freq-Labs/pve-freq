import unittest
from types import SimpleNamespace


class TestHostScope(unittest.TestCase):
    def test_managed_probe_hosts_excludes_operator_and_pve_guest_rows(self):
        from freq.core.host_scope import managed_probe_hosts

        cfg = SimpleNamespace(
            pve_nodes=["10.25.255.26", "10.25.255.27", "10.25.255.28"],
            hosts=[
                SimpleNamespace(label="pve01", ip="10.25.255.26", htype="pve", vmid=0, managed=True),
                SimpleNamespace(label="pve-freq", ip="10.25.255.50", htype="pve", vmid=100, managed=True),
                SimpleNamespace(label="nexus", ip="10.25.255.8", htype="linux", vmid=900, managed=True),
                SimpleNamespace(label="lab-pve1", ip="10.25.10.202", htype="pve", vmid=5002, managed=True),
                SimpleNamespace(label="managed-app", ip="10.25.255.44", htype="linux", vmid=44, managed=True),
                SimpleNamespace(label="inventory-only", ip="10.25.255.45", htype="linux", vmid=45, managed=False),
            ],
        )

        labels = [h.label for h in managed_probe_hosts(cfg)]

        self.assertEqual(labels, ["pve01", "managed-app"])


if __name__ == "__main__":
    unittest.main()
