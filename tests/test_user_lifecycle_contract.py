"""User lifecycle contract for browser-testable Vault isolation.

The Web UI must support disposable user creation, password reset, login,
and cleanup without TOML edits or password material in URLs. This gives
Vault user-scope tests a first-class product path instead of an operator
side channel.
"""

import io
import json
import os
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _handler(path="/api/users/reset-password", method="POST", body=None, user="admin"):
    from freq.modules.serve import FreqHandler
    from freq.api.auth import _auth_tokens, _auth_lock

    token = f"user-life-{user}-{time.time()}"
    with _auth_lock:
        _auth_tokens[token] = {
            "user": user,
            "role": "admin",
            "ts": time.time(),
            "last_activity_ts": time.time(),
        }

    raw = json.dumps(body or {}).encode()
    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.command = method
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO(raw)
    h.requestline = f"{method} {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h._headers_buffer = []
    h._status = None
    h._resp_headers = []

    def header_get(key, default=""):
        return {
            "Authorization": f"Bearer {token}",
            "Cookie": "",
            "Origin": "",
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }.get(key, default)

    h.headers = SimpleNamespace(get=header_get)
    h.send_response = lambda code, msg=None: setattr(h, "_status", code)
    h.send_header = lambda k, v: h._resp_headers.append((k, v))
    h.end_headers = lambda: None
    return h, token


def _json(h):
    return json.loads(h.wfile.getvalue().decode())


class TestUserLifecycleContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = SimpleNamespace(
            conf_dir=self.tmp.name,
            vault_file=os.path.join(self.tmp.name, "vault.enc"),
            ssh_service_account="freq-ops",
            _toml_users=[],
        )
        with open(os.path.join(self.tmp.name, "users.conf"), "w") as f:
            f.write("admin admin\nalice operator\n")
        self.vault = {}

    def tearDown(self):
        from freq.api.auth import _auth_tokens, _auth_lock
        with _auth_lock:
            for token in [t for t in _auth_tokens if t.startswith("user-life-")]:
                del _auth_tokens[token]
        self.tmp.cleanup()

    def _patches(self):
        return patch.multiple(
            "freq.api.user",
            load_config=lambda: self.cfg,
            vault_init=lambda cfg: True,
            vault_set=lambda cfg, host, key, value: self.vault.__setitem__((host, key), value) or True,
            vault_delete=lambda cfg, host, key: self.vault.pop((host, key), None) is not None,
        )

    def test_reset_password_uses_json_body_and_purges_target_sessions(self):
        from freq.api.auth import _auth_tokens, _auth_lock
        from freq.api.user import handle_user_reset_password

        with _auth_lock:
            _auth_tokens["user-life-alice-old"] = {
                "user": "alice",
                "role": "operator",
                "ts": time.time(),
                "last_activity_ts": time.time(),
            }
        h, _token = _handler(body={"username": "alice", "password": "new-secret-123"})
        with self._patches():
            handle_user_reset_password(h)

        self.assertEqual(h._status, 200)
        data = _json(h)
        self.assertTrue(data["ok"])
        self.assertEqual(data["sessions_purged"], 1)
        self.assertIn(("auth", "password_alice"), self.vault)
        self.assertNotIn("new-secret-123", self.vault[("auth", "password_alice")])
        self.assertNotIn("user-life-alice-old", _auth_tokens)

    def test_reset_password_rejects_self_and_short_password(self):
        from freq.api.user import handle_user_reset_password

        h, _token = _handler(body={"username": "admin", "password": "new-secret-123"}, user="admin")
        with self._patches():
            handle_user_reset_password(h)
        self.assertEqual(h._status, 409)

        h, _token = _handler(body={"username": "alice", "password": "short"}, user="admin")
        with self._patches():
            handle_user_reset_password(h)
        self.assertEqual(h._status, 400)

    def test_delete_user_removes_user_password_and_sessions_but_not_last_admin(self):
        from freq.api.auth import _auth_tokens, _auth_lock
        from freq.api.user import handle_user_delete

        self.vault[("auth", "password_alice")] = "stored-hash"
        with _auth_lock:
            _auth_tokens["user-life-alice-old"] = {
                "user": "alice",
                "role": "operator",
                "ts": time.time(),
                "last_activity_ts": time.time(),
            }
        h, _token = _handler(path="/api/users/delete?username=alice", body={})
        with self._patches():
            handle_user_delete(h)
        self.assertEqual(h._status, 200)
        self.assertNotIn(("auth", "password_alice"), self.vault)
        self.assertNotIn("user-life-alice-old", _auth_tokens)
        with open(os.path.join(self.tmp.name, "users.conf")) as f:
            self.assertNotIn("alice", f.read())

        h, _token = _handler(path="/api/users/delete?username=admin", body={})
        with self._patches():
            handle_user_delete(h)
        self.assertEqual(h._status, 409)

    def test_frontend_contract_has_reset_delete_without_password_query(self):
        app_js = os.path.join(
            os.path.dirname(__file__), "..", "freq", "data", "web", "js", "app.js"
        )
        with open(app_js) as f:
            src = f.read()
        self.assertIn("USERS_RESET_PASSWORD:'/api/users/reset-password'", src)
        self.assertIn("USERS_DELETE:'/api/users/delete'", src)
        reset_fn = src.split("function userResetPassword", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("JSON.stringify({username:u,password:pw})", reset_fn)
        self.assertNotIn("USERS_RESET_PASSWORD+'?", reset_fn)
        self.assertNotIn("password='+", reset_fn)


if __name__ == "__main__":
    unittest.main()
