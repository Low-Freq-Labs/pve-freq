"""Original dispatch/auth with fictional service/config/TLS ports; no native I/O."""
import copy
import hashlib
import importlib
import io
import json
import socket
import threading
import time
from email.message import Message
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.api import auth
from freq.modules import serve
from freq.services.lab_guest_power import LabPowerError
from freq.services.lab_guest_registration import Registration


TOKEN = "fictional-creator-session"
CSRF = "fictional-csrf"
OPERATION = "1" * 32
REFERENCE = "2" * 32
REVISION = "a" * 64
STAMP = 1794571200.0


def session(role="operator"):
    return {"user": "fictional-operator", "role": role, "csrf_token": CSRF,
            "ts": time.time(), "last_activity_ts": time.time()}


def request_body(**overrides):
    return {"target_ref": REFERENCE, "registration_revision": REVISION,
            "action": "start", "expected_state": "stopped", "request_key": "fictional-intent", **overrides}


def handler(path="/api/lab/guest", method="GET", *, mode="cockpit", body=None, raw=None,
            cookie=TOKEN, role=None, https=True):
    value = serve.FreqHandler.__new__(serve.FreqHandler)
    value.server = SimpleNamespace(freq_read_only=mode == "readonly", freq_lab_cockpit=mode == "cockpit")
    value.path, value.command = path, method
    value.client_address = ("192.0.2.44", 12345)
    value.request = value.connection = object()
    value._test_https = https
    raw = json.dumps(body or {}).encode() if raw is None else raw
    value.headers = Message()
    for key, text in (("Host", "freq.test:8443"), ("Origin", "https://freq.test:8443"),
                      ("Content-Type", "application/json"), ("Content-Length", str(len(raw))),
                      ("X-Freq-CSRF", CSRF)):
        value.headers[key] = text
    if cookie is not None:
        value.headers["Cookie"] = "freq_session=" + cookie
    value.rfile = io.BytesIO(raw)
    value.wfile = io.BytesIO()
    value.close_connection = False
    value._json_response = Mock()
    value.send_response = Mock()
    value.send_header = Mock()
    value.end_headers = Mock()
    value._send_security_headers = Mock()
    return value


def response(value):
    if value.wfile.getvalue():
        return json.loads(value.wfile.getvalue()), value.send_response.call_args.args[0]
    call = value._json_response.call_args
    assert call is not None, "expected one bounded API response"
    return call.args[0], call.args[1] if len(call.args) > 1 else call.kwargs.get("status", 200)


@pytest.fixture
def api_case(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("network forbidden")))
    module = importlib.import_module("freq.api.lab_guest")
    monkeypatch.setattr(auth, "_auth_lock", threading.RLock())
    monkeypatch.setattr(auth, "_auth_tokens", {TOKEN: session()})
    monkeypatch.setattr(auth, "request_is_https", lambda value: value._test_https)
    monkeypatch.setattr(serve.FreqHandler, "_ROUTE_REGISTRY", None)
    record = Registration(
        registration_id=REFERENCE, qualified_at="2026-11-13T00:00:00Z", expires_at="2026-11-14T00:00:00Z",
        estate="fictional-lab", provider="pve.example.invalid", node="fictional-pve", guest_type="qemu",
        vmid=5000, name="fictional-guest", instance_uuid="12345678-1234-5678-9123-123456789abc",
        allowed_actions=("status", "start", "shutdown"), qualification_ref="private-qualification-ref",
        revision=REVISION, token_id="private-token-id@pve!lab", token_secret_file="/private/token-path",
        ca_file="/private/ca-path")
    internal_target = json.dumps({key: getattr(record, key) for key in (
        "estate", "provider", "node", "guest_type", "vmid", "instance_uuid")}, sort_keys=True, separators=(",", ":"))
    row = {"id": OPERATION, "actor": "private-actor", "request_key": "private-request-key",
           "registration_revision": REVISION, "target": internal_target, "target_slot": "private-target-slot",
           "action": "start", "expected_state": "stopped", "phase": "acknowledged", "active": 1,
           "upid": "UPID:private-provider-task", "task_state": None, "task_exit": None,
           "observed_state": "stopped", "observed_at": STAMP, "error": None, "version": 1,
           "created_at": STAMP, "updated_at": STAMP}
    case = SimpleNamespace(module=module, registration=record, row=row, calls=[], services=[], hook=None,
                           owner=None, cfg=SimpleNamespace(conf_dir="/fictional/conf", data_dir="/fictional/data"))

    class Service:
        def __init__(self, cfg, *, still_current=None, **_kwargs):
            assert cfg is case.cfg
            assert callable(still_current), "original session callback must always be supplied"
            self.still_current = still_current
            case.services.append(self)

        def inspect(self, actor):
            assert self.still_current() is True
            case.calls.append(("inspect", actor))
            if case.hook:
                case.hook(self)
            operation = None
            if case.owner == actor:
                operation = {key: case.row[key] for key in (
                    "id", "registration_revision", "action", "expected_state", "phase",
                    "task_state", "task_exit", "observed_state", "observed_at", "error", "version")}
            return {"registration": record.public_view(), "observed_state": "stopped", "observed_at": STAMP,
                    "capability_scope": {"lab_only": True, "allowed_actions": list(record.allowed_actions)},
                    "busy": case.owner is not None, "operation": operation}

        def submit(self, actor, body):
            assert self.still_current() is True
            case.calls.append(("submit", actor, copy.deepcopy(body)))
            case.owner = actor
            if case.hook:
                case.hook(self)
            return copy.deepcopy(case.row)

        def poll(self, actor, reference):
            assert self.still_current() is True
            case.calls.append(("poll", actor, reference))
            if case.owner is not None and case.owner != actor:
                raise LabPowerError("not_found")
            if case.hook:
                case.hook(self)
            return copy.deepcopy(case.row)

    monkeypatch.setattr(module, "RegisteredLabPower", Service)
    monkeypatch.setattr(module, "load_config", Mock(return_value=case.cfg))
    monkeypatch.setattr(module, "load_registration", Mock(return_value=record))
    # This suite isolates HTTP/projection from owner files and SQLite. The
    # original factory/store path is exercised in qualification composition.
    class Qualification:
        def __init__(self, cfg, *, still_current):
            assert cfg is case.cfg
            self.current = still_current

        def effective_registration(self, actor, *, can_request, now=None):
            assert self.current() is True
            return module.load_registration(case.cfg)

    monkeypatch.setattr("freq.services.lab_power_qualification.LabPowerQualification", Qualification)
    return case


def assert_private_fields_absent(document):
    encoded = json.dumps(document)
    for private in ("private-actor", "private-request-key", "private-target-slot", "UPID:",
                    "private-token-id", "/private/", "private-qualification-ref", "instance_uuid"):
        assert private not in encoded
    for name in ("actor", "request_key", "target_slot", "upid", "credentials", "token_id", "ca_file", "token_secret_file"):
        assert '"' + name + '"' not in encoded


def test_original_dispatch_guest_wire_and_private_projection(api_case):
    value = handler()
    value._dispatch()
    body, status = response(value)
    assert status == 200
    assert body == {"schema": "pve-freq-lab-guest-view-v1", "target": {
        "ref": REFERENCE, "registration_revision": REVISION, "estate": "fictional-lab",
        "source": "pve.example.invalid", "node": "fictional-pve", "kind": "qemu", "vmid": 5000,
        "name": "fictional-guest", "qualified_at": "2026-11-13T00:00:00Z",
        "expires_at": "2026-11-14T00:00:00Z"},
        "capabilities": {"lab_only": True, "actions": ["start", "shutdown"]},
        "observation": {"state": "stopped", "observed_at": "2026-11-13T12:00:00Z"},
        "busy": False, "operation": None}
    assert_private_fields_absent(body)
    headers = {call.args[0].lower(): call.args[1] for call in value.send_header.call_args_list}
    assert headers["content-type"].startswith("application/json")
    assert headers["cache-control"] == "no-store"
    assert int(headers["content-length"]) == len(value.wfile.getvalue())
    assert api_case.calls[0][0] == "inspect"
    assert len(api_case.calls[0][1]) == 64 and api_case.calls[0][1] != hashlib.sha256(b"fictional-operator").hexdigest()


@pytest.mark.parametrize("path,method,denial", [
    (path, method, denial)
    for path, method in [("/api/lab/guest", "GET"), ("/api/lab/power", "POST"),
                         ("/api/lab/operations/" + OPERATION, "GET")]
    for denial in ["missing-cookie", "bearer", "viewer", "http"] +
    (["wrong-csrf", "missing-origin", "foreign-origin"] if method == "POST" else [])
])
def test_authentication_role_tls_and_post_guards_precede_service(api_case, path, method, denial):
    value = handler(path, method, body=request_body(), https=denial != "http")
    if denial in ("missing-cookie", "bearer"):
        del value.headers["Cookie"]
        if denial == "bearer":
            value.headers["Authorization"] = "Bearer " + TOKEN
    elif denial == "viewer":
        auth._auth_tokens[TOKEN]["role"] = "viewer"
    elif denial == "wrong-csrf":
        value.headers.replace_header("X-Freq-CSRF", "wrong")
    elif denial == "missing-origin":
        del value.headers["Origin"]
    elif denial == "foreign-origin":
        value.headers.replace_header("Origin", "https://foreign.invalid")
    value._dispatch()
    assert response(value)[1] == 403
    assert api_case.calls == []


@pytest.mark.parametrize("path,method", [("/api/lab/guest", "GET"), ("/api/lab/power", "POST"),
                                        ("/api/lab/operations/" + OPERATION, "GET")])
@pytest.mark.parametrize("mode", ["normal", "readonly"])
def test_lab_routes_are_disabled_outside_explicit_cockpit(api_case, path, method, mode):
    value = handler(path, method, mode=mode, body=request_body())
    value._dispatch()
    assert response(value)[1] == 404
    assert api_case.calls == []


@pytest.mark.parametrize("bad", ["query", "duplicate", "oversize", "extra-field", "wrong-expected-state",
                                  "transfer-encoding", "duplicate-length", "non-json", "non-object"])
def test_power_request_rejections_precede_service(api_case, bad):
    raw = json.dumps(request_body()).encode()
    if bad == "duplicate":
        raw = raw.replace(b'"action": "start"', b'"action": "shutdown", "action": "start"')
    elif bad == "oversize":
        raw += b" " * 4096
    elif bad == "extra-field":
        raw = json.dumps(request_body(provider="other.invalid")).encode()
    elif bad == "wrong-expected-state":
        raw = json.dumps(request_body(expected_state="running")).encode()
    elif bad == "non-object":
        raw = b"[]"
    value = handler("/api/lab/power" + ("?vmid=1" if bad == "query" else ""), "POST", raw=raw)
    if bad == "transfer-encoding":
        value.headers["Transfer-Encoding"] = "chunked"
    elif bad == "duplicate-length":
        value.headers["Content-Length"] = str(len(raw))
    elif bad == "non-json":
        value.headers.replace_header("Content-Type", "text/plain")
    value._dispatch()
    assert response(value)[1] == 400
    assert api_case.calls == []


@pytest.mark.parametrize("phase,status,ack", [("dispatching", 202, "pending"), ("acknowledged", 202, "received"),
    ("running", 202, "received"), ("uncertain", 202, "uncertain"), ("succeeded", 200, "received"),
    ("failed", 200, "received"), ("rejected", 409, "not_submitted")])
def test_power_phase_status_and_internal_row_redaction(api_case, phase, status, ack):
    api_case.row["phase"] = phase
    if phase in ("dispatching", "rejected", "uncertain"):
        api_case.row["upid"] = None
    value = handler("/api/lab/power", "POST", body=request_body())
    value._dispatch()
    body, actual_status = response(value)
    assert actual_status == status
    assert body["schema"] == "pve-freq-lab-operation-view-v1"
    operation = body["operation"]
    assert (operation["ref"], operation["target_ref"], operation["retired"]) == (OPERATION, REFERENCE, False)
    assert (operation["phase"], operation["acknowledgement"]) == (phase, ack)
    assert operation["observation"] == {"state": "stopped", "observed_at": "2026-11-13T12:00:00Z"}
    assert operation["task"] == {"state": "unknown", "exit": None}
    assert operation["created_at"] == operation["updated_at"] == "2026-11-13T12:00:00Z"
    assert_private_fields_absent(body)
    assert api_case.calls[0][2] == request_body()


def test_known_provider_acknowledgement_survives_later_observation_uncertainty(api_case):
    api_case.row.update(phase="uncertain", error="instance_changed")
    value = handler("/api/lab/operations/" + OPERATION)
    value._dispatch()
    body, status = response(value)
    assert status == 200
    assert body["operation"]["phase"] == "uncertain"
    assert body["operation"]["acknowledgement"] == "received"
    assert_private_fields_absent(body)


@pytest.mark.parametrize("state,exit_status,public", [(None, None, "unknown"), ("running", None, "running"),
                                                    ("stopped", "OK", "succeeded"), ("stopped", "failed", "failed")])
def test_poll_uses_opaque_id_and_projects_task_axis(api_case, state, exit_status, public):
    api_case.row.update(task_state=state, task_exit=exit_status)
    value = handler("/api/lab/operations/" + OPERATION)
    value._dispatch()
    body, status = response(value)
    assert status == 200
    assert body["operation"]["task"] == {"state": public, "exit": exit_status}
    assert api_case.calls[0][0] == "poll" and api_case.calls[0][2] == OPERATION
    assert_private_fields_absent(body)


@pytest.mark.parametrize("stage", ["inspect", "submit", "poll"])
@pytest.mark.parametrize("retirement", ["logout", "replacement", "role", "csrf", "expired"])
def test_retired_creator_cannot_receive_late_service_result(api_case, stage, retirement):
    def retire(service):
        original = auth._auth_tokens[TOKEN]
        if retirement == "logout":
            del auth._auth_tokens[TOKEN]
        elif retirement == "replacement":
            auth._auth_tokens[TOKEN] = original.copy()
        elif retirement == "role":
            original["role"] = "viewer"
        elif retirement == "csrf":
            original["csrf_token"] = "replacement-csrf"
        else:
            original["last_activity_ts"] = time.time() - auth.SESSION_TIMEOUT_SECONDS - 1
        assert service.still_current() is False

    api_case.hook = retire
    path = {"inspect": "/api/lab/guest", "submit": "/api/lab/power", "poll": "/api/lab/operations/" + OPERATION}[stage]
    value = handler(path, "POST" if stage == "submit" else "GET", body=request_body())
    value._dispatch()
    if value.wfile.getvalue():
        assert response(value)[0].get("schema") not in ("pve-freq-lab-guest-view-v1", "pve-freq-lab-operation-view-v1")
    for call in value._json_response.call_args_list:
        assert call.args[0].get("schema") not in ("pve-freq-lab-guest-view-v1", "pve-freq-lab-operation-view-v1")
    assert value.close_connection or response(value)[1] == 403
    assert len(api_case.calls) == 1


def test_lost_post_response_does_not_send_second_json_or_dispatch_again_and_get_recovers(api_case):
    class Disconnected(io.BytesIO):
        def write(self, _data):
            raise BrokenPipeError("fictional-disconnect")

    value = handler("/api/lab/power", "POST", body=request_body())
    value.wfile = Disconnected()
    value._dispatch()
    assert value.send_response.call_count == 1
    value._json_response.assert_not_called()
    assert value.close_connection
    recovered = handler()
    recovered._dispatch()
    body, status = response(recovered)
    assert status == 200 and body["busy"] is True
    assert body["operation"]["ref"] == OPERATION
    assert [call[0] for call in api_case.calls] == ["submit", "inspect"]


def test_session_retirement_after_publication_closes_without_second_response(api_case):
    class Retiring(io.BytesIO):
        def write(self, data):
            count = super().write(data)
            auth._auth_tokens.clear()
            return count

    value = handler()
    value.wfile = Retiring()
    value._dispatch()
    assert value.send_response.call_count == 1
    value._json_response.assert_not_called()
    assert value.close_connection


def test_header_send_failure_cannot_append_generic_error_response(api_case):
    value = handler("/api/lab/power", "POST", body=request_body())
    value.end_headers.side_effect = OSError("fictional-header-failure")
    value._dispatch()
    assert value.send_response.call_count == 1
    value._json_response.assert_not_called()
    assert value.close_connection
    assert [call[0] for call in api_case.calls] == ["submit"]


def test_memory_failure_during_publication_propagates_without_resubmission(api_case):
    value = handler("/api/lab/power", "POST", body=request_body())
    error = MemoryError("fictional-allocation")
    value.send_header.side_effect = error
    with pytest.raises(MemoryError) as raised:
        value._dispatch()
    assert raised.value is error
    assert value.send_response.call_count == 1
    value._json_response.assert_not_called()
    assert [call[0] for call in api_case.calls] == ["submit"]


def test_changed_revision_retires_recovered_operation_reference(api_case):
    post = handler("/api/lab/power", "POST", body=request_body())
    post._dispatch()
    api_case.row["registration_revision"] = "b" * 64
    current = handler()
    current._dispatch()
    recovery = response(current)[0]["operation"]
    assert recovery["ref"] == OPERATION
    assert recovery["target_ref"] is None and recovery["retired"] is True


def test_other_session_gets_busy_without_creator_operation_and_cannot_poll(api_case):
    post = handler("/api/lab/power", "POST", body=request_body())
    post._dispatch()
    auth._auth_tokens["fictional-other-session"] = session()
    other = handler(cookie="fictional-other-session")
    other._dispatch()
    assert response(other)[0]["busy"] is True and response(other)[0]["operation"] is None
    foreign = handler("/api/lab/operations/" + OPERATION, cookie="fictional-other-session")
    foreign._dispatch()
    assert response(foreign)[1] == 404


def test_fixed_service_error_never_projects_provider_text(api_case):
    def fail(_service):
        raise RuntimeError("private-provider-message-and-path")
    api_case.hook = fail
    value = handler()
    value._dispatch()
    body, status = response(value)
    assert status == 503
    assert "private-provider" not in json.dumps(body)
