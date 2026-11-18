"""Containers.toml consumer acceptance tests.

Acceptance surface:
1. Docker tab — fleet inventory, container registry, media status
2. Media tab — container cards, downloads, streams
3. Lab Equipment — lab hosts + docker section
4. CRUD — add/edit/delete containers in registry
5. Blocked/unconfigured states — honest UI when upstream data absent

Each test proves a specific consumer touchpoint behaves correctly
against the current upstream artifact state.
"""

import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _assert_media_status_projection_contract():
    """Pin media-status registry, SSH, normalization, and response truth."""
    from ast import FunctionDef, ImportFrom, parse, walk
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from freq.modules import serve
    from freq.services import media_activity

    serve_source = (Path(REPO_ROOT) / "freq/modules/serve.py").read_text()
    service_source = (Path(REPO_ROOT) / "freq/services/media_activity.py").read_text()
    serve_tree = parse(serve_source)
    service_tree = parse(service_source)
    assert "media_status_projection" not in {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    assert len([
        node for node in walk(service_tree)
        if isinstance(node, FunctionDef) and node.name == "media_status_projection"
    ]) == 1
    assert not any(
        isinstance(node, ImportFrom)
        and node.module is not None
        and node.module.startswith("freq.modules")
        for node in service_tree.body
    )
    assert serve._media_activity.media_status_projection is media_activity.media_status_projection
    status_handler = serve_source.split(
        "def _serve_media_status", 1
    )[1].split("def _serve_", 1)[0]
    assert "_media_activity.media_status_projection(" in status_handler

    vm = SimpleNamespace(
        vm_id=101,
        label="arr-stack",
        containers={
            "tdarr_node": SimpleNamespace(port=8265),
            "missing": SimpleNamespace(port=9000),
        },
    )
    cfg = SimpleNamespace(
        container_vms={"arr-stack": vm},
        ssh_key_path="/home/freq/.ssh/key",
    )
    resolved_ip = "10.0.0.31"
    ssh_result = SimpleNamespace(
        returncode=0,
        stdout="tdarr-node-cpu-2|Up 2 hours\n",
        stderr="",
    )
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler._json_response = MagicMock()

    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_resolve_container_vm_ip", return_value=resolved_ip) as resolve,
        patch.object(serve, "ssh_single", return_value=ssh_result) as ssh,
    ):
        handler._serve_media_status()

    resolve.assert_called_once_with(vm)
    ssh.assert_called_once_with(
        host=resolved_ip,
        command="docker ps -a --format '{{.Names}}|{{.Status}}' 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=10,
        htype="docker",
        use_sudo=False,
        cfg=cfg,
    )
    handler._json_response.assert_called_once_with(
        {
            "containers": [
                {
                    "name": "tdarr_node",
                    "vm_id": 101,
                    "vm_label": "arr-stack",
                    "vm_ip": resolved_ip,
                    "port": 8265,
                    "status": "up",
                    "detail": "Up 2 hours",
                },
                {
                    "name": "missing",
                    "vm_id": 101,
                    "vm_label": "arr-stack",
                    "vm_ip": resolved_ip,
                    "port": 9000,
                    "status": "down",
                    "detail": "not found",
                },
            ],
            "count": 2,
            "registry_configured": True,
        }
    )

    absent = SimpleNamespace(container_vms={}, ssh_key_path="/unused")
    absent_handler = serve.FreqHandler.__new__(serve.FreqHandler)
    absent_handler._json_response = MagicMock()
    with patch.object(serve, "load_config", return_value=absent):
        absent_handler._serve_media_status()
    absent_handler._json_response.assert_called_once_with(
        {"containers": [], "count": 0, "registry_configured": False}
    )

    failed_handler = serve.FreqHandler.__new__(serve.FreqHandler)
    failed_handler._json_response = MagicMock()
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_resolve_container_vm_ip", return_value=resolved_ip),
        patch.object(serve, "ssh_single", side_effect=OSError("ssh failed")),
    ):
        try:
            failed_handler._serve_media_status()
        except OSError as exc:
            assert str(exc) == "ssh failed"
        else:
            raise AssertionError("media status SSH failure was swallowed")
    failed_handler._json_response.assert_not_called()


def _assert_media_dashboard_projection_contract():
    """Pin cached/live dashboard totals and truthful registry projection."""
    from ast import FunctionDef, ImportFrom, parse, walk
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from freq.modules import serve
    from freq.services import media_activity

    serve_source = (Path(REPO_ROOT) / "freq/modules/serve.py").read_text()
    service_source = (Path(REPO_ROOT) / "freq/services/media_activity.py").read_text()
    serve_tree = parse(serve_source)
    service_tree = parse(service_source)
    assert "media_dashboard_counts" not in {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    assert len([
        node for node in walk(service_tree)
        if isinstance(node, FunctionDef) and node.name == "media_dashboard_counts"
    ]) == 1
    assert not any(
        isinstance(node, ImportFrom)
        and node.module is not None
        and node.module.startswith("freq.modules")
        for node in service_tree.body
    )
    assert serve._media_activity.media_dashboard_counts is media_activity.media_dashboard_counts
    dashboard_handler = serve_source.split("def _serve_media_dashboard", 1)[1].split(
        "def _serve_", 1
    )[0]
    assert "_media_activity.media_dashboard_counts(" in dashboard_handler

    vm = SimpleNamespace(vm_id=101, label="arr-stack", containers={
        "tdarr_node": SimpleNamespace(port=8265),
        "missing": SimpleNamespace(port=9000),
    })
    cfg = SimpleNamespace(
        container_vms={"arr-stack": vm},
        ssh_key_path="/home/freq/.ssh/key",
    )
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler._json_response = MagicMock()
    health = {"hosts": [
        {"ip": "10.0.0.31", "status": "ok", "docker": "1"},
        {"ip": "10.0.0.31", "status": "unreachable", "docker": "50"},
        {"ip": "10.0.0.99", "status": "ok", "docker": "99"},
    ]}
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_bg_cache", {"health": health}),
        patch.object(serve, "_bg_cache_ts", {"health": 100}),
        patch.object(serve.time, "time", return_value=110),
        patch.object(serve, "_resolve_container_vm_ip", return_value="10.0.0.31"),
    ):
        handler._serve_media_dashboard()
    handler._json_response.assert_called_once_with({
        "containers_total": 2, "containers_running": 1, "containers_down": 1,
        "vm_count": 1, "registry_configured": True, "cached": True,
        "age_seconds": 10, "source": "health_cache",
    })

    live_result = SimpleNamespace(returncode=0, stdout="2\n", stderr="")
    handler._json_response.reset_mock()
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_bg_cache", {"health": None}),
        patch.object(serve, "_bg_cache_ts", {}),
        patch.object(serve, "_resolve_container_vm_ip", return_value="10.0.0.31") as resolve,
        patch.object(serve, "ssh_single", return_value=live_result) as ssh,
    ):
        handler._serve_media_dashboard()
    resolve.assert_called_once_with(vm)
    ssh.assert_called_once_with(
        host="10.0.0.31",
        command="docker ps --format '{{.Names}}' 2>/dev/null | wc -l",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=10,
        htype="docker",
        use_sudo=False,
        cfg=cfg,
    )
    handler._json_response.assert_called_once_with({
        "containers_total": 2, "containers_running": 2, "containers_down": 0,
        "vm_count": 1, "registry_configured": True, "cached": False,
        "age_seconds": None, "source": "live_probe",
    })

    empty = SimpleNamespace(container_vms={})
    handler._json_response.reset_mock()
    with (
        patch.object(serve, "load_config", return_value=empty),
        patch.object(serve, "_bg_cache", {"health": None}),
        patch.object(serve, "_bg_cache_ts", {}),
        patch.object(serve, "ssh_single") as ssh,
    ):
        handler._serve_media_dashboard()
    handler._json_response.assert_called_once_with({
        "containers_total": 0, "containers_running": 0, "containers_down": 0,
        "vm_count": 0, "registry_configured": False, "cached": False,
        "age_seconds": None, "source": "live_probe",
    })
    ssh.assert_not_called()

    failed_handler = serve.FreqHandler.__new__(serve.FreqHandler)
    failed_handler._json_response = MagicMock()
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_bg_cache", {"health": None}),
        patch.object(serve, "_bg_cache_ts", {}),
        patch.object(serve, "_resolve_container_vm_ip", return_value="10.0.0.31"),
        patch.object(serve, "ssh_single", side_effect=OSError("ssh failed")),
    ):
        try:
            failed_handler._serve_media_dashboard()
        except OSError as exc:
            assert str(exc) == "ssh failed"
        else:
            raise AssertionError("media dashboard SSH failure was swallowed")
    failed_handler._json_response.assert_not_called()


def _assert_media_health_projection_contract():
    """Pin media-health eligibility, SSH probe, and response truth."""
    from ast import FunctionDef, ImportFrom, parse, walk
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from freq.modules import serve
    from freq.services import media_activity

    serve_source = (Path(REPO_ROOT) / "freq/modules/serve.py").read_text()
    service_source = (Path(REPO_ROOT) / "freq/services/media_activity.py").read_text()
    serve_tree = parse(serve_source)
    service_tree = parse(service_source)
    assert "media_health_projection" not in {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    assert len([
        node for node in walk(service_tree)
        if isinstance(node, FunctionDef) and node.name == "media_health_projection"
    ]) == 1
    assert not any(
        isinstance(node, ImportFrom)
        and node.module is not None
        and node.module.startswith("freq.modules")
        for node in service_tree.body
    )
    assert serve._media_activity.media_health_projection is media_activity.media_health_projection
    health_handler = serve_source.split("def _serve_media_health", 1)[1].split(
        "def _serve_", 1
    )[0]
    assert "_media_activity.media_health_projection(" in health_handler

    vm = SimpleNamespace(
        vm_id=101,
        label="arr-stack",
        containers={
            "sonarr": SimpleNamespace(port=8989, api_path="/ping"),
            "radarr": SimpleNamespace(port=7878, api_path="/health"),
            "unprobed": SimpleNamespace(port=9000, api_path=""),
        },
    )
    cfg = SimpleNamespace(
        container_vms={"arr-stack": vm},
        ssh_key_path="/home/freq/.ssh/key",
    )
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler._json_response = MagicMock()
    ssh_results = [
        SimpleNamespace(returncode=0, stdout="200\n", stderr=""),
        SimpleNamespace(returncode=1, stdout="503\n", stderr="failed"),
    ]
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_resolve_container_vm_ip", return_value="10.0.0.31") as resolve,
        patch.object(serve, "ssh_single", side_effect=ssh_results) as ssh,
    ):
        handler._serve_media_health()
    resolve.assert_called_once_with(vm)
    assert ssh.call_count == 2
    ssh.assert_any_call(
        host="10.0.0.31",
        command="curl -s -o /dev/null -w '%{http_code}' --connect-timeout 2 "
                "'http://localhost:8989/ping' 2>/dev/null || echo 000",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=5,
        htype="docker",
        use_sudo=False,
        cfg=cfg,
    )
    handler._json_response.assert_called_once_with({
        "services": [
            {"name": "sonarr", "vm_label": "arr-stack", "status": "healthy",
             "http_code": "200", "port": 8989},
            {"name": "radarr", "vm_label": "arr-stack", "status": "down",
             "http_code": "000", "port": 7878},
        ],
        "skipped": 1,
        "registry_configured": True,
    })

    empty = SimpleNamespace(container_vms={}, ssh_key_path="/unused")
    handler._json_response.reset_mock()
    with patch.object(serve, "load_config", return_value=empty):
        handler._serve_media_health()
    handler._json_response.assert_called_once_with({
        "services": [], "skipped": 0, "registry_configured": False,
    })

    failed_handler = serve.FreqHandler.__new__(serve.FreqHandler)
    failed_handler._json_response = MagicMock()
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_resolve_container_vm_ip", return_value="10.0.0.31"),
        patch.object(serve, "ssh_single", side_effect=OSError("ssh failed")),
    ):
        try:
            failed_handler._serve_media_health()
        except OSError as exc:
            assert str(exc) == "ssh failed"
        else:
            raise AssertionError("media health SSH failure was swallowed")
    failed_handler._json_response.assert_not_called()


def _assert_media_downloads_qbit_projection_contract():
    """Pin qBittorrent container-local success and response projection."""
    from ast import FunctionDef, ImportFrom, parse, walk
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from freq.modules import serve
    from freq.services import media_activity

    serve_source = (Path(REPO_ROOT) / "freq/modules/serve.py").read_text()
    service_source = (Path(REPO_ROOT) / "freq/services/media_activity.py").read_text()
    serve_tree = parse(serve_source)
    service_tree = parse(service_source)
    assert "qbit_container_local_downloads" not in {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    assert len([
        node for node in walk(service_tree)
        if isinstance(node, FunctionDef) and node.name == "qbit_container_local_downloads"
    ]) == 1
    assert not any(
        isinstance(node, ImportFrom)
        and node.module is not None
        and node.module.startswith("freq.modules")
        for node in service_tree.body
    )
    assert (
        serve._media_activity.qbit_container_local_downloads
        is media_activity.qbit_container_local_downloads
    )
    assert "_media_activity.qbit_container_local_downloads(" in serve_source.split(
        "def _serve_media_downloads(self)", 1
    )[1].split("def _serve_", 1)[0]

    container = SimpleNamespace(name="qbittorrent", port=8080)
    vm = SimpleNamespace(label="arr-stack", containers={"qbittorrent": container})
    cfg = SimpleNamespace(container_vms={"arr-stack": vm})
    parsed = [{"name": "ubuntu.iso", "progress": 50}]
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler._json_response = MagicMock()
    result = SimpleNamespace(returncode=0, stdout="[]", stderr="")
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_media_container_port", return_value=8080) as port,
        patch.object(serve, "_docker_exec_json", return_value=([{"name": "raw"}], result)) as docker,
        patch.object(serve, "_parse_qbit_downloads", return_value=parsed) as parse,
        patch.object(serve, "vault_get") as vault,
        patch.object(serve, "_media_ssh_single") as ssh,
    ):
        handler._serve_media_downloads()
    port.assert_called_once_with(container)
    docker.assert_called_once_with(
        cfg,
        vm,
        "qbittorrent",
        'curl -s --connect-timeout 3 "http://localhost:8080/api/v2/torrents/info?filter=downloading"',
    )
    parse.assert_called_once_with([{"name": "raw"}], "arr-stack")
    vault.assert_not_called()
    ssh.assert_not_called()
    handler._json_response.assert_called_once_with({
        "downloads": parsed,
        "count": 1,
        "warnings": [],
        "sources": [{"client": "qBittorrent", "vm": "arr-stack", "source": "container-local"}],
    })

    empty = SimpleNamespace(container_vms={})
    handler._json_response.reset_mock()
    with patch.object(serve, "load_config", return_value=empty):
        handler._serve_media_downloads()
    handler._json_response.assert_called_once_with({
        "downloads": [], "count": 0, "warnings": [], "sources": [],
    })

    failed_handler = serve.FreqHandler.__new__(serve.FreqHandler)
    failed_handler._json_response = MagicMock()
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_media_container_port", return_value=8080),
        patch.object(serve, "_docker_exec_json", side_effect=OSError("exec failed")),
    ):
        try:
            failed_handler._serve_media_downloads()
        except OSError as exc:
            assert str(exc) == "exec failed"
        else:
            raise AssertionError("media downloads execution failure was swallowed")
    failed_handler._json_response.assert_not_called()


def _assert_media_downloads_qbit_vault_fallback_contract():
    """Pin qBittorrent vault-auth fallback without credential projection."""
    from ast import FunctionDef, ImportFrom, parse, walk
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import MagicMock, call, patch

    from freq.modules import serve
    from freq.services import media_activity

    serve_source = (Path(REPO_ROOT) / "freq/modules/serve.py").read_text()
    service_source = (Path(REPO_ROOT) / "freq/services/media_activity.py").read_text()
    serve_tree = parse(serve_source)
    service_tree = parse(service_source)
    assert "qbit_vault_auth_downloads" not in {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    assert len([
        node for node in walk(service_tree)
        if isinstance(node, FunctionDef) and node.name == "qbit_vault_auth_downloads"
    ]) == 1
    assert not any(
        isinstance(node, ImportFrom)
        and node.module is not None
        and node.module.startswith("freq.modules")
        for node in service_tree.body
    )
    assert (
        serve._media_activity.qbit_vault_auth_downloads
        is media_activity.qbit_vault_auth_downloads
    )
    assert "_media_activity.qbit_vault_auth_downloads(" in serve_source.split(
        "def _serve_media_downloads(self)", 1
    )[1].split("def _serve_", 1)[0]

    container = SimpleNamespace(name="qbittorrent", port=8080)
    vm = SimpleNamespace(label="arr-stack", containers={"qbittorrent": container})
    cfg = SimpleNamespace(container_vms={"arr-stack": vm})
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler._json_response = MagicMock()
    parsed = [{"name": "ubuntu.iso", "progress": 50}]
    failed_local = SimpleNamespace(returncode=1, stdout="", stderr="unauthorized")
    authenticated = SimpleNamespace(
        returncode=0,
        stdout='Ok.\n[{"name":"raw"}]',
        stderr="",
    )
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_media_container_port", return_value=8080),
        patch.object(serve, "_docker_exec_json", return_value=(None, failed_local)),
        patch.object(serve, "vault_get", side_effect=[None, "fake-secret"]) as vault,
        patch.object(serve, "_media_ssh_single", return_value=authenticated) as ssh,
        patch.object(serve, "_parse_qbit_downloads", return_value=parsed) as parse,
    ):
        handler._serve_media_downloads()
    assert vault.call_args_list == [
        call(cfg, "DEFAULT", "qbittorrent_user"),
        call(cfg, "DEFAULT", "qbittorrent_password"),
    ]
    ssh.assert_called_once_with(
        cfg,
        vm,
        "curl -s -c /tmp/qb.cookie --connect-timeout 3 "
        "'http://localhost:8080/api/v2/auth/login' "
        "-d 'username=admin&password=fake-secret' && "
        "curl -s -b /tmp/qb.cookie --connect-timeout 3 "
        "'http://localhost:8080/api/v2/torrents/info?filter=downloading'",
        timeout=10,
    )
    parse.assert_called_once_with([{"name": "raw"}], "arr-stack")
    expected = {
        "downloads": parsed,
        "count": 1,
        "warnings": [],
        "sources": [{"client": "qBittorrent", "vm": "arr-stack", "source": "vault-auth"}],
    }
    handler._json_response.assert_called_once_with(expected)
    assert "fake-secret" not in repr(expected)

    missing = serve.FreqHandler.__new__(serve.FreqHandler)
    missing._json_response = MagicMock()
    with (
        patch.object(serve, "load_config", return_value=cfg),
        patch.object(serve, "_media_container_port", return_value=8080),
        patch.object(serve, "_docker_exec_json", return_value=(None, failed_local)),
        patch.object(serve, "vault_get", side_effect=[None, ""]) as vault,
        patch.object(serve, "_media_ssh_single") as ssh,
    ):
        missing._serve_media_downloads()
    assert vault.call_count == 2
    ssh.assert_not_called()
    missing._json_response.assert_called_once_with({
        "downloads": [],
        "count": 0,
        "warnings": [{"client": "qBittorrent", "vm": "arr-stack", "reason": "auth_required"}],
        "sources": [],
    })


class TestDockerFleetAcceptance(unittest.TestCase):
    """Docker Fleet Inventory uses hosts.toml, not containers.toml."""

    def test_docker_hosts_exist_in_fleet(self):
        """Fleet has docker-type hosts from hosts.toml."""
        from freq.core.config import load_config
        from freq.core.resolve import by_type
        cfg = load_config()
        docker_hosts = by_type(cfg.hosts, "docker")
        self.assertGreater(len(docker_hosts), 0,
                           "hosts.toml must define docker-type hosts")
        labels = [h.label for h in docker_hosts]
        self.assertIn("arr-stack", labels)
        self.assertIn("plex", labels)

    def test_docker_fleet_handler_passes_cfg(self):
        """handle_docker_fleet passes cfg=cfg to SSH (fixes freq-admin bug)."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn("cfg=cfg", handler_src,
                       "docker-fleet SSH must pass cfg=cfg")

    def test_docker_fleet_returns_frontend_keys(self):
        """Response includes vms + running for frontend loadDockerFleet."""
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler_src = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn('"vms"', handler_src)
        self.assertIn('"running"', handler_src)


class TestContainerRegistryAcceptance(unittest.TestCase):
    """Container registry reflects real containers.toml state."""

    def test_registry_reflects_disk_state(self):
        """container_vms matches containers.toml contents."""
        from freq.core.config import load_config
        cfg = load_config()
        containers_path = os.path.join(cfg.conf_dir, "containers.toml")
        with open(containers_path) as f:
            content = f.read()
        has_entries = any(l.strip() and not l.strip().startswith("#")
                         for l in content.split("\n"))
        if has_entries:
            self.assertGreater(len(cfg.container_vms), 0)
        else:
            self.assertEqual(len(cfg.container_vms), 0,
                             "Empty containers.toml must yield empty container_vms")

    def test_registry_response_has_vm_key(self):
        """Registry list includes vm_key for canonical CRUD identity."""
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        self.assertIn('"vm_key"',
                       src.split("def handle_containers_registry")[1].split("\ndef ")[0])

    def test_crud_uses_lookup_vm(self):
        """All CRUD handlers use _lookup_vm for format-agnostic lookup."""
        with open(os.path.join(REPO_ROOT, "freq/api/docker_api.py")) as f:
            src = f.read()
        for name in ["handle_containers_add", "handle_containers_edit",
                      "handle_containers_delete"]:
            block = src.split(f"def {name}")[1].split("\ndef ")[0]
            self.assertIn("_lookup_vm", block, f"{name} must use _lookup_vm")


class TestMediaEndpointsAcceptance(unittest.TestCase):
    """All media endpoints include registry_configured flag."""

    def _get_handler_block(self, handler_name):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        return src.split(f"def {handler_name}")[1].split("def _serve_")[0]

    def test_media_status_flag(self):
        self.assertIn("registry_configured", self._get_handler_block("_serve_media_status"))
        _assert_media_status_projection_contract()

    def test_media_dashboard_flag(self):
        self.assertIn("registry_configured", self._get_handler_block("_serve_media_dashboard"))
        _assert_media_dashboard_projection_contract()

    def test_media_health_flag(self):
        self.assertIn("registry_configured", self._get_handler_block("_serve_media_health"))
        _assert_media_health_projection_contract()
        _assert_media_downloads_qbit_projection_contract()
        _assert_media_downloads_qbit_vault_fallback_contract()


class TestLabEquipmentAcceptance(unittest.TestCase):
    """Lab Equipment shows real host data from hosts.toml."""

    def test_lab_hosts_exist(self):
        from freq.core.config import load_config
        cfg = load_config()
        lab_hosts = [h for h in cfg.hosts if "lab" in (h.groups or "").split(",")]
        self.assertGreater(len(lab_hosts), 0)
        fixture = next((host for host in lab_hosts if host.label == "freq-test"), None)
        self.assertIsNotNone(fixture, "lab registry must include freq-test")
        self.assertTrue(fixture.ip, "freq-test must have an address")

    def test_lab_handler_passes_cfg(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        lab_block = src.split("def _serve_lab_status")[1].split("def _serve_")[0]
        # Both SSH calls in lab handler must have cfg=cfg
        ssh_calls = lab_block.split("ssh_single(")
        for i, call in enumerate(ssh_calls[1:], 1):
            call_block = call.split(")")[0]
            self.assertIn("cfg=cfg", call_block,
                           f"Lab status SSH call #{i} must pass cfg=cfg")


class TestBlockedStatesAcceptance(unittest.TestCase):
    """Frontend shows honest blocked state when upstream data is absent."""

    def test_frontend_checks_registry_configured(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        # loadContainerSection checks registry_configured
        section = src.split("function loadContainerSection")[1].split("\nfunction ")[0]
        self.assertIn("registry_configured", section)

    def test_frontend_registry_checks_flag(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        section = src.split("function loadContainerRegistry")[1].split("\nfunction ")[0]
        self.assertIn("registry_configured", section)


class TestFormatPreservationAcceptance(unittest.TestCase):
    """_write_containers_toml preserves format on round-trip."""

    def test_host_format_preserved(self):
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {"test-host": ContainerVM(vm_id=0, ip="10.0.0.1", label="test-host")}
        vms["test-host"].containers["app"] = Container(name="app", vm_id=0, port=8080)

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            tmp = f.name
        try:
            _write_containers_toml(tmp, vms)
            with open(tmp) as f:
                content = f.read()
            self.assertIn("[host.test-host]", content)
            self.assertNotIn("[vm.", content)
            reloaded = load_containers(tmp)
            self.assertIn("test-host", reloaded)
            self.assertEqual(reloaded["test-host"].containers["app"].port, 8080)
        finally:
            os.unlink(tmp)

    def test_legacy_format_preserved(self):
        from freq.core.config import Container, ContainerVM, load_containers
        from freq.modules.serve import _write_containers_toml

        vms = {200: ContainerVM(vm_id=200, ip="10.0.0.2", label="legacy")}
        vms[200].containers["web"] = Container(name="web", vm_id=200, port=80)

        with tempfile.NamedTemporaryFile(suffix=".toml", delete=False) as f:
            tmp = f.name
        try:
            _write_containers_toml(tmp, vms)
            with open(tmp) as f:
                content = f.read()
            self.assertIn("[vm.200]", content)
            self.assertNotIn("[host.", content)
            reloaded = load_containers(tmp)
            self.assertIn(200, reloaded)
        finally:
            os.unlink(tmp)


class TestSSHCfgAcceptance(unittest.TestCase):
    """All consumer SSH calls pass cfg=cfg."""

    def test_no_missing_cfg(self):
        """AST scan confirms zero SSH calls without cfg."""
        import ast

        SSH_FUNCS = {"ssh_single", "ssh_run_many", "run_many", "ssh_run_many_fn", "ssh_fn"}
        consumer_files = [
            "freq/api/fleet.py", "freq/api/docker_api.py", "freq/api/vm.py",
            "freq/api/secure.py", "freq/api/backup_verify.py", "freq/api/logs.py",
            "freq/api/hw.py", "freq/api/net.py", "freq/modules/serve.py",
        ]
        missing = []
        for relpath in consumer_files:
            fpath = os.path.join(REPO_ROOT, relpath)
            if not os.path.isfile(fpath):
                continue
            with open(fpath) as f:
                tree = ast.parse(f.read(), filename=relpath)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = ""
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    if name in SSH_FUNCS:
                        if not any(kw.arg == "cfg" for kw in node.keywords):
                            missing.append(f"{relpath}:{node.lineno}")
        self.assertEqual(missing, [], f"SSH calls missing cfg=cfg: {missing}")


if __name__ == "__main__":
    unittest.main()
