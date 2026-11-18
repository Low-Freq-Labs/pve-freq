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
        ssh_service_account="freq-admin",  # freq-ops is bootstrap-only
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

    def setUp(self):
        # Unit tests must not probe the documentation subnet while resolving
        # VM ownership.  The command result itself remains patched per test.
        self._vm_node_patcher = patch(
            "freq.modules.pve._find_vm_node", return_value="192.168.10.1"
        )
        self._vm_node_patcher.start()
        self.addCleanup(self._vm_node_patcher.stop)

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

    def setUp(self):
        self._vm_node_patcher = patch(
            "freq.modules.pve._find_vm_node", return_value="192.168.10.1"
        )
        self._vm_node_patcher.start()
        self.addCleanup(self._vm_node_patcher.stop)

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

    def setUp(self):
        self._vm_node_patcher = patch(
            "freq.modules.pve._find_vm_node", return_value="192.168.10.1"
        )
        self._vm_node_patcher.start()
        self.addCleanup(self._vm_node_patcher.stop)

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
    @patch("freq.modules.vm._find_vm_node", return_value="192.168.10.1")
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
    @patch("freq.modules.vm._find_vm_node", return_value="192.168.10.1")
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
    @patch("freq.modules.vm._find_vm_node", return_value="192.168.10.1")
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
    @patch("freq.modules.vm._find_vm_node", return_value="192.168.10.1")
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
        from freq.modules.web_ui import read_asset
        app_js = read_asset("js/app.js")
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
        self._case_deploy_log_behavior()

    def _case_deploy_log_behavior(self):
        from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
        from pathlib import Path

        from freq.services import deployment_history

        def attribute_path(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, Attribute):
                parent = attribute_path(node.value)
                return f"{parent}.{node.attr}" if parent else node.attr
            return ""

        repo_root = Path(__file__).parent.parent
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        service_tree = parse(
            (repo_root / "freq/services/deployment_history.py").read_text()
        )
        service_imports = set()
        for node in walk(service_tree):
            if isinstance(node, Import):
                service_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                service_imports.add(node.module)
        self.assertEqual(service_imports, {"subprocess"})
        self.assertIn(
            "read_deploy_log",
            {node.name for node in walk(service_tree) if isinstance(node, FunctionDef)},
        )
        handler_node = next(
            node
            for node in walk(serve_tree)
            if isinstance(node, FunctionDef) and node.name == "_serve_deploy_log"
        )
        self.assertEqual(len(handler_node.body), 2)
        handler_calls = {
            attribute_path(node.func)
            for node in walk(handler_node)
            if isinstance(node, Call)
        }
        self.assertIn("_deployment_history.read_deploy_log", handler_calls)
        self.assertIn("load_config", handler_calls)
        self.assertNotIn("subprocess.run", handler_calls)
        self.assertIs(deployment_history.subprocess, __import__("subprocess"))

        cfg = SimpleNamespace(install_dir="/opt/freq-test")
        result = MagicMock(
            returncode=0,
            stdout=(
                "1234567890abcdef|initial install|2 hours ago\n"
                "malformed\n"
                "fedcba9876543210|upgrade complete|yesterday|local time\n"
            ),
        )
        with (
            patch("freq.modules.serve.load_config", return_value=cfg) as load_config,
            patch(
                "freq.services.deployment_history.subprocess.run",
                return_value=result,
            ) as run,
        ):
            handler = _make_handler("/api/deploy/log")
            handler._serve_deploy_log()

        assert (handler._status_code, _get_json(handler)) == (
            200,
            {
                "commits": [
                    {
                        "hash": "12345678",
                        "message": "initial install",
                        "ago": "2 hours ago",
                    },
                    {
                        "hash": "fedcba98",
                        "message": "upgrade complete",
                        "ago": "yesterday|local time",
                    },
                ],
                "count": 2,
            },
        )
        load_config.assert_called_once_with()
        run.assert_called_once_with(
            ["git", "log", "--oneline", "-20", "--format=%H|%s|%ar"],
            cwd=cfg.install_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )

        nonzero = MagicMock(returncode=7, stdout="ignored|commit|now\n")
        with (
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch(
                "freq.services.deployment_history.subprocess.run",
                return_value=nonzero,
            ) as run,
        ):
            handler = _make_handler("/api/deploy/log")
            handler._serve_deploy_log()
        assert (handler._status_code, _get_json(handler)) == (
            200,
            {"commits": [], "count": 0},
        )
        run.assert_called_once_with(
            ["git", "log", "--oneline", "-20", "--format=%H|%s|%ar"],
            cwd=cfg.install_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )

        with (
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch(
                "freq.services.deployment_history.subprocess.run",
                side_effect=RuntimeError("git unavailable"),
            ) as run,
        ):
            handler = _make_handler("/api/deploy/log")
            handler._serve_deploy_log()
        assert (handler._status_code, _get_json(handler)) == (
            200,
            {
                "commits": [],
                "count": 0,
                "error": "git unavailable",
                "request_id": "",
            },
        )
        run.assert_called_once_with(
            ["git", "log", "--oneline", "-20", "--format=%H|%s|%ar"],
            cwd=cfg.install_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )


class TestWebUIViews(unittest.TestCase):
    """Verify new view containers exist in web_ui.py."""

    def test_security_view_exists(self):
        from freq.modules.web_ui import load_app_html
        app_html = load_app_html()
        assert 'id="security-view"' in app_html
        assert 'data-view="security"' in app_html

    def test_tools_view_exists(self):
        from freq.modules.web_ui import load_app_html
        app_html = load_app_html()
        assert 'id="tools-view"' in app_html
        assert 'data-view="tools"' in app_html

    def test_view_ids_includes_new(self):
        """Token O swept inline `onclick="switchView('X')"` to
        `data-view="X"`. The view-id presence test now checks for the
        new attribute marker — sub-tab buttons still exist, they just
        bind via the existing data-view delegator instead of inline JS."""
        from freq.modules.web_ui import load_app_html
        app_html = load_app_html()
        assert 'data-view="security"' in app_html
        assert 'data-view="tools"' in app_html


class TestWebUIJsFunctions(unittest.TestCase):
    """Verify new JS functions exist in app.js."""

    def test_policy_functions(self):
        from freq.modules.web_ui import read_asset
        app_js = read_asset("js/app.js")
        assert "function policyAction(" in app_js
        assert "function runSweep(" in app_js
        assert "function loadPatrolStatus(" in app_js
        assert "function loadPoliciesPage(" in app_js

    def test_ops_functions(self):
        from freq.modules.web_ui import read_asset
        app_js = read_asset("js/app.js")
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
    """Verify all new endpoints are present in the complete route registry."""

    def test_new_routes_registered(self):
        routes = FreqHandler._load_routes()
        new_routes = [
            "/api/doctor", "/api/diagnose", "/api/log",
            "/api/policy/check", "/api/policy/fix", "/api/policy/diff",
            "/api/sweep", "/api/patrol/status",
            "/api/zfs", "/api/backup", "/api/discover", "/api/gwipe",
        ]
        for route in new_routes:
            assert route in routes, f"Missing route: {route}"


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
