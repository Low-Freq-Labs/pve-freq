"""E2E proof surfaces for init flow and dashboard truth.

Proves:
- _is_first_run() three-marker logic cannot lie
- /api/setup/status fields match on-disk reality
- /api/setup/complete cannot claim success; init owns completion markers
- /api/setup/create-admin rejects duplicate users
- /api/info version matches freq.__version__ (not stale)
- Setup endpoints gate on _is_first_run() (post-setup = 403)
"""
import ast
import contextlib
import datetime
import inspect
import io
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.case_matrix import run_case_matrix  # noqa: E402


def _make_handler(path="/", method="GET", headers=None, body=None):
    """Create a FreqHandler with captured response."""
    from freq.modules.serve import FreqHandler

    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.command = method
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO(body.encode() if body else b"")
    h.requestline = f"{method} {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = headers or {}
    h._headers_buffer = []
    h._status = None
    h._resp_headers = []

    def mock_send(code, msg=None):
        h._status = code

    def mock_header(k, v):
        h._resp_headers.append((k, v))

    h.send_response = mock_send
    h.send_header = mock_header
    h.end_headers = lambda: None
    return h


def _get_json(h):
    raw = h.wfile.getvalue()
    if not raw:
        return None
    return json.loads(raw.decode())


def _mock_cfg(tmpdir):
    """Create a minimal mock config pointing to a temp directory."""
    return SimpleNamespace(
        data_dir=os.path.join(tmpdir, "data"),
        conf_dir=os.path.join(tmpdir, "conf"),
        key_dir=os.path.join(tmpdir, "keys"),
        vault_dir=os.path.join(tmpdir, "data", "vault"),
        vault_file=os.path.join(tmpdir, "conf", "vault.json"),
        install_dir="/opt/freq",
        ssh_key_path=os.path.join(tmpdir, "keys", "freq_id_ed25519"),
        ssh_service_account="freq-admin",
        trusted_proxy_cidrs=[],
        pve_nodes=["192.168.10.1"],
        hosts=[],
        brand="FREQ",
        build="dev",
        cluster_name="testcluster",
        _toml_users=[],
    )


# ══════════════════════════════════════════════════════════════════════════
# _is_first_run() — three-marker truth logic
# ══════════════════════════════════════════════════════════════════════════

class TestIsFirstRunThreeMarkerLogic(unittest.TestCase):
    """_is_first_run() checks 3 conditions: web marker, CLI marker, users."""

    def _assert_first_run_gate_contract(self):
        """Freeze the fail-closed setup-opening decision before relocation."""
        from freq.api import auth
        from freq.modules import serve

        serve_tree = ast.parse(inspect.getsource(serve))
        self.assertIs(serve._is_first_run, auth.is_first_run)
        self.assertFalse(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_is_first_run"
                for node in ast.walk(serve_tree)
            )
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_is_first_run"
                for node in ast.walk(serve_tree)
            ),
            5,
        )
        self.assertFalse(
            any(
                isinstance(node, (ast.Import, ast.ImportFrom))
                for node in ast.walk(ast.parse(inspect.getsource(auth.is_first_run)))
            )
        )

        cfg = SimpleNamespace(data_dir="/data-root", conf_dir="/conf-root")
        loaded_users = object()
        with patch(
            "freq.modules.users._load_users",
            return_value=loaded_users,
        ) as user_loader:
            self.assertIs(auth._load_users(cfg), loaded_users)
        user_loader.assert_called_once_with(cfg)

        marker_paths = [
            "/data-root/setup-complete",
            "/conf-root/.initialized",
            "/conf-root/.web-setup-complete",
        ]

        for users in ([], None):
            with self.subTest(users=users), \
                 patch("freq.api.auth.load_config", return_value=cfg) as load_config, \
                 patch("freq.api.auth._load_users", return_value=users) as load_users, \
                 patch("freq.api.auth.os.path.isfile") as isfile:
                self.assertTrue(serve._is_first_run())
            load_config.assert_called_once_with()
            load_users.assert_called_once_with(cfg)
            isfile.assert_not_called()

        for marker_results, expected_paths in (
            ([True], marker_paths[:1]),
            ([False, True], marker_paths[:2]),
            ([False, False, True], marker_paths),
            ([False, False, False], marker_paths),
        ):
            with self.subTest(marker_results=marker_results), \
                 patch("freq.api.auth.load_config", return_value=cfg), \
                 patch(
                     "freq.api.auth._load_users",
                     return_value=[{"username": "operator", "role": "admin"}],
                 ) as load_users, \
                 patch(
                     "freq.api.auth.os.path.isfile",
                     side_effect=marker_results,
                 ) as isfile:
                self.assertFalse(serve._is_first_run())
            load_users.assert_called_once_with(cfg)
            self.assertEqual(isfile.call_args_list, [call(path) for path in expected_paths])

        with patch("freq.api.auth.load_config", return_value=cfg), \
             patch(
                 "freq.api.auth._load_users",
                 side_effect=OSError("users unreadable"),
             ) as load_users, \
             patch("freq.api.auth.os.path.isfile") as isfile, \
             patch("freq.api.auth.logger.error") as log_error:
            self.assertFalse(serve._is_first_run())
        load_users.assert_called_once_with(cfg)
        isfile.assert_not_called()
        log_error.assert_called_once_with(
            "_is_first_run: failed to check users — failing CLOSED to keep "
            "setup endpoints gated: users unreadable"
        )

        with patch(
            "freq.api.auth.load_config",
            side_effect=RuntimeError("config unavailable"),
        ), patch("freq.api.auth._load_users") as load_users, patch(
            "freq.api.auth.os.path.isfile"
        ) as isfile, self.assertRaisesRegex(RuntimeError, "config unavailable"):
            serve._is_first_run()
        load_users.assert_not_called()
        isfile.assert_not_called()

    def test_no_markers_no_users_is_first_run(self):
        """With no markers and no users, _is_first_run() must return True."""
        self._assert_first_run_gate_contract()
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            with patch("freq.api.auth.load_config", return_value=cfg), \
                 patch("freq.api.auth._load_users", return_value=[]):
                self.assertTrue(_is_first_run())

    def test_web_marker_means_not_first_run(self):
        """data/setup-complete marker + users must return False."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir, exist_ok=True)
            with open(os.path.join(cfg.data_dir, "setup-complete"), "w") as f:
                f.write("done\n")
            users = [{"username": "admin", "role": "admin"}]
            with patch("freq.api.auth.load_config", return_value=cfg), \
                 patch("freq.api.auth._load_users", return_value=users):
                self.assertFalse(_is_first_run())

    def test_cli_marker_means_not_first_run(self):
        """conf/.initialized marker + users must return False."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)
            with open(os.path.join(cfg.conf_dir, ".initialized"), "w") as f:
                f.write("done\n")
            users = [{"username": "admin", "role": "admin"}]
            with patch("freq.api.auth.load_config", return_value=cfg), \
                 patch("freq.api.auth._load_users", return_value=users):
                self.assertFalse(_is_first_run())

    def test_existing_users_means_not_first_run(self):
        """Users in users.conf alone must return False (no markers needed)."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            users = [{"username": "admin", "role": "admin"}]
            with patch("freq.api.auth.load_config", return_value=cfg), \
                 patch("freq.api.auth._load_users", return_value=users):
                self.assertFalse(_is_first_run())

    def test_user_load_failure_fails_closed(self):
        """If _load_users raises, _is_first_run() must return False (fail closed).

        F9 of R-SECURITY-TRUST-AUDIT-20260413P: fail-open was wrong — a
        transient IO error reopened the entire setup wizard surface to
        unauth callers. Fail-closed keeps the wizard gated.
        """
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            with patch("freq.api.auth.load_config", return_value=cfg), \
                 patch("freq.api.auth._load_users", side_effect=Exception("disk error")):
                self.assertFalse(_is_first_run(),
                                 "User load failure must fail CLOSED — never reopen wizard on read error")


# ══════════════════════════════════════════════════════════════════════════
# /api/setup/status — response accuracy
# ══════════════════════════════════════════════════════════════════════════

class TestSetupStatusAccuracy(unittest.TestCase):
    """/api/setup/status fields must match on-disk reality."""

    def _assert_setup_admin_window_contract(self):
        """Own setup-continuation authorization after relocation."""
        from freq.api import auth
        from freq.modules import serve

        serve_tree = ast.parse(inspect.getsource(serve))
        auth_function_tree = ast.parse(inspect.getsource(auth.allow_setup_admin_window))
        self.assertIs(serve._allow_setup_admin_window, auth.allow_setup_admin_window)
        self.assertFalse(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_allow_setup_admin_window"
                for node in ast.walk(serve_tree)
            )
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_allow_setup_admin_window"
                for node in ast.walk(serve_tree)
            ),
            2,
        )
        self.assertFalse(
            any(
                isinstance(node, (ast.Import, ast.ImportFrom))
                for node in ast.walk(auth_function_tree)
            )
        )

        cfg = object()

        responses = []
        handler = SimpleNamespace(
            _json_response=lambda payload, status: responses.append((payload, status))
        )
        with patch("freq.api.auth.load_config", return_value=cfg) as load_config, \
             patch("freq.api.auth._setup_marker_exists", return_value=True) as marker_exists, \
             patch("freq.api.auth.check_session_role") as role_check:
            self.assertFalse(serve._allow_setup_admin_window(handler))
        load_config.assert_called_once_with()
        marker_exists.assert_called_once_with(cfg)
        role_check.assert_not_called()
        self.assertEqual(
            responses,
            [
                (
                    {
                        "error": (
                            "Setup wizard already used — run freq init to complete "
                            "fleet deployment"
                        )
                    },
                    403,
                )
            ],
        )

        responses.clear()
        with patch("freq.api.auth.load_config", return_value=cfg), \
             patch("freq.api.auth._setup_marker_exists", return_value=False), \
             patch(
                 "freq.api.auth.check_session_role",
                 return_value=(None, "Authentication required"),
             ) as role_check:
            self.assertFalse(serve._allow_setup_admin_window(handler))
        role_check.assert_called_once_with(handler, "admin")
        self.assertEqual(responses, [({"error": "Authentication required"}, 403)])

        responses.clear()
        with patch("freq.api.auth.load_config", return_value=cfg), \
             patch("freq.api.auth._setup_marker_exists", return_value=False), \
             patch(
                 "freq.api.auth.check_session_role",
                 return_value=("admin", None),
             ) as role_check:
            self.assertTrue(serve._allow_setup_admin_window(handler))
        role_check.assert_called_once_with(handler, "admin")
        self.assertEqual(responses, [])

        for failure_stage in ("config", "marker", "role"):
            responses.clear()
            load_effect = RuntimeError("config unavailable") if failure_stage == "config" else None
            marker_effect = RuntimeError("marker unavailable") if failure_stage == "marker" else None
            role_effect = RuntimeError("role unavailable") if failure_stage == "role" else None
            with self.subTest(failure_stage=failure_stage), patch(
                "freq.api.auth.load_config",
                return_value=cfg,
                side_effect=load_effect,
            ) as load_config, patch(
                "freq.api.auth._setup_marker_exists",
                return_value=False,
                side_effect=marker_effect,
            ) as marker_exists, patch(
                "freq.api.auth.check_session_role",
                return_value=("admin", None),
                side_effect=role_effect,
            ) as role_check, self.assertRaisesRegex(
                RuntimeError,
                f"{failure_stage} unavailable",
            ):
                serve._allow_setup_admin_window(handler)
            load_config.assert_called_once_with()
            if failure_stage == "config":
                marker_exists.assert_not_called()
            else:
                marker_exists.assert_called_once_with(cfg)
            if failure_stage == "role":
                role_check.assert_called_once_with(handler, "admin")
            else:
                role_check.assert_not_called()
            self.assertEqual(responses, [])

    def _assert_setup_key_generation_contract(self):
        """Own setup-key generation before its implementation is relocated."""
        from freq.modules.serve import FreqHandler
        from freq.services import setup_keys

        handler_source = inspect.getsource(FreqHandler._serve_setup_generate_key)
        service_tree = ast.parse(inspect.getsource(setup_keys))
        self.assertIn(
            "_setup_keys.generate_setup_keys(load_config().key_dir)",
            handler_source,
        )
        self.assertNotIn("subprocess", handler_source)
        self.assertNotIn("os.", handler_source)
        self.assertIs(setup_keys.subprocess, __import__("subprocess"))
        self.assertEqual(
            {
                node.names[0].name
                for node in ast.walk(service_tree)
                if isinstance(node, ast.Import)
            },
            {"os", "subprocess"},
        )
        self.assertFalse(
            any(isinstance(node, ast.ImportFrom) for node in ast.walk(service_tree))
        )
        hostname = "setup-owner-node"

        with self.subTest(setup_key_case="existing-with-public-key"), \
             tempfile.TemporaryDirectory(prefix="freq-setup-key-owner-") as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.key_dir, mode=0o700)
            ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
            with open(ed_key, "w") as f:
                f.write("private")
            with open(f"{ed_key}.pub", "w") as f:
                f.write("ssh-ed25519 existing-key owner\n")

            h = _make_handler("/api/setup/generate-key", method="POST")
            with patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.services.setup_keys.os.uname", return_value=SimpleNamespace(nodename=hostname)), \
                 patch("freq.services.setup_keys.subprocess.run") as run:
                h._serve_setup_generate_key()

            run.assert_not_called()
            self.assertEqual(h._status, 200)
            self.assertEqual(
                _get_json(h),
                {
                    "ok": True,
                    "exists": True,
                    "pubkey": "ssh-ed25519 existing-key owner",
                    "key_path": ed_key,
                },
            )

        with self.subTest(setup_key_case="existing-without-public-key"), \
             tempfile.TemporaryDirectory(prefix="freq-setup-key-owner-") as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.key_dir, mode=0o700)
            ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
            with open(ed_key, "w") as f:
                f.write("private")

            h = _make_handler("/api/setup/generate-key", method="POST")
            with patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.services.setup_keys.os.uname", return_value=SimpleNamespace(nodename=hostname)), \
                 patch("freq.services.setup_keys.subprocess.run") as run:
                h._serve_setup_generate_key()

            run.assert_not_called()
            self.assertEqual(
                _get_json(h),
                {"ok": True, "exists": True, "pubkey": "", "key_path": ed_key},
            )

        with self.subTest(setup_key_case="ed25519-failure"), \
             tempfile.TemporaryDirectory(prefix="freq-setup-key-owner-") as tmpdir:
            cfg = _mock_cfg(tmpdir)
            ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
            stderr = "e" * 120
            h = _make_handler("/api/setup/generate-key", method="POST")
            with patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.services.setup_keys.os.uname", return_value=SimpleNamespace(nodename=hostname)), \
                 patch(
                     "freq.services.setup_keys.subprocess.run",
                     return_value=SimpleNamespace(returncode=17, stderr=stderr),
                 ) as run, patch("freq.services.setup_keys.os.chmod") as chmod:
                h._serve_setup_generate_key()

            run.assert_called_once_with(
                [
                    "ssh-keygen", "-t", "ed25519", "-C",
                    f"freq@{hostname}", "-f", ed_key, "-N", "", "-q",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            chmod.assert_not_called()
            self.assertEqual(h._status, 500)
            self.assertEqual(
                _get_json(h),
                {
                    "error": f"Key generation failed: {stderr[:100]}",
                    "request_id": "",
                },
            )
            self.assertEqual(os.stat(cfg.key_dir).st_mode & 0o777, 0o700)

        with self.subTest(setup_key_case="generate-both-key-types"), \
             tempfile.TemporaryDirectory(prefix="freq-setup-key-owner-") as tmpdir:
            cfg = _mock_cfg(tmpdir)
            ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
            rsa_key = os.path.join(cfg.key_dir, "freq_id_rsa")

            def generate(argv, **_kwargs):
                key_path = argv[argv.index("-f") + 1]
                with open(key_path, "w") as f:
                    f.write("private")
                with open(f"{key_path}.pub", "w") as f:
                    f.write("ssh-public generated-key owner\n")
                return SimpleNamespace(returncode=0, stderr="")

            h = _make_handler("/api/setup/generate-key", method="POST")
            with patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.services.setup_keys.os.uname", return_value=SimpleNamespace(nodename=hostname)), \
                 patch("freq.services.setup_keys.subprocess.run", side_effect=generate) as run:
                h._serve_setup_generate_key()

            self.assertEqual(
                run.call_args_list,
                [
                    call(
                        [
                            "ssh-keygen", "-t", "ed25519", "-C",
                            f"freq@{hostname}", "-f", ed_key, "-N", "", "-q",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    ),
                    call(
                        [
                            "ssh-keygen", "-t", "rsa", "-b", "4096", "-C",
                            f"freq-legacy@{hostname}", "-f", rsa_key, "-N", "", "-q",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    ),
                ],
            )
            self.assertEqual(os.stat(ed_key).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(f"{ed_key}.pub").st_mode & 0o777, 0o644)
            self.assertEqual(os.stat(rsa_key).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(f"{rsa_key}.pub").st_mode & 0o777, 0o644)
            self.assertEqual(
                _get_json(h),
                {
                    "ok": True,
                    "exists": False,
                    "pubkey": "ssh-public generated-key owner",
                    "key_path": ed_key,
                },
            )

        with self.subTest(setup_key_case="retain-existing-rsa-key"), \
             tempfile.TemporaryDirectory(prefix="freq-setup-key-owner-") as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.key_dir, mode=0o700)
            ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")
            rsa_key = os.path.join(cfg.key_dir, "freq_id_rsa")
            with open(rsa_key, "w") as f:
                f.write("legacy-private")
            os.chmod(rsa_key, 0o640)

            def generate_ed25519(argv, **_kwargs):
                self.assertEqual(argv[2], "ed25519")
                with open(ed_key, "w") as f:
                    f.write("private")
                with open(f"{ed_key}.pub", "w") as f:
                    f.write("ssh-ed25519 generated-key owner\n")
                return SimpleNamespace(returncode=0, stderr="")

            h = _make_handler("/api/setup/generate-key", method="POST")
            with patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.services.setup_keys.os.uname", return_value=SimpleNamespace(nodename=hostname)), \
                 patch("freq.services.setup_keys.subprocess.run", side_effect=generate_ed25519) as run:
                h._serve_setup_generate_key()

            self.assertEqual(run.call_count, 1)
            self.assertEqual(os.stat(rsa_key).st_mode & 0o777, 0o640)
            self.assertEqual(
                _get_json(h),
                {
                    "ok": True,
                    "exists": False,
                    "pubkey": "ssh-ed25519 generated-key owner",
                    "key_path": ed_key,
                },
            )

        with self.subTest(setup_key_case="legacy-generation-does-not-create-key"), \
             tempfile.TemporaryDirectory(prefix="freq-setup-key-owner-") as tmpdir:
            cfg = _mock_cfg(tmpdir)
            ed_key = os.path.join(cfg.key_dir, "freq_id_ed25519")

            def generate_ed25519_only(argv, **_kwargs):
                if argv[2] == "ed25519":
                    with open(ed_key, "w") as f:
                        f.write("private")
                    with open(f"{ed_key}.pub", "w") as f:
                        f.write("ssh-ed25519 generated-key owner\n")
                    return SimpleNamespace(returncode=0, stderr="")
                return SimpleNamespace(returncode=23, stderr="legacy generation failed")

            h = _make_handler("/api/setup/generate-key", method="POST")
            with patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.services.setup_keys.os.uname", return_value=SimpleNamespace(nodename=hostname)), \
                 patch("freq.services.setup_keys.subprocess.run", side_effect=generate_ed25519_only) as run:
                h._serve_setup_generate_key()

            self.assertEqual(run.call_count, 2)
            self.assertFalse(os.path.exists(os.path.join(cfg.key_dir, "freq_id_rsa")))
            self.assertEqual(
                _get_json(h),
                {
                    "ok": True,
                    "exists": False,
                    "pubkey": "ssh-ed25519 generated-key owner",
                    "key_path": ed_key,
                },
            )

    def test_first_run_true_when_no_markers(self):
        """first_run field must be True when no setup has occurred."""
        self._assert_setup_admin_window_contract()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            h = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h._serve_setup_status()
            data = _get_json(h)
            self.assertTrue(data["first_run"])

    def test_version_matches_module_version(self):
        """version field must match freq.__version__ for authenticated setup status."""
        import freq
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            h = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
                h._serve_setup_status()
            data = _get_json(h)
            self.assertEqual(data["version"], freq.__version__,
                             "version must match freq.__version__ exactly")

    def test_ssh_key_exists_reflects_disk(self):
        """ssh_key_exists must be True only when key file exists on disk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            # No key file — should be False
            h = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h._serve_setup_status()
            data = _get_json(h)
            self.assertFalse(data["ssh_key_exists"],
                             "ssh_key_exists must be False when key doesn't exist")

            # Create key file — should become True
            os.makedirs(cfg.key_dir, exist_ok=True)
            key_path = os.path.join(cfg.key_dir, "freq_id_ed25519")
            with open(key_path, "w") as f:
                f.write("fake-key\n")

            h2 = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h2._serve_setup_status()
            data2 = _get_json(h2)
            self.assertTrue(data2["ssh_key_exists"],
                            "ssh_key_exists must be True when key file exists")

        self._assert_setup_key_generation_contract()

    def test_pve_nodes_configured_reflects_config(self):
        """pve_nodes_configured must reflect actual config state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # With nodes
            cfg = _mock_cfg(tmpdir)
            cfg.pve_nodes = ["192.168.10.1", "192.168.10.2"]
            h = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h._serve_setup_status()
            data = _get_json(h)
            self.assertTrue(data["pve_nodes_configured"])

            # Without nodes
            cfg.pve_nodes = []
            h2 = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h2._serve_setup_status()
            data2 = _get_json(h2)
            self.assertFalse(data2["pve_nodes_configured"])


class TestInitStatusDurabilityCases(unittest.TestCase):
    """Own the current durable init-status boundary before typed persistence."""

    def _case_write_atomically_replaces_valid_json_and_cleans_staging_file(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            path = os.path.join(cfg.conf_dir, "init-status.json")
            tmp = f"{path}.tmp"
            real_replace = os.replace
            with patch("freq.modules.init_cmd.os.replace", side_effect=real_replace) as replace:
                init_cmd._write_init_status(
                    cfg,
                    {"initialized": False, "failed_checks": ["Phase 8 fleet deployment"]},
                )

            replace.assert_called_once_with(tmp, path)
            with open(path) as status_file:
                payload = json.load(status_file)
            self.assertIs(payload["initialized"], False)
            self.assertEqual(payload["failed_checks"], ["Phase 8 fleet deployment"])
            checked_at = datetime.datetime.fromisoformat(payload["checked_at"])
            self.assertEqual(checked_at.utcoffset(), datetime.timedelta(0))
            self.assertFalse(os.path.exists(tmp))

    def _case_replace_failure_preserves_prior_artifact_cleans_tmp_and_warns(self):
        from freq.modules import init_cmd

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)
            path = os.path.join(cfg.conf_dir, "init-status.json")
            tmp = f"{path}.tmp"
            prior = '{"initialized": true, "checked_at": "prior"}\n'
            with open(path, "w") as status_file:
                status_file.write(prior)

            with patch(
                "freq.modules.init_cmd.os.replace",
                side_effect=OSError("forced replace failure"),
            ), patch("freq.modules.init_cmd.fmt.step_warn") as warn:
                init_cmd._write_init_status(cfg, {"initialized": False})

            with open(path) as status_file:
                self.assertEqual(status_file.read(), prior)
            self.assertFalse(os.path.exists(tmp))
            warn.assert_called_once()
            self.assertIn("forced replace failure", warn.call_args.args[0])

    def _case_clear_is_idempotent(self):
        from freq.modules.init_cmd import _clear_init_status

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)
            path = os.path.join(cfg.conf_dir, "init-status.json")
            with open(path, "w") as status_file:
                status_file.write("{}\n")

            _clear_init_status(cfg)
            self.assertFalse(os.path.exists(path))
            _clear_init_status(cfg)
            self.assertFalse(os.path.exists(path))

    def _case_setup_status_consumes_failed_truth_and_ignores_success_record(self):
        cases = (
            (
                {"initialized": False, "failed_checks": ["Phase 8 fleet deployment failed"]},
                "Phase 8 fleet deployment failed",
            ),
            (
                {"initialized": False, "reason": "verification did not complete"},
                "verification did not complete",
            ),
        )
        for status, expected_reason in cases:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmpdir:
                cfg = _mock_cfg(tmpdir)
                os.makedirs(cfg.conf_dir, exist_ok=True)
                with open(os.path.join(cfg.conf_dir, "init-status.json"), "w") as status_file:
                    json.dump(status, status_file)
                h = _make_handler("/api/setup/status")
                with patch("freq.modules.serve.load_config", return_value=cfg), patch(
                    "freq.modules.serve._is_first_run", return_value=True
                ):
                    h._serve_setup_status()
                body = _get_json(h)
                self.assertEqual(body["setup_health"], "init-failed")
                self.assertIn(expected_reason, body["setup_reason"])
                self.assertIs(body["initialized"], False)

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)
            with open(os.path.join(cfg.conf_dir, "init-status.json"), "w") as status_file:
                json.dump(
                    {"initialized": True, "failed_checks": ["stale failure must be ignored"]},
                    status_file,
                )
            h = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), patch(
                "freq.modules.serve._is_first_run", return_value=True
            ):
                h._serve_setup_status()
            body = _get_json(h)
            self.assertNotEqual(body["setup_health"], "init-failed")
            self.assertNotIn("stale failure", body["setup_reason"])
            self.assertIs(body["initialized"], False)

    def _case_malformed_or_unreadable_status_never_claims_success(self):
        for unreadable in (False, True):
            with self.subTest(unreadable=unreadable), tempfile.TemporaryDirectory() as tmpdir:
                cfg = _mock_cfg(tmpdir)
                os.makedirs(cfg.conf_dir, exist_ok=True)
                path = os.path.join(cfg.conf_dir, "init-status.json")
                with open(path, "w") as status_file:
                    if unreadable:
                        json.dump(
                            {"initialized": False, "reason": "must not be readable"},
                            status_file,
                        )
                    else:
                        status_file.write("{not-json\n")
                if unreadable:
                    os.chmod(path, 0)
                    self.assertFalse(os.access(path, os.R_OK))
                h = _make_handler("/api/setup/status")
                with patch("freq.modules.serve.load_config", return_value=cfg), patch(
                    "freq.modules.serve._is_first_run", return_value=True
                ):
                    h._serve_setup_status()
                body = _get_json(h)
                self.assertIs(body["initialized"], False)
                self.assertNotEqual(body["setup_health"], "configured")
                self.assertNotEqual(body["setup_health"], "init-failed")

    def _case_cli_and_authenticated_web_share_canonical_status_projection(self):
        from freq.core.setup_state import _project_init_status
        from freq.modules import init_cmd

        cases = (
            (
                None,
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "not_started",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "freq init has not started",
                },
            ),
            (
                None,
                True,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "succeeded",
                    "initialized": True,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "freq init completed",
                },
            ),
            (
                {
                    "schema": "pve-freq-init-status-v2",
                    "state": "running",
                    "initialized": False,
                    "current_phase": 2,
                    "current_phase_key": "configure",
                    "reason": "",
                    "failed_checks": [],
                    "run_id": "a" * 32,
                    "private_value": "must-not-escape",
                },
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "running",
                    "initialized": False,
                    "current_phase": 2,
                    "current_phase_key": "configure",
                    "reason": "",
                },
            ),
            (
                {
                    "schema": "pve-freq-init-status-v1",
                    "state": "failed",
                    "initialized": False,
                    "current_phase": 8,
                    "current_phase_key": "fleet_deploy",
                    "reason": "",
                    "failed_checks": ["fleet deployment failed token=private-value"],
                },
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "failed",
                    "initialized": False,
                    "current_phase": 8,
                    "current_phase_key": "fleet_deploy",
                    "reason": "fleet deployment failed token=***REDACTED***",
                },
            ),
            (
                {
                    "schema": "pve-freq-init-status-v1",
                    "state": "succeeded",
                    "initialized": True,
                    "reason": "freq init completed",
                    "failed_checks": [],
                },
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "inconsistent",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "init status claims success without initialized marker",
                },
            ),
            (
                {
                    "schema": "pve-freq-init-status-v1",
                    "state": "running",
                    "initialized": False,
                    "current_phase": 2,
                    "current_phase_key": "service_account",
                    "reason": "",
                    "failed_checks": [],
                },
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "unknown",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "init status phase identity is invalid",
                },
            ),
            (
                {
                    "schema": "pve-freq-init-status-v1",
                    "state": "running",
                    "initialized": False,
                    "current_phase": False,
                    "current_phase_key": "",
                    "reason": "",
                    "failed_checks": [],
                },
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "unknown",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "init status phase identity is invalid",
                },
            ),
            (
                {
                    "schema": "pve-freq-init-status-v1",
                    "state": "running",
                    "initialized": False,
                    "current_phase": 0.0,
                    "current_phase_key": "",
                    "reason": "",
                    "failed_checks": [],
                },
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "unknown",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "init status phase identity is invalid",
                },
            ),
            (
                {
                    "schema": "pve-freq-init-status-v1",
                    "state": "running",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": None,
                    "reason": "",
                    "failed_checks": [],
                },
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "unknown",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "init status phase identity is invalid",
                },
            ),
            (
                "{not-json\n",
                False,
                {
                    "schema": "pve-freq-init-status-public-v1",
                    "state": "unknown",
                    "initialized": False,
                    "current_phase": 0,
                    "current_phase_key": "",
                    "reason": "init status is unreadable",
                },
            ),
        )
        for status, marker, expected in cases:
            with self.subTest(status=status, marker=marker), tempfile.TemporaryDirectory() as tmpdir:
                cfg = _mock_cfg(tmpdir)
                cfg.hosts = []
                cfg.pve_nodes = []
                os.makedirs(cfg.conf_dir, exist_ok=True)
                if marker:
                    with open(os.path.join(cfg.conf_dir, ".initialized"), "w") as marker_file:
                        marker_file.write("initialized\n")
                if isinstance(status, dict):
                    with open(os.path.join(cfg.conf_dir, "init-status.json"), "w") as status_file:
                        json.dump(status, status_file)
                elif isinstance(status, str):
                    with open(os.path.join(cfg.conf_dir, "init-status.json"), "w") as status_file:
                        status_file.write(status)

                self.assertEqual(_project_init_status(cfg), expected)

                stdout = io.StringIO()
                with patch("freq.modules.init_cmd._run", return_value=(1, "", "")), patch(
                    "sys.stdout", new=stdout
                ):
                    init_cmd._init_check(cfg, json_output=True)
                cli_projection = json.loads(stdout.getvalue())["init_status"]

                h = _make_handler("/api/setup/status")
                users = [{"username": "admin", "role": "admin"}]
                with patch("freq.modules.serve.load_config", return_value=cfg), patch(
                    "freq.modules.serve._is_first_run", return_value=False
                ), patch("freq.modules.serve._setup_init_snapshot", return_value={}), patch(
                    "freq.modules.serve._observe_setup_state", return_value={}
                ), patch("freq.modules.serve._load_users", return_value=users), patch(
                    "freq.modules.serve._check_session_role", return_value=("admin", None)
                ), patch("freq.modules.serve.vault_get", return_value=None):
                    h._serve_setup_status()
                web_projection = _get_json(h)["init_status"]

                self.assertEqual(cli_projection, expected)
                self.assertEqual(web_projection, expected)
                self.assertEqual(
                    json.dumps(cli_projection, sort_keys=True, separators=(",", ":")),
                    json.dumps(web_projection, sort_keys=True, separators=(",", ":")),
                )


INIT_STATUS_DURABILITY_CASES = (
    "_case_write_atomically_replaces_valid_json_and_cleans_staging_file",
    "_case_replace_failure_preserves_prior_artifact_cleans_tmp_and_warns",
    "_case_clear_is_idempotent",
    "_case_setup_status_consumes_failed_truth_and_ignores_success_record",
    "_case_malformed_or_unreadable_status_never_claims_success",
    "_case_cli_and_authenticated_web_share_canonical_status_projection",
)


class TestInitStatusDurabilityOwnerMatrix(unittest.TestCase):
    def test_init_status_durability_matrix(self):
        self.assertEqual(len(INIT_STATUS_DURABILITY_CASES), 6)
        run_case_matrix(
            self,
            TestInitStatusDurabilityCases,
            INIT_STATUS_DURABILITY_CASES,
        )


# ══════════════════════════════════════════════════════════════════════════
# /api/setup/complete — retired; successful web init owns finalization
# ══════════════════════════════════════════════════════════════════════════

class TestSetupCompleteFinalization(unittest.TestCase):
    """Only a successful web-launched init may write completion markers."""

    def _case_web_marker_writer_contract(self):
        import ast

        from freq import __version__
        from freq.modules import serve
        from freq.services import setup_health

        _write_web_setup_markers = serve._write_web_setup_markers
        self.assertIs(_write_web_setup_markers, setup_health.write_web_setup_markers)
        self.assertFalse(
            any(
                isinstance(node, ast.FunctionDef)
                and node.name == "_write_web_setup_markers"
                for node in ast.walk(ast.parse(inspect.getsource(serve)))
            )
        )
        self.assertEqual(inspect.getsource(serve).count("_write_web_setup_markers(cfg)"), 1)
        self.assertNotIn("freq.modules", inspect.getsource(setup_health))

        stamp = datetime.datetime(2026, 7, 21, 2, 45, 0)
        setup_text = f"Setup completed: {stamp.isoformat()}\n"
        web_text = f"PVE FREQ {__version__} — web setup {stamp.isoformat()}\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            with patch("freq.services.setup_health.datetime.datetime") as clock:
                clock.now.return_value = stamp
                result = _write_web_setup_markers(cfg)
            self.assertIsNone(result)
            with open(os.path.join(cfg.data_dir, "setup-complete")) as handle:
                self.assertEqual(handle.read(), setup_text)
            with open(os.path.join(cfg.conf_dir, ".web-setup-complete")) as handle:
                self.assertEqual(handle.read(), web_text)
            self.assertFalse(os.path.exists(os.path.join(cfg.conf_dir, ".initialized")))

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir)
            os.makedirs(cfg.conf_dir)
            paths = {
                "setup": os.path.join(cfg.data_dir, "setup-complete"),
                "web": os.path.join(cfg.conf_dir, ".web-setup-complete"),
                "initialized": os.path.join(cfg.conf_dir, ".initialized"),
            }
            for name, path in paths.items():
                with open(path, "w") as handle:
                    handle.write(f"preserve-{name}\n")
            with patch("freq.services.setup_health.datetime.datetime") as clock:
                clock.now.side_effect = AssertionError(
                    "existing markers must not evaluate a timestamp"
                )
                self.assertIsNone(_write_web_setup_markers(cfg))
            for name, path in paths.items():
                with open(path) as handle:
                    self.assertEqual(handle.read(), f"preserve-{name}\n")

        for existing in ("setup", "web"):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmpdir:
                cfg = _mock_cfg(tmpdir)
                os.makedirs(cfg.data_dir)
                os.makedirs(cfg.conf_dir)
                setup_marker = os.path.join(cfg.data_dir, "setup-complete")
                web_marker = os.path.join(cfg.conf_dir, ".web-setup-complete")
                existing_path = setup_marker if existing == "setup" else web_marker
                with open(existing_path, "w") as handle:
                    handle.write("preserve-existing\n")
                with patch("freq.services.setup_health.datetime.datetime") as clock:
                    clock.now.return_value = stamp
                    self.assertIsNone(_write_web_setup_markers(cfg))
                with open(existing_path) as handle:
                    self.assertEqual(handle.read(), "preserve-existing\n")
                missing_path = web_marker if existing == "setup" else setup_marker
                expected = web_text if existing == "setup" else setup_text
                with open(missing_path) as handle:
                    self.assertEqual(handle.read(), expected)
                self.assertFalse(os.path.exists(os.path.join(cfg.conf_dir, ".initialized")))

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir)
            os.mkdir(os.path.join(cfg.data_dir, "setup-complete"))
            with self.assertRaises(IsADirectoryError):
                _write_web_setup_markers(cfg)
            self.assertFalse(os.path.exists(cfg.conf_dir))

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir)
            os.mkdir(os.path.join(cfg.conf_dir, ".web-setup-complete"))
            with patch("freq.services.setup_health.datetime.datetime") as clock:
                clock.now.return_value = stamp
                with self.assertRaises(IsADirectoryError):
                    _write_web_setup_markers(cfg)
            with open(os.path.join(cfg.data_dir, "setup-complete")) as handle:
                self.assertEqual(handle.read(), setup_text)
            self.assertFalse(os.path.exists(os.path.join(cfg.conf_dir, ".initialized")))

    def test_legacy_complete_endpoint_is_disabled(self):
        """The legacy endpoint cannot claim setup success."""
        h = _make_handler("/api/setup/complete", method="POST")
        h._serve_setup_complete()
        self.assertEqual(h._status, 409)
        self.assertEqual(_get_json(h)["error"]["code"], "legacy_endpoint_disabled")

    def test_successful_init_marker_writer_records_web_setup(self):
        """The init success path writes both web markers, not .initialized."""
        self._case_web_marker_writer_contract()

    def test_marker_writer_is_idempotent(self):
        """A repeated init-success callback must preserve completed state."""
        from freq.modules.serve import _write_web_setup_markers

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            _write_web_setup_markers(cfg)
            _write_web_setup_markers(cfg)
            self.assertTrue(os.path.isfile(os.path.join(cfg.data_dir, "setup-complete")))
            self.assertTrue(os.path.isfile(os.path.join(cfg.conf_dir, ".web-setup-complete")))

    def test_is_first_run_false_after_init_success_marker(self):
        """The successful-init marker closes first-run when an operator exists."""
        from freq.modules.serve import _is_first_run, _write_web_setup_markers

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            _write_web_setup_markers(cfg)
            users = [{"username": "admin", "role": "admin"}]
            with patch("freq.api.auth.load_config", return_value=cfg), \
                 patch("freq.api.auth._load_users", return_value=users):
                self.assertFalse(_is_first_run())


# ══════════════════════════════════════════════════════════════════════════
# /api/setup/create-admin — duplicate rejection
# ══════════════════════════════════════════════════════════════════════════

class TestSetupCreateAdminDuplicateGuard(unittest.TestCase):
    """create-admin is HTTPS-only, single-use, and accepts no path inputs."""

    def setUp(self):
        self._https = patch("freq.modules.serve._request_is_https", return_value=True)
        self._https.start()
        self.addCleanup(self._https.stop)

        @contextlib.contextmanager
        def available_claim(_cfg):
            yield SimpleNamespace(
                state_name="available",
                claim_id="legacy-regression-fixture",
                matches=lambda _candidate: True,
                consume=lambda: None,
            )

        self._claim = patch(
            "freq.modules.serve.locked_first_admin_claim",
            side_effect=available_claim,
        )
        self._claim.start()
        self.addCleanup(self._claim.stop)

    def _setup_handler(self, body_str):
        """Create a handler with proper Content-Length for body parsing."""
        body = json.loads(body_str)
        body.setdefault("schema", "zero-state-web-v1")
        body.setdefault("username", "newadmin")
        body.setdefault("password", "validpass123")
        body.setdefault("claim_secret", "legacy-regression-claim")
        body.setdefault("client_request_id", "12345678-1234-4123-8123-123456789abc")
        body_str = json.dumps(body)
        h = _make_handler(
            "/api/setup/create-admin", method="POST", body=body_str
        )
        h.headers = {
            "Content-Length": str(len(body_str)),
            "Content-Type": "application/json",
        }
        return h

    def _assert_setup_password_store_contract(self):
        """Own setup password-vault storage after relocation."""
        from freq.api import auth
        from freq.modules import serve

        serve_tree = ast.parse(inspect.getsource(serve))
        auth_function_tree = ast.parse(
            inspect.getsource(auth._setup_store_admin_password)
        )
        self.assertIs(
            serve._setup_store_admin_password,
            auth._setup_store_admin_password,
        )
        self.assertFalse(
            any(
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "_setup_store_admin_password"
                for node in ast.walk(serve_tree)
            )
        )
        self.assertEqual(
            sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_setup_store_admin_password"
                for node in ast.walk(serve_tree)
            ),
            1,
        )
        self.assertFalse(
            any(
                isinstance(node, (ast.Import, ast.ImportFrom))
                for node in ast.walk(auth_function_tree)
            )
        )

        cfg = SimpleNamespace(vault_file="/runtime/freq-vault.enc")
        username = "setup-admin"
        password = "correct horse battery staple"
        password_hash = "pbkdf2-owner-hash"
        vault_key = "password_setup-admin"

        with patch(
            "freq.api.auth.hash_password",
            return_value=password_hash,
        ) as hash_password, patch(
            "freq.api.auth.os.path.exists",
            return_value=False,
        ) as exists, patch(
            "freq.api.auth.vault_init",
            return_value=True,
        ) as vault_init, patch(
            "freq.api.auth.vault_set",
            return_value=True,
        ) as vault_set, patch(
            "freq.api.auth.vault_get",
            return_value=password_hash,
        ) as vault_get:
            timeline = unittest.mock.Mock()
            timeline.attach_mock(hash_password, "hash")
            timeline.attach_mock(exists, "exists")
            timeline.attach_mock(vault_init, "init")
            timeline.attach_mock(vault_set, "set")
            timeline.attach_mock(vault_get, "get")
            self.assertEqual(
                serve._setup_store_admin_password(cfg, username, password),
                "",
            )
        self.assertEqual(
            timeline.mock_calls,
            [
                call.hash(password),
                call.exists(cfg.vault_file),
                call.init(cfg),
                call.set(cfg, "auth", vault_key, password_hash),
                call.get(cfg, "auth", vault_key),
            ],
        )

        scenarios = (
            (
                "init-false",
                False,
                False,
                True,
                "Failed to initialize password vault",
                (1, 0, 0),
            ),
            (
                "set-false",
                True,
                True,
                False,
                "Failed to store password in vault",
                (0, 1, 0),
            ),
            (
                "verify-false",
                True,
                True,
                True,
                "Password storage verification failed",
                (0, 1, 1),
            ),
        )
        for (
            name,
            vault_exists,
            init_result,
            set_result,
            expected,
            expected_counts,
        ) in scenarios:
            with self.subTest(password_store_case=name), patch(
                "freq.api.auth.hash_password",
                return_value=password_hash,
            ) as hash_password, patch(
                "freq.api.auth.os.path.exists",
                return_value=vault_exists,
            ) as exists, patch(
                "freq.api.auth.vault_init",
                return_value=init_result,
            ) as vault_init, patch(
                "freq.api.auth.vault_set",
                return_value=set_result,
            ) as vault_set, patch(
                "freq.api.auth.vault_get",
                return_value="",
            ) as vault_get:
                self.assertEqual(
                    serve._setup_store_admin_password(cfg, username, password),
                    expected,
                )
            hash_password.assert_called_once_with(password)
            exists.assert_called_once_with(cfg.vault_file)
            self.assertEqual(
                (vault_init.call_count, vault_set.call_count, vault_get.call_count),
                expected_counts,
            )
            if vault_set.called:
                vault_set.assert_called_once_with(
                    cfg,
                    "auth",
                    vault_key,
                    password_hash,
                )
            if vault_get.called:
                vault_get.assert_called_once_with(cfg, "auth", vault_key)

        with patch(
            "freq.api.auth.hash_password",
            side_effect=RuntimeError("hash unavailable"),
        ), patch("freq.api.auth.os.path.exists") as exists, self.assertRaisesRegex(
            RuntimeError,
            "hash unavailable",
        ):
            serve._setup_store_admin_password(cfg, username, password)
        exists.assert_not_called()

        exception_stages = (
            ("exists", True, None, None, None),
            ("init", False, True, None, None),
            ("set", True, None, True, None),
            ("get", True, None, None, True),
        )
        for stage, vault_exists, init_raises, set_raises, get_raises in exception_stages:
            error = RuntimeError(f"{stage} unavailable")
            with self.subTest(password_store_exception=stage), patch(
                "freq.api.auth.hash_password",
                return_value=password_hash,
            ), patch(
                "freq.api.auth.os.path.exists",
                return_value=vault_exists,
                side_effect=error if stage == "exists" else None,
            ) as exists, patch(
                "freq.api.auth.vault_init",
                return_value=True,
                side_effect=error if init_raises else None,
            ) as vault_init, patch(
                "freq.api.auth.vault_set",
                return_value=True,
                side_effect=error if set_raises else None,
            ) as vault_set, patch(
                "freq.api.auth.vault_get",
                return_value=password_hash,
                side_effect=error if get_raises else None,
            ) as vault_get:
                self.assertEqual(
                    serve._setup_store_admin_password(cfg, username, password),
                    f"{stage} unavailable",
                )
            self.assertEqual(exists.call_count, 1)
            expected_init = int(stage == "init")
            expected_set = int(stage in {"set", "get"})
            expected_get = int(stage == "get")
            self.assertEqual(
                (vault_init.call_count, vault_set.call_count, vault_get.call_count),
                (expected_init, expected_set, expected_get),
            )

    def test_duplicate_username_returns_409(self):
        """Creating same user twice must return 409."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)

            existing_users = [{"username": "admin", "role": "admin", "groups": ""}]
            body = '{"username":"admin","password":"testpass123"}'
            h = self._setup_handler(body)

            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve._load_users", return_value=existing_users):
                h._serve_setup_create_admin()

            self.assertEqual(h._status, 409)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "operator_exists")

    def test_short_password_rejected(self):
        """Password under 8 chars must be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            body = '{"username":"newadmin","password":"short"}'
            h = self._setup_handler(body)
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h._serve_setup_create_admin()
            self.assertEqual(h._status, 400)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "invalid_password")

    def test_invalid_username_rejected(self):
        """Username with invalid chars must be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            body = '{"username":"Admin User!","password":"validpass123"}'
            h = self._setup_handler(body)
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h._serve_setup_create_admin()
            self.assertEqual(h._status, 400)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "invalid_username")

    def test_password_file_is_rejected_without_reading_server_path(self):
        """Browser setup must reject every server-side credential path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            body = '{"username":"newadmin","password_file":"/freq-init-inputs/missing"}'
            h = self._setup_handler(body)

            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("builtins.open") as mock_open:
                h._serve_setup_create_admin()

            self.assertEqual(h._status, 400)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "path_input_not_allowed")
            self.assertNotIn("field", data["error"])
            mock_open.assert_not_called()

    def test_create_admin_creates_missing_conf_dir(self):
        """Zero-state create-admin must create conf_dir before users.conf."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            cfg.vault_dir = os.path.join(tmpdir, "vault")
            cfg.vault_file = os.path.join(cfg.vault_dir, "freq-vault.enc")
            body = '{"username":"newadmin","password":"validpass123"}'
            h = self._setup_handler(body)

            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.vault._vault_key", return_value="a" * 64):
                h._serve_setup_create_admin()

            self.assertEqual(h._status, 200)
            self.assertTrue(os.path.isfile(os.path.join(cfg.conf_dir, "users.conf")))

    def test_create_admin_existing_operator_requires_normal_auth(self):
        """An existing operator cannot be resumed through credential creation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)
            existing_users = [{"username": "admin", "role": "admin", "groups": ""}]
            body = '{"username":"admin","password":"validpass123"}'
            h = self._setup_handler(body)

            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=existing_users), \
                 patch("freq.modules.serve._setup_marker_exists", return_value=False), \
                 patch("freq.modules.serve._setup_store_admin_password") as mock_store:
                h._serve_setup_create_admin()

            self.assertEqual(h._status, 409)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "operator_exists")
            mock_store.assert_not_called()

    def test_create_admin_closed_after_completion_marker(self):
        """Completed setup cannot be reopened through create-admin."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)
            existing_users = [{"username": "admin", "role": "admin", "groups": ""}]
            body = '{"username":"admin","password":"validpass123"}'
            h = self._setup_handler(body)

            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=existing_users), \
                 patch("freq.modules.serve._setup_marker_exists", return_value=True):
                h._serve_setup_create_admin()

            self.assertEqual(h._status, 403)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "setup_closed")

    def test_create_admin_does_not_write_user_when_password_store_fails(self):
        """create-admin must not leave a passwordless admin row on vault failure."""
        self._assert_setup_password_store_contract()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            body = '{"username":"newadmin","password":"validpass123"}'
            h = self._setup_handler(body)

            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve._load_users", return_value=[]), \
                 patch("freq.modules.serve._setup_store_admin_password", return_value="Permission denied: vault"):
                h._serve_setup_create_admin()

            self.assertEqual(h._status, 500)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "operator_password_store_failed")
            self.assertIn("Failed to store password", data["error"]["message"])
            self.assertFalse(os.path.exists(os.path.join(cfg.conf_dir, "users.conf")))

    def test_save_failure_returns_filesystem_reason(self):
        """create-admin must not collapse filesystem failures to a vague 500."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            body = '{"username":"newadmin","password":"validpass123"}'
            h = self._setup_handler(body)

            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True), \
                 patch("freq.modules.serve._load_users", return_value=[]), \
                 patch("freq.modules.serve._setup_store_admin_password", return_value=""), \
                 patch("freq.modules.serve._save_users_error", return_value="Permission denied: users.conf"):
                h._serve_setup_create_admin()

            self.assertEqual(h._status, 500)
            data = _get_json(h)
            self.assertEqual(data["error"]["code"], "operator_write_failed")
            self.assertEqual(data["error"]["message"], "Failed to save user.")
            self.assertNotIn("Permission denied", data["error"]["message"])


# ══════════════════════════════════════════════════════════════════════════
# Setup gating — all setup endpoints reject after completion
# ══════════════════════════════════════════════════════════════════════════

class TestSetupGatingPostCompletion(unittest.TestCase):
    """After setup is complete, all setup endpoints must return 403."""

    SETUP_ENDPOINTS = [
        ("_serve_setup_configure", "POST",
         '{"cluster_name":"c","timezone":"UTC","pve_nodes":["1.2.3.4"]}'),
        ("_serve_setup_generate_key", "POST", None),
    ]

    def test_all_setup_endpoints_return_403_after_completion(self):
        """Every setup endpoint must reject with 403 when _is_first_run()=False."""
        for handler_attr, method, body in self.SETUP_ENDPOINTS:
            h = _make_handler(f"/api/setup/test-{handler_attr}",
                              method=method, body=body)
            with patch("freq.modules.serve._is_first_run", return_value=False):
                fn = getattr(h, handler_attr, None)
                if fn is None:
                    continue
                fn()
            self.assertEqual(
                h._status, 403,
                f"{handler_attr} must return 403 after setup completion, got {h._status}"
            )


# ══════════════════════════════════════════════════════════════════════════
# /api/info — version freshness
# ══════════════════════════════════════════════════════════════════════════

class TestInfoApiVersionTruth(unittest.TestCase):
    """/api/info version must match freq.__version__ exactly."""

    def test_version_matches_module(self):
        """info.version must equal freq.__version__."""
        import freq
        from freq.api.fleet import handle_info

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            h = _make_handler("/api/info")
            with patch("freq.api.fleet.load_config", return_value=cfg), \
                 patch("freq.api.fleet._get_discovered_nodes", return_value=["pve01"]), \
                 patch("freq.core.personality.load_pack", return_value=None):
                handle_info(h)
            data = _get_json(h)
            self.assertEqual(data["version"], freq.__version__)

    def test_cluster_name_matches_config(self):
        """info.cluster must match cfg.cluster_name."""
        from freq.api.fleet import handle_info

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            cfg.cluster_name = "my-test-cluster"
            h = _make_handler("/api/info")
            with patch("freq.api.fleet.load_config", return_value=cfg), \
                 patch("freq.api.fleet._get_discovered_nodes", return_value=[]), \
                 patch("freq.core.personality.load_pack", return_value=None):
                handle_info(h)
            data = _get_json(h)
            self.assertEqual(data["cluster"], "my-test-cluster")

    def test_host_count_matches_config(self):
        """info.hosts must reflect cfg.hosts length."""
        from freq.api.fleet import handle_info

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            cfg.hosts = [SimpleNamespace(label="h1"), SimpleNamespace(label="h2")]
            h = _make_handler("/api/info")
            with patch("freq.api.fleet.load_config", return_value=cfg), \
                 patch("freq.api.fleet._get_discovered_nodes", return_value=["n1"]), \
                 patch("freq.core.personality.load_pack", return_value=None):
                handle_info(h)
            data = _get_json(h)
            self.assertEqual(data["hosts"], 2)
            self.assertEqual(data["pve_nodes"], 1)


if __name__ == "__main__":
    unittest.main()
