"""Tier 5B: serve.py HTTP handler tests with MockFreqHandler.

Tests HTTP endpoints by creating a mock handler that captures JSON responses
without needing real sockets or SSH backends.

NOTE: Auth handler tests (login, verify, change-password), info, status, vault,
users, exec, and VM action tests were removed in the Phase 3.1 refactor.
Those handlers were extracted to freq/api/*.py modules and the old _serve_*
methods were deleted from serve.py.  Auth is now tested in test_security_api.py.
"""
import io
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import patch

# ── Path setup ──────────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.modules.serve import FreqHandler


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
# NOTE: Auth (login/verify/change-password), Info, Status, Vault, Users,
# Exec, and VM action tests were removed.  Those _serve_* handler methods
# were deleted from serve.py during the Phase 3.1 API extraction.
# The functionality is now in freq/api/*.py and tested via
# test_security_api.py, test_admin_api.py, and the API-level test suite.
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# Routing Tests
# ══════════════════════════════════════════════════════════════════════════

class TestDoGetRouting:
    """Test do_GET route dispatch."""

    def test_known_route_dispatches(self):
        h = _make_handler("/api/config")
        # Patch _serve_config to just track it was called
        called = []
        h._serve_config = lambda: called.append(True)
        h.do_GET()
        assert called == [True]

    def test_unknown_route_404(self):
        h = _make_handler("/api/nonexistent")
        h.do_GET()
        # Unknown API routes return JSON 404 via _json_response
        assert h._status_code == 404
        data = _get_json(h)
        assert data["error"] == "not found"

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
        # CORS headers are now origin-aware (only sent when Origin header present)
        assert header_dict.get("X-Content-Type-Options") == "nosniff"
        assert header_dict.get("X-Frame-Options") == "DENY"

    def test_json_response_cors_with_origin(self):
        h = _make_handler("/test")
        h.headers = {"Origin": "http://localhost:3000"}
        h._json_response({"x": 1})

        header_dict = dict(h._resp_headers)
        assert header_dict["Access-Control-Allow-Origin"] == "http://localhost:3000"

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
