"""R-SECURITY-ARCH-DEBT-20260413U regression contract.

Closes the two documented-not-fixed items from the R-REDTEAM-SECURITY-
ASSAULT-20260413T pass:

  T-7 — Rate limiter ignored X-Forwarded-For and had no per-user bucket.
        Fix: dual-bucket (per-IP + per-user) rate limiter with a trusted-
        proxy-aware client-IP resolver. Empty trusted_proxy_cidrs → the
        XFF header is ignored entirely (default-deny on direct-serve
        deployments). When the peer IS a trusted proxy, the resolver
        walks the XFF chain left-to-right and returns the leftmost
        non-trusted entry (the real client). The per-user bucket has a
        lower ceiling (5 failures/5min) than the per-IP bucket (10
        failures/5min) so a distributed attacker with many source IPs
        still gets ceilinged on any single target user.

  T-8 — /api/setup/create-admin had no lock. Two concurrent setup
        requests could both pass _is_first_run and write two admin
        accounts. Fix: wrap the mutation in _setup_lock (non-blocking
        acquire → 409 on collision) and double-check _is_first_run
        inside the lock.
"""
import os
import re
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
AUTH_PY = REPO / "freq" / "api" / "auth.py"
SERVE_PY = REPO / "freq" / "modules" / "serve.py"
CONFIG_PY = REPO / "freq" / "core" / "config.py"


class TestT7ConfigField(unittest.TestCase):
    """FreqConfig must expose a trusted_proxy_cidrs field and the TOML
    loader must populate it from [services] or [dashboard] tables."""

    def test_config_field_exists(self):
        src = CONFIG_PY.read_text()
        self.assertIn("trusted_proxy_cidrs: list", src)

    def test_toml_loader_reads_field(self):
        src = CONFIG_PY.read_text()
        self.assertIn("trusted_proxy_cidrs", src)
        # Pin that both [services] and [dashboard] tables are accepted.
        self.assertIn('services.get("trusted_proxy_cidrs")', src)
        self.assertIn('dashboard.get("trusted_proxy_cidrs")', src)


class TestT7ResolveClientIp(unittest.TestCase):
    """resolve_client_ip must default-deny XFF and only read it when the
    peer is in the trusted CIDR list."""

    def _fake_handler(self, peer_ip, xff_header=None):
        headers = {}
        if xff_header is not None:
            headers["X-Forwarded-For"] = xff_header

        class FakeHandler:
            client_address = (peer_ip, 0)
            def __init__(self, h):
                self.headers = h
        h = FakeHandler(headers)
        return h

    def test_empty_trusted_returns_peer_ip(self):
        """No trusted_proxy_cidrs configured → ignore XFF entirely."""
        from freq.api import auth as auth_mod
        fake_cfg = mock.Mock(trusted_proxy_cidrs=[])
        with mock.patch("freq.api.auth.load_config", return_value=fake_cfg):
            ip = auth_mod.resolve_client_ip(
                self._fake_handler("203.0.113.5", "198.51.100.99")
            )
        self.assertEqual(ip, "203.0.113.5",
                         "empty trusted_proxy_cidrs must ignore XFF")

    def test_peer_not_trusted_returns_peer_ip(self):
        """Peer NOT in trusted list → ignore XFF."""
        from freq.api import auth as auth_mod
        fake_cfg = mock.Mock(trusted_proxy_cidrs=["10.0.0.0/8"])
        with mock.patch("freq.api.auth.load_config", return_value=fake_cfg):
            ip = auth_mod.resolve_client_ip(
                self._fake_handler("203.0.113.5", "198.51.100.99")
            )
        self.assertEqual(ip, "203.0.113.5",
                         "untrusted peer must not be allowed to spoof XFF")

    def test_trusted_peer_reads_xff(self):
        """Peer IS in trusted list → leftmost non-trusted XFF entry wins."""
        from freq.api import auth as auth_mod
        fake_cfg = mock.Mock(trusted_proxy_cidrs=["10.0.0.0/8"])
        with mock.patch("freq.api.auth.load_config", return_value=fake_cfg):
            ip = auth_mod.resolve_client_ip(
                self._fake_handler("10.1.2.3", "198.51.100.99")
            )
        self.assertEqual(ip, "198.51.100.99")

    def test_chained_proxies_skip_trusted(self):
        """XFF with multiple entries — walk until we find the first
        non-trusted (real client) address."""
        from freq.api import auth as auth_mod
        fake_cfg = mock.Mock(trusted_proxy_cidrs=["10.0.0.0/8", "172.16.0.0/12"])
        with mock.patch("freq.api.auth.load_config", return_value=fake_cfg):
            ip = auth_mod.resolve_client_ip(
                self._fake_handler("10.1.2.3", "10.9.9.9, 172.16.1.1, 203.0.113.5")
            )
        self.assertEqual(ip, "203.0.113.5",
                         "trusted hops in XFF must be skipped")

    def test_trusted_peer_no_xff_header_falls_back_to_peer(self):
        from freq.api import auth as auth_mod
        fake_cfg = mock.Mock(trusted_proxy_cidrs=["10.0.0.0/8"])
        with mock.patch("freq.api.auth.load_config", return_value=fake_cfg):
            ip = auth_mod.resolve_client_ip(self._fake_handler("10.1.2.3"))
        self.assertEqual(ip, "10.1.2.3")


class TestT7DualBucketRateLimit(unittest.TestCase):
    """check_rate_limit must reject when EITHER per-IP OR per-user
    bucket is saturated. Per-user ceiling is lower than per-IP."""

    def _reset_buckets(self):
        from freq.api import auth as auth_mod
        with auth_mod._login_lock:
            auth_mod._login_attempts_ip.clear()
            auth_mod._login_attempts_user.clear()

    def test_per_user_ceiling_lower_than_per_ip(self):
        from freq.api import auth as auth_mod
        self.assertLess(
            auth_mod._RATE_MAX_FAILURES_USER,
            auth_mod._RATE_MAX_FAILURES_IP,
            "per-user bucket must have a lower ceiling than per-IP",
        )

    def test_per_user_bucket_blocks_distributed_attacker(self):
        """Simulate a distributed brute force: attacker hits `alice`
        from 20 different IPs, each just below the per-IP ceiling.
        The per-user bucket MUST still fire and block."""
        from freq.api import auth as auth_mod
        self._reset_buckets()
        username = "alice"
        # Each attacker IP records 1 failure — well under per-IP.
        for i in range(20):
            ip = f"198.51.100.{i+1}"
            auth_mod.record_login_attempt(ip, False, username)
        # All 20 failures counted against alice.
        ok = auth_mod.check_rate_limit("198.51.100.99", username)
        self.assertFalse(
            ok,
            "per-user bucket must reject after 20 distributed failures "
            "on one username even though no single IP was near its ceiling",
        )

    def test_per_ip_bucket_still_fires_on_single_ip(self):
        from freq.api import auth as auth_mod
        self._reset_buckets()
        ip = "198.51.100.77"
        for _ in range(auth_mod._RATE_MAX_FAILURES_IP + 1):
            auth_mod.record_login_attempt(ip, False, "")
        ok = auth_mod.check_rate_limit(ip)
        self.assertFalse(ok)

    def test_success_clears_per_user_failures(self):
        """Legitimate login must clear the per-user failure history so
        the operator's next typo doesn't land them in jail."""
        from freq.api import auth as auth_mod
        self._reset_buckets()
        username = "bob"
        for i in range(4):  # just under per-user ceiling
            auth_mod.record_login_attempt(f"10.0.0.{i}", False, username)
        self.assertTrue(auth_mod.check_rate_limit("10.0.0.50", username))
        # Successful login from yet another IP should purge failures.
        auth_mod.record_login_attempt("10.0.0.99", True, username)
        with auth_mod._login_lock:
            remaining_failures = sum(
                1 for t, s in auth_mod._login_attempts_user.get(username, [])
                if not s
            )
        self.assertEqual(
            remaining_failures, 0,
            "success must purge the per-user failure history"
        )

    def test_unused_buckets_dont_cross_contaminate(self):
        """Per-IP bucket for one IP must not leak into another IP's bucket."""
        from freq.api import auth as auth_mod
        self._reset_buckets()
        for _ in range(auth_mod._RATE_MAX_FAILURES_IP + 1):
            auth_mod.record_login_attempt("10.0.0.1", False, "alice")
        self.assertFalse(auth_mod.check_rate_limit("10.0.0.1", "carol"))
        # Different IP, different user — should NOT be blocked.
        self.assertTrue(auth_mod.check_rate_limit("10.0.0.2", "carol"))


class TestT7SourcePins(unittest.TestCase):
    """Source-level guards so the implementation shape can't drift."""

    def test_handle_auth_login_uses_resolve_client_ip(self):
        src = AUTH_PY.read_text()
        idx = src.find("def handle_auth_login")
        window_end = src.find("\ndef ", idx + 50)
        window = src[idx:window_end]
        self.assertIn("resolve_client_ip(handler)", window)
        # The old raw `handler.client_address[0]` read must be gone
        # from this function (still present in other handlers).
        self.assertNotIn("client_ip = handler.client_address[0]", window)

    def test_check_rate_limit_takes_username(self):
        src = AUTH_PY.read_text()
        self.assertIn("def check_rate_limit(ip: str, username: str = ", src)


class TestT8SetupCreateAdminLock(unittest.TestCase):
    """create-admin must wrap the mutation in _setup_lock with a
    double-checked _is_first_run guard."""

    def test_source_pins_lock_and_double_check(self):
        src = SERVE_PY.read_text()
        idx = src.find("def _serve_setup_create_admin")
        self.assertGreater(idx, 0)
        window_end = src.find("\n    def ", idx + 50)
        window = src[idx:window_end]
        # Lock acquire with non-blocking.
        self.assertIn("_setup_lock.acquire(blocking=False)", window)
        # Double-check after acquire.
        self.assertIn("Setup already in progress", window)
        # Release in finally.
        self.assertIn("_setup_lock.release()", window)
        # _is_first_run is checked at least twice in the handler — once
        # as the fast-path reject, once inside the lock.
        self.assertGreaterEqual(
            window.count("if not _is_first_run():"), 2,
            "double-checked locking must re-verify _is_first_run inside the lock",
        )


if __name__ == "__main__":
    unittest.main()
