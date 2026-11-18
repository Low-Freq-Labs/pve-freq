"""Fictional native ports for strict registered-guest transport; no PVE calls."""
import contextlib
import http.client
import http.server
import json
import ssl
import threading
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import quote

import pytest

from freq.services import lab_pve_transport as transport
from freq.services.lab_guest_registration import load_registration
from tests.test_lab_guest_registration import NOW, manifest, synthetic_ca  # noqa: F401
from tests.test_pve_read_tls import synthetic_tls  # noqa: F401


UPID = "UPID:fictional-pve:00000001:00000002:12345678:qmstart:5000:reader@pve!lab:"
BASE = "/api2/json/nodes/fictional-pve/qemu/5000"


@pytest.fixture
def registered(manifest):
    return load_registration(manifest.cfg, now=NOW)


def wire(monkeypatch, *, data=None, payload=None, status=200, headers=None):
    if payload is None:
        payload = json.dumps({"data": {} if data is None else data}).encode()
    replies = []

    class Response:
        def __init__(self):
            self.status = status
            self.rest = payload
            self.read_sizes = []
            self.close_calls = 0
            replies.append(self)

        def getheader(self, name, default=None):
            return (headers or {}).get(name, default)

        def read1(self, size):
            self.read_sizes.append(size)
            value, self.rest = self.rest[:size], self.rest[size:]
            return value

        def isclosed(self):
            return False

        def close(self):
            self.close_calls += 1

    connection = Mock()
    connection.getresponse.side_effect = Response
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(transport.http.client, "HTTPSConnection", constructor)
    context = SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_REQUIRED)
    context_factory = Mock(return_value=context)
    monkeypatch.setattr(transport.ssl, "create_default_context", context_factory)
    return SimpleNamespace(connection=connection, constructor=constructor,
                           context=context, factory=context_factory, replies=replies)


@pytest.mark.parametrize("method,suffix", [("get_config", "/config"), ("get_status", "/status/current")])
def test_reads_use_fixed_direct_https_paths_and_verifying_context(monkeypatch, registered, method, suffix):
    native = wire(monkeypatch, data={"name": "fictional-lab", "status": "stopped"})
    client = transport.LabPveTransport(registered)
    assert getattr(client, method)() == {"name": "fictional-lab", "status": "stopped"}
    native.factory.assert_called_once_with(cafile=registered.ca_file)
    args, kwargs = native.constructor.call_args
    assert args == (registered.provider, 8006)
    assert 0 < kwargs["timeout"] <= 5
    assert kwargs["context"] is native.context
    request = native.connection.request.call_args
    assert request.args == ("GET", BASE + suffix)
    assert request.kwargs["body"] is None
    assert request.kwargs["headers"] == {
        "Authorization": "PVEAPIToken=reader@pve!lab=fictional-token",
        "Accept": "application/json", "Accept-Encoding": "identity",
    }
    assert all(0 < call.args[0] <= 5 for call in native.connection.sock.settimeout.call_args_list)
    native.connection.close.assert_called_once_with()


@pytest.mark.parametrize("action,body", [("start", b""), ("shutdown", b"forceStop=0&timeout=30")])
def test_submit_uses_only_fixed_non_force_forms_and_returns_server_upid(monkeypatch, registered, action, body):
    native = wire(monkeypatch, data=UPID)
    assert transport.LabPveTransport(registered).submit(action) == UPID
    request = native.connection.request.call_args
    assert request.args == ("POST", BASE + "/status/" + action)
    assert request.kwargs["body"] == body
    assert request.kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    native.connection.close.assert_called_once_with()


def test_submit_revalidates_after_tls_connect_and_immediately_before_post(monkeypatch, registered):
    native = wire(monkeypatch, data=UPID)
    client = transport.LabPveTransport(registered)
    sequence = []
    native.connection.connect.side_effect = lambda: sequence.append("tls-connected")

    def revalidate():
        assert sequence == ["tls-connected"]
        native.connection.request.assert_not_called()
        sequence.append("session-and-registration-current")

    def post(*args, **kwargs):
        assert sequence == ["tls-connected", "session-and-registration-current"]
        sequence.append("post")

    client.before_submit = revalidate
    native.connection.request.side_effect = post
    assert client.submit("start") == UPID
    assert sequence == ["tls-connected", "session-and-registration-current", "post"]


def test_session_revoked_during_tls_connect_prevents_any_post(monkeypatch, registered):
    native = wire(monkeypatch, data=UPID)
    client = transport.LabPveTransport(registered)
    current = [True]
    native.connection.connect.side_effect = lambda: current.__setitem__(0, False)

    def revalidate():
        assert current[0] is False
        raise transport.LabTransportError("session_retired")

    client.before_submit = revalidate
    with pytest.raises(transport.LabTransportError) as failure:
        client.submit("start")
    assert (failure.value.code, failure.value.uncertain) == ("session_retired", False)
    native.connection.connect.assert_called_once_with()
    native.connection.request.assert_not_called()
    native.connection.close.assert_called_once_with()


@pytest.mark.parametrize("action", ["stop", "reset", "reboot", "status", "../shutdown", [], None])
def test_unsupported_action_never_opens_connection(monkeypatch, registered, action):
    native = wire(monkeypatch)
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).submit(action)
    assert (failure.value.code, failure.value.uncertain) == ("invalid_action", False)
    native.constructor.assert_not_called()


def test_registered_action_subset_is_enforced_before_network(monkeypatch, registered):
    import dataclasses
    native = wire(monkeypatch)
    restricted = dataclasses.replace(registered, allowed_actions=("status",))
    with pytest.raises(transport.LabTransportError, match="^invalid_action$"):
        transport.LabPveTransport(restricted).submit("start")
    native.constructor.assert_not_called()


def test_task_uses_validated_node_and_quotes_complete_server_held_upid(monkeypatch, registered):
    native = wire(monkeypatch, data={"status": "stopped", "exitstatus": "OK"})
    result = transport.LabPveTransport(registered).get_task(UPID)
    assert result["exitstatus"] == "OK"
    assert native.connection.request.call_args.args == (
        "GET", "/api2/json/nodes/fictional-pve/tasks/" + quote(UPID, safe="") + "/status")


@pytest.mark.parametrize("upid", ["/api2/json/other", UPID.replace("fictional-pve", "other"),
                                  UPID + "../other", "UPID:" + "x" * 600, None])
def test_invalid_task_reference_never_opens_connection(monkeypatch, registered, upid):
    native = wire(monkeypatch)
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).get_task(upid)
    assert (failure.value.code, failure.value.uncertain) == ("invalid_task", False)
    native.constructor.assert_not_called()


def test_each_native_call_rereads_protected_secret(monkeypatch, registered, manifest):
    native = wire(monkeypatch)
    client = transport.LabPveTransport(registered)
    client.get_status()
    manifest.secret.write_bytes(b"replacement-fictional-token\n")
    client.get_config()
    assert native.connection.request.call_args.kwargs["headers"]["Authorization"].endswith("=replacement-fictional-token")
    manifest.secret.chmod(0o640)
    with pytest.raises(transport.LabTransportError) as failure:
        client.get_status()
    assert (failure.value.code, failure.value.uncertain) == ("credentials_unavailable", False)
    assert native.constructor.call_count == 2


@pytest.mark.parametrize("part", ["hostname", "verify"])
def test_insecure_context_is_never_used(monkeypatch, registered, part):
    native = wire(monkeypatch)
    if part == "hostname":
        native.context.check_hostname = False
    else:
        native.context.verify_mode = ssl.CERT_NONE
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).submit("start")
    assert (failure.value.code, failure.value.uncertain) == ("tls_unavailable", False)
    native.constructor.assert_not_called()


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 500])
def test_provider_errors_are_sanitized_and_never_redirected_or_retried(monkeypatch, registered, status):
    native = wire(monkeypatch, status=status,
                  payload=b'{"private":"fictional-provider-error"}',
                  headers={"Location": "https://other.invalid/"})
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).submit("start")
    assert (failure.value.code, failure.value.uncertain) == ("provider_unavailable", True)
    assert str(failure.value) == "provider_unavailable"
    assert native.constructor.call_count == native.connection.request.call_count == 1
    assert native.replies[0].read_sizes == []
    native.connection.close.assert_called_once_with()


@pytest.mark.parametrize("payload,headers", [
    (b'{"data":{}}', {"Content-Length": "500"}),
    (b'{"data":{}}', {"Content-Length": str(transport.MAX_BODY + 1)}),
    (b'{"data":{}}', {"Content-Encoding": "gzip"}),
    (b'{"data":{},"data":{}}', {}),
    (b'{"data":{"duplicate":1,"duplicate":2}}', {}),
    (b'{"data":{"value":NaN}}', {}),
    (b'{"data":{"value":1e999}}', {}),
    (b'{"data":[]}', {}), (b'{"other":{}}', {}), (b'private-not-json', {}),
    (b'x' * (transport.MAX_BODY + 1), {}),
])
def test_invalid_read_documents_are_bounded_refused_and_closed(monkeypatch, registered, payload, headers):
    native = wire(monkeypatch, payload=payload, headers=headers)
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).get_status()
    assert (failure.value.code, failure.value.uncertain) == ("invalid_response", False)
    assert str(failure.value) == "invalid_response"
    assert all(0 < size <= 65536 for reply in native.replies for size in reply.read_sizes)
    native.connection.close.assert_called_once_with()


@pytest.mark.parametrize("data", [{}, "", "not-a-UPID", UPID.replace("fictional-pve", "other")])
def test_invalid_submit_response_keeps_uncertainty(monkeypatch, registered, data):
    native = wire(monkeypatch, data=data)
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).submit("shutdown")
    assert (failure.value.code, failure.value.uncertain) == ("invalid_response", True)
    native.connection.close.assert_called_once_with()


@pytest.mark.parametrize("phase,code,uncertain", [
    ("connect", "provider_unavailable", False), ("request", "provider_unavailable", True),
    ("getresponse", "provider_unavailable", True), ("close", "provider_unavailable", True),
])
def test_submit_uncertainty_begins_at_post_attempt(monkeypatch, registered, phase, code, uncertain):
    native = wire(monkeypatch, data=UPID)
    getattr(native.connection, phase).side_effect = OSError("private-path-token-and-error")
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).submit("start")
    assert (failure.value.code, failure.value.uncertain) == (code, uncertain)
    assert str(failure.value) == code
    native.connection.close.assert_called_once_with()


def test_tls_failure_before_post_is_known_not_submitted(monkeypatch, registered):
    native = wire(monkeypatch)
    native.connection.connect.side_effect = ssl.SSLError("private-certificate-detail")
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).submit("start")
    assert (failure.value.code, failure.value.uncertain) == ("tls_unavailable", False)
    native.connection.request.assert_not_called()
    native.connection.close.assert_called_once_with()


def test_late_body_cannot_renew_call_deadline(monkeypatch, registered):
    native = wire(monkeypatch)
    instant = [100.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: instant[0])
    original = native.connection.getresponse.side_effect

    def delayed_response():
        response = original()
        read = response.read1

        def slow_read(size):
            chunk = read(size)
            instant[0] += 6
            return chunk

        response.read1 = slow_read
        return response

    native.connection.getresponse.side_effect = delayed_response
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).get_status()
    assert (failure.value.code, failure.value.uncertain) == ("provider_unavailable", False)
    native.connection.close.assert_called_once_with()


def test_memory_error_propagates_and_still_closes_connection(monkeypatch, registered):
    native = wire(monkeypatch)
    error = MemoryError("synthetic")
    native.connection.request.side_effect = error
    with pytest.raises(MemoryError) as failure:
        transport.LabPveTransport(registered).submit("start")
    assert failure.value is error
    native.connection.close.assert_called_once_with()


def test_cleanup_failure_does_not_hide_original_memory_error(monkeypatch, registered):
    native = wire(monkeypatch)
    error = MemoryError("synthetic")
    native.connection.request.side_effect = error
    native.connection.close.side_effect = OSError("synthetic-close")
    with pytest.raises(MemoryError) as failure:
        transport.LabPveTransport(registered).submit("start")
    assert failure.value is error


def test_incomplete_native_body_is_fixed_invalid_response(monkeypatch, registered):
    native = wire(monkeypatch)
    native.connection.getresponse.side_effect = http.client.IncompleteRead(b"private", 10)
    with pytest.raises(transport.LabTransportError) as failure:
        transport.LabPveTransport(registered).get_status()
    assert (failure.value.code, failure.value.uncertain) == ("invalid_response", False)
    native.connection.close.assert_called_once_with()


@contextlib.contextmanager
def local_provider(tls):
    observations = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def answer(self):
            length = int(self.headers.get("Content-Length", "0"))
            assert length <= 64
            body = self.rfile.read(length)
            observations.append((self.command, self.path, body,
                                 self.headers.get("Authorization") ==
                                 "PVEAPIToken=reader@pve!lab=fictional-token"))
            data = UPID if self.command == "POST" else {"status": "stopped", "name": "fictional-lab"}
            payload = json.dumps({"data": data}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)

        do_GET = answer
        do_POST = answer

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls / "server.pem", tls / "server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield server.server_port, observations
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def route_local_port(monkeypatch, port):
    original = http.client.HTTPSConnection

    def connect(host, fixed_port, *, timeout, context):
        assert fixed_port == 8006
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        return original(host, port, timeout=timeout, context=context)

    # Only the service lookup changes; stdlib HTTPSConnection's own explicit
    # super() lookup keeps its original class and all native wire behavior.
    client_view = SimpleNamespace(**vars(http.client))
    client_view.HTTPSConnection = connect
    monkeypatch.setattr(transport, "http", SimpleNamespace(client=client_view))


def test_actual_local_tls_exercises_reads_submission_forms_and_task_without_real_pve(
    monkeypatch, manifest, synthetic_tls
):
    manifest.document["provider"] = "localhost"
    manifest.ca.write_bytes((synthetic_tls / "ca.pem").read_bytes())
    manifest.write()
    record = load_registration(manifest.cfg, now=NOW)
    with local_provider(synthetic_tls) as (port, observations):
        route_local_port(monkeypatch, port)
        client = transport.LabPveTransport(record)
        assert client.get_config()["name"] == "fictional-lab"
        assert client.get_status()["status"] == "stopped"
        assert client.submit("start") == UPID
        assert client.submit("shutdown") == UPID
        assert client.get_task(UPID)["status"] == "stopped"
    assert observations == [
        ("GET", BASE + "/config", b"", True),
        ("GET", BASE + "/status/current", b"", True),
        ("POST", BASE + "/status/start", b"", True),
        ("POST", BASE + "/status/shutdown", b"forceStop=0&timeout=30", True),
        ("GET", "/api2/json/nodes/fictional-pve/tasks/" + quote(UPID, safe="") + "/status", b"", True),
    ]


@pytest.mark.parametrize("reason", ["untrusted-ca", "hostname-mismatch"])
def test_actual_local_tls_rejects_untrusted_ca_and_wrong_hostname_before_post(
    monkeypatch, manifest, synthetic_tls, reason
):
    manifest.document["provider"] = "localhost" if reason == "untrusted-ca" else "127.0.0.1"
    if reason == "hostname-mismatch":
        manifest.ca.write_bytes((synthetic_tls / "ca.pem").read_bytes())
    manifest.write()
    record = load_registration(manifest.cfg, now=NOW)
    with local_provider(synthetic_tls) as (port, observations):
        route_local_port(monkeypatch, port)
        with pytest.raises(transport.LabTransportError) as failure:
            transport.LabPveTransport(record).submit("start")
    assert (failure.value.code, failure.value.uncertain) == ("tls_unavailable", False)
    assert observations == []


@pytest.mark.parametrize("raw", [
    b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 20\r\n\r\nfictional-error-body",
    b'HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Encoding: gzip\r\nContent-Length: 11\r\n\r\n{"data":{}}',
    b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: 2097153\r\n\r\nfictional-body",
])
def test_real_stdlib_detached_response_reader_closes_on_early_refusal(monkeypatch, registered, raw):
    import io
    import socket
    sockets, responses = [], []

    class InMemorySocket:
        def __init__(self):
            self.fp = io.BytesIO(raw)
            self.closes = 0
        def makefile(self, *_args, **_kwargs): return self.fp
        def sendall(self, _data): pass
        def settimeout(self, _value): pass
        def close(self): self.closes += 1

    class OriginalHTTPS(http.client.HTTPSConnection):
        def connect(self):
            self.sock = InMemorySocket()
            sockets.append(self.sock)
        def getresponse(self):
            response = super().getresponse()
            responses.append(response)
            return response

    client_view = SimpleNamespace(**vars(http.client))
    client_view.HTTPSConnection = OriginalHTTPS
    monkeypatch.setattr(transport, "http", SimpleNamespace(client=client_view))
    monkeypatch.setattr(transport.ssl, "create_default_context",
                        lambda **_kwargs: SimpleNamespace(check_hostname=True, verify_mode=ssl.CERT_REQUIRED))
    monkeypatch.setattr(socket, "create_connection", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(socket, "socket", Mock(side_effect=AssertionError("network forbidden")))
    with pytest.raises(transport.LabTransportError):
        transport.LabPveTransport(registered).get_config()
    assert len(sockets) == len(responses) == 1
    assert type(responses[0]) is http.client.HTTPResponse and responses[0].will_close
    assert responses[0].fp is None and sockets[0].fp.closed
    assert sockets[0].closes == 1


def test_original_memory_error_survives_both_independent_cleanup_failures(monkeypatch, registered):
    class CleanupInterrupt(BaseException): pass
    native = wire(monkeypatch)
    make_response = native.connection.getresponse.side_effect
    original = MemoryError("fictional original read")
    held = []
    def getresponse():
        response = make_response()
        response.read1 = Mock(side_effect=original)
        response.close = Mock(side_effect=CleanupInterrupt())
        held.append(response)
        return response
    native.connection.getresponse.side_effect = getresponse
    native.connection.close.side_effect = RuntimeError("fictional cleanup")
    with pytest.raises(MemoryError) as failure:
        transport.LabPveTransport(registered).get_config()
    assert failure.value is original
    held[0].close.assert_called_once_with()
    native.connection.close.assert_called_once_with()


@pytest.mark.parametrize('guard', ['retired-session', 'expired-outer-deadline'])
def test_outer_qualification_guards_refuse_before_credential_or_network_io(monkeypatch, registered, guard):
    import time
    native = wire(monkeypatch)
    read = Mock(side_effect=AssertionError('credential read after failed guard'))
    monkeypatch.setattr(transport, 'read_token_secret', read)
    client = transport.LabPveTransport(registered)
    if guard == 'retired-session':
        client.current = lambda: False
    else:
        client.deadline = time.monotonic() - 1
    with pytest.raises(transport.LabTransportError) as failure:
        client.get_permissions()
    assert failure.value.uncertain is False
    assert failure.value.code == ('session_retired' if guard == 'retired-session' else 'provider_unavailable')
    read.assert_not_called()
    native.constructor.assert_not_called()


def test_outer_session_guard_rechecks_after_tls_before_selected_permission_get(monkeypatch, registered):
    native = wire(monkeypatch)
    state = {'current': True}
    native.connection.connect.side_effect = lambda: state.update(current=False)
    client = transport.LabPveTransport(registered)
    client.current = lambda: state['current']
    with pytest.raises(transport.LabTransportError) as failure:
        client.get_permissions()
    assert (failure.value.code, failure.value.uncertain) == ('session_retired', False)
    native.connection.request.assert_not_called()
    native.connection.close.assert_called_once_with()
