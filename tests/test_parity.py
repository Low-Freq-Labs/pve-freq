"""Feature parity tests — new CLI commands + Web UI endpoints.

Tests for Phase 1 (CLI: power, snapshot list/delete, nic) and
Phase 2 (Web UI: doctor, diagnose, log, policy, sweep, zfs, backup, discover, gwipe).
"""
import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
        pve_nodes=["192.168.10.1"],
        pve_node_names=["pve01"],
        ssh_key_path="/tmp/fake_key",
        ssh_connect_timeout=3,
        ssh_service_account="freq-admin",  # R-PVEFREQ-BOOTSTRAP-UNTOUCHED-20260415D: freq-ops is bootstrap-only
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

class TestCmdPower(unittest.TestCase):
    """Test cmd_power in pve.py."""

    @patch("freq.modules.pve._pve_cmd", return_value=("OK", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
    def test_power_start(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="start", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 0
        mock_pve.assert_called_once()
        assert "qm start 5001" in mock_pve.call_args[0][2]

    @patch("freq.modules.pve._pve_cmd", return_value=("OK", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
    def test_power_stop(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="stop", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 0
        assert "qm stop 5001" in mock_pve.call_args[0][2]

    @patch("freq.modules.pve._pve_cmd", return_value=("OK", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
    def test_power_status(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_power
        args = _mock_args(action="status", target="5001")
        result = cmd_power(_mock_cfg(), None, args)
        assert result == 0
        assert "qm status 5001" in mock_pve.call_args[0][2]

    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
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
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
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

class TestCmdSnapshotList(unittest.TestCase):
    """Test snapshot list action."""

    @patch("freq.modules.pve._pve_cmd", return_value=(
        "`- snap1 0 bytes 2025-03-01\n`- snap2 0 bytes 2025-03-02\n-> current", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
    def test_snapshot_list_found(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_snapshot_list
        args = _mock_args(target="5001")
        result = cmd_snapshot_list(_mock_cfg(), None, args)
        assert result == 0

    @patch("freq.modules.pve._pve_cmd", return_value=("", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
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


class TestCmdSnapshotDelete(unittest.TestCase):
    """Test snapshot delete action."""

    @patch("freq.modules.pve._pve_cmd", return_value=("", True))
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
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
    @patch("freq.modules.pve._find_reachable_node", return_value="192.168.10.1")
    def test_snapshot_delete_fail(self, mock_node, mock_pve):
        from freq.modules.pve import cmd_snapshot_delete
        args = _mock_args(target="5001", name="snap1", yes=True)
        result = cmd_snapshot_delete(_mock_cfg(), None, args)
        assert result == 1


class TestCmdSnapshotDispatch(unittest.TestCase):
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

class TestCmdNic(unittest.TestCase):
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
    @patch("freq.modules.vm._find_node", return_value="192.168.10.1")
    def test_nic_add(self, mock_node, mock_pve):
        mock_pve.side_effect = [
            ("net0: virtio...", True),  # qm config
            ("", True),                  # qm set net
            ("", True),                  # qm set ipconfig
        ]
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="add", target="5001", ip="192.168.10.50")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("freq.modules.vm._pve_cmd")
    @patch("freq.modules.vm._find_node", return_value="192.168.10.1")
    def test_nic_clear(self, mock_node, mock_pve):
        mock_pve.side_effect = [
            ("net0: virtio\nipconfig0: ip=192.168.10.1/24", True),  # qm config
            ("", True),  # delete net0
            ("", True),  # delete ipconfig0
        ]
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="clear", target="5001", yes=True)
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("freq.modules.vm._pve_cmd")
    @patch("freq.modules.vm._find_node", return_value="192.168.10.1")
    def test_nic_change_ip(self, mock_node, mock_pve):
        mock_pve.side_effect = [
            ("", True),  # qm set net
            ("", True),  # qm set ipconfig
        ]
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="change-ip", target="5001", ip="192.168.10.99")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("subprocess.run")
    def test_nic_check_ip_available(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=1)
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="check-ip", ip="192.168.10.99")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    @patch("subprocess.run")
    def test_nic_check_ip_taken(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0)
        from freq.modules.vm import cmd_nic
        args = _mock_args(action="check-ip", ip="192.168.10.1")
        result = cmd_nic(_mock_cfg(), None, args)
        assert result == 0

    def test_nic_add_no_target(self):
        from freq.modules.vm import _nic_add
        args = _mock_args(ip="192.168.10.50")
        result = _nic_add(_mock_cfg(), args)
        assert result == 1

    def test_nic_add_no_ip(self):
        from freq.modules.vm import _nic_add
        args = _mock_args(target="5001")
        result = _nic_add(_mock_cfg(), args)
        assert result == 1

    def test_nic_add_protected(self):
        from freq.modules.vm import _nic_add
        args = _mock_args(target="900", ip="192.168.10.50")
        result = _nic_add(_mock_cfg(), args)
        assert result == 1

    @patch("freq.modules.vm._pve_cmd")
    @patch("freq.modules.vm._find_node", return_value="192.168.10.1")
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

class TestCLIParserParity(unittest.TestCase):
    """Verify new commands are registered in argparse (under domain subcommands)."""

    def test_power_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["vm", "power", "start", "5001"])
        assert args.action == "start"
        assert args.target == "5001"
        assert hasattr(args, "func")

    def test_snapshot_list_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["vm", "snapshot", "list", "5001"])
        assert args.snap_action == "list"
        assert args.target == "5001"

    def test_snapshot_delete_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["vm", "snapshot", "delete", "5001", "--name", "snap1"])
        assert args.snap_action == "delete"
        assert args.name == "snap1"

    def test_nic_add_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["vm", "nic", "add", "5001", "--ip", "192.168.10.50", "--vlan", "10"])
        assert args.action == "add"
        assert args.target == "5001"
        assert args.ip == "192.168.10.50"
        assert args.vlan == "10"

    def test_nic_clear_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["vm", "nic", "clear", "5001"])
        assert args.action == "clear"

    def test_nic_change_id_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["vm", "nic", "change-id", "5001", "--new-id", "5002"])
        assert args.action == "change-id"
        assert args.new_id == "5002"

    def test_nic_check_ip_registered(self):
        from freq.cli import _build_parser
        p = _build_parser()
        args = p.parse_args(["vm", "nic", "check-ip", "--ip", "192.168.10.1"])
        assert args.action == "check-ip"
        assert args.ip == "192.168.10.1"


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Web UI — New Endpoints
# ═══════════════════════════════════════════════════════════════════

# NOTE: TestServeDiagnose and TestServeLog removed — _serve_diagnose and _serve_log
# were deleted from serve.py. Those endpoints now live in freq/api/fleet.py and
# are tested via the V1 API route handlers.


class TestServeDoctor(unittest.TestCase):
    """Test /api/doctor endpoint."""

    @patch("freq.core.doctor.run", return_value=0)
    def test_doctor_ok(self, mock_doctor):
        h = _make_handler("/api/doctor")
        h._serve_doctor()
        data = _get_json(h)
        assert data["ok"] is True


# NOTE: TestServePolicyCheck, TestServePolicyFix, TestServePolicyDiff, TestServeSweep,
# TestServeZfs, TestServeBackup, TestServeDiscover, TestServeGwipe removed — all
# _serve_* methods were deleted from serve.py during the API refactor. Those endpoints
# now live in freq/api/ domain modules (secure.py, dr.py, fleet.py, hw.py) and are
# tested via the V1 API route handlers.


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Web UI — API Constants
# ═══════════════════════════════════════════════════════════════════

class TestWebUIApiConstants(unittest.TestCase):
    """Verify all new API constants are present in app.js."""

    def test_api_constants_present(self):
        from freq.modules.web_ui import _read_asset
        app_js = _read_asset("js/app.js")
        # POLICY_CHECK, POLICY_FIX, POLICY_DIFF were removed from the API object
        # (zero consumers after refactor)
        required = [
            "DOCTOR:'/api/doctor'",
            "DIAGNOSE:'/api/diagnose'",
            "LOG:'/api/log'",
            "SWEEP:'/api/sweep'",
            "PATROL_STATUS:'/api/patrol/status'",
            "ZFS:'/api/zfs'",
            "BACKUP:'/api/backup'",
            "DISCOVER:'/api/discover'",
            "GWIPE:'/api/gwipe'",
        ]
        for constant in required:
            assert constant in app_js, f"Missing API constant: {constant}"


class TestWebUIViews(unittest.TestCase):
    """Verify new view containers exist in web_ui.py."""

    def test_security_view_exists(self):
        from freq.modules.web_ui import APP_HTML
        assert 'id="security-view"' in APP_HTML
        assert 'data-view="security"' in APP_HTML

    def test_tools_view_exists(self):
        from freq.modules.web_ui import APP_HTML
        assert 'id="tools-view"' in APP_HTML
        assert 'data-view="tools"' in APP_HTML

    def test_view_ids_includes_new(self):
        """Token O swept inline `onclick="switchView('X')"` to
        `data-view="X"`. The view-id presence test now checks for the
        new attribute marker — sub-tab buttons still exist, they just
        bind via the existing data-view delegator instead of inline JS."""
        from freq.modules.web_ui import APP_HTML
        assert 'data-view="security"' in APP_HTML
        assert 'data-view="tools"' in APP_HTML


class TestWebUIJsFunctions(unittest.TestCase):
    """Verify new JS functions exist in app.js."""

    def test_policy_functions(self):
        from freq.modules.web_ui import _read_asset
        app_js = _read_asset("js/app.js")
        assert "function policyAction(" in app_js
        assert "function runSweep(" in app_js
        assert "function loadPatrolStatus(" in app_js
        assert "function loadPoliciesPage(" in app_js

    def test_ops_functions(self):
        from freq.modules.web_ui import _read_asset
        app_js = _read_asset("js/app.js")
        assert "function runDoctor(" in app_js
        assert "function runDiagnose(" in app_js
        assert "function fetchLogs(" in app_js
        assert "function loadZfs(" in app_js
        assert "function loadBackups(" in app_js
        assert "function runDiscover(" in app_js
        assert "function loadGwipe(" in app_js


# ═══════════════════════════════════════════════════════════════════
# Phase 3: Serve.py Route Coverage
# ═══════════════════════════════════════════════════════════════════

class TestRouteRegistration(unittest.TestCase):
    """Verify all new endpoints are registered in _ROUTES or _V1_ROUTES."""

    def test_new_routes_registered(self):
        # Build the combined route set from _ROUTES + _V1_ROUTES
        routes = dict(FreqHandler._ROUTES)
        FreqHandler._load_v1_routes()
        v1_routes = FreqHandler._V1_ROUTES or {}
        new_routes = [
            "/api/doctor", "/api/diagnose", "/api/log",
            "/api/policy/check", "/api/policy/fix", "/api/policy/diff",
            "/api/sweep", "/api/patrol/status",
            "/api/zfs", "/api/backup", "/api/discover", "/api/gwipe",
        ]
        for route in new_routes:
            in_routes = route in routes
            in_v1 = route in v1_routes
            assert in_routes or in_v1, f"Missing route: {route} (not in _ROUTES or _V1_ROUTES)"


# ── Phase 1D: detail + boundaries CLI ────────────────────────────────

class TestCmdDetail(unittest.TestCase):
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


class TestCmdBoundaries(unittest.TestCase):
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


class TestCLIParserPhase1D(unittest.TestCase):
    """Verify detail + boundaries are registered in argparse (under fleet domain)."""

    def test_detail_registered(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["fleet", "detail", "web01"])
        assert hasattr(args, "func")
        assert args.target == "web01"

    def test_boundaries_show(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["fleet", "boundaries"])
        assert hasattr(args, "func")
        assert args.action == "show"

    def test_boundaries_lookup(self):
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["fleet", "boundaries", "lookup", "5001"])
        assert hasattr(args, "func")
        assert args.action == "lookup"
        assert args.target == "5001"
