"""Feature parity tests — new CLI commands + Web UI endpoints.

Tests for Phase 1 (CLI: power, snapshot list/delete, nic) and
Phase 2 (Web UI: doctor, diagnose, log, policy, sweep, zfs, backup, discover, gwipe).
"""
import io
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.modules.serve import FreqHandler


# ── Mock helpers ────────────────────────────────────────────────────────

class MockWfile(io.BytesIO):
    pass


def _make_handler(path="/api/info"):
    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.wfile = MockWfile()
    h.rfile = io.BytesIO()
    h.requestline = f"GET {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = {}
    h._headers_buffer = []
    h.responses = {200: ("OK", ""), 404: ("Not Found", "")}
    h._status_code = None
    h._resp_headers = []
    h.send_response = lambda code, msg=None: setattr(h, '_status_code', code)
    h.send_header = lambda k, v: h._resp_headers.append((k, v))
    h.end_headers = lambda: None
    return h


def _get_json(handler):
    handler.wfile.seek(0)
    body = handler.wfile.read()
    if not body:
        return None
    return json.loads(body.decode())


def _mock_cfg(**overrides):
    from freq.core.types import FleetBoundaries
    fb = FleetBoundaries(
        tiers={
            "probe": {"actions": ["view"]},
            "operator": {"actions": ["view", "start", "stop", "restart", "snapshot"]},
            "admin": {"actions": ["view", "start", "stop", "restart", "snapshot", "resize", "migrate", "configure", "destroy"]},
        },
        categories={
            "personal": {"vmid_ranges": [[5000, 5999]], "tier": "admin"},
        },
    )
    defaults = dict(
        hosts=[],
        pve_nodes=["10.25.10.1"],
        pve_node_names=["pve01"],
        ssh_key_path="/tmp/fake_key",
        ssh_connect_timeout=3,
        ssh_service_account="freq-ops",
        brand="FREQ",
        build="dev",
        cluster_name="testcluster",
        install_dir="/opt/freq",
        vault_file="/tmp/fake_vault",
        conf_dir="/tmp/fake_conf",
        dashboard_port=8888,
        fleet_boundaries=fb,
        infrastructure={},
        protected_vmids=[100, 900],
        protected_ranges=[[800, 899]],
        nic_bridge="vmbr0",
        pve_storage={},
        vm_default_cores=2,
        vm_default_ram=2048,
        vm_default_disk=32,
        vm_cpu="host",
        vm_machine="q35",
        vm_scsihw="virtio-scsi-single",
        debug=False,
        ascii_mode=False,
        version="2.0.0",
        log_file="/dev/null",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_ssh_result(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def _mock_args(**overrides):
    defaults = dict(
        target=None, action=None, name=None, snap_action=None,
        yes=False, debug=False, ip=None, gw=None, vlan=None,
        nic_index=0, new_id=None, json=False, dry_run=False,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ═══════════════════════════════════════════════════════════════════
# Phase 1: CLI — VM Power
# ═══════════════════════════════════════════════════════════════════

class TestCmdPower:
    """Test cmd_power in pve.py."""

    @patch("freq.modules.pve._pve_cmd", return_value=("OK", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_power_start(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="start", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 0
        mock_pve.assert_called_once()
        assert "qm start 5001" in mock_pve.call_args[0][2]

    @patch("freq.modules.pve._pve_cmd", return_value=("OK", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_power_stop(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="stop", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 0
        assert "qm stop 5001" in mock_pve.call_args[0][2]

    @patch("freq.modules.pve._pve_cmd", return_value=("OK", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_power_status(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="status", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 0
        assert "qm status 5001" in mock_pve.call_args[0][2]

    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_power_protected_vm(self, mock_node):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="stop", target="900")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 1  # Protected

    def test_power_no_action(self):
        from freq.modules.pve import cmd_power
        args = _mock_args(action=None, target=None)
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 1

    @patch("freq.modules.pve._pve_cmd", return_value=("FAIL", False))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_power_ssh_fail(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="start", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 1

    @patch("freq.modules.pve._find_reachable_node", return_value=None)
    def test_power_no_node(self, mock_node):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="start", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 1


# ═══════════════════════════════════════════════════════════════════
# Phase 1: CLI — Snapshot List/Delete
# ═══════════════════════════════════════════════════════════════════

class TestCmdSnapshotList:
    """Test snapshot list action."""

    @patch("freq.modules.pve._pve_cmd", return_value=(
        "`- snap1 0 bytes 2025-03-01\n`- snap2 0 bytes 2025-03-02\n-> current", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_snapshot_list_found(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_snapshot_list
        args = _mock_args(target="5001")
        result = cmd_snapshot_list(_mock_cfg(), None, args)
        assert result == 0

    @patch("freq.modules.pve._pve_cmd", return_value=("", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_snapshot_list_empty(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_snapshot_list
        args = _mock_args(target="5001")
        result = cmd_snapshot_list(_mock_cfg(), None, args)
        assert result == 0

    def test_snapshot_list_no_target(self):
        from freq.modules.pve import cmd_snapshot_list
        args = _mock_args()
        result = cmd_snapshot_list(_mock_cfg(), None, args)
        assert result == 1

    @patch("freq.modules.pve._find_reachable_node", return_value=None)
    def test_snapshot_list_no_node(self, mock_node):
        from freq.modules.pve import cmd_snapshot_list
        args = _mock_args(target="5001")
        result = cmd_snapshot_list(_mock_cfg(), None, args)
        assert result == 1


class TestCmdSnapshotDelete:
    """Test snapshot delete action."""

    @patch("freq.modules.pve._pve_cmd", return_value=("", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_snapshot_delete_ok(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_snapshot_delete
        args = _mock_args(target="5001", name="snap1", yes=True)
        result = cmd_snapshot_delete(_mock_cfg(), None, args)
        assert result == 0
        assert "qm delsnapshot 5001 snap1" in mock_pve.call_args[0][2]

    def test_snapshot_delete_missing_name(self):
        from freq.modules.pve import cmd_snapshot_delete
        args = _mock_args(target="5001", name=None)
        result = cmd_snapshot_delete(_mock_cfg(), None, args)
        assert result == 1

    def test_snapshot_delete_bad_name(self):
        from freq.modules.pve import cmd_snapshot_delete
        args = _mock_args(target="5001", name="snap; rm -rf /")
        result = cmd_snapshot_delete(_mock_cfg(), None, args)
        assert result == 1

    @patch("freq.modules.pve._pve_cmd", return_value=("FAIL", False))
    @patch("freq.modules.pve._find_reachable_node", return_value="10.25.10.1")
    def test_snapshot_delete_fail(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_snapshot_delete
        args = _mock_args(target="5001", name="snap1", yes=True)
        result = cmd_snapshot_delete(_mock_cfg(), None, args)
        assert result == 1


class TestCmdSnapshotDispatch:
    """Test snapshot command dispatch to subactions."""

    @patch("freq.modules.pve.cmd_snapshot_list", return_value=0)
    def test_snapshot_dispatch_list(self, mock_list):
        from freq.modules.pve import cmd_snapshot
        args = _mock_args(snap_action="list", target="5001")
        result = cmd_snapshot(_mock_cfg(), None, args)
        assert result == 0
        mock_list.assert_called_once()

    @patch("freq.modules.pve.cmd_snapshot_delete", return_value=0)
    def test_snapshot_dispatch_delete(self, mock_del):
        from freq.modules.pve import cmd_snapshot
        args = _mock_args(snap_action="delete", target="5001", name="snap1")
        result = cmd_snapshot(_mock_cfg(), None, args)
        assert result == 0
        mock_del.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# Phase 1: CLI — NIC Management
# ═══════════════════════════════════════════════════════════════════

class TestCmdNic:
    """Test cmd_nic dispatch and operations."""

    def test_nic_no_action(self):
        from freq.modules.vm import cmd_nic
        args = _mock_args()
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 1

    def test_nic_bad_action(self):
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="badaction")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 1

    @patch("freq.modules.vm._pve_cmd")
    @patch("freq.modules.vm._find_node", return_value="10.25.10.1")
    def test_nic_add(self, mock_node, mock_pve):
        mock_pve.side_effect = [
            ("net0: virtio...", True),  # qm config
            ("", True),                  # qm set net
            ("", True),                  # qm set ipconfig
        ]
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="add", target="5001", ip="10.25.10.50")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("freq.modules.vm._pve_cmd")
    @patch("freq.modules.vm._find_node", return_value="10.25.10.1")
    def test_nic_clear(self, mock_node, mock_pve):
        mock_pve.side_effect = [
            ("net0: virtio\nipconfig0: ip=10.25.10.1/24", True),  # qm config
            ("", True),  # delete net0
            ("", True),  # delete ipconfig0
        ]
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="clear", target="5001", yes=True)
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("freq.modules.vm._pve_cmd")
    @patch("freq.modules.vm._find_node", return_value="10.25.10.1")
    def test_nic_change_ip(self, mock_node, mock_pve):
        mock_pve.side_effect = [
            ("", True),  # qm set net
            ("", True),  # qm set ipconfig
        ]
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="change-ip", target="5001", ip="10.25.10.99")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("subprocess.run")
    def test_nic_check_ip_available(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1)
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="check-ip", ip="10.25.10.99")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("subprocess.run")
    def test_nic_check_ip_taken(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="check-ip", ip="10.25.10.1")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    def test_nic_add_no_target(self):
        from freq.modules.vm import _nic_add
        args = _mock_args(ip="10.25.10.50")
        result = _nic_add(_mock_cfg(), args)
        assert result == 1

    def test_nic_add_no_ip(self):
        from freq.modules.vm import _nic_add
        args = _mock_args(target="5001")
        result = _nic_add(_mock_cfg(), args)
        assert result == 1

    def test_nic_add_protected(self):
        from freq.modules.vm import _nic_add
        args = _mock_args(target="900", ip="10.25.10.50")
        result = _nic_add(_mock_cfg(), args)
        assert result == 1

    @patch("freq.modules.vm._pve_cmd")
    @patch("freq.modules.vm._find_node", return_value="10.25.10.1")
    def test_nic_change_id(self, mock_node, mock_pve):
        mock_pve.side_effect = [
            ("status: stopped", True),   # qm status
            ("", True),                   # qm clone
            ("", True),                   # qm destroy
        ]
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="change-id", target="5001", new_id="5002", yes=True)
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0


# ═══════════════════════════════════════════════════════════════════
# Phase 1: CLI Parser Registration
# ═══════════════════════════════════════════════════════════════════

class TestCLIParserParity:
    """Verify new commands are registered in argparse."""

    def test_power_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["power", "start", "5001"])
        assert args.action == "start"
        assert args.target == "5001"
        assert hasattr(args, "func")

    def test_snapshot_list_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["snapshot", "list", "5001"])
        assert args.snap_action == "list"
        assert args.target == "5001"

    def test_snapshot_delete_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["snapshot", "delete", "5001", "--name", "snap1"])
        assert args.snap_action == "delete"
        assert args.name == "snap1"

    def test_nic_add_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["nic", "add", "5001", "--ip", "10.25.10.50", "--vlan", "10"])
        assert args.action == "add"
        assert args.target == "5001"
        assert args.ip == "10.25.10.50"
        assert args.vlan == "10"

    def test_nic_clear_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["nic", "clear", "5001"])
        assert args.action == "clear"

    def test_nic_change_id_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["nic", "change-id", "5001", "--new-id", "5002"])
        assert args.action == "change-id"
        assert args.new_id == "5002"

    def test_nic_check_ip_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["nic", "check-ip", "--ip", "10.25.10.1"])
        assert args.action == "check-ip"
        assert args.ip == "10.25.10.1"


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Web UI — New Endpoints
# ═══════════════════════════════════════════════════════════════════

class TestServeDiagnose:
    """Test /api/diagnose endpoint."""

    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.res")
    @patch("freq.modules.serve.load_config")
    def test_diagnose_ok(self, mock_cfg, mock_res, mock_ssh):
        mock_cfg.return_value = _mock_cfg()
        mock_res.by_target.return_value = SimpleNamespace(
            label="testhost", ip="10.25.10.50", htype="linux", groups="")
        mock_ssh.return_value = _mock_ssh_result(stdout="test output")

        h = _make_handler("/api/diagnose?target=testhost")
        h._serve_diagnose()

        data = _get_json(h)
        assert data["host"] == "testhost"
        assert "checks" in data
        assert "uptime" in data["checks"]

    @patch("freq.modules.serve.load_config")
    def test_diagnose_no_target(self, mock_cfg):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/diagnose")
        h._serve_diagnose()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.res")
    @patch("freq.modules.serve.load_config")
    def test_diagnose_unknown_host(self, mock_cfg, mock_res):
        mock_cfg.return_value = _mock_cfg()
        mock_res.by_target.return_value = None
        h = _make_handler("/api/diagnose?target=nonexistent")
        h._serve_diagnose()
        data = _get_json(h)
        assert "error" in data


class TestServeLog:
    """Test /api/log endpoint."""

    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.res")
    @patch("freq.modules.serve.load_config")
    def test_log_ok(self, mock_cfg, mock_res, mock_ssh):
        mock_cfg.return_value = _mock_cfg()
        mock_res.by_target.return_value = SimpleNamespace(
            label="testhost", ip="10.25.10.50", htype="linux", groups="")
        mock_ssh.return_value = _mock_ssh_result(stdout="Mar 25 log line 1\nMar 25 log line 2")

        h = _make_handler("/api/log?target=testhost&lines=10")
        h._serve_log()

        data = _get_json(h)
        assert data["host"] == "testhost"
        assert len(data["lines"]) > 0

    @patch("freq.modules.serve.load_config")
    def test_log_no_target(self, mock_cfg):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/log")
        h._serve_log()
        data = _get_json(h)
        assert "error" in data


class TestServeDoctor:
    """Test /api/doctor endpoint."""

    @patch("freq.core.doctor.run", return_value=0)
    def test_doctor_ok(self, mock_doctor):
        h = _make_handler("/api/doctor")
        h._serve_doctor()
        data = _get_json(h)
        assert data["ok"] is True


class TestServePolicyCheck:
    """Test /api/policy/check endpoint."""

    @patch("freq.modules.engine_cmds.cmd_check", return_value=0)
    @patch("freq.modules.serve.load_config")
    def test_policy_check_ok(self, mock_cfg, mock_check):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/policy/check")
        h._serve_policy_check()
        data = _get_json(h)
        assert data["ok"] is True

    @patch("freq.modules.engine_cmds.cmd_check", side_effect=Exception("boom"))
    @patch("freq.modules.serve.load_config")
    def test_policy_check_error(self, mock_cfg, mock_check):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/policy/check")
        h._serve_policy_check()
        data = _get_json(h)
        assert "error" in data


class TestServePolicyFix:
    """Test /api/policy/fix endpoint (requires admin)."""

    @patch("freq.modules.serve._check_session_role", return_value=("admin", None))
    @patch("freq.modules.engine_cmds.cmd_fix", return_value=0)
    @patch("freq.modules.serve.load_config")
    def test_policy_fix_ok(self, mock_cfg, mock_fix, mock_role):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/policy/fix?token=test")
        h._serve_policy_fix()
        data = _get_json(h)
        assert data["ok"] is True

    @patch("freq.modules.serve._check_session_role", return_value=(None, "Unauthorized"))
    @patch("freq.modules.serve.load_config")
    def test_policy_fix_unauthorized(self, mock_cfg, mock_role):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/policy/fix")
        h._serve_policy_fix()
        data = _get_json(h)
        assert "error" in data


class TestServePolicyDiff:
    """Test /api/policy/diff endpoint."""

    @patch("freq.modules.engine_cmds.cmd_diff", return_value=0)
    @patch("freq.modules.serve.load_config")
    def test_policy_diff_ok(self, mock_cfg, mock_diff):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/policy/diff")
        h._serve_policy_diff()
        data = _get_json(h)
        assert data["ok"] is True


class TestServeSweep:
    """Test /api/sweep endpoint."""

    @patch("freq.modules.serve._check_session_role", return_value=("operator", None))
    @patch("freq.jarvis.sweep.cmd_sweep", return_value=0)
    @patch("freq.modules.serve.load_config")
    def test_sweep_dry_run(self, mock_cfg, mock_sweep, mock_role):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/sweep?fix=false&token=test")
        h._serve_sweep()
        data = _get_json(h)
        assert data["ok"] is True
        assert data["fix_mode"] is False


class TestServeZfs:
    """Test /api/zfs endpoint."""

    @patch("freq.modules.infrastructure.cmd_zfs", return_value=0)
    @patch("freq.modules.serve.load_config")
    def test_zfs_status(self, mock_cfg, mock_zfs):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/zfs?action=status")
        h._serve_zfs()
        data = _get_json(h)
        assert data["ok"] is True


class TestServeBackup:
    """Test /api/backup endpoint."""

    @patch("freq.modules.backup.cmd_backup", return_value=0)
    @patch("freq.modules.serve.load_config")
    def test_backup_list(self, mock_cfg, mock_backup):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/backup?action=list")
        h._serve_backup()
        data = _get_json(h)
        assert data["ok"] is True
        assert data["action"] == "list"


class TestServeDiscover:
    """Test /api/discover endpoint."""

    @patch("freq.modules.serve._check_session_role", return_value=("operator", None))
    @patch("freq.modules.discover.cmd_discover", return_value=0)
    @patch("freq.modules.serve.load_config")
    def test_discover_ok(self, mock_cfg, mock_discover, mock_role):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/discover?token=test")
        h._serve_discover()
        data = _get_json(h)
        assert data["ok"] is True


class TestServeGwipe:
    """Test /api/gwipe endpoint."""

    @patch("freq.modules.serve._check_session_role", return_value=("admin", None))
    @patch("freq.modules.serve.vault_get", return_value="")
    @patch("freq.modules.serve.load_config")
    def test_gwipe_not_configured(self, mock_cfg, mock_vault, mock_role):
        mock_cfg.return_value = _mock_cfg()
        h = _make_handler("/api/gwipe?token=test")
        h._serve_gwipe()
        data = _get_json(h)
        assert "error" in data
        assert "not configured" in data["error"].lower()


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Web UI — API Constants
# ═══════════════════════════════════════════════════════════════════

class TestWebUIApiConstants:
    """Verify all new API constants are present in web_ui.py."""

    def test_api_constants_present(self):
        from freq.modules.web_ui import APP_HTML
        required = [
            "DOCTOR:'/api/doctor'",
            "DIAGNOSE:'/api/diagnose'",
            "LOG:'/api/log'",
            "POLICY_CHECK:'/api/policy/check'",
            "POLICY_FIX:'/api/policy/fix'",
            "POLICY_DIFF:'/api/policy/diff'",
            "SWEEP:'/api/sweep'",
            "PATROL_STATUS:'/api/patrol/status'",
            "ZFS:'/api/zfs'",
            "BACKUP:'/api/backup'",
            "DISCOVER:'/api/discover'",
            "GWIPE:'/api/gwipe'",
        ]
        for constant in required:
            assert constant in APP_HTML, f"Missing API constant: {constant}"


class TestWebUIViews:
    """Verify new view containers exist in web_ui.py."""

    def test_policies_view_exists(self):
        from freq.modules.web_ui import APP_HTML
        assert 'id="policies-view"' in APP_HTML
        assert 'data-view="policies"' in APP_HTML

    def test_ops_view_exists(self):
        from freq.modules.web_ui import APP_HTML
        assert 'id="ops-view"' in APP_HTML
        assert 'data-view="ops"' in APP_HTML

    def test_view_ids_includes_new(self):
        from freq.modules.web_ui import APP_HTML
        assert "'policies'" in APP_HTML
        assert "'ops'" in APP_HTML


class TestWebUIJsFunctions:
    """Verify new JS functions exist."""

    def test_policy_functions(self):
        from freq.modules.web_ui import APP_HTML
        assert "function policyAction(" in APP_HTML
        assert "function runSweep(" in APP_HTML
        assert "function loadPatrolStatus(" in APP_HTML
        assert "function loadPoliciesPage(" in APP_HTML

    def test_ops_functions(self):
        from freq.modules.web_ui import APP_HTML
        assert "function runDoctor(" in APP_HTML
        assert "function runDiagnose(" in APP_HTML
        assert "function fetchLogs(" in APP_HTML
        assert "function loadZfs(" in APP_HTML
        assert "function loadBackups(" in APP_HTML
        assert "function runDiscover(" in APP_HTML
        assert "function loadGwipe(" in APP_HTML


# ═══════════════════════════════════════════════════════════════════
# Phase 3: Serve.py Route Coverage
# ═══════════════════════════════════════════════════════════════════

class TestRouteRegistration:
    """Verify all new endpoints are in the _ROUTES dict."""

    def test_new_routes_registered(self):
        routes = FreqHandler._ROUTES
        new_routes = [
            "/api/doctor", "/api/diagnose", "/api/log",
            "/api/policy/check", "/api/policy/fix", "/api/policy/diff",
            "/api/sweep", "/api/patrol/status",
            "/api/zfs", "/api/backup", "/api/discover", "/api/gwipe",
        ]
        for route in new_routes:
            assert route in routes, f"Missing route: {route}"
            # Verify handler method exists
            method_name = routes[route]
            assert hasattr(FreqHandler, method_name), f"Missing handler: {method_name}"


# ── Phase 1D: detail + boundaries CLI ────────────────────────────────

class TestCmdDetail:
    """Tests for cmd_detail — deep host inventory."""

    def _make_cfg(self):
        from freq.core.types import Host
        cfg = MagicMock()
        cfg.hosts = [Host(ip="10.0.0.1", label="web01", htype="linux", groups="web")]
        cfg.ssh_key_path = "/tmp/fake_key"
        cfg.ssh_connect_timeout = 3
        return cfg

    @patch("freq.modules.fleet.ssh_run")
    def test_detail_ok(self, mock_ssh):
        from freq.modules.fleet import cmd_detail
        mock_ssh.return_value = MagicMock(returncode=0, stdout="test-output")
        cfg = self._make_cfg()
        args = SimpleNamespace(target="web01")
        rc = cmd_detail(cfg, None, args)
        assert rc == 0
        assert mock_ssh.called

    def test_detail_no_target(self):
        from freq.modules.fleet import cmd_detail
        cfg = self._make_cfg()
        args = SimpleNamespace(target=None)
        rc = cmd_detail(cfg, None, args)
        assert rc == 1

    @patch("freq.modules.fleet.ssh_run")
    def test_detail_unknown_host(self, mock_ssh):
        from freq.modules.fleet import cmd_detail
        cfg = self._make_cfg()
        args = SimpleNamespace(target="nope99")
        rc = cmd_detail(cfg, None, args)
        assert rc == 1
        assert not mock_ssh.called


class TestCmdBoundaries:
    """Tests for cmd_boundaries — fleet permission tiers."""

    def _make_cfg(self):
        from freq.core.types import FleetBoundaries
        fb = FleetBoundaries()
        fb.tiers = {
            "probe": ["view"],
            "operator": ["view", "start", "stop", "restart", "snapshot"],
            "admin": ["view", "start", "stop", "restart", "snapshot", "destroy", "clone", "migrate"],
        }
        fb.categories = {
            "lab": {"description": "Lab VMs", "tier": "admin", "range_start": 5000, "range_end": 5999},
            "infrastructure": {"description": "Core infra", "tier": "operator", "vmids": [100, 101]},
        }
        cfg = MagicMock()
        cfg.fleet_boundaries = fb
        return cfg

    def test_show(self):
        from freq.modules.fleet import cmd_boundaries
        cfg = self._make_cfg()
        args = SimpleNamespace(action="show", target=None)
        rc = cmd_boundaries(cfg, None, args)
        assert rc == 0

    def test_lookup_lab(self):
        from freq.modules.fleet import cmd_boundaries
        cfg = self._make_cfg()
        args = SimpleNamespace(action="lookup", target="5001")
        rc = cmd_boundaries(cfg, None, args)
        assert rc == 0

    def test_lookup_infra(self):
        from freq.modules.fleet import cmd_boundaries
        cfg = self._make_cfg()
        args = SimpleNamespace(action="lookup", target="100")
        rc = cmd_boundaries(cfg, None, args)
        assert rc == 0

    def test_lookup_no_target(self):
        from freq.modules.fleet import cmd_boundaries
        cfg = self._make_cfg()
        args = SimpleNamespace(action="lookup", target=None)
        rc = cmd_boundaries(cfg, None, args)
        assert rc == 1

    def test_lookup_invalid_vmid(self):
        from freq.modules.fleet import cmd_boundaries
        cfg = self._make_cfg()
        args = SimpleNamespace(action="lookup", target="abc")
        rc = cmd_boundaries(cfg, None, args)
        assert rc == 1

    def test_unknown_action(self):
        from freq.modules.fleet import cmd_boundaries
        cfg = self._make_cfg()
        args = SimpleNamespace(action="nope", target=None)
        rc = cmd_boundaries(cfg, None, args)
        assert rc == 1


class TestCLIParserPhase1D:
    """Verify detail + boundaries are registered in argparse."""

    def test_detail_registered(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["detail", "web01"])
        assert hasattr(args, "func")
        assert args.target == "web01"

    def test_boundaries_show(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["boundaries"])
        assert hasattr(args, "func")
        assert args.action == "show"

    def test_boundaries_lookup(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["boundaries", "lookup", "5001"])
        assert hasattr(args, "func")
        assert args.action == "lookup"
        assert args.target == "5001"
