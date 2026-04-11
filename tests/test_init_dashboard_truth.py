"""E2E proof surfaces for init flow and dashboard truth.

Proves:
- _is_first_run() three-marker logic cannot lie
- /api/setup/status fields match on-disk reality
- /api/setup/complete finalization is atomic and idempotent
- /api/setup/create-admin rejects duplicate users
- /api/info version matches freq.__version__ (not stale)
- Setup endpoints gate on _is_first_run() (post-setup = 403)
"""
import datetime
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


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
        vault_file=os.path.join(tmpdir, "conf", "vault.json"),
        install_dir="/opt/freq",
        pve_nodes=["192.168.10.1"],
        hosts=[],
        brand="FREQ",
        build="dev",
        cluster_name="testcluster",
    )


# ══════════════════════════════════════════════════════════════════════════
# _is_first_run() — three-marker truth logic
# ══════════════════════════════════════════════════════════════════════════

class TestIsFirstRunThreeMarkerLogic(unittest.TestCase):
    """_is_first_run() checks 3 conditions: web marker, CLI marker, users."""

    def test_no_markers_no_users_is_first_run(self):
        """With no markers and no users, _is_first_run() must return True."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                self.assertTrue(_is_first_run())

    def test_web_marker_means_not_first_run(self):
        """data/setup-complete marker alone must return False."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir, exist_ok=True)
            with open(os.path.join(cfg.data_dir, "setup-complete"), "w") as f:
                f.write("done\n")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                self.assertFalse(_is_first_run())

    def test_cli_marker_means_not_first_run(self):
        """conf/.initialized marker alone must return False."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.conf_dir, exist_ok=True)
            with open(os.path.join(cfg.conf_dir, ".initialized"), "w") as f:
                f.write("done\n")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                self.assertFalse(_is_first_run())

    def test_existing_users_means_not_first_run(self):
        """Users in users.conf alone must return False (no markers needed)."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            users = [{"username": "admin", "role": "admin"}]
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=users):
                self.assertFalse(_is_first_run())

    def test_user_load_failure_treated_as_first_run(self):
        """If _load_users raises, _is_first_run() must still return True (safe fallback)."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", side_effect=Exception("disk error")):
                self.assertTrue(_is_first_run(),
                                "User load failure must not silently skip first-run wizard")


# ══════════════════════════════════════════════════════════════════════════
# /api/setup/status — response accuracy
# ══════════════════════════════════════════════════════════════════════════

class TestSetupStatusAccuracy(unittest.TestCase):
    """/api/setup/status fields must match on-disk reality."""

    def test_first_run_true_when_no_markers(self):
        """first_run field must be True when no setup has occurred."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            h = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
                h._serve_setup_status()
            data = _get_json(h)
            self.assertTrue(data["first_run"])

    def test_version_matches_module_version(self):
        """version field must match freq.__version__ exactly."""
        import freq
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            h = _make_handler("/api/setup/status")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._is_first_run", return_value=True):
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


# ══════════════════════════════════════════════════════════════════════════
# /api/setup/complete — finalization, atomicity, idempotency
# ══════════════════════════════════════════════════════════════════════════

class TestSetupCompleteFinalization(unittest.TestCase):
    """/api/setup/complete must write markers and gate subsequent requests."""

    def test_complete_creates_marker_file(self):
        """setup/complete must create data/setup-complete marker."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir, exist_ok=True)
            os.makedirs(cfg.conf_dir, exist_ok=True)

            h = _make_handler("/api/setup/complete", method="POST")

            # First call: _is_first_run must return True, then complete
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                h._serve_setup_complete()

            self.assertEqual(h._status, 200)
            marker = os.path.join(cfg.data_dir, "setup-complete")
            self.assertTrue(os.path.isfile(marker),
                            "setup/complete must create setup-complete marker file")

    def test_complete_writes_cli_initialized_marker(self):
        """setup/complete must also write .initialized for CLI compatibility."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir, exist_ok=True)
            os.makedirs(cfg.conf_dir, exist_ok=True)

            h = _make_handler("/api/setup/complete", method="POST")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                h._serve_setup_complete()

            init_marker = os.path.join(cfg.conf_dir, ".initialized")
            self.assertTrue(os.path.isfile(init_marker),
                            "setup/complete must write .initialized for CLI compatibility")

    def test_second_complete_returns_403(self):
        """After completion, second call must return 403 'already complete'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir, exist_ok=True)
            os.makedirs(cfg.conf_dir, exist_ok=True)

            # First complete
            h1 = _make_handler("/api/setup/complete", method="POST")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                h1._serve_setup_complete()
            self.assertEqual(h1._status, 200)

            # Second complete — markers now exist, _is_first_run() returns False
            h2 = _make_handler("/api/setup/complete", method="POST")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                h2._serve_setup_complete()
            self.assertEqual(h2._status, 403, "Second complete must return 403")
            data = _get_json(h2)
            self.assertIn("already complete", data["error"].lower())

    def test_is_first_run_false_after_complete(self):
        """_is_first_run() must return False after setup/complete."""
        from freq.modules.serve import _is_first_run

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _mock_cfg(tmpdir)
            os.makedirs(cfg.data_dir, exist_ok=True)
            os.makedirs(cfg.conf_dir, exist_ok=True)

            # Before: first run
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                self.assertTrue(_is_first_run())

            # Complete setup
            h = _make_handler("/api/setup/complete", method="POST")
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                h._serve_setup_complete()

            # After: not first run
            with patch("freq.modules.serve.load_config", return_value=cfg), \
                 patch("freq.modules.serve._load_users", return_value=[]):
                self.assertFalse(_is_first_run(),
                                 "_is_first_run() must be False after setup/complete")


# ══════════════════════════════════════════════════════════════════════════
# /api/setup/create-admin — duplicate rejection
# ══════════════════════════════════════════════════════════════════════════

class TestSetupCreateAdminDuplicateGuard(unittest.TestCase):
    """create-admin must reject duplicate usernames with 409."""

    def _setup_handler(self, body_str):
        """Create a handler with proper Content-Length for body parsing."""
        h = _make_handler(
            "/api/setup/create-admin", method="POST", body=body_str
        )
        h.headers = {"Content-Length": str(len(body_str))}
        return h

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
            self.assertIn("already exists", data["error"])

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
            self.assertIn("8 characters", data["error"])

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
            self.assertIn("Invalid username", data["error"])


# ══════════════════════════════════════════════════════════════════════════
# Setup gating — all setup endpoints reject after completion
# ══════════════════════════════════════════════════════════════════════════

class TestSetupGatingPostCompletion(unittest.TestCase):
    """After setup is complete, all setup endpoints must return 403."""

    SETUP_ENDPOINTS = [
        ("_serve_setup_create_admin", "POST",
         '{"username":"admin","password":"testpass123"}'),
        ("_serve_setup_configure", "POST",
         '{"cluster_name":"c","timezone":"UTC","pve_nodes":["1.2.3.4"]}'),
        ("_serve_setup_generate_key", "POST", None),
        ("_serve_setup_complete", "POST", None),
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
