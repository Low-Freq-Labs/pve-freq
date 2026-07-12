import os
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
    handler.headers = {}
    handler._request_body = lambda: dict(body or {})
    handler._captured = None
    handler._status_code = None

    def respond(payload, status=200):
        handler._captured = payload
        handler._status_code = status

    handler._json_response = respond
    return handler


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
    handler = _handler({"schema": SCHEMA, "username": "operator", "password": "password-123"})
    with patch("freq.modules.serve._request_is_https", return_value=False):
        handler._serve_setup_create_admin()

    assert handler._status_code == 403
    assert handler._captured["error"]["code"] == "https_required"


def test_create_admin_rejects_server_path_before_reading_it():
    handler = _handler({
        "schema": SCHEMA,
        "username": "operator",
        "password_file": "/root/operator-password",
    })
    with patch("freq.modules.serve._request_is_https", return_value=True):
        handler._serve_setup_create_admin()

    assert handler._status_code == 400
    assert handler._captured["error"]["code"] == "path_input_not_allowed"
    assert handler._captured["error"]["field"] == "password_file"


def test_create_admin_existing_user_is_not_a_password_resume():
    handler = _handler({"schema": SCHEMA, "username": "operator", "password": "password-123"})
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
    handler = _handler({"schema": SCHEMA, "username": "operator", "password": "password-123"})
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
    with tempfile.TemporaryDirectory() as root:
        handler = _handler({"schema": SCHEMA, "username": "operator", "password": "password-123"})
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
