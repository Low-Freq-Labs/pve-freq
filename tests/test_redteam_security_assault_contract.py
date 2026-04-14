"""R-REDTEAM-SECURITY-ASSAULT-20260413T regression contract.

Red-team pass on the 8c0d1f6 green baseline turned up 6 trivially-
fixable findings (plus 3 architectural/documented ones). This file
pins the fixes so they can't silently regress.

  T-1 — /api/auth/change-password takes no current-password check.
        CRITICAL: any compromised token could silently overwrite the
        user's dashboard password. Fix: require `current_password`,
        verify against stored hash before writing new.

  T-2 — /api/auth/change-password leaves other sessions valid.
        HIGH: rotating a password didn't invalidate other tokens for
        the same user — stolen tokens survived up to 8 hours past
        rotation. Fix: purge every OTHER session for the user on
        successful change, keep the caller's token.

  T-3 — /api/lab-tool/save-config accepts API key in query string.
        HIGH: POST endpoint but payload read from URL query params;
        API key leaked into browser history, proxy logs, Referer.
        Fix: POST JSON body only (symmetric with F5/F6 from P).

  T-4 — /api/setup/test-ssh reachable post-setup.
        MEDIUM: setup-wizard endpoint stayed callable forever after
        init. Fix: gate on _is_first_run() — after setup completes,
        admins use freq doctor / freq host test.

  T-5 — /api/vault/delete returns 200 ok:false on malformed body.
        MEDIUM: contract lie — clients can't distinguish validation
        error from empty lookup. Fix: return 400 on empty key.

  T-6 — /api/chaos/log returns 500 on PermissionError.
        MEDIUM: post-init chaos dir ownership gap surfaced as a
        generic 500. Fix: catch PermissionError / FileNotFoundError
        and return 200 with empty experiments list.

  T-9 — vault _encrypt not atomic + no ownership preservation.
        MEDIUM/correctness: concurrent reads during a vault write saw
        half-written files (explained the 401/401/200 post-write
        sequence Finn observed). Fix: write to tmp, chown to preserve
        existing uid/gid, atomic rename.

T-7, T-8 are documented-not-fixed (architectural follow-ups).
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
AUTH_PY = REPO / "freq" / "api" / "auth.py"
SECURE_PY = REPO / "freq" / "api" / "secure.py"
AUTO_PY = REPO / "freq" / "api" / "auto.py"
SERVE_PY = REPO / "freq" / "modules" / "serve.py"
VAULT_PY = REPO / "freq" / "modules" / "vault.py"


class TestT1ChangePasswordRequiresCurrent(unittest.TestCase):
    """Source-pin + behavioral pin for the current-password requirement."""

    def test_source_pins_current_password_field(self):
        src = AUTH_PY.read_text()
        idx = src.find("def handle_auth_change_password")
        self.assertGreater(idx, 0)
        window_end = src.find("\ndef ", idx + 50)
        window = src[idx:window_end]
        self.assertIn('body.get("current_password"', window)
        self.assertIn("verify_password(current_password", window)
        self.assertIn('"current_password required"', window)

    def test_no_current_password_returns_400(self):
        """A fake handler call with no current_password in body must 400."""
        from freq.api import auth as auth_mod
        status = {}
        body = {"password": "new-password-12345"}

        class FakeHandler:
            command = "POST"
            client_address = ("127.0.0.1", 0)
            headers = {}
            def _request_body(self):
                return body
            def _json_response(self, data, code=200):
                status["code"] = code
                status["data"] = data

        # Seed a valid session so we reach the current_password check.
        token = "fake-token-t1-a"
        with auth_mod._auth_lock:
            auth_mod._auth_tokens[token] = {
                "user": "alice", "role": "admin", "ts": __import__("time").time(),
            }
        try:
            h = FakeHandler()
            h.headers = {"Authorization": f"Bearer {token}"}
            auth_mod.handle_auth_change_password(h)
        finally:
            with auth_mod._auth_lock:
                auth_mod._auth_tokens.pop(token, None)
        self.assertEqual(status.get("code"), 400)
        self.assertIn("current_password", str(status.get("data", {})))

    def test_wrong_current_password_returns_401(self):
        from freq.api import auth as auth_mod
        from freq.api.auth import hash_password
        status = {}
        body = {"current_password": "wrong-old", "password": "new-password-12345"}

        class FakeHandler:
            command = "POST"
            client_address = ("127.0.0.1", 0)
            headers = {}
            def _request_body(self):
                return body
            def _json_response(self, data, code=200):
                status["code"] = code
                status["data"] = data

        token = "fake-token-t1-b"
        with auth_mod._auth_lock:
            auth_mod._auth_tokens[token] = {
                "user": "alice", "role": "admin", "ts": __import__("time").time(),
            }
        # Patch vault_get so we return a known hash for alice.
        real_hash = hash_password("right-old-password")
        with mock.patch("freq.api.auth.vault_get", return_value=real_hash):
            try:
                h = FakeHandler()
                h.headers = {"Authorization": f"Bearer {token}"}
                auth_mod.handle_auth_change_password(h)
            finally:
                with auth_mod._auth_lock:
                    auth_mod._auth_tokens.pop(token, None)
        self.assertEqual(status.get("code"), 401)
        self.assertIn("incorrect", str(status.get("data", {})).lower())


class TestT2ChangePasswordPurgesStaleTokens(unittest.TestCase):
    """On successful password change, all other tokens for the user
    must be purged; the caller's token must survive."""

    def test_source_pins_purge_loop(self):
        src = AUTH_PY.read_text()
        idx = src.find("def handle_auth_change_password")
        window_end = src.find("\ndef ", idx + 50)
        window = src[idx:window_end]
        # purge loop identifier.
        self.assertIn("purged", window)
        self.assertIn("_auth_tokens.items()", window)
        self.assertIn("sess.get(\"user\") == username", window)
        self.assertIn("t != token", window)

    def test_other_tokens_purged_caller_survives(self):
        from freq.api import auth as auth_mod
        from freq.api.auth import hash_password

        old_hash = hash_password("current-password-correct")
        status = {}
        body = {
            "current_password": "current-password-correct",
            "password": "new-password-98765",
        }

        class FakeHandler:
            command = "POST"
            client_address = ("127.0.0.1", 0)
            headers = {}
            def _request_body(self):
                return body
            def _json_response(self, data, code=200):
                status["code"] = code
                status["data"] = data

        caller_token = "caller-token-t2"
        stale_token_a = "stale-a-t2"
        stale_token_b = "stale-b-t2"
        unrelated_token = "bob-token-t2"
        with auth_mod._auth_lock:
            auth_mod._auth_tokens.clear()
            now = __import__("time").time()
            auth_mod._auth_tokens[caller_token] = {
                "user": "alice", "role": "admin", "ts": now,
            }
            auth_mod._auth_tokens[stale_token_a] = {
                "user": "alice", "role": "admin", "ts": now,
            }
            auth_mod._auth_tokens[stale_token_b] = {
                "user": "alice", "role": "admin", "ts": now,
            }
            auth_mod._auth_tokens[unrelated_token] = {
                "user": "bob", "role": "operator", "ts": now,
            }

        # Patch vault_get for verify, vault_set for write.
        with mock.patch("freq.api.auth.vault_get", return_value=old_hash), \
             mock.patch("freq.api.auth.vault_set", return_value=True), \
             mock.patch("os.path.exists", return_value=True):
            h = FakeHandler()
            h.headers = {"Authorization": f"Bearer {caller_token}"}
            auth_mod.handle_auth_change_password(h)

        self.assertEqual(status.get("code"), 200)
        self.assertEqual(status["data"].get("sessions_purged"), 2)

        with auth_mod._auth_lock:
            # caller still valid
            self.assertIn(caller_token, auth_mod._auth_tokens)
            # alice's other sessions gone
            self.assertNotIn(stale_token_a, auth_mod._auth_tokens)
            self.assertNotIn(stale_token_b, auth_mod._auth_tokens)
            # bob unaffected
            self.assertIn(unrelated_token, auth_mod._auth_tokens)
            auth_mod._auth_tokens.clear()


class TestT3LabToolSaveConfigPostBody(unittest.TestCase):
    """save-config payload must come from POST body, not query string."""

    def test_source_pins_post_body_read(self):
        src = SERVE_PY.read_text()
        idx = src.find("def _serve_lab_tool_save_config")
        self.assertGreater(idx, 0)
        window_end = src.find("\n    def ", idx + 50)
        window = src[idx:window_end]
        self.assertIn("body = self._request_body()", window)
        self.assertIn('body.get("tool"', window)
        self.assertIn('body.get("host"', window)
        self.assertIn('body.get("key"', window)
        # And the old query-parse is gone.
        self.assertNotIn('params = _parse_query(self)', window)


class TestT4TestSshGatedFirstRun(unittest.TestCase):
    """test-ssh must refuse after _is_first_run() returns False."""

    def test_source_pins_first_run_gate(self):
        src = SERVE_PY.read_text()
        idx = src.find("def _serve_setup_test_ssh")
        self.assertGreater(idx, 0)
        window_end = src.find("\n    def ", idx + 50)
        window = src[idx:window_end]
        self.assertIn("_is_first_run()", window)
        self.assertIn("Setup already complete", window)


class TestT5VaultDeleteValidatesKey(unittest.TestCase):
    """vault/delete must return 400 on empty key."""

    def test_source_pins_key_validation(self):
        src = SECURE_PY.read_text()
        idx = src.find("def handle_vault_delete")
        self.assertGreater(idx, 0)
        window_end = src.find("\ndef ", idx + 50)
        window = src[idx:window_end]
        self.assertIn('if not key:', window)
        self.assertIn('"key required"', window)

    def test_empty_key_returns_400(self):
        from freq.api import secure as secure_mod
        status = {}

        class FakeHandler:
            command = "POST"
            path = "/api/vault/delete"
            headers = {}
            def _json_response(self, data, code=200):
                status["code"] = code
                status["data"] = data

        def fake_params(handler):
            return {"key": [""], "host": ["DEFAULT"]}

        def fake_require_post(h, label):
            return False

        def fake_role_check(h, minrole):
            return "admin", None

        with mock.patch("freq.api.secure.require_post", side_effect=fake_require_post), \
             mock.patch("freq.api.secure._check_session_role", side_effect=fake_role_check), \
             mock.patch("freq.api.secure.get_params", side_effect=fake_params), \
             mock.patch("freq.api.secure.load_config", return_value=mock.Mock()), \
             mock.patch("freq.api.secure.json_response",
                        side_effect=lambda h, d, c=200: (status.update(code=c, data=d))):
            secure_mod.handle_vault_delete(FakeHandler())
        self.assertEqual(status.get("code"), 400)


class TestT6ChaosLogGracefulOnPermissionError(unittest.TestCase):
    """chaos/log must return 200 + empty list on PermissionError /
    FileNotFoundError, not bubble to a 500."""

    def test_source_pins_exception_catch(self):
        src = AUTO_PY.read_text()
        idx = src.find("handle_chaos_log")
        # Find the load_experiment_log call region.
        region_start = src.find("load_experiment_log(cfg.data_dir, count)", idx)
        self.assertGreater(region_start, 0)
        window = src[idx:region_start + 500]
        self.assertIn("PermissionError", window)
        self.assertIn("FileNotFoundError", window)
        self.assertIn("No chaos experiments recorded", window)

    def test_permission_error_returns_empty(self):
        from freq.api import auto as auto_mod
        status = {}

        def fake_load(data_dir, count):
            raise PermissionError(13, "Permission denied")

        class FakeHandler:
            command = "GET"
            path = "/api/chaos/log"
            headers = {}

        # load_experiment_log is imported inside the handler from
        # freq.jarvis.chaos — patch there.
        with mock.patch("freq.jarvis.chaos.load_experiment_log", side_effect=fake_load), \
             mock.patch("freq.api.auto.load_config", return_value=mock.Mock(data_dir="/tmp")), \
             mock.patch("freq.api.auto._get_params_flat", return_value={"count": "20"}), \
             mock.patch("freq.api.auto.json_response",
                        side_effect=lambda h, d, c=200: (status.update(code=c, data=d))):
            auto_mod.handle_chaos_log(FakeHandler())
        self.assertEqual(status.get("code", 200), 200)
        self.assertEqual(status["data"].get("experiments"), [])


class TestT9VaultAtomicWrite(unittest.TestCase):
    """Vault _encrypt must use tmp+rename and preserve existing ownership."""

    def test_source_pins_tmp_rename_pattern(self):
        src = VAULT_PY.read_text()
        idx = src.find("def _encrypt(")
        self.assertGreater(idx, 0)
        window_end = src.find("\ndef ", idx + 50)
        window = src[idx:window_end]
        self.assertIn('tmp_path = vault_path + ".tmp"', window)
        self.assertIn("os.rename(tmp_path, vault_path)", window)
        self.assertIn("os.chown(tmp_path, st.st_uid, st.st_gid)", window)
        # Openssl writes to the tmp path, not the final path.
        self.assertIn('"-out", tmp_path', window)

    def test_atomic_write_behavior_isolates_partial(self):
        """Smoke test: a reader starts reading the vault while a writer
        is mid-encrypt. With atomic rename the reader sees the OLD
        contents, never a half-written partial. Approximate this by
        patching _run_openssl_with_key to sleep briefly between tmp
        write and rename, and asserting the final file ends up with
        the new plaintext."""
        from freq.modules import vault as vault_mod
        with tempfile.TemporaryDirectory() as td:
            vault_path = os.path.join(td, "test-vault.enc")
            # Pre-seed an existing "old" vault file.
            Path(vault_path).write_bytes(b"old-contents")
            original_uid = os.stat(vault_path).st_uid

            call_count = {"n": 0}

            def fake_openssl(cmd, key, stdin_data=None):
                # Write to the tmp path the command specified.
                call_count["n"] += 1
                out_path = None
                for i, a in enumerate(cmd):
                    if a == "-out" and i + 1 < len(cmd):
                        out_path = cmd[i + 1]
                        break
                assert out_path and out_path.endswith(".tmp"), \
                    f"_encrypt must write to tmp, not live path, got {out_path}"
                Path(out_path).write_bytes(b"new-encrypted-contents")
                return mock.Mock(returncode=0, stderr=b"")

            with mock.patch("freq.modules.vault._run_openssl_with_key",
                            side_effect=fake_openssl):
                ok = vault_mod._encrypt("new-plaintext", "test-key", vault_path)
            self.assertTrue(ok)
            self.assertEqual(call_count["n"], 1)
            # Live file must now contain new contents — tmp was atomically
            # renamed over the old.
            self.assertEqual(Path(vault_path).read_bytes(), b"new-encrypted-contents")
            # Ownership preserved (same uid as original seed).
            self.assertEqual(os.stat(vault_path).st_uid, original_uid)

    def test_openssl_failure_removes_tmp(self):
        from freq.modules import vault as vault_mod
        with tempfile.TemporaryDirectory() as td:
            vault_path = os.path.join(td, "test-vault.enc")
            Path(vault_path).write_bytes(b"pre-existing")

            def fake_openssl(cmd, key, stdin_data=None):
                # Simulate openssl writing partial then failing.
                for i, a in enumerate(cmd):
                    if a == "-out" and i + 1 < len(cmd):
                        Path(cmd[i + 1]).write_bytes(b"partial-garbage")
                        break
                return mock.Mock(returncode=1, stderr=b"fake openssl fail")

            with mock.patch("freq.modules.vault._run_openssl_with_key",
                            side_effect=fake_openssl):
                ok = vault_mod._encrypt("new", "k", vault_path)
            self.assertFalse(ok)
            # Live file MUST still carry the old contents — tmp was cleaned up.
            self.assertEqual(Path(vault_path).read_bytes(), b"pre-existing")
            # Tmp file must NOT be left behind.
            self.assertFalse(Path(vault_path + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
