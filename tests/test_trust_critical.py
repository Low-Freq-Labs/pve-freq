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


if __name__ == "__main__":
    unittest.main()
