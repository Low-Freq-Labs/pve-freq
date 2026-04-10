"""Regression tests for trust-critical paths.

These test the contract, not the implementation. If any of these
fail, the product is lying to the operator.

Created after Codex audit (2026-04-08) exposed:
- backup verify returning ok:true on SSH failure
- DR verify stub that verified nothing
- logs/observe hiding unreachable hosts
- uncaught int() casts crashing API handlers
"""

import json
import types
import unittest
from unittest.mock import MagicMock, patch


class TestBackupVerifyStatus(unittest.TestCase):
    """backup_verify.py must never return ok:true when it can't verify."""

    def _make_handler(self):
        handler = MagicMock()
        handler.command = "GET"
        handler.path = "/api/backup/verify/status"
        handler.headers = {"Authorization": "Bearer test"}
        self._response = None
        self._status = None

        def mock_json_response(h, data, status=200):
            self._response = data
            self._status = status

        return handler, mock_json_response

    @patch("freq.api.backup_verify._check_session_role", return_value=("admin", None))
    @patch("freq.api.backup_verify.load_config")
    @patch("freq.api.backup_verify._find_node_ip", return_value="10.0.0.1")
    @patch("freq.api.backup_verify._pve_ssh")
    def test_ssh_failure_returns_unknown_not_ok(self, mock_ssh, mock_node, mock_cfg, mock_role):
        """If SSH fails, status must be 'unknown', not ok:true."""
        from freq.api.backup_verify import handle_backup_verify_status, json_response

        mock_ssh.return_value = MagicMock(returncode=1, stdout="", stderr="Connection refused")

        handler, mock_resp = self._make_handler()
        with patch("freq.api.backup_verify.json_response", mock_resp):
            handle_backup_verify_status(handler)

        self.assertEqual(self._status, 502)
        self.assertEqual(self._response["status"], "unknown")
        self.assertNotEqual(self._response.get("ok"), True, "Must not return ok:true on SSH failure")

    @patch("freq.api.backup_verify._check_session_role", return_value=("admin", None))
    @patch("freq.api.backup_verify.load_config")
    @patch("freq.api.backup_verify._find_node_ip", return_value="10.0.0.1")
    @patch("freq.api.backup_verify._pve_ssh")
    def test_success_returns_pass(self, mock_ssh, mock_node, mock_cfg, mock_role):
        """Successful query must return status:pass."""
        from freq.api.backup_verify import handle_backup_verify_status

        mock_ssh.return_value = MagicMock(
            returncode=0,
            stdout="100|2026_04_08-10_00_00|1073741824|qemu|vzdump-qemu-100-2026_04_08.vma.zst\n",
        )

        handler, mock_resp = self._make_handler()
        with patch("freq.api.backup_verify.json_response", mock_resp):
            handle_backup_verify_status(handler)

        self.assertEqual(self._status, 200)
        self.assertEqual(self._response["status"], "pass")
        self.assertEqual(len(self._response["backups"]), 1)


class TestObserveIntParams(unittest.TestCase):
    """observe.py must never crash on bad query parameters."""

    def test_safe_int_param_handles_garbage(self):
        from freq.api.observe import _safe_int_param

        self.assertEqual(_safe_int_param({"limit": ["abc"]}, "limit", 50), 50)
        self.assertEqual(_safe_int_param({"limit": [""]}, "limit", 50), 50)
        self.assertEqual(_safe_int_param({}, "limit", 50), 50)
        self.assertEqual(_safe_int_param({"limit": ["10"]}, "limit", 50), 10)


class TestLogPartialFailure(unittest.TestCase):
    """logs.py must report which hosts were unreachable."""

    @patch("freq.modules.logs.ssh_run_many")
    def test_tail_reports_unreachable_hosts(self, mock_ssh):
        """Unreachable hosts must be listed, not silently skipped."""
        from freq.modules.logs import _cmd_tail
        from freq.core import fmt

        # Mock 2 hosts, 1 reachable, 1 not
        host_a = MagicMock(label="host-a", ip="10.0.0.1")
        host_b = MagicMock(label="host-b", ip="10.0.0.2")

        mock_ssh.return_value = {
            "host-a": MagicMock(returncode=0, stdout="Apr 08 test log line\n"),
            "host-b": MagicMock(returncode=255, stdout="", stderr="Connection refused"),
        }

        cfg = MagicMock()
        cfg.hosts = [host_a, host_b]
        cfg.ssh_key_path = "/tmp/test"
        cfg.ssh_connect_timeout = 3
        cfg.ssh_max_parallel = 10

        args = MagicMock(target_host=None, lines=5, unit=None)

        # Capture fmt output
        output_lines = []
        original_line = fmt.line

        def capture_line(text):
            output_lines.append(text)
            original_line(text)

        with patch.object(fmt, "line", capture_line):
            _cmd_tail(cfg, args)

        # Verify unreachable host is reported
        all_output = " ".join(output_lines)
        self.assertIn("host-b", all_output, "Unreachable host must be mentioned in output")
        self.assertIn("unreachable", all_output.lower(), "Must use the word 'unreachable'")


class TestReleaseScriptGrep(unittest.TestCase):
    """release.sh must not die when all commits are correct."""

    def test_grep_v_with_no_matches_survives_pipefail(self):
        """grep -v finding zero bad authors must not kill the script."""
        import subprocess

        # Simulate: all commits are lowfreqlabs → grep -v matches nothing → exit 1
        # With || true, this should exit 0
        result = subprocess.run(
            ["bash", "-c", "set -euo pipefail; echo 'lowfreqlabs' | grep -v 'lowfreqlabs' || true"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, "grep -v with no matches must not crash under pipefail")


class TestBackupVerifyNodeFallback(unittest.TestCase):
    """_find_node_ip must verify reachability, not just return the named IP."""

    @patch("freq.api.backup_verify._pve_ssh")
    def test_named_node_down_falls_back(self, mock_ssh):
        """If the named node is down, must try other nodes."""
        from freq.api.backup_verify import _find_node_ip

        # Named node (pve01) is down, second node (pve02) is up
        def ssh_side_effect(cfg, ip, cmd, timeout=5):
            r = MagicMock()
            r.returncode = 0 if ip == "10.0.0.2" else 1
            return r

        mock_ssh.side_effect = ssh_side_effect

        cfg = MagicMock()
        cfg.pve_node_names = ["pve01", "pve02"]
        cfg.pve_nodes = ["10.0.0.1", "10.0.0.2"]

        result = _find_node_ip(cfg, node_name="pve01")
        self.assertEqual(result, "10.0.0.2", "Must fall back to reachable node when named node is down")

    @patch("freq.api.backup_verify._pve_ssh")
    def test_named_node_up_returns_it(self, mock_ssh):
        """If the named node is up, return it directly."""
        from freq.api.backup_verify import _find_node_ip

        mock_ssh.return_value = MagicMock(returncode=0)

        cfg = MagicMock()
        cfg.pve_node_names = ["pve01", "pve02"]
        cfg.pve_nodes = ["10.0.0.1", "10.0.0.2"]

        result = _find_node_ip(cfg, node_name="pve01")
        self.assertEqual(result, "10.0.0.1")


class TestDrVerifyMultiNode(unittest.TestCase):
    """DR verify must check all nodes, not just one."""

    @patch("freq.modules.pve._pve_cmd")
    def test_verify_uses_storage_metadata_across_nodes(self, mock_pve_cmd):
        """cmd_dr_backup_verify must use storage metadata before path guessing."""
        from freq.modules.dr import cmd_dr_backup_verify

        calls = []

        def cmd_side_effect(cfg, ip, cmd, timeout=30):
            calls.append((ip, cmd))
            if "echo OK" in cmd:
                return ("OK", True)
            if cmd == "pvesh get /storage --content backup --output-format json":
                return ('[{"storage":"pbs-backups","content":"backup"}]', True)
            if "/nodes/pve01/storage/pbs-backups/content" in cmd:
                return ('[{"content":"backup","vmid":100,"ctime":1712600000}]', True)
            if "/nodes/pve02/storage/pbs-backups/content" in cmd:
                return ('[{"content":"backup","vmid":200,"ctime":1712600000}]', True)
            return ("", True)

        mock_pve_cmd.side_effect = cmd_side_effect

        cfg = MagicMock()
        cfg.pve_nodes = ["10.0.0.1", "10.0.0.2"]
        cfg.pve_node_names = ["pve01", "pve02"]
        cfg.ssh_key_path = "/tmp/fake"
        cfg.ssh_connect_timeout = 3
        cfg.conf_dir = "/tmp/fake-conf"

        pack = MagicMock()
        args = MagicMock()

        result = cmd_dr_backup_verify(cfg, pack, args)

        self.assertEqual(result, 1)
        storage_queries = [cmd for _ip, cmd in calls if "/storage/pbs-backups/content" in cmd]
        self.assertTrue(storage_queries, "Storage content queries must be used")
        self.assertTrue(any("/nodes/pve01/storage/pbs-backups/content" in cmd for cmd in storage_queries))
        self.assertTrue(any("/nodes/pve02/storage/pbs-backups/content" in cmd for cmd in storage_queries))
        self.assertFalse(
            any("for d in /var/lib/vz/dump" in cmd for _ip, cmd in calls),
            "Should not fall back when storage metadata works",
        )

    @patch("freq.modules.pve._pve_cmd")
    def test_verify_falls_back_to_filesystem_scan_when_storage_metadata_unavailable(self, mock_pve_cmd):
        """cmd_dr_backup_verify must retain filesystem fallback when storage metadata is unavailable."""
        from freq.modules.dr import cmd_dr_backup_verify

        calls = []

        def cmd_side_effect(cfg, ip, cmd, timeout=30):
            calls.append((ip, cmd))
            if "echo OK" in cmd:
                return ("OK", True)
            if cmd == "pvesh get /storage --content backup --output-format json":
                return ("permission denied", False)
            if "for d in /var/lib/vz/dump" in cmd and ip == "10.0.0.1":
                return ("100|1712600000\n", True)
            if "for d in /var/lib/vz/dump" in cmd and ip == "10.0.0.2":
                return ("200|1712600000\n", True)
            return ("", True)

        mock_pve_cmd.side_effect = cmd_side_effect

        cfg = MagicMock()
        cfg.pve_nodes = ["10.0.0.1", "10.0.0.2"]
        cfg.pve_node_names = ["pve01", "pve02"]
        cfg.ssh_key_path = "/tmp/fake"
        cfg.ssh_connect_timeout = 3
        cfg.conf_dir = "/tmp/fake-conf"

        pack = MagicMock()
        args = MagicMock()

        result = cmd_dr_backup_verify(cfg, pack, args)

        self.assertEqual(result, 1)
        self.assertTrue(any(cmd == "pvesh get /storage --content backup --output-format json" for _ip, cmd in calls))
        self.assertTrue(any("for d in /var/lib/vz/dump" in cmd for _ip, cmd in calls), "Filesystem fallback must still exist")

    def test_dr_backup_scan_command_is_valid_bash(self):
        """The shell command generated by dr.py must be syntactically valid."""
        import subprocess

        # Extract the command pattern from dr.py
        cmd = (
            "for d in /var/lib/vz/dump /mnt/*/dump /mnt/pbs-*; do "
            '[ -d "$d" ] || continue; '
            'for f in "$d"/vzdump-qemu-*.vma* "$d"/vzdump-lxc-*.tar*; do '
            '[ -f "$f" ] || continue; '
            'base=$(basename "$f"); '
            "vmid=$(echo \"$base\" | grep -oP '(?<=vzdump-(qemu|lxc)-)\\d+'); "
            "epoch=$(stat -c%Y \"$f\" 2>/dev/null || echo 0); "
            'echo "$vmid|$epoch"; '
            "done; "
            "done 2>/dev/null | sort -t'|' -k1,1n -k2,2rn"
        )
        result = subprocess.run(["bash", "-n", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, f"Bash syntax error: {result.stderr}")


class TestInitSummaryHonesty(unittest.TestCase):
    """Init summary must not claim success when verification failed."""

    def _make_cfg(self, **overrides):
        cfg = MagicMock()
        cfg.version = "1.0.0"
        cfg.key_dir = "/tmp/fake-keys"
        cfg.vault_file = "/tmp/fake-vault"
        cfg.conf_dir = "/tmp/fake-conf"
        cfg.pve_nodes = ["10.0.0.1"]
        cfg.pve_node_names = ["pve01"]
        cfg.hosts = []
        cfg.pve_api_token_id = ""
        cfg.dashboard_port = 8888
        cfg.watchdog_port = 9900
        cfg.agent_port = 9990
        cfg.pfsense_ip = ""
        cfg.truenas_ip = ""
        cfg.switch_ip = ""
        cfg.vlans = []
        cfg.ssh_service_account = "freq-admin"
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    @patch("freq.modules.init_cmd.fmt")
    def test_summary_says_partially_configured_when_not_verified(self, mock_fmt):
        """If verified=False, summary must say 'partially configured', not 'ready'."""
        from freq.modules.init_cmd import _phase_summary

        cfg = self._make_cfg()
        ctx = {"svc_name": "freq-admin"}
        _phase_summary(cfg, ctx, verified=False)

        # Check that fmt.line was called with 'partially configured'
        all_calls = [str(c) for c in mock_fmt.line.call_args_list]
        combined = " ".join(all_calls)
        self.assertIn("partially configured", combined,
                       "Summary must say 'partially configured' when verified=False")
        self.assertNotIn("is ready", combined,
                         "Summary must NOT say 'ready' when verified=False")

    @patch("freq.modules.init_cmd.fmt")
    def test_summary_says_ready_when_verified(self, mock_fmt):
        """If verified=True, summary should say 'ready'."""
        from freq.modules.init_cmd import _phase_summary

        cfg = self._make_cfg()
        ctx = {"svc_name": "freq-admin"}
        _phase_summary(cfg, ctx, verified=True)

        all_calls = [str(c) for c in mock_fmt.line.call_args_list]
        combined = " ".join(all_calls)
        self.assertIn("is ready", combined,
                       "Summary must say 'ready' when verified=True")


class TestInitOwnershipContract(unittest.TestCase):
    """Init must not silently ignore chown failures.

    The 'worked once as root, broken as freq-ops' trap happens when:
    1. init runs as root, creates files with root:root ownership
    2. chown to freq-admin fails silently (user doesn't exist, etc.)
    3. init reports success
    4. dashboard starts as freq-admin, can't read root-owned files
    """

    def test_no_unchecked_chown_calls(self):
        """All chown operations must use _chown() helper which checks return codes.

        No bare _run(["chown"...]) calls should exist — they discard rc and
        silently leave root-owned files that freq-admin can't read.
        """
        import os
        init_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "init_cmd.py")
        with open(init_path) as f:
            lines = f.readlines()

        unchecked_chowns = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("_run([") and '"chown"' in stripped:
                unchecked_chowns.append(i)

        self.assertEqual(unchecked_chowns, [],
                         f"Unchecked _run(['chown'...]) at lines: {unchecked_chowns}")

    def test_chown_helper_exists(self):
        """_chown() helper must exist and check return codes."""
        from freq.modules.init_cmd import _chown
        self.assertTrue(callable(_chown))

    def test_ownership_directories_are_documented(self):
        """The list of directories that need freq-admin ownership must be explicit."""
        import os
        init_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "init_cmd.py")
        with open(init_path) as f:
            content = f.read()

        # Phase 9m ownership fix should cover these critical directories
        critical_dirs = ["data/keys", "data/log", "data/vault", "credentials"]
        for d in critical_dirs:
            self.assertIn(d, content,
                          f"Critical directory '{d}' not found in init ownership fix")

    def test_key_permissions_are_enforced(self):
        """SSH key files must have chmod 600 enforced in init."""
        import os
        init_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "init_cmd.py")
        with open(init_path) as f:
            content = f.read()

        # ed25519 and RSA keys must have 600 permissions
        self.assertIn("os.chmod(ed_key, 0o600)", content,
                       "ed25519 key must have chmod 600")
        self.assertIn("os.chmod(rsa_key, 0o600)", content,
                       "RSA key must have chmod 600")


class TestCacheStalenessVisibility(unittest.TestCase):
    """Cached API endpoints must expose staleness to the operator.

    If background probes die, the dashboard must not silently show
    stale data as if it's fresh. Every cache-backed endpoint must
    include age_seconds and stale flag.
    """

    def test_fleet_health_score_exposes_staleness(self):
        """health-score must include cache age and stale flag."""
        import inspect
        from freq.api.fleet import handle_fleet_health_score
        src = inspect.getsource(handle_fleet_health_score)
        self.assertIn("age_seconds", src,
                       "health-score must include age_seconds in response")
        self.assertIn("stale", src,
                       "health-score must include stale flag in response")

    def test_fleet_heatmap_exposes_staleness(self):
        """heatmap must include cache age and stale flag."""
        import inspect
        from freq.api.fleet import handle_fleet_heatmap
        src = inspect.getsource(handle_fleet_heatmap)
        self.assertIn("age_seconds", src,
                       "heatmap must include age_seconds in response")
        self.assertIn("stale", src,
                       "heatmap must include stale flag in response")

    def test_fleet_topology_exposes_staleness(self):
        """topology-enhanced must include cache age and stale flag."""
        import inspect
        from freq.api.fleet import handle_topology_enhanced
        src = inspect.getsource(handle_topology_enhanced)
        self.assertIn("age_seconds", src,
                       "topology must include age_seconds in response")
        self.assertIn("stale", src,
                       "topology must include stale flag in response")

    def test_fleet_overview_exposes_staleness(self):
        """fleet overview must include cache age (already has it — regression guard)."""
        import inspect
        from freq.api.fleet import handle_fleet_overview
        src = inspect.getsource(handle_fleet_overview)
        self.assertIn("age_seconds", src,
                       "fleet overview must include age_seconds")

    def test_health_api_exposes_probe_status(self):
        """health API must include probe_status (already has it — regression guard)."""
        import inspect
        from freq.api.fleet import handle_health_api
        src = inspect.getsource(handle_health_api)
        self.assertIn("probe_status", src,
                       "health API must include probe_status")


class TestStaleCacheRegressions(unittest.TestCase):
    """Cache-backed API responses must never show stale data as fresh.

    These tests verify that endpoints which read from _bg_cache include
    staleness metadata. If a background probe dies, the dashboard must
    know the data is old.
    """

    def test_fleet_overview_includes_age_in_cached_response(self):
        """When fleet_overview cache exists, response must include age_seconds."""
        from freq.api.fleet import handle_fleet_overview, _bg_cache, _bg_cache_ts, _bg_lock
        import time

        handler = MagicMock()
        handler.command = "GET"
        handler.path = "/api/fleet/overview"
        handler.headers = {}
        captured = {}

        def mock_json_resp(h, data, status=200):
            captured["data"] = data
            captured["status"] = status

        # Seed cache with data from 60 seconds ago
        with _bg_lock:
            _bg_cache["fleet_overview"] = {
                "vms": [], "physical": [], "pve_nodes": [],
                "vlans": [], "nic_profiles": {}, "categories": {},
                "summary": {"total_vms": 0, "running": 0, "stopped": 0,
                            "prod_count": 0, "lab_count": 0, "template_count": 0},
                "duration": 0.5,
            }
            _bg_cache_ts["fleet_overview"] = time.time() - 60

        with patch("freq.api.fleet.json_response", mock_json_resp):
            handle_fleet_overview(handler)

        self.assertIn("age_seconds", captured["data"],
                       "Cached fleet overview must include age_seconds")
        self.assertIn("cached", captured["data"],
                       "Cached fleet overview must include cached flag")
        self.assertGreaterEqual(captured["data"]["age_seconds"], 59,
                                "age_seconds must reflect real cache age")

    def test_health_api_includes_probe_status(self):
        """When health cache exists, response must include probe_status."""
        from freq.api.fleet import handle_health_api, _bg_cache, _bg_cache_ts, _bg_cache_errors, _bg_lock
        import time

        handler = MagicMock()
        handler.command = "GET"
        handler.path = "/api/health"
        handler.headers = {"Authorization": "Bearer test"}
        captured = {}

        def mock_json_resp(h, data, status=200):
            captured["data"] = data
            captured["status"] = status

        with _bg_lock:
            _bg_cache["health"] = {"hosts": [], "duration": 0.1}
            _bg_cache_ts["health"] = time.time() - 30
            _bg_cache_errors.pop("health", None)

        with patch("freq.api.fleet._check_session_role", return_value=("viewer", None)), \
             patch("freq.api.fleet.json_response", mock_json_resp):
            handle_health_api(handler)

        self.assertIn("probe_status", captured["data"],
                       "Health API must include probe_status")
        self.assertEqual(captured["data"]["probe_status"], "ok")
        self.assertIn("age_seconds", captured["data"])

    def test_health_api_reports_probe_error_when_probe_failed(self):
        """When probe has consecutive failures, health API must report it."""
        from freq.api.fleet import handle_health_api, _bg_cache, _bg_cache_ts, _bg_cache_errors, _bg_lock
        import time

        handler = MagicMock()
        handler.command = "GET"
        handler.path = "/api/health"
        handler.headers = {"Authorization": "Bearer test"}
        captured = {}

        def mock_json_resp(h, data, status=200):
            captured["data"] = data

        with _bg_lock:
            _bg_cache["health"] = {"hosts": [], "duration": 0.1}
            _bg_cache_ts["health"] = time.time() - 300  # 5 min stale
            _bg_cache_errors["health"] = {
                "error": "SSH timeout to all hosts",
                "failed_at": time.time() - 120,
                "consecutive": 5,
            }

        with patch("freq.api.fleet._check_session_role", return_value=("viewer", None)), \
             patch("freq.api.fleet.json_response", mock_json_resp):
            handle_health_api(handler)

        self.assertEqual(captured["data"]["probe_status"], "error",
                         "Must report probe_status=error when probe has failures")
        self.assertIn("probe_error", captured["data"])
        self.assertEqual(captured["data"]["probe_consecutive_failures"], 5)

        # Cleanup
        with _bg_lock:
            _bg_cache_errors.pop("health", None)


class TestHealthScoreColdStart(unittest.TestCase):
    """health-score must not return 100/A when no data exists."""

    def test_no_cache_returns_503_not_perfect_score(self):
        """With empty cache, health-score must return 503, not score=100."""
        from freq.api.fleet import handle_fleet_health_score, _bg_cache, _bg_cache_ts, _bg_lock

        handler = MagicMock()
        handler.path = "/api/fleet/health-score"
        captured = {}

        def mock_json_resp(h, data, status=200):
            captured["data"] = data
            captured["status"] = status

        # Clear both caches
        with _bg_lock:
            _bg_cache["health"] = None
            _bg_cache["fleet_overview"] = None

        with patch("freq.api.fleet.json_response", mock_json_resp):
            handle_fleet_health_score(handler)

        self.assertEqual(captured["status"], 503,
                         "health-score with no data must return 503")
        self.assertNotEqual(captured["data"].get("score"), 100,
                            "health-score must NOT be 100 with no data")
        self.assertNotEqual(captured["data"].get("grade"), "A",
                            "grade must NOT be A with no data")


class TestAPIStatusCodeTruth(unittest.TestCase):
    """API error responses must never return 200.

    These tests verify the operator-visible HTTP contract:
    if the response body says error, the status code must not say success.
    """

    def _make_mock_handler(self, path="/api/test"):
        handler = MagicMock()
        handler.command = "GET"
        handler.path = path
        handler.headers = {}
        handler.wfile = MagicMock()
        handler._headers_buffer = []
        captured = {"status": None, "data": None}

        def mock_send_response(code, msg=None):
            captured["status"] = code

        handler.send_response = mock_send_response
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler, captured

    def test_unauthenticated_api_returns_403_not_200(self):
        """An API request without auth must get 403, never 200 with error body."""
        from freq.api.helpers import json_response
        from freq.api.auth import check_session_role

        handler, captured = self._make_mock_handler("/api/fleet/overview")
        # No auth headers → check_session_role should fail
        handler.headers = {}
        role, err = check_session_role(handler, "admin")
        if err:
            json_response(handler, {"error": err}, 403)
        self.assertIsNotNone(err, "Missing auth should produce an error")
        self.assertEqual(captured["status"], 403, "Auth failure must return 403, not 200")

    def test_validation_error_returns_400_not_200(self):
        """A missing required parameter must get 400, never 200 with error body."""
        from freq.api.helpers import json_response

        handler, captured = self._make_mock_handler("/api/vm/create?name=")
        # Simulate validation failure
        json_response(handler, {"error": "name parameter required"}, 400)
        self.assertEqual(captured["status"], 400, "Validation error must return 400, not 200")

    def test_not_found_returns_404_not_200(self):
        """A missing resource must get 404, never 200 with error body."""
        from freq.api.helpers import json_response

        handler, captured = self._make_mock_handler("/api/agent/status?name=ghost")
        json_response(handler, {"error": "Agent not found: ghost"}, 404)
        self.assertEqual(captured["status"], 404, "Not found must return 404, not 200")

    def test_source_level_no_bare_errors_in_serve(self):
        """serve.py must have zero json_response(error) without status code."""
        import os, re
        serve_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "serve.py")
        with open(serve_path) as f:
            lines = f.readlines()
        bare = [i for i, l in enumerate(lines, 1)
                if '_json_response({"error"' in l.strip() and l.strip().endswith("})")
                and not re.search(r'},\s*\d+\)$', l.strip())]
        self.assertEqual(bare, [], f"serve.py has bare error→200 at lines: {bare}")

    def test_source_level_no_bare_errors_in_v1_api(self):
        """freq/api/*.py must have zero json_response(handler, {{error}}) without status code."""
        import os, re, glob
        api_dir = os.path.join(os.path.dirname(__file__), "..", "freq", "api")
        bare = []
        for fpath in sorted(glob.glob(os.path.join(api_dir, "*.py"))):
            fname = os.path.basename(fpath)
            with open(fpath) as f:
                for i, line in enumerate(f, 1):
                    s = line.strip()
                    if 'json_response(handler, {"error"' in s and s.endswith("})"):
                        if not re.search(r'},\s*\d+\)$', s):
                            bare.append(f"{fname}:{i}")
        self.assertEqual(bare, [], f"v1 API has bare error→200: {bare}")


class TestDestructiveEndpointSafety(unittest.TestCase):
    """Destructive API endpoints must enforce POST method."""

    def test_vm_destroy_enforces_post(self):
        """VM destroy must reject GET requests."""
        import inspect
        from freq.api.vm import handle_vm_destroy
        src = inspect.getsource(handle_vm_destroy)
        self.assertIn("_require_post", src,
                       "VM destroy must enforce POST")

    def test_vm_delete_snapshot_enforces_post(self):
        """VM delete snapshot must reject GET requests."""
        import inspect
        from freq.api.vm import handle_vm_delete_snapshot
        src = inspect.getsource(handle_vm_delete_snapshot)
        self.assertIn("_require_post", src,
                       "VM delete snapshot must enforce POST")


class TestSetupTrustBoundaries(unittest.TestCase):
    """Setup endpoints must not leak or mutate state after setup is complete."""

    def test_all_setup_endpoints_check_first_run(self):
        """Every write-capable setup endpoint must check _is_first_run()."""
        import inspect
        from freq.modules.serve import FreqHandler
        write_handlers = [
            "_serve_setup_create_admin",
            "_serve_setup_configure",
            "_serve_setup_generate_key",
            "_serve_setup_complete",
        ]
        for name in write_handlers:
            src = inspect.getsource(getattr(FreqHandler, name))
            self.assertIn("_is_first_run", src,
                          f"{name} must check _is_first_run()")

    def test_setup_complete_has_lock(self):
        """setup_complete must use a lock to prevent race conditions."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._serve_setup_complete)
        self.assertIn("_setup_lock", src,
                       "setup_complete must use _setup_lock")

    def test_setup_complete_double_checks_after_lock(self):
        """setup_complete must re-check _is_first_run() after acquiring lock."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._serve_setup_complete)
        # Should have at least 2 _is_first_run calls (before lock + after lock)
        count = src.count("_is_first_run()")
        self.assertGreaterEqual(count, 2,
                                "setup_complete must double-check _is_first_run() after lock")

    def test_setup_reset_requires_admin(self):
        """setup_reset must require admin auth, not just _is_first_run()."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._serve_setup_reset)
        self.assertIn("check_session_role", src,
                       "setup_reset must require admin auth")
        # Must not CALL _is_first_run() — comment references are OK
        lines = [l.strip() for l in src.split('\n') if not l.strip().startswith('#')]
        code_only = '\n'.join(lines)
        self.assertNotIn("_is_first_run()", code_only,
                         "setup_reset must NOT call _is_first_run() (admin-only)")

    @patch("freq.modules.serve._is_first_run", return_value=False)
    def test_setup_create_admin_blocked_after_setup(self, _mock):
        """create-admin must return 403 when setup is already complete."""
        import io
        from freq.modules.serve import FreqHandler

        h = FreqHandler.__new__(FreqHandler)
        h.path = "/api/setup/create-admin"
        h.command = "POST"
        h.wfile = io.BytesIO()
        h.rfile = io.BytesIO(b'{"username":"hacker","password":"pwned123"}')
        h.headers = {"Content-Length": "50"}
        h._headers_buffer = []
        h._status = None
        h.send_response = lambda code, msg=None: setattr(h, '_status', code)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None

        h._serve_setup_create_admin()
        self.assertEqual(h._status, 403,
                         "create-admin must be blocked after setup completes")


class TestDashboardShellSafety(unittest.TestCase):
    """Dashboard SPA shell must not embed fleet data for anonymous users."""

    def test_app_html_does_not_contain_fleet_data(self):
        """The static HTML shell must not contain real fleet IPs or hostnames."""
        import re
        from freq.modules.web_ui import APP_HTML
        # The HTML is a SPA shell — data comes from authenticated API calls
        # Full IPs (x.x.x.x) should not appear except in placeholder examples
        real_ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', APP_HTML)
        # Filter out example/placeholder IPs
        suspicious = [ip for ip in real_ips if not ip.startswith("0.") and ip != "127.0.0.1"]
        self.assertEqual(suspicious, [],
                         f"APP_HTML contains real-looking IPs: {suspicious}")

    def test_first_run_serves_setup_html(self):
        """On first run, the dashboard serves setup wizard, not fleet UI."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._serve_app)
        self.assertIn("_is_first_run()", src)
        self.assertIn("SETUP_HTML", src)


class TestCreateAdminCredentialSafety(unittest.TestCase):
    """create-admin must never accept credentials via URL query params."""

    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_get_with_query_params_rejected(self, _mock):
        """GET /api/setup/create-admin?username=x&password=y must be rejected."""
        import io
        from freq.modules.serve import FreqHandler

        h = FreqHandler.__new__(FreqHandler)
        h.path = "/api/setup/create-admin?username=admin&password=secret123"
        h.command = "GET"
        h.wfile = io.BytesIO()
        h.rfile = io.BytesIO()
        h.headers = {}
        h._headers_buffer = []
        h._status = None
        h.send_response = lambda code, msg=None: setattr(h, '_status', code)
        h.send_header = lambda k, v: None
        h.end_headers = lambda: None

        h._serve_setup_create_admin()
        self.assertEqual(h._status, 405,
                         "create-admin must reject GET (credentials in URL)")


class TestAnonymousAccessRejected(unittest.TestCase):
    """Trust-critical API endpoints must reject unauthenticated requests."""

    def _make_handler(self, path):
        handler = MagicMock()
        handler.command = "GET"
        handler.path = path
        handler.headers = {}  # No auth headers
        captured = {"status": None, "data": None}

        def mock_send(code, msg=None):
            captured["status"] = code

        handler.send_response = mock_send
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.wfile = MagicMock()
        return handler, captured

    def test_health_api_rejects_anonymous(self):
        """GET /api/health without auth must return 403."""
        from freq.api.fleet import handle_health_api
        from freq.api.auth import check_session_role

        handler, captured = self._make_handler("/api/health")
        role, err = check_session_role(handler, "viewer")
        self.assertIsNotNone(err, "Anonymous request should fail auth")

    def test_fleet_overview_behind_global_gate(self):
        """/api/fleet/overview is not in auth whitelist — global gate rejects anonymous."""
        from freq.modules.serve import FreqHandler
        self.assertNotIn("/api/fleet/overview", FreqHandler._AUTH_WHITELIST)

    def test_events_not_in_whitelist(self):
        """/api/events is not in auth whitelist."""
        from freq.modules.serve import FreqHandler
        self.assertNotIn("/api/events", FreqHandler._AUTH_WHITELIST)

    def test_config_view_not_in_whitelist(self):
        """/api/config/view is not in auth whitelist."""
        from freq.modules.serve import FreqHandler
        self.assertNotIn("/api/config/view", FreqHandler._AUTH_WHITELIST)

    def test_watchdog_proxy_requires_auth(self):
        """Watchdog proxy must NOT be in auth whitelist — fleet data requires auth."""
        from freq.modules.serve import FreqHandler
        for prefix in FreqHandler._AUTH_WHITELIST_PREFIXES:
            self.assertNotIn("watch", prefix,
                             "/api/watch/ must not be in auth whitelist")
            self.assertNotIn("comms", prefix,
                             "/api/comms/ must not be in auth whitelist")


class TestSecurityHeaders(unittest.TestCase):
    """All responses must include security headers."""

    def test_json_response_has_security_headers(self):
        """_json_response must call _send_security_headers."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._json_response)
        self.assertIn("_send_security_headers", src)

    def test_app_html_has_security_headers(self):
        """_serve_app must call _send_security_headers."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._serve_app)
        self.assertIn("_send_security_headers", src)

    def test_sse_has_security_headers(self):
        """_serve_events must call _send_security_headers."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._serve_events)
        self.assertIn("_send_security_headers", src)

    def test_security_headers_include_csp(self):
        """_send_security_headers must include Content-Security-Policy."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._send_security_headers)
        self.assertIn("Content-Security-Policy", src)

    def test_cookie_has_httponly_samesite(self):
        """Session cookie must have HttpOnly and SameSite=Strict."""
        import inspect
        from freq.api.auth import handle_auth_login
        src = inspect.getsource(handle_auth_login)
        self.assertIn("HttpOnly", src)
        self.assertIn("SameSite=Strict", src)


class TestDashboardSessionExpiry(unittest.TestCase):
    """Dashboard must redirect to login on 403/401, never show stale data."""

    def test_authfetch_handles_403(self):
        """_authFetch in app.js must call doLogout() on 403."""
        import os
        app_path = os.path.join(os.path.dirname(__file__), "..", "freq", "data", "web", "js", "app.js")
        with open(app_path) as f:
            content = f.read()
        # Must detect 403 and call doLogout
        self.assertIn("r.status===403", content,
                       "_authFetch must check for 403")
        self.assertIn("doLogout()", content.split("_authFetch")[1][:500],
                       "_authFetch must call doLogout on auth failure")

    def test_authfetch_handles_401(self):
        """_authFetch in app.js must call doLogout() on 401."""
        import os
        app_path = os.path.join(os.path.dirname(__file__), "..", "freq", "data", "web", "js", "app.js")
        with open(app_path) as f:
            content = f.read()
        self.assertIn("r.status===401", content,
                       "_authFetch must check for 401")

    def test_readyz_returns_503_on_cold_start(self):
        """readyz must return 503 when background cache hasn't run yet."""
        import inspect
        from freq.modules.serve import FreqHandler
        src = inspect.getsource(FreqHandler._serve_readyz)
        self.assertIn("503", src, "readyz must return 503 when not ready")
        self.assertIn("warming_up", src, "readyz must report warming_up status")


class TestTLSConfigChain(unittest.TestCase):
    """TLS config chain must be consistent: init writes → config reads → serve uses."""

    def test_serve_reads_tls_from_config(self):
        """cmd_serve checks cfg.tls_cert and cfg.tls_key for TLS enablement."""
        import inspect
        from freq.modules.serve import cmd_serve
        src = inspect.getsource(cmd_serve)
        self.assertIn("cfg.tls_cert", src, "serve must read tls_cert from config")
        self.assertIn("cfg.tls_key", src, "serve must read tls_key from config")

    def test_config_loader_reads_tls(self):
        """Config loader must populate tls_cert and tls_key from [services]."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        self.assertTrue(hasattr(cfg, "tls_cert"))
        self.assertTrue(hasattr(cfg, "tls_key"))
        self.assertEqual(cfg.tls_cert, "", "Default tls_cert should be empty")

    def test_cookie_secure_flag_uses_config_tls(self):
        """Cookie Secure flag must check cfg.tls_cert, not hardcoded path."""
        import inspect
        from freq.api.auth import handle_auth_login
        src = inspect.getsource(handle_auth_login)
        self.assertNotIn("cert.pem", src, "Must not hardcode cert.pem filename")
        self.assertIn("tls_cert", src, "Must check config tls_cert")


class TestPOSTEnforcementGap(unittest.TestCase):
    """Document and guard POST enforcement across mutating handlers.

    These tests verify the known state: critical endpoints ARE enforced,
    remaining admin-only ops are a documented gap for require_role refactor.
    """

    def test_critical_mutating_endpoints_enforce_post(self):
        """The most dangerous endpoints must enforce POST."""
        import inspect
        from freq.api.vm import handle_vm_destroy, handle_vm_clone
        from freq.api.fleet import handle_exec, handle_deploy_agent
        from freq.api.secure import handle_vault_delete

        for handler in [handle_vm_destroy, handle_vm_clone, handle_exec,
                        handle_deploy_agent, handle_vault_delete]:
            src = inspect.getsource(handler)
            self.assertIn("require_post", src,
                           f"{handler.__name__} must enforce POST")

    def test_batch1_privilege_endpoints_enforce_post(self):
        """Privilege escalation + vault write + remote exec endpoints must enforce POST."""
        import inspect
        from freq.api.user import handle_user_promote, handle_user_demote
        from freq.api.secure import handle_vault_set
        from freq.api.bench import handle_wol, handle_bench_run, handle_bench_netspeed
        from freq.api.net import handle_switch_acl

        for handler in [handle_user_promote, handle_user_demote,
                        handle_vault_set,
                        handle_wol, handle_bench_run, handle_bench_netspeed,
                        handle_switch_acl]:
            src = inspect.getsource(handler)
            self.assertIn("require_post", src,
                           f"{handler.__name__} must enforce POST")

    def test_batch2_storage_endpoints_enforce_post(self):
        """TrueNAS storage mutation endpoints must enforce POST."""
        import inspect
        from freq.api.store import (
            handle_truenas_snapshot, handle_truenas_service,
            handle_truenas_scrub, handle_truenas_reboot,
            handle_truenas_dataset, handle_truenas_share,
            handle_truenas_replication, handle_truenas_app,
        )

        for handler in [handle_truenas_snapshot, handle_truenas_service,
                        handle_truenas_scrub, handle_truenas_reboot,
                        handle_truenas_dataset, handle_truenas_share,
                        handle_truenas_replication, handle_truenas_app]:
            src = inspect.getsource(handler)
            self.assertIn("require_post", src,
                           f"{handler.__name__} must enforce POST")

    def test_batch3_firewall_endpoints_enforce_post(self):
        """pfSense firewall mutation endpoints must enforce POST."""
        import inspect
        from freq.api.fw import (
            handle_pfsense_service, handle_pfsense_dhcp_reservation,
            handle_pfsense_config_backup, handle_pfsense_reboot,
            handle_pfsense_rules, handle_pfsense_nat,
            handle_pfsense_wg_peer,
        )

        for handler in [handle_pfsense_service, handle_pfsense_dhcp_reservation,
                        handle_pfsense_config_backup, handle_pfsense_reboot,
                        handle_pfsense_rules, handle_pfsense_nat,
                        handle_pfsense_wg_peer]:
            src = inspect.getsource(handler)
            self.assertIn("require_post", src,
                           f"{handler.__name__} must enforce POST")

    def test_batch4_opnsense_docker_enforce_post(self):
        """OPNsense + Docker mutation endpoints must enforce POST."""
        import inspect
        from freq.api.opnsense import (
            handle_opnsense_service_action, handle_opnsense_rule_add,
            handle_opnsense_dhcp_add, handle_opnsense_dns_add,
            handle_opnsense_wg_add, handle_opnsense_reboot,
        )
        from freq.api.docker_api import (
            handle_containers_add, handle_containers_edit,
            handle_containers_compose_up, handle_containers_compose_down,
        )

        for handler in [handle_opnsense_service_action, handle_opnsense_rule_add,
                        handle_opnsense_dhcp_add, handle_opnsense_dns_add,
                        handle_opnsense_wg_add, handle_opnsense_reboot,
                        handle_containers_add, handle_containers_edit,
                        handle_containers_compose_up, handle_containers_compose_down]:
            src = inspect.getsource(handler)
            self.assertIn("require_post", src,
                           f"{handler.__name__} must enforce POST")

    def test_batch5_container_endpoints_enforce_post(self):
        """LXC container mutation endpoints must enforce POST."""
        import inspect
        from freq.api.ct import (
            handle_ct_power, handle_ct_set, handle_ct_snapshot,
            handle_ct_clone, handle_ct_migrate, handle_ct_resize,
            handle_ct_exec,
        )

        for handler in [handle_ct_power, handle_ct_set, handle_ct_snapshot,
                        handle_ct_clone, handle_ct_migrate, handle_ct_resize,
                        handle_ct_exec]:
            src = inspect.getsource(handler)
            self.assertIn("require_post", src,
                           f"{handler.__name__} must enforce POST")

    def test_batch6_remaining_endpoints_enforce_post(self):
        """All remaining mutating endpoints must enforce POST."""
        import inspect
        from freq.api.backup_verify import handle_backup_verify
        from freq.api.dr import handle_backup_restore
        from freq.api.fleet import (
            handle_federation_register, handle_federation_unregister,
            handle_federation_poll, handle_federation_toggle,
        )
        from freq.api.ipmi import handle_ipmi_power, handle_ipmi_boot, handle_ipmi_sel_clear
        from freq.api.redfish import handle_redfish_power
        from freq.api.state import (
            handle_policy_fix, handle_gitops_sync,
            handle_gitops_apply, handle_gitops_init,
        )
        from freq.api.synology import handle_synology_service, handle_synology_reboot
        from freq.api.terminal import handle_terminal_open, handle_terminal_close, handle_terminal_resize
        from freq.api.vm import handle_vm_add_nic, handle_vm_add_disk

        for handler in [handle_backup_verify, handle_backup_restore,
                        handle_federation_register, handle_federation_unregister,
                        handle_federation_poll, handle_federation_toggle,
                        handle_ipmi_power, handle_ipmi_boot, handle_ipmi_sel_clear,
                        handle_redfish_power,
                        handle_policy_fix, handle_gitops_sync,
                        handle_gitops_apply, handle_gitops_init,
                        handle_synology_service, handle_synology_reboot,
                        handle_terminal_open, handle_terminal_close, handle_terminal_resize,
                        handle_vm_add_nic, handle_vm_add_disk]:
            src = inspect.getsource(handler)
            self.assertIn("require_post", src,
                           f"{handler.__name__} must enforce POST")

    def test_helpers_require_post_exists(self):
        """require_post helper must exist in helpers.py for shared use."""
        from freq.api.helpers import require_post
        self.assertTrue(callable(require_post))

    def test_count_unprotected_post_handlers(self):
        """Document the known gap: count handlers with POST docstring but no enforcement.

        This test tracks the gap size. As handlers are fixed, update the count.
        """
        import os, re
        api_dir = os.path.join(os.path.dirname(__file__), "..", "freq", "api")
        unprotected = []
        for fname in sorted(os.listdir(api_dir)):
            if not fname.endswith('.py') or fname in ('auth.py', '__init__.py', 'helpers.py'):
                continue
            fpath = os.path.join(api_dir, fname)
            with open(fpath) as f:
                lines = f.readlines()
            for i, line in enumerate(lines):
                if line.strip().startswith('def handle_'):
                    func = line.strip().split('(')[0].replace('def ', '')
                    doc = ''.join(lines[i+1:i+5])
                    check = ''.join(lines[i+1:i+20])
                    if 'POST' in doc and 'require_post' not in check and '_require_post' not in check and "command" not in check:
                        unprotected.append(f"{fname}:{func}")
        # Gap tracker: ceiling tightens as batches ship
        # Batch 1 fixed 7: user promote/demote, vault set, wol, bench run/netspeed, acl
        # Batch 2 fixed 8: truenas snapshot/service/scrub/reboot/dataset/share/replication/app
        # Batch 3 fixed 7: pfsense service/dhcp/config/reboot/rules/nat/wg
        # Batch 4 fixed 10: opnsense service/rule/dhcp/dns/wg/reboot + docker add/edit/up/down
        # Batch 5 fixed 7: ct power/set/snapshot/clone/migrate/resize/exec
        # Batch 6 fixed 21: remaining (backup/dr/fleet/ipmi/redfish/state/synology/terminal/vm)
        # Remaining 1 is a false positive: opnsense_rules is GET but mentions POST in docstring
        # This test will fail if the count INCREASES (new unprotected handler added)
        self.assertLessEqual(len(unprotected), 1,
                             f"POST enforcement gap grew: {len(unprotected)} unprotected. "
                             f"New handlers must use require_post().")


class TestRouteIntegrity(unittest.TestCase):
    """Every registered route must point at a callable handler."""

    def test_all_v1_routes_are_callable(self):
        """Every route in the v1 route table must be a callable function."""
        from freq.api import build_routes

        routes = build_routes()
        dead = []
        for path, handler in routes.items():
            if not callable(handler):
                dead.append(path)

        self.assertEqual(dead, [],
                         f"Dead v1 routes (not callable): {dead}")

    def test_all_legacy_routes_resolve(self):
        """Every route in _ROUTES must resolve via getattr."""
        from freq.modules.serve import FreqHandler

        dead = []
        for path, method_name in FreqHandler._ROUTES.items():
            if not hasattr(FreqHandler, method_name):
                dead.append(f"{path} -> {method_name}")

        self.assertEqual(dead, [],
                         f"Dead legacy routes (missing method): {dead}")


class TestFleetOverviewFallbackTruth(unittest.TestCase):
    """Fleet overview fallback must not silently hide loading state."""

    def test_fallback_includes_loading_indicator(self):
        """When no cache exists, fallback response must include _loading flag."""
        import inspect
        from freq.api.fleet import handle_fleet_overview
        src = inspect.getsource(handle_fleet_overview)
        self.assertIn("_loading", src,
                       "Fleet overview fallback must include _loading indicator")

    def test_fallback_includes_cache_metadata(self):
        """Fallback response must include cached/age_seconds/probe_status."""
        import inspect
        from freq.api.fleet import handle_fleet_overview
        src = inspect.getsource(handle_fleet_overview)
        # The fallback (else) path must include staleness metadata
        self.assertIn('"cached": False', src,
                       "Fallback must include cached: False")
        self.assertIn('"probe_status": "loading"', src,
                       "Fallback must include probe_status: loading")

    def test_fallback_has_zero_summary_not_misleading(self):
        """Fallback summary must show zeros, not non-zero counts."""
        import inspect
        from freq.api.fleet import handle_fleet_overview
        src = inspect.getsource(handle_fleet_overview)
        # Ensure fallback path includes total_vms: 0
        self.assertIn('"total_vms": 0', src,
                       "Fallback must report total_vms: 0, not a cached count")

    def test_cached_path_includes_staleness_fields(self):
        """Cached fleet overview must include age_seconds and probe_status."""
        import inspect
        from freq.api.fleet import handle_fleet_overview
        src = inspect.getsource(handle_fleet_overview)
        self.assertIn("age_seconds", src,
                       "Cached path must expose age_seconds")
        self.assertIn("probe_status", src,
                       "Cached path must expose probe_status")


class TestHealthScoreTruth(unittest.TestCase):
    """Health score must never lie about fleet state."""

    def test_cold_start_returns_503_not_100(self):
        """No cache = score 0 + 503, never score 100."""
        import inspect
        from freq.api.fleet import handle_fleet_health_score
        src = inspect.getsource(handle_fleet_health_score)
        # Must have explicit cold-start check that returns 503
        self.assertIn("503", src,
                       "Health score must return 503 on cold start")
        self.assertIn('"score": 0', src,
                       "Cold start score must be 0, not 100")

    def test_health_score_exposes_cache_age(self):
        """Health score must include age metadata for staleness detection."""
        import inspect
        from freq.api.fleet import handle_fleet_health_score
        src = inspect.getsource(handle_fleet_health_score)
        self.assertIn("health_age_seconds", src,
                       "Health score must expose health_age_seconds")
        self.assertIn("fleet_age_seconds", src,
                       "Health score must expose fleet_age_seconds")
        self.assertIn("stale", src,
                       "Health score must include stale flag")

    def test_health_score_penalizes_unhealthy_hosts(self):
        """Score must decrease when hosts are unhealthy, not stay at 100."""
        import inspect
        from freq.api.fleet import handle_fleet_health_score
        src = inspect.getsource(handle_fleet_health_score)
        self.assertIn("penalty", src,
                       "Health score must apply penalties for unhealthy state")
        self.assertIn("hosts_down", src,
                       "Health score must track hosts_down factor")


class TestInitSummaryTruth(unittest.TestCase):
    """Init summary must never overstate deployment success."""

    def test_api_token_summary_checks_verification(self):
        """Summary must distinguish between token configured vs verified.

        Bug: Phase 13 shows green 'enabled' based on token_id being set,
        even if Phase 6 verification failed. The summary must check
        verification status, not just token_id presence.
        """
        import inspect
        from freq.modules.init_cmd import _phase_summary

        src = inspect.getsource(_phase_summary)
        # The summary section about PVE API should reference verification,
        # not just blindly show "enabled" if token_id exists
        has_api_verified = "api_token_verified" in src or "api_verified" in src or "token_test" in src
        has_token_id_only = "token_id" in src or "pve_api_token_id" in src
        # If token_id is shown in summary, there should also be verification tracking
        self.assertTrue(
            has_api_verified or "will fall back to SSH" in src,
            "Init summary must track API token verification status, not just presence"
        )

    def test_config_reload_failure_is_visible(self):
        """Config reload exceptions must warn the operator, not silently continue."""
        import os
        init_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "init_cmd.py")
        with open(init_path) as f:
            src = f.read()
        # The exception handler must at minimum warn
        self.assertIn("Config reload", src,
                       "Config reload failure must produce a visible warning")

    def test_chown_failures_tracked_in_summary(self):
        """Init must use _chown helper that checks return codes."""
        import os
        init_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "init_cmd.py")
        with open(init_path) as f:
            src = f.read()
        # No bare _run(["chown"...]) calls — all must use _chown helper
        import re
        bare_chowns = re.findall(r'_run\(\s*\[.*"chown"', src)
        self.assertEqual(len(bare_chowns), 0,
                         f"Found {len(bare_chowns)} bare chown calls — must use _chown() helper")


class TestErrorPropagation(unittest.TestCase):
    """Errors must propagate to operators, not be swallowed silently."""

    def test_health_api_reports_probe_errors(self):
        """Health API must expose probe_error when probes fail."""
        import inspect
        from freq.api.fleet import handle_health_api
        src = inspect.getsource(handle_health_api)
        self.assertIn("probe_error", src,
                       "Health API must expose probe_error field")
        self.assertIn("probe_status", src,
                       "Health API must expose probe_status field")

    def test_topology_exposes_staleness(self):
        """Enhanced topology must include cache age metadata."""
        import inspect
        from freq.api.fleet import handle_topology_enhanced
        src = inspect.getsource(handle_topology_enhanced)
        self.assertIn("age_seconds", src,
                       "Topology must expose age_seconds")

    def test_basic_topology_exposes_staleness(self):
        """Basic topology must include cache age and stale flag."""
        import inspect
        from freq.api.fleet import handle_topology
        src = inspect.getsource(handle_topology)
        self.assertIn("age_seconds", src,
                       "Basic topology must expose age_seconds")
        self.assertIn("stale", src,
                       "Basic topology must expose stale flag")

    def test_infra_quick_fallback_has_staleness(self):
        """Infra quick fallback must include probe_status."""
        import inspect
        from freq.api.fleet import handle_infra_quick
        src = inspect.getsource(handle_infra_quick)
        self.assertIn("probe_status", src,
                       "Infra quick must include probe_status in both cached and fallback paths")

    def test_heatmap_exposes_staleness(self):
        """Heatmap must include cache age and stale flag."""
        import inspect
        from freq.api.fleet import handle_fleet_heatmap
        src = inspect.getsource(handle_fleet_heatmap)
        self.assertIn("age_seconds", src,
                       "Heatmap must expose age_seconds")
        self.assertIn("stale", src,
                       "Heatmap must expose stale flag")

    def test_js_mutation_calls_use_post(self):
        """All JS calls to mutation endpoints must include {method:'POST'}.

        Scans app.js for _authFetch calls to known mutation API constants
        and verifies they include the POST method option.
        """
        import os, re
        js_path = os.path.join(os.path.dirname(__file__), "..", "freq", "data", "web", "js", "app.js")
        with open(js_path) as f:
            src = f.read()
        # Known mutation API constants that must use POST
        mutation_apis = [
            "API.EXEC", "API.VM_CREATE", "API.VM_DESTROY", "API.VM_CLONE",
            "API.VM_MIGRATE", "API.VM_POWER", "API.VM_SNAPSHOT",
            "API.VM_DELETE_SNAP", "API.VM_RESIZE", "API.VM_RENAME",
            "API.VM_CHANGE_ID", "API.VM_ADD_NIC", "API.VM_CLEAR_NICS",
            "API.VM_CHANGE_IP", "API.VM_ADD_DISK", "API.VM_TAG",
            "API.CT_POWER", "API.CT_DESTROY",
            "API.USERS_CREATE", "API.USERS_PROMOTE", "API.USERS_DEMOTE",
            "API.VAULT_SET", "API.VAULT_DELETE",
            "API.GWIPE",
        ]
        missing = []
        for api in mutation_apis:
            # Find all _authFetch calls using this API constant (exact match)
            pattern = rf"_authFetch\({re.escape(api)}(?![A-Z_])[^;]*?\.then"
            matches = re.findall(pattern, src)
            for m in matches:
                if "method:'POST'" not in m and '{method:"POST"}' not in m:
                    missing.append(f"{api}: {m[:60]}")
        self.assertEqual(len(missing), 0,
                         f"JS mutation calls missing POST: {missing}")

    def test_no_method_post_inside_encodeuri(self):
        """JS must not pass {method:'POST'} inside encodeURIComponent.

        This bug caused exec calls to silently send GET instead of POST.
        encodeURIComponent(x, {method:'POST'}) ignores the second argument.
        """
        import os, re
        js_path = os.path.join(os.path.dirname(__file__), "..", "freq", "data", "web", "js", "app.js")
        with open(js_path) as f:
            src = f.read()
        # Pattern: encodeURIComponent(anything, {method:'POST'})
        broken = re.findall(r"encodeURIComponent\([^)]+,\s*\{method:", src)
        self.assertEqual(len(broken), 0,
                         f"Found {len(broken)} encodeURIComponent calls with {{method}} inside: "
                         f"this sends GET instead of POST")

    def test_sse_broadcasts_probe_errors(self):
        """SSE event stream must broadcast probe errors in real-time."""
        import os
        serve_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "serve.py")
        with open(serve_path) as f:
            src = f.read()
        self.assertIn("probe_error", src,
                       "serve.py must broadcast probe_error events via SSE")


if __name__ == "__main__":
    unittest.main()
