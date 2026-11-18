"""Contained original CLI/startup/dispatch checks for explicit cockpit mode."""
import contextlib
import io
import socket
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from freq import _legacy_cli
from freq.core.config import FreqConfig, _resolve_paths
from freq.modules import serve
from tests.test_lab_guest_api import OPERATION, api_case, handler, request_body, response  # noqa: F401


@pytest.fixture
def contained(monkeypatch):
    for owner, name in ((socket, "socket"), (socket, "create_connection"),
                        (subprocess, "Popen"), (subprocess, "run"), (threading.Thread, "start")):
        monkeypatch.setattr(owner, name, Mock(side_effect=AssertionError("uncontained effect")))


def startup(tmp_path, monkeypatch, *, bind=None, tls=True, wrap_error=None):
    cfg = FreqConfig(install_dir=str(tmp_path))
    _resolve_paths(cfg)
    if tls:
        cfg.tls_cert, cfg.tls_key = "fictional-server-cert", "fictional-server-key"
    server = Mock(socket=object())
    context = Mock()
    if wrap_error:
        context.wrap_socket.side_effect = wrap_error
    listener = Mock(return_value=server)
    claim = Mock(return_value={"state": "closed"})
    effects = {}
    for name in ("start_background_cache", "_start_embedded_watchdog_if_needed",
                 "_start_cert_renewal_scheduler_if_needed", "_cleanup_ssh_mux"):
        effects[name] = Mock(side_effect=AssertionError("background activity forbidden"))
        monkeypatch.setattr(serve, name, effects[name])
    monkeypatch.setattr(serve, "ThreadedHTTPServer", listener)
    monkeypatch.setattr(serve.ssl, "SSLContext", Mock(return_value=context))
    monkeypatch.setattr(serve, "prepare_first_admin_claim", claim)
    monkeypatch.setattr(serve, "_load_users", Mock(return_value=[]))
    monkeypatch.setattr(serve, "_setup_marker_exists", Mock(return_value=False))
    monkeypatch.setattr("freq.modules.users._load_users", Mock(return_value=[]))
    monkeypatch.setattr("freq.modules.vault.vault_get", Mock(side_effect=AssertionError("credential read forbidden")))
    monkeypatch.setattr(serve.signal, "signal", Mock())
    args = SimpleNamespace(read_only=False, lab_cockpit=True, bind=bind, port=18443)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = serve.cmd_serve(cfg, None, args)
    return SimpleNamespace(result=result, cfg=cfg, server=server, context=context,
                           listener=listener, claim=claim, effects=effects)


@pytest.mark.parametrize("bind,expected", [(None, "127.0.0.1"), ("192.0.2.20", "192.0.2.20")])
def test_lab_startup_requires_tls_and_skips_all_background_activity(tmp_path, monkeypatch, contained, bind, expected):
    observed = startup(tmp_path, monkeypatch, bind=bind)
    assert observed.result == 0
    observed.listener.assert_called_once_with((expected, 18443), serve.FreqHandler)
    assert observed.server.freq_lab_cockpit is True
    observed.context.load_cert_chain.assert_called_once_with(observed.cfg.tls_cert, observed.cfg.tls_key)
    observed.context.wrap_socket.assert_called_once()
    observed.server.serve_forever.assert_called_once_with()
    observed.server.server_close.assert_called_once_with()
    for effect in observed.effects.values():
        effect.assert_not_called()


def test_missing_tls_refuses_before_claim_listener_or_background(tmp_path, monkeypatch, contained):
    observed = startup(tmp_path, monkeypatch, tls=False)
    assert observed.result == 1
    observed.claim.assert_not_called()
    observed.listener.assert_not_called()
    for effect in observed.effects.values():
        effect.assert_not_called()


def test_tls_wrap_failure_closes_listener_without_serving(tmp_path, monkeypatch, contained):
    observed = startup(tmp_path, monkeypatch, wrap_error=OSError("fictional-TLS-failure"))
    assert observed.result == 1
    observed.server.serve_forever.assert_not_called()
    observed.server.server_close.assert_called_once_with()
    for effect in observed.effects.values():
        effect.assert_not_called()


def test_cli_mode_is_explicit_and_mutually_exclusive():
    parser = _legacy_cli._build_parser()
    assert parser.parse_args(["serve"]).lab_cockpit is False
    selected = parser.parse_args(["serve", "--lab-cockpit", "--bind", "127.0.0.2", "--port", "18443"])
    assert selected.lab_cockpit is True and selected.read_only is False
    assert (selected.bind, selected.port) == ("127.0.0.2", 18443)
    with contextlib.redirect_stderr(io.StringIO()), pytest.raises(SystemExit) as failure:
        parser.parse_args(["serve", "--lab-cockpit", "--read-only"])
    assert failure.value.code == 2


@pytest.mark.parametrize("argv", [["serve", "--lab-cockpit"], ["--debug", "-y", "serve", "--lab-cockpit"],
                                  ["serve", "--lab-cock"]])
def test_early_cli_selection_never_executes_installed_plugins(tmp_path, monkeypatch, contained, argv):
    cfg = FreqConfig(install_dir=str(tmp_path))
    _resolve_paths(cfg)
    monkeypatch.setattr(_legacy_cli, "load_config", Mock(return_value=cfg))
    monkeypatch.setattr(_legacy_cli, "load_pack", Mock(return_value={}))
    monkeypatch.setattr(_legacy_cli, "show_vibe", Mock())
    monkeypatch.setattr(_legacy_cli.logger, "init", Mock())
    monkeypatch.setattr(_legacy_cli.logger, "init_perf", Mock())
    monkeypatch.setattr("freq.core.audit.init", Mock())
    discover = Mock(side_effect=AssertionError("installed plugin executed"))
    monkeypatch.setattr("freq.core.plugins.discover_plugins", discover)
    start = Mock(return_value=0)
    monkeypatch.setattr(serve, "cmd_serve", start)
    assert _legacy_cli.main(argv) == 0
    discover.assert_not_called()
    assert start.call_args.args[2].lab_cockpit is True


def test_cockpit_denies_all_unselected_registry_routes_before_domain_dispatch(api_case, monkeypatch):
    permitted = set(serve._READ_ONLY_API_ROUTES) | {
        ("GET", "/api/lab/guest"), ("POST", "/api/lab/power"),
        ("GET", "/api/lab/window"), ("POST", "/api/lab/window")}
    paths = set(serve.FreqHandler._load_routes()) | {
        "/api/exec", "/api/vm/start", "/api/vm/shutdown", "/api/vm/stop", "/api/vm/reset",
        "/api/terminal/open", "/api/terminal/ws", "/api/lab/guest/", "/api/lab/power/",
        "/api/lab/operations/" + OPERATION + "/", "/api/lab/operations/UPID:private-task",
        "/api/lab/operations/" + "A" * 32, "/api/lab/anything", "/api/unknown",
    }
    for method in ("GET", "POST", "PUT", "DELETE"):
        for path in sorted(paths):
            if (method, path) in permitted:
                continue
            # Registry also declares exact public setup/SPA transport pages.
            if method == "GET" and path in ("/", "/dashboard", "/setup", "/setup.html"):
                continue
            value = handler(path, method, body=request_body())
            value._load_routes = Mock(side_effect=AssertionError("unselected endpoint reached"))
            value._dispatch()
            assert response(value)[1] in (403, 404), (method, path)
            assert value.close_connection, (method, path)
            value._load_routes.assert_not_called()
    assert api_case.calls == []


def test_operation_reference_is_exact_lowercase_hex_namespace(api_case):
    for suffix in ("", "g" * 32, "A" * 32, OPERATION + "/extra", "%31" * 32, "../guest"):
        value = handler("/api/lab/operations/" + suffix)
        value._dispatch()
        assert response(value)[1] in (400, 403, 404)
    assert api_case.calls == []


def test_persistent_handler_resets_consumed_lab_response_state_for_next_request(api_case):
    value = handler()
    value._dispatch()
    assert response(value)[1] == 200
    value.path = "/api/lab/guest"
    value._json_response.reset_mock()
    value.wfile = io.BytesIO()
    value.send_response.reset_mock()
    value._begin_request()
    value._dispatch()
    assert response(value)[1] == 200
    assert [call[0] for call in api_case.calls] == ["inspect", "inspect"]
