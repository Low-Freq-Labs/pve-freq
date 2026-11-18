import ast
import inspect
import io
import os
import tempfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import call, patch

import pytest

from freq.api import auth
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
from freq.services import setup_progress

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


def test_credential_error_fields_match_actual_nested_request_paths():
    contract = build_setup_contract(_contract_body(), _discovery(), setup_id="setup-1")
    base = {
        "schema": SCHEMA,
        "setup_id": "setup-1",
        "contract_id": contract["contract_id"],
        "client_request_id": REQUEST_ID,
        "credentials": [
            {
                "resource_id": "device:truenas:10.0.0.10",
                "username": "root\n",
                "secrets": {"password": "secret"},
            }
        ],
    }
    with pytest.raises(SetupContractError) as username_error:
        validate_credential_request(base, contract, "setup-1")
    assert username_error.value.field == "credentials[0].username"

    base["credentials"][0]["username"] = "root"
    base["credentials"][0]["secrets"]["password"] = "secret\n"
    with pytest.raises(SetupContractError) as secret_error:
        validate_credential_request(base, contract, "setup-1")
    assert secret_error.value.field == "credentials[0].secrets.password"


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

    @contextmanager
    def list_patches():
        with patch("freq.modules.serve.vault_list", side_effect=list_values), patch(
            "freq.api.auth.vault_list", side_effect=list_values
        ):
            yield

    @contextmanager
    def update_patches():
        with patch("freq.modules.serve.vault_update", side_effect=update), patch(
            "freq.api.auth.vault_update", side_effect=update
        ):
            yield

    return (
        patch("freq.modules.serve.vault_init", return_value=True),
        list_patches(),
        update_patches(),
    )


def _assert_setup_contract_credential_cleanup_contract():
    assert serve._clear_setup_contract_credentials is auth._clear_setup_contract_credentials
    serve_tree = ast.parse(inspect.getsource(serve))
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_clear_setup_contract_credentials"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_clear_setup_contract_credentials"
        for node in ast.walk(serve_tree)
    ) == 0
    auth_tree = ast.parse(inspect.getsource(auth))
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_vault_host"
        for node in ast.walk(auth_tree)
    ) == 4
    assert sum(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            name.startswith("freq.modules")
            for name in (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
        )
        for node in ast.walk(auth_tree)
    ) == 1

    cfg = object()
    setup_id = object()
    contract = {"setup_id": setup_id}
    host = object()
    other_host = object()
    keep_value = object()
    drop_value = object()

    for falsey_contract in (None, {}):
        with patch("freq.api.auth._setup_vault_host") as vault_host, patch(
            "freq.api.auth.vault_list"
        ) as vault_list, patch(
            "freq.api.auth.contract_credential_keys"
        ) as credential_keys, patch("freq.api.auth.vault_update") as vault_update:
            assert serve._clear_setup_contract_credentials(cfg, falsey_contract) is None
        vault_host.assert_not_called()
        vault_list.assert_not_called()
        credential_keys.assert_not_called()
        vault_update.assert_not_called()

    first_snapshot = [
        (host, "keep", keep_value),
        (other_host, "cross-host", object()),
        (host, "drop", drop_value),
        (host, "keep", object()),
    ]
    verified_snapshot = [
        (host, "unrelated", object()),
        (other_host, "keep", keep_value),
    ]
    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ) as vault_host, patch(
        "freq.api.auth.vault_list", side_effect=[first_snapshot, verified_snapshot]
    ) as vault_list, patch(
        "freq.api.auth.contract_credential_keys",
        return_value=["missing", "keep", "cross-host", "drop", "keep"],
    ) as credential_keys, patch(
        "freq.api.auth.vault_update", return_value=True
    ) as vault_update:
        assert serve._clear_setup_contract_credentials(cfg, contract) is None
    vault_host.assert_called_once_with(setup_id)
    assert vault_list.call_args_list == [call(cfg), call(cfg)]
    credential_keys.assert_called_once_with(contract)
    vault_update.assert_called_once_with(cfg, host, {"keep": None, "drop": None})

    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list",
        side_effect=[[(host, "unrelated", object())], [(host, "unrelated", object())]],
    ) as vault_list, patch(
        "freq.api.auth.contract_credential_keys", return_value=["missing"]
    ), patch("freq.api.auth.vault_update") as vault_update:
        assert serve._clear_setup_contract_credentials(cfg, contract) is None
    assert vault_list.call_args_list == [call(cfg), call(cfg)]
    vault_update.assert_not_called()

    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list", return_value=first_snapshot
    ) as vault_list, patch(
        "freq.api.auth.contract_credential_keys", return_value=["drop"]
    ), patch("freq.api.auth.vault_update", return_value=False):
        with pytest.raises(OSError, match="^setup credential cleanup failed$"):
            serve._clear_setup_contract_credentials(cfg, contract)
    vault_list.assert_called_once_with(cfg)

    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list",
        side_effect=[first_snapshot, [(host, "drop", drop_value)]],
    ) as vault_list, patch(
        "freq.api.auth.contract_credential_keys", return_value=["drop"]
    ), patch("freq.api.auth.vault_update", return_value=True):
        with pytest.raises(OSError, match="^setup credential cleanup failed$"):
            serve._clear_setup_contract_credentials(cfg, contract)
    assert vault_list.call_args_list == [call(cfg), call(cfg)]

    namespace_error = RuntimeError("namespace failed")
    with patch(
        "freq.api.auth._setup_vault_host", side_effect=namespace_error
    ), patch("freq.api.auth.vault_list") as vault_list, patch(
        "freq.api.auth.contract_credential_keys"
    ) as credential_keys, patch("freq.api.auth.vault_update") as vault_update:
        with pytest.raises(RuntimeError) as caught:
            serve._clear_setup_contract_credentials(cfg, contract)
    assert caught.value is namespace_error
    vault_list.assert_not_called()
    credential_keys.assert_not_called()
    vault_update.assert_not_called()

    list_error = OSError("verification snapshot failed")
    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list", side_effect=[first_snapshot, list_error]
    ) as vault_list, patch(
        "freq.api.auth.contract_credential_keys", return_value=["drop"]
    ), patch("freq.api.auth.vault_update", return_value=True):
        with pytest.raises(OSError) as caught:
            serve._clear_setup_contract_credentials(cfg, contract)
    assert caught.value is list_error
    assert vault_list.call_args_list == [call(cfg), call(cfg)]


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
        with open(contract_path) as handle:
            serialized = handle.read()
        assert "secret" not in serialized
        assert os.stat(contract_path).st_mode & 0o777 == 0o600
        assert os.stat(os.path.dirname(contract_path)).st_mode & 0o777 == 0o700
        _assert_setup_contract_get_resolution_contract(
            cfg,
            load_setup_state(cfg),
            load_setup_contract(cfg),
        )


def _assert_setup_contract_get_resolution_contract(cfg, state, contract):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_resolve_setup_contract_get"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "resolve_setup_contract_get"
        for node in service_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module == "freq.modules" or (node.module or "").startswith("freq.modules."))
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name == "freq.modules" or alias.name.startswith("freq.modules.")
                for alias in node.names
            )
        )
        for node in ast.walk(service_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resolve_setup_contract_get"
        for node in ast.walk(serve_tree)
    ) == 1
    assert serve._resolve_setup_contract_get is setup_progress.resolve_setup_contract_get
    assert setup_progress.SetupContractGetResolution.__dataclass_params__.frozen is True

    def invoke(candidate):
        handler = _handler(path="/api/setup/contract", command="GET")

        def private_getter(_key):
            return "private-credential-value"

        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve.load_setup_state", return_value=state),
            patch("freq.modules.serve.load_setup_contract", return_value=candidate) as read_contract,
            patch(
                "freq.modules.serve._setup_contract_getter",
                return_value=private_getter,
            ) as build_getter,
            patch(
                "freq.modules.serve.contract_payload",
                wraps=contract_payload,
            ) as project_contract,
        ):
            handler._serve_setup_contract()
        return handler, read_contract, build_getter, project_contract

    for candidate in (
        None,
        {**contract, "setup_id": "other-setup"},
        {**contract, "contract_id": "other-contract"},
    ):
        handler, read_contract, build_getter, project_contract = invoke(candidate)
        assert handler._status_code == 404
        assert handler._captured["error"]["code"] == "contract_not_found"
        read_contract.assert_called_once_with(cfg)
        build_getter.assert_not_called()
        project_contract.assert_not_called()

    handler, read_contract, build_getter, project_contract = invoke(contract)
    private_getter = build_getter.return_value
    assert handler._status_code == 200
    assert handler._captured == {
        "ok": True,
        "schema": SCHEMA,
        "contract": contract_payload(contract, private_getter),
    }
    assert "private-credential-value" not in str(handler._captured)
    assert "stored_fields" in str(handler._captured)
    read_contract.assert_called_once_with(cfg)
    build_getter.assert_called_once_with(cfg, state["setup_id"])
    project_contract.assert_called_once_with(contract, private_getter)


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
        _assert_setup_contract_post_admission_contract(
            cfg,
            load_setup_state(cfg),
            discovery,
            body,
            load_setup_contract(cfg),
        )


def _assert_setup_contract_post_admission_contract(cfg, state, discovery, body, previous):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_admit_setup_contract"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "admit_setup_contract"
        for node in service_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module == "freq.modules" or (node.module or "").startswith("freq.modules."))
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name == "freq.modules" or alias.name.startswith("freq.modules.")
                for alias in node.names
            )
        )
        for node in ast.walk(service_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_admit_setup_contract"
        for node in ast.walk(serve_tree)
    ) == 1
    assert serve._admit_setup_contract.func is setup_progress.admit_setup_contract
    assert (
        serve._admit_setup_contract.keywords["runtime"]
        is serve._setup_contract_admission_runtime
    )
    assert setup_progress.SetupContractAdmissionRuntime.__dataclass_params__.frozen is True
    assert setup_progress.SetupContractAdmissionResult.__dataclass_params__.frozen is True

    built = {
        **previous,
        "contract_id": "replacement-contract",
        "client_request_id": "replacement-request",
    }
    projected = {"id": "projected-contract", "ready": False, "stored_fields": []}

    def invoke(*, current_state=state, snapshot=discovery, prior=previous, request=body):
        handler = _handler(request)

        def private_getter(_key):
            return "private-admission-value"

        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve.load_setup_state", return_value=state),
            patch("freq.modules.serve._observe_setup_state", return_value=current_state) as observe_state,
            patch("freq.modules.serve._setup_discovery_snapshot", return_value=snapshot) as read_discovery,
            patch("freq.modules.serve.load_setup_contract", return_value=prior) as read_contract,
            patch("freq.modules.serve._retire_setup_contract") as retire_contract,
            patch("freq.modules.serve.build_setup_contract", return_value=built) as build_contract,
            patch("freq.modules.serve.contract_credential_keys", return_value=[]),
            patch("freq.modules.serve._setup_vault_host", return_value="setup:admission"),
            patch("freq.modules.serve.vault_list", return_value=[]),
            patch("freq.modules.serve.save_setup_contract") as save_contract,
            patch(
                "freq.modules.serve._setup_contract_getter",
                return_value=private_getter,
            ) as build_getter,
            patch(
                "freq.modules.serve.contract_payload",
                return_value=projected,
            ) as project_contract,
            patch("freq.modules.serve.update_setup_state") as update_state,
        ):
            handler._serve_setup_contract()
        return SimpleNamespace(
            handler=handler,
            observe_state=observe_state,
            read_discovery=read_discovery,
            read_contract=read_contract,
            retire_contract=retire_contract,
            build_contract=build_contract,
            save_contract=save_contract,
            build_getter=build_getter,
            project_contract=project_contract,
            update_state=update_state,
            private_getter=private_getter,
        )

    lost = invoke(current_state=None)
    assert lost.handler._status_code == 410
    assert lost.handler._captured["error"]["code"] == "setup_expired"
    lost.read_discovery.assert_not_called()
    lost.read_contract.assert_not_called()

    wrong_owner = invoke(current_state={**state, "username": "other-operator"})
    assert wrong_owner.handler._status_code == 403
    assert wrong_owner.handler._captured["error"]["code"] == "setup_owner_mismatch"
    wrong_owner.read_discovery.assert_not_called()
    wrong_owner.read_contract.assert_not_called()

    for stale in (
        None,
        {**discovery, "state": "running"},
        {**discovery, "id": "other-discovery"},
    ):
        rejected = invoke(snapshot=stale)
        assert rejected.handler._status_code == 409
        assert rejected.handler._captured["error"]["code"] == "stale_discovery"
        assert rejected.handler._captured["error"]["field"] == "discovery_id"
        rejected.read_contract.assert_not_called()
        rejected.build_contract.assert_not_called()

    for stale_previous in (
        {**previous, "setup_id": "other-setup"},
        {**previous, "discovery_id": "other-discovery"},
    ):
        replaced = invoke(prior=stale_previous)
        replaced.retire_contract.assert_called_once_with(cfg, stale_previous)
        replaced.build_contract.assert_called_once_with(
            body,
            discovery,
            setup_id=state["setup_id"],
            previous={},
        )
        replaced.save_contract.assert_called_once_with(cfg, built)
        replaced.update_state.assert_called_once()

    replayed = invoke()
    assert replayed.handler._status_code == 200
    assert replayed.handler._captured == {
        "ok": True,
        "schema": SCHEMA,
        "contract": projected,
    }
    replayed.observe_state.assert_called_once_with(cfg)
    replayed.read_discovery.assert_called_once_with()
    replayed.read_contract.assert_called_once_with(cfg)
    replayed.retire_contract.assert_not_called()
    replayed.build_contract.assert_not_called()
    replayed.save_contract.assert_not_called()
    replayed.update_state.assert_not_called()
    replayed.build_getter.assert_called_once_with(cfg, state["setup_id"])
    replayed.project_contract.assert_called_once_with(previous, replayed.private_getter)
    assert "private-admission-value" not in str(replayed.handler._captured)

    non_replays = (
        {**body, "client_request_id": ""},
        {**body, "schema": "other-schema"},
        {**body, "setup_id": "other-setup"},
        {**body, "discovery_id": "other-discovery"},
    )
    for changed_body in non_replays:
        admitted = invoke(request=changed_body)
        admitted.retire_contract.assert_not_called()
        admitted.build_contract.assert_called_once_with(
            changed_body,
            discovery,
            setup_id=state["setup_id"],
            previous=previous,
        )
        admitted.save_contract.assert_called_once_with(cfg, built)
        admitted.update_state.assert_called_once()


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
        _assert_setup_device_credentials_admission_contract(
            cfg,
            load_setup_state(cfg),
            load_setup_contract(cfg),
            credentials,
        )


def _assert_setup_device_credentials_admission_contract(cfg, state, contract, body):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_admit_setup_device_credentials"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef)
        and node.name == "admit_setup_device_credentials"
        for node in service_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module == "freq.modules" or (node.module or "").startswith("freq.modules."))
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name == "freq.modules" or alias.name.startswith("freq.modules.")
                for alias in node.names
            )
        )
        for node in ast.walk(service_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_admit_setup_device_credentials"
        for node in ast.walk(serve_tree)
    ) == 1
    assert (
        serve._admit_setup_device_credentials.func
        is setup_progress.admit_setup_device_credentials
    )
    assert (
        serve._admit_setup_device_credentials.keywords["runtime"]
        is serve._setup_device_credential_admission_runtime
    )
    assert (
        setup_progress.SetupDeviceCredentialAdmissionRuntime.__dataclass_params__.frozen
        is True
    )
    assert (
        setup_progress.SetupDeviceCredentialAdmissionResult.__dataclass_params__.frozen
        is True
    )

    resource_id = "device:truenas:10.0.0.10"
    username_key = f"{resource_id}|username"
    password_key = f"{resource_id}|password"
    host = f"setup:{state['setup_id']}"
    normalized = {
        "client_request_id": REQUEST_ID,
        "credentials": [
            {
                "resource_id": resource_id,
                "values": {
                    "username": "new-user",
                    "password": "new-password",
                },
            }
        ],
    }
    projected = [
        {
            "resource_id": resource_id,
            "stored_fields": ["password", "username"],
            "complete": True,
        }
    ]
    updates = {
        username_key: "stored:username:new-user",
        password_key: "stored:password:new-password",
    }
    before_values = [
        (host, username_key, "old-user"),
        ("setup:other", password_key, "other-secret"),
    ]
    verified_values = [(host, key, value) for key, value in sorted(updates.items())]

    def invoke(
        *,
        current_state=state,
        prior=contract,
        request=body,
        vault_exists=True,
        init_ok=True,
        verify=True,
        presence=projected,
    ):
        handler = _handler(request, path="/api/setup/device-credentials")

        def private_getter(_key):
            return "private-device-value"

        lists = [before_values, verified_values if verify else []]
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._observe_setup_state", return_value=state),
            patch("freq.modules.serve.load_setup_state", return_value=current_state) as read_state,
            patch("freq.modules.serve.load_setup_contract", return_value=prior) as read_contract,
            patch(
                "freq.modules.serve.validate_credential_request",
                return_value=normalized,
            ) as validate_request,
            patch("freq.modules.serve.os.path.exists", return_value=vault_exists),
            patch("freq.modules.serve.vault_init", return_value=init_ok) as initialize_vault,
            patch("freq.modules.serve._setup_vault_host", return_value=host) as build_host,
            patch("freq.modules.serve.vault_list", side_effect=lists) as list_values,
            patch("freq.modules.serve.vault_update", return_value=True) as update_vault,
            patch(
                "freq.modules.serve.credential_vault_key",
                side_effect=lambda candidate, field: f"{candidate}|{field}",
            ) as build_key,
            patch(
                "freq.modules.serve.credential_storage_value",
                side_effect=lambda field, value: f"stored:{field}:{value}",
            ) as store_value,
            patch("freq.modules.serve.record_credential_request") as record_request,
            patch("freq.modules.serve.save_setup_contract") as save_contract,
            patch(
                "freq.modules.serve._setup_contract_getter",
                return_value=private_getter,
            ) as build_getter,
            patch(
                "freq.modules.serve.credential_presence",
                return_value=presence,
            ) as project_presence,
            patch("freq.modules.serve.update_setup_state") as update_state,
        ):
            handler._serve_setup_device_credentials()
        return SimpleNamespace(
            handler=handler,
            read_state=read_state,
            read_contract=read_contract,
            validate_request=validate_request,
            initialize_vault=initialize_vault,
            build_host=build_host,
            list_values=list_values,
            update_vault=update_vault,
            build_key=build_key,
            store_value=store_value,
            record_request=record_request,
            save_contract=save_contract,
            build_getter=build_getter,
            project_presence=project_presence,
            update_state=update_state,
            private_getter=private_getter,
        )

    lost = invoke(current_state=None)
    assert lost.handler._status_code == 410
    assert lost.handler._captured["error"]["code"] == "setup_expired"
    lost.validate_request.assert_not_called()
    lost.update_vault.assert_not_called()

    wrong_owner = invoke(current_state={**state, "username": "other-operator"})
    assert wrong_owner.handler._status_code == 403
    assert wrong_owner.handler._captured["error"]["code"] == "setup_owner_mismatch"
    wrong_owner.validate_request.assert_not_called()
    wrong_owner.update_vault.assert_not_called()

    for stale in (
        None,
        {**contract, "setup_id": "other-setup"},
        {**contract, "contract_id": "other-contract"},
    ):
        rejected = invoke(prior=stale)
        assert rejected.handler._status_code == 409
        assert rejected.handler._captured["error"]["code"] == "stale_contract"
        assert rejected.handler._captured["error"]["field"] == "contract_id"
        rejected.validate_request.assert_not_called()
        rejected.update_vault.assert_not_called()

    replay_contract = {**contract, "credential_request_ids": [REQUEST_ID]}
    replayed = invoke(prior=replay_contract)
    assert replayed.handler._status_code == 200
    assert replayed.handler._captured == {
        "ok": True,
        "schema": SCHEMA,
        "contract_id": replay_contract["contract_id"],
        "credentials": projected,
        "ready": True,
    }
    replayed.read_state.assert_called_once_with(cfg)
    replayed.read_contract.assert_called_once_with(cfg)
    replayed.validate_request.assert_called_once_with(body, replay_contract, state["setup_id"])
    replayed.initialize_vault.assert_not_called()
    replayed.list_values.assert_not_called()
    replayed.update_vault.assert_not_called()
    replayed.record_request.assert_not_called()
    replayed.save_contract.assert_not_called()
    replayed.build_getter.assert_called_once_with(cfg, state["setup_id"])
    replayed.project_presence.assert_called_once_with(
        replay_contract,
        replayed.private_getter,
    )
    replayed.update_state.assert_called_once_with(
        cfg,
        phase="ready",
        active_contract_id=replay_contract["contract_id"],
        last_error_code=None,
    )
    assert "private-device-value" not in str(replayed.handler._captured)

    fresh_contract = {**contract, "credential_request_ids": []}
    admitted = invoke(prior=fresh_contract, vault_exists=False)
    assert admitted.handler._status_code == 200
    assert admitted.handler._captured == {
        "ok": True,
        "schema": SCHEMA,
        "contract_id": fresh_contract["contract_id"],
        "credentials": projected,
        "ready": True,
    }
    admitted.initialize_vault.assert_called_once_with(cfg)
    admitted.build_host.assert_called_once_with(state["setup_id"])
    assert admitted.build_key.call_args_list == [
        call(resource_id, "username"),
        call(resource_id, "password"),
    ]
    assert admitted.store_value.call_args_list == [
        call("username", "new-user"),
        call("password", "new-password"),
    ]
    assert admitted.list_values.call_args_list == [call(cfg), call(cfg)]
    admitted.update_vault.assert_called_once_with(cfg, host, updates)
    admitted.record_request.assert_called_once_with(fresh_contract, REQUEST_ID)
    admitted.save_contract.assert_called_once_with(cfg, fresh_contract)
    admitted.build_getter.assert_called_once_with(cfg, state["setup_id"])
    admitted.project_presence.assert_called_once_with(
        fresh_contract,
        admitted.private_getter,
    )
    admitted.update_state.assert_called_once_with(
        cfg,
        phase="ready",
        active_contract_id=fresh_contract["contract_id"],
        last_error_code=None,
    )
    assert "new-password" not in str(admitted.handler._captured)

    init_failed = invoke(prior=fresh_contract, vault_exists=False, init_ok=False)
    assert init_failed.handler._status_code == 500
    assert init_failed.handler._captured["error"]["code"] == "credential_store_failed"
    init_failed.list_values.assert_not_called()
    init_failed.update_vault.assert_not_called()
    init_failed.save_contract.assert_not_called()

    verify_failed = invoke(prior=fresh_contract, verify=False)
    assert verify_failed.handler._status_code == 500
    assert verify_failed.handler._captured["error"]["code"] == "credential_store_failed"
    assert verify_failed.update_vault.call_args_list == [
        call(cfg, host, updates),
        call(cfg, host, {username_key: "old-user", password_key: None}),
    ]
    verify_failed.record_request.assert_not_called()
    verify_failed.save_contract.assert_called_once_with(cfg, fresh_contract)
    verify_failed.update_state.assert_not_called()
    assert "new-password" not in str(verify_failed.handler._captured)


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
        with patch("freq.api.auth.load_setup_state", return_value={"username": "operator", "setup_id": "setup"}):
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


def _assert_setup_contract_retirement_order_contract():
    serve_tree = ast.parse(inspect.getsource(serve))
    auth_tree = ast.parse(inspect.getsource(auth))

    def function(name, *, class_name=None):
        body = serve_tree.body
        if class_name is not None:
            class_node = next(
                node
                for node in body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            )
            body = class_node.body
        return next(
            node
            for node in body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )

    retirement = next(
        node
        for node in auth_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_retire_setup_contract"
    )
    retirement_calls = [
        node.func.id
        for node in ast.walk(retirement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert retirement_calls == [
        "_clear_setup_contract_credentials",
        "clear_setup_contract",
    ]
    assert serve._retire_setup_contract is auth._retire_setup_contract

    service_tree = ast.parse(inspect.getsource(setup_progress))
    discovery_worker = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_setup_discovery_job"
    )
    discovery_retire_calls = [
        node
        for node in ast.walk(discovery_worker)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func) == "runtime.retire_contract"
    ]
    assert len(discovery_retire_calls) == 1

    contract_admission = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "admit_setup_contract"
    )
    admission_retire_calls = [
        node
        for node in ast.walk(contract_admission)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func) == "runtime.retire_contract"
    ]
    assert len(admission_retire_calls) == 1

    reset_scope = function("_serve_setup_reset", class_name="FreqHandler")
    reset_retire_calls = [
        node
        for node in ast.walk(reset_scope)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_retire_setup_contract"
    ]
    assert len(reset_retire_calls) == 1
    contract_scope = function("_serve_setup_contract", class_name="FreqHandler")
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_retire_setup_contract"
        for node in ast.walk(contract_scope)
    )


def test_reset_removes_setup_contract_and_exact_namespace_secrets():
    _assert_setup_contract_credential_cleanup_contract()
    _assert_setup_contract_retirement_order_contract()
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

    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state, discovery = _setup_handler_state(cfg)
        contract = build_setup_contract(
            _contract_body(setup_id=state["setup_id"], discovery_id=discovery["id"]),
            discovery,
            setup_id=state["setup_id"],
        )
        save_setup_contract(cfg, contract)
        cleanup_error = OSError("contract credentials remain")
        clear_contract = patch("freq.api.auth.clear_setup_contract")
        handler = _handler({}, path="/api/setup/reset")
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_init_snapshot", return_value={"running": False, "job": None}),
            patch(
                "freq.api.auth._clear_setup_contract_credentials",
                side_effect=cleanup_error,
            ),
            clear_contract as clear_contract_mock,
        ):
            handler._serve_setup_reset()

        assert handler._status_code == 500
        assert handler._captured["error"] == f"Failed to reset setup: {cleanup_error}"
        clear_contract_mock.assert_not_called()
        assert load_setup_contract(cfg) == contract
