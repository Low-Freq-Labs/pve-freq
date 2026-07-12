import inspect
import io
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.core.setup_discovery import (
    DiscoveryInputError,
    _http_fingerprint,
    _ssh_cluster_resources,
    derived_ipv4_networks,
    normalize_pve_resources,
    query_declared_pve_nodes,
    run_setup_discovery,
    scan_derived_devices,
    validate_discovery_request,
)
from freq.core.setup_state import SCHEMA, ensure_setup_state, update_setup_state
from freq.modules import serve
from freq.modules.serve import FreqHandler


def _cfg(root):
    return SimpleNamespace(
        data_dir=os.path.join(root, "data"),
        conf_dir=os.path.join(root, "conf"),
        vault_dir=os.path.join(root, "vault"),
        vault_file=os.path.join(root, "vault", "vault.enc"),
    )


def _request(setup_id="setup-id", request_id="123e4567-e89b-12d3-a456-426614174000"):
    return {
        "schema": SCHEMA,
        "setup_id": setup_id,
        "client_request_id": request_id,
        "cluster": {
            "name": "dc01",
            "nodes": [{"host": "10.25.255.26", "name": "pve01"}],
        },
        "bootstrap": {"username": "freq-ops", "password": "write-only"},
    }


def _handler(body=None, path="/api/setup/discovery/start", command="POST"):
    handler = FreqHandler.__new__(FreqHandler)
    handler.command = command
    handler.path = path
    handler.headers = {}
    handler.rfile = io.BytesIO()
    handler._session_user = "operator"
    handler._request_body = lambda: dict(body or {})
    handler._captured = None
    handler._status_code = None

    def respond(payload, status=200):
        handler._captured = payload
        handler._status_code = status

    handler._json_response = respond
    return handler


@pytest.fixture(autouse=True)
def _clear_discovery_job():
    with serve._setup_discovery_lock:
        serve._setup_discovery_job = None
    yield
    with serve._setup_discovery_lock:
        serve._setup_discovery_job = None


def test_discovery_request_accepts_only_literal_declared_node_ips():
    payload = _request()
    normalized = validate_discovery_request(payload, SCHEMA)
    assert normalized["cluster"]["nodes"] == [{"host": "10.25.255.26", "name": "pve01"}]

    payload["cluster"]["nodes"][0]["host"] = "pve01.example.test"
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "invalid_node_ip"


def test_discovery_request_rejects_non_uuid_idempotency_key():
    payload = _request(request_id="not-a-uuid")
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "invalid_client_request_id"
    assert caught.value.field == "client_request_id"


def test_discovery_request_limits_secret_by_encoded_bytes():
    payload = _request()
    payload["bootstrap"]["password"] = "é" * 2049
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "secret_too_large"
    assert caught.value.field == "bootstrap.password"


def test_discovery_request_has_no_caller_subnet_surface():
    payload = _request()
    payload["cluster"]["subnet"] = "203.0.113.0/24"
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "unsupported_field"
    assert caught.value.field == "cluster.subnet"


def test_derived_networks_are_deduplicated_declared_node_prefixes_only():
    networks = derived_ipv4_networks([
        {"host": "10.25.255.26"},
        {"host": "10.25.255.27"},
        {"host": "10.25.10.1"},
        {"host": "2001:db8::1"},
    ])
    assert [str(network) for network in networks] == ["10.25.255.0/24", "10.25.10.0/24"]


def test_http_identification_disables_proxies_and_redirects():
    source = inspect.getsource(_http_fingerprint)
    assert "ProxyHandler({})" in source
    assert "_NoRedirect" in source
    assert "return None" in source


def test_pve_normalization_distinguishes_vm_container_and_template():
    resources = normalize_pve_resources([
        {"vmid": 100, "name": "app", "node": "pve01", "type": "qemu", "status": "running"},
        {"vmid": 200, "name": "ct", "node": "pve01", "type": "lxc", "status": "running"},
        {"vmid": 9000, "name": "debian", "node": "pve02", "type": "qemu", "template": 1},
    ])
    assert [resource["kind"] for resource in resources] == ["vm", "container", "template"]
    assert [resource["vmid"] for resource in resources] == [100, 200, 9000]


def test_pve_query_never_leaves_declared_node_list():
    seen = []

    def query(host, _username, _password_file):
        seen.append(host)
        return ([{"vmid": 100, "type": "qemu", "node": "pve01"}], "")

    nodes = [{"host": "10.0.0.1", "name": "pve01"}, {"host": "10.0.0.2", "name": "pve02"}]
    with patch("freq.core.setup_discovery._ssh_cluster_resources", side_effect=query):
        node_rows, resources, warnings = query_declared_pve_nodes(nodes, "operator", "/secret")

    assert seen == ["10.0.0.1", "10.0.0.2"]
    assert all(row["host"] in seen for row in node_rows)
    assert resources[0]["vmid"] == 100
    assert warnings == []


def test_pve_ssh_password_is_stdin_and_never_argv():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as secret:
        secret.write("bootstrap-secret")
        secret_path = secret.name
    captured = {}

    def run(args, **kwargs):
        captured["args"] = args
        captured["stdin"] = kwargs["stdin"].read()
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    try:
        with patch("freq.core.setup_discovery.subprocess.run", side_effect=run):
            resources, error = _ssh_cluster_resources("10.0.0.1", "operator", secret_path)
    finally:
        os.unlink(secret_path)

    assert resources == []
    assert error == ""
    assert captured["stdin"] == "bootstrap-secret"
    assert "bootstrap-secret" not in " ".join(captured["args"])
    assert "10.0.0.1" in " ".join(captured["args"])
    assert "sudo -S" in captured["args"][-1]


def test_empty_but_reachable_pve_cluster_is_successful():
    with patch("freq.core.setup_discovery._ssh_cluster_resources", return_value=([], "")):
        node_rows, resources, warnings = query_declared_pve_nodes(
            [{"host": "10.0.0.1", "name": "pve01"}], "operator", "/secret"
        )
    assert node_rows[0]["reachable"] is True
    assert resources == []
    assert warnings == []


def test_derived_device_scan_reports_credential_free_truth():
    def ping(ip):
        return ip == "10.0.0.10"

    with (
        patch("freq.core.setup_discovery._ping", side_effect=ping),
        patch("freq.core.setup_discovery._http_fingerprint", return_value=("truenas", "https")),
    ):
        devices, warnings = scan_derived_devices([{"host": "10.0.0.1"}], set())

    assert warnings == []
    assert devices == [{
        "id": "device:truenas:10.0.0.10",
        "kind": "truenas",
        "label": "truenas-10-0-0-10",
        "host": "10.0.0.10",
        "source": "credential-free-http",
        "reachable": True,
        "credential_fields": ["username", "password", "api_key"],
        "suggested_disposition": "owned",
        "suggested_placement": "production",
    }]


def test_network_scan_uses_only_nodes_proven_to_be_pve():
    cluster = {
        "name": "dc01",
        "nodes": [
            {"host": "10.0.0.1", "name": "pve01"},
            {"host": "203.0.113.7", "name": "not-pve"},
        ],
    }
    proven = [
        {"id": "pve-node:10.0.0.1", "host": "10.0.0.1", "name": "pve01", "reachable": True, "version": ""},
        {"id": "pve-node:203.0.113.7", "host": "203.0.113.7", "name": "not-pve", "reachable": False, "version": ""},
    ]
    captured = {}

    def scan(nodes, _resource_ips, progress=None):
        captured["nodes"] = nodes
        return [], []

    with (
        patch("freq.core.setup_discovery.query_declared_pve_nodes", return_value=(proven, [], [])),
        patch("freq.core.setup_discovery.scan_derived_devices", side_effect=scan),
    ):
        run_setup_discovery(cluster, "operator", "/secret")

    assert captured["nodes"] == [{"host": "10.0.0.1", "name": "pve01"}]


def test_discovery_start_rejects_nested_subnet_before_probe():
    body = _request()
    body["cluster"]["subnet"] = "203.0.113.0/24"
    handler = _handler(body)
    with patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
        handler._serve_setup_discovery_start()
    assert handler._status_code == 400
    assert handler._captured["error"]["code"] == "manual_contract_not_allowed"
    assert handler._captured["error"]["field"] == "cluster.subnet"


def test_discovery_start_stores_password_but_never_returns_it():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        body = _request(setup_id=state["setup_id"])

        class HeldThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

        handler = _handler(body)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", return_value=True) as store,
            patch("freq.modules.serve.vault_get", return_value="write-only"),
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            handler._serve_setup_discovery_start()

        assert handler._status_code == 202
        assert "write-only" not in str(handler._captured)
        assert "bootstrap_username" not in str(handler._captured)
        store.assert_called_once_with(cfg, f"setup:{state['setup_id']}", "bootstrap_password", "write-only")
        assert handler._captured["discovery"]["state"] == "running"


def test_discovery_start_failure_clears_secret_and_reports_blocked_truth():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        body = _request(setup_id=state["setup_id"])

        class BrokenThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                raise RuntimeError("thread unavailable")

        handler = _handler(body)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", return_value=True),
            patch("freq.modules.serve.vault_get", return_value="write-only"),
            patch("freq.modules.serve.vault_delete") as delete,
            patch("freq.modules.serve.threading.Thread", BrokenThread),
        ):
            handler._serve_setup_discovery_start()

        assert handler._status_code == 500
        assert handler._captured["error"]["code"] == "discovery_start_failed"
        delete.assert_called_once_with(
            cfg,
            f"setup:{state['setup_id']}",
            "bootstrap_password",
        )
        assert serve._setup_discovery_snapshot() is None


def test_discovery_worker_deletes_password_and_tofu_adapter_files():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        update_setup_state(cfg, phase="discovering", active_discovery_id="job-1")
        with serve._setup_discovery_lock:
            serve._setup_discovery_job = {
                "id": "job-1",
                "setup_id": state["setup_id"],
                "state": "running",
                "cluster": {"name": "dc01", "nodes": [{"host": "10.0.0.1", "name": "pve01"}]},
                "bootstrap_username": "operator",
                "progress": {},
            }
        captured = {}

        def discover(_cluster, _username, password_file, progress=None):
            captured["password_file"] = password_file
            captured["known_hosts_file"] = f"{password_file}.known-hosts"
            assert os.stat(password_file).st_mode & 0o777 == 0o600
            with open(password_file) as handle:
                assert handle.read() == "bootstrap-secret"
            with open(captured["known_hosts_file"], "w") as handle:
                handle.write("tofu-host-key")
            if progress:
                progress("pve-bootstrap", 1, 1, "Declared PVE node reached.")
            return {"pve_nodes": [], "resources": [], "devices": [], "warnings": []}

        with (
            patch("freq.modules.serve.vault_get", return_value="bootstrap-secret"),
            patch("freq.modules.serve.run_setup_discovery", side_effect=discover),
        ):
            serve._run_setup_discovery_job(cfg, "job-1")

        assert not os.path.exists(captured["password_file"])
        assert not os.path.exists(captured["known_hosts_file"])
        snapshot = serve._setup_discovery_snapshot()
        assert snapshot["state"] == "succeeded"
        assert "bootstrap-secret" not in str(snapshot)


def test_discovery_status_returns_410_when_active_job_was_lost():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        update_setup_state(cfg, phase="discovering", active_discovery_id="lost-job")
        handler = _handler(path="/api/setup/discovery/status?id=lost-job", command="GET")
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
        ):
            handler._serve_setup_discovery_status()

        assert handler._status_code == 410
        assert handler._captured["error"]["code"] == "discovery_expired"
        assert state["setup_id"] == load_setup_id(cfg)


def test_discovery_status_rejects_admin_who_does_not_own_setup():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        handler = _handler(path="/api/setup/discovery/status?id=job-1", command="GET")
        handler._session_user = "other-admin"
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
        ):
            handler._serve_setup_discovery_status()

        assert handler._status_code == 403
        assert handler._captured["error"]["code"] == "setup_owner_mismatch"
        assert state["username"] == "operator"


def test_idempotency_replay_is_bound_to_current_setup_identity():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        body = _request(setup_id=state["setup_id"])
        with serve._setup_discovery_lock:
            serve._setup_discovery_job = {
                "id": "stale-job",
                "setup_id": "different-setup",
                "client_request_id": body["client_request_id"],
                "state": "succeeded",
                "results": {"resources": [{"id": "private-stale-result"}]},
            }

        class HeldThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

        handler = _handler(body)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", return_value=True),
            patch("freq.modules.serve.vault_get", return_value="write-only"),
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            handler._serve_setup_discovery_start()

        assert handler._status_code == 202
        assert handler._captured["discovery"]["id"] != "stale-job"
        assert "private-stale-result" not in str(handler._captured)


def load_setup_id(cfg):
    from freq.core.setup_state import load_setup_state

    return load_setup_state(cfg)["setup_id"]


def test_discovery_routes_require_auth_and_csrf():
    for route in ("/api/setup/discovery/start", "/api/setup/discovery/status"):
        assert route not in FreqHandler._AUTH_WHITELIST
    assert "/api/setup/discovery/start" not in FreqHandler._CSRF_EXEMPT
