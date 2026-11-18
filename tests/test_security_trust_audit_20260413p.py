"""Regression contracts for R-SECURITY-TRUST-AUDIT-20260413P fixes.

Each TestCase pins one finding from
/opt/freq-devs/rick/findings/R-SECURITY-TRUST-AUDIT-20260413P.md
so the underlying gap can never silently regress.

Covered:
  - F1   trust-on-first-use account takeover (auth.py login refuses
         empty stored_hash + refuses on vault read failure).
  - F2   /api/setup/test-ssh dropped from AUTH_WHITELIST + admin-only
         + scoped to configured PVE nodes.
  - F3   /api/lab-tool/proxy reads host/key from vault, GET-only,
         per-tool endpoint allow-list.
  - F4   vault openssl key passed via inherited pipe FD, not argv.
  - F5   /api/ct/create reads password from JSON body, not query string.
  - F6   /api/federation/register reads HMAC secret from JSON body.
  - F7   check_session_role drops the SSE query-string token fallback.
  - F8   terminal session creator binding — WS refuses cross-user binds.
  - F9   _is_first_run fails CLOSED on exception (not OPEN).
  - F10  logout cookie clear matches login Secure-flag symmetry.
  - F11  /api/setup/status hides ssh_key_path / version / host_count
         from unauth callers.
  - F12  ct/exec drops the theatrical dangerous-command blacklist.
  - F13  log redaction covers key= / session= / pass= / pw= / auth=.
  - F15  ct/create password is shlex.quoted before shell interpolation.
  - F17  /api/dns/lookup tightened to operator + per-IP rate limit.
  - F18  /api/vm/push-key migrated from GET to POST + JSON body.
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
        headers={"Origin": "https://freq.test", "Host": "freq.test"},
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
         patch("freq.api.auth.record_login_attempt"), \
         patch("freq.api.auth.request_is_https", return_value=True):
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
        scheme = "https" if is_tls else "http"
        handler = _FakeHandler(
            command="POST",
            is_tls=is_tls,
            headers={"Origin": f"{scheme}://freq.test", "Host": "freq.test"},
        )
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
        self.assertEqual(cookie, "")
        self.assertNotIn("Secure", cookie,
                         "plain HTTP logout must be rejected before cookie mutation")


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
        self.assertIn("ws_nonce = secrets.token_urlsafe", block,
                      "open handler must create a websocket nonce")
        self.assertIn('"ws_nonce": ws_nonce', block,
                      "session dict must store the websocket nonce")

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
        self.assertIn("same_origin_or_absent(handler)", block)
        self.assertIn("secrets.compare_digest(expected_nonce, supplied_nonce)", block)
        self.assertIn("Terminal websocket nonce required", block)


class TestF4VaultKeyNotInArgv(unittest.TestCase):
    """F4 — vault openssl invocations must NOT carry the key in argv.

    Pre-fix the key landed in /proc/<pid>/cmdline as `pass:KEY`. Fix
    moves the key to an inherited pipe FD via subprocess.pass_fds.
    """

    def test_vault_source_uses_pass_fd_helper(self):
        src = (REPO_ROOT / "freq" / "core" / "vault.py").read_text()
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
        """Sanity: openssl does not recover plaintext with the wrong key."""
        import os
        import tempfile
        from freq.modules.vault import _encrypt, _decrypt

        with tempfile.NamedTemporaryFile(suffix=".vault", delete=False) as f:
            path = f.name
        try:
            self.assertTrue(_encrypt("secret data", "key-one" * 8, path))
            wrong = _decrypt("key-two" * 8, path)
            self.assertNotEqual(
                wrong,
                "secret data",
                "decrypt with wrong key must not recover the plaintext",
            )
        finally:
            if os.path.exists(path):
                os.unlink(path)

    @patch("freq.modules.vault._run_openssl_with_key")
    @patch("freq.modules.vault.os.path.exists", return_value=True)
    def test_invalid_utf8_decrypt_fails_closed(self, _exists, run_openssl):
        """Valid CBC padding with non-text bytes must not escape as an exception."""
        from freq.modules.vault import _decrypt

        run_openssl.return_value = MagicMock(returncode=0, stdout=b"\xcc")

        self.assertEqual(_decrypt("wrong-key", "/tmp/vault.enc"), "")


class TestF15CtCreatePasswordShellQuoted(unittest.TestCase):
    """F15 — ct/create keeps password bytes in a serializer-owned argument."""

    def test_password_shell_quoted(self):
        src = (REPO_ROOT / "freq" / "api" / "ct.py").read_text()
        idx = src.find("def handle_ct_create")
        end = src.find("def handle_ct_destroy", idx)
        block = src[idx:end]
        self.assertIn(
            'remote_command(',
            block,
            "ct.handle_ct_create must delegate command serialization",
        )
        self.assertIn(
            '(("--password", password) if password else ())',
            block,
            "password must remain one data argument owned by remote_command",
        )
        self.assertNotIn(
            "--password {password}",
            block,
            "raw unquoted --password {password} interpolation must not return",
        )


class TestF17DnsLookupRateLimited(unittest.TestCase):
    """F17 — /api/dns/lookup tightened to operator + per-IP rate limit."""

    def test_handler_requires_operator(self):
        import socket

        from freq.modules import serve
        from freq.services import dns_lookup

        def handler(client_address=("203.0.113.50", 4242)):
            instance = object.__new__(serve.FreqHandler)
            instance.client_address = client_address
            instance._json_response = MagicMock()
            return instance

        denied = handler()
        with patch.object(
            serve,
            "_check_session_role",
            return_value=(None, "operator required"),
        ) as check_role, patch.object(
            dns_lookup, "allow_lookup"
        ) as rate_limit, patch.object(serve, "_parse_query") as parse_query, patch(
            "socket.getaddrinfo"
        ) as getaddrinfo:
            denied._serve_dns_lookup()
        check_role.assert_called_once_with(denied, "operator")
        denied._json_response.assert_called_once_with(
            {"error": "operator required"}, 403
        )
        rate_limit.assert_not_called()
        parse_query.assert_not_called()
        getaddrinfo.assert_not_called()

        limited = handler()
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            dns_lookup, "allow_lookup", return_value=False
        ) as rate_limit, patch.object(serve, "_parse_query") as parse_query, patch(
            "socket.getaddrinfo"
        ) as getaddrinfo:
            limited._serve_dns_lookup()
        rate_limit.assert_called_once_with("203.0.113.50")
        limited._json_response.assert_called_once_with(
            {"error": "Too many DNS lookups. Try again in 5 minutes."}, 429
        )
        parse_query.assert_not_called()
        getaddrinfo.assert_not_called()

        unknown_client = handler(None)
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            dns_lookup, "allow_lookup", return_value=False
        ) as rate_limit:
            unknown_client._serve_dns_lookup()
        rate_limit.assert_called_once_with("unknown")

        invalid_cases = (
            ({}, {"error": "host required"}),
            ({"host": ["a" * 254]}, {"error": "Hostname too long"}),
            ({"host": ["not valid!"]}, {"error": "Invalid hostname"}),
        )
        for query, expected in invalid_cases:
            with self.subTest(query=query):
                invalid = handler()
                with patch.object(
                    serve, "_check_session_role", return_value=(object(), None)
                ), patch.object(
                    dns_lookup, "allow_lookup", return_value=True
                ), patch.object(
                    serve, "_parse_query", return_value=query
                ), patch(
                    "freq.services.dns_lookup.socket.getaddrinfo"
                ) as getaddrinfo:
                    invalid._serve_dns_lookup()
                invalid._json_response.assert_called_once_with(expected, 400)
                getaddrinfo.assert_not_called()

        max_length_host = ".".join(("a" * 63, "b" * 63, "c" * 63, "d" * 61))
        self.assertEqual(len(max_length_host), 253)
        max_length = handler()
        max_length_rows = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.253", 0)),
        ]
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            dns_lookup, "allow_lookup", return_value=True
        ), patch.object(
            serve, "_parse_query", return_value={"host": [max_length_host]}
        ), patch(
            "freq.services.dns_lookup.socket.getaddrinfo", return_value=max_length_rows
        ) as getaddrinfo:
            max_length._serve_dns_lookup()
        getaddrinfo.assert_called_once_with(max_length_host, None)
        max_length._json_response.assert_called_once_with(
            {"host": max_length_host, "ips": ["192.0.2.253"], "count": 1}
        )

        resolved = handler()
        address_rows = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 0, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.20", 0)),
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.10", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.20", 0)),
        ]
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            dns_lookup, "allow_lookup", return_value=True
        ), patch.object(
            serve, "_parse_query", return_value={"host": ["node.example"]}
        ), patch(
            "freq.services.dns_lookup.socket.getaddrinfo", return_value=address_rows
        ) as getaddrinfo:
            resolved._serve_dns_lookup()
        getaddrinfo.assert_called_once_with("node.example", None)
        resolved._json_response.assert_called_once_with(
            {
                "host": "node.example",
                "ips": ["192.0.2.10", "192.0.2.20", "2001:db8::1"],
                "count": 3,
            }
        )

        failed = handler()
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            dns_lookup, "allow_lookup", return_value=True
        ), patch.object(
            serve, "_parse_query", return_value={"host": ["missing.example"]}
        ), patch(
            "freq.services.dns_lookup.socket.getaddrinfo",
            side_effect=socket.gaierror("not found"),
        ):
            failed._serve_dns_lookup()
        failed._json_response.assert_called_once_with(
            {
                "host": "missing.example",
                "ips": [],
                "error": "DNS resolution failed",
            },
            400,
        )

    def test_rate_limiter_caps_at_max(self):
        from freq.services.dns_lookup import (
            _DNS_LOOKUP_LOG,
            _DNS_LOOKUP_MAX,
            allow_lookup,
        )
        # Use a unique IP so other tests don't pollute this bucket.
        ip = "203.0.113.99"
        with patch.dict(_DNS_LOOKUP_LOG, {ip: []}, clear=False):
            _DNS_LOOKUP_LOG[ip] = []
            for i in range(_DNS_LOOKUP_MAX):
                self.assertTrue(
                    allow_lookup(ip),
                    f"lookup #{i + 1} must be allowed (under cap)",
                )
            # The (cap + 1)-th lookup must be denied.
            self.assertFalse(
                allow_lookup(ip),
                "lookup beyond the cap must be denied",
            )
            _DNS_LOOKUP_LOG.pop(ip, None)

    def test_rate_limiter_per_ip_isolated(self):
        from freq.services.dns_lookup import (
            _DNS_LOOKUP_LOG,
            _DNS_LOOKUP_MAX,
            allow_lookup,
        )
        ip_a = "203.0.113.10"
        ip_b = "203.0.113.20"
        _DNS_LOOKUP_LOG[ip_a] = []
        _DNS_LOOKUP_LOG[ip_b] = []
        try:
            for _ in range(_DNS_LOOKUP_MAX):
                self.assertTrue(allow_lookup(ip_a))
            self.assertFalse(allow_lookup(ip_a))
            # ip_b's bucket is independent — must still be allowed.
            self.assertTrue(
                allow_lookup(ip_b),
                "rate limit must be per-source-IP, not global",
            )
        finally:
            _DNS_LOOKUP_LOG.pop(ip_a, None)
            _DNS_LOOKUP_LOG.pop(ip_b, None)


class TestF18VmPushKeyIsPost(unittest.TestCase):
    """F18 — /api/vm/push-key now requires POST and reads ip from body."""

    def test_handler_requires_post(self):
        src = (REPO_ROOT / "freq" / "api" / "vm.py").read_text()
        idx = src.find("def handle_vm_push_key")
        self.assertNotEqual(idx, -1)
        end = src.find("\ndef ", idx + 1)
        block = src[idx:end]
        self.assertIn("_require_post(handler", block,
                      "vm push-key must call _require_post")
        self.assertIn("get_json_body(handler)", block,
                      "vm push-key must read ip from JSON body")
        self.assertNotIn(
            'parse_qs(urlparse(handler.path).query)',
            block,
            "vm push-key must not pull the target IP from the query string",
        )

    def test_dashboard_js_uses_post_body(self):
        js = (REPO_ROOT / "freq" / "data" / "web" / "js" / "app.js").read_text()
        idx = js.find("function vmPushKey")
        self.assertNotEqual(idx, -1)
        end = js.find("\nfunction ", idx + 1)
        block = js[idx:end]
        self.assertIn("'/api/vm/push-key'", block,
                      "vmPushKey must POST to /api/vm/push-key")
        self.assertIn("method:'POST'", block)
        self.assertNotIn(
            "/api/vm/push-key?ip=",
            block,
            "vmPushKey must not put target ip in the query string",
        )


class TestF2SetupTestSshGated(unittest.TestCase):
    """F2 — /api/setup/test-ssh removed from AUTH_WHITELIST,
    admin-only, scoped to configured PVE nodes."""

    def setUp(self):
        self.src = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()

    def test_not_in_auth_whitelist(self):
        # Look at the whitelist literal block, not the entire file.
        idx = self.src.find("_AUTH_WHITELIST = frozenset({")
        self.assertNotEqual(idx, -1)
        end = self.src.find("})", idx)
        whitelist = self.src[idx:end]
        self.assertNotIn(
            '"/api/setup/test-ssh"',
            whitelist,
            "/api/setup/test-ssh must NOT be in _AUTH_WHITELIST anymore",
        )

    def test_handler_requires_admin_and_scopes_targets(self):
        idx = self.src.find("def _serve_setup_test_ssh")
        self.assertNotEqual(idx, -1)
        end = self.src.find("def _serve_setup_reset", idx)
        block = self.src[idx:end]
        self.assertIn(
            '_check_session_role(self, "admin")',
            block,
            "test-ssh must require admin role",
        )
        self.assertIn(
            "configured_targets = set(cfg.pve_nodes",
            block,
            "test-ssh must scope host to cfg.pve_nodes",
        )
        self.assertIn(
            "if host not in configured_targets",
            block,
            "test-ssh must refuse hosts outside the configured target list",
        )


class TestF3LabToolProxyHardened(unittest.TestCase):
    """F3 — /api/lab-tool/proxy reads host/key from vault, GET-only,
    per-tool endpoint allow-list."""

    def test_registry_carries_endpoints_allowlist(self):
        from freq.modules import serve
        from freq.services import lab_tool_proxy

        self.assertIs(
            serve.FreqHandler.LAB_TOOL_REGISTRY,
            lab_tool_proxy.LAB_TOOL_REGISTRY,
        )
        self.assertEqual(set(serve.FreqHandler.LAB_TOOL_REGISTRY), {"gwipe"})
        tool = serve.FreqHandler.LAB_TOOL_REGISTRY["gwipe"]
        self.assertEqual(tool["default_port"], 7980)
        self.assertEqual(tool["api_base"], "/api/v1")
        self.assertEqual(tool["auth_header"], "X-API-Key")
        self.assertIsInstance(tool["endpoints"], frozenset)
        self.assertEqual(
            tool["endpoints"],
            {"status", "drives", "drives/list", "jobs", "jobs/list"},
        )

    def test_proxy_handler_reads_from_vault_only(self):
        from freq.modules import serve

        def handler():
            instance = object.__new__(serve.FreqHandler)
            instance._json_response = MagicMock()
            return instance

        denied = handler()
        with patch.object(
            serve,
            "_check_session_role",
            return_value=(None, "operator required"),
        ) as check_role, patch.object(serve, "_parse_query") as parse_query, patch.object(
            serve, "load_config"
        ) as load_config, patch.object(serve, "vault_get") as vault_get, patch.object(
            serve.FreqHandler, "_lab_tool_request"
        ) as request:
            denied._serve_lab_tool_proxy()
        check_role.assert_called_once_with(denied, "operator")
        denied._json_response.assert_called_once_with(
            {"error": "operator required"}, 403
        )
        parse_query.assert_not_called()
        load_config.assert_not_called()
        vault_get.assert_not_called()
        request.assert_not_called()

        for query in ({}, {"tool": ["gwipe"]}, {"endpoint": ["status"]}):
            with self.subTest(query=query):
                missing = handler()
                with patch.object(
                    serve, "_check_session_role", return_value=(object(), None)
                ), patch.object(
                    serve, "_parse_query", return_value=query
                ), patch.object(serve, "load_config") as load_config, patch.object(
                    serve, "vault_get"
                ) as vault_get, patch.object(
                    serve.FreqHandler, "_lab_tool_request"
                ) as request:
                    missing._serve_lab_tool_proxy()
                missing._json_response.assert_called_once_with(
                    {"error": "Missing tool or endpoint parameter"}, 400
                )
                load_config.assert_not_called()
                vault_get.assert_not_called()
                request.assert_not_called()

        unknown = handler()
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            serve,
            "_parse_query",
            return_value={"tool": ["unknown"], "endpoint": ["status"]},
        ), patch.object(serve, "load_config") as load_config, patch.object(
            serve, "vault_get"
        ) as vault_get, patch.object(
            serve.FreqHandler, "_lab_tool_request"
        ) as request:
            unknown._serve_lab_tool_proxy()
        unknown._json_response.assert_called_once_with(
            {"error": "Unknown lab tool: unknown"}, 404
        )
        load_config.assert_not_called()
        vault_get.assert_not_called()
        request.assert_not_called()

        disallowed = handler()
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            serve,
            "_parse_query",
            return_value={"tool": ["gwipe"], "endpoint": ["admin/delete"]},
        ), patch.object(serve, "load_config") as load_config, patch.object(
            serve, "vault_get"
        ) as vault_get, patch.object(
            serve.FreqHandler, "_lab_tool_request"
        ) as request:
            disallowed._serve_lab_tool_proxy()
        disallowed._json_response.assert_called_once_with(
            {
                "error": (
                    "Endpoint 'admin/delete' is not in the allow-list for tool "
                    "'gwipe'. Allowed: ['drives', 'drives/list', 'jobs', "
                    "'jobs/list', 'status']"
                )
            },
            403,
        )
        load_config.assert_not_called()
        vault_get.assert_not_called()
        request.assert_not_called()

        cfg = object()
        unavailable = handler()
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            serve,
            "_parse_query",
            return_value={"tool": ["gwipe"], "endpoint": ["status"]},
        ), patch.object(serve, "load_config", return_value=cfg), patch.object(
            serve, "vault_get", side_effect=RuntimeError("vault unavailable")
        ) as vault_get, patch.object(
            serve.FreqHandler, "_lab_tool_request"
        ) as request:
            unavailable._serve_lab_tool_proxy()
        vault_get.assert_called_once_with(cfg, "gwipe", "gwipe_host")
        unavailable._json_response.assert_called_once_with(
            {
                "error": (
                    "Tool 'gwipe' has no saved host/key — admin must call "
                    "/api/lab-tool/save-config first."
                )
            },
            503,
        )
        request.assert_not_called()

        key_unavailable = handler()
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            serve,
            "_parse_query",
            return_value={"tool": ["gwipe"], "endpoint": ["status"]},
        ), patch.object(serve, "load_config", return_value=cfg), patch.object(
            serve,
            "vault_get",
            side_effect=("vault-host.example", RuntimeError("key unavailable")),
        ) as vault_get, patch.object(
            serve.FreqHandler, "_lab_tool_request"
        ) as request:
            key_unavailable._serve_lab_tool_proxy()
        self.assertEqual(
            vault_get.call_args_list,
            [
                unittest.mock.call(cfg, "gwipe", "gwipe_host"),
                unittest.mock.call(cfg, "gwipe", "gwipe_api_key"),
            ],
        )
        key_unavailable._json_response.assert_called_once_with(
            {
                "error": (
                    "Tool 'gwipe' has no saved host/key — admin must call "
                    "/api/lab-tool/save-config first."
                )
            },
            503,
        )
        request.assert_not_called()

        configured = handler()
        vault_values = {
            "gwipe_host": "vault-host.example",
            "gwipe_api_key": "vault-secret",
        }
        with patch.object(
            serve, "_check_session_role", return_value=(object(), None)
        ), patch.object(
            serve,
            "_parse_query",
            return_value={
                "tool": ["gwipe"],
                "endpoint": ["status"],
                "host": ["caller-host.example"],
                "key": ["caller-secret"],
                "method": ["DELETE"],
            },
        ), patch.object(serve, "load_config", return_value=cfg), patch.object(
            serve,
            "vault_get",
            side_effect=lambda _cfg, _group, key: vault_values[key],
        ) as vault_get, patch.object(
            serve.FreqHandler,
            "_lab_tool_request",
            return_value={"status": "ready"},
        ) as request:
            configured._serve_lab_tool_proxy()
        self.assertEqual(
            vault_get.call_args_list,
            [
                unittest.mock.call(cfg, "gwipe", "gwipe_host"),
                unittest.mock.call(cfg, "gwipe", "gwipe_api_key"),
            ],
        )
        request.assert_called_once_with(
            "gwipe", "vault-host.example", "vault-secret", "status"
        )
        configured._json_response.assert_called_once_with({"status": "ready"})

    def test_lab_tool_request_helper_is_get_only(self):
        import io
        import urllib.error

        from freq.modules import serve
        from freq.services import lab_tool_proxy

        self.assertIs(
            serve.FreqHandler._lab_tool_request,
            lab_tool_proxy.lab_tool_request,
        )
        request_tool = lab_tool_proxy.lab_tool_request

        with patch("freq.services.lab_tool_proxy.urllib.request.urlopen") as urlopen:
            self.assertEqual(
                request_tool("unknown", "host.example", "secret", "status"),
                {"error": "Unknown lab tool: unknown"},
            )
            self.assertEqual(
                request_tool("gwipe", "host.example", "secret", "admin/delete"),
                {"error": "Endpoint 'admin/delete' not allowed for gwipe"},
            )
        urlopen.assert_not_called()

        endpoints = serve.FreqHandler.LAB_TOOL_REGISTRY["gwipe"]["endpoints"]
        for endpoint in sorted(endpoints):
            with self.subTest(endpoint=endpoint):
                response = MagicMock()
                response.read.return_value = (
                    f'{{"endpoint":"{endpoint}"}}'.encode()
                )
                context = MagicMock()
                context.__enter__.return_value = response
                with patch(
                    "freq.services.lab_tool_proxy.urllib.request.urlopen",
                    return_value=context,
                ) as urlopen:
                    result = request_tool(
                        "gwipe", "host.example", "vault-secret", endpoint
                    )
                self.assertEqual(result, {"endpoint": endpoint})
                request = urlopen.call_args.args[0]
                self.assertEqual(
                    request.full_url,
                    f"http://host.example:7980/api/v1/{endpoint}",
                )
                self.assertEqual(request.get_method(), "GET")
                self.assertEqual(request.get_header("X-api-key"), "vault-secret")
                self.assertEqual(urlopen.call_args.kwargs, {"timeout": 10})

        http_json = urllib.error.HTTPError(
            "http://host.example",
            502,
            "bad gateway",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"upstream failed"}'),
        )
        with patch(
            "freq.services.lab_tool_proxy.urllib.request.urlopen",
            side_effect=http_json,
        ):
            self.assertEqual(
                request_tool("gwipe", "host.example", "secret", "status"),
                {"error": "upstream failed"},
            )

        http_invalid = urllib.error.HTTPError(
            "http://host.example",
            503,
            "unavailable",
            hdrs=None,
            fp=io.BytesIO(b"not-json"),
        )
        with patch(
            "freq.services.lab_tool_proxy.urllib.request.urlopen",
            side_effect=http_invalid,
        ):
            self.assertEqual(
                request_tool("gwipe", "host.example", "secret", "status"),
                {"error": "HTTP 503"},
            )

        with patch(
            "freq.services.lab_tool_proxy.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            self.assertEqual(
                request_tool("gwipe", "host.example", "secret", "status"),
                {"error": "Cannot reach gwipe at host.example:7980 — offline"},
            )

        with patch(
            "freq.services.lab_tool_proxy.urllib.request.urlopen",
            side_effect=RuntimeError("unexpected failure"),
        ):
            self.assertEqual(
                request_tool("gwipe", "host.example", "secret", "status"),
                {"error": "unexpected failure"},
            )


class TestF9IsFirstRunFailsClosed(unittest.TestCase):
    """F9 — _is_first_run returns False on exception (fail closed)."""

    def test_source_returns_false_on_exception(self):
        src = (REPO_ROOT / "freq" / "api" / "auth.py").read_text()
        idx = src.find("def is_first_run")
        self.assertNotEqual(idx, -1)
        end = src.find("\ndef ", idx + 1)
        block = src[idx:end]
        # The pre-fix shape was `return True  # If we can't check`
        self.assertNotIn(
            "return True  # If we can't check",
            block,
            "fail-open `return True` on exception must be gone — F9 regression",
        )
        # Look for the explicit fail-closed return.
        self.assertIn(
            "return False  # Fail closed",
            block,
            "fail-closed `return False` must be the exception-handler return",
        )

    def test_behavioral_fail_closed_on_exception(self):
        from freq.modules import serve as serve_mod
        with patch("freq.api.auth._load_users", side_effect=RuntimeError("boom")), \
             patch("freq.api.auth.load_config") as load_cfg:
            load_cfg.return_value = MagicMock(
                data_dir="/tmp/nonexistent",
                conf_dir="/tmp/nonexistent",
            )
            self.assertFalse(
                serve_mod._is_first_run(),
                "_is_first_run must return False (fail closed) on _load_users exception",
            )


class TestF12CtExecBlacklistDropped(unittest.TestCase):
    """F12 — ct/exec drops the theatrical dangerous-command blacklist."""

    def test_blacklist_gone(self):
        src = (REPO_ROOT / "freq" / "api" / "ct.py").read_text()
        idx = src.find("def handle_ct_exec")
        end = src.find("def handle_ct_templates", idx)
        block = src[idx:end]
        # Pre-fix had a `dangerous = [...]` list with these literal patterns.
        self.assertNotIn(
            'dangerous = [',
            block,
            "the theatrical blacklist must be removed entirely",
        )
        self.assertNotIn(
            '"rm -rf /"',
            block,
            "the rm -rf / blacklist entry must be gone",
        )
        self.assertNotIn(
            '"mkfs"',
            block,
            "the mkfs blacklist entry must be gone",
        )
        # The honest framing comment must reference the audit token so a
        # future reader can understand WHY the blacklist isn't there.
        self.assertIn(
            "F12 of R-SECURITY-TRUST-AUDIT-20260413P",
            block,
            "must carry an explicit pointer to the audit token explaining "
            "why the blacklist was dropped",
        )


if __name__ == "__main__":
    unittest.main()
