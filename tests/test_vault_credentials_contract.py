"""Product Vault contract.

The visible Vault is a password manager, not user management and not the
old host/key admin panel. It exposes scoped credentials:

- global: visible to operators/admins, writable by admins
- user: private to the signed-in operator/admin
"""

import ast
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(__file__).parent.parent
APP_HTML = REPO / "freq" / "data" / "web" / "app.html"
APP_JS = REPO / "freq" / "data" / "web" / "js" / "app.js"

VAULT_API_IMPORTS = {
    "auth.py": {"vault_get", "vault_init", "vault_list", "vault_set", "vault_update"},
    "hw.py": {"vault_get"},
    "ipmi.py": {"vault_get"},
    "opnsense.py": {"vault_get", "vault_update"},
    "redfish.py": {"vault_get"},
    "secure.py": {"vault_delete", "vault_get", "vault_init", "vault_list", "vault_set"},
    "synology.py": {"vault_get"},
    "user.py": {"vault_delete", "vault_init", "vault_set"},
}


def read(path: Path) -> str:
    return path.read_text()


class Handler:
    def __init__(self, method="GET", body=None):
        self.command = method
        self.path = "/api/vault/credentials"
        raw = json.dumps(body or {}).encode()
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.headers = {"Content-Length": str(len(raw))}
        self.sent = {}

    def send_response(self, status):
        self.sent["status"] = status

    def send_header(self, key, value):
        pass

    def end_headers(self):
        pass


def capture_json(handler, data, status=200):
    handler.sent["status"] = status
    handler.sent["data"] = data


def _assert_vault_seam_owner_contract():
    """Freeze the eight-site vault seam before its downward relocation."""
    from freq.modules import vault

    observed = {}
    for path in sorted((REPO / "freq" / "api").glob("*.py")):
        names = set()
        for node in ast.walk(ast.parse(read(path))):
            if isinstance(node, ast.ImportFrom) and node.module == "freq.core.vault":
                names.update(alias.name for alias in node.names)
        if names:
            observed[path.name] = names
    assert observed == VAULT_API_IMPORTS

    public_signatures = {
        "vault_init": ("cfg",),
        "vault_update": ("cfg", "host", "updates"),
        "vault_set": ("cfg", "host", "cred_key", "value"),
        "vault_get": ("cfg", "host", "cred_key"),
        "vault_delete": ("cfg", "host", "cred_key"),
        "vault_list": ("cfg",),
    }
    vault_tree = ast.parse(read(REPO / "freq" / "core" / "vault.py"))
    definitions = {
        node.name: tuple(arg.arg for arg in node.args.args)
        for node in vault_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {name: definitions[name] for name in public_signatures} == public_signatures

    cfg = SimpleNamespace(vault_file="/tmp/contract-vault.enc", vault_dir="/tmp")
    plaintext = "DEFAULT|token|fallback-value\nnode-a|token|exact-value\nnode-a|keep|old\n"
    with patch.object(vault, "_vault_key", return_value="derived-key"), patch.object(
        vault, "_decrypt", return_value=plaintext
    ), patch.object(vault, "_encrypt", return_value=True) as encrypt:
        assert vault.vault_get(cfg, "node-a", "token") == "exact-value"
        assert vault.vault_get(cfg, "node-b", "token") == "fallback-value"
        assert vault.vault_get(cfg, "node-b", "missing") == ""
        assert vault.vault_set(cfg, "node-a", "new", "new-value") is True
        serialized = encrypt.call_args.args[0]
        assert "node-a|new|new-value" in serialized
        assert "node-a|keep|old" in serialized
        encrypt.reset_mock()
        assert vault.vault_delete(cfg, "node-a", "missing") is False
        encrypt.assert_not_called()
        assert vault.vault_delete(cfg, "node-a", "token") is True
        assert "node-a|token|exact-value" not in encrypt.call_args.args[0]
        assert vault.vault_list(cfg) == [
            ("DEFAULT", "token", "fallback-value"),
            ("node-a", "token", "exact-value"),
            ("node-a", "keep", "old"),
        ]

    logger_calls = [
        node
        for node in ast.walk(vault_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
    ]
    assert logger_calls
    for call in logger_calls:
        referenced = {node.id for node in ast.walk(call) if isinstance(node, ast.Name)}
        assert not ({"value", "plaintext"} & referenced)


def test_vault_is_top_level_between_security_and_system():
    html = read(APP_HTML)

    assert 'data-view="security">SECURITY' in html
    assert 'data-view="vault">VAULT' in html
    assert html.index('data-view="security">SECURITY') < html.index('data-view="vault">VAULT')
    assert html.index('data-view="vault">VAULT') < html.index('data-view="tools">SYSTEM')


def test_security_no_longer_owns_vault_or_api_key_panel():
    html = read(APP_HTML)
    js = read(APP_JS)

    assert "sec-vault" not in html
    assert "sec-apikeys" not in html
    assert "vault-auth-user" not in html
    assert "vault-auth-pass" not in html
    assert "users tab" not in js.lower()
    assert "unlockVault" not in js
    assert "vaultSet" not in js
    assert "API.VAULT_SET" not in js
    assert "API.VAULT_DELETE" not in js


def test_vault_uses_scoped_credential_api_not_legacy_key_value():
    js = read(APP_JS)

    assert "VAULT_CREDENTIALS:'/api/vault/credentials'" in js
    assert "VAULT_CREDENTIAL_SET:'/api/vault/credentials/set'" in js
    assert "VAULT_CREDENTIAL_REVEAL:'/api/vault/credentials/reveal'" in js
    assert "VAULT_CREDENTIAL_DELETE:'/api/vault/credentials/delete'" in js
    assert "VAULT:'/api/vault'" not in js


def test_scoped_list_hides_other_users_and_never_returns_secret():
    from freq.api import secure

    cfg = SimpleNamespace(vault_file="/tmp/fake-vault.enc")
    entries = [
        (
            secure._VAULT_GLOBAL_HOST,
            "meta:g1",
            json.dumps({"id": "g1", "scope": "global", "owner": "", "label": "Global", "username": "root"}),
        ),
        (secure._VAULT_GLOBAL_HOST, "secret:g1", "global-secret"),
        (
            secure._credential_host("user", "alice"),
            "meta:u1",
            json.dumps({"id": "u1", "scope": "user", "owner": "alice", "label": "Alice", "username": "alice"}),
        ),
        (secure._credential_host("user", "alice"), "secret:u1", "alice-secret"),
        (
            secure._credential_host("user", "bob"),
            "meta:u2",
            json.dumps({"id": "u2", "scope": "user", "owner": "bob", "label": "Bob", "username": "bob"}),
        ),
        (secure._credential_host("user", "bob"), "secret:u2", "bob-secret"),
    ]

    def fake_get(_cfg, host, key):
        for h, k, v in entries:
            if h == host and k == key:
                return v
        return ""

    h = Handler()
    with patch("freq.api.secure._check_session_role", return_value=("operator", None)), \
        patch("freq.api.secure._vault_request_user", return_value="alice"), \
        patch("freq.api.secure.load_config", return_value=cfg), \
        patch("freq.api.secure.os.path.exists", return_value=True), \
        patch("freq.api.secure.vault_list", return_value=entries), \
        patch("freq.api.secure.vault_get", side_effect=fake_get), \
        patch("freq.api.secure.json_response", side_effect=capture_json):
        secure.handle_vault_credentials(h)

    data = h.sent["data"]
    labels = [c["label"] for c in data["credentials"]]
    assert labels == ["Global", "Alice"]
    assert "Bob" not in labels
    rendered = json.dumps(data)
    assert "global-secret" not in rendered
    assert "alice-secret" not in rendered
    assert "bob-secret" not in rendered
    assert all("masked" in c for c in data["credentials"])


def test_global_write_requires_admin_but_user_write_allows_operator():
    from freq.api import secure

    cfg = SimpleNamespace(vault_file="/tmp/fake-vault.enc")

    h = Handler(method="POST", body={"scope": "global", "label": "Global", "secret": "pw"})
    with patch("freq.api.secure._check_session_role", return_value=("operator", None)), \
        patch("freq.api.secure._vault_request_user", return_value="alice"), \
        patch("freq.api.secure.json_response", side_effect=capture_json):
        secure.handle_vault_credential_set(h)
    assert h.sent["status"] == 403

    h2 = Handler(method="POST", body={"scope": "user", "label": "Mine", "secret": "pw"})
    with patch("freq.api.secure._check_session_role", return_value=("operator", None)), \
        patch("freq.api.secure._vault_request_user", return_value="alice"), \
        patch("freq.api.secure.load_config", return_value=cfg), \
        patch("freq.api.secure.os.path.exists", return_value=True), \
        patch("freq.api.secure.vault_set", return_value=True), \
        patch("freq.api.secure.json_response", side_effect=capture_json):
        secure.handle_vault_credential_set(h2)
    assert h2.sent["status"] == 200
    assert h2.sent["data"]["credential"]["scope"] == "user"
    assert "secret" not in h2.sent["data"]["credential"]


def test_register_exposes_scoped_routes_and_legacy_routes_are_gone_as_product():
    from freq.api import secure

    routes = {}
    secure.register(routes)

    for route in (
        "/api/vault/credentials",
        "/api/vault/credentials/set",
        "/api/vault/credentials/reveal",
        "/api/vault/credentials/delete",
    ):
        assert route in routes

    for route in ("/api/vault", "/api/vault/set", "/api/vault/delete"):
        assert route not in routes
    assert not hasattr(secure, "handle_vault")
    assert not hasattr(secure, "handle_vault_set")
    assert not hasattr(secure, "handle_vault_delete")
    _assert_vault_seam_owner_contract()
