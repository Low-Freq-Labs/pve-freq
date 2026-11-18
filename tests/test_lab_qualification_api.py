"""Original dispatcher/auth/publisher with fictional qualification ports only."""
import copy
import importlib
import io
import json
import re
import socket
import subprocess
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.api import auth
from freq.modules import serve
from tests.test_lab_guest_api import CSRF, TOKEN, handler, response, session


PATH = "/api/lab/window"
TARGET = "1" * 32
BASE_REVISION = "a" * 64
POLICY_REVISION = "b" * 64
WINDOW = "2" * 32


def intent(**changes):
    return {"target_ref": TARGET, "configuration_revision": BASE_REVISION,
            "policy_revision": POLICY_REVISION, "request_key": "fictional-window-intent", **changes}


def metadata():
    return {"schema": "pve-freq-lab-window-v1", "target": {
        "ref": TARGET, "configuration_revision": BASE_REVISION, "estate": "fictional-estate",
        "source": "pve.example.invalid", "node": "fictional-node", "kind": "qemu", "vmid": 120,
        "name": "fictional-qualified-guest"},
        "policy": {"enabled": True, "revision": POLICY_REVISION, "duration_seconds": 900,
                   "audience": "original_session"},
        "window": None, "busy": False, "can_request": True, "reason": None}


@pytest.fixture
def qualification(monkeypatch):
    for owner, name in ((socket, "socket"), (socket, "create_connection"), (subprocess, "Popen")):
        monkeypatch.setattr(owner, name, Mock(side_effect=AssertionError("native effects forbidden")))
    module = importlib.import_module("freq.api.lab_qualification")
    monkeypatch.setattr(auth, "_auth_tokens", {TOKEN: session("admin")})
    monkeypatch.setattr(auth, "_auth_lock", threading.RLock())
    monkeypatch.setattr(auth, "request_is_https", lambda value: value._test_https)
    monkeypatch.setattr(serve.FreqHandler, "_ROUTE_REGISTRY", None)
    case = SimpleNamespace(module=module, cfg=SimpleNamespace(conf_dir="/fictional/conf", data_dir="/fictional/data"),
                           calls=[], constructors=[], dto=metadata(), owner=None, hook=None, status=201,
                           window={"ref": WINDOW, "state": "active", "registration_revision": "c" * 64,
                                   "qualified_at": "2026-11-13T12:00:00Z", "expires_at": "2026-11-13T12:15:00Z",
                                   "error": None})

    class Service:
        def __init__(self, cfg, *, still_current):
            assert cfg is case.cfg
            assert callable(still_current)
            self.current = still_current
            case.constructors.append(self)

        def inspect(self, actor, *, can_request):
            assert self.current() is True
            assert type(can_request) is bool
            case.calls.append(("inspect", actor, can_request))
            if case.hook:
                case.hook(self)
            dto = copy.deepcopy(case.dto)
            dto["can_request"] = can_request and dto["can_request"]
            if case.owner is not None:
                dto["window"] = copy.deepcopy(case.window) if case.owner == actor else None
                if case.owner == actor:
                    dto["can_request"] = False
            return dto

        def qualify(self, actor, body, *, can_request=True):
            assert self.current() is True
            assert can_request is True
            case.calls.append(("qualify", actor, copy.deepcopy(body), can_request))
            case.owner = actor
            if case.hook:
                case.hook(self)
            dto = copy.deepcopy(case.dto)
            dto.update(window=copy.deepcopy(case.window), can_request=False)
            return dto, case.status

    monkeypatch.setattr(module, "LabPowerQualification", Service)
    case.load = Mock(return_value=case.cfg)
    monkeypatch.setattr(module, "load_config", case.load)
    return case


@pytest.mark.parametrize("role,can_request", [("viewer", False), ("operator", False), ("admin", True), ("protected", True)])
def test_get_all_cookie_roles_returns_metadata_without_revoking_legitimate_reader(qualification, role, can_request):
    original = auth._auth_tokens[TOKEN]
    original["role"] = role
    value = handler(PATH)
    value._dispatch()
    body, status = response(value)
    assert status == 200
    expected = metadata()
    expected["can_request"] = can_request
    assert body == expected
    assert auth._auth_tokens.get(TOKEN) is original
    assert qualification.calls[0][0] == "inspect" and qualification.calls[0][2] is can_request
    assert re.fullmatch(r"[0-9a-f]{64}", qualification.calls[0][1])
    assert qualification.calls[0][1] not in (TOKEN, original["user"])
    headers = {call.args[0].lower(): call.args[1] for call in value.send_header.call_args_list}
    assert headers["cache-control"] == "no-store"
    assert int(headers["content-length"]) == len(value.wfile.getvalue())
    assert not any(call[0] == "qualify" for call in qualification.calls)


@pytest.mark.parametrize("role", ["admin", "protected"])
@pytest.mark.parametrize("status,state", [(201, "active"), (202, "preparing"), (200, "active"), (409, "rejected")])
def test_post_preserves_exact_service_dto_status_and_four_field_intent(qualification, role, status, state):
    auth._auth_tokens[TOKEN]["role"] = role
    qualification.status = status
    qualification.window["state"] = state
    if state != "active":
        qualification.window.update(registration_revision=None, qualified_at=None, expires_at=None)
    if state == "rejected":
        qualification.window["error"] = "state_mismatch"
    value = handler(PATH, "POST", body=intent())
    value._dispatch()
    expected = metadata()
    expected.update(window=qualification.window, can_request=False)
    assert response(value) == (expected, status)
    assert qualification.calls[0][0] == "qualify"
    assert qualification.calls[0][2:] == (intent(), True)
    assert value.close_connection


@pytest.mark.parametrize("denial", ["viewer", "operator", "bearer", "missing-cookie", "csrf", "missing-origin", "foreign-origin", "http"])
def test_post_admission_refusals_close_before_constructor_or_body_read(qualification, denial):
    value = handler(PATH, "POST", body=intent(), https=denial != "http")
    if denial in ("viewer", "operator"):
        auth._auth_tokens[TOKEN]["role"] = denial
    elif denial in ("bearer", "missing-cookie"):
        del value.headers["Cookie"]
        if denial == "bearer":
            value.headers["Authorization"] = "Bearer " + TOKEN
    elif denial == "csrf":
        del value.headers["X-Freq-CSRF"]
    elif denial == "missing-origin":
        del value.headers["Origin"]
    elif denial == "foreign-origin":
        value.headers.replace_header("Origin", "https://other.invalid")
    value._dispatch()
    assert response(value)[1] == 403
    assert value.close_connection and value.rfile.tell() == 0
    assert qualification.constructors == qualification.calls == []
    qualification.load.assert_not_called()


@pytest.mark.parametrize("denial", ["bearer", "missing-cookie", "http", "expired"])
def test_get_still_requires_current_cookie_session_and_tls(qualification, denial):
    value = handler(PATH, https=denial != "http")
    if denial in ("bearer", "missing-cookie"):
        del value.headers["Cookie"]
        if denial == "bearer": value.headers["Authorization"] = "Bearer " + TOKEN
    elif denial == "expired":
        auth._auth_tokens[TOKEN]["last_activity_ts"] = time.time() - auth.SESSION_TIMEOUT_SECONDS - 1
    value._dispatch()
    assert response(value)[1] == 403
    assert qualification.constructors == qualification.calls == []


@pytest.mark.parametrize("bad", ["duplicate", "oversize", "query", "extra", "framing", "duplicate-length", "missing-length", "media", "non-object", "nonfinite", "key-space", "key-long"] + ["type-" + key for key in intent()])
def test_malformed_or_expanded_intents_never_reach_qualify(qualification, bad):
    raw = json.dumps(intent()).encode()
    if bad == "duplicate": raw = raw.replace(b'"target_ref":', b'"target_ref":"duplicate", "target_ref":', 1)
    elif bad == "oversize": raw += b" " * (4097 - len(raw))
    elif bad == "extra": raw = json.dumps(intent(duration_seconds=3600)).encode()
    elif bad == "non-object": raw = b"[]"
    elif bad == "nonfinite": raw = raw.replace(b'"fictional-window-intent"', b'NaN')
    elif bad == "key-space": raw = json.dumps(intent(request_key="not printable space")).encode()
    elif bad == "key-long": raw = json.dumps(intent(request_key="x" * 129)).encode()
    elif bad.startswith("type-"): raw = json.dumps(intent(**{bad[5:]: 123})).encode()
    value = handler(PATH + ("?duration=3600" if bad == "query" else ""), "POST", raw=raw)
    if bad == "framing": value.headers["Transfer-Encoding"] = "chunked"
    elif bad == "duplicate-length": value.headers["Content-Length"] = str(len(raw))
    elif bad == "missing-length": del value.headers["Content-Length"]
    elif bad == "media": value.headers.replace_header("Content-Type", "text/plain")
    value._dispatch()
    assert response(value)[1] == 400
    assert value.close_connection and qualification.calls == []


def test_exact_4096_byte_body_is_accepted_without_expanding_intent(qualification):
    raw = json.dumps(intent()).encode()
    raw += b" " * (4096 - len(raw))
    value = handler(PATH, "POST", raw=raw)
    value._dispatch()
    assert response(value)[1] == 201
    assert qualification.calls[0][2] == intent()


def test_get_query_cannot_select_another_window_or_target(qualification):
    value = handler(PATH + "?target_ref=other")
    value._dispatch()
    assert response(value)[1] == 400
    assert qualification.calls == []


@pytest.mark.parametrize("mode", ["normal", "readonly"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_only_explicit_cockpit_exposes_window_pre_auth(qualification, mode, method):
    value = handler(PATH, method, mode=mode, cookie=None, body=intent())
    value._dispatch()
    assert response(value)[1] == 404
    assert value.close_connection
    assert qualification.calls == qualification.constructors == []


@pytest.mark.parametrize("path,method", [(PATH + "/", "GET"), (PATH + "/other", "POST"), (PATH, "PUT"),
    ("/api/lab/window-reset", "POST"), ("/api/vm/start", "POST"), ("/api/vm/stop", "POST"),
    ("/api/terminal/open", "POST"), ("/api/exec", "POST")])
def test_exact_namespace_and_legacy_restrictions_precede_handler(qualification, path, method):
    value = handler(path, method, body=intent())
    value._load_routes = Mock(side_effect=AssertionError("unselected route reached"))
    value._dispatch()
    assert response(value)[1] in (403, 404, 405)
    assert qualification.calls == []
    value._load_routes.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("retirement", ["replacement", "logout", "expiry", "role", "csrf"])
def test_late_result_cannot_publish_after_original_session_retires(qualification, method, retirement):
    def retire(service):
        original = auth._auth_tokens[TOKEN]
        if retirement == "replacement": auth._auth_tokens[TOKEN] = original.copy()
        elif retirement == "logout": del auth._auth_tokens[TOKEN]
        elif retirement == "expiry": original["last_activity_ts"] = time.time() - auth.SESSION_TIMEOUT_SECONDS - 1
        elif retirement == "role": original["role"] = "viewer"
        else: original["csrf_token"] = "different-csrf"
        assert service.current() is False
    qualification.hook = retire
    value = handler(PATH, method, body=intent())
    value._dispatch()
    body, status = response(value)
    assert status == 403 and body.get("schema") != "pve-freq-lab-window-v1"
    assert value.close_connection
    assert len(qualification.calls) == 1


def test_header_failure_is_single_response_after_local_qualification(qualification):
    value = handler(PATH, "POST", body=intent())
    value.end_headers.side_effect = BrokenPipeError("fictional-header-failure")
    value._dispatch()
    assert value.send_response.call_count == 1
    value._json_response.assert_not_called()
    assert value.close_connection
    assert [call[0] for call in qualification.calls] == ["qualify"]


def test_session_retirement_after_admitted_publication_closes_without_second_response(qualification):
    class Retiring(io.BytesIO):
        def write(self, body):
            count = super().write(body)
            auth._auth_tokens.clear()
            return count
    value = handler(PATH)
    value.wfile = Retiring()
    value._dispatch()
    assert response(value)[1] == 200
    assert value.close_connection and value.send_response.call_count == 1
    value._json_response.assert_not_called()


def test_memory_error_keeps_original_identity_and_never_requalifies(qualification):
    error = MemoryError("fictional")
    def fail(_service): raise error
    qualification.hook = fail
    value = handler(PATH, "POST", body=intent())
    with pytest.raises(MemoryError) as raised:
        value._dispatch()
    assert raised.value is error
    assert [call[0] for call in qualification.calls] == ["qualify"]
    value._json_response.assert_not_called()


def test_lost_post_ack_is_recovered_by_get_without_another_post(qualification):
    class Lost(io.BytesIO):
        def write(self, _bytes): raise BrokenPipeError("fictional-lost-ack")
    value = handler(PATH, "POST", body=intent())
    value.wfile = Lost()
    value._dispatch()
    assert value.close_connection and value.send_response.call_count == 1
    value._json_response.assert_not_called()
    recovery = handler(PATH)
    recovery._dispatch()
    body, status = response(recovery)
    assert status == 200 and body["window"] == qualification.window
    assert [call[0] for call in qualification.calls] == ["qualify", "inspect"]


def test_other_session_cannot_read_original_window(qualification):
    value = handler(PATH, "POST", body=intent())
    value._dispatch()
    auth._auth_tokens["fictional-second-session"] = session("admin")
    other = handler(PATH, cookie="fictional-second-session")
    other._dispatch()
    assert response(other)[1] == 200 and response(other)[0]["window"] is None
    assert qualification.calls[0][1] != qualification.calls[1][1]


@pytest.mark.parametrize("reason", ["registration_unavailable", "policy_unavailable", "store_unavailable"])
def test_disabled_or_unknown_metadata_is_still_a_200_read(qualification, reason):
    qualification.dto.update(target=None, busy=None, can_request=False, reason=reason)
    qualification.dto["policy"].update(enabled=False, revision=None)
    value = handler(PATH)
    value._dispatch()
    assert response(value) == (qualification.dto, 200)
    assert [call[0] for call in qualification.calls] == ["inspect"]


def test_unexpected_service_failure_is_fixed_unavailable_without_private_error(qualification):
    def fail(_service): raise RuntimeError("private-provider-and-path")
    qualification.hook = fail
    value = handler(PATH)
    value._dispatch()
    body, status = response(value)
    assert status == 503 and "private-provider" not in json.dumps(body)


@pytest.mark.parametrize("code,status", [
    ("invalid_request", 400), ("role_required", 403), ("session_retired", 403),
    ("registration_changed", 409), ("policy_changed", 409), ("request_conflict", 409),
    ("qualification_busy", 409), ("target_busy", 409), ("store_unavailable", 503),
    ("provider_unavailable", 503), ("tls_unavailable", 503),
])
def test_known_qualification_failures_have_fixed_contract_status(qualification, code, status):
    from freq.services.lab_power_qualification import QualificationError
    def fail(_service): raise QualificationError(code)
    qualification.hook = fail
    value = handler(PATH, "POST", body=intent())
    value._dispatch()
    assert response(value) == ({"error": code}, status)
    assert value.close_connection
