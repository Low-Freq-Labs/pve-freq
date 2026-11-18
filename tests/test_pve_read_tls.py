"""Real local TLS/wire checks against a fictional provider, not live acceptance."""

import contextlib
import http.client
import http.server
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import threading
from types import SimpleNamespace

import pytest

from freq.services import pve_read_inventory as inventory


@pytest.fixture(scope="module")
def synthetic_tls(tmp_path_factory):
    root = tmp_path_factory.mktemp("inventory-local-tls")
    openssl = shutil.which("openssl")
    assert openssl, "the local TLS check requires the documented OpenSSL prerequisite"

    def run(*args):
        subprocess.run([openssl, *args], cwd=root, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)

    try:
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "1",
            "-subj", "/CN=Fictional inventory test CA", "-keyout", "ca.key", "-out", "ca.pem",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        run("req", "-newkey", "rsa:2048", "-nodes", "-sha256",
            "-subj", "/CN=localhost", "-keyout", "server.key", "-out", "server.csr")
        (root / "server.ext").write_text(
            "subjectAltName=DNS:localhost\n"
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n", encoding="ascii")
        run("x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
            "-CAcreateserial", "-out", "server.pem", "-days", "1", "-sha256",
            "-extfile", "server.ext")
        yield root
    finally:
        shutil.rmtree(root)


@contextlib.contextmanager
def _provider(tls_root: Path, *, status=200, body=None, redirect=False):
    observations = []
    if body is None:
        body = json.dumps({"data": [
            {"type": "node", "node": "fictional-pve", "status": "online"},
            {"type": "qemu", "node": "fictional-pve", "vmid": 9001,
             "name": "fictional-stopped", "status": "stopped", "cpu": 0,
             "mem": 0, "maxmem": 2147483648},
        ]}).encode("utf-8")

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            # Retain a boolean comparison, never the Authorization value.
            observations.append({
                "path": self.path,
                "authorized": self.headers.get("Authorization") ==
                "PVEAPIToken=fictional@pve!reader=fictional-token",
                "accept": self.headers.get("Accept"),
                "encoding": self.headers.get("Accept-Encoding"),
            })
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            if redirect:
                self.send_header("Location", "/must-not-follow")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tls_root / "server.pem", tls_root / "server.key")
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield server.server_port, observations
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive(), "local fictional provider did not stop"


def _observe(monkeypatch, port, ca_file, *, source="localhost"):
    original_connection = http.client.HTTPSConnection
    calls = []

    def routed_connection(host, configured_port, *, timeout, context):
        assert configured_port == 8006
        assert context.check_hostname is True
        assert context.verify_mode == ssl.CERT_REQUIRED
        calls.append(host)
        return original_connection(host, port, timeout=timeout, context=context)

    # Keep stdlib's module globals intact: HTTPSConnection.__init__ itself
    # refers to its module's HTTPSConnection class in an explicit super call.
    # Only the service's constructor lookup receives the port adapter.
    client_view = SimpleNamespace(**vars(http.client))
    client_view.HTTPSConnection = routed_connection
    monkeypatch.setattr(inventory, "http", SimpleNamespace(client=client_view))
    monkeypatch.setattr(inventory, "_pve_api_credentials",
                        lambda *_args: ("fictional@pve!reader", "fictional-token"))
    cfg = SimpleNamespace(pve_nodes=[source], pve_api_ca_file=str(ca_file) if ca_file else "",
                          pve_api_verify_ssl=False)
    return inventory.resolve_inventory(cfg), calls


def test_actual_verified_tls_get_preserves_stopped_guest_without_template_inference(monkeypatch, synthetic_tls):
    with _provider(synthetic_tls) as (port, observations):
        result, calls = _observe(monkeypatch, port, synthetic_tls / "ca.pem")
    assert calls == ["localhost"]
    assert observations == [{"path": "/api2/json/cluster/resources", "authorized": True,
                             "accept": "application/json", "encoding": "identity"}]
    assert result["state"] == "ok"
    source = result["sources"][0]
    assert source["state"] == "ok"
    assert source["nodes"][0]["node"] == "fictional-pve"
    guest = source["guests"][0]
    assert (guest["vmid"], guest["name"], guest["status"]) == (9001, "fictional-stopped", "stopped")
    assert guest["template"] is None
    assert guest["mem"] == 0
    assert "fictional-token" not in json.dumps(result)


def test_actual_untrusted_certificate_refuses_before_http(monkeypatch, synthetic_tls):
    with _provider(synthetic_tls) as (port, observations):
        result, calls = _observe(monkeypatch, port, None)
    assert calls == ["localhost"]
    assert observations == []
    assert result["state"] == "unavailable"
    assert result["sources"][0]["error"] == "tls_unavailable"


def test_actual_trusted_ca_still_checks_source_hostname(monkeypatch, synthetic_tls):
    with _provider(synthetic_tls) as (port, observations):
        result, calls = _observe(monkeypatch, port, synthetic_tls / "ca.pem", source="127.0.0.1")
    assert calls == ["127.0.0.1"]
    assert observations == []
    assert result["sources"][0]["error"] == "tls_unavailable"


@pytest.mark.parametrize("status,redirect", [(302, True), (401, False)])
def test_actual_provider_refusal_is_sanitized_and_redirect_is_never_followed(
    monkeypatch, synthetic_tls, status, redirect
):
    with _provider(synthetic_tls, status=status, redirect=redirect,
                   body=b'{"error":"fictional-private-provider-response"}') as (port, observations):
        result, calls = _observe(monkeypatch, port, synthetic_tls / "ca.pem")
    assert calls == ["localhost"]
    assert len(observations) == 1
    assert observations[0]["path"] == "/api2/json/cluster/resources"
    assert observations[0]["authorized"] is True
    assert result["state"] == "unavailable"
    assert result["sources"][0]["error"] == "provider_unavailable"
    assert result["sources"][0]["guests"] == []
    assert "fictional-private-provider-response" not in json.dumps(result)
    assert "fictional-token" not in json.dumps(result)
