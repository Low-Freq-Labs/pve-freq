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
import tempfile
import time
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
    h.command = "GET"
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


def test_static_web_assets_preserve_nested_bytes_mime_and_security_headers():
    """Serve real top-level and nested assets with exact transport truth."""
    from freq.modules.web_ui import read_asset

    cases = (
        ("/static/js/app.js", "js/app.js", "application/javascript; charset=utf-8"),
        ("/static/vendor/xterm/xterm.min.css", "vendor/xterm/xterm.min.css", "text/css; charset=utf-8"),
        (
            "/static/vendor/xterm/xterm.min.js",
            "vendor/xterm/xterm.min.js",
            "application/javascript; charset=utf-8",
        ),
    )
    for route, asset, content_type in cases:
        expected = read_asset(asset).encode("utf-8")
        handler = _make_handler(route)

        handler._serve_static(route)

        headers = dict(handler._resp_headers)
        assert handler._status_code == 200, asset
        assert handler.wfile.getvalue() == expected, asset
        assert headers["Content-Type"] == content_type, asset
        assert headers["Content-Length"] == str(len(expected)), asset
        assert headers["Cache-Control"] == "no-cache, must-revalidate", asset
        assert headers["X-Content-Type-Options"] == "nosniff", asset
        assert headers["Connection"] == "close", asset

    assert b"xterm" in read_asset("vendor/xterm/xterm.min.css").lower().encode("utf-8")
    assert len(read_asset("vendor/xterm/xterm.min.css")) > 500
    assert len(read_asset("vendor/xterm/xterm.min.js")) > 100_000


class BusyLock:
    """Lock stub that simulates a background probe holding the cache lock."""

    def acquire(self, blocking=True):
        return False

    def release(self):
        raise AssertionError("release should not be called when acquire returned False")


class ReadyLock:
    def acquire(self, blocking=True):
        return True

    def release(self):
        return None


def test_metrics_prometheus_returns_when_health_cache_lock_is_busy():
    from freq.api import observe

    h = _make_handler("/api/metrics/prometheus")
    with patch.object(observe, "_bg_lock", BusyLock()):
        observe.handle_metrics_prometheus(h)

    h.wfile.seek(0)
    body = h.wfile.read().decode()
    assert h._status_code == 200
    assert "freq_info" in body
    assert "freq_uptime_seconds" in body
    assert "freq_health_cache_locked 1" in body


def test_metrics_prometheus_counts_health_cache_status_shapes():
    from freq.api import observe

    h = _make_handler("/api/metrics/prometheus")
    health = {
        "hosts": [
            {"label": "a", "state": "live"},
            {"label": "b", "status": "healthy"},
            {"label": "c", "reachable": True},
            {"label": "d", "status": "down"},
        ]
    }
    with patch.object(observe, "_bg_lock", ReadyLock()), patch.object(observe, "_bg_cache", {"health": health}):
        observe.handle_metrics_prometheus(h)

    h.wfile.seek(0)
    body = h.wfile.read().decode()
    assert "freq_hosts_total 4" in body
    assert "freq_hosts_healthy 3" in body
    assert "freq_hosts_unreachable 1" in body


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


def _assert_config_projection_contract():
    """Pin the authenticated config payload before its service extraction."""
    from inspect import getsource

    from freq.modules import serve

    cfg = SimpleNamespace(
        version="2026.7",
        brand="FREQ",
        build="gate-125",
        ssh_service_account="freq-service",
        ssh_connect_timeout=17,
        ssh_max_parallel=9,
        pve_nodes=("pve-a", "pve-b"),
        cluster_name="dc01",
        timezone="America/Chicago",
        truenas_ip="10.25.40.10",
        pfsense_ip="10.25.0.1",
        install_dir="/opt/freq",
        hosts=[object(), object()],
        vlans={10: object()},
        distros=(object(), object(), object()),
        protected_vmids=[100, 101],
    )
    discovered = [{"name": "pve-a"}, {"id": "missing-name"}, {"name": None}]
    expected_base = {
        "version": "2026.7",
        "brand": "FREQ",
        "build": "gate-125",
        "ssh_account": "freq-service",
        "ssh_timeout": 17,
        "ssh_parallel": 9,
        "pve_nodes": ("pve-a", "pve-b"),
        "cluster": "dc01",
        "timezone": "America/Chicago",
        "truenas_ip": "10.25.40.10",
        "pfsense_ip": "10.25.0.1",
        "install_dir": "/opt/freq",
        "hosts_count": 2,
        "vlans_count": 1,
        "distros_count": 3,
        "protected_vmids": [100, 101],
        "pve_nodes_discovered": ["pve-a", "", None],
    }
    default_kill_chain = ["Operator", "VPN", "Firewall", "Switch", "Network", "Target"]

    for loaded_kill_chain, expected_kill_chain in (
        (["Operator", "Gateway", "Target"], ["Operator", "Gateway", "Target"]),
        (None, default_kill_chain),
        ([], default_kill_chain),
    ):
        responses = []
        handler = FreqHandler.__new__(FreqHandler)
        handler._json_response = responses.append
        with (
            patch.object(serve, "load_config", return_value=cfg) as load_config,
            patch.object(serve, "_get_discovered_nodes", return_value=discovered) as get_nodes,
            patch.object(serve, "_load_kill_chain", return_value=loaded_kill_chain) as load_chain,
        ):
            handler._serve_config()

        assert responses == [{**expected_base, "kill_chain": expected_kill_chain}]
        load_config.assert_called_once_with()
        get_nodes.assert_called_once_with()
        load_chain.assert_called_once_with(cfg)

    responses = []
    handler = FreqHandler.__new__(FreqHandler)
    handler._json_response = responses.append
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_get_discovered_nodes", side_effect=OSError("discovery unavailable")),
        patch.object(serve, "_load_kill_chain") as load_chain,
    ):
        try:
            handler._serve_config()
        except OSError as exc:
            assert str(exc) == "discovery unavailable"
        else:
            raise AssertionError("config projection must not hide discovery failure")
    assert responses == []
    load_chain.assert_not_called()

    responses = []
    projected = {"projection": "owned-by-dashboard-state"}
    handler = FreqHandler.__new__(FreqHandler)
    handler._json_response = responses.append
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_get_discovered_nodes", return_value=discovered),
        patch.object(serve, "_load_kill_chain", return_value=["Operator", "Target"]),
        patch.object(
            serve._dashboard_state,
            "build_config_projection",
            return_value=projected,
        ) as build_projection,
    ):
        handler._serve_config()
    assert responses == [projected]
    build_projection.assert_called_once_with(cfg, discovered, ["Operator", "Target"])
    assert getsource(FreqHandler._serve_config).count(
        "_dashboard_state.build_config_projection("
    ) == 1


def _assert_distros_projection_contract():
    """Pin the authenticated distro catalog before its service extraction."""
    from inspect import getsource

    from freq.modules import serve

    configured = (
        SimpleNamespace(
            key="ubuntu-2404",
            name="Ubuntu 24.04",
            family="debian",
            tier="stable",
            url="https://example.invalid/ubuntu-2404.img",
            checksum="must-not-leak",
        ),
        SimpleNamespace(
            key="ubuntu-2404",
            name="Custom duplicate",
            family=None,
            tier=0,
            url=None,
            password="must-not-leak",
        ),
    )
    expected = {
        "distros": [
            {
                "key": "ubuntu-2404",
                "name": "Ubuntu 24.04",
                "family": "debian",
                "tier": "stable",
                "url": "https://example.invalid/ubuntu-2404.img",
            },
            {
                "key": "ubuntu-2404",
                "name": "Custom duplicate",
                "family": None,
                "tier": 0,
                "url": None,
            },
        ],
        "count": 2,
    }

    for distros, projected in ((configured, expected), ([], {"distros": [], "count": 0})):
        responses = []
        handler = FreqHandler.__new__(FreqHandler)
        handler._json_response = responses.append
        with patch.object(
            serve,
            "load_config",
            return_value=SimpleNamespace(distros=distros),
        ) as load_config:
            handler._serve_distros()
        assert responses == [projected]
        load_config.assert_called_once_with()

    responses = []
    handler = FreqHandler.__new__(FreqHandler)
    handler._json_response = responses.append
    incomplete = SimpleNamespace(
        key="incomplete",
        name="Incomplete",
        family="unknown",
        tier="test",
    )
    with patch.object(
        serve,
        "load_config",
        return_value=SimpleNamespace(distros=[incomplete]),
    ):
        try:
            handler._serve_distros()
        except AttributeError as exc:
            assert "url" in str(exc)
        else:
            raise AssertionError("distro projection must not hide an invalid record")
    assert responses == []

    responses = []
    projected = [{"key": "owned-by-dashboard-state"}]
    handler = FreqHandler.__new__(FreqHandler)
    handler._json_response = responses.append
    cfg = SimpleNamespace(distros=configured)
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(
            serve._dashboard_state,
            "build_distro_catalog",
            return_value=projected,
        ) as build_catalog,
    ):
        handler._serve_distros()
    assert responses == [{"distros": projected, "count": 1}]
    build_catalog.assert_called_once_with(configured)
    assert getsource(FreqHandler._serve_distros).count(
        "_dashboard_state.build_distro_catalog("
    ) == 1


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

    def test_authenticated_and_public_routes_dispatch_with_exact_health_truth(self):
        from freq import __version__

        h = _make_handler("/api/config")
        called = []
        h._serve_config = lambda: called.append(True)
        with patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
            h.do_GET()
        assert called == [True]
        _assert_config_projection_contract()

        h = _make_handler("/api/distros")
        called = []
        h._serve_distros = lambda: called.append(True)
        with patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
            h.do_GET()
        assert called == [True]
        _assert_distros_projection_contract()

        for path in ("/", "/dashboard"):
            h = _make_handler(path)
            called = []
            h._serve_app = lambda: called.append(True)
            with patch(
                "freq.modules.serve._check_session_role",
                side_effect=AssertionError("public route must not authenticate"),
            ):
                h.do_GET()
            assert called == [True]

        for first_run in (True, False):
            h = _make_handler("/")
            with patch("freq.modules.serve._is_first_run", return_value=first_run):
                h._serve_app()
            headers = dict(h._resp_headers)
            assert h._status_code == 200
            assert headers["Content-Type"] == "text/html; charset=utf-8"
            assert headers["Cache-Control"] == "no-store, no-cache, must-revalidate"
            assert headers["Pragma"] == "no-cache"
            assert headers["Connection"] == "close"
            assert "default-src 'self'" in headers["Content-Security-Policy"]

        h = _make_handler("/healthz")
        with patch(
            "freq.modules.serve._check_session_role",
            side_effect=AssertionError("public route must not authenticate"),
        ):
            h.do_GET()
        assert h._status_code == 200
        assert _get_json(h) == {"status": "ok", "version": __version__}

    def test_unknown_route_404(self):
        h = _make_handler("/api/nonexistent")
        # Bypass global auth check for routing test (auth tested separately)
        with patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
            h.do_GET()
        # Unknown API routes return JSON 404 via _json_response
        assert h._status_code == 404
        data = _get_json(h)
        assert data["error"] == "not found"

class TestFleetOverviewApi:
    """Test /api/fleet/overview cache metadata."""

    def test_cached_response_includes_age_seconds(self):
        from freq.api.fleet import handle_fleet_overview
        from freq.modules.serve import _bg_cache, _bg_cache_ts, _bg_lock

        h = _make_handler("/api/fleet/overview")
        now = time.time()

        with _bg_lock:
            _bg_cache["fleet_overview"] = {
                "vms": [],
                "vm_nics": {},
                "physical": [],
                "pve_nodes": [],
                "vlans": [],
                "nic_profiles": {},
                "categories": {},
                "summary": {
                    "total_vms": 0,
                    "running": 0,
                    "stopped": 0,
                    "prod_count": 0,
                    "lab_count": 0,
                    "template_count": 0,
                },
                "duration": 0.2,
            }
            _bg_cache_ts["fleet_overview"] = now - 123.4

        handle_fleet_overview(h)
        data = _get_json(h)

        assert data["cached"] is True
        assert isinstance(data["age_seconds"], float)
        assert round(data["age_seconds"], 1) == 123.4
        assert data["age"] == data["age_seconds"]

        with _bg_lock:
            assert "cached" not in _bg_cache["fleet_overview"]
            assert "age_seconds" not in _bg_cache["fleet_overview"]


# ══════════════════════════════════════════════════════════════════════════
# Lab / Media Endpoints
# ══════════════════════════════════════════════════════════════════════════

class TestServeMediaActivity:
    """Test live media activity endpoints."""

    @patch("freq.services.media_activity.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_streams_fallback_reads_tautulli_config_inside_container(self, mock_cfg_fn, mock_ssh_single):
        from freq.core.types import Container, ContainerVM

        vm = ContainerVM(
            vm_id=0,
            ip="10.0.0.31",
            label="arr-stack",
            containers={
                "tautulli": Container(name="tautulli", vm_id=0, port=0, vault_key=""),
            },
        )
        mock_cfg_fn.return_value = _mock_cfg(container_vms={"arr-stack": vm})
        mock_ssh_single.return_value = _mock_ssh_result(json.dumps({
            "response": {
                "data": {
                    "sessions": [
                        {
                            "friendly_name": "sonny",
                            "full_title": "Live Proof",
                            "media_type": "movie",
                            "video_resolution": "1080",
                            "state": "playing",
                        }
                    ]
                }
            }
        }))

        h = _make_handler("/api/media/streams")
        h._serve_media_streams()

        data = _get_json(h)
        assert data["count"] == 1
        assert data["sessions"][0]["title"] == "Live Proof"
        assert data["sources"][0]["source"] == "container-config"
        command = mock_ssh_single.call_args.kwargs["command"]
        assert "docker exec tautulli" in command
        assert "/config/config.ini" in command
        assert "localhost:8181" in command

    @patch("freq.services.media_activity.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_streams_retry_uses_key_owner_when_service_account_denied(self, mock_cfg_fn, mock_ssh_single):
        from freq.core.types import Container, ContainerVM

        vm = ContainerVM(
            vm_id=0,
            ip="10.0.0.31",
            label="arr-stack",
            containers={
                "tautulli": Container(name="tautulli", vm_id=0, port=0, vault_key=""),
            },
        )
        mock_cfg_fn.return_value = _mock_cfg(
            container_vms={"arr-stack": vm},
            ssh_key_path="/home/freq-ops/.ssh/fleet_key",
            ssh_service_account="dc01-admin",
        )
        mock_ssh_single.side_effect = [
            _mock_ssh_result("", "dc01-admin@10.0.0.31: Permission denied (publickey,password).", 255),
            _mock_ssh_result(json.dumps({"response": {"data": {"sessions": []}}})),
        ]

        h = _make_handler("/api/media/streams")
        h._serve_media_streams()

        data = _get_json(h)
        assert data["sources"][0]["source"] == "container-config"
        assert mock_ssh_single.call_count == 2
        assert "user" not in mock_ssh_single.call_args_list[0].kwargs
        assert mock_ssh_single.call_args_list[1].kwargs["user"] == "freq-ops"

    @patch("freq.services.media_activity.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_downloads_fallback_reads_sab_config_inside_container(self, mock_cfg_fn, mock_ssh_single):
        from ast import FunctionDef, Import, ImportFrom, Name, parse, walk
        from copy import deepcopy
        from pathlib import Path

        from freq.core.types import Container, ContainerVM
        from freq.modules.serve import (
            _docker_exec_json,
            _media_container_port,
            _media_default_port,
            _media_ssh_single,
            _media_ssh_user_from_key,
            _parse_qbit_downloads,
            _parse_sab_downloads,
        )
        from freq.services import media_activity

        assert _media_default_port is media_activity.media_default_port
        assert _media_container_port is media_activity.media_container_port
        assert _parse_sab_downloads is media_activity.parse_sab_downloads
        assert _parse_qbit_downloads is media_activity.parse_qbit_downloads
        assert _media_ssh_user_from_key is media_activity.media_ssh_user_from_key
        assert _media_ssh_single is media_activity.media_ssh_single
        assert _docker_exec_json is media_activity.docker_exec_json

        repo_root = Path(__file__).parent.parent
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        service_tree = parse((repo_root / "freq/services/media_activity.py").read_text())
        serve_defs = {
            node.name
            for node in walk(serve_tree)
            if isinstance(node, FunctionDef)
        }
        service_defs = {
            node.name
            for node in walk(service_tree)
            if isinstance(node, FunctionDef)
        }
        assert {
            "_media_default_port",
            "_media_container_port",
            "_parse_sab_downloads",
            "_parse_qbit_downloads",
            "_media_ssh_user_from_key",
            "_media_ssh_single",
            "_docker_exec_json",
        }.isdisjoint(serve_defs)
        assert {
            "media_default_port",
            "media_container_port",
            "parse_sab_downloads",
            "parse_qbit_downloads",
            "media_ssh_user_from_key",
            "media_ssh_single",
            "docker_exec_json",
        } <= service_defs
        assert not any(
            isinstance(node, Name) and node.id == "_MEDIA_DEFAULT_PORTS"
            for node in walk(serve_tree)
        )
        assert any(
            isinstance(node, Name) and node.id == "_MEDIA_DEFAULT_PORTS"
            for node in walk(service_tree)
        )
        service_package = ("freq", "services")
        service_import_roots = set()
        for node in walk(service_tree):
            if isinstance(node, ImportFrom):
                resolved_parts = []
                if node.level:
                    keep = len(service_package) - node.level + 1
                    resolved_parts.extend(service_package[:max(keep, 0)])
                if node.module:
                    resolved_parts.extend(node.module.split("."))
                resolved_base = ".".join(resolved_parts)
                if resolved_base:
                    service_import_roots.add(resolved_base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    service_import_roots.add(
                        ".".join(part for part in (resolved_base, alias.name) if part)
                    )
            elif isinstance(node, Import):
                service_import_roots.update(alias.name for alias in node.names)
        assert not any(
            module == "freq.modules" or module.startswith("freq.modules.")
            for module in service_import_roots
        )

        media_default_port = media_activity.media_default_port
        media_container_port = media_activity.media_container_port
        parse_sab_downloads = media_activity.parse_sab_downloads
        parse_qbit_downloads = media_activity.parse_qbit_downloads

        default_ports = {
            "Tautulli-main": 8181,
            "sabnzbd": 8080,
            "qBittorrent-v5": 8080,
            "qbit-alt": 8080,
            "plex-media-server": 32400,
            "unknown": 0,
            "": 0,
        }
        for name, expected_port in default_ports.items():
            assert media_default_port(name) == expected_port

        assert media_container_port(Container(name="plex", vm_id=0, port=9443)) == 9443
        assert media_container_port(Container(name="plex", vm_id=0, port=0)) == 32400
        assert media_container_port(Container(name="unknown", vm_id=0, port=0)) == 0

        sab_cases = (
            ("1.5 M", 1572864),
            ("2 K", 2048),
            ("0.5 G", 536870912),
            ("7", 7),
        )
        for speed, expected_speed in sab_cases:
            sab_payload = {
                "queue": {
                    "speed": speed,
                    "slots": [
                        {
                            "filename": "release.iso",
                            "percentage": "49.9",
                            "mb": "1.5",
                        }
                    ],
                }
            }
            original = deepcopy(sab_payload)
            assert parse_sab_downloads(sab_payload, "sab-vm") == [
                {
                    "name": "release.iso",
                    "size": 1572864,
                    "progress": 49,
                    "speed": expected_speed,
                    "client": "SABnzbd",
                    "vm": "sab-vm",
                }
            ]
            assert sab_payload == original
        assert parse_sab_downloads([], "sab-vm") == []
        assert parse_sab_downloads({}, "sab-vm") == []

        qbit_payload = [
            {
                "name": "linux.iso",
                "size": 4096,
                "progress": 0.506,
                "dlspeed": 1234,
            },
            {},
        ]
        original_qbit = deepcopy(qbit_payload)
        assert parse_qbit_downloads(qbit_payload, "qbit-vm") == [
            {
                "name": "linux.iso",
                "size": 4096,
                "progress": 51,
                "speed": 1234,
                "client": "qBittorrent",
                "vm": "qbit-vm",
            },
            {
                "name": "?",
                "size": 0,
                "progress": 0,
                "speed": 0,
                "client": "qBittorrent",
                "vm": "qbit-vm",
            },
        ]
        assert qbit_payload == original_qbit
        assert parse_qbit_downloads({}, "qbit-vm") == []
        assert parse_qbit_downloads([], "qbit-vm") == []

        vm = ContainerVM(
            vm_id=0,
            ip="10.0.0.150",
            label="sabnzbd",
            containers={
                "sabnzbd": Container(name="sabnzbd", vm_id=0, port=0, vault_key=""),
            },
        )
        mock_cfg_fn.return_value = _mock_cfg(container_vms={"sabnzbd": vm})
        mock_ssh_single.return_value = _mock_ssh_result(json.dumps({
            "queue": {
                "speed": "2 M",
                "slots": [
                    {"filename": "ubuntu.iso", "percentage": "50", "mb": "100"},
                ],
            }
        }))

        h = _make_handler("/api/media/downloads")
        h._serve_media_downloads()

        data = _get_json(h)
        assert data["count"] == 1
        assert data["downloads"][0]["name"] == "ubuntu.iso"
        assert data["downloads"][0]["speed"] == 2097152
        assert data["sources"][0]["source"] == "container-config"
        command = mock_ssh_single.call_args.kwargs["command"]
        assert "docker exec sabnzbd" in command
        assert "/config/sabnzbd.ini" in command
        assert "localhost:8080" in command

    @patch("freq.services.media_activity.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_downloads_retry_sudo_when_docker_socket_denied(self, mock_cfg_fn, mock_ssh_single):
        from shlex import quote

        from freq.core.types import Container, ContainerVM
        from freq.modules.serve import (
            _docker_exec_json,
            _media_ssh_single,
            _media_ssh_user_from_key,
        )

        vm = ContainerVM(
            vm_id=0,
            ip="10.0.0.150",
            label="sabnzbd",
            containers={
                "sabnzbd": Container(name="sabnzbd", vm_id=0, port=0, vault_key=""),
            },
        )
        assert _media_ssh_user_from_key(_mock_cfg(ssh_key_path="/home/freq-ops/.ssh/fleet_key")) == "freq-ops"
        assert _media_ssh_user_from_key(_mock_cfg(ssh_key_path="/root/.ssh/id_ed25519")) == "root"
        assert _media_ssh_user_from_key(_mock_cfg(ssh_key_path="/tmp/fleet_key")) == ""
        assert _media_ssh_user_from_key(_mock_cfg(ssh_key_path="")) == ""

        direct_cfg = _mock_cfg(
            ssh_key_path="/home/freq-ops/.ssh/fleet_key",
            ssh_service_account="dc01-admin",
        )
        with patch(
            "freq.services.media_activity._resolve_container_vm_ip",
            return_value="10.0.0.250",
        ):
            direct_ok = _mock_ssh_result("ok")
            mock_ssh_single.side_effect = None
            mock_ssh_single.return_value = direct_ok
            assert _media_ssh_single(direct_cfg, vm, "docker ps", timeout=17) is direct_ok
            mock_ssh_single.assert_called_once_with(
                cfg=direct_cfg,
                host="10.0.0.250",
                command="docker ps",
                key_path="/home/freq-ops/.ssh/fleet_key",
                connect_timeout=3,
                command_timeout=17,
                htype="docker",
                use_sudo=False,
            )

            mock_ssh_single.reset_mock()
            permission_denied = _mock_ssh_result(
                "",
                "dc01-admin@10.0.0.250: Permission denied (publickey,password).",
                255,
            )
            key_owner_ok = _mock_ssh_result("key-owner-ok")
            mock_ssh_single.side_effect = [permission_denied, key_owner_ok]
            assert _media_ssh_single(direct_cfg, vm, "docker ps") is key_owner_ok
            assert mock_ssh_single.call_count == 2
            initial_kwargs = mock_ssh_single.call_args_list[0].kwargs
            assert "user" not in initial_kwargs
            assert mock_ssh_single.call_args_list[1].kwargs == {
                **initial_kwargs,
                "user": "freq-ops",
            }

            mock_ssh_single.reset_mock()
            same_owner_cfg = _mock_cfg(
                ssh_key_path="/home/freq-ops/.ssh/fleet_key",
                ssh_service_account="freq-ops",
            )
            mock_ssh_single.side_effect = None
            mock_ssh_single.return_value = permission_denied
            assert _media_ssh_single(same_owner_cfg, vm, "docker ps") is permission_denied
            mock_ssh_single.assert_called_once()
            assert "user" not in mock_ssh_single.call_args.kwargs

            mock_ssh_single.reset_mock()
            lowercase_auth_denied = _mock_ssh_result(
                "",
                "permission denied (publickey,password).",
                255,
            )
            mock_ssh_single.return_value = lowercase_auth_denied
            assert _media_ssh_single(direct_cfg, vm, "docker ps") is lowercase_auth_denied
            mock_ssh_single.assert_called_once()

            mock_ssh_single.reset_mock()
            docker_denied = _mock_ssh_result(
                "",
                "Permission Denied connecting to /var/run/docker.sock",
                1,
            )
            sudo_ok = _mock_ssh_result("sudo-ok")
            mock_ssh_single.side_effect = [permission_denied, docker_denied, sudo_ok]
            assert _media_ssh_single(direct_cfg, vm, "docker ps") is sudo_ok
            assert mock_ssh_single.call_count == 3
            initial_kwargs = mock_ssh_single.call_args_list[0].kwargs
            key_owner_kwargs = {**initial_kwargs, "user": "freq-ops"}
            assert mock_ssh_single.call_args_list[1].kwargs == key_owner_kwargs
            assert mock_ssh_single.call_args_list[2].kwargs == {
                **key_owner_kwargs,
                "use_sudo": True,
            }

        container_name = "sab nzbd;unsafe"
        container_script = "printf '%s' \"$HOME\""
        expected_command = (
            f"docker exec {quote(container_name)} sh -lc {quote(container_script)}"
        )
        with patch("freq.services.media_activity.media_ssh_single") as mock_media_ssh:
            json_result = _mock_ssh_result('{"queue": {"slots": []}}')
            mock_media_ssh.return_value = json_result
            parsed, result = _docker_exec_json(
                direct_cfg,
                vm,
                container_name,
                container_script,
                timeout=19,
            )
            assert parsed == {"queue": {"slots": []}}
            assert result is json_result
            mock_media_ssh.assert_called_once_with(
                direct_cfg,
                vm,
                expected_command,
                timeout=19,
            )

            invalid_json = _mock_ssh_result("not-json")
            mock_media_ssh.return_value = invalid_json
            assert _docker_exec_json(direct_cfg, vm, "sab", "true") == (None, invalid_json)

            empty_stdout = _mock_ssh_result(None)
            mock_media_ssh.return_value = empty_stdout
            assert _docker_exec_json(direct_cfg, vm, "sab", "true") == (None, empty_stdout)

            command_failed = _mock_ssh_result("{}", "failed", 9)
            mock_media_ssh.return_value = command_failed
            assert _docker_exec_json(direct_cfg, vm, "sab", "true") == (None, command_failed)

        mock_ssh_single.reset_mock()
        mock_cfg_fn.return_value = _mock_cfg(container_vms={"sabnzbd": vm})
        mock_ssh_single.side_effect = [
            _mock_ssh_result("", "permission denied while trying to connect to the docker API at unix:///var/run/docker.sock", 1),
            _mock_ssh_result(json.dumps({"queue": {"speed": "0", "slots": []}})),
        ]

        h = _make_handler("/api/media/downloads")
        h._serve_media_downloads()

        data = _get_json(h)
        assert data["sources"][0]["source"] == "container-config"
        assert mock_ssh_single.call_count == 2
        initial_kwargs = mock_ssh_single.call_args_list[0].kwargs
        assert initial_kwargs["use_sudo"] is False
        assert mock_ssh_single.call_args_list[1].kwargs == {
            **initial_kwargs,
            "use_sudo": True,
        }
        assert "user" not in mock_ssh_single.call_args_list[1].kwargs


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

    @patch("freq.modules.serve._check_session_role", return_value=("operator", ""))
    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_restart_returns_structured_failure(self, mock_cfg_fn, mock_ssh_single, _role):
        from freq.core.types import Container, ContainerVM

        vm = ContainerVM(vm_id=0, ip="10.0.0.30", label="plex", containers={
            "plex": Container(name="plex", vm_id=0),
        })
        mock_cfg_fn.return_value = _mock_cfg(container_vms={"plex": vm})
        mock_ssh_single.return_value = _mock_ssh_result("", "permission denied", 255)

        h = _make_handler("/api/media/restart?name=plex")
        h.command = "POST"
        h._serve_media_restart()

        data = _get_json(h)
        assert data["ok"] is False
        assert data["returncode"] == 255
        assert "permission denied" in data["error"]


class TestServeMediaLogs:
    """Test /api/media/logs endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_logs_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/logs?name=")
        h._serve_media_logs()

        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_logs_returns_structured_failure(self, mock_cfg_fn, mock_ssh_single):
        from freq.core.types import Container, ContainerVM

        vm = ContainerVM(vm_id=0, ip="10.0.0.30", label="plex", containers={
            "plex": Container(name="plex", vm_id=0),
        })
        mock_cfg_fn.return_value = _mock_cfg(container_vms={"plex": vm})
        mock_ssh_single.return_value = _mock_ssh_result("", "docker unavailable", 1)

        h = _make_handler("/api/media/logs?name=plex")
        h._serve_media_logs()

        data = _get_json(h)
        assert data["ok"] is False
        assert data["returncode"] == 1
        assert data["logs"] == ""
        assert "docker unavailable" in data["error"]


class TestServeContainerActions:
    """Test Docker host-detail container endpoints."""

    @patch("freq.modules.serve._check_session_role", return_value=("operator", ""))
    @patch("freq.services.container_action.ssh_single")
    @patch("freq.modules.serve.load_config")
    @patch("freq.core.config.load_config")
    def test_container_action_resolves_container_vm_label(
        self,
        mock_core_cfg_fn,
        mock_cfg_fn,
        mock_ssh_single,
        _role,
    ):
        from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
        from pathlib import Path
        from unittest.mock import call

        from freq.core import resolve
        from freq.core.types import ContainerVM, Host
        from freq.modules.serve import _container_vm_host
        from freq.services import container_action

        def attribute_path(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, Attribute):
                parent = attribute_path(node.value)
                return f"{parent}.{node.attr}" if parent else node.attr
            return ""

        assert _container_vm_host is resolve.container_vm_host
        repo_root = Path(__file__).parent.parent
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        resolve_tree = parse((repo_root / "freq/core/resolve.py").read_text())
        service_tree = parse((repo_root / "freq/services/container_action.py").read_text())
        assert "_container_vm_host" not in {
            node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
        }
        assert "container_vm_host" in {
            node.name for node in walk(resolve_tree) if isinstance(node, FunctionDef)
        }
        resolve_package = ("freq", "core")
        resolve_imports = set()
        for node in walk(resolve_tree):
            if isinstance(node, Import):
                resolve_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom):
                resolved_parts = []
                if node.level:
                    keep = len(resolve_package) - node.level + 1
                    resolved_parts.extend(resolve_package[:max(keep, 0)])
                if node.module:
                    resolved_parts.extend(node.module.split("."))
                resolved_base = ".".join(resolved_parts)
                if resolved_base:
                    resolve_imports.add(resolved_base)
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    resolve_imports.add(
                        ".".join(
                            part for part in (resolved_base, alias.name) if part
                        )
                    )
        assert not any(
            module == "freq.modules" or module.startswith("freq.modules.")
            for module in resolve_imports
        )
        service_imports = set()
        for node in walk(service_tree):
            if isinstance(node, Import):
                service_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                service_imports.add(node.module)
        assert service_imports == {"re", "shlex", "freq.core", "freq.core.ssh"}
        assert container_action.resolve.container_vm_host is resolve.container_vm_host
        assert "run_container_action" in {
            node.name for node in walk(service_tree) if isinstance(node, FunctionDef)
        }

        action_handler = next(
            node
            for node in walk(serve_tree)
            if isinstance(node, FunctionDef) and node.name == "_serve_container_action"
        )
        assert len(action_handler.body) == 11
        handler_calls = {
            attribute_path(node.func) for node in walk(action_handler) if isinstance(node, Call)
        }
        assert "_container_action.run_container_action" in handler_calls
        assert "ssh_single" not in handler_calls
        assert "_container_vm_host" not in handler_calls

        decoy_vm = ContainerVM(vm_id=116, ip="10.0.0.20", label="Decoy VM")
        matrix_vm = ContainerVM(vm_id=217, ip="10.0.0.30", label="Plex VM")
        zero_vm = ContainerVM(vm_id=0, ip="10.0.0.40", label="Zero VM")
        static_host = Host(
            ip="192.0.2.10",
            label="Plex VM",
            htype="linux",
            groups="static",
        )
        precedence_cfg = _mock_cfg(
            hosts=[static_host],
            container_vms={"plex": matrix_vm},
        )
        assert _container_vm_host(precedence_cfg, "PLEX VM") is static_host
        assert _container_vm_host(precedence_cfg, "192.0.2.10") is static_host

        container_cfg = _mock_cfg(
            hosts=[],
            container_vms={"decoy": decoy_vm, "plex": matrix_vm, "zero": zero_vm},
        )
        with patch(
            "freq.core.resolve._resolve_container_vm_ip",
            return_value="10.0.0.99",
        ) as resolve_ip:
            for target in (" Plex VM ", "PLEX VM", "10.0.0.30", "217", "vm:217"):
                assert _container_vm_host(container_cfg, target) == Host(
                    ip="10.0.0.99",
                    label="Plex VM",
                    htype="docker",
                    groups="docker",
                    vmid=217,
                )
            assert resolve_ip.call_args_list == [call(matrix_vm)] * 5
            assert _container_vm_host(container_cfg, "0") is None
            assert _container_vm_host(container_cfg, "vm:0") is None
            assert _container_vm_host(container_cfg, "missing") is None
            assert resolve_ip.call_count == 5

        cfg = _mock_cfg(
            hosts=[],
            container_vms={"plex": ContainerVM(vm_id=0, ip="10.0.0.30", label="plex")},
        )
        mock_cfg_fn.return_value = cfg
        mock_core_cfg_fn.return_value = cfg
        mock_ssh_single.return_value = _mock_ssh_result("plex", "", 0)

        h = _make_handler("/api/containers/action?host=plex&name=plex&action=restart")
        h.command = "POST"
        h._serve_container_action()

        data = _get_json(h)
        assert data == {
            "ok": True,
            "output": "plex",
            "error": "",
            "returncode": 0,
            "action": "restart",
            "container": "plex",
            "host": "plex",
            "resolved_host": "plex",
            "ip": "10.0.0.30",
            "request_id": "",
        }
        assert data["ok"] is True
        ssh_kwargs = mock_ssh_single.call_args.kwargs
        assert ssh_kwargs == {
            "host": "10.0.0.30",
            "command": "docker restart plex 2>&1",
            "key_path": "/tmp/fake_key",
            "connect_timeout": 5,
            "command_timeout": 30,
            "htype": "docker",
            "use_sudo": False,
            "cfg": cfg,
        }
        assert ssh_kwargs["cfg"] is cfg

        mock_cfg_fn.reset_mock()
        mock_ssh_single.reset_mock()
        _role.reset_mock()

        h = _make_handler("/api/containers/action?host=plex&name=plex")
        h._serve_container_action()
        assert h._status_code == 405
        assert _get_json(h) == {"error": "Container action requires POST", "request_id": ""}
        _role.assert_not_called()
        mock_cfg_fn.assert_not_called()
        mock_ssh_single.assert_not_called()

        _role.return_value = ("viewer", "operator role required")
        h = _make_handler("/api/containers/action?host=plex&name=plex")
        h.command = "POST"
        h._serve_container_action()
        assert h._status_code == 403
        assert _get_json(h) == {"error": "operator role required", "request_id": ""}
        mock_cfg_fn.assert_not_called()
        mock_ssh_single.assert_not_called()

        _role.return_value = ("operator", "")
        mock_cfg_fn.return_value = cfg
        invalid_cases = (
            (
                "/api/containers/action?name=plex",
                {"error": "host and name required", "request_id": ""},
            ),
            (
                "/api/containers/action?host=plex&name=plex&action=remove",
                {"error": "action must be restart, stop, or start", "request_id": ""},
            ),
            (
                "/api/containers/action?host=plex&name=bad%20name&action=start",
                {"error": "Invalid container name", "request_id": ""},
            ),
        )
        for path, expected in invalid_cases:
            h = _make_handler(path)
            h.command = "POST"
            h._serve_container_action()
            assert h._status_code == 400
            assert _get_json(h) == expected
        mock_ssh_single.assert_not_called()

        missing_cfg = _mock_cfg(hosts=[], container_vms={})
        mock_cfg_fn.return_value = missing_cfg
        h = _make_handler("/api/containers/action?host=missing&name=plex&action=stop")
        h.command = "POST"
        h._serve_container_action()
        assert h._status_code == 404
        assert _get_json(h) == {"error": "Host not found: missing", "request_id": ""}
        mock_ssh_single.assert_not_called()

        mock_cfg_fn.return_value = cfg
        mock_ssh_single.return_value = _mock_ssh_result("stale output", "runtime unavailable", 23)
        h = _make_handler("/api/containers/action?host=plex&name=plex&action=stop")
        h.command = "POST"
        h._serve_container_action()
        failed_data = _get_json(h)
        assert failed_data == {
            "ok": False,
            "output": "stale output",
            "error": "runtime unavailable",
            "returncode": 23,
            "action": "stop",
            "container": "plex",
            "host": "plex",
            "resolved_host": "plex",
            "ip": "10.0.0.30",
            "request_id": "",
        }
        assert failed_data["ok"] is False
        failed_kwargs = mock_ssh_single.call_args.kwargs
        assert failed_kwargs == {
            **ssh_kwargs,
            "command": "docker stop plex 2>&1",
        }
        assert failed_kwargs["cfg"] is cfg

    @patch("freq.services.container_logs.resolve.container_vm_host")
    @patch("freq.services.container_logs.ssh_single")
    @patch("freq.modules.serve.load_config")
    def test_container_logs_resolves_container_vm_label_and_reports_failure(
        self,
        mock_cfg_fn,
        mock_ssh_single,
        mock_container_vm_host,
    ):
        from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
        from pathlib import Path

        from freq.services import container_logs

        def attribute_path(node):
            if isinstance(node, Name):
                return node.id
            if isinstance(node, Attribute):
                parent = attribute_path(node.value)
                return f"{parent}.{node.attr}" if parent else node.attr
            return ""

        repo_root = Path(__file__).parent.parent
        serve_tree = parse((repo_root / "freq/modules/serve.py").read_text())
        service_tree = parse((repo_root / "freq/services/container_logs.py").read_text())
        service_imports = set()
        for node in walk(service_tree):
            if isinstance(node, Import):
                service_imports.update(alias.name for alias in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                service_imports.add(node.module)
        assert service_imports == {"re", "shlex", "freq.core", "freq.core.ssh"}
        assert "read_container_logs" in {
            node.name for node in walk(service_tree) if isinstance(node, FunctionDef)
        }
        logs_handler = next(
            node
            for node in walk(serve_tree)
            if isinstance(node, FunctionDef) and node.name == "_serve_container_logs"
        )
        assert len(logs_handler.body) == 5
        handler_calls = {
            attribute_path(node.func) for node in walk(logs_handler) if isinstance(node, Call)
        }
        assert "_container_logs.read_container_logs" in handler_calls
        assert "ssh_single" not in handler_calls
        assert "_container_vm_host" not in handler_calls
        assert container_logs.resolve.container_vm_host is mock_container_vm_host

        cfg = _mock_cfg(hosts=[], container_vms={})
        resolved_host = _mock_host(label="Plex VM", ip="10.0.0.30", htype="")
        mock_cfg_fn.return_value = cfg
        mock_container_vm_host.return_value = resolved_host
        mock_ssh_single.return_value = _mock_ssh_result("line one\n", "", 0)

        h = _make_handler("/api/containers/logs?host=plex-vm&name=plex.v2&lines=350")
        h._serve_container_logs()

        data = _get_json(h)
        assert data == {
            "ok": True,
            "output": "line one\n",
            "error": "",
            "returncode": 0,
            "container": "plex.v2",
            "host": "plex-vm",
            "resolved_host": "Plex VM",
            "ip": "10.0.0.30",
            "lines": 200,
            "request_id": "",
        }
        assert data["ok"] is True
        mock_container_vm_host.assert_called_once_with(cfg, "plex-vm")
        ssh_kwargs = mock_ssh_single.call_args.kwargs
        assert ssh_kwargs == {
            "host": "10.0.0.30",
            "command": "docker logs --tail 200 plex.v2 2>&1",
            "key_path": "/tmp/fake_key",
            "connect_timeout": 5,
            "command_timeout": 15,
            "htype": "docker",
            "use_sudo": False,
            "cfg": cfg,
        }
        assert ssh_kwargs["cfg"] is cfg

        mock_container_vm_host.reset_mock()
        mock_ssh_single.reset_mock()
        invalid_cases = (
            (
                "/api/containers/logs?name=plex",
                {"error": "host and name required", "request_id": ""},
            ),
            (
                "/api/containers/logs?host=plex-vm&name=bad%20name",
                {"error": "Invalid container name", "request_id": ""},
            ),
        )
        for path, expected in invalid_cases:
            h = _make_handler(path)
            h._serve_container_logs()
            assert h._status_code == 400
            assert _get_json(h) == expected
        mock_container_vm_host.assert_not_called()
        mock_ssh_single.assert_not_called()

        mock_container_vm_host.return_value = None
        h = _make_handler("/api/containers/logs?host=missing&name=plex")
        h._serve_container_logs()
        assert h._status_code == 404
        assert _get_json(h) == {"error": "Host not found: missing", "request_id": ""}
        mock_ssh_single.assert_not_called()

        mock_container_vm_host.return_value = resolved_host
        mock_ssh_single.return_value = _mock_ssh_result(
            "stale output",
            " no such container \n",
            23,
        )
        h = _make_handler("/api/containers/logs?host=plex-vm&name=plex.v2")
        h._serve_container_logs()
        failed_data = _get_json(h)
        assert failed_data == {
            "ok": False,
            "output": "",
            "error": "no such container",
            "returncode": 23,
            "container": "plex.v2",
            "host": "plex-vm",
            "resolved_host": "Plex VM",
            "ip": "10.0.0.30",
            "lines": 50,
            "request_id": "",
        }
        assert failed_data["ok"] is False
        failed_kwargs = mock_ssh_single.call_args.kwargs
        assert failed_kwargs == {
            **ssh_kwargs,
            "command": "docker logs --tail 50 plex.v2 2>&1",
        }
        assert failed_kwargs["cfg"] is cfg


class TestServeMediaUpdate:
    """Test /api/media/update endpoint."""

    @patch("freq.modules.serve.load_config")
    def test_update_missing_name(self, mock_cfg_fn):
        mock_cfg_fn.return_value = _mock_cfg()

        h = _make_handler("/api/media/update?name=")
        h._serve_media_update()

        data = _get_json(h)
        assert "error" in data


class TestSetupHandlers:
    """Trust-critical setup handler behavior."""

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_rejects_invalid_timezone(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "Mars/Phobos", "pve_nodes": ["10.0.0.1"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert "Invalid timezone" in data["error"]

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    @patch("zoneinfo.ZoneInfo", side_effect=RuntimeError("tzdata unavailable"))
    def test_setup_configure_accepts_utc_without_tzdata(self, mock_zoneinfo, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {
            "cluster_name": "dc01",
            "timezone": "UTC",
            "pve_nodes": ["bad-ip"],
        }

        h._serve_setup_configure()

        assert h._status_code == 400
        assert "Invalid PVE node IP" in _get_json(h)["error"]
        mock_zoneinfo.assert_not_called()

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_rejects_invalid_pve_nodes(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "UTC", "pve_nodes": ["bad-ip", "10.0.0.2"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert "Invalid PVE node IP" in data["error"]

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_requires_cluster_name(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "", "timezone": "UTC", "pve_nodes": ["10.0.0.1"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "cluster_name is required"

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_requires_pve_nodes(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "UTC", "pve_nodes": []}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "At least one PVE node IP is required"

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_rejects_duplicate_pve_nodes(self, mock_cfg_fn, _mock_first_run):
        cfg = _mock_cfg(conf_dir="/tmp/freq-test-conf")
        mock_cfg_fn.return_value = cfg

        h = _make_handler("/api/setup/configure")
        h.command = "POST"
        h._request_body = lambda: {"cluster_name": "dc01", "timezone": "UTC", "pve_nodes": ["10.0.0.1", "10.0.0.1"]}

        h._serve_setup_configure()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "Duplicate PVE node IPs are not allowed"

    @patch("freq.modules.serve._is_first_run", return_value=True)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_writes_default_node_names(self, mock_cfg_fn, _mock_first_run):
        with tempfile.TemporaryDirectory() as td:
            cfg = _mock_cfg(conf_dir=td)
            mock_cfg_fn.return_value = cfg

            h = _make_handler("/api/setup/configure")
            h.command = "POST"
            h._request_body = lambda: {
                "cluster_name": "dc01",
                "timezone": "",
                "pve_nodes": ["10.0.0.1", "10.0.0.2"],
            }

            h._serve_setup_configure()

            assert h._status_code == 200
            data = _get_json(h)
            assert data["timezone"] == "UTC"
            assert data["pve_node_names"] == ["pve01", "pve02"]
            with open(os.path.join(td, "freq.toml")) as f:
                content = f.read()
            assert 'timezone = "UTC"' in content
            assert 'node_names = ["pve01", "pve02"]' in content

    @patch("freq.api.auth.check_session_role", return_value=("admin", None))
    @patch("freq.modules.serve._is_first_run", return_value=False)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_continues_after_admin_creation_with_admin_session(
        self, mock_cfg_fn, _mock_first_run, _mock_role
    ):
        with tempfile.TemporaryDirectory() as td:
            cfg = _mock_cfg(conf_dir=td, data_dir=os.path.join(td, "data"))
            mock_cfg_fn.return_value = cfg

            h = _make_handler("/api/setup/configure")
            h.command = "POST"
            h._request_body = lambda: {
                "cluster_name": "dc01",
                "timezone": "UTC",
                "pve_nodes": ["10.0.0.1"],
            }

            h._serve_setup_configure()

            assert h._status_code == 200
            data = _get_json(h)
            assert data["cluster_name"] == "dc01"

    @patch("freq.api.auth.check_session_role", return_value=(None, "Authentication required"))
    @patch("freq.modules.serve._is_first_run", return_value=False)
    @patch("freq.modules.serve.load_config")
    def test_setup_configure_after_admin_creation_requires_admin_session(
        self, mock_cfg_fn, _mock_first_run, _mock_role
    ):
        with tempfile.TemporaryDirectory() as td:
            cfg = _mock_cfg(conf_dir=td, data_dir=os.path.join(td, "data"))
            mock_cfg_fn.return_value = cfg

            h = _make_handler("/api/setup/configure")
            h.command = "POST"
            h._request_body = lambda: {
                "cluster_name": "dc01",
                "timezone": "UTC",
                "pve_nodes": ["10.0.0.1"],
            }

            h._serve_setup_configure()

            assert h._status_code == 403
            assert _get_json(h)["error"] == "Authentication required"

    @patch("freq.modules.serve._check_session_role", return_value=("admin", None))
    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_setup_test_ssh_requires_host(self, _mock_first_run, _mock_role):
        h = _make_handler("/api/setup/test-ssh")
        h._serve_setup_test_ssh()

        assert h._status_code == 400
        data = _get_json(h)
        assert data["error"] == "host parameter required"

    @patch("freq.modules.serve._check_session_role", return_value=("admin", None))
    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_setup_test_ssh_rejects_invalid_host(self, _mock_first_run, _mock_role):
        h = _make_handler("/api/setup/test-ssh?host=bad host")
        h._serve_setup_test_ssh()

        assert h._status_code == 400
        data = _get_json(h)
        assert "Invalid host" in data["error"]

    @patch("freq.modules.serve.ssh_single")
    @patch("freq.modules.serve.load_config")
    @patch("freq.modules.serve._check_session_role", return_value=("admin", None))
    @patch("freq.modules.serve._is_first_run", return_value=True)
    def test_setup_test_ssh_returns_502_on_connection_failure(self, _mock_first_run, _mock_role, mock_cfg_fn, mock_ssh_single):
        mock_cfg_fn.return_value = _mock_cfg(
            ssh_connect_timeout=5,
            ssh_service_account="freq-admin",
            pve_nodes=["10.0.0.1"],
        )
        mock_ssh_single.return_value = _mock_ssh_result("", "Permission denied", 255)

        h = _make_handler("/api/setup/test-ssh?host=10.0.0.1")
        h._serve_setup_test_ssh()

        assert h._status_code == 502
        data = _get_json(h)
        assert data["ok"] is False
        assert data["error"] == "Permission denied"


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
        assert header_dict["Cache-Control"] == "no-store, no-cache, must-revalidate"
        assert header_dict["Pragma"] == "no-cache"
        assert header_dict["X-Content-Type-Options"] == "nosniff"
        assert header_dict["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in header_dict["Content-Security-Policy"]
        assert "Access-Control-Allow-Origin" not in header_dict

    def test_json_response_cors_with_origin(self):
        h = _make_handler("/test")
        h.headers = {"Origin": "http://localhost:3000"}
        h._json_response({"x": 1})

        header_dict = dict(h._resp_headers)
        assert "Access-Control-Allow-Origin" not in header_dict

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

    def test_serve_events_emits_runtime_headers_and_unsubscribes(self):
        """The SSE handler emits its runtime headers and cleans up on disconnect."""
        class DisconnectQueue:
            def get(self, timeout):
                raise OSError("bounded client disconnect")

        h = _make_handler("/api/events")
        queue = DisconnectQueue()
        with patch("freq.modules.serve._check_session_role", return_value=("viewer", None)), \
             patch("freq.modules.serve._sse_subscribe", return_value=queue), \
             patch("freq.modules.serve._sse_unsubscribe") as unsubscribe:
            h._serve_events()

        headers = dict(h._resp_headers)
        assert h._status_code == 200
        assert headers["Content-Type"] == "text/event-stream"
        assert headers["Cache-Control"] == "no-cache"
        assert headers["Connection"] == "keep-alive"
        assert headers["X-Accel-Buffering"] == "no"
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert h.wfile.getvalue() == b": connected\n\n"
        unsubscribe.assert_called_once_with(queue)

    def test_events_query_token_gets_truthful_403(self):
        """SSE query-token callers get the migration reason, not generic auth required."""
        h = _make_handler("/api/events?token=deadbeef")
        h.do_GET()
        assert h._status_code == 403
        data = _get_json(h)
        assert "Query-string auth" in data["error"]


# ═══════════════════════════════════════════════════════════════════
# OpenAPI / API Docs Truthfulness
# ═══════════════════════════════════════════════════════════════════

class TestOpenAPITruthfulness:
    """Verify the OpenAPI spec reflects the real API surface."""

    def _get_spec(self):
        """Generate and return the OpenAPI spec as dict."""
        h = _make_handler("/api/openapi.json")
        h._serve_openapi_json()
        return _get_json(h)

    def test_spec_is_valid_openapi(self):
        spec = self._get_spec()
        assert spec["openapi"] == "3.0.3"
        assert "info" in spec
        assert "paths" in spec
        assert spec["info"]["title"] == "PVE FREQ API"

    def test_every_legacy_route_in_spec(self):
        """Every route in _ROUTES appears in the spec (except /, /dashboard, /api/docs, /api/openapi.json)."""
        spec = self._get_spec()
        skip = {"/", "/dashboard", "/api/docs", "/api/openapi.json"}
        for path in FreqHandler._ROUTES:
            if path in skip:
                continue
            assert path in spec["paths"], f"Legacy route {path} missing from OpenAPI spec"

    def test_domain_routes_in_spec(self):
        """Domain routes appear in the spec from the runtime registry."""
        from freq.api import build_routes

        spec = self._get_spec()
        for path in build_routes():
            assert path in spec["paths"], f"Domain route {path} missing from OpenAPI spec"

    def test_post_endpoints_documented_as_post(self):
        """Routes with mutating names should be documented as POST, not GET."""
        spec = self._get_spec()
        post_keywords = ("create", "update", "delete", "reset", "login",
                         "change", "complete", "generate", "deploy", "rollback")
        # Read-only endpoints that have keyword matches but are genuinely GET
        get_overrides = {"/api/fleet/updates", "/api/redfish/power-usage"}
        for path, methods in spec["paths"].items():
            if path in get_overrides:
                continue
            path_tail = path.rsplit("/", 1)[-1]
            if any(kw in path_tail for kw in post_keywords):
                assert "post" in methods, f"{path} should be POST but is {list(methods.keys())}"

    def test_post_endpoints_document_error_responses(self):
        """POST endpoints should document 400 and 403 responses."""
        spec = self._get_spec()
        for path, methods in spec["paths"].items():
            if "post" in methods:
                responses = methods["post"]["responses"]
                assert "400" in responses, f"POST {path} missing 400 response"
                assert "403" in responses, f"POST {path} missing 403 response"

    def test_auth_logout_documented_as_post(self):
        """Logout must appear as POST in the spec."""
        spec = self._get_spec()
        assert "/api/auth/logout" in spec["paths"]
        assert "post" in spec["paths"]["/api/auth/logout"]

    def test_spec_has_security_schemes(self):
        """OpenAPI spec must document bearer and cookie auth."""
        spec = self._get_spec()
        schemes = spec.get("components", {}).get("securitySchemes", {})
        assert "bearerAuth" in schemes, "Spec must document bearerAuth"
        assert "cookieAuth" in schemes, "Spec must document cookieAuth"
        assert schemes["cookieAuth"]["name"] == "freq_session"

    def test_no_internal_method_names_in_summaries(self):
        """Spec summaries must not contain _serve_ method names."""
        spec = self._get_spec()
        for path, methods in spec["paths"].items():
            for method, detail in methods.items():
                summary = detail.get("summary", "")
                assert not summary.startswith("_serve_"), \
                    f"{path} leaks internal method name: {summary}"

    def test_no_url_token_in_spec(self):
        """Spec must not document ?token= query parameter auth."""
        import json
        spec = self._get_spec()
        spec_str = json.dumps(spec)
        assert "?token=" not in spec_str, "Spec must not reference ?token= auth"
        assert "X-Session" not in spec_str, "Spec must not reference X-Session header"

    def test_every_endpoint_has_summary(self):
        """Every endpoint in spec has a non-empty summary."""
        spec = self._get_spec()
        missing = []
        for path, methods in spec["paths"].items():
            for method, detail in methods.items():
                summary = detail.get("summary", "")
                if not summary or summary.startswith("_serve_"):
                    missing.append(f"{method.upper()} {path}")
        # Allow some missing — v1 callables without docs are ok for now
        # but legacy _serve_ method names leaking through is a bug
        serve_leaks = [m for m in missing if "_serve_" in m]
        assert not serve_leaks, f"Internal method names leaked into spec: {serve_leaks}"

    def test_spec_route_count_matches_real_routes(self):
        """OpenAPI spec must include all registered routes (no silent omissions)."""
        from freq.api import build_routes
        from freq.modules.serve import FreqHandler

        real_routes = dict(FreqHandler._ROUTES)
        real_routes.update(build_routes())

        skip = {"/", "/dashboard", "/api/docs", "/api/openapi.json"}
        real_api = {k for k in real_routes if k not in skip}

        spec = self._get_spec()
        spec_routes = set(spec["paths"].keys())
        # Proxy routes use {path} template, skip them for exact match
        spec_routes_clean = {r for r in spec_routes if "{path}" not in r}

        # Every real route should appear in the spec
        missing = real_api - spec_routes_clean
        assert len(missing) <= 2, (
            f"OpenAPI spec missing {len(missing)} routes: "
            f"{sorted(list(missing))[:10]}"
        )

    def test_no_error_responses_return_200(self):
        """Verify no _json_response({{error:...}}) call defaults to 200.

        Checks both single-line and multi-line patterns in serve.py.
        """
        import re
        serve_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "serve.py")
        with open(serve_path) as f:
            content = f.read()
            lines = content.splitlines(True)

        bad_lines = []
        # Single-line check
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if '_json_response({"error"' in stripped and stripped.endswith("})"):
                if not re.search(r'},\s*\d+\)$', stripped):
                    bad_lines.append(i)

        # Multi-line check: _json_response(\n...{"error": <only field>...}\n)
        # Skip mixed payloads (data + error field) — those are partial-success
        for m in re.finditer(
            r'_json_response\(\s*\n\s*(\{[^)]*"error"[^)]*\})\s*\n\s*\)',
            content,
        ):
            lineno = content[:m.start()].count('\n') + 1
            payload = m.group(1)
            # Count top-level keys — if "error" is the only key (or with simple
            # metadata), it's an error-only response. Mixed payloads have 3+ keys.
            key_count = len(re.findall(r'"[a-z_]+":', payload))
            if key_count <= 2:  # error + at most one metadata key
                match_text = m.group()
                if not re.search(r'},\s*\d+\s*\n\s*\)', match_text):
                    bad_lines.append(lineno)

        assert not bad_lines, f"Lines returning error with implicit 200: {bad_lines}"

    def test_no_v1_api_error_responses_return_200(self):
        """Verify no v1 API json_response(handler, {{error:...}}) defaults to 200.

        Source-level guard across all freq/api/*.py files.
        """
        import glob
        import re
        api_dir = os.path.join(os.path.dirname(__file__), "..", "freq", "api")
        bad = []
        for fpath in sorted(glob.glob(os.path.join(api_dir, "*.py"))):
            fname = os.path.basename(fpath)
            with open(fpath) as f:
                for i, line in enumerate(f, 1):
                    stripped = line.strip()
                    if 'json_response(handler, {"error"' in stripped and stripped.endswith("})"):
                        if not re.search(r'},\s*\d+\)$', stripped):
                            bad.append(f"{fname}:{i}")
        assert not bad, f"v1 API lines returning error with implicit 200: {bad}"


class TestAPIDocsPage:
    """Verify the /api/docs HTML page is truthful."""

    def test_docs_page_renders(self):
        h = _make_handler("/api/docs")
        h._serve_api_docs()
        assert h._status_code == 200
        body = h.wfile.getvalue().decode()
        assert "PVE FREQ" in body
        assert "<table>" in body

    def test_docs_page_includes_routes(self):
        h = _make_handler("/api/docs")
        h._serve_api_docs()
        body = h.wfile.getvalue().decode()
        # Should contain real API paths
        assert "/api/auth/login" in body
        assert "/healthz" in body


# ═══════════════════════════════════════════════════════════════════
# Auth Whitelist Correctness
# ═══════════════════════════════════════════════════════════════════

class TestAuthWhitelist:
    """Verify auth whitelist covers required public endpoints."""

    def test_setup_endpoints_whitelisted_for_first_run(self):
        """Only status and first-operator creation are public."""
        for route in ["/api/setup/status", "/api/setup/create-admin"]:
            assert route in FreqHandler._AUTH_WHITELIST, \
                f"Setup route {route} missing from auth whitelist — first-run will 403"

        for route in [
            "/api/setup/configure",
            "/api/setup/generate-key",
            "/api/setup/complete",
            "/api/setup/test-ssh",
            "/api/setup/init/start",
        ]:
            assert route not in FreqHandler._AUTH_WHITELIST

    def test_auth_endpoints_whitelisted(self):
        """Auth login and verify must be public."""
        assert "/api/auth/login" in FreqHandler._AUTH_WHITELIST
        assert "/api/auth/verify" in FreqHandler._AUTH_WHITELIST

    def test_health_probes_whitelisted(self):
        """Orchestration probes must not require auth."""
        assert "/healthz" in FreqHandler._AUTH_WHITELIST
        assert "/readyz" in FreqHandler._AUTH_WHITELIST

    def test_docs_endpoints_whitelisted(self):
        """API documentation should be publicly accessible."""
        assert "/api/docs" in FreqHandler._AUTH_WHITELIST
        assert "/api/openapi.json" in FreqHandler._AUTH_WHITELIST

    def test_setup_reset_not_whitelisted(self):
        """Setup reset requires admin auth — must NOT be in whitelist."""
        assert "/api/setup/reset" not in FreqHandler._AUTH_WHITELIST

    def test_destructive_endpoints_not_whitelisted(self):
        """Mutating endpoints must never be in whitelist."""
        dangerous = [
            "/api/admin/fleet-boundaries/update",
            "/api/admin/hosts/update",
            "/api/config",
        ]
        for route in dangerous:
            assert route not in FreqHandler._AUTH_WHITELIST, \
                f"Dangerous route {route} should NOT be in auth whitelist"


class TestSetupInitCredentialPaths:
    """Web init runner must support server-side credential paths."""

    def _cfg(self, tmpdir):
        return SimpleNamespace(
            data_dir=os.path.join(tmpdir, "data"),
            install_dir="/opt/pve-freq",
            pve_nodes=[],
            pve_node_names=[],
        )

    def _secret(self, tmpdir, name, value="secret-value-123"):
        path = os.path.join(tmpdir, name)
        with open(path, "w") as f:
            f.write(value)
        os.chmod(path, 0o600)
        return path

    def test_setup_init_accepts_bootstrap_key_path(self):
        from freq.modules.serve import _setup_init_command

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = self._cfg(tmpdir)
            service_pw = self._secret(tmpdir, "service-pass", "service-password-123")
            dash_pw = self._secret(tmpdir, "dash-pass", "dashboard-password-123")
            key_path = self._secret(tmpdir, "bootstrap-key", "not-a-real-key")

            cmd, _env, _secret_dir = _setup_init_command(
                cfg,
                {
                    "service_account_password_file": service_pw,
                    "dashboard_user": "admin",
                    "dashboard_password_file": dash_pw,
                    "bootstrap_user": "freq-ops",
                    "bootstrap_key_path": key_path,
                },
                "jobtest",
            )

        assert "--bootstrap-key" in cmd
        assert cmd[cmd.index("--bootstrap-key") + 1] == key_path
        assert "--service-account" not in cmd

    def test_setup_init_accepts_password_file_paths(self):
        from freq.modules.serve import _setup_init_command

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = self._cfg(tmpdir)
            service_pw = self._secret(tmpdir, "service-pass", "service-password-123")
            dash_pw = self._secret(tmpdir, "dash-pass", "dashboard-password-123")
            bootstrap_pw = self._secret(tmpdir, "bootstrap-pass", "bootstrap-password-123")

            cmd, _env, _secret_dir = _setup_init_command(
                cfg,
                {
                    "service_account_password_file": service_pw,
                    "dashboard_user": "admin",
                    "dashboard_password_file": dash_pw,
                    "bootstrap_user": "freq-ops",
                    "bootstrap_password_file": bootstrap_pw,
                },
                "jobtest",
            )

        assert "--password-file" in cmd
        assert cmd[cmd.index("--password-file") + 1] == service_pw
        assert "--dashboard-password-file" in cmd
        assert cmd[cmd.index("--dashboard-password-file") + 1] == dash_pw
        assert "--bootstrap-password-file" in cmd
        assert cmd[cmd.index("--bootstrap-password-file") + 1] == bootstrap_pw

    def test_setup_init_places_global_yes_before_init_subcommand(self):
        from freq.modules.serve import _setup_init_command

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = self._cfg(tmpdir)
            service_pw = self._secret(tmpdir, "service-pass", "service-password-123")

            cmd, _env, _secret_dir = _setup_init_command(
                cfg,
                {"service_account_password_file": service_pw},
                "jobtest",
            )

        assert "--yes" in cmd
        assert "init" in cmd
        assert cmd.index("--yes") < cmd.index("init")
