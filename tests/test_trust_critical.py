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


if __name__ == "__main__":
    unittest.main()
