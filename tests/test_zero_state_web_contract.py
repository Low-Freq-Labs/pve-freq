import io
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.core.setup_contract import (
    SetupContractError,
    build_setup_contract,
    contract_payload,
    credential_runtime_value,
    credential_storage_value,
    credential_vault_key,
    load_setup_contract,
    save_setup_contract,
    validate_credential_request,
)
from freq.core.setup_state import SCHEMA, ensure_setup_state, load_setup_state, update_setup_state
from freq.modules import serve
from freq.modules.serve import FreqHandler

REQUEST_ID = "123e4567-e89b-12d3-a456-426614174000"


def _cfg(root):
    return SimpleNamespace(
        data_dir=os.path.join(root, "data"),
        conf_dir=os.path.join(root, "conf"),
        vault_dir=os.path.join(root, "vault"),
        vault_file=os.path.join(root, "vault", "vault.enc"),
    )


def _discovery(discovery_id="discovery-1"):
    return {
        "id": discovery_id,
        "setup_id": "setup-1",
        "state": "succeeded",
        "results": {
            "pve_nodes": [
                {"id": "pve-node:10.0.0.1", "host": "10.0.0.1", "name": "pve01", "reachable": True}
            ],
            "resources": [
                {"id": "pve:pve01:qemu:100", "kind": "vm", "vmid": 100, "name": "app", "node": "pve01"},
                {"id": "pve:pve01:lxc:200", "kind": "container", "vmid": 200, "name": "ct", "node": "pve01"},
                {"id": "pve:pve01:qemu:9000", "kind": "template", "vmid": 9000, "name": "debian", "node": "pve01"},
            ],
            "devices": [
                {
                    "id": "device:truenas:10.0.0.10",
                    "kind": "truenas",
                    "label": "storage",
                    "host": "10.0.0.10",
                },
                {
                    "id": "device:unknown:10.0.0.99",
                    "kind": "unknown",
                    "label": "unknown-10-0-0-99",
                    "host": "10.0.0.99",
                },
            ],
            "warnings": [],
        },
    }


def _contract_body(setup_id="setup-1", discovery_id="discovery-1"):
    return {
        "schema": SCHEMA,
        "setup_id": setup_id,
        "discovery_id": discovery_id,
        "client_request_id": REQUEST_ID,
        "selections": [
            {"resource_id": "pve:pve01:qemu:100", "disposition": "owned", "placement": "production"},
            {"resource_id": "pve:pve01:lxc:200", "disposition": "owned", "placement": "lab"},
            {"resource_id": "pve:pve01:qemu:9000", "disposition": "owned", "placement": "production"},
            {"resource_id": "device:truenas:10.0.0.10", "disposition": "owned", "placement": "production"},
            {"resource_id": "device:unknown:10.0.0.99", "disposition": "acknowledged"},
        ],
    }


def _handler(body=None, path="/api/setup/contract", command="POST"):
    handler = FreqHandler.__new__(FreqHandler)
    handler.command = command
    handler.path = path
    handler.headers = {}
    handler.rfile = io.BytesIO()
    handler._session_user = "operator"
    handler._request_body = lambda: body
    handler._captured = None
    handler._status_code = None

    def respond(payload, status=200):
        handler._captured = payload
        handler._status_code = status

    handler._json_response = respond
    return handler


@pytest.fixture(autouse=True)
def _clear_jobs():
    with serve._setup_discovery_lock:
        serve._setup_discovery_job = None
    yield
    with serve._setup_discovery_lock:
        serve._setup_discovery_job = None


def test_contract_normalizes_every_discovered_resource():
    contract = build_setup_contract(_contract_body(), _discovery(), setup_id="setup-1", now=100)
    assert contract["owned_vmids"] == [100, 200]
    assert contract["template_vmids"] == [9000]
    assert contract["acknowledged_out_of_contract_vmids"] == []
    assert contract["owned_devices"][0]["resource_id"] == "device:truenas:10.0.0.10"
    assert contract["acknowledged_devices"][0]["resource_id"] == "device:unknown:10.0.0.99"
    assert contract["credential_requirements"][0]["required_any"] == [
        ["username", "password"],
        ["api_key"],
        ["username", "ssh_private_key"],
    ]


def test_contract_hash_is_stable_for_identical_discovery_and_selections():
    first = build_setup_contract(_contract_body(), _discovery(), setup_id="setup-1", now=100)
    second = build_setup_contract(_contract_body(), _discovery(), setup_id="setup-1", now=200)
    assert first["sha256"] == second["sha256"]
    assert first["contract_id"] != second["contract_id"]


def test_contract_requires_exactly_one_selection_per_resource():
    body = _contract_body()
    body["selections"] = body["selections"][:-1] + [body["selections"][0]]
    with pytest.raises(SetupContractError) as caught:
        build_setup_contract(body, _discovery(), setup_id="setup-1")
    assert caught.value.code == "incomplete_selections"
    assert {item["code"] for item in caught.value.details} == {"duplicate_resource", "missing_selection"}


def test_contract_bounds_untrusted_resource_ids_in_error_details():
    body = _contract_body()
    body["selections"][0] = {"resource_id": "x" * 5000, "disposition": "acknowledged"}
    with pytest.raises(SetupContractError) as caught:
        build_setup_contract(body, _discovery(), setup_id="setup-1")
    detail = next(item for item in caught.value.details if item["code"] == "invalid_resource_id")
    assert len(detail["resource_id"]) == 256


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"resource_id": "missing", "disposition": "acknowledged"}, "unknown_resource"),
        ({"resource_id": "pve:pve01:qemu:100", "disposition": "owned"}, "placement_required"),
        (
            {"resource_id": "pve:pve01:qemu:100", "disposition": "acknowledged", "placement": "lab"},
            "placement_not_allowed",
        ),
    ],
)
def test_contract_rejects_unknown_or_invalid_selection(change, code):
    body = _contract_body()
    body["selections"][0] = change
    with pytest.raises(SetupContractError) as caught:
        build_setup_contract(body, _discovery(), setup_id="setup-1")
    assert code in {item["code"] for item in caught.value.details}


def test_unknown_device_is_acknowledged_only():
    body = _contract_body()
    body["selections"][-1] = {
        "resource_id": "device:unknown:10.0.0.99",
        "disposition": "owned",
        "placement": "lab",
    }
    with pytest.raises(SetupContractError) as caught:
        build_setup_contract(body, _discovery(), setup_id="setup-1")
    assert caught.value.code == "unsupported_device_kind"
    assert caught.value.status == 422


def test_empty_successful_discovery_builds_ready_contract():
    discovery = _discovery()
    discovery["results"]["resources"] = []
    discovery["results"]["devices"] = []
    body = _contract_body()
    body["selections"] = []
    contract = build_setup_contract(body, discovery, setup_id="setup-1")
    payload = contract_payload(contract, lambda _key: "")
    assert payload["counts"] == {
        "owned_virtual": 0,
        "templates": 0,
        "acknowledged_virtual": 0,
        "owned_devices": 0,
        "acknowledged_devices": 0,
    }
    assert payload["ready"] is True


def test_credential_validation_is_kind_constrained_and_value_only():
    contract = build_setup_contract(_contract_body(), _discovery(), setup_id="setup-1")
    body = {
        "schema": SCHEMA,
        "setup_id": "setup-1",
        "contract_id": contract["contract_id"],
        "client_request_id": REQUEST_ID,
        "credentials": [
            {
                "resource_id": "device:truenas:10.0.0.10",
                "username": "root",
                "secrets": {"password": "secret"},
            }
        ],
    }
    normalized = validate_credential_request(body, contract, "setup-1")
    assert normalized["credentials"][0]["values"] == {"username": "root", "password": "secret"}
    body["credentials"][0]["secrets"] = {"sudo_password_file": "/root/secret"}
    with pytest.raises(SetupContractError) as caught:
        validate_credential_request(body, contract, "setup-1")
    assert caught.value.code == "unsupported_credential_field"


def test_multiline_private_key_round_trips_through_line_safe_storage():
    private_key = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----\n"
    stored = credential_storage_value("ssh_private_key", private_key)
    assert "\n" not in stored
    assert credential_runtime_value("ssh_private_key", stored) == private_key


def test_vault_update_applies_one_atomic_rewrite():
    from freq.modules.vault import vault_update

    cfg = SimpleNamespace(vault_file="/tmp/vault.enc")
    captured = {}

    def encrypt(plaintext, key, path):
        captured.update({"plaintext": plaintext, "key": key, "path": path})
        return True

    with (
        patch("freq.modules.vault._vault_key", return_value="vault-key"),
        patch("freq.modules.vault._decrypt", return_value="host|keep|old\nhost|drop|old\n"),
        patch("freq.modules.vault._encrypt", side_effect=encrypt) as encrypt_call,
    ):
        assert vault_update(cfg, "host", {"drop": None, "new": "value"}) is True

    encrypt_call.assert_called_once()
    assert "host|keep|old" in captured["plaintext"]
    assert "host|new|value" in captured["plaintext"]
    assert "host|drop|old" not in captured["plaintext"]


def _setup_handler_state(cfg):
    state = ensure_setup_state(cfg, "operator")
    discovery = _discovery()
    discovery["setup_id"] = state["setup_id"]
    update_setup_state(cfg, phase="selecting", active_discovery_id=discovery["id"])
    with serve._setup_discovery_lock:
        serve._setup_discovery_job = discovery
    return state, discovery


def _vault_patches(store):
    def list_values(_cfg):
        return [(host, key, value) for (host, key), value in sorted(store.items())]

    def update(_cfg, host, updates):
        for key, value in updates.items():
            if value is None:
                store.pop((host, key), None)
            else:
                store[(host, key)] = value
        return True

    return (
        patch("freq.modules.serve.vault_init", return_value=True),
        patch("freq.modules.serve.vault_list", side_effect=list_values),
        patch("freq.modules.serve.vault_update", side_effect=update),
    )


def test_contract_endpoint_persists_non_secret_contract_and_gets_presence_only():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state, discovery = _setup_handler_state(cfg)
        body = _contract_body(setup_id=state["setup_id"], discovery_id=discovery["id"])
        handler = _handler(body)
        store = {}
        p_init, p_list, p_update = _vault_patches(store)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            p_init,
            p_list,
            p_update,
        ):
            handler._serve_setup_contract()
            contract_id = handler._captured["contract"]["id"]
            get_handler = _handler(path="/api/setup/contract", command="GET")
            get_handler._serve_setup_contract()

        assert handler._status_code == 200
        assert handler._captured["contract"]["ready"] is False
        assert get_handler._captured == handler._captured
        assert load_setup_contract(cfg)["contract_id"] == contract_id
        assert load_setup_state(cfg)["phase"] == "credentials"
        contract_path = os.path.join(cfg.data_dir, "setup", "zero-state-contract.json")
        serialized = open(contract_path).read()
        assert "secret" not in serialized
        assert os.stat(contract_path).st_mode & 0o777 == 0o600
        assert os.stat(os.path.dirname(contract_path)).st_mode & 0o777 == 0o700


def test_contract_endpoint_idempotency_returns_existing_contract():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state, discovery = _setup_handler_state(cfg)
        body = _contract_body(setup_id=state["setup_id"], discovery_id=discovery["id"])
        store = {}
        p_init, p_list, p_update = _vault_patches(store)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            p_init,
            p_list,
            p_update,
        ):
            first = _handler(body)
            first._serve_setup_contract()
            replay = _handler(body)
            replay._serve_setup_contract()

        assert replay._captured["contract"]["id"] == first._captured["contract"]["id"]
        assert replay._captured["contract"]["revision"] == 1


def test_device_credentials_store_values_but_return_presence_only():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state, discovery = _setup_handler_state(cfg)
        contract_body = _contract_body(setup_id=state["setup_id"], discovery_id=discovery["id"])
        store = {}
        p_init, p_list, p_update = _vault_patches(store)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            p_init,
            p_list,
            p_update,
        ):
            contract_handler = _handler(contract_body)
            contract_handler._serve_setup_contract()
            contract_id = contract_handler._captured["contract"]["id"]
            credentials = {
                "schema": SCHEMA,
                "setup_id": state["setup_id"],
                "contract_id": contract_id,
                "client_request_id": "123e4567-e89b-12d3-a456-426614174001",
                "credentials": [
                    {
                        "resource_id": "device:truenas:10.0.0.10",
                        "username": "root",
                        "secrets": {"password": "write-only-secret"},
                    }
                ],
            }
            handler = _handler(credentials, path="/api/setup/device-credentials")
            handler._serve_setup_device_credentials()

        assert handler._status_code == 200
        assert handler._captured["ready"] is True
        assert handler._captured["credentials"] == [
            {
                "resource_id": "device:truenas:10.0.0.10",
                "stored_fields": ["password", "username"],
                "complete": True,
            }
        ]
        assert "write-only-secret" not in str(handler._captured)
        assert "write-only-secret" in store.values()
        assert load_setup_state(cfg)["phase"] == "ready"


def test_device_credential_failure_rolls_back_every_touched_value():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state, discovery = _setup_handler_state(cfg)
        contract = build_setup_contract(
            _contract_body(setup_id=state["setup_id"], discovery_id=discovery["id"]),
            discovery,
            setup_id=state["setup_id"],
        )
        save_setup_contract(cfg, contract)
        update_setup_state(cfg, phase="credentials", active_contract_id=contract["contract_id"])
        host = f"setup:{state['setup_id']}"
        username_key = credential_vault_key("device:truenas:10.0.0.10", "username")
        password_key = credential_vault_key("device:truenas:10.0.0.10", "password")
        store = {(host, username_key): "old-user"}

        def list_values(_cfg):
            return [(vault_host, key, value) for (vault_host, key), value in sorted(store.items())]

        def fail_password(_cfg, vault_host, updates):
            if password_key in updates:
                return False
            for key, value in updates.items():
                if value is None:
                    store.pop((vault_host, key), None)
                else:
                    store[(vault_host, key)] = value
            return True

        body = {
            "schema": SCHEMA,
            "setup_id": state["setup_id"],
            "contract_id": contract["contract_id"],
            "client_request_id": REQUEST_ID,
            "credentials": [
                {
                    "resource_id": "device:truenas:10.0.0.10",
                    "username": "new-user",
                    "secrets": {"password": "new-password"},
                }
            ],
        }
        handler = _handler(body, path="/api/setup/device-credentials")
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.vault_list", side_effect=list_values),
            patch("freq.modules.serve.vault_update", side_effect=fail_password),
        ):
            handler._serve_setup_device_credentials()

        assert handler._status_code == 500
        assert handler._captured["error"]["code"] == "credential_store_failed"
        assert store[(host, username_key)] == "old-user"
        assert (host, password_key) not in store


def test_nested_path_input_is_rejected_before_vault_access():
    handler = _handler(
        {
            "schema": SCHEMA,
            "setup_id": "setup",
            "contract_id": "contract",
            "credentials": [
                {"resource_id": "device:truenas:1", "secrets": {"password_file": "/root/secret"}}
            ],
        },
        path="/api/setup/device-credentials",
    )
    with (
        patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
        patch("freq.modules.serve.load_config") as load,
        patch("freq.modules.serve.vault_update") as store,
    ):
        load.return_value = _cfg("/unused")
        with patch("freq.modules.serve.load_setup_state", return_value={"username": "operator", "setup_id": "setup"}):
            handler._serve_setup_device_credentials()
    assert handler._status_code == 400
    assert handler._captured["error"]["code"] == "path_input_not_allowed"
    assert handler._captured["error"]["field"] == "credentials[0].secrets.password_file"
    store.assert_not_called()


def test_setup_contract_and_credentials_routes_are_authenticated_and_csrf_bound():
    for route in ("/api/setup/contract", "/api/setup/device-credentials"):
        assert route in FreqHandler._ROUTES
        assert route not in FreqHandler._AUTH_WHITELIST
        assert route not in FreqHandler._CSRF_EXEMPT


def test_zero_state_window_closes_only_when_both_markers_exist():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        os.makedirs(cfg.conf_dir)
        initialized = os.path.join(cfg.conf_dir, ".initialized")
        web_complete = os.path.join(cfg.conf_dir, ".web-setup-complete")
        open(initialized, "w").close()
        assert serve._zero_state_setup_complete(cfg) is False
        open(web_complete, "w").close()
        assert serve._zero_state_setup_complete(cfg) is True


def test_contract_endpoint_rejects_after_complete_without_reading_contract():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        os.makedirs(cfg.conf_dir)
        open(os.path.join(cfg.conf_dir, ".initialized"), "w").close()
        open(os.path.join(cfg.conf_dir, ".web-setup-complete"), "w").close()
        handler = _handler({}, command="GET")
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.load_setup_contract") as load_contract,
        ):
            handler._serve_setup_contract()
        assert handler._status_code == 403
        assert handler._captured["error"]["code"] == "setup_closed"
        load_contract.assert_not_called()


def test_reset_removes_setup_contract_and_exact_namespace_secrets():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state, discovery = _setup_handler_state(cfg)
        contract = build_setup_contract(
            _contract_body(setup_id=state["setup_id"], discovery_id=discovery["id"]),
            discovery,
            setup_id=state["setup_id"],
        )
        save_setup_contract(cfg, contract)
        update_setup_state(cfg, phase="credentials", active_contract_id=contract["contract_id"])
        host = f"setup:{state['setup_id']}"
        device_key = credential_vault_key("device:truenas:10.0.0.10", "password")
        store = {(host, "bootstrap_password"): "bootstrap", (host, device_key): "device-secret"}
        p_init, p_list, p_update = _vault_patches(store)
        handler = _handler({}, path="/api/setup/reset")
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_init_snapshot", return_value={"running": False, "job": None}),
            p_init,
            p_list,
            p_update,
        ):
            handler._serve_setup_reset()

        assert handler._status_code == 200
        assert load_setup_state(cfg) == {}
        assert load_setup_contract(cfg) == {}
        assert store == {}
