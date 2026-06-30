"""Product Vault contract.

The visible Vault is a password manager, not user management and not the
old host/key admin panel. It exposes scoped credentials:

- global: visible to operators/admins, writable by admins
- user: private to the signed-in operator/admin
"""

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO = Path(__file__).parent.parent
APP_HTML = REPO / "freq" / "data" / "web" / "app.html"
APP_JS = REPO / "freq" / "data" / "web" / "js" / "app.js"


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


def test_vault_is_top_level_between_security_and_system():
    html = read(APP_HTML)

    assert 'data-view="certs">SECURITY' in html
    assert 'data-view="vault">VAULT' in html
    assert html.index('data-view="certs">SECURITY') < html.index('data-view="vault">VAULT')
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
