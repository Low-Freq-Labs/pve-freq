"""Integrated failing-first owners for the E1 F4 claim boundary.

These nodes complement ``test_e1_f4_claim_contract.py``.  They deliberately
drive shipped handlers, startup, and durable files so a helper or token can
not satisfy a property whose name claims end-to-end enforcement.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import importlib
import io
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.api import auth as auth_mod
from freq.api import helpers as api_helpers
from freq.core.setup_state import SCHEMA
from freq.modules import serve
from freq.modules.serve import FreqHandler
from tests.support.e1_f4_requirement_manifest import (
    CLAIM_GUIDANCE_CONTRACT,
    CONSUMER_BENIGN_MESSAGE_CONTROLS,
    CONSUMER_FORBIDDEN_SHAPE_CONTRACT,
    CONSUMER_INTERNAL_FRAGMENTS,
    CREATE_ADMIN_FAILURE_CONTRACT,
    ERROR_ENVELOPE_BASE_PROPERTIES,
    OPERATOR_EXISTS_GUIDANCE_CONTRACT,
    PUBLIC_ERROR_OUTER_PROPERTIES,
    REQUIREMENTS,
    SETUP_ERROR_HELPER_OUTER_PROPERTIES,
    render_requirement_table,
)
from tests.test_e1_f4_claim_contract import (
    JSON_BODY_ROUTES,
    REPO_ROOT,
    _capturing_handler,
    _cfg,
    _claim_body,
    _prepare_claim,
    _seeded_claim,
)

DESIGN_REQUIREMENT_OWNERS = {item["requirement"]: item["owner"] for item in REQUIREMENTS}


def _claim_module():
    try:
        return importlib.import_module("freq.core.first_admin_claim")
    except ModuleNotFoundError:
        pytest.fail("structural red: freq.core.first_admin_claim is absent")


def _response_code(handler: FreqHandler) -> str:
    payload = handler._captured or {}
    error = payload.get("error") or {}
    return error.get("code", "") if isinstance(error, dict) else ""


def _runtime_patches(cfg, registry, *, save=None, session=None, is_https=True, setup_complete=False):
    """Patch only external persistence/projection seams; keep handler real."""
    if save is None:

        def save(_cfg, users):
            registry[:] = [dict(user) for user in users]
            return ""

    if session is None:
        session = {
            "ok": True,
            "schema": SCHEMA,
            "user": "operator",
            "role": "admin",
            "session_started": True,
            "csrf_token": "csrf",
            "setup_id": "setup-1",
            "state": "collecting",
        }
    stack = contextlib.ExitStack()
    stack.enter_context(patch("freq.modules.serve._request_is_https", return_value=is_https))
    stack.enter_context(patch("freq.modules.serve.load_config", return_value=cfg))
    stack.enter_context(patch("freq.modules.serve._setup_marker_exists", return_value=False))
    stack.enter_context(patch("freq.modules.serve._zero_state_setup_complete", return_value=setup_complete))
    stack.enter_context(
        patch(
            "freq.modules.serve._load_users",
            side_effect=lambda _cfg: [dict(user) for user in registry],
        )
    )
    store = stack.enter_context(patch("freq.modules.serve._setup_store_admin_password", return_value=""))
    stack.enter_context(patch("freq.modules.serve._save_users_error", side_effect=save))
    stack.enter_context(patch("freq.modules.serve.ensure_setup_state", return_value={"setup_id": "setup-1"}))
    project = stack.enter_context(patch("freq.modules.serve._setup_session_payload", return_value=session))
    return stack, store, project


_UNSET_BODY = object()


def _invoke_create(
    cfg,
    registry,
    secret,
    *,
    client="192.0.2.44",
    headers=None,
    body=_UNSET_BODY,
    save=None,
    session=None,
    is_https=True,
    setup_complete=False,
    via_dispatch=False,
):
    request_body = _claim_body(secret) if body is _UNSET_BODY else body
    handler = _capturing_handler(request_body, headers=headers)
    handler.client_address = (client, 40444)
    stack, store, project = _runtime_patches(
        cfg,
        registry,
        save=save,
        session=session,
        is_https=is_https,
        setup_complete=setup_complete,
    )
    with stack:
        if via_dispatch:
            handler.do_POST()
        else:
            handler._serve_setup_create_admin()
    return handler, store, project


def _invoke_lifecycle_create(cfg, registry, secret, **options):
    """Enter the shipped create-admin route for every lifecycle interaction."""
    return _invoke_create(cfg, registry, secret, via_dispatch=True, **options)


def _fresh_limiter():
    limiter_type = getattr(serve, "_FirstAdminClaimRateLimiter", None)
    assert limiter_type is not None, "structural red: integrated claim limiter is absent"
    return limiter_type(clock=lambda: 1000.0)


def test_every_composed_design_requirement_has_an_explicit_owner_node():
    assert DESIGN_REQUIREMENT_OWNERS
    assert len(DESIGN_REQUIREMENT_OWNERS) == len(REQUIREMENTS)
    for item in REQUIREMENTS:
        assert item["requirement"]
        assert item["authority"]
        assert item["owner"] != "UNOWNED" or item["reason"]
    unowned = [item for item in REQUIREMENTS if item["owner"] == "UNOWNED"]
    assert unowned == []
    python_nodes = {name for name, value in globals().items() if name.startswith("test_") and callable(value)}
    from tests import test_e1_f4_claim_contract as core_owners

    python_nodes.update(
        name for name, value in vars(core_owners).items() if name.startswith("test_") and callable(value)
    )
    for owner in DESIGN_REQUIREMENT_OWNERS.values():
        if owner.startswith("test_"):
            assert owner in python_nodes, f"unresolved owner node: {owner}"
        else:
            assert (REPO_ROOT / owner).is_file(), f"unresolved owner artifact: {owner}"
    rendered = render_requirement_table()
    assert rendered.count(" | owned | ") + rendered.count(" | UNOWNED | ") == len(REQUIREMENTS)
    assert f"None — computed from {len(REQUIREMENTS)} enumerated rows with zero `UNOWNED` owners." in rendered


def test_f4_source_scope_keeps_f12_separate():
    f4_final = "9c903387797b631bff274efbb0bf03633bcd8ddd"
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", f4_final, "HEAD"],
        cwd=REPO_ROOT,
        check=False,
    ).returncode == 0
    frozen = {
        "freq/data/web/js/app.js": "298c166bba92494c94558d555a6a9ee697ac275b54b2beaf076df8f1ca596dbf",
        "tests/test_frontend_structure_table.py": "872faa6bb1c0c74d369a59557a9372903fa6bd17453c8411aef1bb8b2a6f7da7",
    }
    for relative, expected in frozen.items():
        source = subprocess.run(
            ["git", "show", f"{f4_final}:{relative}"],
            cwd=REPO_ROOT,
            check=True,
            stdout=subprocess.PIPE,
        ).stdout
        assert hashlib.sha256(source).hexdigest() == expected


@pytest.mark.parametrize("route", sorted(JSON_BODY_ROUTES))
def test_all_twelve_dispatch_routes_project_wrong_media_before_body_or_handler(route):
    class TrackedBody(io.BytesIO):
        touched = False

        def read(self, *args, **kwargs):
            self.touched = True
            return super().read(*args, **kwargs)

    body = TrackedBody(b"{}")
    handler = FreqHandler.__new__(FreqHandler)
    handler.path = route
    handler.command = "POST"
    handler.client_address = ("192.0.2.10", 1234)
    handler.headers = {"Content-Type": "text/plain", "Content-Length": "2"}
    handler.rfile = body
    handler._captured = None
    handler._status_code = None
    mutations = []

    def response(payload, status=200):
        handler._captured = payload
        handler._status_code = status

    def governed_handler(request):
        mutations.append(route)
        request._request_body()
        request._json_response({"ok": True})

    handler._json_response = response
    with (
        patch.object(handler, "_load_routes", return_value={route: governed_handler}),
        patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
        patch("freq.modules.serve._check_csrf", return_value=(True, "")),
    ):
        handler._dispatch()
    assert handler._status_code == 400
    assert _response_code(handler) == "unsupported_media_type"
    assert body.touched is False
    assert mutations == []


def test_every_shipped_parser_caller_sends_json_and_direct_only_routes_have_no_caller():
    from tests.test_setup_schema_table import _js_function

    app_source = (REPO_ROOT / "freq/data/web/js/app.js").read_text(encoding="utf-8")
    setup_source = (REPO_ROOT / "freq/data/web/js/setup.js").read_text(encoding="utf-8")

    app_callers = {
        "doLogin": "fetch(API.AUTH_LOGIN,",
        "_submitChangePassword": "fetch(API.AUTH_CHANGE_PW,",
        "_uiLog": "fetch('/api/ui/event',",
        "_setMediaTags": "_authFetch('/api/media/tags',",
        "ltSaveConfig": "_authFetch(API.LAB_TOOL_SAVE,",
    }
    for caller, endpoint_call in app_callers.items():
        body = _js_function(app_source, caller)
        assert "method:'POST'" in body
        assert "'Content-Type':'application/json'" in body
        assert "JSON.stringify(" in body
        assert body.count(endpoint_call) == 1

    post_json = _js_function(setup_source, "postJson")
    assert "method:'POST'" in post_json
    assert "'Content-Type':'application/json'" in post_json
    assert "body:JSON.stringify(payload)" in post_json
    setup_callers = {
        "createOperator": "postJson(API.createAdmin,",
        "startDiscovery": "postJson(API.discoveryStart,",
        "saveContract": "postJson(API.contract,",
        "saveCredentials": "postJson(API.credentials,",
        "startInit": "postJson(API.initStart,",
        "requestInitCancellation": "postJson(API.initCancel,",
    }
    for caller, endpoint_call in setup_callers.items():
        body = _js_function(setup_source, caller)
        assert body.count("postJson(") == 1
        assert body.count(endpoint_call) == 1

    # Configure is explicitly direct-client-only at this revision.  A shipped
    # caller would have to enter this inventory and prove its media behavior.
    assert "postJson(API.configure" not in setup_source
    assert "/api/setup/configure" not in app_source


SERVER_REQUEST_ID = "0a1b2c3d4e5f"


def _assert_exact_error_object(error, *, code, field, retryable):
    expected_keys = set(ERROR_ENVELOPE_BASE_PROPERTIES)
    if field is not None:
        expected_keys.add("field")
    assert set(error) == expected_keys
    assert error["code"] == code
    assert error["retryable"] is retryable
    assert error.get("field") == field
    assert isinstance(error["message"], str) and error["message"]


def _assert_exact_stable_claim_failure(payload, *, code, field, retryable):
    """Assert the three-key payload passed from setup_error to its adapter."""
    assert set(payload) == set(SETUP_ERROR_HELPER_OUTER_PROPERTIES)
    assert payload["ok"] is False
    assert payload["schema"] == SCHEMA
    _assert_exact_error_object(payload["error"], code=code, field=field, retryable=retryable)


def _serialize_with_real_freq_handler(payload, status):
    """Run the shipped serializer/end-header boundary and return its client bytes."""
    handler = FreqHandler.__new__(FreqHandler)
    handler.path = "/api/setup/create-admin"
    handler.command = "POST"
    handler.client_address = ("192.0.2.44", 40444)
    handler._request_id_header_sent = False
    handler.wfile = io.BytesIO()
    observed_status = []
    observed_headers = []

    def send_response(code, _message=None):
        observed_status.append(code)

    def send_header(name, value):
        observed_headers.append((name, value))

    handler.send_response = send_response
    handler.send_header = send_header
    handler._send_security_headers = lambda: None
    deterministic_uuid = SimpleNamespace(hex=SERVER_REQUEST_ID + "0" * 20)
    with (
        patch.object(serve.uuid, "uuid4", return_value=deterministic_uuid),
        patch("http.server.BaseHTTPRequestHandler.end_headers", autospec=True),
    ):
        FreqHandler._begin_request(handler)
        FreqHandler._json_response(handler, payload, status)

    body = handler.wfile.getvalue()
    headers = {name.lower(): value for name, value in observed_headers}
    assert observed_status == [status]
    assert int(headers["content-length"]) == len(body)
    return json.loads(body), headers


def _assert_exact_public_claim_failure(payload, headers, *, code, field, retryable, client_request_id):
    assert set(payload) == set(PUBLIC_ERROR_OUTER_PROPERTIES)
    assert payload["ok"] is False
    assert payload["schema"] == SCHEMA
    _assert_exact_error_object(payload["error"], code=code, field=field, retryable=retryable)
    request_id = payload["request_id"]
    assert isinstance(request_id, str)
    assert re.fullmatch(r"[0-9a-f]{12}", request_id)
    assert headers["x-request-id"] == request_id
    assert request_id != client_request_id


def test_setup_error_helper_and_real_serializer_have_distinct_complete_layers():
    captured_handler = _capturing_handler({})
    api_helpers.setup_error(
        captured_handler,
        403,
        "claim_secret_invalid",
        "Use the newest first-boot claim.",
        field="claim_secret",
        retryable=True,
    )
    helper_payload = captured_handler._captured
    _assert_exact_stable_claim_failure(
        helper_payload,
        code="claim_secret_invalid",
        field="claim_secret",
        retryable=True,
    )
    wire, headers = _serialize_with_real_freq_handler(helper_payload, 403)
    _assert_exact_public_claim_failure(
        wire,
        headers,
        code="claim_secret_invalid",
        field="claim_secret",
        retryable=True,
        client_request_id="12345678-1234-4123-8123-123456789abc",
    )
    assert set(helper_payload) == set(SETUP_ERROR_HELPER_OUTER_PROPERTIES)
    assert wire["request_id"] == headers["x-request-id"] == SERVER_REQUEST_ID

    removed_adapter_field = copy.deepcopy(wire)
    del removed_adapter_field["request_id"]
    with pytest.raises(AssertionError):
        _assert_exact_public_claim_failure(
            removed_adapter_field,
            headers,
            code="claim_secret_invalid",
            field="claim_secret",
            retryable=True,
            client_request_id="12345678-1234-4123-8123-123456789abc",
        )
    _assert_exact_stable_claim_failure(
        helper_payload,
        code="claim_secret_invalid",
        field="claim_secret",
        retryable=True,
    )

    premature_helper = {**helper_payload, "request_id": SERVER_REQUEST_ID}
    with pytest.raises(AssertionError):
        _assert_exact_stable_claim_failure(
            premature_helper,
            code="claim_secret_invalid",
            field="claim_secret",
            retryable=True,
        )
    premature_wire, premature_headers = _serialize_with_real_freq_handler(premature_helper, 403)
    _assert_exact_public_claim_failure(
        premature_wire,
        premature_headers,
        code="claim_secret_invalid",
        field="claim_secret",
        retryable=True,
        client_request_id="12345678-1234-4123-8123-123456789abc",
    )


@pytest.mark.parametrize(
    ("content_type", "accepted"),
    [
        ("application/json", True),
        ("APPLICATION/JSON; charset=utf-8", True),
        ("Application/Json ; Charset=UTF-8", True),
        (None, False),
        ("application/x-www-form-urlencoded", False),
        ("multipart/form-data; boundary=abc", False),
        ("application/problem+json", False),
        ("text/plain;charset=UTF-8", False),
    ],
)
def test_shared_json_parser_enforces_exact_media_matrix(content_type, accepted):
    class TrackedBody(io.BytesIO):
        touched = False

        def read(self, *args, **kwargs):
            self.touched = True
            return super().read(*args, **kwargs)

    body = TrackedBody(b'{"value":1}')
    handler = FreqHandler.__new__(FreqHandler)
    handler.headers = {"Content-Length": str(len(body.getvalue()))}
    if content_type is not None:
        handler.headers["Content-Type"] = content_type
    handler.rfile = body
    if accepted:
        assert handler._request_body() == {"value": 1}
        assert body.touched is True
    else:
        with pytest.raises(Exception, match="application/json"):
            handler._request_body()
        assert body.touched is False


class _AuthHandler:
    def __init__(self, body, origin):
        self.command = "POST"
        self.client_address = ("192.0.2.10", 1234)
        self.headers = {"Host": "freq.test"}
        if origin is not None:
            self.headers["Origin"] = origin
        self._body = body
        self._json_calls = []
        self._sent_status = None
        self._sent_headers = []
        self.wfile = io.BytesIO()
        self.request = object()

    def _request_body(self):
        return dict(self._body)

    def _json_response(self, payload, status=200):
        self._json_calls.append((payload, status))

    def send_response(self, status):
        self._sent_status = status

    def send_header(self, key, value):
        self._sent_headers.append((key, value))

    def end_headers(self):
        pass


@pytest.mark.parametrize("origin", [None, "http://freq.test", "https://other.invalid", "not-an-origin"])
def test_login_route_requires_matching_origin_before_auth_mutation(origin):
    handler = _AuthHandler({"username": "operator", "password": "password-123"}, origin)
    cfg = SimpleNamespace(ssh_service_account="freq-ops", vault_file="/missing")
    with (
        patch.object(auth_mod, "load_config", return_value=cfg),
        patch.object(auth_mod, "_load_users", return_value=[{"username": "operator", "role": "admin"}]),
        patch.object(auth_mod, "vault_get", return_value="stored"),
        patch.object(auth_mod, "verify_password", return_value=True),
        patch.object(auth_mod, "check_rate_limit", return_value=True),
        patch.object(auth_mod, "record_login_attempt"),
        patch.object(auth_mod, "establish_session", return_value="token") as establish,
    ):
        auth_mod.handle_auth_login(handler)
    assert handler._json_calls
    assert handler._json_calls[-1][1] == 403
    establish.assert_not_called()


def test_login_route_accepts_exact_matching_origin():
    handler = _AuthHandler(
        {"username": "operator", "password": "password-123"},
        "https://freq.test",
    )
    cfg = SimpleNamespace(ssh_service_account="freq-ops", vault_file="/missing")
    with (
        patch.object(auth_mod, "load_config", return_value=cfg),
        patch.object(auth_mod, "_load_users", return_value=[{"username": "operator", "role": "admin"}]),
        patch.object(auth_mod, "vault_get", return_value="stored"),
        patch.object(auth_mod, "verify_password", return_value=True),
        patch.object(auth_mod, "check_rate_limit", return_value=True),
        patch.object(auth_mod, "record_login_attempt"),
        patch.object(auth_mod, "request_is_https", return_value=True),
        patch.object(auth_mod, "establish_session", return_value="token") as establish,
    ):
        auth_mod.handle_auth_login(handler)
    assert handler._sent_status == 200
    establish.assert_called_once()


@pytest.mark.parametrize("origin", [None, "http://freq.test", "https://other.invalid", "not-an-origin"])
def test_logout_route_requires_matching_origin_before_session_mutation(origin):
    handler = _AuthHandler({}, origin)
    sessions = {"token": {"user": "operator", "role": "admin"}}
    with (
        patch.object(auth_mod, "_auth_tokens", sessions),
        patch.object(auth_mod, "_extract_session_token", return_value="token"),
    ):
        auth_mod.handle_auth_logout(handler)
    assert handler._json_calls
    assert handler._json_calls[-1][1] == 403
    assert "token" in sessions


def test_logout_route_accepts_exact_matching_origin_and_invalidates_session():
    handler = _AuthHandler({}, "https://freq.test")
    sessions = {"token": {"user": "operator", "role": "admin"}}
    with (
        patch.object(auth_mod, "_auth_tokens", sessions),
        patch.object(auth_mod, "_extract_session_token", return_value="token"),
        patch.object(auth_mod, "request_is_https", return_value=True),
    ):
        auth_mod.handle_auth_logout(handler)
    assert handler._sent_status == 200
    assert "token" not in sessions


@pytest.mark.parametrize("origin", [None, "https://attacker.invalid"])
def test_correct_claim_succeeds_for_absent_and_hostile_origin(origin):
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        headers = {} if origin is None else {"Origin": origin}
        registry = []
        handler, store, _project = _invoke_create(cfg, registry, secret, headers=headers)
        assert handler._status_code == 200
        assert [user["username"] for user in registry] == ["operator"]
        store.assert_called_once()


def test_same_exact_claim_is_independent_of_host_cookie_client_ip_and_username():
    claim = _claim_module()
    variants = (
        ("freq-a.test", "session=alpha", "192.0.2.10", "operator-a"),
        ("freq-b.invalid:9443", "session=beta", "198.51.100.22", "operator_b"),
        ("[2001:db8::1]:8888", "other=value", "2001:db8::44", "bootstrap-admin"),
    )
    with tempfile.TemporaryDirectory() as root:
        template_cfg = _cfg(str(Path(root, "template")))
        deliveries = []
        _prepare_claim(claim, template_cfg, deliveries)
        assert len(deliveries) == 1
        exact_secret = deliveries[0][1]
        state_bytes = Path(claim.claim_state_path(template_cfg)).read_bytes()

        for index, (host, cookie, client_ip, username) in enumerate(variants):
            cfg = _cfg(str(Path(root, f"variant-{index}")))
            state_path = Path(claim.claim_state_path(cfg))
            state_path.parent.mkdir(parents=True, mode=0o700)
            state_path.write_bytes(state_bytes)
            state_path.chmod(0o600)
            registry = []
            body = {**_claim_body(exact_secret), "username": username}
            handler, store, _project = _invoke_create(
                cfg,
                registry,
                exact_secret,
                client=client_ip,
                headers={"Host": host, "Cookie": cookie},
                body=body,
            )
            assert handler._status_code == 200
            assert [user["username"] for user in registry] == [username]
            store.assert_called_once()


def test_correct_claim_cannot_authorize_cleartext_transport():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        registry = []
        handler = _capturing_handler(_claim_body(secret))
        stack, store, _project = _runtime_patches(cfg, registry)
        with stack, patch("freq.modules.serve._request_is_https", return_value=False):
            handler._serve_setup_create_admin()
        assert handler._status_code == 403
        assert _response_code(handler) == "https_required"
        assert registry == []
        store.assert_not_called()
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "available"
            assert transaction.matches(secret)


def test_persisted_digest_is_exactly_domain_separated_sha256():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        secret = deliveries[0][1]
        state = json.loads(Path(claim.claim_state_path(cfg)).read_text(encoding="utf-8"))
        expected = hashlib.sha256(b"pve-freq-first-admin-claim-v1\0" + secret.encode("utf-8")).hexdigest()
        assert state["digest"] == expected
        assert state["digest"] != hashlib.sha256(secret.encode("utf-8")).hexdigest()


def test_unicode_normalization_forms_remain_distinct_candidates():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        composed = "\u00e9"
        decomposed = "e\u0301"
        assert composed != decomposed
        path = Path(claim.claim_state_path(cfg))
        state = json.loads(path.read_text(encoding="utf-8"))
        state["digest"] = hashlib.sha256(b"pve-freq-first-admin-claim-v1\0" + composed.encode("utf-8")).hexdigest()
        path.write_text(json.dumps(state), encoding="utf-8")
        path.chmod(0o600)
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.matches(composed) is True
            assert transaction.matches(decomposed) is False


@pytest.mark.parametrize(
    "body_mutation",
    [
        ("drop", "schema"),
        ("drop", "username"),
        ("drop", "password"),
        ("drop", "claim_secret"),
        ("drop", "client_request_id"),
        ("set", "claim_secret", ""),
        ("set", "claim_secret", 7),
        ("set", "claim_secret", "x" * 257),
        ("set", "server_path", "/tmp/forbidden"),
        ("set", "extra", True),
    ],
)
def test_invalid_request_shapes_do_not_compare_or_consume_claim(body_mutation):
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        body = _claim_body(secret)
        if body_mutation[0] == "drop":
            body.pop(body_mutation[1])
        else:
            body[body_mutation[1]] = body_mutation[2]
        with patch.object(claim.ClaimTransaction, "matches", wraps=claim.ClaimTransaction.matches) as compare:
            handler, store, _project = _invoke_create(cfg, [], secret, body=body)
        assert handler._status_code == 400
        compare.assert_not_called()
        store.assert_not_called()
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "available"
            assert transaction.matches(secret)


@pytest.mark.parametrize(
    "body",
    [
        ["not", "an", "object"],
        "not-an-object",
        7,
        True,
        None,
        {**_claim_body("candidate"), "schema": 7},
        {**_claim_body("candidate"), "username": ["operator"]},
        {**_claim_body("candidate"), "password": {"value": "password-123"}},
        {**_claim_body("candidate"), "client_request_id": 7},
    ],
)
def test_non_object_and_wrong_field_types_fail_before_compare(body):
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        if isinstance(body, dict) and body.get("claim_secret") == "candidate":
            body = {**body, "claim_secret": secret}
        with patch.object(claim.ClaimTransaction, "matches", wraps=claim.ClaimTransaction.matches) as compare:
            handler, store, _project = _invoke_create(cfg, [], secret, body=body)
        assert handler._status_code == 400
        compare.assert_not_called()
        store.assert_not_called()


def _saturate_global(cfg, registry):
    for client_index in range(10):
        client = f"192.0.2.{client_index + 1}"
        for attempt in range(5):
            handler, store, _project = _invoke_create(
                cfg,
                registry,
                f"wrong-{client_index}-{attempt}",
                client=client,
            )
            assert handler._status_code in {403, 429}
            store.assert_not_called()


def _assert_neutral_rate_projection(handler, candidate, secret, claim, cfg):
    assert handler._status_code == 429
    error = handler._captured["error"]
    assert set(error) == {"code", "message", "retryable"}
    assert error["code"] == "claim_rate_limited"
    assert error["retryable"] is True
    assert isinstance(error["message"], str) and error["message"]
    rendered = json.dumps(handler._captured)
    candidate_digest = hashlib.sha256(b"pve-freq-first-admin-claim-v1\0" + candidate.encode("utf-8")).hexdigest()
    assert candidate not in rendered
    assert secret not in rendered
    assert candidate_digest not in rendered
    assert claim.claim_state_path(cfg) not in rendered


def test_global_saturation_through_handler_allows_fresh_correct_claim():
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        registry = []
        limiter = _fresh_limiter()
        with patch.object(serve, "_first_admin_claim_limiter", limiter):
            _saturate_global(cfg, registry)
            handler, store, _project = _invoke_create(cfg, registry, secret, client="198.51.100.10")
        assert handler._status_code == 200
        assert [user["username"] for user in registry] == ["operator"]
        store.assert_called_once()


def test_global_saturation_through_handler_rejects_fresh_wrong_claim_without_mutation():
    with tempfile.TemporaryDirectory() as root:
        claim, cfg, _metadata, secret = _seeded_claim(root)
        registry = []
        limiter = _fresh_limiter()
        candidate = "fresh-wrong"
        with patch.object(serve, "_first_admin_claim_limiter", limiter):
            _saturate_global(cfg, registry)
            handler, store, project = _invoke_create(cfg, registry, candidate, client="198.51.100.10")
        _assert_neutral_rate_projection(handler, candidate, secret, claim, cfg)
        assert registry == []
        store.assert_not_called()
        project.assert_not_called()
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "available"
            assert transaction.matches(secret)


def test_per_client_saturation_through_handler_rejects_correct_claim_before_compare():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        registry = []
        limiter = _fresh_limiter()
        with patch.object(serve, "_first_admin_claim_limiter", limiter):
            for attempt in range(5):
                _invoke_create(cfg, registry, f"wrong-{attempt}", client="192.0.2.77")
            with patch.object(claim.ClaimTransaction, "matches", wraps=claim.ClaimTransaction.matches) as compare:
                handler, store, project = _invoke_create(cfg, registry, secret, client="192.0.2.77")
        _assert_neutral_rate_projection(handler, secret, secret, claim, cfg)
        compare.assert_not_called()
        store.assert_not_called()
        project.assert_not_called()
        assert registry == []
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "available"
            assert transaction.matches(secret)


def test_claim_rate_bucket_uses_resolved_client_ip():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        resolved = "198.51.100.77"
        limiter = _fresh_limiter()
        for attempt in range(5):
            limiter.record_invalid(resolved)
        with (
            patch.object(serve, "_first_admin_claim_limiter", limiter),
            patch("freq.modules.serve.resolve_client_ip", return_value=resolved, create=True) as resolve,
            patch.object(claim.ClaimTransaction, "matches", wraps=claim.ClaimTransaction.matches) as compare,
        ):
            handler, store, project = _invoke_create(cfg, [], secret, client="192.0.2.200")
        resolve.assert_called_once_with(handler)
        _assert_neutral_rate_projection(handler, secret, secret, claim, cfg)
        compare.assert_not_called()
        store.assert_not_called()
        project.assert_not_called()


def test_media_and_missing_claim_failures_do_not_consume_claim_attempts():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        client = "192.0.2.88"
        limiter = _fresh_limiter()
        with patch.object(serve, "_first_admin_claim_limiter", limiter):
            for _attempt in range(5):
                media, _store, _project = _invoke_create(
                    cfg,
                    [],
                    secret,
                    client=client,
                    headers={"Content-Type": "text/plain"},
                )
                assert media._status_code == 400
            for _attempt in range(5):
                body = _claim_body(secret)
                body.pop("claim_secret")
                missing, _store, _project = _invoke_create(cfg, [], secret, client=client, body=body)
                assert missing._status_code == 400
        assert limiter.client_allowed(client) is True
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.matches(secret)


def test_failed_registry_commit_does_not_clear_client_failures():
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        client = "192.0.2.89"
        limiter = _fresh_limiter()

        def fail_save(_cfg, _users):
            return "registry unavailable"

        with patch.object(serve, "_first_admin_claim_limiter", limiter):
            for attempt in range(4):
                _invoke_create(cfg, [], f"wrong-{attempt}", client=client)
            failed, _store, _project = _invoke_create(cfg, [], secret, client=client, save=fail_save)
            final_wrong, store, _project = _invoke_create(cfg, [], "fifth-wrong", client=client)
        assert failed._status_code == 500
        assert final_wrong._status_code == 429
        assert _response_code(final_wrong) == "claim_rate_limited"
        store.assert_not_called()


def test_successful_commit_clears_the_calling_client_bucket():
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        client = "192.0.2.90"
        other_client = "192.0.2.92"
        limiter = _fresh_limiter()
        registry = []
        with patch.object(serve, "_first_admin_claim_limiter", limiter):
            for attempt in range(4):
                _invoke_create(cfg, registry, f"wrong-{attempt}", client=client)
            for attempt in range(5):
                _invoke_create(cfg, registry, f"other-wrong-{attempt}", client=other_client)
            assert limiter.client_allowed(other_client) is False
            accepted, _store, _project = _invoke_create(cfg, registry, secret, client=client)
        assert accepted._status_code == 200
        assert limiter.client_allowed(client) is True
        assert limiter.client_allowed(other_client) is False


def test_rate_limiter_exact_edges_and_full_window():
    clock = [1000.0]
    limiter_type = getattr(serve, "_FirstAdminClaimRateLimiter", None)
    assert limiter_type is not None, "structural red: integrated claim limiter is absent"
    limiter = limiter_type(clock=lambda: clock[0])
    client = "192.0.2.91"
    for _attempt in range(4):
        limiter.record_invalid(client)
    assert limiter.client_allowed(client) is True
    assert limiter.global_limited() is False
    limiter.record_invalid(client)
    assert limiter.client_allowed(client) is False

    for index in range(44):
        limiter.record_invalid(f"198.51.100.{index + 1}")
    assert limiter.global_limited() is False
    limiter.record_invalid("203.0.113.50")
    assert limiter.global_limited() is True

    clock[0] += 299.999
    assert limiter.client_allowed(client) is False
    assert limiter.global_limited() is True
    clock[0] += 0.001
    assert limiter.client_allowed(client) is True
    assert limiter.global_limited() is False


def _serve_cfg(root):
    return SimpleNamespace(
        dashboard_port=8888,
        tls_cert="",
        tls_key="",
        watchdog_enabled=False,
        data_dir=str(Path(root, "data")),
        conf_dir=str(Path(root, "conf")),
        _toml_users=[],
    )


def _quiet_server():
    return SimpleNamespace(
        socket=object(),
        serve_forever=lambda: None,
        server_close=lambda: None,
    )


def _record_lifecycle_event(trace, event, phase="", **values):
    trace.append({"event": event, "phase": phase, **values})


def _run_claim_service_once(cfg, claim, phase, trace, *, while_active=None):
    """Run production cmd_serve while replacing only external service machinery."""
    state_path = Path(claim.claim_state_path(cfg))
    args = SimpleNamespace(port=None)
    _record_lifecycle_event(trace, "service-start", phase)

    class HermeticHTTPServer:
        def __init__(self, *_args):
            self.socket = object()
            _record_lifecycle_event(trace, "listener-created", phase)

        def serve_forever(self):
            _record_lifecycle_event(trace, "listener-active", phase)
            if while_active is not None:
                while_active()

        def server_close(self):
            _record_lifecycle_event(trace, "service-stopped", phase)

    def printed(*parts, **kwargs):
        line = " ".join(map(str, parts))
        secret_matches = re.findall(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])", line)
        if secret_matches:
            assert len(secret_matches) == 1
            state = json.loads(state_path.read_text(encoding="utf-8"))
            claim_id = state["claim_id"]
            assert claim_id in line
            _record_lifecycle_event(
                trace,
                "delivery",
                phase,
                token=secret_matches[0],
                claim_id=claim_id,
                flushed=kwargs.get("flush") is True,
            )
        if "Dashboard running" in line:
            claim_id = ""
            if state_path.exists():
                claim_id = json.loads(state_path.read_text(encoding="utf-8")).get("claim_id", "")
            if claim_id:
                assert claim_id in line
            _record_lifecycle_event(trace, "readiness", phase, claim_id=claim_id)

    with (
        patch("freq.modules.serve.start_background_cache"),
        patch("freq.modules.serve._start_embedded_watchdog_if_needed"),
        patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed"),
        patch("freq.modules.serve.ThreadedHTTPServer", HermeticHTTPServer),
        patch("freq.modules.serve.signal.signal"),
        patch("freq.modules.serve._cleanup_ssh_mux"),
        patch("freq.modules.serve.vault_get", return_value="configured-hash"),
        patch("freq.modules.vault.vault_get", return_value="configured-hash"),
        patch("builtins.print", side_effect=printed),
    ):
        assert serve.cmd_serve(cfg, None, args) == 0


def _lifecycle_index(trace, event, phase=""):
    matches = [
        index
        for index, item in enumerate(trace)
        if item["event"] == event and (not phase or item["phase"] == phase)
    ]
    assert len(matches) == 1, (event, phase, matches, trace)
    return matches[0]


def _assert_consumed_recovery_lifecycle(trace, *, old_claim_id, old_secret):
    initial_start = _lifecycle_index(trace, "service-start", "initial")
    initial_readiness = _lifecycle_index(trace, "readiness", "initial")
    initial_active = _lifecycle_index(trace, "listener-active", "initial")
    old_before = _lifecycle_index(trace, "old-token-rejected-before-reset", "initial")
    initial_stop = _lifecycle_index(trace, "service-stopped", "initial")
    absent = _lifecycle_index(trace, "state-absent-while-stopped")
    restart_start = _lifecycle_index(trace, "service-start", "restart")
    restart_readiness = _lifecycle_index(trace, "readiness", "restart")
    restart_active = _lifecycle_index(trace, "listener-active", "restart")
    old_after = _lifecycle_index(trace, "old-token-rejected-after-restart", "restart")
    new_accepted = _lifecycle_index(trace, "new-token-accepted-once", "restart")
    old_replay = _lifecycle_index(trace, "old-token-replay-rejected", "restart")
    new_replay = _lifecycle_index(trace, "new-token-replay-rejected", "restart")
    restart_stop = _lifecycle_index(trace, "service-stopped", "restart")
    assert (
        initial_start
        < initial_readiness
        < initial_active
        < old_before
        < initial_stop
        < absent
        < restart_start
        < restart_readiness
        < restart_active
        < old_after
        < new_accepted
        < old_replay
        < new_replay
        < restart_stop
    )

    deliveries = [item for item in trace if item["event"] == "delivery"]
    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery["phase"] == "restart"
    assert restart_start < trace.index(delivery) < restart_readiness
    assert delivery["claim_id"] != old_claim_id
    assert delivery["token"] != old_secret
    assert delivery["flushed"] is True
    assert not any(item["event"] == "delivery" and item["phase"] == "initial" for item in trace)


def _assert_configured_recovery_lifecycle(trace, *, configured_case):
    initial_start = _lifecycle_index(trace, "service-start", "initial")
    initial_readiness = _lifecycle_index(trace, "readiness", "initial")
    initial_active = _lifecycle_index(trace, "listener-active", "initial")
    initial_stop = _lifecycle_index(trace, "service-stopped", "initial")
    absent = _lifecycle_index(trace, "state-absent-while-stopped")
    restart_start = _lifecycle_index(trace, "service-start", "restart")
    restart_readiness = _lifecycle_index(trace, "readiness", "restart")
    restart_active = _lifecycle_index(trace, "listener-active", "restart")
    closed = _lifecycle_index(trace, "configured-create-admin-closed", "restart")
    restart_stop = _lifecycle_index(trace, "service-stopped", "restart")
    assert (
        initial_start
        < initial_readiness
        < initial_active
        < initial_stop
        < absent
        < restart_start
        < restart_readiness
        < restart_active
        < closed
        < restart_stop
    )
    assert not any(item["event"] == "delivery" for item in trace)
    assert not any(item["event"] == "claim-regenerated" for item in trace)
    closed_event = trace[closed]
    assert closed_event["configured_case"] == configured_case
    assert closed_event["code"] == ("operator_exists" if configured_case == "user-present" else "setup_closed")


def _replace_lifecycle_event(trace, old_event, new_event, *, phase=""):
    mutated = copy.deepcopy(trace)
    index = _lifecycle_index(mutated, old_event, phase)
    mutated[index]["event"] = new_event
    return mutated


def _valid_consumed_recovery_trace():
    old_claim_id = "old-generation"
    old_secret = "O" * 43
    return (
        [
            {"event": "service-start", "phase": "initial"},
            {"event": "listener-created", "phase": "initial"},
            {"event": "readiness", "phase": "initial", "claim_id": old_claim_id},
            {"event": "listener-active", "phase": "initial"},
            {"event": "old-token-rejected-before-reset", "phase": "initial"},
            {"event": "service-stopped", "phase": "initial"},
            {"event": "state-absent-while-stopped", "phase": ""},
            {"event": "service-start", "phase": "restart"},
            {"event": "listener-created", "phase": "restart"},
            {
                "event": "delivery",
                "phase": "restart",
                "token": "N" * 43,
                "claim_id": "new-generation",
                "flushed": True,
            },
            {"event": "readiness", "phase": "restart", "claim_id": "new-generation"},
            {"event": "listener-active", "phase": "restart"},
            {"event": "old-token-rejected-after-restart", "phase": "restart"},
            {"event": "new-token-accepted-once", "phase": "restart"},
            {"event": "old-token-replay-rejected", "phase": "restart"},
            {"event": "new-token-replay-rejected", "phase": "restart"},
            {"event": "service-stopped", "phase": "restart"},
        ],
        old_claim_id,
        old_secret,
    )


def _valid_configured_recovery_trace(configured_case):
    code = "operator_exists" if configured_case == "user-present" else "setup_closed"
    return [
        {"event": "service-start", "phase": "initial"},
        {"event": "listener-created", "phase": "initial"},
        {"event": "readiness", "phase": "initial", "claim_id": ""},
        {"event": "listener-active", "phase": "initial"},
        {"event": "service-stopped", "phase": "initial"},
        {"event": "state-absent-while-stopped", "phase": ""},
        {"event": "service-start", "phase": "restart"},
        {"event": "listener-created", "phase": "restart"},
        {"event": "readiness", "phase": "restart", "claim_id": ""},
        {"event": "listener-active", "phase": "restart"},
        {
            "event": "configured-create-admin-closed",
            "phase": "restart",
            "configured_case": configured_case,
            "code": code,
        },
        {"event": "service-stopped", "phase": "restart"},
    ]


def _exercise_consumed_recovery_lifecycle():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _serve_cfg(root)
        deliveries = []
        initial = _prepare_claim(claim, cfg, deliveries)
        old_claim_id, old_secret, _generated_at = deliveries[0]
        assert initial["claim_id"] == old_claim_id
        with claim.locked_first_admin_claim(cfg) as transaction:
            transaction.consume(now=1001.0)
        state_path = Path(claim.claim_state_path(cfg))
        consumed_bytes = state_path.read_bytes()
        registry = []
        trace = []

        def reject_old_before_reset():
            handler, store, project = _invoke_lifecycle_create(cfg, registry, old_secret)
            assert handler._status_code == 409
            assert _response_code(handler) == "claim_consumed"
            store.assert_not_called()
            project.assert_not_called()
            assert registry == []
            assert state_path.read_bytes() == consumed_bytes
            _record_lifecycle_event(trace, "old-token-rejected-before-reset", "initial")

        _run_claim_service_once(cfg, claim, "initial", trace, while_active=reject_old_before_reset)
        assert trace[-1]["event"] == "service-stopped"
        state_path.unlink()
        assert not state_path.exists()
        _record_lifecycle_event(trace, "state-absent-while-stopped")

        def exercise_restarted_service():
            delivery = next(item for item in trace if item["event"] == "delivery" and item["phase"] == "restart")
            new_secret = delivery["token"]
            available_bytes = state_path.read_bytes()
            old, old_store, old_project = _invoke_lifecycle_create(cfg, registry, old_secret)
            assert old._status_code == 403
            assert _response_code(old) == "claim_secret_invalid"
            old_store.assert_not_called()
            old_project.assert_not_called()
            assert registry == []
            assert state_path.read_bytes() == available_bytes
            _record_lifecycle_event(trace, "old-token-rejected-after-restart", "restart")

            accepted, _store, _project = _invoke_lifecycle_create(cfg, registry, new_secret)
            assert accepted._status_code == 200
            assert [user["username"] for user in registry] == ["operator"]
            _record_lifecycle_event(trace, "new-token-accepted-once", "restart")

            old_replay, old_replay_store, _project = _invoke_lifecycle_create(cfg, registry, old_secret)
            assert old_replay._status_code == 409
            assert _response_code(old_replay) == "operator_exists"
            old_replay_store.assert_not_called()
            _record_lifecycle_event(trace, "old-token-replay-rejected", "restart")

            new_replay, new_replay_store, _project = _invoke_lifecycle_create(cfg, registry, new_secret)
            assert new_replay._status_code == 409
            assert _response_code(new_replay) == "operator_exists"
            new_replay_store.assert_not_called()
            assert [user["username"] for user in registry] == ["operator"]
            _record_lifecycle_event(trace, "new-token-replay-rejected", "restart")

        _run_claim_service_once(cfg, claim, "restart", trace, while_active=exercise_restarted_service)
        _assert_consumed_recovery_lifecycle(trace, old_claim_id=old_claim_id, old_secret=old_secret)
        return trace, old_claim_id, old_secret


def _mutate_consumed_recovery_trace(trace, mutation):
    mutated = copy.deepcopy(trace)
    if mutation == "initial-delivery":
        mutated.insert(
            _lifecycle_index(mutated, "readiness", "initial"),
            {
                "event": "delivery",
                "phase": "initial",
                "token": "A" * 43,
                "claim_id": "wrong-initial-generation",
                "flushed": True,
            },
        )
    elif mutation == "deletion-before-stop":
        deletion = mutated.pop(_lifecycle_index(mutated, "state-absent-while-stopped"))
        mutated.insert(_lifecycle_index(mutated, "service-stopped", "initial"), deletion)
    elif mutation == "deletion-after-restart":
        deletion = mutated.pop(_lifecycle_index(mutated, "state-absent-while-stopped"))
        mutated.insert(_lifecycle_index(mutated, "readiness", "restart"), deletion)
    elif mutation == "restart-without-delivery":
        mutated = [item for item in mutated if item["event"] != "delivery"]
    elif mutation == "delivery-after-readiness":
        delivery = mutated.pop(_lifecycle_index(mutated, "delivery", "restart"))
        mutated.insert(_lifecycle_index(mutated, "listener-active", "restart"), delivery)
    elif mutation == "duplicate-delivery":
        mutated.insert(
            _lifecycle_index(mutated, "readiness", "restart"),
            copy.deepcopy(next(item for item in mutated if item["event"] == "delivery")),
        )
    elif mutation == "old-identifier-reused":
        delivery = next(item for item in mutated if item["event"] == "delivery")
        delivery["claim_id"] = "old-generation"
    elif mutation == "old-secret-reused":
        delivery = next(item for item in mutated if item["event"] == "delivery")
        delivery["token"] = "O" * 43
    elif mutation == "old-token-accepted":
        mutated = _replace_lifecycle_event(
            mutated,
            "old-token-rejected-after-restart",
            "old-token-accepted-after-restart",
            phase="restart",
        )
    elif mutation == "new-token-rejected":
        mutated = _replace_lifecycle_event(
            mutated,
            "new-token-accepted-once",
            "new-token-rejected",
            phase="restart",
        )
    elif mutation == "new-token-reusable":
        mutated = _replace_lifecycle_event(
            mutated,
            "new-token-replay-rejected",
            "new-token-reusable",
            phase="restart",
        )
    else:
        raise AssertionError(f"unknown lifecycle mutation: {mutation}")
    return mutated


def _exercise_configured_recovery_lifecycle(configured_case):
    assert configured_case in {"user-present", "marker-present"}
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _serve_cfg(root)
        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        old_secret = deliveries[0][1]
        with claim.locked_first_admin_claim(cfg) as transaction:
            transaction.consume(now=1001.0)
        state_path = Path(claim.claim_state_path(cfg))
        consumed_bytes = state_path.read_bytes()
        if configured_case == "user-present":
            Path(cfg.conf_dir).mkdir(parents=True, exist_ok=True)
            Path(cfg.conf_dir, "users.conf").write_text("operator admin\n", encoding="utf-8")
            registry = [{"username": "operator", "role": "admin"}]
            setup_complete = False
        else:
            Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
            Path(cfg.data_dir, "setup-complete").write_text("complete\n", encoding="utf-8")
            registry = []
            setup_complete = True
        trace = []
        _run_claim_service_once(cfg, claim, "initial", trace)
        if state_path.exists() and state_path.read_bytes() != consumed_bytes:
            _record_lifecycle_event(trace, "claim-regenerated", "initial")
        if state_path.exists():
            state_path.unlink()
        assert not state_path.exists()
        _record_lifecycle_event(trace, "state-absent-while-stopped")

        def prove_closed_after_restart():
            before_registry = copy.deepcopy(registry)
            before_claim = state_path.read_bytes() if state_path.exists() else None
            if before_claim is not None:
                _record_lifecycle_event(trace, "claim-regenerated", "restart")
            handler, store, project = _invoke_lifecycle_create(
                cfg,
                registry,
                old_secret,
                setup_complete=setup_complete,
            )
            assert handler._status_code == (409 if configured_case == "user-present" else 403)
            assert _response_code(handler) == ("operator_exists" if configured_case == "user-present" else "setup_closed")
            store.assert_not_called()
            project.assert_not_called()
            assert registry == before_registry
            after_claim = state_path.read_bytes() if state_path.exists() else None
            assert after_claim == before_claim
            _record_lifecycle_event(
                trace,
                "configured-create-admin-closed",
                "restart",
                configured_case=configured_case,
                code=_response_code(handler),
            )

        _run_claim_service_once(cfg, claim, "restart", trace, while_active=prove_closed_after_restart)
        _assert_configured_recovery_lifecycle(trace, configured_case=configured_case)
        return trace


def _route_entry_witness(*, mutation="", direct=False):
    handler = _capturing_handler({})
    calls = []
    routes = dict(handler._load_routes())
    route = "/api/setup/create-admin"
    assert routes[route] == "_serve_setup_create_admin"

    def create_admin_target():
        calls.append("create-admin")
        handler._json_response({"ok": True}, 200)

    def retargeted_handler():
        calls.append("retargeted")
        handler._json_response({"error": "wrong route"}, 418)

    if mutation == "removed":
        routes.pop(route)
    elif mutation == "retargeted":
        routes[route] = "_serve_setup_status"
    elif mutation:
        raise AssertionError(f"unknown route mutation: {mutation}")

    with (
        patch.object(handler, "_load_routes", return_value=routes),
        patch.object(handler, "_serve_setup_create_admin", side_effect=create_admin_target),
        patch.object(handler, "_serve_setup_status", side_effect=retargeted_handler),
    ):
        if direct:
            handler._serve_setup_create_admin()
        else:
            handler.do_POST()
    return handler._status_code, calls


def _assert_create_admin_route_entered(result):
    status, calls = result
    assert status == 200
    assert calls == ["create-admin"]


@pytest.mark.parametrize("mutation", ["removed", "retargeted"])
def test_lifecycle_create_admin_route_removal_and_retarget_are_independently_red(mutation):
    _assert_create_admin_route_entered(_route_entry_witness())
    _assert_create_admin_route_entered(_route_entry_witness(mutation=mutation, direct=True))
    with pytest.raises(AssertionError):
        _assert_create_admin_route_entered(_route_entry_witness(mutation=mutation))


def test_consumed_recovery_uses_production_start_stop_delete_restart_lifecycle():
    trace, old_claim_id, old_secret = _exercise_consumed_recovery_lifecycle()
    _assert_consumed_recovery_lifecycle(trace, old_claim_id=old_claim_id, old_secret=old_secret)


@pytest.mark.parametrize(
    "mutation",
    [
        "initial-delivery",
        "deletion-before-stop",
        "deletion-after-restart",
        "restart-without-delivery",
        "delivery-after-readiness",
        "duplicate-delivery",
        "old-identifier-reused",
        "old-secret-reused",
        "old-token-accepted",
        "new-token-rejected",
        "new-token-reusable",
    ],
)
def test_each_consumed_recovery_lifecycle_wrong_path_is_independently_red(mutation):
    trace, old_claim_id, old_secret = _valid_consumed_recovery_trace()
    _assert_consumed_recovery_lifecycle(trace, old_claim_id=old_claim_id, old_secret=old_secret)
    mutated = _mutate_consumed_recovery_trace(trace, mutation)
    with pytest.raises(AssertionError):
        _assert_consumed_recovery_lifecycle(mutated, old_claim_id=old_claim_id, old_secret=old_secret)


@pytest.mark.parametrize("configured_case", ["user-present", "marker-present"])
def test_configured_recovery_cases_each_run_independent_full_lifecycle(configured_case):
    trace = _exercise_configured_recovery_lifecycle(configured_case)
    _assert_configured_recovery_lifecycle(trace, configured_case=configured_case)


@pytest.mark.parametrize("configured_case", ["user-present", "marker-present"])
@pytest.mark.parametrize(
    "mutation",
    [
        "initial-delivery",
        "restart-delivery",
        "initial-regeneration",
        "restart-regeneration",
        "create-admin-reopened",
    ],
)
def test_each_configured_recovery_wrong_path_is_independently_red(configured_case, mutation):
    trace = _valid_configured_recovery_trace(configured_case)
    _assert_configured_recovery_lifecycle(trace, configured_case=configured_case)
    mutated = copy.deepcopy(trace)
    if mutation.endswith("delivery"):
        phase = mutation.removesuffix("-delivery")
        mutated.insert(
            _lifecycle_index(mutated, "readiness", phase),
            {
                "event": "delivery",
                "phase": phase,
                "token": "B" * 43,
                "claim_id": f"wrong-{configured_case}-{phase}",
                "flushed": True,
            },
        )
    elif mutation.endswith("regeneration"):
        phase = mutation.removesuffix("-regeneration")
        mutated.insert(
            _lifecycle_index(mutated, "readiness", phase),
            {"event": "claim-regenerated", "phase": phase},
        )
    else:
        mutated = _replace_lifecycle_event(
            mutated,
            "configured-create-admin-closed",
            "configured-create-admin-reopened",
            phase="restart",
        )
    with pytest.raises(AssertionError):
        _assert_configured_recovery_lifecycle(mutated, configured_case=configured_case)


def test_zero_state_corrupt_claim_aborts_cmd_serve_before_listener():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _serve_cfg(root)
        path = Path(claim.claim_state_path(cfg))
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text("not-json", encoding="utf-8")
        path.chmod(0o600)
        args = SimpleNamespace(port=None)
        with (
            patch.object(FreqHandler, "_load_routes", return_value={}),
            patch("freq.modules.serve._load_users", return_value=[]),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve.start_background_cache") as background,
            patch("freq.modules.serve._start_embedded_watchdog_if_needed") as watchdog,
            patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed") as cert,
            patch("freq.modules.serve.ThreadedHTTPServer") as listener,
            patch("freq.modules.serve._cleanup_ssh_mux"),
        ):
            assert serve.cmd_serve(cfg, None, args) == 1
        background.assert_not_called()
        watchdog.assert_not_called()
        cert.assert_not_called()
        listener.assert_not_called()


def test_zero_state_unreadable_claim_aborts_cmd_serve_before_listener():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _serve_cfg(root)
        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        state_path = os.path.abspath(claim.claim_state_path(cfg))
        real_open = os.open

        def unreadable_state(path, flags, mode=0o777, *, dir_fd=None):
            absolute = os.path.abspath(os.fspath(path))
            if absolute == state_path and flags & os.O_ACCMODE == os.O_RDONLY:
                raise PermissionError("claim state read denied")
            return real_open(path, flags, mode, dir_fd=dir_fd)

        args = SimpleNamespace(port=None)
        with (
            patch.object(claim.os, "open", side_effect=unreadable_state),
            patch.object(FreqHandler, "_load_routes", return_value={}),
            patch("freq.modules.serve._load_users", return_value=[]),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve.start_background_cache") as background,
            patch("freq.modules.serve._start_embedded_watchdog_if_needed") as watchdog,
            patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed") as cert,
            patch("freq.modules.serve.ThreadedHTTPServer") as listener,
            patch("freq.modules.serve._cleanup_ssh_mux"),
        ):
            assert serve.cmd_serve(cfg, None, args) == 1
        background.assert_not_called()
        watchdog.assert_not_called()
        cert.assert_not_called()
        listener.assert_not_called()


def test_configured_corrupt_claim_reaches_cmd_serve_readiness_secret_free():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _serve_cfg(root)
        path = Path(claim.claim_state_path(cfg))
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text("not-json", encoding="utf-8")
        path.chmod(0o600)
        args = SimpleNamespace(port=None)
        output = []
        warnings = []
        with (
            patch.object(FreqHandler, "_load_routes", return_value={}),
            patch("freq.modules.serve._load_users", return_value=[{"username": "operator", "role": "admin"}]),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve.start_background_cache"),
            patch("freq.modules.serve._start_embedded_watchdog_if_needed"),
            patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed"),
            patch("freq.modules.serve.ThreadedHTTPServer", return_value=_quiet_server()),
            patch("freq.modules.serve.signal.signal"),
            patch("freq.modules.serve._cleanup_ssh_mux"),
            patch("freq.modules.serve.vault_get", return_value="hash"),
            patch.object(serve.logger, "warning", side_effect=lambda *args, **kwargs: warnings.append((args, kwargs))),
            patch("builtins.print", side_effect=lambda *parts, **_kwargs: output.append(" ".join(map(str, parts)))),
        ):
            assert serve.cmd_serve(cfg, None, args) == 0
        rendered = "\n".join(output) + json.dumps(warnings, default=str)
        assert "Dashboard running" in rendered
        assert warnings
        assert "secret" not in rendered.lower()


@pytest.mark.parametrize("unsafe_case", ["symlink", "unreadable", "cleanup-failure"])
def test_configured_unsafe_state_and_cleanup_failure_reach_readiness(unsafe_case):
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _serve_cfg(root)
        path = Path(claim.claim_state_path(cfg))
        path.parent.mkdir(parents=True, mode=0o700)
        cleanup_patch = contextlib.nullcontext()
        read_patch = contextlib.nullcontext()
        cleanup_attempts = []
        if unsafe_case == "symlink":
            target = path.parent / "attacker-state.json"
            target.write_text("{}", encoding="utf-8")
            path.symlink_to(target)
        elif unsafe_case == "unreadable":
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o600)
            real_open = os.open

            def deny_state_read(candidate, flags, *args, **kwargs):
                if os.fspath(candidate) == os.fspath(path):
                    raise PermissionError("state read denied")
                return real_open(candidate, flags, *args, **kwargs)

            read_patch = patch.object(claim.os, "open", side_effect=deny_state_read)
        else:
            _prepare_claim(claim, cfg, [])

            def fail_reconciliation_replace(*args, **kwargs):
                cleanup_attempts.append((args, kwargs))
                raise OSError("configured reconciliation denied")

            cleanup_patch = patch.object(claim.os, "replace", side_effect=fail_reconciliation_replace)
        output = []
        warnings = []
        args = SimpleNamespace(port=None)
        with (
            cleanup_patch,
            read_patch,
            patch.object(FreqHandler, "_load_routes", return_value={}),
            patch("freq.modules.serve._load_users", return_value=[{"username": "operator", "role": "admin"}]),
            patch("freq.modules.serve._setup_marker_exists", return_value=False),
            patch("freq.modules.serve.start_background_cache"),
            patch("freq.modules.serve._start_embedded_watchdog_if_needed"),
            patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed"),
            patch("freq.modules.serve.ThreadedHTTPServer", return_value=_quiet_server()) as listener,
            patch("freq.modules.serve.signal.signal"),
            patch("freq.modules.serve._cleanup_ssh_mux"),
            patch("freq.modules.serve.vault_get", return_value="hash"),
            patch.object(serve.logger, "warning", side_effect=lambda *args, **kwargs: warnings.append((args, kwargs))),
            patch("builtins.print", side_effect=lambda *parts, **_kwargs: output.append(" ".join(map(str, parts)))),
        ):
            assert serve.cmd_serve(cfg, None, args) == 0
        listener.assert_called_once()
        if unsafe_case == "cleanup-failure":
            assert len(cleanup_attempts) == 1
        rendered = "\n".join(output) + json.dumps(warnings, default=str)
        assert "Dashboard running" in rendered
        assert warnings
        assert "claim_secret" not in rendered


def test_marker_observation_failure_aborts_before_listener():
    with tempfile.TemporaryDirectory() as root:
        cfg = _serve_cfg(root)
        args = SimpleNamespace(port=None)
        with (
            patch.object(FreqHandler, "_load_routes", return_value={}),
            patch("freq.modules.serve._load_users", return_value=[]),
            patch(
                "freq.modules.serve._setup_marker_exists",
                side_effect=PermissionError("marker observation denied"),
            ),
            patch("freq.modules.serve.start_background_cache") as background,
            patch("freq.modules.serve._start_embedded_watchdog_if_needed") as watchdog,
            patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed") as cert,
            patch("freq.modules.serve.ThreadedHTTPServer") as listener,
            patch("freq.modules.serve._cleanup_ssh_mux"),
        ):
            assert serve.cmd_serve(cfg, None, args) == 1
        background.assert_not_called()
        watchdog.assert_not_called()
        cert.assert_not_called()
        listener.assert_not_called()


def test_startup_orders_observation_delivery_workers_listener_and_readiness():
    cfg = SimpleNamespace(
        dashboard_port=8888,
        tls_cert="",
        tls_key="",
        watchdog_enabled=False,
        data_dir="/tmp/f4-data",
        conf_dir="/tmp/f4-conf",
    )
    args = SimpleNamespace(port=None)
    order = []
    output_lines = []
    output_calls = []
    raw_secret = "fixture-raw-secret"
    claim_id = "generation-b"
    httpd = SimpleNamespace(
        socket=object(),
        serve_forever=lambda: None,
        server_close=lambda: None,
    )

    def observe_users(_cfg):
        order.append("users")
        return []

    def observe_marker(_cfg):
        order.append("marker")
        return False

    def prepare(_cfg, **kwargs):
        order.append("prepare")
        assert kwargs["users_present"] is False
        assert kwargs["setup_complete"] is False
        kwargs["deliver"](claim_id, raw_secret, 1000.0)
        return {"state": "available", "claim_id": claim_id, "generated": True, "delivered": True}

    def load_routes():
        order.append("routes")
        return {}

    def printed(*parts, **kwargs):
        line = " ".join(map(str, parts))
        output_lines.append(line)
        output_calls.append((line, dict(kwargs)))
        if raw_secret in line:
            order.append("delivery")
        if "Dashboard running" in line:
            order.append("readiness")

    with (
        patch.object(FreqHandler, "_load_routes", autospec=True, side_effect=load_routes),
        patch("freq.modules.serve._load_users", side_effect=observe_users),
        patch("freq.modules.serve._setup_marker_exists", side_effect=observe_marker),
        patch("freq.modules.serve.prepare_first_admin_claim", side_effect=prepare, create=True),
        patch("freq.modules.serve.start_background_cache", side_effect=lambda: order.append("background")),
        patch(
            "freq.modules.serve._start_embedded_watchdog_if_needed",
            side_effect=lambda *_args: order.append("watchdog"),
        ),
        patch(
            "freq.modules.serve._start_cert_renewal_scheduler_if_needed",
            side_effect=lambda *_args: order.append("cert"),
        ),
        patch(
            "freq.modules.serve.ThreadedHTTPServer",
            side_effect=lambda *_args: order.append("listener") or httpd,
        ),
        patch("freq.modules.serve.signal.signal"),
        patch("freq.modules.serve._cleanup_ssh_mux"),
        patch("builtins.print", side_effect=printed),
    ):
        assert serve.cmd_serve(cfg, None, args) == 0
    assert order == [
        "routes",
        "users",
        "marker",
        "prepare",
        "delivery",
        "background",
        "watchdog",
        "cert",
        "listener",
        "readiness",
    ]
    readiness = next(line for line in output_lines if "Dashboard running" in line)
    delivery_lines = [line for line in output_lines if raw_secret in line]
    assert len(delivery_lines) == 1
    delivery = delivery_lines[0]
    assert claim_id in delivery
    assert re.search(r"(?:generated|generation|timestamp).*1000", delivery, re.IGNORECASE)
    delivery_call = next(call for call in output_calls if raw_secret in call[0])
    assert delivery_call[1].get("flush") is True
    assert claim_id in readiness
    assert raw_secret not in readiness


def test_browser_and_programmatic_copy_and_c03_are_explicit():
    setup_html = (REPO_ROOT / "freq/data/web/setup.html").read_text(encoding="utf-8")
    schema_owner = (REPO_ROOT / "tests/test_setup_schema_table.py").read_text(encoding="utf-8")
    browser_owner = (REPO_ROOT / "tests/e2e/zero-state-web-ux.spec.js").read_text(encoding="utf-8")
    assert "first-run · browser-only init" not in setup_html
    assert "browser-only transport truth" not in schema_owner
    assert "browser-only wizard" not in browser_owner
    for source in (setup_html, schema_owner, browser_owner):
        assert "browser and programmatic" in source.lower()


def test_f4_playwright_policy_detects_and_cleans_planted_secret():
    config = (REPO_ROOT / "playwright.f4-owner.config.js").read_text(encoding="utf-8")
    runner = (REPO_ROOT / "tests/support/run_e1_f4_browser_owner.js").read_text(encoding="utf-8")
    spec = (REPO_ROOT / "tests/e2e/e1-f4-first-admin-claim.spec.js").read_text(encoding="utf-8")
    assert "trace: 'off'" in config
    assert "screenshot: 'off'" in config
    assert "video: 'off'" in config
    assert "scanArtifacts" in runner and "cleanup" in runner
    assert "PVE_FREQ_F4_SECRET_AUDIT_FILE" in runner
    assert "PVE_FREQ_F4_EVIDENCE_XML" in runner
    assert "PVE_FREQ_F4_SECRET_AUDIT_FILE" in spec
    result = subprocess.run(
        ["node", "tests/support/e1_f4_artifact_policy.js", "--self-test"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PLANTED_SECRET_DETECTED_AND_CLEANED\n"
    assert "F4-Planted_Secret-Value" not in result.stdout + result.stderr


def test_default_playwright_config_cannot_collect_claim_owner():
    with tempfile.TemporaryDirectory() as root:
        registry = Path(root, "registered-secrets")
        registry.write_text("", encoding="utf-8")
        registry.chmod(0o600)
        for supplied_registry in (None, registry):
            env = dict(os.environ)
            if supplied_registry is None:
                env.pop("PVE_FREQ_F4_SECRET_AUDIT_FILE", None)
            else:
                env["PVE_FREQ_F4_SECRET_AUDIT_FILE"] = os.fspath(supplied_registry)
            result = subprocess.run(
                ["node_modules/.bin/playwright", "test", "--config=playwright.config.js", "--list"],
                cwd=REPO_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr
            listing = result.stdout + result.stderr
            assert "e1-f4-first-admin-claim.spec.js" not in listing
            assert "Total:" in listing


def test_browser_runner_refuses_unsafe_evidence_destinations_without_mutation(tmp_path, monkeypatch):
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    monkeypatch.setenv("PVE_FREQ_F4_EVIDENCE_ROOT", os.fspath(evidence_root))
    runner = REPO_ROOT / "tests/support/run_e1_f4_browser_owner.js"

    def refused_untouched(target, sentinel):
        env = dict(os.environ)
        env["PVE_FREQ_F4_EVIDENCE_XML"] = os.fspath(target)
        result = subprocess.run(
            ["node", os.fspath(runner)],
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert sentinel.exists()
        assert sentinel.read_text(encoding="utf-8") == "DO-NOT-DELETE\n"

    with tempfile.TemporaryDirectory(dir=evidence_root) as directory:
        target_dir = Path(directory)
        sentinel = target_dir / "sentinel"
        sentinel.write_text("DO-NOT-DELETE\n", encoding="utf-8")
        refused_untouched(target_dir, sentinel)

    with tempfile.TemporaryDirectory() as directory:
        outside = Path(directory, "outside.xml")
        outside.write_text("DO-NOT-DELETE\n", encoding="utf-8")
        refused_untouched(outside, outside)

        descriptor, link_name = tempfile.mkstemp(prefix=".f4-r6-link-", dir=evidence_root)
        os.close(descriptor)
        link = Path(link_name)
        link.unlink()
        link.symlink_to(outside)
        try:
            refused_untouched(link, outside)
            assert link.is_symlink()
            outside.unlink()
            env = dict(os.environ)
            env["PVE_FREQ_F4_EVIDENCE_XML"] = os.fspath(link)
            broken = subprocess.run(
                ["node", os.fspath(runner)],
                cwd=REPO_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )
            assert broken.returncode != 0
            assert link.is_symlink()
        finally:
            link.unlink(missing_ok=True)


def test_local_lost_token_reset_replaces_only_zero_state_claim():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        first = []
        _prepare_claim(claim, cfg, first)
        old_secret = first[0][1]
        Path(claim.claim_state_path(cfg)).unlink()
        second = []
        _prepare_claim(claim, cfg, second, now=1001.0)
        new_secret = second[0][1]
        assert new_secret != old_secret
        registry = []
        wrong, store, _project = _invoke_create(cfg, registry, old_secret)
        assert wrong._status_code == 403
        assert _response_code(wrong) == "claim_secret_invalid"
        store.assert_not_called()
        accepted, _store, _project = _invoke_create(cfg, registry, new_secret)
        assert accepted._status_code == 200

        configured_root = Path(root, "configured")
        configured_root.mkdir()
        configured_cfg = _cfg(str(configured_root))
        configured_deliveries = []
        result = _prepare_claim(
            claim,
            configured_cfg,
            configured_deliveries,
            users_present=True,
        )
        assert result["state"] == "configured"
        assert configured_deliveries == []


def test_consumed_zero_state_local_reset_regenerates_once_and_configured_state_stays_closed():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        first = []
        _prepare_claim(claim, cfg, first)
        old_secret = first[0][1]
        with claim.locked_first_admin_claim(cfg) as transaction:
            transaction.consume(now=1001.0)
        consumed = json.loads(Path(claim.claim_state_path(cfg)).read_text(encoding="utf-8"))
        assert consumed["state"] == "consumed"
        assert "digest" not in consumed

        Path(claim.claim_state_path(cfg)).unlink()
        replacement = []
        _prepare_claim(claim, cfg, replacement, now=1002.0)
        assert len(replacement) == 1
        new_secret = replacement[0][1]
        assert new_secret != old_secret

        registry = []
        rejected, old_store, _old_project = _invoke_create(cfg, registry, old_secret)
        assert rejected._status_code == 403
        assert _response_code(rejected) == "claim_secret_invalid"
        old_store.assert_not_called()
        accepted, _new_store, _new_project = _invoke_create(cfg, registry, new_secret)
        assert accepted._status_code == 200

        configured_root = Path(root, "configured-consumed")
        configured_root.mkdir()
        configured_cfg = _cfg(str(configured_root))
        configured_first = []
        _prepare_claim(claim, configured_cfg, configured_first)
        with claim.locked_first_admin_claim(configured_cfg) as transaction:
            transaction.consume(now=1003.0)
        Path(claim.claim_state_path(configured_cfg)).unlink()
        configured_deliveries = []
        result = _prepare_claim(
            claim,
            configured_cfg,
            configured_deliveries,
            users_present=True,
            now=1004.0,
        )
        assert result["state"] == "configured"
        assert configured_deliveries == []


def test_pending_generation_old_token_fails_and_new_token_commits():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        generation_a = []

        def interrupted(claim_id, secret, generated_at):
            generation_a.append((claim_id, secret, generated_at))
            raise OSError("stop after delivery")

        with pytest.raises(claim.ClaimStateError, match="delivery"):
            _prepare_claim(claim, cfg, [], deliver=interrupted)
        generation_b = []
        metadata = _prepare_claim(claim, cfg, generation_b, now=1001.0)
        assert metadata["claim_id"] == generation_b[0][0]
        assert generation_a[0][0] != generation_b[0][0]
        registry = []
        old, old_store, _project = _invoke_create(cfg, registry, generation_a[0][1])
        assert old._status_code == 403
        assert _response_code(old) == "claim_secret_invalid"
        assert registry == []
        old_store.assert_not_called()
        new, _new_store, _project = _invoke_create(cfg, registry, generation_b[0][1])
        assert new._status_code == 200
        assert [user["username"] for user in registry] == ["operator"]


@pytest.mark.parametrize(
    "record",
    [
        {
            "schema": "pve-freq-first-admin-claim-v1",
            "state": "available",
            "claim_id": "id",
            "digest": "0" * 64,
            "generated_at": 1,
            "delivered_at": 2,
            "unknown": True,
        },
        {
            "schema": "pve-freq-first-admin-claim-v1",
            "state": "available",
            "claim_id": ["id"],
            "digest": "0" * 64,
            "generated_at": 1,
            "delivered_at": 2,
        },
        {
            "schema": "pve-freq-first-admin-claim-v1",
            "state": "consumed",
            "claim_id": "id",
            "digest": "0" * 64,
            "generated_at": 1,
            "consumed_at": 2,
        },
        {
            "schema": "pve-freq-first-admin-claim-v1",
            "state": "pending_delivery",
            "claim_id": "id",
            "generated_at": 2,
            "delivered_at": 1,
            "digest": "0" * 64,
        },
    ],
)
def test_claim_state_rejects_unknown_types_and_impossible_transitions(record):
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        path = Path(claim.claim_state_path(cfg))
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text(json.dumps(record), encoding="utf-8")
        path.chmod(0o600)
        with pytest.raises(claim.ClaimStateError, match="unavailable"):
            _prepare_claim(claim, cfg, [])


def test_claim_state_rejects_unsafe_file_shapes_and_repairs_private_mode():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        path = Path(claim.claim_state_path(cfg))
        path.parent.mkdir(parents=True, mode=0o700)
        path.mkdir()
        with pytest.raises(claim.ClaimStateError, match="unavailable"):
            _prepare_claim(claim, cfg, [])
        path.rmdir()

        target = path.parent / "attacker.json"
        target.write_text("{}", encoding="utf-8")
        path.symlink_to(target)
        with pytest.raises(claim.ClaimStateError, match="unavailable"):
            _prepare_claim(claim, cfg, [])
        path.unlink()
        target.unlink()

        deliveries = []
        _prepare_claim(claim, cfg, deliveries)
        hardlink = path.parent / "hardlink.json"
        os.link(path, hardlink)
        with pytest.raises(claim.ClaimStateError, match="unavailable"):
            _prepare_claim(claim, cfg, [])
        hardlink.unlink()
        path.chmod(0o644)
        _prepare_claim(claim, cfg, [])
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        path.chmod(0o644)
        with (
            patch.object(claim.os, "chmod", side_effect=PermissionError("chmod denied")),
            patch.object(claim.os, "fchmod", side_effect=PermissionError("fchmod denied")),
            pytest.raises(claim.ClaimStateError, match="unavailable"),
        ):
            _prepare_claim(claim, cfg, [])
        path.chmod(0o600)


def test_claim_state_preserves_existing_ownership():
    claim = _claim_module()
    alternate_groups = [group for group in os.getgroups() if group != os.getegid()]
    assert alternate_groups, "owner requires a supplementary group to distinguish ownership"
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        _prepare_claim(claim, cfg, [])
        path = Path(claim.claim_state_path(cfg))
        os.chown(path, -1, alternate_groups[0])
        before = path.stat()
        with claim.locked_first_admin_claim(cfg) as transaction:
            transaction.consume(now=1002.0)
        after = path.stat()
        assert (after.st_uid, after.st_gid) == (before.st_uid, before.st_gid)


def test_claim_uses_stable_private_flock_for_full_transaction_lifetime():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        _prepare_claim(claim, cfg, [])
        real_flock = claim.fcntl.flock
        flock_events = []

        def observed_flock(fd, operation):
            flock_events.append((fd, operation, os.path.realpath(f"/proc/self/fd/{fd}")))
            return real_flock(fd, operation)

        stable_paths = []
        for _attempt in range(2):
            before = len(flock_events)
            with patch.object(claim.fcntl, "flock", side_effect=observed_flock):
                with claim.locked_first_admin_claim(cfg) as transaction:
                    acquired = [event for event in flock_events[before:] if event[1] & claim.fcntl.LOCK_EX]
                    assert len(acquired) == 1
                    fd, _operation, lock_path = acquired[0]
                    stable_paths.append(lock_path)
                    assert not any(event[1] == claim.fcntl.LOCK_UN for event in flock_events[before:])
                    os.fstat(fd)  # the flock-owning descriptor spans the transaction body
                    assert transaction.state_name == "available"
                    assert Path(lock_path).is_file()
                    assert stat.S_IMODE(Path(lock_path).stat().st_mode) == 0o600
                    contender = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
                    try:
                        with pytest.raises(BlockingIOError):
                            real_flock(contender, claim.fcntl.LOCK_EX | claim.fcntl.LOCK_NB)
                    finally:
                        os.close(contender)
            with pytest.raises(OSError):
                os.fstat(fd)
            contender = os.open(lock_path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
            try:
                real_flock(contender, claim.fcntl.LOCK_EX | claim.fcntl.LOCK_NB)
                real_flock(contender, claim.fcntl.LOCK_UN)
            finally:
                os.close(contender)

        assert stable_paths[0] == stable_paths[1]
        assert "lock" in Path(stable_paths[0]).name


def test_claim_state_write_is_nofollow_same_directory_atomic_and_durable():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        events = []
        real_open = os.open
        real_fsync = os.fsync
        real_replace = os.replace

        def observed_open(path, flags, mode=0o777, *, dir_fd=None):
            events.append(("open", os.fspath(path), flags, mode))
            return real_open(path, flags, mode, dir_fd=dir_fd)

        def observed_fsync(fd):
            events.append(("fsync", os.fstat(fd).st_mode))
            return real_fsync(fd)

        def observed_replace(source, destination, *args, **kwargs):
            events.append(("replace", os.fspath(source), os.fspath(destination)))
            return real_replace(source, destination, *args, **kwargs)

        with (
            patch.object(claim.os, "open", side_effect=observed_open),
            patch.object(claim.os, "fsync", side_effect=observed_fsync),
            patch.object(claim.os, "replace", side_effect=observed_replace),
        ):
            _prepare_claim(claim, cfg, [])
        opens = [event for event in events if event[0] == "open"]
        assert opens
        assert all(event[2] & getattr(os, "O_NOFOLLOW", 0) for event in opens)
        created = [event for event in opens if event[2] & os.O_CREAT]
        assert created
        assert all(stat.S_IMODE(event[3]) == 0o600 for event in created)
        assert any("lock" in Path(event[1]).name for event in created)
        assert any(
            "lock" not in Path(event[1]).name and Path(event[1]).name != "first-admin-claim.json" for event in created
        )
        # Mutation 27 removed every post-replace directory fsync, yet the old
        # lifecycle-wide "some fsync later" assertion stayed green because
        # the next write's temporary-file fsync satisfied it. Keep this
        # adjacency per operation; future write-sequence changes must
        # strengthen this owner rather than restore that lifecycle-wide hole.
        replacement_indexes = [index for index, event in enumerate(events) if event[0] == "replace"]
        assert len(replacement_indexes) == 2
        for replacement_number, replace_index in enumerate(replacement_indexes):
            replacement = events[replace_index]
            assert Path(replacement[1]).parent == Path(replacement[2]).parent
            prior_replace_index = replacement_indexes[replacement_number - 1] if replacement_number else -1
            next_replace_index = (
                replacement_indexes[replacement_number + 1]
                if replacement_number + 1 < len(replacement_indexes)
                else len(events)
            )
            before = events[prior_replace_index + 1 : replace_index]
            after = events[replace_index + 1 : next_replace_index]
            assert any(
                event[0] == "fsync" and stat.S_ISREG(event[1])
                for event in before
            )
            assert any(
                event[0] == "fsync" and stat.S_ISDIR(event[1])
                for event in after
            )
        state_dir = Path(claim.claim_state_path(cfg)).parent
        assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
        for artifact in state_dir.iterdir():
            assert artifact.is_file() and not artifact.is_symlink()
            assert stat.S_IMODE(artifact.stat().st_mode) == 0o600


def test_claim_state_write_and_delivery_failures_surface_without_available_state():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        with (
            patch.object(claim.os, "replace", side_effect=OSError("replace failed")),
            pytest.raises(claim.ClaimStateError),
        ):
            _prepare_claim(claim, cfg, [])
        path = Path(claim.claim_state_path(cfg))
        if path.exists():
            assert json.loads(path.read_text(encoding="utf-8"))["state"] != "available"

    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)

        def failed_delivery(_claim_id, _secret, _generated_at):
            raise OSError("delivery failed")

        with pytest.raises(claim.ClaimStateError, match="delivery"):
            _prepare_claim(claim, cfg, [], deliver=failed_delivery)
        state = json.loads(Path(claim.claim_state_path(cfg)).read_text(encoding="utf-8"))
        assert state["state"] == "pending_delivery"


@pytest.mark.parametrize(
    ("username", "password", "field"),
    [("Bad User", "password-123", "username"), ("operator", "short", "password")],
)
def test_invalid_operator_fields_leave_claim_reusable(username, password, field):
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        body = {**_claim_body(secret), "username": username, "password": password}
        handler, store, _project = _invoke_create(cfg, [], secret, body=body)
        assert handler._status_code == 400
        assert (handler._captured["error"] or {})["field"] == field
        store.assert_not_called()
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "available"
            assert transaction.matches(secret)


def test_user_registry_failure_leaves_claim_reusable():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)

        def fail_save(_cfg, _users):
            return "registry unavailable"

        handler, _store, _project = _invoke_create(cfg, [], secret, save=fail_save)
        assert handler._status_code == 500
        assert _response_code(handler) == "operator_write_failed"
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "available"
            assert transaction.matches(secret)


def _invoke_create_with_lock_trace(*, setup_lock_available=True):
    _claim_module()
    events = []
    held = {"setup": False, "claim": False}

    class SetupLock:
        def acquire(self, blocking=True):
            assert not held["setup"] and not held["claim"]
            events.append(("setup-acquire", blocking, setup_lock_available))
            if not setup_lock_available:
                return False
            held["setup"] = True
            events.append(("setup-enter", True, False))
            return True

        def release(self):
            events.append(("setup-exit", held["setup"], held["claim"]))
            assert held["setup"] and not held["claim"]
            held["setup"] = False

    class Transaction:
        @property
        def state_name(self):
            events.append(("claim-state", held["setup"], held["claim"]))
            return "available"

        def matches(self, _candidate):
            events.append(("claim-compare", held["setup"], held["claim"]))
            return False

    @contextlib.contextmanager
    def claim_lock(_cfg):
        assert held["setup"] and not held["claim"]
        held["claim"] = True
        events.append(("claim-enter", held["setup"], held["claim"]))
        try:
            yield Transaction()
        finally:
            events.append(("claim-exit", held["setup"], held["claim"]))
            held["claim"] = False

    def observe_marker(_cfg):
        events.append(("marker", held["setup"], held["claim"]))
        return False

    def observe_users(_cfg):
        events.append(("users", held["setup"], held["claim"]))
        return []

    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        handler = _capturing_handler(_claim_body("wrong-claim"))
        with (
            patch.object(serve, "_setup_lock", SetupLock()),
            patch("freq.modules.serve.locked_first_admin_claim", side_effect=claim_lock, create=True),
            patch("freq.modules.serve._request_is_https", return_value=True),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._setup_marker_exists", side_effect=observe_marker),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._load_users", side_effect=observe_users),
            patch("freq.modules.serve._setup_store_admin_password") as store,
            patch("freq.modules.serve._save_users_error") as save,
            patch("freq.modules.serve.ensure_setup_state") as setup_state,
            patch("freq.modules.serve._setup_session_payload") as session,
            patch.object(serve, "_first_admin_claim_limiter", _fresh_limiter()),
        ):
            handler._serve_setup_create_admin()
        store.assert_not_called()
        save.assert_not_called()
        setup_state.assert_not_called()
        session.assert_not_called()
        if setup_lock_available:
            assert handler._status_code == 403
        else:
            assert handler._status_code == 409
            assert _response_code(handler) == "setup_busy"
    assert held == {"setup": False, "claim": False}
    return events


def test_create_admin_acquires_setup_then_claim_lock_in_order():
    events = _invoke_create_with_lock_trace()
    names = [event[0] for event in events]
    assert events[0] == ("setup-acquire", False, True)
    assert names.index("setup-enter") < names.index("claim-enter")
    assert names.index("claim-enter") < names.index("claim-exit") < names.index("setup-exit")


def test_create_admin_setup_lock_busy_is_nonblocking_and_never_enters_claim_or_mutation():
    events = _invoke_create_with_lock_trace(setup_lock_available=False)
    assert events == [("setup-acquire", False, False)]


def test_create_admin_reobserves_marker_and_users_inside_both_locks_before_claim_state():
    events = _invoke_create_with_lock_trace()
    fully_locked = [event for event in events if event[1:] == (True, True)]
    assert any(event[0] == "marker" for event in fully_locked)
    assert any(event[0] == "users" for event in fully_locked)
    names = [event[0] for event in events]
    claim_truth = min(names.index("claim-state"), names.index("claim-compare"))
    locked_marker = next(index for index, event in enumerate(events) if event == ("marker", True, True))
    locked_users = next(index for index, event in enumerate(events) if event == ("users", True, True))
    assert names.index("claim-enter") < locked_marker < claim_truth
    assert names.index("claim-enter") < locked_users < claim_truth


def test_session_projection_failure_after_commit_does_not_reopen_claim():
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        registry = []
        handler = _capturing_handler(_claim_body(secret))
        stack, _store, project = _runtime_patches(cfg, registry)
        project.side_effect = RuntimeError("session projection failed")
        with stack:
            handler._serve_setup_create_admin()
        assert [user["username"] for user in registry] == ["operator"]
        with claim.locked_first_admin_claim(cfg) as transaction:
            assert transaction.state_name == "consumed"
            assert transaction.matches(secret) is False
        replay, second_store, _project = _invoke_create(cfg, registry, secret)
        assert replay._status_code == 409
        assert _response_code(replay) == "operator_exists"
        second_store.assert_not_called()


def _assert_create_admin_rejection_has_no_claim_surface(cfg, secret, body):
    """Inspect the complete public/error surface without emitting claim bytes."""
    log_records = []

    def capture_log(level, message, **extra):
        log_records.append({"level": level, "message": message, "extra": extra})

    with patch.object(serve.logger, "_write", side_effect=capture_log):
        handler, store, project = _invoke_create(cfg, [], secret, body=body)
        wire, headers = _serialize_with_real_freq_handler(handler._captured, handler._status_code)
    surface = json.dumps(
        {
            "helper_payload": handler._captured,
            "wire_body": wire,
            "wire_headers": headers,
            "logs": log_records,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    secret_digest = hashlib.sha256(
        b"pve-freq-first-admin-claim-v1\0" + secret.encode("utf-8")
    ).hexdigest()
    if secret in surface:
        pytest.fail("secret-safe rejection violated: secret_present=True")
    if secret_digest in surface:
        pytest.fail("secret-safe rejection violated: digest_present=True")
    assert len(hashlib.sha256(surface.encode("utf-8")).hexdigest()) == 64
    store.assert_not_called()
    project.assert_not_called()
    return handler


def test_create_admin_schema_rejection_never_reflects_live_claim():
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        body = _claim_body(secret)
        body["schema"] = secret
        handler = _assert_create_admin_rejection_has_no_claim_surface(cfg, secret, body)
        assert handler._status_code == 400
        assert _response_code(handler) == "unsupported_schema"


def test_create_admin_unknown_key_rejection_never_reflects_live_claim():
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        body = _claim_body(secret)
        body[secret] = True
        handler = _assert_create_admin_rejection_has_no_claim_surface(cfg, secret, body)
        assert handler._status_code == 400
        assert _response_code(handler) == "unsupported_field"


@pytest.mark.parametrize(
    "shape",
    ("schema", "unknown_key", "wrong_typed_claim", "nested_value", "duplicated_fields"),
)
def test_create_admin_malformed_shape_matrix_never_projects_submitted_claim(shape):
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        body = _claim_body(secret)
        if shape == "schema":
            body["schema"] = secret
        elif shape == "unknown_key":
            body[secret] = {"ignored": True}
        elif shape == "wrong_typed_claim":
            body["claim_secret"] = {"nested": secret}
        elif shape == "nested_value":
            body["password"] = {"nested": [secret]}
        else:
            body["username"] = secret
            body["password"] = secret
        handler = _assert_create_admin_rejection_has_no_claim_surface(cfg, secret, body)
        assert handler._status_code == 400


def test_create_admin_template_api_accepts_no_arbitrary_projection_data():
    boundary = getattr(serve, "_create_admin_error", None)
    if boundary is None:
        pytest.fail("structural red: centralized create-admin error boundary is absent")
    with tempfile.TemporaryDirectory() as root:
        _claim, _cfg_value, _metadata, secret = _seeded_claim(root)
        handler = _capturing_handler(_claim_body(secret))
        with pytest.raises(TypeError):
            boundary(handler, "claim_secret_invalid", details=[{"submitted": secret}])
        assert handler._captured is None
        boundary(handler, "claim_secret_invalid")
        surface = json.dumps(handler._captured, sort_keys=True, ensure_ascii=False)
        if secret in surface:
            pytest.fail("closed template API violated: secret_present=True")
        assert handler._status_code == 403
        _assert_exact_stable_claim_failure(
            handler._captured,
            code="claim_secret_invalid",
            field="claim_secret",
            retryable=True,
        )


def test_create_admin_shipped_boundary_blocks_future_reflective_validator():
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        body = _claim_body(secret)
        with patch.object(
            serve,
            "_setup_forbidden_browser_input",
            return_value=(secret, "future_validation_error"),
        ):
            handler = _assert_create_admin_rejection_has_no_claim_surface(cfg, secret, body)
        assert handler._status_code == 500
        assert _response_code(handler) == "response_projection_blocked"


def _invoke_short_claim_with_observed_logs(cfg, candidate, limiter):
    log_records = []

    def capture_log(level, message, **extra):
        log_records.append({"level": level, "message": message, "extra": extra})

    with (
        patch.object(serve, "_first_admin_claim_limiter", limiter),
        patch.object(serve.logger, "_write", side_effect=capture_log),
    ):
        handler, store, project = _invoke_create(cfg, [], candidate)
        wire, headers = _serialize_with_real_freq_handler(handler._captured, handler._status_code)
    return handler, wire, headers, log_records, store, project


def test_short_collision_candidates_share_exact_403_without_critical_or_reflection():
    observed = []
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, _secret = _seeded_claim(root)
        for candidate in ("a", "e", "z", "-", "1"):
            handler, wire, headers, logs, store, project = _invoke_short_claim_with_observed_logs(
                cfg,
                candidate,
                _fresh_limiter(),
            )
            assert handler._status_code == 403
            _assert_exact_stable_claim_failure(
                handler._captured,
                code="claim_secret_invalid",
                field="claim_secret",
                retryable=True,
            )
            _assert_exact_public_claim_failure(
                wire,
                headers,
                code="claim_secret_invalid",
                field="claim_secret",
                retryable=True,
                client_request_id="12345678-1234-4123-8123-123456789abc",
            )
            assert not any(record["level"] == "CRITICAL" for record in logs)
            store.assert_not_called()
            project.assert_not_called()
            observed.append(json.dumps(handler._captured, sort_keys=True))
        assert len(set(observed)) == 1


def test_short_collision_candidates_preserve_exact_saturated_429_without_critical():
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, _secret = _seeded_claim(root)
        for candidate in ("a", "e", "z", "-", "1"):
            limiter = _fresh_limiter()
            for _attempt in range(5):
                limiter.record_invalid("192.0.2.44")
            handler, wire, headers, logs, store, project = _invoke_short_claim_with_observed_logs(
                cfg,
                candidate,
                limiter,
            )
            assert handler._status_code == 429
            _assert_exact_stable_claim_failure(
                handler._captured,
                code="claim_rate_limited",
                field=None,
                retryable=True,
            )
            _assert_exact_public_claim_failure(
                wire,
                headers,
                code="claim_rate_limited",
                field=None,
                retryable=True,
                client_request_id="12345678-1234-4123-8123-123456789abc",
            )
            assert not any(record["level"] == "CRITICAL" for record in logs)
            store.assert_not_called()
            project.assert_not_called()


def test_unapproved_create_admin_template_fails_closed_without_projection():
    templates = getattr(serve, "_CREATE_ADMIN_ERROR_TEMPLATES", None)
    if templates is None:
        pytest.fail("structural red: closed create-admin error templates are absent")
    with tempfile.TemporaryDirectory() as root:
        _claim, _cfg_value, _metadata, secret = _seeded_claim(root)
        handler = _capturing_handler(_claim_body(secret))
        log_records = []
        with patch.object(
            serve.logger,
            "_write",
            side_effect=lambda level, message, **extra: log_records.append(
                {"level": level, "message": message, "extra": extra}
            ),
        ):
            serve._create_admin_error(handler, secret)
        surface = json.dumps(handler._captured, sort_keys=True, ensure_ascii=False)
        if secret in surface:
            pytest.fail("unapproved template violated: secret_present=True")
        assert handler._status_code == 500
        assert _response_code(handler) == "response_projection_blocked"
        assert [record["level"] for record in log_records] == ["CRITICAL"]


@pytest.mark.parametrize(
    ("scenario", "status", "code", "field", "retryable"),
    tuple(
        (item["scenario"], int(item["status"]), item["code"], item["field"], item["retryable"])
        for item in CREATE_ADMIN_FAILURE_CONTRACT
        if item["runtime"]
    ),
)
def test_claim_failures_publish_exact_stable_envelopes_without_reflection(scenario, status, code, field, retryable):
    claim = _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        candidate = "Reflect-Me-Exactly"
        body = _claim_body(candidate)
        registry = []
        invoke_options = {}
        if scenario == "missing":
            body.pop("claim_secret")
        elif scenario == "https":
            body = _claim_body(secret)
            invoke_options["is_https"] = False
        elif scenario == "setup_closed":
            body = _claim_body(secret)
            invoke_options["setup_complete"] = True
        elif scenario == "operator_exists":
            body = _claim_body(secret)
            registry.append({"username": "operator", "role": "admin"})
        elif scenario == "consumed":
            with claim.locked_first_admin_claim(cfg) as transaction:
                transaction.consume(now=1002.0)
        elif scenario == "unavailable":
            Path(claim.claim_state_path(cfg)).write_text("not-json", encoding="utf-8")
        rate_context = contextlib.nullcontext()
        if scenario == "rate":
            limiter = _fresh_limiter()
            for _attempt in range(5):
                limiter.record_invalid("192.0.2.44")
            rate_context = patch.object(serve, "_first_admin_claim_limiter", limiter)
        headers = {"Content-Type": "text/plain"} if scenario == "unsupported_media" else None
        setup_lock_context = contextlib.nullcontext()
        if scenario == "setup_busy":

            class BusySetupLock:
                def acquire(self, blocking=True):
                    assert blocking is False
                    return False

                def release(self):
                    raise AssertionError("busy setup lock must not be released by the rejected caller")

            setup_lock_context = patch.object(serve, "_setup_lock", BusySetupLock())
        with rate_context, setup_lock_context:
            handler, store, project = _invoke_create(
                cfg,
                registry,
                candidate,
                headers=headers,
                body=body,
                **invoke_options,
            )
        assert handler._status_code == status
        payload = handler._captured
        _assert_exact_stable_claim_failure(payload, code=code, field=field, retryable=retryable)
        client_request_id = body.get("client_request_id", "") if isinstance(body, dict) else ""
        wire, wire_headers = _serialize_with_real_freq_handler(payload, status)
        _assert_exact_public_claim_failure(
            wire,
            wire_headers,
            code=code,
            field=field,
            retryable=retryable,
            client_request_id=client_request_id,
        )

        # The helper and wire sets are separately closed. Removing the adapter
        # field breaks only the wire owner; adding it prematurely breaks only
        # the helper owner while a correctly correlated wire remains valid.
        missing_wire_request_id = copy.deepcopy(wire)
        del missing_wire_request_id["request_id"]
        with pytest.raises(AssertionError):
            _assert_exact_public_claim_failure(
                missing_wire_request_id,
                wire_headers,
                code=code,
                field=field,
                retryable=retryable,
                client_request_id=client_request_id,
            )
        _assert_exact_stable_claim_failure(payload, code=code, field=field, retryable=retryable)

        premature_helper_request_id = {**payload, "request_id": SERVER_REQUEST_ID}
        with pytest.raises(AssertionError):
            _assert_exact_stable_claim_failure(
                premature_helper_request_id,
                code=code,
                field=field,
                retryable=retryable,
            )
        premature_wire, premature_headers = _serialize_with_real_freq_handler(premature_helper_request_id, status)
        _assert_exact_public_claim_failure(
            premature_wire,
            premature_headers,
            code=code,
            field=field,
            retryable=retryable,
            client_request_id=client_request_id,
        )

        for invalid_request_id in (
            "",
            7,
            "0A1B2C3D4E5F",
            "0a1b2c3d4e5",
            "12345678-1234-4123-8123-123456789abc",
        ):
            invalid_wire = {**wire, "request_id": invalid_request_id}
            with pytest.raises(AssertionError):
                _assert_exact_public_claim_failure(
                    invalid_wire,
                    wire_headers,
                    code=code,
                    field=field,
                    retryable=retryable,
                    client_request_id=client_request_id,
                )
        mismatched_headers = {**wire_headers, "x-request-id": "f0e1d2c3b4a5"}
        with pytest.raises(AssertionError):
            _assert_exact_public_claim_failure(
                wire,
                mismatched_headers,
                code=code,
                field=field,
                retryable=retryable,
                client_request_id=client_request_id,
            )
        fifth_wire_property = {**wire, "claim_state": "internal-metadata-must-fail"}
        with pytest.raises(AssertionError):
            _assert_exact_public_claim_failure(
                fifth_wire_property,
                wire_headers,
                code=code,
                field=field,
                retryable=retryable,
                client_request_id=client_request_id,
            )
        inner_mutated = copy.deepcopy(payload)
        inner_mutated["error"]["digest"] = "internal-metadata-must-fail"
        with pytest.raises(AssertionError):
            _assert_exact_stable_claim_failure(inner_mutated, code=code, field=field, retryable=retryable)
        outer_mutated = {**payload, "claim_state": "internal-metadata-must-fail"}
        with pytest.raises(AssertionError):
            _assert_exact_stable_claim_failure(outer_mutated, code=code, field=field, retryable=retryable)
        rendered = json.dumps(payload)
        assert candidate not in rendered
        assert secret not in rendered
        assert claim.claim_state_path(cfg) not in rendered
        for value in (candidate, secret):
            digest = hashlib.sha256(b"pve-freq-first-admin-claim-v1\0" + value.encode("utf-8")).hexdigest()
            assert digest not in rendered
        store.assert_not_called()
        project.assert_not_called()
        if scenario == "rate":
            with claim.locked_first_admin_claim(cfg) as transaction:
                assert transaction.state_name == "available"
                assert transaction.matches(secret)


def test_openapi_create_admin_publishes_write_only_secrets_and_stable_failures():
    from tests.test_openapi_truth import _get_openapi_spec

    # This is deliberately a governed F4 subset, not a claim that the design
    # exhaustively enumerates every inherited create-admin validation failure.
    # Truthful additional documented branches are allowed; governed codes must
    # each occur exactly once at their cited status with exact wrapper shapes.
    governed = {}
    for item in CREATE_ADMIN_FAILURE_CONTRACT:
        governed.setdefault(item["status"], {})[item["code"]] = (item["retryable"], item["field"])

    def validate(operation):
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        for field in ("password", "claim_secret"):
            assert request_schema["properties"][field]["writeOnly"] is True
            assert request_schema["properties"][field]["format"] == "password"

        observed_governed = {}
        for status, response in operation["responses"].items():
            content = response.get("content", {}).get("application/json")
            if not content or "schema" not in content:
                continue
            schema = content["schema"]
            branches = schema.get("oneOf", ())
            for branch in branches:
                properties = branch.get("properties", {})
                error_properties = properties.get("error", {}).get("properties", {})
                code = error_properties.get("code", {}).get("const")
                if code not in {item["code"] for item in CREATE_ADMIN_FAILURE_CONTRACT}:
                    continue
                assert code not in observed_governed
                observed_governed[code] = status

        for status, expected_codes in governed.items():
            schema = operation["responses"][status]["content"]["application/json"]["schema"]
            branches = schema["oneOf"]
            observed = {}
            for branch in branches:
                branch_properties = branch.get("properties", {})
                error_properties = branch_properties.get("error", {}).get("properties", {})
                code = error_properties.get("code", {}).get("const")
                if code not in expected_codes:
                    continue
                assert branch["type"] == "object"
                assert branch["additionalProperties"] is False
                assert set(branch["required"]) == set(PUBLIC_ERROR_OUTER_PROPERTIES)
                assert set(branch_properties) == set(PUBLIC_ERROR_OUTER_PROPERTIES)
                assert branch_properties["ok"]["type"] == "boolean"
                assert branch_properties["ok"]["const"] is False
                assert branch_properties["schema"]["type"] == "string"
                assert branch_properties["schema"]["const"] == SCHEMA
                assert branch_properties["request_id"]["type"] == "string"
                assert branch_properties["request_id"]["minLength"] == 12
                assert branch_properties["request_id"]["maxLength"] == 12
                assert branch_properties["request_id"]["pattern"] == "^[0-9a-f]{12}$"
                error = branch["properties"]["error"]
                assert error["type"] == "object"
                assert error["additionalProperties"] is False
                properties = error["properties"]
                retryable, field = expected_codes[code]
                expected_properties = set(ERROR_ENVELOPE_BASE_PROPERTIES)
                if field is not None:
                    expected_properties.add("field")
                assert set(properties) == expected_properties
                assert set(error["required"]) == expected_properties
                assert properties["message"]["type"] == "string"
                assert code not in observed
                assert properties["retryable"]["const"] is retryable
                if field is None:
                    assert "field" not in properties
                else:
                    assert properties["field"]["const"] == field
                observed[code] = (retryable, field)
            assert observed == expected_codes
        assert observed_governed == {item["code"]: item["status"] for item in CREATE_ADMIN_FAILURE_CONTRACT}

    operation = _get_openapi_spec()["paths"]["/api/setup/create-admin"]["post"]
    validate(operation)

    def governed_branch(operation, status, code):
        branches = operation["responses"][status]["content"]["application/json"]["schema"]["oneOf"]
        return next(
            branch for branch in branches if branch["properties"]["error"]["properties"]["code"]["const"] == code
        )

    moved_code = copy.deepcopy(operation)
    source = moved_code["responses"]["403"]["content"]["application/json"]["schema"]["oneOf"]
    destination = moved_code["responses"]["409"]["content"]["application/json"]["schema"]["oneOf"]
    moved_index = next(
        index
        for index, branch in enumerate(source)
        if branch["properties"]["error"]["properties"]["code"]["const"] == "claim_secret_invalid"
    )
    destination.append(source.pop(moved_index))
    with pytest.raises(AssertionError):
        validate(moved_code)

    readable_secret = copy.deepcopy(operation)
    readable_secret["requestBody"]["content"]["application/json"]["schema"]["properties"]["claim_secret"][
        "writeOnly"
    ] = False
    with pytest.raises(AssertionError):
        validate(readable_secret)

    digest_property = copy.deepcopy(operation)
    digest_error = governed_branch(digest_property, "400", "claim_secret_required")["properties"]["error"]
    digest_error["properties"]["digest"] = {"type": "string"}
    digest_error["required"].append("digest")
    with pytest.raises(AssertionError):
        validate(digest_property)

    outer_property = copy.deepcopy(operation)
    outer_branch = governed_branch(outer_property, "403", "claim_secret_invalid")
    outer_branch["properties"]["digest"] = {"type": "string"}
    outer_branch["required"].append("digest")
    with pytest.raises(AssertionError):
        validate(outer_property)

    for removed_property in ("schema", "request_id"):
        removed_outer = copy.deepcopy(operation)
        removed_branch = governed_branch(removed_outer, "403", "claim_secret_invalid")
        del removed_branch["properties"][removed_property]
        removed_branch["required"].remove(removed_property)
        with pytest.raises(AssertionError):
            validate(removed_outer)

    nonstring_request_id = copy.deepcopy(operation)
    nonstring_branch = governed_branch(nonstring_request_id, "403", "claim_secret_invalid")
    nonstring_branch["properties"]["request_id"] = {"type": "integer", "minimum": 0}
    with pytest.raises(AssertionError):
        validate(nonstring_request_id)

    duplicate_governed = copy.deepcopy(operation)
    duplicate_branches = duplicate_governed["responses"]["403"]["content"]["application/json"]["schema"]["oneOf"]
    duplicate_branches.append(copy.deepcopy(governed_branch(duplicate_governed, "403", "claim_secret_invalid")))
    with pytest.raises(AssertionError):
        validate(duplicate_governed)

    inherited_addition = copy.deepcopy(operation)
    inherited_branch = copy.deepcopy(governed_branch(inherited_addition, "400", "claim_secret_required"))
    inherited_error = inherited_branch["properties"]["error"]
    inherited_error["properties"]["code"]["const"] = "invalid_username"
    inherited_error["properties"]["field"]["const"] = "username"
    inherited_addition["responses"]["400"]["content"]["application/json"]["schema"]["oneOf"].append(inherited_branch)
    validate(inherited_addition)

    media_branch_control = copy.deepcopy(operation)
    media_branches = media_branch_control["responses"]["400"]["content"]["application/json"]["schema"]["oneOf"]
    media_index = next(
        index
        for index, branch in enumerate(media_branches)
        if branch["properties"]["error"]["properties"]["code"]["const"] == "unsupported_media_type"
    )
    media_branch = media_branches.pop(media_index)
    with pytest.raises(AssertionError):
        validate(media_branch_control)
    media_branches.append(media_branch)
    validate(media_branch_control)


def test_setup_consumer_executes_code_specific_claim_guidance():
    from tests.test_setup_schema_table import _js_function

    js = (REPO_ROOT / "freq/data/web/js/setup.js").read_text(encoding="utf-8")
    guidance = _js_function(js, "claimFailureGuidance")
    codes = tuple(item["code"] for item in CLAIM_GUIDANCE_CONTRACT)
    unknown_code = "future_ungoverned_code"
    script = (
        guidance
        + "\nconst codes="
        + json.dumps(codes)
        + ";const out={};for(const code of codes){out[code]=claimFailureGuidance(code);}"
        + "out.__unknown=claimFailureGuidance("
        + json.dumps(unknown_code)
        + ");process.stdout.write(JSON.stringify(out));"
    )
    result = subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
    observed = json.loads(result.stdout)
    unknown = observed.pop("__unknown")

    for benign in CONSUMER_BENIGN_MESSAGE_CONTROLS:
        for shape in CONSUMER_FORBIDDEN_SHAPE_CONTRACT:
            assert re.search(shape["pattern"], benign, re.IGNORECASE) is None

    def validate_guidance(items):
        assert set(items) == set(codes)
        for contract in CLAIM_GUIDANCE_CONTRACT:
            guidance_item = items[contract["code"]]
            assert set(guidance_item) == {"message", "action", "focus", "retryable", "terminal"}
            assert guidance_item["action"] == contract["action"]
            assert guidance_item["focus"] == contract["focus"]
            assert guidance_item["retryable"] is contract["retryable"]
            assert guidance_item["terminal"] is contract["terminal"]
            message = guidance_item["message"]
            assert isinstance(message, str) and message
            message_lower = message.lower()
            for token in contract["message_tokens"]:
                assert token in message_lower
            for fragment in CONSUMER_INTERNAL_FRAGMENTS:
                assert fragment not in message_lower
            for shape in CONSUMER_FORBIDDEN_SHAPE_CONTRACT:
                assert re.search(shape["pattern"], message, re.IGNORECASE) is None

    validate_guidance(observed)
    assert unknown.get("action") is None
    assert unknown.get("focus") is None
    for code in codes:
        mutated = copy.deepcopy(observed)
        mutated[code]["digest"] = "internal-metadata-must-fail"
        with pytest.raises(AssertionError):
            validate_guidance(mutated)
        for shape in CONSUMER_FORBIDDEN_SHAPE_CONTRACT:
            shaped = copy.deepcopy(observed)
            shaped[code]["message"] += " " + shape["witness"]
            with pytest.raises(AssertionError):
                validate_guidance(shaped)

    consumed_focus_mutations = ("operator-claim", "resume-sign-in", "generic-fallback")
    for focus in consumed_focus_mutations:
        mutated = copy.deepcopy(observed)
        mutated["claim_consumed"]["focus"] = focus
        with pytest.raises(AssertionError):
            validate_guidance(mutated)


def test_setup_consumer_operator_exists_preserves_resume_handoff():
    from tests.test_setup_schema_table import _js_function

    js = (REPO_ROOT / "freq/data/web/js/setup.js").read_text(encoding="utf-8")
    html = (REPO_ROOT / "freq/data/web/setup.html").read_text(encoding="utf-8")
    create = _js_function(js, "createOperator")
    assert "operator_exists" in create
    assert "resume-session" in create
    focus = OPERATOR_EXISTS_GUIDANCE_CONTRACT["focus"]
    link_match = re.search(
        rf"<a\b(?=[^>]*\bid=[\"']{re.escape(focus)}[\"'])(?=[^>]*\bhref=[\"']/[\"'])[^>]*>(.*?)</a>",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    assert link_match, "resume-sign-in must be the existing root-destination link"

    def validate_visible_copy(raw_html):
        normalized = " ".join(re.sub(r"<[^>]+>", " ", raw_html).split())
        assert normalized == "Open sign in"

    validate_visible_copy(link_match.group(1))
    with pytest.raises(AssertionError):
        validate_visible_copy("Continue to sign in")


def test_shipped_product_has_no_remote_claim_recovery_or_test_bypass_surface():
    production_paths = sorted(
        path for path in (REPO_ROOT / "freq").rglob("*") if path.suffix in {".py", ".js", ".html"}
    )
    production = {path: path.read_text(encoding="utf-8") for path in production_paths}
    joined = "\n".join(production.values())

    route_literals = set(re.findall(r"['\"](/api/[^'\"]+)['\"]", joined))
    for route in route_literals:
        lowered = route.lower()
        assert "claim" not in lowered and "first-admin" not in lowered, route
    assert {route for route in route_literals if route.startswith("/api/setup/")} == {
        "/api/setup/complete",
        "/api/setup/configure",
        "/api/setup/contract",
        "/api/setup/create-admin",
        "/api/setup/device-credentials",
        "/api/setup/discovery/start",
        "/api/setup/discovery/status",
        "/api/setup/generate-key",
        "/api/setup/init/cancel",
        "/api/setup/init/logs",
        "/api/setup/init/start",
        "/api/setup/init/status",
        "/api/setup/reset",
        "/api/setup/status",
        "/api/setup/test-ssh",
    }

    serve_source = (REPO_ROOT / "freq/modules/serve.py").read_text(encoding="utf-8")
    serve_tree = ast.parse(serve_source)
    claim_state_tokens = ("locked_first_admin_claim", "prepare_first_admin_claim", "claim_state_path")
    claim_touching_functions = set()
    for node in ast.walk(serve_tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(serve_source, node) or ""
            if any(token in segment for token in claim_state_tokens):
                claim_touching_functions.add(node.name)
    assert claim_touching_functions <= {"cmd_serve", "_serve_setup_create_admin"}

    for forbidden in (
        "PVE_FREQ_F4_SECRET_AUDIT_FILE",
        "PVE_FREQ_F4_EVIDENCE_XML",
        "FIRST_ADMIN_CLAIM_TEST_SECRET",
        "fixture-raw-secret",
    ):
        assert forbidden not in joined
    assert re.search(r"add_argument\([^\n]*claim", joined, re.IGNORECASE) is None


def test_raw_claim_is_excluded_from_every_observable_product_channel(capsys):
    _claim_module()
    with tempfile.TemporaryDirectory() as root:
        _claim, cfg, _metadata, secret = _seeded_claim(root)
        registry = []
        handler = _capturing_handler(_claim_body(secret))
        logs = []

        def record(*args, **kwargs):
            logs.append((args, kwargs))

        stack, _store, project = _runtime_patches(cfg, registry)
        with stack, contextlib.ExitStack() as log_stack:
            for level in ("debug", "info", "warn", "warning", "error", "critical"):
                if hasattr(serve.logger, level):
                    log_stack.enter_context(patch.object(serve.logger, level, side_effect=record))
            handler._begin_request()
            handler._serve_setup_create_admin()
            handler._finish_request()
        captured = capsys.readouterr()
        state_bytes = b"".join(path.read_bytes() for path in Path(root).rglob("*") if path.is_file())
        observable = json.dumps(
            {
                "response": handler._captured,
                "logs": logs,
                "session_projection": project.call_args_list,
                "stdout": captured.out,
                "stderr": captured.err,
            },
            default=str,
        )
        assert secret not in observable
        assert secret.encode() not in state_bytes
        assert handler._status_code == 200


def test_runbook_publishes_exact_local_reset_commands_without_remote_path_disclosure():
    docs = {
        path: (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in ("docs/API-REFERENCE.md", "docs/ZERO-STATE-WEB-API-CONTRACT.md")
    }
    joined = "\n".join(docs.values())
    for command in (
        "sudo systemctl stop pve-freq-setup.service",
        "sudo rm -- /opt/pve-freq/data/setup/first-admin-claim.json",
        "sudo systemctl start pve-freq-setup.service",
    ):
        assert command in joined
    assert "custom FREQ_DIR" in joined
    assert "data/setup/first-admin-claim.json" in joined
    operation = docs["docs/API-REFERENCE.md"].split("/api/setup/create-admin", 1)[1]
    invalid_guidance = operation.split("claim_secret_invalid", 1)[1].split("\n##", 1)[0]
    assert "/opt/pve-freq" not in invalid_guidance
    assert "most recently emitted claim" in invalid_guidance
    assert "zero-state runbook" in invalid_guidance


def test_human_contract_publishes_exact_serialized_error_envelope():
    document = (REPO_ROOT / "docs/ZERO-STATE-WEB-API-CONTRACT.md").read_text(encoding="utf-8")
    section_match = re.search(r"(?ms)^### Error envelope\s*$\n(.*?)(?=^##\s|\Z)", document)
    assert section_match, "human contract must publish a bounded error-envelope section"
    error_section = section_match.group(1)
    match = re.search(r"```json\s*(\{.*?\})\s*```", error_section, flags=re.DOTALL)
    assert match, "human contract must publish a JSON error-envelope example"
    example = json.loads(match.group(1))

    def validate(payload):
        assert set(payload) == set(PUBLIC_ERROR_OUTER_PROPERTIES)
        assert payload["ok"] is False
        assert payload["schema"] == SCHEMA
        assert isinstance(payload["error"], dict) and payload["error"]
        assert re.fullmatch(r"[0-9a-f]{12}", payload["request_id"])

    validate(example)
    assert "serialized public" in error_section.lower()
    assert "X-Request-ID" in error_section

    helper_only = {key: copy.deepcopy(example[key]) for key in SETUP_ERROR_HELPER_OUTER_PROPERTIES}
    with pytest.raises(AssertionError):
        validate(helper_only)
    fifth_property = {**example, "client_request_id": "must-not-be-public-correlation"}
    with pytest.raises(AssertionError):
        validate(fifth_property)
