"""Original logout/HTTP framing with loopback sockets and synthetic auth ports.

TLS admission and the source-write gate are substituted; no live service,
credential store, provider or installation is exercised.
"""
import contextlib
import json
import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq.api import auth
from freq.core import read_source_epoch
from freq.modules import serve


@pytest.fixture
def ports(monkeypatch):
    sessions = {"fixture-token": {"user": "fixture", "role": "viewer"}}
    monkeypatch.setattr(auth, "_auth_tokens", sessions)
    monkeypatch.setattr(auth, "request_is_https", lambda handler: True)
    monkeypatch.setattr(auth, "_lookup_session", lambda token, **kwargs: sessions.get(token))
    monkeypatch.setattr(read_source_epoch, "source_write", contextlib.nullcontext)
    monkeypatch.setattr(serve, "_check_session_role", lambda handler, role: ("viewer", None))
    monkeypatch.setattr(serve, "_check_csrf", lambda handler: (True, ""))
    monkeypatch.setattr(serve.FreqHandler, "_ROUTE_REGISTRY", {
        "/api/auth/logout": auth.handle_auth_logout,
        "/api/auth/verify": auth.handle_auth_verify,
    })
    for name in ("info", "warn", "error"):
        monkeypatch.setattr(serve.logger, name, Mock())
    return sessions


@contextlib.contextmanager
def original_server(*, read_only=False):
    server = serve.ThreadedHTTPServer(("127.0.0.1", 0), serve.FreqHandler)
    server.freq_read_only = read_only
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def exchange(address, request):
    chunks = []
    with socket.create_connection(address, timeout=2) as client:
        client.settimeout(2)
        client.sendall(request)
        while True:
            try:
                chunk = client.recv(65536)
            except ConnectionResetError:
                break  # Closing with an unread pipelined body may reset TCP.
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def logout_request(body=b"", *, method="POST", origin="https://fixture.example"):
    return (f"{method} /api/auth/logout HTTP/1.1\r\nHost: fixture.example\r\n"
            f"Origin: {origin}\r\nCookie: freq_session=fixture-token\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode() + body


def verify_request():
    return (b"GET /api/auth/verify HTTP/1.1\r\nHost: fixture.example\r\n"
            b"Cookie: freq_session=fixture-token\r\nConnection: close\r\n\r\n")


def test_pipelined_logout_body_closes_before_another_response(ports):
    with original_server() as address:
        raw = exchange(address, logout_request(b"{}") + verify_request())
    assert raw.count(b"HTTP/1.1 ") == 1, raw
    head, body = raw.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200 ")
    assert b"Connection: close\r\n" in head + b"\r\n"
    assert json.loads(body) == {"ok": True, "message": "Logged out"}
    assert ports == {}


def test_bodyless_logout_preserves_cookie_clear_and_revocation(ports):
    with original_server() as address:
        raw = exchange(address, logout_request())
        verified = exchange(address, verify_request())
    head, body = raw.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 200 ")
    assert b"Set-Cookie: freq_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0; Secure" in head
    assert b"Connection: close" in head
    assert json.loads(body) == {"ok": True, "message": "Logged out"}
    assert json.loads(verified.split(b"\r\n\r\n", 1)[1]) == {"valid": False}
    assert ports == {}


@pytest.mark.parametrize("method,origin,status", [
    ("GET", "https://fixture.example", 405),
    ("POST", "https://other.example", 403),
])
def test_refused_logout_closes_with_unread_pipeline_without_revoking(ports, method, origin, status):
    with original_server() as address:
        raw = exchange(address, logout_request(b"{}", method=method, origin=origin) + verify_request())
    assert raw.count(b"HTTP/1.1 ") == 1, raw
    assert raw.startswith(f"HTTP/1.1 {status} ".encode())
    assert "fixture-token" in ports


def test_logout_closes_before_fallible_auth_and_never_reads_body(monkeypatch):
    handler = SimpleNamespace(command="POST", close_connection=False, rfile=Mock())
    handler.rfile.read.side_effect = AssertionError("logout must not drain body")

    def failing_tls(_handler):
        assert handler.close_connection is True
        raise RuntimeError("synthetic admission failure")

    monkeypatch.setattr(auth, "request_is_https", failing_tls)
    with pytest.raises(RuntimeError, match="synthetic admission failure"):
        auth.handle_auth_logout(handler)
    handler.rfile.read.assert_not_called()


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("credential", ["unauthenticated", "expired"])
def test_outer_auth_denial_closes_logout_pipeline(ports, monkeypatch, read_only, credential):
    # Restore the actual role gate; only session storage/TLS ports remain fake.
    monkeypatch.setattr(serve, "_check_session_role", auth.check_session_role)
    monkeypatch.setattr(auth, "_lookup_session", lambda token, **kwargs: None)
    request = logout_request(b"{}")
    if credential == "unauthenticated":
        request = request.replace(b"Cookie: freq_session=fixture-token\r\n", b"")
    with original_server(read_only=read_only) as address:
        raw = exchange(address, request + verify_request())
    assert raw.count(b"HTTP/1.1 ") == 1, raw
    head, body = raw.split(b"\r\n\r\n", 1)
    assert head.startswith(b"HTTP/1.1 403 ")
    assert json.loads(body)["error"] == (
        "Authentication required" if credential == "unauthenticated"
        else "Session expired or invalid"
    )
    assert "fixture-token" in ports
