"""Setup status truth tests.

Proves:
1. Setup status uses actual resolved key path (not hardcoded ed25519)
2. Setup status reports key readability (not just existence)
3. Setup status includes setup_health summary
4. Setup health distinguishes configured/partial/unconfigured
5. "configured" requires .initialized marker (not just config items)
6. Response includes initialized field for partial-init distinction
"""

import json
import os
import sys
import tempfile
import types
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from tests.case_matrix import run_case_matrix  # noqa: E402, I001


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

    def _case_includes_setup_health(self):
        src = self._handler_src()
        self.assertIn("setup_health", src)

    def _case_distinguishes_three_states(self):
        src = self._handler_src()
        self.assertIn('"configured"', src)
        self.assertIn('"partial"', src)
        self.assertIn('"unconfigured"', src)

    def _case_configured_requires_key_and_hosts(self):
        """'configured' state must require readable key + hosts + nodes."""
        src = self._handler_src()
        config_block_idx = src.index('setup_health = "configured"')
        preceding = src[max(0, config_block_idx - 800):config_block_idx]
        self.assertIn("key_readable", preceding)
        self.assertIn("has_hosts", preceding)

    def _case_configured_requires_initialized_marker(self):
        """'configured' must require .initialized — partial init is NOT configured."""
        src = self._handler_src()
        config_block_idx = src.index('setup_health = "configured"')
        preceding = src[max(0, config_block_idx - 800):config_block_idx]
        self.assertIn("is_initialized", preceding,
                       "'configured' state must check .initialized marker")

    def _case_response_includes_initialized_field(self):
        """Response must include 'initialized' boolean for UI truth."""
        src = self._handler_src()
        self.assertIn('"initialized"', src,
                       "Response must include initialized field")

    def _case_response_includes_web_setup_complete_field(self):
        """Response must include 'web_setup_complete' boolean for marker distinction."""
        src = self._handler_src()
        self.assertIn('"web_setup_complete"', src,
                       "Response must include web_setup_complete field")

    def _case_response_includes_dashboard_account_health(self):
        """Setup status must name dashboard account/hash health without exposing secrets."""
        src = self._handler_src()
        self.assertIn('"dashboard_accounts_configured"', src)
        self.assertIn('"dashboard_passwords_configured"', src)
        self.assertIn('"dashboard_users"', src)
        self.assertIn('"has_password"', src)

    def _case_checks_both_marker_files(self):
        """Must check both .initialized and .web-setup-complete in conf_dir."""
        src = self._handler_src()
        self.assertIn(".initialized", src,
                       "Must check .initialized marker file")
        self.assertIn(".web-setup-complete", src,
                       "Must check .web-setup-complete marker file")

    def _case_web_setup_only_health_tier(self):
        """setup_health must have a 'web-setup-only' tier distinct from 'configured'."""
        src = self._handler_src()
        self.assertIn("web-setup-only", src,
                       "setup_health must include web-setup-only tier")

    def _case_running_init_is_not_reported_as_failed(self):
        """A running Web Init job must not show stale init-failed blocker text."""
        src = self._handler_src()
        self.assertIn("init-running", src)
        self.assertIn("_setup_init_snapshot", src)
        self.assertIn("init_is_running", src)

    def _case_failed_init_artifacts_are_not_reported_as_never_run(self):
        """Generated init artifacts must override the no-marker default reason."""
        src = self._handler_src()
        self.assertIn("_init_blocker_from_artifacts", src)
        self.assertIn("init-failed", src)
        self.assertIn("init_blocker or \"freq init not yet run", src)

    def _case_vm_inventory_annotations_are_not_setup_blockers(self):
        with open(os.path.join(REPO_ROOT, "freq/services/setup_health.py")) as f:
            src = f.read()
        helper = src.split("def init_blocker_from_artifacts", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("unexpected_out_of_contract_vmids", helper)
        self.assertNotIn("blocked by operator VM contract", helper)
        self.assertIn('"operator vm contract" not in str(item).lower()', helper)

    def _case_init_status_prefers_real_failed_check_over_acknowledged_vmids(self):
        from freq.modules.serve import _init_blocker_from_artifacts

        with tempfile.TemporaryDirectory() as td:
            cfg = types.SimpleNamespace(conf_dir=td)
            with open(os.path.join(td, "init-status.json"), "w") as f:
                json.dump(
                    {
                        "initialized": False,
                        "failed_checks": [
                            "Operator VM contract: 0 unexpected out-of-contract PVE VMs (saw 1: 106)",
                            "Phase 8 fleet deployment: 0 failed hosts (saw 1)",
                        ],
                        "out_of_contract_vmids": [400, 404, 802],
                        "unexpected_out_of_contract_vmids": [],
                    },
                    f,
                )

            reason = _init_blocker_from_artifacts(cfg)

        self.assertIn("Phase 8 fleet deployment", reason)
        self.assertNotIn("operator VM contract", reason)

    def _case_legacy_vm_contract_only_status_is_not_a_blocker(self):
        from freq.modules.serve import _init_blocker_from_artifacts

        with tempfile.TemporaryDirectory() as td:
            cfg = types.SimpleNamespace(conf_dir=td)
            with open(os.path.join(td, "init-status.json"), "w") as f:
                json.dump(
                    {
                        "initialized": False,
                        "failed_checks": ["Operator VM contract: 0 unexpected out-of-contract PVE VMs (saw 1: 106)"],
                        "reason": "Operator VM contract failed: unexpected out-of-contract PVE VM 106",
                        "out_of_contract_vmids": [106],
                        "unexpected_out_of_contract_vmids": [106],
                    },
                    f,
                )
            with open(os.path.join(td, "pve-inventory.toml"), "w") as f:
                f.write('[[vms]]\nvmid = 106\nname = "legacy-guest"\n')
            with open(os.path.join(td, "fleet-boundaries.toml"), "w") as f:
                f.write("[categories.production]\nvmids = [900]\n")

            reason = _init_blocker_from_artifacts(cfg)

        self.assertEqual(reason, "")

    def _case_init_blocker_artifact_matrix(self):
        import ast
        import inspect

        from freq.modules import serve
        from freq.services import setup_health

        _init_blocker_from_artifacts = serve._init_blocker_from_artifacts
        assert _init_blocker_from_artifacts is setup_health.init_blocker_from_artifacts
        assert not any(
            isinstance(node, ast.FunctionDef)
            and node.name == "_init_blocker_from_artifacts"
            for node in ast.walk(ast.parse(inspect.getsource(serve)))
        )
        service_tree = ast.parse(inspect.getsource(setup_health))
        assert {
            alias.name
            for node in ast.walk(service_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } == {"datetime", "json", "os"}
        assert [
            (node.module, [alias.name for alias in node.names])
            for node in ast.walk(service_tree)
            if isinstance(node, ast.ImportFrom)
        ] == [
            ("freq.core.config", ["load_toml"]),
            ("freq", ["__version__"]),
        ]

        missing = object()

        def blocker(*, status=missing, inventory=False, boundaries=False):
            with tempfile.TemporaryDirectory() as td:
                status_path = os.path.join(td, "init-status.json")
                if status == "directory":
                    os.mkdir(status_path)
                elif status == "invalid":
                    with open(status_path, "w") as handle:
                        handle.write("{invalid")
                elif status is not missing:
                    with open(status_path, "w") as handle:
                        json.dump(status, handle)
                if inventory:
                    with open(os.path.join(td, "pve-inventory.toml"), "w") as handle:
                        handle.write('[[vms]]\nvmid = 106\nname = "legacy-guest"\n')
                if boundaries:
                    with open(os.path.join(td, "fleet-boundaries.toml"), "w") as handle:
                        handle.write("[categories.production]\nvmids = [900]\n")
                return _init_blocker_from_artifacts(types.SimpleNamespace(conf_dir=td))

        assert blocker() == ""
        assert blocker(status="directory") == ""
        assert blocker(status="invalid") == ""
        assert blocker(
            status={
                "initialized": True,
                "failed_checks": ["Phase 12 verification failed"],
                "reason": "init failed",
            },
            inventory=True,
        ) == ""
        assert blocker(
            status={
                "initialized": False,
                "failed_checks": [
                    "OPERATOR VM CONTRACT annotation",
                    "OUT-OF-CONTRACT PVE VM annotation",
                    "Phase 8 fleet deployment failed",
                    "Phase 9 later failure",
                ],
                "reason": "lower-priority reason",
            }
        ) == "freq init ran and failed verification: Phase 8 fleet deployment failed"
        assert blocker(
            status={
                "initialized": False,
                "failed_checks": ["Operator VM contract annotation"],
                "reason": "Phase 10 validation failed",
            }
        ) == "freq init ran and failed verification: Phase 10 validation failed"
        assert blocker(
            status={
                "initialized": False,
                "failed_checks": ["Operator VM contract annotation"],
                "reason": "out-of-contract PVE VM annotation",
            },
            inventory=True,
            boundaries=True,
        ) == ""
        assert blocker(
            status="invalid",
            inventory=True,
        ) == "freq init ran but did not mark initialized; run freq init --check for the failing check"
        assert blocker(status="invalid", boundaries=True) == ""

    def _case_setup_marker_truth_matrix(self):
        import ast
        import inspect

        from freq.modules import serve
        from freq.services import setup_health

        _setup_marker_exists = serve._setup_marker_exists
        _zero_state_setup_complete = serve._zero_state_setup_complete
        assert _setup_marker_exists is setup_health.setup_marker_exists
        assert _zero_state_setup_complete is setup_health.zero_state_setup_complete
        assert not {
            node.name
            for node in ast.walk(ast.parse(inspect.getsource(serve)))
            if isinstance(node, ast.FunctionDef)
            and node.name in {"_setup_marker_exists", "_zero_state_setup_complete"}
        }
        assert "freq.modules" not in inspect.getsource(setup_health)

        markers = {
            "setup": ("data", "setup-complete"),
            "initialized": ("conf", ".initialized"),
            "web": ("conf", ".web-setup-complete"),
        }

        def marker_truth(*names, directories=()):
            with tempfile.TemporaryDirectory() as td:
                roots = {
                    "data": os.path.join(td, "data"),
                    "conf": os.path.join(td, "conf"),
                }
                for root in roots.values():
                    os.mkdir(root)
                for name in names:
                    root, filename = markers[name]
                    path = os.path.join(roots[root], filename)
                    if name in directories:
                        os.mkdir(path)
                    else:
                        with open(path, "w"):
                            pass
                cfg = types.SimpleNamespace(
                    data_dir=roots["data"],
                    conf_dir=roots["conf"],
                )
                return _setup_marker_exists(cfg), _zero_state_setup_complete(cfg)

        assert marker_truth() == (False, False)
        for marker in markers:
            assert marker_truth(marker) == (True, False)
            assert marker_truth(marker, directories=(marker,)) == (False, False)
        assert marker_truth("setup", "initialized") == (True, False)
        assert marker_truth("setup", "web") == (True, False)
        assert marker_truth("initialized", "web") == (True, True)
        assert marker_truth("setup", "initialized", "web") == (True, True)
        assert marker_truth(
            "initialized",
            "web",
            directories=("initialized", "web"),
        ) == (False, False)
        assert marker_truth(
            "initialized",
            "web",
            directories=("web",),
        ) == (True, False)

        with tempfile.TemporaryDirectory() as td:
            data_dir = os.path.join(td, "data")
            conf_dir = os.path.join(td, "conf")
            os.mkdir(data_dir)
            os.mkdir(conf_dir)
            with open(os.path.join(data_dir, "unrelated"), "w"):
                pass
            cfg = types.SimpleNamespace(data_dir=data_dir, conf_dir=conf_dir)
            assert _setup_marker_exists(cfg) is False
            assert _zero_state_setup_complete(cfg) is False


SETUP_HEALTH_SUMMARY_CASES = (
    "_case_includes_setup_health",
    "_case_distinguishes_three_states",
    "_case_configured_requires_key_and_hosts",
    "_case_configured_requires_initialized_marker",
    "_case_response_includes_initialized_field",
    "_case_response_includes_web_setup_complete_field",
    "_case_response_includes_dashboard_account_health",
    "_case_checks_both_marker_files",
    "_case_web_setup_only_health_tier",
    "_case_running_init_is_not_reported_as_failed",
    "_case_failed_init_artifacts_are_not_reported_as_never_run",
    "_case_vm_inventory_annotations_are_not_setup_blockers",
    "_case_init_status_prefers_real_failed_check_over_acknowledged_vmids",
    "_case_legacy_vm_contract_only_status_is_not_a_blocker",
    "_case_init_blocker_artifact_matrix",
    "_case_setup_marker_truth_matrix",
)


class TestSetupHealthSummaryMatrix(unittest.TestCase):
    def test_setup_health_summary_matrix(self):
        self.assertEqual(len(SETUP_HEALTH_SUMMARY_CASES), 16)
        run_case_matrix(self, TestSetupHealthSummary, SETUP_HEALTH_SUMMARY_CASES)


class TestWebInitRuntimeHandoff(unittest.TestCase):
    """Web Init must leave one managed dashboard runtime after init exits."""

    def test_setup_init_job_schedules_runtime_handoff(self):
        with open(os.path.join(REPO_ROOT, "freq/services/setup_progress.py")) as f:
            worker = f.read()
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            serve = f.read()
        job = worker.split("def run_setup_init_job", 1)[1]
        self.assertIn("FREQ_WEB_INIT", job)
        self.assertIn("runtime.schedule_runtime_handoff", job)
        self.assertIn("scheduled dashboard handoff to freq-serve.service", job)
        self.assertIn(
            "schedule_runtime_handoff=lambda cfg: _schedule_setup_runtime_handoff(cfg)",
            serve,
        )

    def test_runtime_handoff_stops_setup_listener_before_restart(self):
        with open(os.path.join(REPO_ROOT, "freq/services/setup_handoff.py")) as f:
            src = f.read()
        helper = src.split("def schedule_setup_runtime_handoff", 1)[1]
        self.assertIn("systemd-run", helper)
        self.assertIn("pve-freq-setup.service", helper)
        self.assertIn('"disable", "--now"', helper)
        self.assertIn('"rm", "-f", setup_unit', helper)
        self.assertIn('"rm", "-rf", bootstrap_tls_dir', helper)
        self.assertIn('"systemctl", "daemon-reload"', helper)
        self.assertIn("_finalize_web_init_runtime_ownership", helper)
        self.assertLess(
            helper.index("_finalize_web_init_runtime_ownership"),
            helper.index('"disable", "--now"'),
        )
        self.assertIn("freq-serve.service", helper)

    def test_setup_status_turns_state_read_failure_into_blocked_truth(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        status = src.split("def _serve_setup_status", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("setup_state_unreadable", status)
        self.assertIn('zero_state = "blocked"', status)
        self.assertIn('"code": "setup_state_unreadable"', status)

    def test_web_init_does_not_start_managed_service_before_handoff(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/init_cmd.py")) as f:
            src = f.read()
        block = src.split("# \u2500\u2500 9k: Dashboard Service", 1)[1].split("# \u2500\u2500 9k.1: Watchdog Service", 1)[0]
        self.assertIn('os.environ.get("FREQ_WEB_INIT") == "1"', block)
        self.assertIn("handoff will start", block)
        self.assertLess(
            block.index('os.environ.get("FREQ_WEB_INIT") == "1"'),
            block.index('["systemctl", "start", "freq-serve"]'),
        )


class TestFleetNicProbeContract(unittest.TestCase):
    """Fleet NIC inventory should not timeout on slow per-VM qm config loops."""

    def test_nic_inventory_reads_pve_config_files(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        block = src.split("# VM NIC data", 1)[1].split("duration = round", 1)[0]
        self.assertIn("/etc/pve/qemu-server/", block)
        self.assertNotIn("qm config", block)

    def test_vm_tag_inventory_reads_pve_config_files(self):
        with open(os.path.join(REPO_ROOT, "freq/services/pve_tags.py")) as f:
            src = f.read()
        block = src.split("def _bg_fetch_vm_tags", 1)[1].split("result = {\"tags\"", 1)[0]
        self.assertIn("/etc/pve/qemu-server/", block)
        self.assertNotIn("qm config", block)


if __name__ == "__main__":
    unittest.main()
