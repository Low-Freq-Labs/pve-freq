"""Regression contracts for R-SECURITY-TRUST-AUDIT-20260413P fixes.

Each TestCase pins one finding from
/opt/freq-devs/rick/findings/R-SECURITY-TRUST-AUDIT-20260413P.md
so the underlying gap can never silently regress.

Covered:
  - F1   trust-on-first-use account takeover (auth.py login refuses
         empty stored_hash + refuses on vault read failure).
  - F4   vault openssl key passed via inherited pipe FD, not argv.
  - F5   /api/ct/create reads password from JSON body, not query string.
  - F6   /api/federation/register reads HMAC secret from JSON body.
  - F7   check_session_role drops the SSE query-string token fallback.
  - F8   terminal session creator binding — WS refuses cross-user binds.
  - F10  logout cookie clear matches login Secure-flag symmetry.
  - F11  /api/setup/status hides ssh_key_path / version / host_count
         from unauth callers.
  - F13  log redaction covers key= / session= / pass= / pw= / auth=.
  - F15  ct/create password is shlex.quoted before shell interpolation.
"""
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.api import auth as auth_mod  # noqa: E402
from freq.core import log as freq_log  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent


class _FakeHandler:
    """Minimal HTTP-handler stub for auth.py handlers.

    auth.py touches:
      - .headers (dict-like with .get)
      - .client_address (tuple)
      - .command (HTTP verb)
      - ._request_body() (returns parsed dict)
      - ._json_response(payload, status)
      - .send_response / .send_header / .end_headers / .wfile
      - .request (the underlying socket — used to detect TLS)
    """

    def __init__(self, body=None, command="POST", headers=None, is_tls=False):
        self.command = command
        self.client_address = ("127.0.0.1", 0)
        self.headers = headers or {}
        self._body = body or {}
        self._json_calls = []
        self._sent_headers = []
        self.wfile = MagicMock()
        # auth.py uses isinstance(self.request, ssl.SSLSocket) for is_tls.
        if is_tls:
            import ssl as _ssl
            self.request = MagicMock(spec=_ssl.SSLSocket)
        else:
            self.request = MagicMock()

    def _request_body(self):
        return self._body

    def _json_response(self, payload, status=200):
        self._json_calls.append((payload, status))

    def send_response(self, status):
        self._sent_status = status

    def send_header(self, k, v):
        self._sent_headers.append((k, v))

    def end_headers(self):
        pass


def _call_login(stored_hash_value, raise_on_vault=False):
    """Drive auth.handle_auth_login with controlled vault state."""
    handler = _FakeHandler(
        body={"username": "alice", "password": "anything"},
        command="POST",
    )

    def fake_vault_get(cfg, group, key):
        if raise_on_vault:
            raise RuntimeError("boom")
        return stored_hash_value

    fake_users = [{"username": "alice", "role": "admin", "groups": ""}]
    with patch("freq.modules.users._load_users", return_value=fake_users), \
         patch("freq.api.auth.vault_get", side_effect=fake_vault_get), \
         patch("freq.api.auth.vault_set"), \
         patch("freq.api.auth.vault_init"), \
         patch("freq.api.auth.load_config") as load_cfg, \
         patch("freq.api.auth.check_rate_limit", return_value=True), \
         patch("freq.api.auth.record_login_attempt"):
        load_cfg.return_value = MagicMock(
            ssh_service_account="freq-admin",
            vault_file="/tmp/nonexistent-vault",
        )
        auth_mod.handle_auth_login(handler)
    return handler


class TestF1TrustOnFirstUse(unittest.TestCase):
    """F1 — login MUST refuse empty stored_hash and MUST NOT silently
    re-seed the vault from caller-supplied input."""

    def test_login_refuses_when_no_stored_hash(self):
        """User exists in users.conf but has no vault password entry.
        Login must 401, not auto-seed and 200."""
        handler = _call_login(stored_hash_value="")
        # Last (and only) _json_response call must be the 401 refusal.
        self.assertEqual(len(handler._json_calls), 1,
                         "login must respond exactly once")
        payload, status = handler._json_calls[0]
        self.assertEqual(status, 401, f"expected 401, got {status}: {payload}")
        self.assertIn("Invalid credentials", payload.get("error", ""))

    def test_login_refuses_when_vault_read_fails(self):
        """Transient vault read error MUST refuse, not fall through to
        the legacy migration block (the original takeover trigger)."""
        handler = _call_login(stored_hash_value="", raise_on_vault=True)
        self.assertEqual(len(handler._json_calls), 1)
        payload, status = handler._json_calls[0]
        self.assertEqual(status, 401)
        self.assertIn("Invalid credentials", payload.get("error", ""))

    def test_login_refuses_when_vault_returns_none(self):
        """vault_get returning None (not "") must also refuse."""
        handler = _call_login(stored_hash_value=None)
        self.assertEqual(len(handler._json_calls), 1)
        _, status = handler._json_calls[0]
        self.assertEqual(status, 401)

    def test_no_silent_password_seed_branch_in_source(self):
        """Pin the source contract: the legacy migration block must
        only fire when stored_hash is truthy AND lacks a $ separator.
        The pre-fix `if not stored_hash or ('$' not in stored_hash):`
        let an empty hash trigger the seed — that's the regression."""
        src = (REPO_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertNotIn(
            "if not stored_hash or",
            src,
            "auth.py must NOT contain `if not stored_hash or ...:` — "
            "that pattern re-introduces the trust-on-first-use takeover",
        )
        self.assertIn(
            'if "$" not in stored_hash:',
            src,
            "the legacy SHA256 migration branch must be the standalone "
            "`if \"$\" not in stored_hash:` form, fired only after "
            "verify_password already succeeded against a non-empty hash",
        )


class TestF10LogoutCookieSecuritySymmetry(unittest.TestCase):
    """F10 — logout cookie clear must mirror the Secure flag set by login
    when the request arrived over TLS."""

    def _logout(self, is_tls):
        handler = _FakeHandler(command="POST", is_tls=is_tls)
        with patch("freq.api.auth.vault_get"), patch("freq.api.auth.vault_set"):
            auth_mod.handle_auth_logout(handler)
        cookie_header = next(
            (v for k, v in handler._sent_headers if k == "Set-Cookie"), ""
        )
        return cookie_header

    def test_logout_over_tls_sets_secure(self):
        cookie = self._logout(is_tls=True)
        self.assertIn("Max-Age=0", cookie)
        self.assertIn("Secure", cookie,
                      "logout over TLS must mirror login's Secure flag")

    def test_logout_over_plain_omits_secure(self):
        cookie = self._logout(is_tls=False)
        self.assertIn("Max-Age=0", cookie)
        self.assertNotIn("Secure", cookie,
                         "logout over plain HTTP must NOT set Secure")


class TestF11SetupStatusHidesSensitiveFields(unittest.TestCase):
    """F11 — /api/setup/status, which is in AUTH_WHITELIST, must not
    leak ssh_key_path / version / host_count to unauth callers."""

    def setUp(self):
        self.src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()

    def test_unauth_branch_omits_sensitive_fields(self):
        """The unauth payload literal must not name ssh_key_path,
        version, or host_count outside the is_authed branch."""
        # Anchor on the function header.
        idx = self.src.find("def _serve_setup_status")
        self.assertNotEqual(idx, -1)
        end = self.src.find("def _serve_setup_create_admin", idx)
        block = self.src[idx:end]
        # The payload literal that always ships:
        always_idx = block.find("payload = {")
        self.assertNotEqual(always_idx, -1,
                            "F11 fix must build payload as a dict literal")
        always_end = block.find("}", always_idx)
        always_payload = block[always_idx:always_end]
        self.assertNotIn("ssh_key_path", always_payload,
                         "ssh_key_path must only land in the is_authed branch")
        self.assertNotIn("version", always_payload,
                         "version must only land in the is_authed branch")
        self.assertNotIn("host_count", always_payload,
                         "host_count must only land in the is_authed branch")

    def test_is_authed_gate_present(self):
        """The handler must consult _check_session_role to decide whether
        to enrich the response."""
        idx = self.src.find("def _serve_setup_status")
        end = self.src.find("def _serve_setup_create_admin", idx)
        block = self.src[idx:end]
        self.assertIn("_check_session_role", block)
        self.assertIn("is_authed", block)
        self.assertIn('payload["ssh_key_path"]', block)
        self.assertIn('payload["version"]', block)
        self.assertIn('payload["host_count"]', block)


class TestF13LogRedactionCoversNewParams(unittest.TestCase):
    """F13 — log redaction must catch key=, session=, pass=, pw=, auth="""

    def test_redact_key_equals(self):
        """Lab-tool API key in URL (F3) must be redacted."""
        msg = "GET /api/lab-tool/proxy?tool=tdarr&host=x&key=SECRETKEY123&endpoint=foo"
        out = freq_log._redact(msg)
        self.assertNotIn("SECRETKEY123", out)
        self.assertIn("REDACTED", out)

    def test_redact_session_equals(self):
        """Terminal session id in WS URL (F8) must be redacted so the
        log itself can't be the leak channel for the hijack vector."""
        msg = "GET /api/terminal/ws?session=abcdef0123456789ghijklmn"
        out = freq_log._redact(msg)
        self.assertNotIn("abcdef0123456789ghijklmn", out)
        self.assertIn("REDACTED", out)

    def test_redact_pass_short_form(self):
        msg = "?pass=mypassword123"
        out = freq_log._redact(msg)
        self.assertNotIn("mypassword123", out)
        self.assertIn("REDACTED", out)

    def test_redact_pw_short_form(self):
        msg = "user pw=hunter2"
        out = freq_log._redact(msg)
        self.assertNotIn("hunter2", out)
        self.assertIn("REDACTED", out)

    def test_redact_auth_generic(self):
        msg = "auth=ZmFrZS10b2tlbg=="
        out = freq_log._redact(msg)
        self.assertNotIn("ZmFrZS10b2tlbg", out)
        self.assertIn("REDACTED", out)

    def test_existing_password_still_redacted(self):
        """The original password= pattern must still work."""
        msg = "?password=qwerty12345"
        out = freq_log._redact(msg)
        self.assertNotIn("qwerty12345", out)


class TestF5CtCreatePasswordFromBody(unittest.TestCase):
    """F5 — ct/create reads password from JSON body, not query string."""

    def test_source_reads_password_from_body_only(self):
        src = (REPO_ROOT / "freq" / "api" / "ct.py").read_text()
        # Anchor on the handler.
        idx = src.find("def handle_ct_create")
        self.assertNotEqual(idx, -1)
        end = src.find("def handle_ct_destroy", idx)
        block = src[idx:end]
        # Password must be read from body, not via the params/query path.
        self.assertIn(
            'password = str(body.get("password", "")).strip()',
            block,
            "password must be read from JSON body only, not query params",
        )
        # Pre-fix shape must be gone.
        self.assertNotIn(
            'params.get("password"',
            block,
            "params.get(\"password\"...) leak channel must be removed",
        )

    def test_dashboard_js_sends_post_json_body(self):
        js = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        idx = js.find("function doCtCreate")
        self.assertNotEqual(idx, -1)
        end = js.find("function doCtClone", idx)
        block = js[idx:end]
        self.assertIn("API.CT_CREATE", block)
        self.assertIn("method:'POST'", block)
        self.assertIn("Content-Type", block)
        # Must NOT pass template/hostname via query string.
        self.assertNotIn(
            "API.CT_CREATE+'?",
            block,
            "doCtCreate must POST a JSON body, not a query string",
        )


class TestF6FederationRegisterSecretFromBody(unittest.TestCase):
    """F6 — federation/register reads HMAC secret from JSON body."""

    def test_source_reads_secret_from_body_only(self):
        src = (REPO_ROOT / "freq" / "api" / "fleet.py").read_text()
        idx = src.find("def handle_federation_register")
        self.assertNotEqual(idx, -1)
        end = src.find("def handle_federation_unregister", idx)
        block = src[idx:end]
        self.assertIn(
            'secret = str(body.get("secret", "")).strip()',
            block,
            "secret must be read from JSON body only",
        )
        self.assertNotIn(
            'params.get("secret"',
            block,
            "params.get(\"secret\"...) leak channel must be removed",
        )

    def test_dashboard_js_sends_post_json_body(self):
        js = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        idx = js.find("function fedRegister")
        self.assertNotEqual(idx, -1)
        end = js.find("\nfunction ", idx + 1)
        block = js[idx:end]
        self.assertIn("'/api/federation/register'", block)
        self.assertIn("method:'POST'", block)
        self.assertNotIn(
            "?secret=",
            block,
            "fedRegister must NOT put secret in the URL query string",
        )


class TestF7SseQueryTokenFallbackRemoved(unittest.TestCase):
    """F7 — check_session_role no longer falls back to query-string token."""

    def test_source_drops_query_token_path(self):
        src = (REPO_ROOT / "freq" / "api" / "auth.py").read_text()
        # The pre-fix shape was a parse_qs against handler.path checking
        # parsed.path == "/api/events" and reading qs.get("token", ...).
        # All three should be gone from the auth file now.
        self.assertNotIn("/api/events", src,
                         "auth.py must not name /api/events directly")
        self.assertNotIn('qs.get("token"', src,
                         "auth.py must not pull token from query string")
        # The cookie + bearer header path must still exist.
        self.assertIn("Bearer ", src)
        self.assertIn("freq_session=", src)


class TestF8TerminalSessionCreatorBinding(unittest.TestCase):
    """F8 — terminal sessions are bound to their creator and the WS
    refuses to bind a session that belongs to another user."""

    def test_session_dict_carries_user(self):
        src = (REPO_ROOT / "freq" / "api" / "terminal.py").read_text()
        idx = src.find("def handle_terminal_open")
        self.assertNotEqual(idx, -1)
        end = src.find("def handle_terminal_close", idx)
        block = src[idx:end]
        self.assertIn("creator = current_user(handler)", block,
                      "open handler must capture the creating user")
        self.assertIn('"user": creator', block,
                      "session dict must store the creator's username")

    def test_ws_handler_refuses_cross_user_bind(self):
        src = (REPO_ROOT / "freq" / "api" / "terminal.py").read_text()
        idx = src.find("def handle_terminal_ws")
        self.assertNotEqual(idx, -1)
        end = src.find("def _ws_bridge", idx)
        block = src[idx:end]
        self.assertIn("requesting_user = current_user(handler)", block)
        self.assertIn("creator != requesting_user", block,
                      "WS handler must compare creator against requester")
        self.assertIn("Session belongs to another user", block)


class TestF4VaultKeyNotInArgv(unittest.TestCase):
    """F4 — vault openssl invocations must NOT carry the key in argv.

    Pre-fix the key landed in /proc/<pid>/cmdline as `pass:KEY`. Fix
    moves the key to an inherited pipe FD via subprocess.pass_fds.
    """

    def test_vault_source_uses_pass_fd_helper(self):
        src = (REPO_ROOT / "freq" / "modules" / "vault.py").read_text()
        # The new fd-passing helper must exist.
        self.assertIn("def _run_openssl_with_key", src)
        self.assertIn("pass_fds=[r_fd]", src)
        self.assertIn('f"fd:{r_fd}"', src)
        # The pre-fix `-pass`, `pass:{key}` shape must be gone from the
        # _encrypt and _decrypt callers (the helper builds the -pass
        # arg itself, so the literal string `pass:` should not appear).
        self.assertNotIn('f"pass:{key}"', src,
                         "pass:KEY argv form must not return — F4 regression")

    def test_vault_round_trip_works(self):
        """Behavioral: encrypt then decrypt must round-trip."""
        import os
        import tempfile
        from freq.modules.vault import _encrypt, _decrypt

        with tempfile.NamedTemporaryFile(suffix=".vault", delete=False) as f:
            path = f.name
        try:
            key = "abcdef0123456789" * 4  # 64 chars, like the real machine-id derivation
            payload = "host|key|value\nfoo|bar|baz\n"
            self.assertTrue(_encrypt(payload, key, path),
                            "encrypt must succeed via fd-passing")
            self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600",
                             "vault file mode must be 0600 after encrypt")
            self.assertEqual(_decrypt(key, path), payload,
                             "decrypt must round-trip the encrypted plaintext")
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_wrong_key_does_not_decrypt(self):
        """Sanity: openssl is actually doing the encryption."""
        import os
        import tempfile
        from freq.modules.vault import _encrypt, _decrypt

        with tempfile.NamedTemporaryFile(suffix=".vault", delete=False) as f:
            path = f.name
        try:
            self.assertTrue(_encrypt("secret data", "key-one" * 8, path))
            wrong = _decrypt("key-two" * 8, path)
            self.assertEqual(wrong, "",
                             "decrypt with wrong key must return empty string")
        finally:
            if os.path.exists(path):
                os.unlink(path)


class TestF15CtCreatePasswordShellQuoted(unittest.TestCase):
    """F15 — ct/create password is shlex.quoted before shell interpolation."""

    def test_password_shell_quoted(self):
        src = (REPO_ROOT / "freq" / "api" / "ct.py").read_text()
        idx = src.find("def handle_ct_create")
        end = src.find("def handle_ct_destroy", idx)
        block = src[idx:end]
        self.assertIn("import shlex", block,
                      "ct.handle_ct_create must import shlex for password quoting")
        self.assertIn(
            "--password {shlex.quote(password)}",
            block,
            "password must be shlex.quoted before interpolation into the "
            "pct create shell command",
        )
        # The unquoted form must be gone.
        self.assertNotIn(
            "--password {password}",
            block,
            "raw unquoted --password {password} interpolation must not return",
        )


if __name__ == "__main__":
    unittest.main()
