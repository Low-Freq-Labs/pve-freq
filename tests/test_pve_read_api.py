"""Contained original HTTP dispatch checks, with synthetic session/provider ports.

No listener, installation, credential store or Proxmox request is exercised.
"""
import io
import json
import sys
from email.message import Message
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.api import auth, build_route_registry, pve_read
from freq.modules import serve


@pytest.fixture
def ports(monkeypatch):
    session = {"user": "fixture", "role": "viewer", "csrf_token": "fixture-csrf"}
    lookup = Mock(return_value=session)
    monkeypatch.setattr(auth, "_lookup_session", lookup)
    monkeypatch.setattr(auth, "_peer_is_trusted_proxy", lambda handler: True)
    monkeypatch.setattr(serve.logger, "info", Mock())
    monkeypatch.setattr(serve.logger, "warn", Mock())
    monkeypatch.setattr(serve.logger, "error", Mock())
    monkeypatch.setattr(serve.FreqHandler, "_ROUTE_REGISTRY", None)
    cfg = object()
    config = Mock(return_value=cfg)
    inventory = Mock(return_value={"schema": 1, "state": "ok", "sources": []})
    monkeypatch.setattr(pve_read, "load_config", config)
    monkeypatch.setattr(pve_read, "resolve_inventory", inventory)
    helper = ModuleType("freq.services.pve_read_configuration")

    class ConfigurationError(Exception):
        def __init__(self, code):
            self.code = code
            super().__init__("PRIVATE fixture detail must never be public")

    helper.ConfigurationError = ConfigurationError
    helper.configure_pve_read = Mock(return_value={"configured": True})
    helper.get_pve_read_configuration = Mock(return_value={"configured": False})
    monkeypatch.setitem(sys.modules, helper.__name__, helper)
    return SimpleNamespace(session=session, lookup=lookup, cfg=cfg, config=config,
                           inventory=inventory, helper=helper)


def request(path="/api/pve/inventory", method="GET", body=b"", *, headers=None,
            authenticated=True):
    handler = serve.FreqHandler.__new__(serve.FreqHandler)
    handler.path, handler.command = path, method
    handler.requestline = f"{method} {path} HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.client_address = ("127.0.0.1", 0)
    handler.connection = handler.request = object()
    handler.close_connection = False
    handler.headers = Message()
    defaults = {"Host": "fixture.example", "X-Forwarded-Proto": "https"}
    if authenticated:
        defaults["Cookie"] = "freq_session=fixture-token"
    for name, value in defaults.items():
        handler.headers[name] = value
    for name, value in (headers or {}).items():
        if name in handler.headers:
            del handler.headers[name]
        if value is not None:
            handler.headers[name] = value
    handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
    return handler


def dispatch(handler):
    handler._begin_request()
    handler._dispatch()
    head, raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)
    status = int(head.split(b" ", 2)[1])
    payload = json.loads(raw)
    return status, payload


def post(body=b"{}", **overrides):
    headers = {"Content-Type": "application/json", "Content-Length": str(len(body)),
               "Origin": "https://fixture.example", "X-Freq-CSRF": "fixture-csrf"}
    headers.update(overrides)
    return request("/api/pve/endpoints", "POST", body, headers=headers)


def test_real_registry_includes_both_handlers():
    routes = build_route_registry(serve.FreqHandler._ROUTES)
    assert routes["/api/pve/inventory"] is pve_read.handle_inventory
    assert routes["/api/pve/endpoints"] is pve_read.handle_endpoints


def test_original_dispatch_rejects_unauthenticated_without_provider(ports):
    status, body = dispatch(request(authenticated=False))
    assert status == 403
    assert body["error"] == "Authentication required"
    ports.lookup.assert_not_called()
    ports.config.assert_not_called()
    ports.inventory.assert_not_called()


def test_viewer_get_crosses_original_auth_gates_and_returns_inventory(ports):
    status, body = dispatch(request())
    assert status == 200 and body == ports.inventory.return_value
    assert ports.lookup.call_count >= 2
    ports.inventory.assert_called_once_with(ports.cfg)


def test_post_inventory_rejected_without_provider(ports):
    status, body = dispatch(request(method="POST", headers={"X-Freq-CSRF": "fixture-csrf"}))
    assert status == 405 and body["error"] == "method_not_allowed"
    ports.inventory.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_endpoint_configuration_denies_viewer(ports, method):
    handler = post() if method == "POST" else request("/api/pve/endpoints")
    status, body = dispatch(handler)
    assert status == 403 and body["error"] == "authentication_required"
    ports.config.assert_not_called()


@pytest.mark.parametrize("path", ["/api/pve/inventory", "/api/pve/endpoints"])
def test_https_required_before_configuration_or_provider(ports, path):
    ports.session["role"] = "admin"
    status, body = dispatch(request(path, headers={"X-Forwarded-Proto": "http"}))
    assert status == 403 and body["error"] == "https_required"
    ports.config.assert_not_called()
    ports.inventory.assert_not_called()


@pytest.mark.parametrize("origin", [None, "https://other.example", "http://fixture.example"])
def test_post_requires_matching_present_origin(ports, origin):
    ports.session["role"] = "admin"
    status, body = dispatch(post(Origin=origin))
    assert status == 403 and body["error"] == "same_origin_required"
    ports.helper.configure_pve_read.assert_not_called()


def test_cookie_post_requires_original_csrf_gate(ports):
    ports.session["role"] = "admin"
    status, body = dispatch(post(**{"X-Freq-CSRF": None}))
    assert status == 403 and body["error"] == "CSRF token required"
    ports.config.assert_not_called()


def test_admin_post_validates_body_then_calls_local_configuration(ports):
    ports.session["role"] = "admin"
    status, body = dispatch(post(b'{"endpoints":[]}'))
    assert status == 200 and body == {"ok": True, "configured": True}
    ports.helper.configure_pve_read.assert_called_once_with(ports.cfg, {"endpoints": []})
    ports.inventory.assert_not_called()


@pytest.mark.parametrize("raw,headers", [
    (b'{}', {"Content-Length": "3"}),
    (b'{}', {"Content-Length": None}),
    (b'{}', {"Content-Length": "0"}),
    (b'{}', {"Content-Length": "-1"}),
    (b'{}', {"Content-Length": "131073"}),
    (b'{}', {"Content-Length": "999999999"}),
    (b'{}', {"Content-Length": "\u0662"}),
    (b'{}', {"Content-Type": "text/plain"}),
    (b'{}', {"Transfer-Encoding": "chunked"}),
    (b'{"a":1,"a":2}', {}),
    (b'{"a":{"x":1,"x":2}}', {}),
    (b'{"a":NaN}', {}),
    (b'[]', {}),
    (b'null', {}),
    (b'{"bad":\xff}', {}),
])
def test_bad_body_is_fixed_error_and_never_reaches_writer(ports, raw, headers):
    ports.session["role"] = "admin"
    handler = post(raw, **headers)
    status, body = dispatch(handler)
    assert status == 400 and body["error"] == "invalid_request"
    assert set(body) == {"error", "request_id"}
    assert handler.close_connection
    ports.helper.configure_pve_read.assert_not_called()


def test_duplicate_content_lengths_rejected(ports):
    ports.session["role"] = "admin"
    handler = post()
    handler.headers["Content-Length"] = "2"
    status, body = dispatch(handler)
    assert status == 400 and body["error"] == "invalid_request"
    ports.helper.configure_pve_read.assert_not_called()


@pytest.mark.parametrize("code,status", [("already_configured", 409),
                                        ("invalid_request", 400),
                                        ("configuration_unavailable", 503)])
def test_configuration_errors_expose_only_fixed_code(ports, code, status):
    ports.session["role"] = "admin"
    ports.helper.configure_pve_read.side_effect = ports.helper.ConfigurationError(code)
    actual, body = dispatch(post())
    assert actual == status and body["error"] == code
    assert "PRIVATE" not in json.dumps(body)


def test_inventory_memory_error_propagates_original_dispatch(ports):
    ports.inventory.side_effect = MemoryError()
    with pytest.raises(MemoryError):
        dispatch(request())
