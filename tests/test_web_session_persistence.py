"""Tests for web session persistence contract.

Bug: POST /api/auth/login returned 200 with token, but immediately
afterwards /api/auth/verify returned valid=false and protected APIs
returned 403. Session wasn't being persisted client-side.

Root cause: The Set-Cookie Secure flag was set based on cfg.tls_cert
being configured, not on the actual request scheme. When the dashboard
had tls_cert set but the client spoke HTTP (because TLS wrap failed,
or a reverse proxy terminated TLS, or TLS wasn't yet initialized), the
client received a Secure cookie but dropped it on the next HTTP request
— breaking session persistence.

Fix: Detect the actual request scheme by checking if handler.request
is an ssl.SSLSocket. Only set Secure when the specific login request
arrived over TLS. HTTP requests get non-Secure cookies (which work
over HTTP).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestSecureFlagBasedOnRequestScheme(unittest.TestCase):
    """Set-Cookie Secure flag must match the actual request scheme."""

    def test_secure_checks_sslsocket(self):
        """Secure-cookie classification must check the actual socket."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        self.assertIn("isinstance(getattr(handler,", src)
        self.assertIn("SSLSocket", src)

    def test_no_tls_cert_based_secure(self):
        """Must not set Secure based on cfg.tls_cert existence."""
        src = (FREQ_ROOT / "freq" / "api" / "auth.py").read_text()
        # The old pattern was: secure_flag = "; Secure" if tls_cert and os.path.isfile...
        # Must not reference tls_cert for Secure flag decision
        import re
        match = re.search(
            r'secure_flag\s*=\s*"; Secure" if tls_cert',
            src
        )
        self.assertIsNone(match, "Must not use tls_cert for Secure flag")

    def test_http_request_gets_no_secure_flag(self):
        """Direct HTTP requests must not receive Secure cookies."""
        from freq.api.auth import request_is_https

        handler = MagicMock()
        handler.request = object()
        handler.client_address = ("10.0.0.5", 1234)
        handler.headers.get = lambda key, default="": {"X-Forwarded-Proto": "https"}.get(key, default)
        cfg = MagicMock(trusted_proxy_cidrs=["127.0.0.1/32"])
        with patch("freq.api.auth.load_config", return_value=cfg):
            self.assertFalse(request_is_https(handler))

    def test_trusted_proxy_https_counts_for_secure_flag(self):
        """Trusted proxy HTTPS requests must receive Secure cookies."""
        from freq.api.auth import request_is_https

        handler = MagicMock()
        handler.request = object()
        handler.client_address = ("127.0.0.1", 1234)
        handler.headers.get = lambda key, default="": {"X-Forwarded-Proto": "https"}.get(key, default)
        cfg = MagicMock(trusted_proxy_cidrs=["127.0.0.1/32"])
        with patch("freq.api.auth.load_config", return_value=cfg):
            self.assertTrue(request_is_https(handler))


class TestTokenStorageUnchanged(unittest.TestCase):
    """The _auth_tokens store itself must still be shared across requests."""

    def test_auth_tokens_is_module_level(self):
        """_auth_tokens must remain a module-level dict."""
        from freq.api import auth
        self.assertIsInstance(auth._auth_tokens, dict)

    def test_auth_tokens_lock_is_module_level(self):
        """_auth_lock must remain a module-level threading.Lock."""
        import threading
        from freq.api import auth
        self.assertIsNotNone(auth._auth_lock)
        # threading.Lock returns an _thread.lock object, not a class instance
        self.assertTrue(hasattr(auth._auth_lock, "acquire"))


if __name__ == "__main__":
    unittest.main()
