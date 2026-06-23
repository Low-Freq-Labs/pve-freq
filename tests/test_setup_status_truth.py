"""Setup status truth tests.

Proves:
1. Setup status uses actual resolved key path (not hardcoded ed25519)
2. Setup status reports key readability (not just existence)
3. Setup status includes setup_health summary
4. Setup health distinguishes configured/partial/unconfigured
5. "configured" requires .initialized marker (not just config items)
6. Response includes initialized field for partial-init distinction
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSetupStatusKeyTruth(unittest.TestCase):
    """Setup status must use the actual resolved SSH key path."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _serve_setup_status")[1].split("def _serve_")[0]

    def test_uses_resolved_key_path(self):
        """Must use cfg.ssh_key_path, not hardcoded freq_id_ed25519."""
        src = self._handler_src()
        self.assertIn("cfg.ssh_key_path", src,
                       "Must use resolved key path from config")
        self.assertNotIn("freq_id_ed25519", src,
                          "Must not hardcode ed25519 key name")

    def test_redetects_key_if_missing(self):
        """Must re-detect key path if cached path is stale (key created after serve start)."""
        src = self._handler_src()
        self.assertIn("_detect_ssh_key", src,
                       "Must re-detect key if initial path is missing")

    def test_reports_key_readable(self):
        """Must check if current user can READ the key, not just if file exists."""
        src = self._handler_src()
        self.assertIn("ssh_key_readable", src)
        self.assertIn("os.access", src)

    def test_includes_host_count(self):
        src = self._handler_src()
        self.assertIn("host_count", src)


class TestSetupHealthSummary(unittest.TestCase):
    """Setup status must include honest health summary."""

    def _handler_src(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split("def _serve_setup_status")[1].split("def _serve_")[0]

    def test_includes_setup_health(self):
        src = self._handler_src()
        self.assertIn("setup_health", src)

    def test_distinguishes_three_states(self):
        src = self._handler_src()
        self.assertIn('"configured"', src)
        self.assertIn('"partial"', src)
        self.assertIn('"unconfigured"', src)

    def test_configured_requires_key_and_hosts(self):
        """'configured' state must require readable key + hosts + nodes."""
        src = self._handler_src()
        config_block_idx = src.index('setup_health = "configured"')
        preceding = src[max(0, config_block_idx - 800):config_block_idx]
        self.assertIn("key_readable", preceding)
        self.assertIn("has_hosts", preceding)

    def test_configured_requires_initialized_marker(self):
        """'configured' must require .initialized — partial init is NOT configured."""
        src = self._handler_src()
        config_block_idx = src.index('setup_health = "configured"')
        preceding = src[max(0, config_block_idx - 800):config_block_idx]
        self.assertIn("is_initialized", preceding,
                       "'configured' state must check .initialized marker")

    def test_response_includes_initialized_field(self):
        """Response must include 'initialized' boolean for UI truth."""
        src = self._handler_src()
        self.assertIn('"initialized"', src,
                       "Response must include initialized field")

    def test_response_includes_web_setup_complete_field(self):
        """Response must include 'web_setup_complete' boolean for marker distinction."""
        src = self._handler_src()
        self.assertIn('"web_setup_complete"', src,
                       "Response must include web_setup_complete field")

    def test_response_includes_dashboard_account_health(self):
        """Setup status must name dashboard account/hash health without exposing secrets."""
        src = self._handler_src()
        self.assertIn('"dashboard_accounts_configured"', src)
        self.assertIn('"dashboard_passwords_configured"', src)
        self.assertIn('"dashboard_users"', src)
        self.assertIn('"has_password"', src)

    def test_checks_both_marker_files(self):
        """Must check both .initialized and .web-setup-complete in conf_dir."""
        src = self._handler_src()
        self.assertIn(".initialized", src,
                       "Must check .initialized marker file")
        self.assertIn(".web-setup-complete", src,
                       "Must check .web-setup-complete marker file")

    def test_web_setup_only_health_tier(self):
        """setup_health must have a 'web-setup-only' tier distinct from 'configured'."""
        src = self._handler_src()
        self.assertIn("web-setup-only", src,
                       "setup_health must include web-setup-only tier")

    def test_running_init_is_not_reported_as_failed(self):
        """A running Web Init job must not show stale init-failed blocker text."""
        src = self._handler_src()
        self.assertIn("init-running", src)
        self.assertIn("_setup_init_snapshot", src)
        self.assertIn("init_is_running", src)

    def test_failed_init_artifacts_are_not_reported_as_never_run(self):
        """Generated init artifacts must override the no-marker default reason."""
        src = self._handler_src()
        self.assertIn("_init_blocker_from_artifacts", src)
        self.assertIn("init-failed", src)
        self.assertIn("init_blocker or \"freq init not yet run", src)

    def test_operator_contract_blocker_names_out_of_contract(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        helper = src.split("def _init_blocker_from_artifacts", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("out_of_contract", helper)
        self.assertIn("operator VM contract", helper)
        self.assertIn("out-of-contract PVE VM", helper)


class TestWebInitRuntimeHandoff(unittest.TestCase):
    """Web Init must leave one managed dashboard runtime after init exits."""

    def test_setup_init_job_schedules_runtime_handoff(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        job = src.split("def _run_setup_init_job", 1)[1].split("\ndef _init_blocker_from_artifacts", 1)[0]
        self.assertIn("FREQ_WEB_INIT", job)
        self.assertIn("_schedule_setup_runtime_handoff", job)
        self.assertIn("scheduled dashboard handoff to freq-serve.service", job)

    def test_runtime_handoff_stops_setup_listener_before_restart(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        helper = src.split("def _schedule_setup_runtime_handoff", 1)[1].split("\ndef _run_setup_init_job", 1)[0]
        self.assertIn("systemd-run", helper)
        self.assertIn("pve-freq-setup.service", helper)
        self.assertIn("freq-serve.service", helper)
        self.assertIn("kill -TERM", helper)


class TestFleetNicProbeContract(unittest.TestCase):
    """Fleet NIC inventory should not timeout on slow per-VM qm config loops."""

    def test_nic_inventory_reads_pve_config_files(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        block = src.split("# VM NIC data", 1)[1].split("duration = round", 1)[0]
        self.assertIn("/etc/pve/qemu-server/", block)
        self.assertNotIn("qm config", block)

    def test_vm_tag_inventory_reads_pve_config_files(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        block = src.split("def _bg_fetch_vm_tags", 1)[1].split("result = {\"tags\"", 1)[0]
        self.assertIn("/etc/pve/qemu-server/", block)
        self.assertNotIn("qm config", block)


if __name__ == "__main__":
    unittest.main()
