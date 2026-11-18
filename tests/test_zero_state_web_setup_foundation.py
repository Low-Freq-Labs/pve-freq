import os
import contextlib
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.core.setup_state import (
    SCHEMA,
    SETUP_TTL_SECONDS,
    ensure_setup_state,
    load_setup_state,
    setup_state_path,
    touch_setup_state,
    update_setup_state,
)
from freq.modules.serve import FreqHandler


def _cfg(root):
    return SimpleNamespace(
        data_dir=os.path.join(root, "data"),
        conf_dir=os.path.join(root, "conf"),
        vault_dir=os.path.join(root, "vault"),
        vault_file=os.path.join(root, "vault", "vault.enc"),
    )


def _handler(body=None, command="POST"):
    handler = FreqHandler.__new__(FreqHandler)
    handler.command = command
    handler.client_address = ("192.0.2.44", 40444)
    handler.headers = {"Content-Type": "application/json"}
    handler._request_body = lambda: dict(body or {})
    handler._captured = None
    handler._status_code = None

    def respond(payload, status=200):
        handler._captured = payload
        handler._status_code = status

    handler._json_response = respond
    return handler


def _create_handler(body):
    complete = {
        "schema": SCHEMA,
        "username": "operator",
        "password": "password-123",
        "claim_secret": "legacy-regression-claim",
        "client_request_id": "12345678-1234-4123-8123-123456789abc",
        **body,
    }
    return _handler(complete)


@pytest.fixture(autouse=True)
def _accepted_first_admin_claim_gate():
    @contextlib.contextmanager
    def available_claim(_cfg):
        yield SimpleNamespace(
            state_name="available",
            claim_id="legacy-regression-fixture",
            matches=lambda _candidate: True,
            consume=lambda: None,
        )

    with patch(
        "freq.modules.serve.locked_first_admin_claim",
        side_effect=available_claim,
    ):
        yield


def _assert_forbidden_browser_input_contract():
    import ast
    import inspect

    from freq.modules import serve
    from freq.services import setup_inputs

    _setup_forbidden_browser_input = serve._setup_forbidden_browser_input
    assert _setup_forbidden_browser_input is setup_inputs.forbidden_browser_input
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_setup_forbidden_browser_input"
        for node in ast.walk(ast.parse(inspect.getsource(serve)))
    )
    assert inspect.getsource(serve).count("_setup_forbidden_browser_input(body)") == 5
    assert "freq.modules" not in inspect.getsource(setup_inputs)

    clear = ("", "")
    assert _setup_forbidden_browser_input(None) == clear
    assert _setup_forbidden_browser_input([]) == clear
    assert _setup_forbidden_browser_input([{"secret_path": "ignored"}]) == clear
    assert _setup_forbidden_browser_input({}) == clear
    assert _setup_forbidden_browser_input({"safe": {"value": 1}}) == clear
    assert _setup_forbidden_browser_input({"safe": ({"secret_path": "ignored"},)}) == clear

    manual_fields = (
        "hosts_file",
        "hosts_import",
        "vm_contract",
        "owned_vmids",
        "template_vmids",
        "acknowledged_out_of_contract_vmids",
        "core_devices",
        "lab_devices",
        "subnet",
        "subnets",
        "toml",
    )
    for key in manual_fields:
        assert _setup_forbidden_browser_input({key: None}) == (
            key,
            "manual_contract_not_allowed",
        )
        decorated = f" {key.upper()} "
        assert _setup_forbidden_browser_input({decorated: False}) == (
            decorated,
            "manual_contract_not_allowed",
        )

    assert _setup_forbidden_browser_input({"hosts_file": "ignored"}) == (
        "hosts_file",
        "manual_contract_not_allowed",
    )
    assert _setup_forbidden_browser_input({"credential_file": "ignored"}) == (
        "credential_file",
        "path_input_not_allowed",
    )
    assert _setup_forbidden_browser_input({" Secret_Path ": "ignored"}) == (
        " Secret_Path ",
        "path_input_not_allowed",
    )
    assert _setup_forbidden_browser_input(
        {
            "safe": {
                "first": [
                    {"nested_path": None},
                    {"toml": None},
                ]
            },
            "later_file": None,
        }
    ) == ("safe.first[0].nested_path", "path_input_not_allowed")
    assert _setup_forbidden_browser_input(
        {"first": {"subnets": []}, "second": {"secret_path": "ignored"}}
    ) == ("first.subnets", "manual_contract_not_allowed")


def _assert_setup_error_contract():
    """Own the setup error-envelope adapter after relocation."""
    import ast
    import inspect
    from unittest.mock import Mock

    from freq.api import helpers
    from freq.modules import serve

    serve_tree = ast.parse(inspect.getsource(serve))
    helper_tree = ast.parse(inspect.getsource(helpers.setup_error))
    assert serve._setup_error is helpers.setup_error
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_setup_error"
        for node in ast.walk(serve_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_error"
        for node in ast.walk(serve_tree)
    ) == 102
    assert not any(
        isinstance(node, ast.ImportFrom)
        and str(node.module or "").startswith("freq.modules")
        for node in ast.walk(helper_tree)
    )

    handler = SimpleNamespace(_json_response=Mock())
    code = object()
    message = object()
    assert serve._setup_error(handler, 418, code, message) is None
    handler._json_response.assert_called_once()
    payload, status = handler._json_response.call_args.args
    assert status == 418
    assert payload == {
        "ok": False,
        "schema": SCHEMA,
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
        },
    }
    assert payload["error"]["code"] is code
    assert payload["error"]["message"] is message

    details = list(range(60))
    handler = SimpleNamespace(_json_response=Mock())
    retryable = object()
    assert serve._setup_error(
        handler,
        422,
        "invalid_contract",
        "The contract is invalid.",
        field="selection.devices[0]",
        retryable=retryable,
        details=details,
    ) is None
    handler._json_response.assert_called_once_with(
        {
            "ok": False,
            "schema": SCHEMA,
            "error": {
                "code": "invalid_contract",
                "message": "The contract is invalid.",
                "retryable": True,
                "field": "selection.devices[0]",
                "details": list(range(50)),
            },
        },
        422,
    )
    rich_payload = handler._json_response.call_args.args[0]
    assert rich_payload["error"]["details"] is not details
    assert details == list(range(60))

    class BrokenDetails:
        def __iter__(self):
            raise RuntimeError("details unavailable")

    handler = SimpleNamespace(_json_response=Mock())
    with pytest.raises(RuntimeError, match="details unavailable"):
        serve._setup_error(
            handler,
            400,
            "invalid_details",
            "Invalid details.",
            details=BrokenDetails(),
        )
    handler._json_response.assert_not_called()

    handler = SimpleNamespace(
        _json_response=Mock(side_effect=RuntimeError("response unavailable"))
    )
    with pytest.raises(RuntimeError, match="response unavailable"):
        serve._setup_error(
            handler,
            503,
            "response_failed",
            "Response failed.",
            field="",
            details=[],
        )
    handler._json_response.assert_called_once_with(
        {
            "ok": False,
            "schema": SCHEMA,
            "error": {
                "code": "response_failed",
                "message": "Response failed.",
                "retryable": False,
            },
        },
        503,
    )


def _assert_setup_session_payload_contract():
    import ast
    import inspect

    from freq.api import auth
    from freq.modules import serve

    _setup_session_payload = serve._setup_session_payload
    assert _setup_session_payload is auth.setup_session_payload
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_setup_session_payload"
        for node in ast.walk(ast.parse(inspect.getsource(serve)))
    )
    assert inspect.getsource(serve).count("_setup_session_payload(") == 1
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "freq.api.auth"
        for node in ast.walk(ast.parse(inspect.getsource(auth.setup_session_payload)))
    )

    class ObservedLock:
        def __init__(self):
            self.active = False
            self.entries = 0
            self.exits = 0

        def __enter__(self):
            assert not self.active
            self.active = True
            self.entries += 1

        def __exit__(self, exc_type, exc, tb):
            self.active = False
            self.exits += 1

    class ObservedTokens(dict):
        def __init__(self, lock, *args, **kwargs):
            self.lock = lock
            super().__init__(*args, **kwargs)

        def get(self, key, default=None):
            assert self.lock.active
            return super().get(key, default)

    handler = object()
    lock = ObservedLock()
    tokens = ObservedTokens(lock, {"session-token": {"csrf_token": "csrf-value"}})
    with (
        patch("freq.api.auth.establish_session", return_value="session-token") as establish,
        patch("freq.api.auth._auth_lock", lock),
        patch("freq.api.auth._auth_tokens", tokens),
    ):
        payload = _setup_session_payload(handler, "operator")
    establish.assert_called_once_with(handler, "operator", "admin")
    assert payload == {
        "ok": True,
        "user": "operator",
        "role": "admin",
        "session_started": True,
        "csrf_token": "csrf-value",
        "auth_mode": "cookie",
    }
    assert "session-token" not in payload.values()
    assert (lock.entries, lock.exits, lock.active) == (1, 1, False)

    for token_state in ({}, {"session-token": {}}):
        lock = ObservedLock()
        tokens = ObservedTokens(lock, token_state)
        marker = object()
        with (
            patch("freq.api.auth.establish_session", return_value="session-token"),
            patch("freq.api.auth._auth_lock", lock),
            patch("freq.api.auth._auth_tokens", tokens),
        ):
            payload = _setup_session_payload(
                handler,
                "operator",
                ok=False,
                user="override-user",
                session_started=False,
                csrf_token="override-csrf",
                auth_mode="override-mode",
                marker=marker,
            )
        assert payload == {
            "ok": False,
            "user": "override-user",
            "role": "admin",
            "session_started": False,
            "csrf_token": "override-csrf",
            "auth_mode": "override-mode",
            "marker": marker,
        }
        assert payload["marker"] is marker
        assert (lock.entries, lock.exits, lock.active) == (1, 1, False)

    lock = ObservedLock()
    with (
        patch("freq.api.auth.establish_session", side_effect=RuntimeError("session failed")),
        patch("freq.api.auth._auth_lock", lock),
    ):
        with pytest.raises(RuntimeError, match="session failed"):
            _setup_session_payload(handler, "operator", "viewer")
    assert (lock.entries, lock.exits, lock.active) == (0, 0, False)


def test_setup_state_is_durable_private_and_stable():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        first = ensure_setup_state(cfg, "operator", now=1000)
        second = ensure_setup_state(cfg, "operator", now=1100)

        assert first["schema"] == SCHEMA
        assert first["setup_id"] == second["setup_id"]
        assert first["phase"] == "collecting"
        assert os.stat(setup_state_path(cfg)).st_mode & 0o777 == 0o600


def test_setup_state_touch_extends_ttl_and_expiry_deletes_state():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator", now=1000)
        touched = touch_setup_state(cfg, now=1200)
        assert touched["setup_id"] == state["setup_id"]
        assert touched["last_activity_at"] == 1200

        assert load_setup_state(cfg, now=1200 + SETUP_TTL_SECONDS - 1)
        assert load_setup_state(cfg, now=1200 + SETUP_TTL_SECONDS + 1) == {}
        assert not os.path.exists(setup_state_path(cfg))


def test_setup_state_rejects_unknown_phase_and_fields():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        ensure_setup_state(cfg, "operator", now=1000)
        with pytest.raises(ValueError, match="invalid setup phase"):
            update_setup_state(cfg, now=1001, phase="complete")
        with pytest.raises(ValueError, match="unsupported setup state fields"):
            update_setup_state(cfg, now=1001, secret="must-not-land")


def test_create_admin_refuses_cleartext_transport():
    _assert_setup_error_contract()
    handler = _create_handler({})
    with patch("freq.modules.serve._request_is_https", return_value=False):
        handler._serve_setup_create_admin()

    assert handler._status_code == 403
    assert handler._captured["error"]["code"] == "https_required"


def test_create_admin_rejects_server_path_before_reading_it():
    _assert_forbidden_browser_input_contract()
    handler = _create_handler({
        "password_file": "/root/operator-password",
    })
    with patch("freq.modules.serve._request_is_https", return_value=True):
        handler._serve_setup_create_admin()

    assert handler._status_code == 400
    assert handler._captured["error"]["code"] == "path_input_not_allowed"
    assert "field" not in handler._captured["error"]


def test_create_admin_existing_user_is_not_a_password_resume():
    handler = _create_handler({})
    cfg = _cfg("/unused")
    with (
        patch("freq.modules.serve._request_is_https", return_value=True),
        patch("freq.modules.serve.load_config", return_value=cfg),
        patch("freq.modules.serve._load_users", return_value=[{"username": "operator", "role": "admin"}]),
        patch("freq.modules.serve._setup_marker_exists", return_value=False),
        patch("freq.modules.serve._setup_store_admin_password") as store,
    ):
        handler._serve_setup_create_admin()

    assert handler._status_code == 409
    assert handler._captured["error"]["code"] == "operator_exists"
    store.assert_not_called()


def test_create_admin_complete_install_is_closed():
    handler = _create_handler({})
    cfg = _cfg("/unused")
    with (
        patch("freq.modules.serve._request_is_https", return_value=True),
        patch("freq.modules.serve.load_config", return_value=cfg),
        patch("freq.modules.serve._load_users", return_value=[{"username": "operator", "role": "admin"}]),
        patch("freq.modules.serve._setup_marker_exists", return_value=True),
    ):
        handler._serve_setup_create_admin()

    assert handler._status_code == 403
    assert handler._captured["error"]["code"] == "setup_closed"


def test_create_admin_returns_setup_identity_and_collecting_state():
    _assert_setup_session_payload_contract()
    with tempfile.TemporaryDirectory() as root:
        handler = _create_handler({})
        cfg = _cfg(root)

        def session_payload(_handler, username, role, **extra):
            return {"ok": True, "user": username, "role": role, **extra}

        with (
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._load_users", side_effect=[[], []]),
            patch("freq.modules.serve._setup_store_admin_password", return_value=""),
            patch("freq.modules.serve._save_users_error", return_value=""),
            patch("freq.modules.serve._setup_session_payload", side_effect=session_payload),
        ):
            handler._serve_setup_create_admin()

        assert handler._status_code == 200
        assert handler._captured["schema"] == SCHEMA
        assert handler._captured["state"] == "collecting"
        assert handler._captured["setup_id"]
        assert load_setup_state(cfg)["setup_id"] == handler._captured["setup_id"]


def test_setup_status_public_state_never_exposes_setup_identity():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        cfg.ssh_key_path = ""
        cfg.hosts = []
        cfg.pve_nodes = []
        handler = _handler({}, command="GET")
        with (
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._load_users", return_value=[]),
            patch("freq.modules.serve._check_session_role", return_value=(None, "Authentication required")),
            patch("freq.modules.serve._setup_init_snapshot", return_value={"running": False, "job": None}),
            patch("freq.modules.serve._init_blocker_from_artifacts", return_value=""),
            patch("freq.core.config._detect_ssh_key", return_value=""),
        ):
            handler._serve_setup_status()

        assert handler._captured["schema"] == SCHEMA
        assert handler._captured["state"] == "needs_operator"
        assert handler._captured["setup_id"] is None
        assert handler._captured["next"] == "create_operator"


def test_setup_status_authenticated_operator_gets_durable_collecting_identity():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        cfg.ssh_key_path = ""
        cfg.hosts = []
        cfg.pve_nodes = []
        user = {"username": "operator", "role": "admin"}
        handler = _handler({}, command="GET")

        def authenticated(check_handler, _role):
            check_handler._session_user = "operator"
            return "admin", None

        with (
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._load_users", return_value=[user]),
            patch("freq.modules.serve._check_session_role", side_effect=authenticated),
            patch("freq.modules.serve._setup_init_snapshot", return_value={"running": False, "job": None}),
            patch("freq.modules.serve._init_blocker_from_artifacts", return_value=""),
            patch("freq.modules.serve.vault_get", return_value="stored"),
            patch("freq.core.config._detect_ssh_key", return_value=""),
        ):
            handler._serve_setup_status()

        assert handler._captured["state"] == "collecting"
        assert handler._captured["setup_id"]
        assert handler._captured["next"] == "start_discovery"
        assert load_setup_state(cfg)["setup_id"] == handler._captured["setup_id"]


def test_legacy_complete_endpoint_cannot_write_success():
    handler = _handler({})
    handler._serve_setup_complete()
    assert handler._status_code == 409
    assert handler._captured["error"]["code"] == "legacy_endpoint_disabled"


def test_only_public_setup_mutation_is_create_admin():
    assert "/api/setup/create-admin" in FreqHandler._AUTH_WHITELIST
    assert "/api/setup/status" in FreqHandler._AUTH_WHITELIST
    for route in (
        "/api/setup/configure",
        "/api/setup/generate-key",
        "/api/setup/complete",
        "/api/setup/test-ssh",
        "/api/setup/init/start",
        "/api/setup/reset",
    ):
        assert route not in FreqHandler._AUTH_WHITELIST
        assert route not in FreqHandler._CSRF_EXEMPT
