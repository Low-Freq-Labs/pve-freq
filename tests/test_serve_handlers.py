"""Tier 5B: serve.py HTTP handler tests with MockFreqHandler.

Tests HTTP endpoints by creating a mock handler that captures JSON responses
without needing real sockets or SSH backends.
"""
import hashlib
import io
import json
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.modules.serve import (
    FreqHandler,
    SESSION_TIMEOUT_SECONDS,
    _parse_query,
)


# ── Mock handler factory ────────────────────────────────────────────────

class MockWfile(io.BytesIO):
    """Captures bytes written to wfile."""
    pass


def _make_handler(path="/api/info"):
    """Create a FreqHandler instance without opening a real socket.

    The handler has:
    - h.path set to the given path
    - h.wfile captures written bytes
    - h.send_response / send_header / end_headers are no-ops
    - h._captured: parsed JSON from _json_response calls
    """
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

    # Track response metadata
    h._status_code = None
    h._resp_headers = []

    _orig_send = h.send_response

    def mock_send(code, msg=None):
        h._status_code = code

    def mock_header(k, v):
        h._resp_headers.append((k, v))

    h.send_response = mock_send
    h.send_header = mock_header
    h.end_headers = lambda: None
    return h


def _get_json(handler):
    """Extract JSON response body from handler.wfile."""
    handler.wfile.seek(0)
    body = handler.wfile.read()
    if not body:
        return None
    return json.loads(body.decode())


# ── Mock config ─────────────────────────────────────────────────────────

def _mock_cfg(**overrides):
    """Create a minimal mock config for handler tests."""
    from freq.core.types import FleetBoundaries

    fb = FleetBoundaries(
        tiers={
            "probe": {"actions": ["view"]},
            "operator": {"actions": ["view", "start", "stop", "restart", "snapshot"]},
            "admin": {"actions": ["view", "start", "stop", "restart", "snapshot", "resize", "migrate", "configure", "destroy"]},
        },
        categories={
            "personal": {"vmid_ranges": [[5000, 5999]], "tier": "admin"},
            "prod_media": {"vmid_ranges": [[200, 299]], "tier": "operator"},
            "lab": {"vmid_ranges": [[3000, 3999]], "tier": "probe"},
        },
    )
    defaults = dict(
        hosts=[],
        pve_nodes=["192.168.10.1"],
        ssh_key_path="/tmp/fake_key",
        brand="FREQ",
        build="dev",
        cluster_name="testcluster",
        install_dir="/opt/freq",
        vault_file="/tmp/fake_vault",
        conf_dir="/tmp/fake_conf",
        dashboard_port=8888,
        fleet_boundaries=fb,
        infrastructure={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_host(label="testhost", ip="192.168.10.50", htype="linux", groups=""):
    return SimpleNamespace(label=label, ip=ip, htype=htype, groups=groups)


def _mock_ssh_result(stdout="", stderr="", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# ══════════════════════════════════════════════════════════════════════════
# Auth Tests
# ══════════════════════════════════════════════════════════════════════════

class TestAuthLogin:
    """Test /api/auth/login endpoint."""

    def setup_method(self):
        FreqHandler._auth_tokens.clear()

    @patch("freq.modules.serve.vault_get", return_value=None)
    @patch("freq.modules.serve.vault_set")
    @patch("freq.modules.serve.vault_init")
    @patch("freq.modules.serve._load_users", return_value=[
        {"username": "admin", "role": "admin"},
        {"username": "viewer", "role": "viewer"},
    ])
    @patch("freq.modules.serve.load_config")
    def test_login_success_first_time(self, mock_cfg_fn, mock_users, mock_vinit, mock_vset, mock_vget):
        """First login sets password and returns token."""
        cfg = _mock_cfg()
        cfg.vault_file = "/tmp/fake_vault"
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/auth/login?username=admin&password=secret123")
        with patch("os.path.exists", return_value=False):
            h._serve_auth_login()

        data = _get_json(h)
        assert data["ok"] is True
        assert data["user"] == "admin"
        assert data["role"] == "admin"
        assert len(data["token"]) == 32
        assert data["token"] in FreqHandler._auth_tokens

    @patch("freq.modules.serve.vault_get")
    @patch("freq.modules.serve._load_users", return_value=[
        {"username": "admin", "role": "admin"},
    ])
    @patch("freq.modules.serve.load_config")
    def test_login_correct_password(self, mock_cfg_fn, mock_users, mock_vget):
        """Login with correct stored password succeeds."""
        cfg = _mock_cfg()
        mock_cfg_fn.return_value = cfg
        pw_hash = hashlib.sha256(b"correct_pw").hexdigest()
        mock_vget.return_value = pw_hash

        h = _make_handler("/api/auth/login?username=admin&password=correct_pw")
        h._serve_auth_login()

        data = _get_json(h)
        assert data["ok"] is True
        assert data["user"] == "admin"

    @patch("freq.modules.serve.vault_get")
    @patch("freq.modules.serve._load_users", return_value=[
        {"username": "admin", "role": "admin"},
    ])
    @patch("freq.modules.serve.load_config")
    def test_login_wrong_password(self, mock_cfg_fn, mock_users, mock_vget):
        """Login with wrong password returns error."""
        cfg = _mock_cfg()
        mock_cfg_fn.return_value = cfg
        mock_vget.return_value = hashlib.sha256(b"real_password").hexdigest()

        h = _make_handler("/api/auth/login?username=admin&password=wrong")
        h._serve_auth_login()

        data = _get_json(h)
        assert "error" in data
        assert "Invalid password" in data["error"]

    @patch("freq.modules.serve._load_users", return_value=[])
    @patch("freq.modules.serve.load_config")
    def test_login_unknown_user(self, mock_cfg_fn, mock_users):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/auth/login?username=nobody&password=pw")
        h._serve_auth_login()

        data = _get_json(h)
        assert "Unknown user" in data["error"]

    def test_login_missing_credentials(self):
        h = _make_handler("/api/auth/login?username=&password=")
        h._serve_auth_login()

        data = _get_json(h)
        assert "required" in data["error"].lower()

    def test_login_no_params(self):
        h = _make_handler("/api/auth/login")
        h._serve_auth_login()

        data = _get_json(h)
        assert "required" in data["error"].lower()


class TestAuthVerify:
    """Test /api/auth/verify endpoint."""

    def setup_method(self):
        FreqHandler._auth_tokens.clear()

    def test_verify_valid_session(self):
        FreqHandler._auth_tokens["tok123"] = {
            "user": "admin", "role": "admin", "ts": time.time(),
        }

        h = _make_handler("/api/auth/verify?token=tok123")
        h._serve_auth_verify()

        data = _get_json(h)
        assert data["valid"] is True
        assert data["user"] == "admin"
        assert data["role"] == "admin"

    def test_verify_expired_session(self):
        FreqHandler._auth_tokens["old_tok"] = {
            "user": "admin", "role": "admin",
            "ts": time.time() - SESSION_TIMEOUT_SECONDS - 1,
        }

        h = _make_handler("/api/auth/verify?token=old_tok")
        h._serve_auth_verify()

        data = _get_json(h)
        assert data["valid"] is False
        assert "old_tok" not in FreqHandler._auth_tokens

    def test_verify_invalid_token(self):
        h = _make_handler("/api/auth/verify?token=nonexistent")
        h._serve_auth_verify()

        data = _get_json(h)
        assert data["valid"] is False

    def test_verify_no_token(self):
        h = _make_handler("/api/auth/verify")
        h._serve_auth_verify()

        data = _get_json(h)
        assert data["valid"] is False


class TestAuthChangePassword:
    """Test /api/auth/change-password endpoint."""

    def setup_method(self):
        FreqHandler._auth_tokens.clear()

    @patch("freq.modules.serve.vault_init")
    @patch("freq.modules.serve.vault_set")
    @patch("freq.modules.serve.load_config")
    def test_change_password_success(self, mock_cfg_fn, mock_vset, mock_vinit):
        mock_cfg_fn.return_value = _mock_cfg()
        FreqHandler._auth_tokens["tok_cp"] = {
            "user": "admin", "role": "admin", "ts": time.time(),
        }

        with patch("os.path.exists", return_value=True):
            h = _make_handler("/api/auth/change-password?token=tok_cp&password=newpass123")
            h._serve_auth_change_password()

        data = _get_json(h)
        assert data["ok"] is True

    def test_change_password_not_authenticated(self):
        h = _make_handler("/api/auth/change-password?password=x")
        h._serve_auth_change_password()

        data = _get_json(h)
        assert "Not authenticated" in data["error"]

    def test_change_password_too_short(self):
        FreqHandler._auth_tokens["tok_short"] = {
            "user": "admin", "role": "admin", "ts": time.time(),
        }

        h = _make_handler("/api/auth/change-password?token=tok_short&password=abc")
        h._serve_auth_change_password()

        data = _get_json(h)
        assert "6 characters" in data["error"]


# ══════════════════════════════════════════════════════════════════════════
# Info / Status Tests
# ══════════════════════════════════════════════════════════════════════════

class TestServeInfo:
    """Test /api/info endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_info_returns_expected_fields(self, mock_cfg_fn):
        cfg = _mock_cfg()
        mock_cfg_fn.return_value = cfg

        with patch("freq.core.personality.load_pack", return_value=None):
            h = _make_handler("/api/info")
            h._serve_info()

        data = _get_json(h)
        assert "version" in data
        assert data["brand"] == "FREQ"
        assert data["build"] == "dev"
        assert data["cluster"] == "testcluster"
        assert data["hosts"] == 0
        # pve_nodes count comes from _get_discovered_nodes() which uses
        # cache or fleet-boundaries fallback, not cfg.pve_nodes directly
        assert isinstance(data["pve_nodes"], int)

    @patch("freq.modules.serve.load_config")
    def test_info_with_pack(self, mock_cfg_fn):
        cfg = _mock_cfg()
        mock_cfg_fn.return_value = cfg
        mock_pack = SimpleNamespace(subtitle="TestSub", dashboard_header="TestHead")

        with patch("freq.core.personality.load_pack", return_value=mock_pack):
            h = _make_handler("/api/info")
            h._serve_info()

        data = _get_json(h)
        assert data["subtitle"] == "TestSub"
        assert data["dashboard_header"] == "TestHead"


class TestServeStatus:
    """Test /api/status endpoint."""

    @patch("freq.modules.serve.ssh_run_many")
    @patch("freq.modules.serve.load_config")
    def test_status_all_hosts_up(self, mock_cfg_fn, mock_ssh):
        hosts = [_mock_host("h1", "10.0.0.1"), _mock_host("h2", "10.0.0.2")]
        mock_cfg_fn.return_value = _mock_cfg(hosts=hosts)
        mock_ssh.return_value = {
            "h1": _mock_ssh_result("up 2 days"),
            "h2": _mock_ssh_result("up 5 hours"),
        }

        h = _make_handler("/api/status")
        h._serve_status()

        data = _get_json(h)
        assert data["total"] == 2
        assert data["up"] == 2
        assert data["down"] == 0
        assert len(data["hosts"]) == 2
        assert data["hosts"][0]["status"] == "up"

    @patch("freq.modules.serve.ssh_run_many")
    @patch("freq.modules.serve.load_config")
    def test_status_mixed_hosts(self, mock_cfg_fn, mock_ssh):
        hosts = [_mock_host("h1"), _mock_host("h2")]
        mock_cfg_fn.return_value = _mock_cfg(hosts=hosts)
        mock_ssh.return_value = {
            "h1": _mock_ssh_result("up 1 day"),
            "h2": _mock_ssh_result("", returncode=1),
        }

        h = _make_handler("/api/status")
        h._serve_status()

        data = _get_json(h)
        assert data["up"] == 1
        assert data["down"] == 1

    @patch("freq.modules.serve.ssh_run_many")
    @patch("freq.modules.serve.load_config")
    def test_status_no_hosts(self, mock_cfg_fn, mock_ssh):
        mock_cfg_fn.return_value = _mock_cfg(hosts=[])
        mock_ssh.return_value = {}

        h = _make_handler("/api/status")
        h._serve_status()

        data = _get_json(h)
        assert data["total"] == 0
        assert data["hosts"] == []


# ══════════════════════════════════════════════════════════════════════════
# Vault Tests
# ══════════════════════════════════════════════════════════════════════════

class TestServeVault:
    """Test /api/vault endpoints."""

    @patch("freq.modules.serve.vault_list")
    @patch("freq.modules.serve.load_config")
    def test_vault_list(self, mock_cfg_fn, mock_vlist):
        cfg = _mock_cfg()
        cfg.vault_file = "/tmp/fakevault"
        mock_cfg_fn.return_value = cfg
        mock_vlist.return_value = [
            ("DEFAULT", "db_host", "10.0.0.5"),
            ("DEFAULT", "password_admin", "hashed_value"),
        ]

        with patch("os.path.exists", return_value=True):
            h = _make_handler("/api/vault")
            h._serve_vault()

        data = _get_json(h)
        assert data["initialized"] is True
        assert data["count"] == 2
        # Sensitive keys should be masked
        pw_entry = [e for e in data["entries"] if e["key"] == "password_admin"][0]
        assert pw_entry["masked"] == "********"
        # Non-sensitive keys show preview
        db_entry = [e for e in data["entries"] if e["key"] == "db_host"][0]
        assert db_entry["masked"] == "10.0.0.5"

    @patch("freq.modules.serve.load_config")
    def test_vault_uninitialized(self, mock_cfg_fn):
        cfg = _mock_cfg()
        cfg.vault_file = "/tmp/nonexistent"
        mock_cfg_fn.return_value = cfg

        with patch("os.path.exists", return_value=False):
            h = _make_handler("/api/vault")
            h._serve_vault()

        data = _get_json(h)
        assert data["initialized"] is False
        assert data["entries"] == []

    @patch("freq.modules.serve.vault_set", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_vault_set_success(self, mock_cfg_fn, mock_vset):
        cfg = _mock_cfg()
        cfg.vault_file = "/tmp/fakevault"
        mock_cfg_fn.return_value = cfg

        with patch("os.path.exists", return_value=True):
            h = _make_handler("/api/vault/set?key=mykey&value=myval&host=DEFAULT")
            h._serve_vault_set()

        data = _get_json(h)
        assert data["ok"] is True
        assert data["key"] == "mykey"

    @patch("freq.modules.serve.load_config")
    def test_vault_set_missing_params(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vault/set?key=&value=")
        h._serve_vault_set()

        data = _get_json(h)
        assert "required" in data["error"].lower()

    @patch("freq.modules.serve.vault_delete", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_vault_delete(self, mock_cfg_fn, mock_vdel):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vault/delete?key=mykey&host=DEFAULT")
        h._serve_vault_delete()

        data = _get_json(h)
        assert data["ok"] is True


# ══════════════════════════════════════════════════════════════════════════
# User Management Tests
# ══════════════════════════════════════════════════════════════════════════

class TestServeUsers:
    """Test /api/users endpoints."""

    @patch("freq.modules.serve._load_users", return_value=[
        {"username": "admin", "role": "admin"},
        {"username": "ops", "role": "operator"},
    ])
    @patch("freq.modules.serve.load_config")
    def test_users_list(self, mock_cfg_fn, mock_users):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/users")
        h._serve_users()

        data = _get_json(h)
        assert data["count"] == 2
        assert len(data["users"]) == 2
        assert "roles" in data

    @patch("freq.modules.serve._save_users")
    @patch("freq.modules.serve._load_users", return_value=[
        {"username": "admin", "role": "admin"},
    ])
    @patch("freq.modules.serve.load_config")
    def test_user_create_duplicate(self, mock_cfg_fn, mock_users, mock_save):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/users/create?username=admin&password=pw&role=operator")
        h._serve_user_create()

        data = _get_json(h)
        assert "already exists" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_user_create_missing_username(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/users/create?username=&password=pw")
        h._serve_user_create()

        data = _get_json(h)
        assert "required" in data["error"].lower()


# ══════════════════════════════════════════════════════════════════════════
# Exec Tests
# ══════════════════════════════════════════════════════════════════════════

class TestServeExec:
    """Test /api/exec endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_exec_no_command(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/exec?target=all&cmd=")
        h._serve_exec()

        data = _get_json(h)
        assert "No command" in data["error"]

    @patch("freq.modules.serve.ssh_run_many")
    @patch("freq.modules.serve.res")
    @patch("freq.modules.serve.load_config")
    def test_exec_single_target(self, mock_cfg_fn, mock_res, mock_ssh):
        host = _mock_host("myhost", "10.0.0.1")
        mock_cfg_fn.return_value = _mock_cfg(hosts=[host])
        mock_res.by_group.return_value = []
        mock_res.by_type.return_value = []
        mock_res.by_target.return_value = host
        mock_ssh.return_value = {"myhost": _mock_ssh_result("hello")}

        h = _make_handler("/api/exec?target=myhost&cmd=echo+hello")
        h._serve_exec()

        data = _get_json(h)
        assert data["target"] == "myhost"
        assert data["command"] == "echo hello"
        assert len(data["results"]) == 1

    @patch("freq.modules.serve.ssh_run_many")
    @patch("freq.modules.serve.load_config")
    def test_exec_all_targets(self, mock_cfg_fn, mock_ssh):
        hosts = [_mock_host("h1", "10.0.0.1"), _mock_host("h2", "10.0.0.2")]
        mock_cfg_fn.return_value = _mock_cfg(hosts=hosts)
        mock_ssh.return_value = {
            "h1": _mock_ssh_result("ok"),
            "h2": _mock_ssh_result("ok"),
        }

        h = _make_handler("/api/exec?target=all&cmd=uptime")
        h._serve_exec()

        data = _get_json(h)
        assert data["target"] == "all"
        assert len(data["results"]) == 2

    @patch("freq.modules.serve.ssh_run_many")
    @patch("freq.modules.serve.load_config")
    def test_exec_unknown_target(self, mock_cfg_fn, mock_ssh):
        mock_cfg_fn.return_value = _mock_cfg(hosts=[])
        mock_ssh.return_value = {}

        h = _make_handler("/api/exec?target=nosuchhost&cmd=uptime")
        h._serve_exec()

        data = _get_json(h)
        assert "error" in data or len(data.get("results", [])) == 0


# ══════════════════════════════════════════════════════════════════════════
# VM Action Tests
# ══════════════════════════════════════════════════════════════════════════

class TestServeVmPower:
    """Test /api/vm/power endpoint."""

    @patch("freq.modules.serve._pve_cmd", return_value=("OK", True))
    @patch("freq.modules.serve._find_reachable_node", return_value="192.168.10.1")
    @patch("freq.modules.serve._check_vm_permission", return_value=(True, ""))
    @patch("freq.modules.serve.load_config")
    def test_vm_power_start(self, mock_cfg_fn, mock_perm, mock_node, mock_pve):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vm/power?vmid=5001&action=start")
        h._serve_vm_power()

        data = _get_json(h)
        assert data["ok"] is True
        assert data["vmid"] == 5001
        assert data["action"] == "start"

    @patch("freq.modules.serve._check_vm_permission", return_value=(False, "Action 'stop' blocked on VMID 200"))
    @patch("freq.modules.serve.load_config")
    def test_vm_power_blocked(self, mock_cfg_fn, mock_perm):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vm/power?vmid=200&action=stop")
        h._serve_vm_power()

        data = _get_json(h)
        assert "error" in data
        assert "blocked" in data["error"].lower()

    @patch("freq.modules.serve._find_reachable_node", return_value=None)
    @patch("freq.modules.serve._check_vm_permission", return_value=(True, ""))
    @patch("freq.modules.serve.load_config")
    def test_vm_power_no_node(self, mock_cfg_fn, mock_perm, mock_node):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vm/power?vmid=5001&action=start")
        h._serve_vm_power()

        data = _get_json(h)
        assert "error" in data


class TestServeVmCreate:
    """Test /api/vm/create endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_vm_create_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vm/create?name=")
        h._serve_vm_create()

        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_vm_create_invalid_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vm/create?name=bad%20name%21%21")
        h._serve_vm_create()

        data = _get_json(h)
        assert "Invalid VM name" in data.get("error", "")


class TestServeVmDestroy:
    """Test /api/vm/destroy endpoint."""

    @patch("freq.modules.serve.is_protected_vmid", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_vm_destroy_protected(self, mock_cfg_fn, mock_prot):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vm/destroy?vmid=900")
        h._serve_vm_destroy()

        data = _get_json(h)
        assert "PROTECTED" in data.get("error", "").upper() or "error" in data


class TestServeVmSnapshot:
    """Test /api/vm/snapshot endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_snapshot_invalid_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/vm/snapshot?vmid=5001&name=bad%20snap%21")
        h._serve_vm_snapshot()

        data = _get_json(h)
        assert "Invalid snapshot name" in data.get("error", "")


# ══════════════════════════════════════════════════════════════════════════
# Routing Tests
# ══════════════════════════════════════════════════════════════════════════

class TestDoGetRouting:
    """Test do_GET route dispatch."""

    def test_known_route_dispatches(self):
        h = _make_handler("/api/info")
        # Patch _serve_info to just track it was called
        called = []
        h._serve_info = lambda: called.append(True)
        h.do_GET()
        assert called == [True]

    def test_unknown_route_404(self):
        h = _make_handler("/api/nonexistent")
        errors = []
        h.send_error = lambda code, *args, **kwargs: errors.append(code)
        h.do_GET()
        assert 404 in errors

    def test_watchdog_proxy_route(self):
        h = _make_handler("/api/watch/something")
        called = []
        h._proxy_watchdog = lambda: called.append(True)
        h.do_GET()
        assert called == [True]

    def test_comms_proxy_route(self):
        h = _make_handler("/api/comms/test")
        called = []
        h._proxy_watchdog = lambda: called.append(True)
        h.do_GET()
        assert called == [True]

    def test_root_serves_app(self):
        h = _make_handler("/")
        called = []
        h._serve_app = lambda: called.append(True)
        h.do_GET()
        assert called == [True]

    def test_dashboard_serves_app(self):
        h = _make_handler("/dashboard")
        called = []
        h._serve_app = lambda: called.append(True)
        h.do_GET()
        assert called == [True]


# ══════════════════════════════════════════════════════════════════════════
# Lab / Media Endpoints
# ══════════════════════════════════════════════════════════════════════════

class TestServeLabStatus:
    """Test /api/lab/status endpoint."""

    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_lab_status(self, mock_cfg_fn, mock_ssh_single):
        hosts = [_mock_host("lab1", "192.168.10.100", "linux", groups="lab")]
        cfg = _mock_cfg(hosts=hosts, docker_dev_ip="192.168.10.200")
        mock_cfg_fn.return_value = cfg
        mock_ssh_single.return_value = _mock_ssh_result("up 3 days")

        h = _make_handler("/api/lab/status")
        h._serve_lab_status()

        data = _get_json(h)
        assert "hosts" in data
        assert len(data["hosts"]) == 1


class TestServeMediaRestart:
    """Test /api/media/restart endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_restart_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/restart?name=")
        h._serve_media_restart()

        data = _get_json(h)
        assert "error" in data


class TestServeMediaLogs:
    """Test /api/media/logs endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_logs_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/logs?name=")
        h._serve_media_logs()

        data = _get_json(h)
        assert "error" in data


class TestServeMediaUpdate:
    """Test /api/media/update endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_update_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/update?name=")
        h._serve_media_update()

        data = _get_json(h)
        assert "error" in data


# ══════════════════════════════════════════════════════════════════════════
# JSON Response Mechanics
# ══════════════════════════════════════════════════════════════════════════

class TestJsonResponse:
    """Test _json_response method."""

    def test_json_response_writes_body(self):
        h = _make_handler("/test")
        h._json_response({"key": "value"})

        data = _get_json(h)
        assert data == {"key": "value"}
        assert h._status_code == 200

    def test_json_response_sets_headers(self):
        h = _make_handler("/test")
        h._json_response({"x": 1})

        header_dict = dict(h._resp_headers)
        assert header_dict["Content-Type"] == "application/json"
        assert header_dict["Access-Control-Allow-Origin"] == "*"

    def test_json_response_complex_data(self):
        h = _make_handler("/test")
        complex_data = {
            "list": [1, 2, 3],
            "nested": {"a": True, "b": None},
            "str": "hello",
        }
        h._json_response(complex_data)

        data = _get_json(h)
        assert data == complex_data


# ═══════════════════════════════════════════════════════════════════
# SSE Endpoint
# ═══════════════════════════════════════════════════════════════════

class TestSSEEndpoint:
    """Tests for /api/events SSE route."""

    def test_events_route_registered(self):
        """The /api/events route is in the routing table."""
        assert "/api/events" in FreqHandler._ROUTES
        assert FreqHandler._ROUTES["/api/events"] == "_serve_events"

    def test_serve_events_method_exists(self):
        """FreqHandler has a _serve_events method."""
        assert hasattr(FreqHandler, "_serve_events")
        assert callable(getattr(FreqHandler, "_serve_events"))
