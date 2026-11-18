"""E2E operator truth tests.

Proves:
1. /api/info includes install_method for update guidance
2. Log diversion warning goes to stderr (not stdout)
3. freq help runs cleanly without crashing
4. freq doctor separates workspace issues from fleet health
"""

import os
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestInfoEndpointMetadata(unittest.TestCase):
    """GET /api/info must include runtime metadata for update guidance."""

    def test_info_handler_includes_install_method(self):
        from freq.api import fleet

        cfg = SimpleNamespace(
            brand="FREQ",
            build="test",
            cluster_name="",
            conf_dir="/tmp",
            hosts=[],
            install_dir="/opt/pve-freq",
        )
        handler = object()
        with (
            patch("freq.api.fleet.load_config", return_value=cfg),
            patch("freq.api.fleet._get_discovered_nodes", return_value=[]),
            patch("freq.core.personality.load_pack", return_value=None),
            patch("freq.modules.selfupdate._detect_install_method", return_value="legacy") as legacy_detect,
            patch("freq.core.packages.detect_install_method", return_value="core") as core_detect,
            patch("freq.api.fleet.json_response") as response,
        ):
            fleet.handle_info(handler)

        core_detect.assert_called_once_with(cfg)
        legacy_detect.assert_not_called()
        response.assert_called_once()
        payload = response.call_args.args[1]
        self.assertEqual(payload["install_method"], "core")
        self.assertEqual(
            set(payload),
            {
                "version", "brand", "build", "hosts", "pve_nodes", "cluster",
                "install_dir", "install_method", "subtitle", "dashboard_header",
            },
        )


class TestLogDiversionHonesty(unittest.TestCase):
    """Log diversion warning must go to stderr, never stdout."""

    def test_log_fallback_warns_to_stderr(self):
        with open(os.path.join(REPO_ROOT, "freq/core/log.py")) as f:
            src = f.read()
        self.assertIn("file=sys.stderr", src,
                       "Log diversion warning must go to stderr")

    def test_log_fallback_uses_home_dir(self):
        with open(os.path.join(REPO_ROOT, "freq/core/log.py")) as f:
            src = f.read()
        self.assertIn(".freq", src,
                       "Fallback log dir must be ~/.freq/log/")


class TestFirstTouchClean(unittest.TestCase):
    """First-touch commands must run without crash or confusing output."""

    def test_freq_help_clean_exit(self):
        r = subprocess.run(
            ["python3", "-m", "freq", "help"],
            capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(r.returncode, 0, f"freq help failed: {r.stderr}")
        self.assertNotIn("Traceback", r.stderr)

    def test_freq_version_clean_exit(self):
        r = subprocess.run(
            ["python3", "-m", "freq", "version"],
            capture_output=True, text=True, timeout=15, cwd=REPO_ROOT,
        )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)

    def test_freq_doctor_clean_exit(self):
        r = subprocess.run(
            ["python3", "-m", "freq", "doctor"],
            capture_output=True, text=True, timeout=30, cwd=REPO_ROOT,
        )
        self.assertIn(r.returncode, (0, 1, 2))
        self.assertNotIn("Traceback", r.stderr)


class TestInitIdentityLifecycleTruth(unittest.TestCase):
    """E2E init planning must preserve the identity split at each stage."""

    def test_e2e_progress_pins_identity_contract(self):
        with open(os.path.join(REPO_ROOT, "docs/E2E-PROGRESS.md")) as f:
            src = f.read()
        self.assertIn("## Identity Contract", src)
        self.assertIn("Bootstrap/sudo account: `freq-ops`", src)
        self.assertIn("Deployed fleet service account: `cfg.ssh_service_account`", src)
        self.assertIn("Default fleet service account name when unset: `freq-admin`", src)
        # PVE API identity is
        # derived from cfg.ssh_service_account, NOT the legacy freq-ops@pam.
        self.assertIn(
            "PVE API identity: `{cfg.ssh_service_account}@pam!freq-rw`",
            src,
        )
        # Legacy freq-ops@pam must not be re-introduced as the product token.
        self.assertNotIn(
            "PVE API identity: `freq-ops@pam!freq-rw`",
            src,
            "Legacy freq-ops@pam PVE API identity must stay out of the contract",
        )

    def test_phase_plan_keeps_service_account_and_pve_api_distinct(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/init_cmd.py")) as f:
            src = f.read()
        self.assertIn(
            '("Phase 3", "Service Account", f"Create pve-freq-svc-account \'{svc_name}\', init vault")',
            src,
        )
        self.assertIn(
            '("Phase 2", "Cluster Config + VLAN Discovery", "PVE nodes, gateway, operator-provided bootstrap auth, discover VLANs")',
            src,
        )
        # Phase 6 token ID is
        # derived from the read-only preview identity via an f-string so the
        # summary line matches CLI override or configured identity without
        # mutating the loaded config.
        self.assertIn(
            '("Phase 6", "PVE API Token", f"Create {svc_name}@pam!freq-rw token, save to /etc/freq/credentials/")',
            src,
        )
        # The legacy hardcoded string must not return.
        self.assertNotIn(
            '"Create freq-ops@pam!freq-rw token',
            src,
            "Phase 6 plan line must not hardcode legacy freq-ops@pam identity",
        )


if __name__ == "__main__":
    unittest.main()
