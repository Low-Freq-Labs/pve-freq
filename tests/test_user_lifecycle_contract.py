"""User lifecycle contract for browser-testable Vault isolation.

The Web UI must support disposable user creation, password reset, login,
and cleanup without TOML edits or password material in URLs. This gives
Vault user-scope tests a first-class product path instead of an operator
side channel.
"""

import ast
import io
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
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

        from freq.api.user import handle_user_create, handle_user_demote, handle_user_promote

        before = b"admin admin\nalice operator\n"
        failure_cases = (
            (handle_user_create, "/api/users/create?username=bob&role=operator"),
            (handle_user_promote, "/api/users/promote?username=alice"),
            (handle_user_demote, "/api/users/demote?username=alice"),
        )
        for handler_fn, path in failure_cases:
            with self.subTest(path=path):
                Path(self.cfg.conf_dir, "users.conf").write_bytes(before)
                toml_user = {"username": "alice", "role": "operator", "groups": ""}
                self.cfg._toml_users = [toml_user]
                h, _token = _handler(path=path, body={})
                with self._patches(), patch("freq.api.user._save_users", return_value=False):
                    handler_fn(h)
                self.assertEqual(h._status, 500)
                self.assertEqual(_json(h)["error"], "Failed to save users")
                self.assertEqual(Path(self.cfg.conf_dir, "users.conf").read_bytes(), before)
                self.assertEqual(self.cfg._toml_users, [toml_user])
                self.assertEqual(toml_user["role"], "operator")
        self.cfg._toml_users = []

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

        repo = Path(__file__).resolve().parents[1]
        api_tree = ast.parse((repo / "freq" / "api" / "user.py").read_text())
        legacy_tree = ast.parse((repo / "freq" / "modules" / "users.py").read_text())
        users_tree = ast.parse((repo / "freq" / "services" / "user_registry.py").read_text())
        imports = [
            node
            for node in api_tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module in {"freq.modules.users", "freq.services.user_registry"}
        ]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].module, "freq.services.user_registry")
        storage_symbols = {
            "ROLE_HIERARCHY",
            "_load_users",
            "_role_level",
            "_save_users",
            "_valid_username",
        }
        self.assertEqual({alias.name for alias in imports[0].names}, storage_symbols)

        service_upward = []
        for node in ast.walk(users_tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "freq.api" or node.module.startswith("freq.api."):
                    service_upward.append(node.module)
                if node.module == "freq.modules" or node.module.startswith("freq.modules."):
                    service_upward.append(node.module)
            elif isinstance(node, ast.Import):
                service_upward.extend(
                    alias.name
                    for alias in node.names
                    if alias.name == "freq.api"
                    or alias.name.startswith("freq.api.")
                    or alias.name == "freq.modules"
                    or alias.name.startswith("freq.modules.")
                )
        self.assertEqual(service_upward, [])

        legacy_imports = [
            node
            for node in legacy_tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "freq.services.user_registry"
        ]
        self.assertEqual(
            {alias.name for node in legacy_imports for alias in node.names},
            storage_symbols | {"_save_users_error"},
        )

        functions = {
            node.name: node
            for node in users_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        expected_args = {
            "_load_users": ["cfg"],
            "_save_users_error": ["cfg", "users"],
            "_save_users": ["cfg", "users"],
            "_valid_username": ["username"],
            "_role_level": ["role"],
        }
        self.assertTrue(expected_args.keys() <= functions.keys())
        for name, args in expected_args.items():
            function = functions[name]
            self.assertEqual([arg.arg for arg in function.args.args], args)
            self.assertEqual(function.args.defaults, [])
            upward = []
            for node in ast.walk(function):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module == "freq.api" or node.module.startswith("freq.api."):
                        upward.append(node.module)
                    if node.module == "freq.modules" or node.module.startswith("freq.modules."):
                        upward.append(node.module)
                elif isinstance(node, ast.Import):
                    upward.extend(
                        alias.name
                        for alias in node.names
                        if alias.name == "freq.api"
                        or alias.name.startswith("freq.api.")
                        or alias.name == "freq.modules"
                        or alias.name.startswith("freq.modules.")
                    )
            self.assertEqual(upward, [])

        role_assignments = [
            node
            for node in users_tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "ROLE_HIERARCHY" for target in node.targets)
        ]
        self.assertEqual(len(role_assignments), 1)
        self.assertEqual(
            ast.literal_eval(role_assignments[0].value),
            ["viewer", "operator", "admin", "protected"],
        )

        from freq.modules import users as legacy_users
        from freq.services import user_registry

        for name in storage_symbols | {"_save_users_error"}:
            self.assertIs(getattr(legacy_users, name), getattr(user_registry, name))


if __name__ == "__main__":
    unittest.main()
