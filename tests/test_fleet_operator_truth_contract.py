"""Operator-truth contracts for fleet placement, probes, and logs.

These tests pin the DC01 regressions found during the VM100 install:
lab physical devices must not appear as core systems, unmanaged
inventory-only rows must not drive doctor/API probe failures, and
optional dashboard enrichment must not look like a service-breaking SSH
error in the logs.
"""

import tempfile
import unittest
from pathlib import Path

from freq.core.config import load_fleet_boundaries


REPO_ROOT = Path(__file__).parent.parent


class TestFleetPhysicalScope(unittest.TestCase):
    """Fleet-boundary physical devices carry core/lab scope."""

    def test_legacy_lab_physical_scope_is_inferred(self):
        with tempfile.TemporaryDirectory(prefix="freq-physical-scope-") as tmp:
            path = Path(tmp) / "fleet-boundaries.toml"
            path.write_text(
                "\n".join(
                    [
                        "[physical.truenas]",
                        'ip = "10.25.255.2"',
                        'label = "truenas"',
                        'type = "nas"',
                        "",
                        "[physical.truenas_lab]",
                        'ip = "10.25.255.200"',
                        'label = "truenas-lab"',
                        'type = "nas"',
                    ]
                )
            )

            fb = load_fleet_boundaries(str(path))

        self.assertEqual(fb.physical["truenas"].scope, "core")
        self.assertEqual(fb.physical["truenas_lab"].scope, "lab")

    def test_dashboard_splits_lab_physical_from_core(self):
        src = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        self.assertIn("_isLabPhysical", src)
        self.assertIn("corePhysicals", src)
        self.assertIn("labPhysicals", src)
        self.assertIn("infraLabels", src)


class TestFleetProbeNoiseContract(unittest.TestCase):
    """Probe/log code must preserve operator truth."""

    def test_doctor_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "core" / "doctor.py").read_text()
        self.assertIn("hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)
        self.assertIn("hosts_for_check = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)

    def test_api_health_fallback_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        self.assertIn("active_hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)
        self.assertIn("pool.submit(_probe_host, h): h for h in active_hosts", src)

    def test_init_deploy_phase_uses_managed_hosts_only(self):
        src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn("managed_hosts = [h for h in cfg.hosts if getattr(h, \"managed\", True)]", src)
        self.assertIn("linux_hosts = [h for h in managed_hosts", src)

    def test_optional_dashboard_enrichment_downgrades_ssh_log_severity(self):
        ssh_src = (REPO_ROOT / "freq" / "core" / "ssh.py").read_text()
        serve_src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("failure_log_level: str = \"error\"", ssh_src)
        self.assertIn("optional=normalized_failure_log_level not in", ssh_src)
        self.assertGreaterEqual(serve_src.count('failure_log_level="warn"'), 2)

    def test_health_probe_completion_logs_state_counts_not_catchall_unreachable(self):
        src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
        self.assertIn("state_counts = {", src)
        self.assertIn("stale=state_counts[STATE_STALE]", src)
        self.assertIn("auth_failed=state_counts[STATE_AUTH_FAILED]", src)
        self.assertIn("unreachable=state_counts[STATE_UNREACHABLE]", src)
        self.assertIn('f"{h_e[\'label\']} is now {cur_state}"', src)
        self.assertNotIn('unreachable_count = sum(1 for h in host_data if h.get("status") != "healthy")', src)


if __name__ == "__main__":
    unittest.main()
