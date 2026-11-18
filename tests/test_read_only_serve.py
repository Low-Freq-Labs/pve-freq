"""Contained original startup/dispatch checks; no listener or provider effects."""
import contextlib
import io
import json
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from freq import _legacy_cli
from freq._legacy_cli import _build_parser
from freq.core import read_source_epoch
from freq.core.config import FreqConfig, _resolve_paths
from freq.core.first_admin_claim import claim_state_path
from freq.core.setup_state import SCHEMA
from freq.modules import serve


def handler(path, method="GET", *, read_only=True, body=None):
    h = serve.FreqHandler.__new__(serve.FreqHandler)
    h.server = SimpleNamespace(freq_read_only=read_only)
    h.path, h.command = path, method
    h.client_address = ("127.0.0.1", 12345)
    raw = json.dumps(body or {}).encode()
    h.headers = {"Host": "freq.test", "Content-Type": "application/json",
                 "Content-Length": str(len(raw))}
    h.rfile = io.BytesIO(raw)
    h.connection = object()
    h._json_response = Mock()
    return h


class Contained(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        # The original first-admin claim permanently retires this process's
        # read epoch. Give each test its own complete epoch/locks/tables, then
        # restore the exact previous objects. Never add a production reset.
        for name, value in (("_reads_retired", False), ("_epoch", object()),
                            ("_writers", {}), ("_readers", {}),
                            ("_gate", threading.RLock()), ("_table_gate", threading.Lock())):
            self.stack.enter_context(patch.object(read_source_epoch, name, value))
        for owner, name in ((socket, "socket"), (subprocess, "Popen"),
                            (threading.Thread, "start")):
            self.stack.enter_context(patch.object(
                owner, name, side_effect=AssertionError("uncontained effect")))


class Startup(Contained):
    def run_startup(self, root, *, read_only=True, bind=None, valid_tls=True,
                    wrap_error=None, corrupt_claim=False):
        cfg = FreqConfig(install_dir=root)
        _resolve_paths(cfg)
        if valid_tls:
            cfg.tls_cert, cfg.tls_key = "contained-cert", "contained-key"
        if corrupt_claim:
            claim = Path(claim_state_path(cfg))
            claim.parent.mkdir(parents=True, mode=0o700)
            claim.write_text("invalid claim")
            claim.chmod(0o600)
        server = Mock(socket=object())
        tls = Mock()
        if wrap_error:
            tls.wrap_socket.side_effect = wrap_error
        args = SimpleNamespace(port=18991, read_only=read_only, bind=bind)
        with contextlib.ExitStack() as stack:
            effects = {name: stack.enter_context(patch.object(serve, name)) for name in (
                "start_background_cache", "_start_embedded_watchdog_if_needed",
                "_start_cert_renewal_scheduler_if_needed", "_cleanup_ssh_mux")}
            listener = stack.enter_context(patch.object(serve, "ThreadedHTTPServer", return_value=server))
            stack.enter_context(patch.object(serve.ssl, "SSLContext", return_value=tls))
            signal = stack.enter_context(patch.object(serve.signal, "signal"))
            # Suppress the real ephemeral first-admin delivery; never persist it
            # in test output. The original durable claim implementation runs.
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            result = serve.cmd_serve(cfg, None, args)
        return result, cfg, server, tls, listener, effects, signal

    def test_read_only_default_and_explicit_bind_preserve_real_claim(self):
        for bind, expected in ((None, "127.0.0.1"), ("192.0.2.10", "192.0.2.10")):
            with self.subTest(bind=bind), tempfile.TemporaryDirectory() as root:
                result, cfg, server, tls, listener, effects, _ = self.run_startup(root, bind=bind)
                self.assertEqual(result, 0)
                listener.assert_called_once_with((expected, 18991), serve.FreqHandler)
                self.assertIs(server.freq_read_only, True)
                tls.load_cert_chain.assert_called_once_with(cfg.tls_cert, cfg.tls_key)
                tls.wrap_socket.assert_called_once()
                server.serve_forever.assert_called_once()
                server.server_close.assert_called_once()
                for effect in effects.values():
                    effect.assert_not_called()
                self.assertEqual(json.loads(Path(claim_state_path(cfg)).read_text())["state"], "available")

    def test_missing_tls_refuses_before_claim_listener_and_effects(self):
        with tempfile.TemporaryDirectory() as root:
            result, cfg, server, tls, listener, effects, signal = self.run_startup(root, valid_tls=False)
            self.assertEqual(result, 1)
            self.assertFalse(Path(claim_state_path(cfg)).exists())
            listener.assert_not_called()
            signal.assert_not_called()
            tls.load_cert_chain.assert_not_called()
            for effect in effects.values():
                effect.assert_not_called()

    def test_actual_invalid_tls_refuses_before_listener(self):
        with tempfile.TemporaryDirectory() as root:
            cfg = FreqConfig(install_dir=root)
            _resolve_paths(cfg)
            cfg.tls_cert = str(Path(root, "invalid.pem"))
            cfg.tls_key = cfg.tls_cert
            Path(cfg.tls_cert).write_text("invalid certificate")
            with patch.object(serve, "ThreadedHTTPServer") as listener, \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(serve.cmd_serve(cfg, None, SimpleNamespace(read_only=True)), 1)
            listener.assert_not_called()
            self.assertFalse(Path(claim_state_path(cfg)).exists())

    def test_tls_wrap_failure_closes_without_serving_or_signal_install(self):
        with tempfile.TemporaryDirectory() as root:
            result, _, server, _, _, effects, signal = self.run_startup(root, wrap_error=ssl.SSLError("contained"))
            self.assertEqual(result, 1)
            server.serve_forever.assert_not_called()
            server.server_close.assert_called_once()
            signal.assert_not_called()
            for effect in effects.values():
                effect.assert_not_called()

    def test_corrupt_claim_still_blocks_before_listener(self):
        with tempfile.TemporaryDirectory() as root:
            result, _, _, _, listener, effects, _ = self.run_startup(root, corrupt_claim=True)
            self.assertEqual(result, 1)
            listener.assert_not_called()
            for effect in effects.values():
                effect.assert_not_called()

    def test_ordinary_mode_keeps_bind_background_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            result, cfg, server, _, listener, effects, _ = self.run_startup(root, read_only=False, valid_tls=False)
            self.assertEqual(result, 0)
            listener.assert_called_once_with(("0.0.0.0", 18991), serve.FreqHandler)
            self.assertIs(server.freq_read_only, False)
            effects["start_background_cache"].assert_called_once_with()
            effects["_start_embedded_watchdog_if_needed"].assert_called_once_with(cfg)
            effects["_start_cert_renewal_scheduler_if_needed"].assert_called_once_with(cfg, serve._shutdown_flag)
            effects["_cleanup_ssh_mux"].assert_called_once_with(cfg)
            server.server_close.assert_called_once()

    def test_parser_defaults_and_read_only_bind(self):
        parser = _build_parser()
        ordinary = parser.parse_args(["serve"])
        self.assertFalse(ordinary.read_only)
        self.assertIsNone(ordinary.bind)
        selected = parser.parse_args(["serve", "--read-only", "--bind", "127.0.0.2", "--port", "18888"])
        self.assertTrue(selected.read_only)
        self.assertEqual((selected.bind, selected.port), ("127.0.0.2", 18888))

    def test_read_only_cli_never_discovers_plugins_and_normal_cli_still_does(self):
        for argv, expected in ((["serve", "--read-only"], 0),
                               (["--debug", "-y", "serve", "--read-only"], 0),
                               (["--debu", "serve", "--read-only"], 0),
                               (["serve", "--read-o"], 0),
                               (["serve"], 1)):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as root:
                cfg = FreqConfig(install_dir=root)
                _resolve_paths(cfg)
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.object(_legacy_cli, "load_config", return_value=cfg))
                    stack.enter_context(patch.object(_legacy_cli, "load_pack", return_value={}))
                    stack.enter_context(patch.object(_legacy_cli, "show_vibe"))
                    for name in ("init", "init_perf"):
                        stack.enter_context(patch.object(_legacy_cli.logger, name))
                    stack.enter_context(patch("freq.core.audit.init"))
                    discovery = stack.enter_context(patch("freq.core.plugins.discover_plugins", return_value=[]))
                    if expected == 0:
                        discovery.side_effect = AssertionError("plugin execution reached")
                    start = stack.enter_context(patch.object(serve, "cmd_serve", return_value=0))
                    self.assertEqual(_legacy_cli.main(argv), 0)
                    self.assertEqual(discovery.call_count, expected)
                    self.assertEqual(start.call_args.args[2].read_only, expected == 0)


class Dispatch(Contained):
    def test_every_unselected_registered_route_denied_before_auth_or_dispatch(self):
        # Enumerate the actual registry, not just a few known mutation paths.
        paths = set(serve.FreqHandler._load_routes()) | {
            "/api/pve/inventory/", "/api/pve/endpoints/", "/api/unknown",
            "/api/observe/v1/inventory", "/api/config", "/dashboardevil", "/other",
        }
        expected = {
            ("GET", "/api/pve/inventory"), ("GET", "/api/pve/endpoints"),
            ("POST", "/api/pve/endpoints"), ("POST", "/api/auth/login"),
            ("GET", "/api/auth/verify"), ("POST", "/api/auth/logout"),
            ("GET", "/api/setup/status"), ("POST", "/api/setup/create-admin"),
        }
        self.assertEqual(serve._READ_ONLY_API_ROUTES, expected)
        with patch.object(serve, "_check_session_role", side_effect=AssertionError("auth reached")):
            for method in ("GET", "POST"):
                for path in sorted(paths):
                    if (method, path) in expected or method == "GET" and path in ("/", "/dashboard", "/setup", "/setup.html"):
                        continue
                    with self.subTest(method=method, path=path):
                        h = handler(path, method)
                        h._load_routes = Mock(side_effect=AssertionError("endpoint reached"))
                        h._dispatch()
                        if path in ("/api/lab/guest", "/api/lab/power", "/api/lab/window"):
                            self.assertEqual(h._json_response.call_args.args[1], 404)
                            self.assertEqual(h._json_response.call_args.args[0]["error"], "not_found")
                        else:
                            self.assertEqual(h._json_response.call_args.args[1], 403)
                            self.assertEqual(h._json_response.call_args.args[0]["reason"], "read_only_mode")
                        self.assertTrue(h.close_connection)
                        h._load_routes.assert_not_called()

    def test_inventory_retains_original_unauthenticated_refusal(self):
        h = handler("/api/pve/inventory?refresh=1")
        h._load_routes = Mock(side_effect=AssertionError("endpoint reached"))
        h._dispatch()
        self.assertEqual(h._json_response.call_args.args, ({"error": "Authentication required"}, 403))
        h._load_routes.assert_not_called()

    def test_endpoint_post_still_checks_cookie_csrf_before_endpoint(self):
        h = handler("/api/pve/endpoints", "POST")
        h.headers["Cookie"] = "freq_session=contained-missing-session"
        h._load_routes = Mock(side_effect=AssertionError("endpoint reached"))
        with patch.object(serve, "_check_session_role", return_value=("admin", None)):
            h._dispatch()
        self.assertEqual(h._json_response.call_args.args[1], 403)
        h._load_routes.assert_not_called()

    def test_allowlisted_requests_retain_dispatch_and_auth_entry(self):
        for method, path in sorted(serve._READ_ONLY_API_ROUTES):
            with self.subTest(method=method, path=path):
                h = handler(path, method)
                destination = Mock()
                h._load_routes = Mock(return_value={path: destination})
                with patch.object(serve, "_check_session_role", return_value=("admin", None)) as auth, \
                        patch.object(serve, "_check_csrf", return_value=(True, "")) as csrf:
                    h._dispatch()
                destination.assert_called_once_with(h)
                if path not in serve.FreqHandler._AUTH_WHITELIST:
                    auth.assert_called_once_with(h, "viewer")
                    self.assertEqual(csrf.call_count, int(method == "POST" and path not in serve.FreqHandler._CSRF_EXEMPT))

    def test_assets_are_get_only_and_keep_original_path_validation(self):
        for path in ("/", "/dashboard", "/dashboard/fleet", "/static/app.js?v=current"):
            with self.subTest(path=path):
                h = handler(path)
                h._load_routes = Mock(return_value={})
                h._serve_app, h._serve_static = Mock(), Mock()
                h._dispatch()
                self.assertEqual(h._serve_app.call_count + h._serve_static.call_count, 1)
                h._json_response.assert_not_called()
                denied = handler(path, "POST")
                denied._dispatch()
                self.assertEqual(denied._json_response.call_args.args[1], 403)
        h = handler("/static/../secret")
        h._load_routes, h.send_error = Mock(return_value={}), Mock()
        h._dispatch()
        h.send_error.assert_called_once_with(403)

    def test_original_setup_pages_are_get_only_without_other_setup_apis(self):
        for path in ("/setup", "/setup.html"):
            with self.subTest(path=path):
                h = handler(path)
                # Keep the real registry and exact original page handler.
                target = serve.FreqHandler._load_routes()[path]
                self.assertIsInstance(target, str)
                with patch.object(h, target) as page:
                    h._dispatch()
                page.assert_called_once_with()
                h._json_response.assert_not_called()
                refused = handler(path, "POST")
                refused._dispatch()
                self.assertEqual(refused._json_response.call_args.args[1], 403)
        for path in ("/setup/other", "/setup.html/other", "/api/setup/configure", "/api/setup/init/start"):
            for method in ("GET", "POST"):
                with self.subTest(path=path, method=method):
                    h = handler(path, method)
                    h._load_routes = Mock(side_effect=AssertionError("endpoint reached"))
                    h._dispatch()
                    self.assertEqual(h._json_response.call_args.args[1], 403)
                    h._load_routes.assert_not_called()

    def test_ordinary_server_still_dispatches_other_routes(self):
        h = handler("/api/config", read_only=False)
        destination = Mock()
        h._load_routes = Mock(return_value={"/api/config": destination})
        with patch.object(serve, "_check_session_role", return_value=("viewer", None)):
            h._dispatch()
        destination.assert_called_once_with(h)

    def test_create_admin_rejects_runtime_account_before_any_mutation(self):
        for configured, supplied in (("freq-admin", "freq-admin"), ("runtime-agent", " RUNTIME-AGENT ")):
            with self.subTest(configured=configured):
                cfg = FreqConfig(ssh_service_account=configured)
                h = handler("/api/setup/create-admin", "POST", body={
                    "schema": SCHEMA, "username": supplied,
                    "password": "contained-password", "claim_secret": "contained-not-a-real-claim",
                    "client_request_id": "12345678-1234-4123-8123-123456789abc",
                })
                with patch.object(serve, "_request_is_https", return_value=True), \
                        patch.object(serve, "load_config", return_value=cfg), \
                        patch.object(serve, "locked_first_admin_claim") as claim, \
                        patch.object(serve, "_setup_store_admin_password") as vault, \
                        patch.object(serve, "_save_users_error") as users:
                    h._dispatch()
                payload, status = h._json_response.call_args.args
                self.assertEqual(status, 400)
                self.assertEqual((payload["error"]["code"], payload["error"]["field"]), ("invalid_field", "username"))
                claim.assert_not_called()
                vault.assert_not_called()
                users.assert_not_called()


class Isolation(unittest.TestCase):
    def test_original_claim_tests_restore_prior_source_epoch_objects(self):
        names = ("_reads_retired", "_epoch", "_writers", "_readers", "_gate", "_table_gate")
        original = {name: getattr(read_source_epoch, name) for name in names}
        result = unittest.TestResult()
        Startup("test_read_only_default_and_explicit_bind_preserve_real_claim").run(result)
        self.assertTrue(result.wasSuccessful(), (result.failures, result.errors))
        for name, value in original.items():
            self.assertIs(getattr(read_source_epoch, name), value, name)


if __name__ == "__main__":
    unittest.main()
