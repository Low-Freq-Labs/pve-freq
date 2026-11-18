"""Characterization for the Phase-3 PVE transport service seam."""

import ast
import inspect
import json
import ssl
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.services import pve_transport

REPO = Path(__file__).parent.parent
PVE_API_IMPORTS = {
    "ct.py": {"_find_reachable_node", "_pve_cmd"},
    "dr.py": {"_find_reachable_node", "_pve_cmd"},
    "vm.py": {"_find_reachable_node", "_find_vm_node", "_pve_cmd"},
}


def _cfg(**overrides):
    values = {
        "pve_api_token_id": "freq@pam!rw",
        "pve_api_token_secret": "configured-secret",
        "pve_api_verify_ssl": False,
        "credentials_dir": "/nonexistent",
        "ssh_key_path": "/credentials/freq-admin",
        "ssh_connect_timeout": 7,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode()


class _Context:
    def __init__(self):
        self.check_hostname = True
        self.verify_mode = ssl.CERT_REQUIRED


def test_runtime_token_prefers_configured_secret_as_is(tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    (credential_dir / "pve-token-rw").write_text("file-secret\n")
    cfg = _cfg(
        pve_api_token_secret="  configured-secret  ",
        credentials_dir=f"{credential_dir}/",
    )

    assert pve_transport._runtime_pve_api_token_secret(cfg) == "  configured-secret  "


def test_runtime_token_reads_stripped_file_and_handles_missing(tmp_path):
    credential_dir = tmp_path / "credentials"
    credential_dir.mkdir()
    token_path = credential_dir / "pve-token-rw"
    token_path.write_text("file-secret\n")

    assert pve_transport._runtime_pve_api_token_secret(
        _cfg(pve_api_token_secret="", credentials_dir=f"{credential_dir}/")
    ) == "file-secret"
    token_path.unlink()
    assert pve_transport._runtime_pve_api_token_secret(
        _cfg(pve_api_token_secret="", credentials_dir=str(credential_dir))
    ) == ""


@pytest.mark.parametrize(
    ("token_id", "secret", "expected"),
    [("freq@pam!rw", "secret", True), ("", "secret", False), ("freq@pam!rw", "", False)],
)
def test_token_predicate_is_truthiness_based(token_id, secret, expected):
    cfg = _cfg(pve_api_token_id=token_id, pve_api_token_secret=secret)
    assert pve_transport._has_pve_api_token(cfg) is expected


@pytest.mark.parametrize(
    ("method", "data", "expected_body", "content_type"),
    [
        ("GET", None, None, None),
        ("POST", {}, None, None),
        ("POST", {"vmid": 101, "name": "plex server"}, b"vmid=101&name=plex+server", "application/x-www-form-urlencoded"),
    ],
)
def test_api_request_preserves_url_headers_method_data_timeout_and_insecure_context(
    monkeypatch,
    method,
    data,
    expected_body,
    content_type,
):
    context = _Context()
    captured = {}

    def fake_urlopen(request, *, timeout, context):
        captured.update(request=request, timeout=timeout, context=context)
        return _Response({"data": None})

    monkeypatch.setattr(pve_transport.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(pve_transport.urllib.request, "urlopen", fake_urlopen)

    result, ok = pve_transport._pve_api_call(
        _cfg(),
        "192.0.2.10",
        "/nodes/pve01/status",
        method=method,
        data=data,
        timeout=11,
    )

    request = captured["request"]
    assert (result, ok) == (None, True)
    assert request.full_url == "https://192.0.2.10:8006/api2/json/nodes/pve01/status"
    assert request.get_method() == method
    assert request.data == expected_body
    assert request.get_header("Authorization") == "PVEAPIToken=freq@pam!rw=configured-secret"
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Content-type") == content_type
    assert captured["timeout"] == 11
    assert captured["context"] is context
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_api_verify_ssl_preserves_default_context(monkeypatch):
    context = _Context()
    monkeypatch.setattr(pve_transport.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(
        pve_transport.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response({"version": "8.2"}),
    )

    assert pve_transport._pve_api_call(_cfg(pve_api_verify_ssl=True), "192.0.2.10", "/version") == (
        {"version": "8.2"},
        True,
    )
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_api_missing_token_returns_without_network(monkeypatch):
    monkeypatch.setattr(
        pve_transport.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("missing token used network"),
    )
    assert pve_transport._pve_api_call(
        _cfg(pve_api_token_id="", pve_api_token_secret=""),
        "192.0.2.10",
        "/version",
    ) == ("", False)


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("unreachable"),
        urllib.error.HTTPError("https://example.invalid", 500, "failed", {}, None),
        OSError("socket failed"),
        TimeoutError("timed out"),
    ],
)
def test_api_caught_transport_failures_return_string_and_false(monkeypatch, error):
    monkeypatch.setattr(
        pve_transport.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )
    result, ok = pve_transport._pve_api_call(_cfg(), "192.0.2.10", "/version")
    assert ok is False
    assert result == str(error)


def test_api_invalid_json_is_caught(monkeypatch):
    monkeypatch.setattr(
        pve_transport.urllib.request,
        "urlopen",
        lambda *args, **kwargs: _Response(b"not-json"),
    )
    result, ok = pve_transport._pve_api_call(_cfg(), "192.0.2.10", "/version")
    assert ok is False
    assert result


def test_api_first_success_caps_timeout_and_skips_ssh():
    calls = []

    def api_call(*args, **kwargs):
        calls.append(("api", args, kwargs))
        return {"version": "8.2"}, True

    result = pve_transport._pve_call(
        _cfg(),
        "192.0.2.10",
        "/version",
        "pvesh get /version",
        timeout=60,
        method="POST",
        data={"key": "value"},
        has_token=lambda cfg: True,
        api_call=api_call,
        pve_cmd=lambda *args, **kwargs: pytest.fail("successful API used SSH"),
    )

    assert result == ({"version": "8.2"}, True)
    assert calls[0][2] == {"method": "POST", "data": {"key": "value"}, "timeout": 15}


@pytest.mark.parametrize("has_token", [False, True])
def test_no_token_or_api_failure_falls_back_with_original_timeout(has_token):
    api_calls = []
    ssh_calls = []

    def api_call(*args, **kwargs):
        api_calls.append((args, kwargs))
        return "API detail discarded", False

    def pve_cmd(*args, **kwargs):
        ssh_calls.append((args, kwargs))
        return "ssh result", True

    result = pve_transport._pve_call(
        _cfg(),
        "192.0.2.10",
        "/nodes",
        "pvesh get /nodes",
        timeout=22,
        has_token=lambda cfg: has_token,
        api_call=api_call,
        pve_cmd=pve_cmd,
    )

    assert result == ("ssh result", True)
    assert len(api_calls) == int(has_token)
    assert ssh_calls[0][1] == {"timeout": 22}


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "expected"),
    [(0, "ok", "ignored", ("ok", True)), (1, "partial", "error", ("partial", False)), (1, "  ", "error", ("error", False)), (1, "", "", ("", False))],
)
def test_ssh_command_preserves_kwargs_and_output_rules(returncode, stdout, stderr, expected):
    calls = []

    def ssh_runner(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    cfg = _cfg()
    assert pve_transport._pve_cmd(
        cfg,
        "192.0.2.10",
        "qm list",
        timeout=19,
        ssh_runner=ssh_runner,
    ) == expected
    assert calls == [
        {
            "host": "192.0.2.10",
            "command": "qm list",
            "key_path": "/credentials/freq-admin",
            "connect_timeout": 7,
            "command_timeout": 19,
            "htype": "pve",
            "use_sudo": True,
            "cfg": cfg,
        }
    ]


def test_module_adapters_preserve_signatures_and_legacy_patch_points():
    from freq.modules import pve as legacy_pve
    from freq.services import pve

    observed = {}
    for path in sorted((REPO / "freq" / "api").glob("*.py")):
        names = set()
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ImportFrom) and node.module == "freq.services.pve":
                names.update(alias.name for alias in node.names)
        if names:
            observed[path.name] = names
    assert observed == PVE_API_IMPORTS

    pve_tree = ast.parse((REPO / "freq" / "services" / "pve.py").read_text())
    definitions = {
        node.name: tuple(arg.arg for arg in node.args.args)
        for node in pve_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {name: definitions[name] for name in ("_pve_cmd", "_find_reachable_node", "_find_vm_node")} == {
        "_pve_cmd": ("cfg", "node_ip", "command", "timeout"),
        "_find_reachable_node": ("cfg",),
        "_find_vm_node": ("cfg", "vmid", "fallback_ip"),
    }
    assert not any(
        isinstance(node, ast.ImportFrom) and (node.module or "").startswith("freq.api")
        for node in ast.walk(pve_tree)
    )
    assert legacy_pve is pve

    assert str(inspect.signature(pve._pve_cmd)) == "(cfg: freq.core.config.FreqConfig, node_ip: str, command: str, timeout: int = 30) -> tuple"
    assert str(inspect.signature(pve._pve_call)) == "(cfg: freq.core.config.FreqConfig, node_ip: str, api_endpoint: str, ssh_command: str, timeout: int = 30, method: str = 'GET', data: dict = None) -> tuple"

    ssh_result = SimpleNamespace(returncode=0, stdout="legacy ssh", stderr="")
    with patch("freq.modules.pve.ssh_run", return_value=ssh_result) as ssh_run:
        assert pve._pve_cmd(_cfg(), "192.0.2.10", "qm list") == ("legacy ssh", True)
        ssh_run.assert_called_once()

    with patch("freq.modules.pve._pve_api_call", return_value=("api failed", False)) as api_call, patch(
        "freq.modules.pve._pve_cmd", return_value=("fallback", True)
    ) as pve_cmd:
        assert pve._pve_call(_cfg(), "192.0.2.10", "/nodes", "pvesh get /nodes") == (
            "fallback",
            True,
        )
        api_call.assert_called_once()
        pve_cmd.assert_called_once()

    cfg = _cfg(pve_nodes=["192.0.2.10", "192.0.2.11"])
    ssh_results = [
        SimpleNamespace(returncode=1, stdout="", stderr="unreachable"),
        SimpleNamespace(returncode=0, stdout="FOUND\n", stderr=""),
    ]
    with patch.object(pve, "_has_pve_api_token", return_value=True) as has_token, patch.object(
        pve,
        "_pve_api_call",
        side_effect=[("", False), ({"version": "8.2"}, True)],
    ) as api_call, patch.object(pve, "ssh_run", side_effect=ssh_results) as ssh_run:
        assert pve._find_reachable_node(cfg) == "192.0.2.11"
        assert has_token.call_count == 2
        assert [call.args[2] for call in api_call.call_args_list] == ["/version", "/version"]
        assert api_call.call_args_list[0].kwargs == {"timeout": pve.PVE_QUICK_TIMEOUT}
        assert ssh_run.call_count == 1
        assert ssh_run.call_args.kwargs == {
            "host": "192.0.2.10",
            "command": "pvesh get /version --output-format json",
            "key_path": "/credentials/freq-admin",
            "connect_timeout": 7,
            "command_timeout": pve.PVE_QUICK_TIMEOUT,
            "htype": "pve",
            "use_sudo": True,
            "cfg": cfg,
        }

    vm_results = [
        SimpleNamespace(returncode=0, stdout="NOTFOUND\n", stderr=""),
        SimpleNamespace(returncode=0, stdout="FOUND\n", stderr=""),
    ]
    with patch.object(pve, "ssh_run", side_effect=vm_results) as ssh_run:
        assert pve._find_vm_node(cfg, 501, "192.0.2.99") == "192.0.2.11"
        assert ssh_run.call_count == 2
        assert [call.kwargs["host"] for call in ssh_run.call_args_list] == cfg.pve_nodes
        assert all(
            call.kwargs["command"]
            == "test -f /etc/pve/qemu-server/501.conf && echo FOUND || echo NOTFOUND"
            for call in ssh_run.call_args_list
        )
        assert all(call.kwargs["command_timeout"] == 5 for call in ssh_run.call_args_list)

    with patch.object(
        pve,
        "ssh_run",
        side_effect=[
            SimpleNamespace(returncode=1, stdout="", stderr="failed"),
            SimpleNamespace(returncode=0, stdout="NOTFOUND\n", stderr=""),
        ],
    ):
        assert pve._find_vm_node(cfg, 501, "192.0.2.99") == "192.0.2.99"


def test_module_urllib_patch_intercepts_exact_api_alias():
    from freq.modules import pve

    with patch(
        "freq.modules.pve.urllib.request.urlopen",
        return_value=_Response({"data": {"version": "8.2"}}),
    ) as urlopen:
        assert pve._pve_api_call(_cfg(), "192.0.2.10", "/version") == (
            {"version": "8.2"},
            True,
        )
        urlopen.assert_called_once()


def test_direct_service_defaults_resolve_current_service_callables(monkeypatch):
    monkeypatch.setattr(pve_transport, "_has_pve_api_token", lambda cfg: False)
    monkeypatch.setattr(pve_transport, "_pve_cmd", lambda *args, **kwargs: ("direct", True))
    assert pve_transport._pve_call(
        _cfg(),
        "192.0.2.10",
        "/nodes",
        "pvesh get /nodes",
    ) == ("direct", True)
