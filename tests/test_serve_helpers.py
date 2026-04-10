"""Tests for serve.py pure/helper functions — Tier 5A.

Covers:
- _cache_path() — cache file path generation
- _save_disk_cache() / _load_disk_cache() — disk persistence
- _parse_query() — URL query param extraction
- _check_vm_permission() — fleet boundary permission checks
- _check_session_role() — session token + role hierarchy
- FleetBoundaries — categorize, can_action, allowed_actions, is_prod
- Route dispatch table completeness
"""
import json
import importlib
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.core.types import FleetBoundaries


# ── Helpers ──────────────────────────────────────────────────────────

def _mock_handler(path="/api/info?token=abc123"):
    """Create a mock handler with a .path attribute."""
    h = MagicMock()
    h.path = path
    return h


def _mock_cfg(tiers=None, categories=None):
    """Create a mock config with fleet boundaries."""
    if tiers is None:
        tiers = {
            "probe": ["view"],
            "operator": ["view", "start", "stop", "restart"],
            "admin": ["view", "start", "stop", "restart", "destroy", "clone"],
        }
    if categories is None:
        categories = {
            "personal": {"description": "Personal VMs", "tier": "probe", "vmids": [100, 802]},
            "prod_media": {"description": "Production media", "tier": "operator", "vmids": [101, 102, 103]},
            "lab": {"description": "Lab playground", "tier": "admin", "range_start": 5000, "range_end": 5099},
        }
    fb = FleetBoundaries(tiers=tiers, categories=categories)
    cfg = MagicMock()
    cfg.fleet_boundaries = fb
    return cfg


# ═══════════════════════════════════════════════════════════════════
# _cache_path() tests
# ═══════════════════════════════════════════════════════════════════

class TestCachePath(unittest.TestCase):
    """Test cache path generation."""

    def setUp(self):
        from freq.modules.serve import _cache_path, CACHE_DIR
        self.fn = _cache_path
        self.cache_dir = CACHE_DIR

    def test_returns_json_extension(self):
        result = self.fn("health")
        self.assertTrue(result.endswith(".json"))

    def test_includes_name(self):
        result = self.fn("infra_quick")
        self.assertIn("infra_quick", result)

    def test_under_cache_dir(self):
        result = self.fn("test")
        self.assertTrue(result.startswith(self.cache_dir))

    def test_different_names_different_paths(self):
        self.assertNotEqual(self.fn("health"), self.fn("infra_quick"))

    def test_consistent_results(self):
        self.assertEqual(self.fn("health"), self.fn("health"))


# ═══════════════════════════════════════════════════════════════════
# _save_disk_cache() / _load_disk_cache() tests
# ═══════════════════════════════════════════════════════════════════

class TestDiskCache(unittest.TestCase):
    """Test disk cache save/load cycle."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("freq.modules.serve.CACHE_DIR")
    @patch("freq.modules.serve._cache_path")
    def test_save_creates_file(self, mock_path, mock_dir):
        from freq.modules.serve import _save_disk_cache
        fpath = os.path.join(self.tmpdir, "test.json")
        mock_path.return_value = fpath
        mock_dir.__str__ = lambda s: self.tmpdir
        # Patch CACHE_DIR as string for os.makedirs
        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir):
            _save_disk_cache("test", {"foo": "bar"})
        self.assertTrue(os.path.isfile(fpath))

    @patch("freq.modules.serve._cache_path")
    def test_save_writes_valid_json(self, mock_path):
        from freq.modules.serve import _save_disk_cache
        fpath = os.path.join(self.tmpdir, "test.json")
        mock_path.return_value = fpath
        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir):
            _save_disk_cache("test", {"count": 42})
        with open(fpath) as f:
            data = json.load(f)
        self.assertEqual(data["data"]["count"], 42)
        self.assertIn("ts", data)

    @patch("freq.modules.serve._cache_path")
    def test_save_includes_timestamp(self, mock_path):
        from freq.modules.serve import _save_disk_cache
        fpath = os.path.join(self.tmpdir, "test.json")
        mock_path.return_value = fpath
        before = time.time()
        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir):
            _save_disk_cache("test", {})
        with open(fpath) as f:
            data = json.load(f)
        self.assertGreaterEqual(data["ts"], before)

    @patch("freq.modules.serve._cache_path")
    def test_save_handles_write_error(self, mock_path):
        """OSError on file write should be caught (not crash)."""
        from freq.modules.serve import _save_disk_cache
        # Point to a directory (can't open as file for writing)
        mock_path.return_value = self.tmpdir
        with patch("freq.modules.serve.CACHE_DIR", self.tmpdir):
            # Should not raise — OSError on open() is caught
            _save_disk_cache("test", {"a": 1})


# ═══════════════════════════════════════════════════════════════════
# _parse_query() tests
# ═══════════════════════════════════════════════════════════════════

class TestParseQuery(unittest.TestCase):
    """Test URL query parameter parsing."""

    def setUp(self):
        from freq.modules.serve import _parse_query
        self.fn = _parse_query

    def test_single_param(self):
        h = _mock_handler("/api/test?name=foo")
        result = self.fn(h)
        self.assertEqual(result["name"], ["foo"])

    def test_multiple_params(self):
        h = _mock_handler("/api/test?a=1&b=2")
        result = self.fn(h)
        self.assertEqual(result["a"], ["1"])
        self.assertEqual(result["b"], ["2"])

    def test_no_params(self):
        h = _mock_handler("/api/test")
        result = self.fn(h)
        self.assertEqual(result, {})

    def test_empty_query(self):
        h = _mock_handler("/api/test?")
        result = self.fn(h)
        self.assertEqual(result, {})

    def test_repeated_param(self):
        h = _mock_handler("/api/test?x=1&x=2")
        result = self.fn(h)
        self.assertEqual(result["x"], ["1", "2"])

    def test_encoded_value(self):
        h = _mock_handler("/api/test?q=hello%20world")
        result = self.fn(h)
        self.assertEqual(result["q"], ["hello world"])

    def test_token_extraction(self):
        h = _mock_handler("/api/vault?token=abc123")
        result = self.fn(h)
        self.assertEqual(result["token"], ["abc123"])

    def test_missing_key_returns_empty(self):
        h = _mock_handler("/api/test?a=1")
        result = self.fn(h)
        self.assertNotIn("b", result)


# ═══════════════════════════════════════════════════════════════════
# _check_vm_permission() tests
# ═══════════════════════════════════════════════════════════════════

class TestCheckVmPermission(unittest.TestCase):
    """Test fleet boundary permission checks."""

    def setUp(self):
        from freq.modules.serve import _check_vm_permission
        self.fn = _check_vm_permission
        self.cfg = _mock_cfg()

    def test_probe_tier_allows_view(self):
        allowed, msg = self.fn(self.cfg, 100, "view")
        self.assertTrue(allowed)
        self.assertEqual(msg, "")

    def test_probe_tier_blocks_start(self):
        allowed, msg = self.fn(self.cfg, 100, "start")
        self.assertFalse(allowed)
        self.assertIn("blocked", msg.lower())

    def test_probe_tier_blocks_destroy(self):
        allowed, msg = self.fn(self.cfg, 802, "destroy")
        self.assertFalse(allowed)

    def test_operator_tier_allows_start(self):
        allowed, msg = self.fn(self.cfg, 101, "start")
        self.assertTrue(allowed)

    def test_operator_tier_allows_stop(self):
        allowed, msg = self.fn(self.cfg, 102, "stop")
        self.assertTrue(allowed)

    def test_operator_tier_allows_restart(self):
        allowed, msg = self.fn(self.cfg, 103, "restart")
        self.assertTrue(allowed)

    def test_operator_tier_blocks_destroy(self):
        allowed, msg = self.fn(self.cfg, 101, "destroy")
        self.assertFalse(allowed)

    def test_admin_tier_allows_destroy(self):
        allowed, msg = self.fn(self.cfg, 5001, "destroy")
        self.assertTrue(allowed)

    def test_admin_tier_allows_clone(self):
        allowed, msg = self.fn(self.cfg, 5050, "clone")
        self.assertTrue(allowed)

    def test_unknown_vm_gets_probe(self):
        """Unknown VMID falls to probe tier — view only."""
        allowed, _ = self.fn(self.cfg, 9999, "view")
        self.assertTrue(allowed)
        allowed, _ = self.fn(self.cfg, 9999, "start")
        self.assertFalse(allowed)

    def test_range_boundary_start(self):
        allowed, _ = self.fn(self.cfg, 5000, "destroy")
        self.assertTrue(allowed)

    def test_range_boundary_end(self):
        allowed, _ = self.fn(self.cfg, 5099, "destroy")
        self.assertTrue(allowed)

    def test_range_outside(self):
        """VMID just outside admin range falls to probe."""
        allowed, _ = self.fn(self.cfg, 5100, "start")
        self.assertFalse(allowed)

    def test_error_message_includes_vmid(self):
        _, msg = self.fn(self.cfg, 100, "destroy")
        self.assertIn("100", msg)

    def test_error_message_includes_action(self):
        _, msg = self.fn(self.cfg, 100, "destroy")
        self.assertIn("destroy", msg)


# ═══════════════════════════════════════════════════════════════════
# _check_session_role() tests
# ═══════════════════════════════════════════════════════════════════

class TestCheckSessionRole(unittest.TestCase):
    """Test session-based role authorization.

    Auth tokens moved from FreqHandler._auth_tokens to freq.api.auth._auth_tokens
    during the Phase 3.1 refactor.  check_session_role now requires a valid token
    (no-token returns error, not admin).
    """

    def setUp(self):
        import freq.api.auth as auth_mod
        from freq.modules.serve import _check_session_role
        self.fn = _check_session_role
        self.auth_mod = auth_mod
        self._orig_tokens = dict(auth_mod._auth_tokens)
        auth_mod._auth_tokens.clear()

    def tearDown(self):
        self.auth_mod._auth_tokens.clear()
        self.auth_mod._auth_tokens.update(self._orig_tokens)

    def _handler(self, path, token=None):
        """Create a mock handler with proper headers dict for auth checks."""
        h = MagicMock()
        h.path = path
        h.headers = {}  # real dict so .get("Authorization", "") works correctly
        # Extract token from query string for backward compat with tests,
        # but set it as Bearer header (URL token auth was removed for security)
        if token:
            h.headers["Authorization"] = f"Bearer {token}"
        elif "?token=" in path:
            t = path.split("?token=")[1].split("&")[0]
            if t:
                h.headers["Authorization"] = f"Bearer {t}"
        return h

    def test_no_token_requires_auth(self):
        """When no token is provided, auth is required."""
        h = self._handler("/api/test")
        role, err = self.fn(h)
        self.assertIsNone(role)
        self.assertIn("required", err.lower())

    def test_empty_token_requires_auth(self):
        h = self._handler("/api/test?token=")
        role, err = self.fn(h)
        self.assertIsNone(role)
        self.assertIn("required", err.lower())

    def test_invalid_token_returns_error(self):
        h = self._handler("/api/test?token=invalid123")
        role, err = self.fn(h)
        self.assertIsNone(role)
        self.assertIn("expired", err.lower())

    def test_valid_admin_token(self):
        self.auth_mod._auth_tokens["tok1"] = {
            "user": "admin", "role": "admin", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok1")
        role, err = self.fn(h, min_role="admin")
        self.assertEqual(role, "admin")
        self.assertIsNone(err)

    def test_valid_operator_token(self):
        self.auth_mod._auth_tokens["tok2"] = {
            "user": "ops", "role": "operator", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok2")
        role, err = self.fn(h, min_role="operator")
        self.assertEqual(role, "operator")
        self.assertIsNone(err)

    def test_viewer_blocked_from_operator(self):
        self.auth_mod._auth_tokens["tok3"] = {
            "user": "viewer", "role": "viewer", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok3")
        role, err = self.fn(h, min_role="operator")
        self.assertIsNone(role)
        self.assertIn("requires", err.lower())

    def test_operator_blocked_from_admin(self):
        self.auth_mod._auth_tokens["tok4"] = {
            "user": "ops", "role": "operator", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok4")
        role, err = self.fn(h, min_role="admin")
        self.assertIsNone(role)
        self.assertIn("requires", err.lower())

    def test_admin_can_access_viewer(self):
        self.auth_mod._auth_tokens["tok5"] = {
            "user": "admin", "role": "admin", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok5")
        role, err = self.fn(h, min_role="viewer")
        self.assertEqual(role, "admin")

    def test_expired_token(self):
        timeout = self.auth_mod.SESSION_TIMEOUT_SECONDS
        self.auth_mod._auth_tokens["old"] = {
            "user": "admin", "role": "admin",
            "ts": time.time() - timeout - 1
        }
        h = self._handler("/api/test?token=old")
        role, err = self.fn(h)
        self.assertIsNone(role)
        self.assertIn("expired", err.lower())
        # Expired token should be removed
        self.assertNotIn("old", self.auth_mod._auth_tokens)

    def test_default_min_role_is_operator(self):
        self.auth_mod._auth_tokens["tok6"] = {
            "user": "viewer", "role": "viewer", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok6")
        role, err = self.fn(h)  # default min_role="operator"
        self.assertIsNone(role)
        self.assertIn("requires", err.lower())


# ═══════════════════════════════════════════════════════════════════
# FleetBoundaries tests
# ═══════════════════════════════════════════════════════════════════

class TestFleetBoundaries(unittest.TestCase):
    """Test FleetBoundaries categorization and permission logic."""

    def setUp(self):
        self.fb = FleetBoundaries(
            tiers={
                "probe": ["view"],
                "operator": ["view", "start", "stop", "restart"],
                "admin": ["view", "start", "stop", "restart", "destroy", "clone"],
            },
            categories={
                "personal": {"description": "Personal VMs", "tier": "probe", "vmids": [100, 802]},
                "prod_media": {"description": "Production media", "tier": "operator", "vmids": [101, 102, 103]},
                "lab": {"description": "Lab playground", "tier": "admin", "range_start": 5000, "range_end": 5099},
                "infrastructure": {"description": "Infra", "tier": "probe", "vmids": [900]},
            }
        )

    def test_categorize_by_vmid_list(self):
        cat, tier = self.fb.categorize(100)
        self.assertEqual(cat, "personal")
        self.assertEqual(tier, "probe")

    def test_categorize_by_range(self):
        cat, tier = self.fb.categorize(5050)
        self.assertEqual(cat, "lab")
        self.assertEqual(tier, "admin")

    def test_categorize_unknown(self):
        cat, tier = self.fb.categorize(9999)
        self.assertEqual(cat, "unknown")
        self.assertEqual(tier, "probe")

    def test_can_action_allowed(self):
        self.assertTrue(self.fb.can_action(5001, "destroy"))

    def test_can_action_blocked(self):
        self.assertFalse(self.fb.can_action(100, "destroy"))

    def test_allowed_actions_probe(self):
        actions = self.fb.allowed_actions(100)
        self.assertEqual(actions, ["view"])

    def test_allowed_actions_operator(self):
        actions = self.fb.allowed_actions(101)
        self.assertIn("start", actions)
        self.assertIn("stop", actions)
        self.assertNotIn("destroy", actions)

    def test_allowed_actions_admin(self):
        actions = self.fb.allowed_actions(5000)
        self.assertIn("destroy", actions)
        self.assertIn("clone", actions)

    def test_allowed_actions_unknown_falls_to_probe(self):
        actions = self.fb.allowed_actions(7777)
        self.assertEqual(actions, ["view"])

    def test_is_prod_personal(self):
        # Personal VMs are protected but not production
        self.assertFalse(self.fb.is_prod(100))

    def test_is_prod_infrastructure(self):
        self.assertTrue(self.fb.is_prod(900))

    def test_is_prod_lab(self):
        self.assertFalse(self.fb.is_prod(5001))

    def test_is_prod_unknown(self):
        self.assertFalse(self.fb.is_prod(9999))

    def test_is_protected_personal(self):
        self.assertTrue(self.fb.is_protected(100))

    def test_is_protected_infrastructure(self):
        self.assertTrue(self.fb.is_protected(900))

    def test_is_protected_lab(self):
        self.assertFalse(self.fb.is_protected(5001))

    def test_category_description(self):
        desc = self.fb.category_description(100)
        self.assertEqual(desc, "Personal VMs")

    def test_category_description_unknown(self):
        desc = self.fb.category_description(9999)
        self.assertEqual(desc, "Unknown")

    def test_range_boundary_inclusive_start(self):
        cat, _ = self.fb.categorize(5000)
        self.assertEqual(cat, "lab")

    def test_range_boundary_inclusive_end(self):
        cat, _ = self.fb.categorize(5099)
        self.assertEqual(cat, "lab")

    def test_range_boundary_exclusive_after(self):
        cat, _ = self.fb.categorize(5100)
        self.assertEqual(cat, "unknown")

    def test_range_boundary_exclusive_before(self):
        cat, _ = self.fb.categorize(4999)
        self.assertEqual(cat, "unknown")

    def test_empty_boundaries(self):
        fb = FleetBoundaries()
        cat, tier = fb.categorize(100)
        self.assertEqual(cat, "unknown")
        self.assertEqual(tier, "probe")

    def test_empty_tiers_fallback(self):
        fb = FleetBoundaries(tiers={})
        actions = fb.allowed_actions(100)
        self.assertEqual(actions, ["view"])


# ═══════════════════════════════════════════════════════════════════
# Route dispatch table tests
# ═══════════════════════════════════════════════════════════════════

class TestRouteTable(unittest.TestCase):
    """Verify route table integrity and handler existence."""

    def setUp(self):
        from freq.modules.serve import FreqHandler
        self.handler_cls = FreqHandler

    def test_all_routes_have_handlers(self):
        """Every route in _ROUTES must map to an existing method."""
        for path, method_name in self.handler_cls._ROUTES.items():
            self.assertTrue(
                hasattr(self.handler_cls, method_name),
                f"Route {path} maps to {method_name} which does not exist"
            )

    def test_root_route_exists(self):
        self.assertIn("/", self.handler_cls._ROUTES)

    def test_dashboard_route_exists(self):
        self.assertIn("/dashboard", self.handler_cls._ROUTES)

    def test_api_info_route_exists(self):
        from freq.api import build_routes
        v1_routes = build_routes()
        self.assertIn("/api/info", v1_routes)

    def test_api_auth_login_exists(self):
        self.assertIn("/api/auth/login", self.handler_cls._ROUTES)

    def test_api_vault_exists(self):
        from freq.api import build_routes
        v1_routes = build_routes()
        self.assertIn("/api/vault", v1_routes)

    def test_api_fleet_overview_exists(self):
        from freq.api import build_routes
        v1_routes = build_routes()
        self.assertIn("/api/fleet/overview", v1_routes)

    def test_api_media_status_exists(self):
        self.assertIn("/api/media/status", self.handler_cls._ROUTES)

    def test_no_duplicate_handlers(self):
        """No two routes should map to the same handler (catches copy-paste errors)."""
        handlers = list(self.handler_cls._ROUTES.values())
        # Some intentional duplicates are ok (e.g., / and /dashboard both serve app)
        # but check that the majority are unique
        unique = set(handlers)
        # Allow up to 5 intentional duplicates
        self.assertGreater(len(unique), len(handlers) - 5)

    def test_all_api_routes_start_with_slash(self):
        for path in self.handler_cls._ROUTES:
            self.assertTrue(path.startswith("/"), f"Route '{path}' missing leading /")

    def test_build_routes_raises_on_import_error(self):
        from freq.api import build_routes

        orig_import_module = importlib.import_module

        def fake_import_module(name, package=None):
            if name == "freq.api.vm":
                raise ImportError("boom")
            return orig_import_module(name, package)

        with patch("importlib.import_module", side_effect=fake_import_module):
            with self.assertRaises(ImportError):
                build_routes()


# ═══════════════════════════════════════════════════════════════════
# Constants tests
# ═══════════════════════════════════════════════════════════════════

class TestServeConstants(unittest.TestCase):
    """Verify serve.py constants are sane."""

    def test_session_timeout_positive(self):
        import freq.api.auth as auth_mod
        self.assertGreater(auth_mod.SESSION_TIMEOUT_SECONDS, 0)

    def test_session_timeout_reasonable(self):
        import freq.api.auth as auth_mod
        # Should be between 1 hour and 24 hours
        self.assertGreaterEqual(auth_mod.SESSION_TIMEOUT_SECONDS, 3600)
        self.assertLessEqual(auth_mod.SESSION_TIMEOUT_SECONDS, 86400)

    def test_bg_refresh_interval_positive(self):
        from freq.modules.serve import BG_CACHE_REFRESH_INTERVAL
        self.assertGreater(BG_CACHE_REFRESH_INTERVAL, 0)

    def test_dashboard_refresh_ms(self):
        from freq.modules.serve import DASHBOARD_AUTO_REFRESH_MS
        self.assertGreater(DASHBOARD_AUTO_REFRESH_MS, 5000)

    def test_cache_dir_path(self):
        from freq.modules.serve import CACHE_DIR
        self.assertIn("cache", CACHE_DIR)

    def test_default_log_lines(self):
        from freq.modules.serve import DEFAULT_LOG_LINES
        self.assertGreater(DEFAULT_LOG_LINES, 0)
        self.assertLessEqual(DEFAULT_LOG_LINES, 1000)


if __name__ == "__main__":
    unittest.main()
