import json
import os
import tempfile
import unittest
from types import SimpleNamespace


class _Boundaries:
    def categorize(self, vmid):
        if vmid in {400, 802}:
            return ("out_of_contract", "probe")
        if vmid == 9000:
            return ("templates", "template")
        return ("prod", "core")


class TestWatchdogFleetContract(unittest.TestCase):
    def _cfg(self, root):
        return SimpleNamespace(
            data_dir=root,
            pve_nodes=["10.25.255.26", "10.25.255.27", "10.25.255.28"],
            fleet_boundaries=_Boundaries(),
            hosts=[
                SimpleNamespace(label="pve01", ip="10.25.255.26", vmid=0, htype="pve", managed=True),
                SimpleNamespace(label="pve-freq", ip="10.25.255.50", vmid=100, htype="pve", managed=True),
                SimpleNamespace(label="nexus", ip="10.25.255.8", vmid=999, htype="linux", managed=True),
                SimpleNamespace(label="blue", ip="10.25.255.75", vmid=802, htype="linux", managed=True),
                SimpleNamespace(label="runescapebotvm", ip="10.25.66.69", vmid=400, htype="linux", managed=True),
                SimpleNamespace(label="lab-pve2", ip="10.25.10.203", vmid=5003, htype="pve", managed=True),
                SimpleNamespace(label="managed-app", ip="10.25.255.44", vmid=44, htype="linux", managed=True),
            ],
        )

    def _write_cache(self, root, name, data):
        cache_dir = os.path.join(root, "cache")
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump({"ts": 4_000_000_000, "data": data}, f)

    def test_health_cache_hard_red_ignores_operator_and_out_of_contract_hosts(self):
        from freq.modules import watchdog

        with tempfile.TemporaryDirectory() as root:
            cfg = self._cfg(root)
            self._write_cache(
                root,
                "health",
                {
                    "hosts": [
                        {"label": "pve-freq", "ip": "10.25.255.50", "state": "auth_failed", "status": "auth_failed"},
                        {"label": "nexus", "ip": "10.25.255.8", "state": "auth_failed", "status": "auth_failed"},
                        {"label": "blue", "ip": "10.25.255.75", "state": "auth_failed", "status": "auth_failed"},
                        {"label": "runescapebotvm", "ip": "10.25.66.69", "state": "unreachable", "status": "unreachable"},
                        {"label": "lab-pve2", "ip": "10.25.10.203", "state": "auth_failed", "status": "auth_failed"},
                        {"label": "pve01", "ip": "10.25.255.26", "state": "live", "status": "healthy"},
                    ]
                },
            )

            check, _data = watchdog._check_health_cache(cfg, max_age=999999999)

        self.assertEqual(check.status, "pass")
        self.assertIn("6 host", check.summary)

    def test_health_cache_still_fails_for_managed_contract_host(self):
        from freq.modules import watchdog

        with tempfile.TemporaryDirectory() as root:
            cfg = self._cfg(root)
            self._write_cache(
                root,
                "health",
                {
                    "hosts": [
                        {"label": "managed-app", "ip": "10.25.255.44", "state": "auth_failed", "status": "auth_failed"},
                    ]
                },
            )

            check, _data = watchdog._check_health_cache(cfg, max_age=999999999)

        self.assertEqual(check.status, "fail")
        self.assertIn("managed-app", str(check.evidence))


if __name__ == "__main__":
    unittest.main()
