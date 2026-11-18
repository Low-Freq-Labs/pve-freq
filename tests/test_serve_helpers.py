"""Tests for serve.py pure/helper functions — Tier 5A.

Covers:
- _cache_path() — cache file path generation
- _save_disk_cache() / _load_disk_cache() — disk persistence
- _parse_query() — URL query param extraction
- fleet_policy.check_vm_permission() — fleet boundary permission checks
- _check_session_role() — session token + role hierarchy
- FleetBoundaries — categorize, can_action, allowed_actions, is_prod
- Route dispatch table completeness
"""
import importlib
import inspect
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix  # noqa: E402, I001

from freq.core.types import FleetBoundaries

# ── Helpers ──────────────────────────────────────────────────────────

def _mock_handler(path="/api/info?token=abc123"):
    """Create a mock handler with a .path attribute."""
    h = MagicMock()
    h.path = path
    return h


class TestFleetPolicyContract(unittest.TestCase):
    """Collected owners for fleet categorization and mutation policy."""

    @staticmethod
    def _standard_boundaries():
        return FleetBoundaries(
            tiers={
                "probe": ["view"],
                "operator": ["view", "start", "stop", "restart"],
                "admin": ["view", "start", "stop", "restart", "destroy", "clone"],
            },
            categories={
                "personal": {
                    "description": "Personal VMs",
                    "tier": "probe",
                    "vmids": [100, 802],
                },
                "prod_media": {
                    "description": "Production media",
                    "tier": "operator",
                    "vmids": [101, 102, 103],
                },
                "lab": {
                    "description": "Lab playground",
                    "tier": "admin",
                    "range_start": 5000,
                    "range_end": 5099,
                },
                "infrastructure": {
                    "description": "Infrastructure",
                    "tier": "probe",
                    "vmids": [900],
                },
            },
        )

    def test_categorize_range_and_default_table(self):
        standard = self._standard_boundaries()
        long_range = FleetBoundaries(
            categories={
                "sandbox": {
                    "tier": "admin",
                    "range_start": 5000,
                    "range_end": 5999,
                }
            }
        )
        missing_tier = FleetBoundaries(
            categories={"test": {"vmids": [100], "description": "No tier"}}
        )
        empty = FleetBoundaries()
        cases = (
            ("explicit-vmid-list", standard, 100, ("personal", "probe")),
            ("range-middle", standard, 5050, ("lab", "admin")),
            ("unknown-high-vmid", standard, 99999, ("unknown", "probe")),
            ("zero-vmid", standard, 0, ("unknown", "probe")),
            ("negative-vmid", standard, -1, ("unknown", "probe")),
            ("missing-tier-falls-to-probe", missing_tier, 100, ("test", "probe")),
            ("empty-boundaries", empty, 100, ("unknown", "probe")),
            ("range-start-inclusive", standard, 5000, ("lab", "admin")),
            ("range-end-inclusive", standard, 5099, ("lab", "admin")),
            ("range-before-exclusive", standard, 4999, ("unknown", "probe")),
            ("range-after-exclusive", standard, 5100, ("unknown", "probe")),
            ("long-range-middle", long_range, 5500, ("sandbox", "admin")),
            ("long-range-end", long_range, 5999, ("sandbox", "admin")),
            ("long-range-after", long_range, 6000, ("unknown", "probe")),
        )
        self.assertEqual(len(cases), 14)
        self.assertEqual(len({name for name, *_ in cases}), 14)
        for name, boundaries, vmid, expected in cases:
            with self.subTest(case=name):
                self.assertEqual(boundaries.categorize(vmid), expected)

    def test_actions_classification_and_description_table(self):
        standard = self._standard_boundaries()
        missing_actions = FleetBoundaries(
            tiers={"probe": ["view"]},
            categories={"operator-only": {"tier": "operator", "vmids": [100]}},
        )
        empty = FleetBoundaries()
        custom_probe = FleetBoundaries(tiers={"probe": ["view", "ping"]})
        classifications = FleetBoundaries(
            categories={
                "personal": {"vmids": [100]},
                "infrastructure": {"vmids": [200]},
                "prod_media": {"vmids": [300]},
                "prod_other": {"vmids": [400]},
                "production": {"vmids": [500]},
                "lab": {"vmids": [600]},
            }
        )
        cases = (
            ("probe-actions", standard, "allowed_actions", (100,), ["view"]),
            (
                "operator-actions",
                standard,
                "allowed_actions",
                (101,),
                ["view", "start", "stop", "restart"],
            ),
            (
                "admin-actions",
                standard,
                "allowed_actions",
                (5000,),
                ["view", "start", "stop", "restart", "destroy", "clone"],
            ),
            ("unknown-actions", standard, "allowed_actions", (7777,), ["view"]),
            (
                "missing-tier-actions",
                missing_actions,
                "allowed_actions",
                (100,),
                ["view"],
            ),
            ("empty-tier-actions", empty, "allowed_actions", (100,), ["view"]),
            (
                "empty-categories-custom-probe",
                custom_probe,
                "allowed_actions",
                (500,),
                ["view", "ping"],
            ),
            ("can-destroy-admin", standard, "can_action", (5001, "destroy"), True),
            ("cannot-destroy-probe", standard, "can_action", (100, "destroy"), False),
            ("personal-flags", classifications, "flags", (100,), (False, True)),
            ("infrastructure-flags", classifications, "flags", (200,), (True, True)),
            ("prod-media-flags", classifications, "flags", (300,), (True, True)),
            ("prod-other-flags", classifications, "flags", (400,), (True, True)),
            ("production-flags", classifications, "flags", (500,), (True, True)),
            ("lab-flags", classifications, "flags", (600,), (False, False)),
            ("unknown-flags", classifications, "flags", (999,), (False, False)),
            (
                "known-description",
                standard,
                "category_description",
                (100,),
                "Personal VMs",
            ),
            (
                "unknown-description",
                standard,
                "category_description",
                (9999,),
                "Unknown",
            ),
        )
        self.assertEqual(len(cases), 18)
        self.assertEqual(len({name for name, *_ in cases}), 18)
        for name, boundaries, operation, args, expected in cases:
            with self.subTest(case=name):
                if operation == "flags":
                    actual = (boundaries.is_prod(*args), boundaries.is_protected(*args))
                else:
                    actual = getattr(boundaries, operation)(*args)
                self.assertEqual(actual, expected)

    def test_permission_service_and_consumer_identity_table(self):
        from freq.api import dr, vm
        from freq.services.fleet_policy import check_vm_permission

        cfg = SimpleNamespace(fleet_boundaries=self._standard_boundaries())
        cases = (
            ("probe-view", 100, "view", True, ""),
            ("probe-start", 100, "start", False, "Action 'start' blocked on VMID 100 (personal/probe)"),
            ("probe-destroy", 802, "destroy", False, "Action 'destroy' blocked on VMID 802 (personal/probe)"),
            ("operator-start", 101, "start", True, ""),
            ("operator-stop", 102, "stop", True, ""),
            ("operator-restart", 103, "restart", True, ""),
            ("operator-destroy", 101, "destroy", False, "Action 'destroy' blocked on VMID 101 (prod_media/operator)"),
            ("admin-destroy", 5001, "destroy", True, ""),
            ("admin-clone", 5050, "clone", True, ""),
            ("unknown-view", 9999, "view", True, ""),
            ("unknown-start", 9999, "start", False, "Action 'start' blocked on VMID 9999 (unknown/probe)"),
            ("range-start", 5000, "destroy", True, ""),
            ("range-end", 5099, "destroy", True, ""),
            ("range-outside", 5100, "start", False, "Action 'start' blocked on VMID 5100 (unknown/probe)"),
        )
        self.assertEqual(len(cases), 14)
        self.assertEqual(len({name for name, *_ in cases}), 14)
        for name, vmid, action, allowed, message in cases:
            with self.subTest(case=name):
                self.assertEqual(check_vm_permission(cfg, vmid, action), (allowed, message))
        self.assertIs(vm._check_vm_permission, check_vm_permission)
        self.assertIs(dr._check_vm_permission, check_vm_permission)

    def test_loaded_config_structural_contract(self):
        from freq.core.config import load_config, load_fleet_boundaries

        current = load_config().fleet_boundaries
        self.assertIsInstance(current, FleetBoundaries)
        for tier, actions in current.tiers.items():
            with self.subTest(current_tier=tier):
                self.assertIsInstance(tier, str)
                self.assertIsInstance(actions, list)
                self.assertTrue(all(isinstance(action, str) for action in actions))
        for name, category in current.categories.items():
            with self.subTest(current_category=name):
                self.assertIn("description", category)
                self.assertIn("tier", category)
        for name, device in current.physical.items():
            with self.subTest(current_physical=name):
                self.assertTrue(device.ip)
        for name, node in current.pve_nodes.items():
            with self.subTest(current_pve_node=name):
                self.assertTrue(node.ip)
        for vmid in (100, 500, 900, 5000, 99999):
            with self.subTest(current_vmid=vmid):
                category, tier = current.categorize(vmid)
                self.assertIsInstance(category, str)
                self.assertIsInstance(tier, str)
                self.assertIsInstance(current.allowed_actions(vmid), list)

        with tempfile.TemporaryDirectory(prefix="freq-fleet-policy-") as tmp:
            path = Path(tmp) / "fleet-boundaries.toml"
            path.write_text(
                "\n".join(
                    (
                        "[tiers]",
                        'probe = ["view"]',
                        'operator = ["view", "start"]',
                        "",
                        "[categories.production]",
                        'description = "Production"',
                        'tier = "operator"',
                        "vmids = [200]",
                        "",
                        "[physical.storage]",
                        'ip = "192.0.2.20"',
                        'label = "storage"',
                        'type = "truenas"',
                        "",
                        "[pve_nodes.pve01]",
                        'ip = "192.0.2.26"',
                        'detail = "Primary"',
                    )
                )
            )
            loaded = load_fleet_boundaries(str(path))

        self.assertEqual(loaded.categorize(200), ("production", "operator"))
        self.assertEqual(loaded.allowed_actions(200), ["view", "start"])
        self.assertEqual(loaded.categories["production"]["description"], "Production")
        self.assertEqual(loaded.physical["storage"].ip, "192.0.2.20")
        self.assertEqual(loaded.pve_nodes["pve01"].ip, "192.0.2.26")


# ═══════════════════════════════════════════════════════════════════
# _cache_path() tests
# ═══════════════════════════════════════════════════════════════════

class TestCachePath(unittest.TestCase):
    """Test cache path generation."""

    def setUp(self):
        from freq.modules.serve import CACHE_DIR, _cache_path
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

    def _case_single_param(self):
        h = _mock_handler("/api/test?name=foo")
        result = self.fn(h)
        self.assertEqual(result["name"], ["foo"])

    def _case_multiple_params(self):
        h = _mock_handler("/api/test?a=1&b=2")
        result = self.fn(h)
        self.assertEqual(result["a"], ["1"])
        self.assertEqual(result["b"], ["2"])

    def _case_no_params(self):
        h = _mock_handler("/api/test")
        result = self.fn(h)
        self.assertEqual(result, {})

    def _case_empty_query(self):
        h = _mock_handler("/api/test?")
        result = self.fn(h)
        self.assertEqual(result, {})

    def _case_repeated_param(self):
        h = _mock_handler("/api/test?x=1&x=2")
        result = self.fn(h)
        self.assertEqual(result["x"], ["1", "2"])

    def _case_encoded_value(self):
        h = _mock_handler("/api/test?q=hello%20world")
        result = self.fn(h)
        self.assertEqual(result["q"], ["hello world"])

    def _case_token_extraction(self):
        h = _mock_handler("/api/test?token=abc123")
        result = self.fn(h)
        self.assertEqual(result["token"], ["abc123"])

    def _case_missing_key_returns_empty(self):
        h = _mock_handler("/api/test?a=1")
        result = self.fn(h)
        self.assertNotIn("b", result)


PARSE_QUERY_CASES = (
    "_case_single_param",
    "_case_multiple_params",
    "_case_no_params",
    "_case_empty_query",
    "_case_repeated_param",
    "_case_encoded_value",
    "_case_token_extraction",
    "_case_missing_key_returns_empty",
)


class TestParseQueryMatrix(unittest.TestCase):
    def test_parse_query_matrix(self):
        run_case_matrix(self, TestParseQuery, PARSE_QUERY_CASES)


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

    def _case_no_token_requires_auth(self):
        """When no token is provided, auth is required."""
        h = self._handler("/api/test")
        role, err = self.fn(h)
        self.assertIsNone(role)
        self.assertIn("required", err.lower())

    def _case_empty_token_requires_auth(self):
        h = self._handler("/api/test?token=")
        role, err = self.fn(h)
        self.assertIsNone(role)
        self.assertIn("required", err.lower())

    def _case_invalid_token_returns_error(self):
        h = self._handler("/api/test?token=invalid123")
        role, err = self.fn(h)
        self.assertIsNone(role)
        self.assertIn("expired", err.lower())

    def _case_valid_admin_token(self):
        self.auth_mod._auth_tokens["tok1"] = {
            "user": "admin", "role": "admin", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok1")
        role, err = self.fn(h, min_role="admin")
        self.assertEqual(role, "admin")
        self.assertIsNone(err)

    def _case_valid_operator_token(self):
        self.auth_mod._auth_tokens["tok2"] = {
            "user": "ops", "role": "operator", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok2")
        role, err = self.fn(h, min_role="operator")
        self.assertEqual(role, "operator")
        self.assertIsNone(err)

    def _case_viewer_blocked_from_operator(self):
        self.auth_mod._auth_tokens["tok3"] = {
            "user": "viewer", "role": "viewer", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok3")
        role, err = self.fn(h, min_role="operator")
        self.assertIsNone(role)
        self.assertIn("requires", err.lower())

    def _case_operator_blocked_from_admin(self):
        self.auth_mod._auth_tokens["tok4"] = {
            "user": "ops", "role": "operator", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok4")
        role, err = self.fn(h, min_role="admin")
        self.assertIsNone(role)
        self.assertIn("requires", err.lower())

    def _case_admin_can_access_viewer(self):
        self.auth_mod._auth_tokens["tok5"] = {
            "user": "admin", "role": "admin", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok5")
        role, err = self.fn(h, min_role="viewer")
        self.assertEqual(role, "admin")

    def _case_expired_token(self):
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

    def _case_default_min_role_is_operator(self):
        self.auth_mod._auth_tokens["tok6"] = {
            "user": "viewer", "role": "viewer", "ts": time.time()
        }
        h = self._handler("/api/test?token=tok6")
        role, err = self.fn(h)  # default min_role="operator"
        self.assertIsNone(role)
        self.assertIn("requires", err.lower())


SESSION_ROLE_CASES = (
    "_case_no_token_requires_auth",
    "_case_empty_token_requires_auth",
    "_case_invalid_token_returns_error",
    "_case_valid_admin_token",
    "_case_valid_operator_token",
    "_case_viewer_blocked_from_operator",
    "_case_operator_blocked_from_admin",
    "_case_admin_can_access_viewer",
    "_case_expired_token",
    "_case_default_min_role_is_operator",
)


class TestCheckSessionRoleMatrix(unittest.TestCase):
    def test_session_role_matrix(self):
        run_case_matrix(self, TestCheckSessionRole, SESSION_ROLE_CASES)


# ═══════════════════════════════════════════════════════════════════
# Route dispatch table tests
# ═══════════════════════════════════════════════════════════════════

class TestRouteTable(unittest.TestCase):
    """Verify route table integrity and handler existence."""

    def setUp(self):
        from freq.modules.serve import FreqHandler
        self.handler_cls = FreqHandler

    def _case_all_routes_have_handlers(self):
        """Every route in _ROUTES must map to an existing method."""
        for path, method_name in self.handler_cls._ROUTES.items():
            self.assertTrue(
                hasattr(self.handler_cls, method_name),
                f"Route {path} maps to {method_name} which does not exist"
            )

    def _case_root_route_exists(self):
        self.assertIn("/", self.handler_cls._ROUTES)

    def _case_dashboard_route_exists(self):
        self.assertIn("/dashboard", self.handler_cls._ROUTES)

    def _case_api_info_route_exists(self):
        from freq.api import build_routes
        v1_routes = build_routes()
        self.assertIn("/api/info", v1_routes)

    def _case_api_auth_login_exists(self):
        self.assertIn("/api/auth/login", self.handler_cls._ROUTES)

    def _case_api_vault_exists(self):
        from freq.api import build_routes
        v1_routes = build_routes()
        self.assertIn("/api/vault/credentials", v1_routes)
        self.assertNotIn("/api/vault", v1_routes)

    def _case_api_fleet_overview_exists(self):
        from freq.api import build_routes
        v1_routes = build_routes()
        self.assertIn("/api/fleet/overview", v1_routes)

    def _case_network_switches_route_uses_real_network_handler(self):
        from freq.api import build_routes, net, v1_stubs

        v1_routes = build_routes()
        self.assertIs(v1_routes.get("/api/v1/net/switches"), net.handle_switches)
        self.assertFalse(hasattr(v1_stubs, "handle_net_switches"))

    def _case_api_media_status_exists(self):
        self.assertIn("/api/media/status", self.handler_cls._ROUTES)

    def _case_no_duplicate_handlers(self):
        """No two routes should map to the same handler (catches copy-paste errors)."""
        handlers = list(self.handler_cls._ROUTES.values())
        # Some intentional duplicates are ok (e.g., / and /dashboard both serve app)
        # but check that the majority are unique
        unique = set(handlers)
        # Allow up to 5 intentional duplicates
        self.assertGreater(len(unique), len(handlers) - 5)

    def _case_all_api_routes_start_with_slash(self):
        for path in self.handler_cls._ROUTES:
            self.assertTrue(path.startswith("/"), f"Route '{path}' missing leading /")

    def _case_build_routes_raises_on_import_error(self):
        from freq.api import build_routes

        orig_import_module = importlib.import_module

        def fake_import_module(name, package=None):
            if name == "freq.api.vm":
                raise ImportError("boom")
            return orig_import_module(name, package)

        with patch("importlib.import_module", side_effect=fake_import_module):
            with self.assertRaises(ImportError):
                build_routes()

    def _case_local_and_domain_route_sources_are_disjoint(self):
        """A future unified registry must never resolve a path by precedence."""
        from freq.api import build_routes

        domain_routes = build_routes()
        overlap = sorted(set(self.handler_cls._ROUTES) & set(domain_routes))

        self.assertEqual(overlap, [], f"Route sources collide: {overlap}")
        self.assertEqual(
            len(set(self.handler_cls._ROUTES) | set(domain_routes)),
            len(self.handler_cls._ROUTES) + len(domain_routes),
        )

    def _case_domain_route_build_is_deterministic(self):
        """Repeated registry builds must preserve every path and handler identity."""
        from freq.api import build_routes

        first = build_routes()
        second = build_routes()

        self.assertEqual(tuple(first), tuple(second))
        self.assertEqual(set(first), set(second))
        for path in first:
            self.assertIs(first[path], second[path], path)

    def _case_combined_registry_matches_exact_source_union(self):
        from freq.api import build_route_registry, build_routes

        domain_routes = build_routes()
        registry = build_route_registry(self.handler_cls._ROUTES)

        self.assertEqual(
            tuple(registry),
            tuple(self.handler_cls._ROUTES) + tuple(domain_routes),
        )
        for path, handler in self.handler_cls._ROUTES.items():
            self.assertEqual(registry[path], handler)
        for path, handler in domain_routes.items():
            self.assertIs(registry[path], handler)

    def _case_combined_registry_rejects_every_collision(self):
        from freq.api import RouteRegistrationError, build_route_registry

        with self.assertRaisesRegex(RouteRegistrationError, "/api/vms"):
            build_route_registry({"/api/vms": "_serve_app"})

    def _case_standard_mapping_mutations_cannot_shadow_routes(self):
        from freq.api import RouteRegistrationError, build_route_registry

        path = "/api/auth/login"
        replacement = object()

        def assign(routes):
            routes[path] = replacement

        def update(routes):
            routes.update({path: replacement})

        def in_place_union(routes):
            routes |= {path: replacement}

        def set_default(routes):
            routes.setdefault(path, replacement)

        def delete(routes):
            del routes[path]

        def pop(routes):
            routes.pop(path)

        def pop_item(routes):
            routes.popitem()

        def clear(routes):
            routes.clear()

        for name, register in (
            ("assignment", assign),
            ("update", update),
            ("ior", in_place_union),
            ("setdefault", set_default),
            ("delete", delete),
            ("pop", pop),
            ("popitem", pop_item),
            ("clear", clear),
        ):
            module = SimpleNamespace(register=register)
            with self.subTest(mutation=name):
                with (
                    patch("freq.api._DOMAIN_MODULES", ("freq.api.synthetic",)),
                    patch("importlib.import_module", return_value=module),
                ):
                    with self.assertRaises(RouteRegistrationError):
                        build_route_registry({path: "_serve_auth_login"})

    def _case_update_collision_leaves_runtime_cache_unset(self):
        from freq.api import RouteRegistrationError

        cls = self.handler_cls
        original = cls._ROUTE_REGISTRY
        path = "/api/auth/login"

        def register(routes):
            routes.update({path: object()})

        cls._ROUTE_REGISTRY = None
        try:
            module = SimpleNamespace(register=register)
            with (
                patch("freq.api._DOMAIN_MODULES", ("freq.api.synthetic",)),
                patch("importlib.import_module", return_value=module),
            ):
                with self.assertRaises(RouteRegistrationError):
                    cls._load_routes()
            self.assertIsNone(cls._ROUTE_REGISTRY)
        finally:
            cls._ROUTE_REGISTRY = original

    def _case_failed_registry_load_is_atomic(self):
        cls = self.handler_cls
        original = cls._ROUTE_REGISTRY
        cls._ROUTE_REGISTRY = None
        try:
            with patch("freq.api.build_route_registry", side_effect=RuntimeError("broken registry")):
                with self.assertRaisesRegex(RuntimeError, "broken registry"):
                    cls._load_routes()
            self.assertIsNone(cls._ROUTE_REGISTRY)
        finally:
            cls._ROUTE_REGISTRY = original

    def _case_dispatch_and_docs_share_one_registry(self):
        cls = self.handler_cls
        registry = cls._load_routes()
        handler = object.__new__(cls)

        self.assertEqual(handler._documented_routes(), registry)
        self.assertFalse(hasattr(cls, "_V1_ROUTES"))
        dispatch_src = inspect.getsource(cls._dispatch)
        self.assertIn("self._load_routes().get(path)", dispatch_src)
        self.assertNotIn("_V1_ROUTES", dispatch_src)
        self.assertNotIn("self._ROUTES.get(path)", dispatch_src)

    def _case_serve_startup_fails_before_side_effects(self):
        from freq.modules.serve import cmd_serve

        cfg = SimpleNamespace(dashboard_port=8888)
        args = SimpleNamespace(port=None)
        with (
            patch.object(self.handler_cls, "_load_routes", side_effect=RuntimeError("broken registry")),
            patch("freq.modules.serve.start_background_cache") as start_cache,
            patch("freq.modules.serve._start_embedded_watchdog_if_needed") as start_watchdog,
            patch("freq.modules.serve._start_cert_renewal_scheduler_if_needed") as start_cert,
            patch("freq.modules.serve.ThreadedHTTPServer") as server,
        ):
            self.assertEqual(cmd_serve(cfg, None, args), 1)

        start_cache.assert_not_called()
        start_watchdog.assert_not_called()
        start_cert.assert_not_called()
        server.assert_not_called()

    def _case_managed_cert_renewal_scheduler_contract_is_exact(self):
        from freq.modules import serve
        from freq.services import cert_renewal

        self.assertIs(
            serve._start_cert_renewal_scheduler_if_needed,
            cert_renewal.start_cert_renewal_scheduler_if_needed,
        )
        self.assertFalse(hasattr(serve, "_managed_cert_renewal_enabled"))

        cfg = SimpleNamespace(
            dashboard_port=8888,
            tls_cert="",
            tls_key="",
        )
        server = MagicMock()
        with patch.object(
            serve.FreqHandler,
            "_load_routes",
        ), patch.object(
            serve,
            "start_background_cache",
        ), patch.object(
            serve,
            "_start_embedded_watchdog_if_needed",
        ), patch.object(
            serve,
            "_start_cert_renewal_scheduler_if_needed",
        ) as start_renewal, patch.object(
            serve,
            "ThreadedHTTPServer",
            return_value=server,
        ), patch(
            "signal.signal",
        ), patch(
            "freq.modules.users._load_users",
            return_value=[],
        ), patch.object(
            serve,
            "_setup_marker_exists",
            return_value=False,
        ), patch.object(
            serve,
            "prepare_first_admin_claim",
            return_value={"state": "available", "claim_id": "fixture-claim-id"},
        ), patch.object(
            serve,
            "_cleanup_ssh_mux",
        ):
            self.assertEqual(
                serve.cmd_serve(cfg, None, SimpleNamespace(port=None)),
                0,
            )

        start_renewal.assert_called_once_with(cfg, serve._shutdown_flag)
        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()

        managed = {
            "base_domain": "example.test",
            "dns_provider": "cloudflare",
            "dns_token_path": "/run/freq/cloudflare-token",
        }
        eligibility = (
            ("absent", None, False),
            ("wrong-type", ["managed"], False),
            ("adopted", {**managed, "management_mode": " adopted_EXISTING "}, False),
            ("external", {**managed, "renewal_owner": " EXTERNAL "}, False),
            ("missing-domain", {**managed, "base_domain": ""}, False),
            ("missing-provider", {**managed, "dns_provider": ""}, False),
            ("missing-token", {**managed, "dns_token_path": ""}, False),
            ("managed", managed, True),
        )
        for name, certificates, expected in eligibility:
            with self.subTest(contract="eligibility", case=name):
                cfg = SimpleNamespace(certificates=certificates)
                self.assertIs(
                    cert_renewal.managed_cert_renewal_enabled(cfg),
                    expected,
                )

        with patch("freq.services.cert_renewal.threading.Thread") as thread_ctor:
            cert_renewal.start_cert_renewal_scheduler_if_needed(
                SimpleNamespace(certificates=None),
                MagicMock(),
            )
        thread_ctor.assert_not_called()

        class OneIterationShutdown:
            def __init__(self):
                self.checks = 0
                self.waits = []

            def reset(self):
                self.checks = 0
                self.waits = []

            def is_set(self):
                self.checks += 1
                return self.checks > 1

            def wait(self, timeout):
                self.waits.append(timeout)

        def run_iteration(target, run_mock):
            shutdown.reset()
            with patch(
                "freq.services.cert_renewal.time.sleep"
            ) as initial_sleep, patch(
                "freq.services.cert_renewal.time.strftime",
                return_value="2026-07-19T23:00:00-0500",
            ), patch(
                "freq.services.cert_renewal.subprocess.run",
                run_mock,
            ):
                target()
            initial_sleep.assert_called_once_with(300)
            self.assertEqual(shutdown.waits, [3600])

        with tempfile.TemporaryDirectory(
            prefix="freq-cert-renewal-owner-"
        ) as root:
            cfg = SimpleNamespace(data_dir=root, certificates=managed)
            shutdown = OneIterationShutdown()
            thread = MagicMock()
            with patch(
                "freq.services.cert_renewal.threading.Thread",
                return_value=thread,
            ) as thread_ctor:
                cert_renewal.start_cert_renewal_scheduler_if_needed(
                    cfg,
                    shutdown,
                )

            thread_ctor.assert_called_once()
            thread_args = thread_ctor.call_args
            self.assertEqual(thread_args.args, ())
            self.assertEqual(thread_args.kwargs["name"], "freq-cert-renewal")
            self.assertIs(thread_args.kwargs["daemon"], True)
            target = thread_args.kwargs["target"]
            self.assertTrue(callable(target))
            thread.start.assert_called_once_with()

            success = MagicMock(
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout="s" * 2100,
                    stderr="e" * 2100,
                )
            )
            run_iteration(target, success)
            success.assert_called_once_with(
                [
                    sys.executable,
                    "-m",
                    "freq",
                    "--yes",
                    "cert",
                    "renew",
                    "--deploy",
                ],
                stdin=cert_renewal.subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=1800,
            )

            state_dir = os.path.join(root, "certs")
            state_path = os.path.join(state_dir, "renewal-scheduler.json")
            self.assertEqual(os.stat(state_dir).st_mode & 0o777, 0o700)
            with open(state_path) as state_file:
                state = json.load(state_file)
            self.assertEqual(
                state,
                {
                    "last_attempt_day": cert_renewal.datetime.date.today().isoformat(),
                    "last_attempt_at": "2026-07-19T23:00:00-0500",
                    "last_returncode": 0,
                    "last_stdout_tail": "s" * 2000,
                    "last_stderr_tail": "e" * 2000,
                },
            )

            run_iteration(target, success)
            success.assert_called_once()

            with open(state_path, "w") as state_file:
                state_file.write("{")
            run_iteration(target, success)
            self.assertEqual(success.call_count, 2)

            with open(state_path, "w") as state_file:
                json.dump({"last_attempt_day": "1900-01-01"}, state_file)
            nonzero = MagicMock(
                return_value=SimpleNamespace(
                    returncode=7,
                    stdout="not renewed",
                    stderr="renew failed",
                )
            )
            run_iteration(target, nonzero)
            with open(state_path) as state_file:
                state = json.load(state_file)
            self.assertEqual(state["last_returncode"], 7)
            self.assertEqual(state["last_stdout_tail"], "not renewed")
            self.assertEqual(state["last_stderr_tail"], "renew failed")

            with open(state_path, "w") as state_file:
                json.dump({"last_attempt_day": "1900-01-01"}, state_file)
            unavailable = OSError("renew command unavailable")
            failed = MagicMock(side_effect=unavailable)
            run_iteration(target, failed)
            with open(state_path) as state_file:
                state = json.load(state_file)
            self.assertEqual(
                state,
                {
                    "last_attempt_day": cert_renewal.datetime.date.today().isoformat(),
                    "last_attempt_at": "2026-07-19T23:00:00-0500",
                    "last_returncode": -1,
                    "last_error": "renew command unavailable",
                },
            )


# ═══════════════════════════════════════════════════════════════════
# Constants tests
# ═══════════════════════════════════════════════════════════════════

ROUTE_TABLE_CASES = (
    "_case_all_routes_have_handlers",
    "_case_root_route_exists",
    "_case_dashboard_route_exists",
    "_case_api_info_route_exists",
    "_case_api_auth_login_exists",
    "_case_api_vault_exists",
    "_case_api_fleet_overview_exists",
    "_case_network_switches_route_uses_real_network_handler",
    "_case_api_media_status_exists",
    "_case_no_duplicate_handlers",
    "_case_all_api_routes_start_with_slash",
    "_case_build_routes_raises_on_import_error",
    "_case_local_and_domain_route_sources_are_disjoint",
    "_case_domain_route_build_is_deterministic",
    "_case_combined_registry_matches_exact_source_union",
    "_case_combined_registry_rejects_every_collision",
    "_case_standard_mapping_mutations_cannot_shadow_routes",
    "_case_update_collision_leaves_runtime_cache_unset",
    "_case_failed_registry_load_is_atomic",
    "_case_dispatch_and_docs_share_one_registry",
    "_case_serve_startup_fails_before_side_effects",
    "_case_managed_cert_renewal_scheduler_contract_is_exact",
)


class TestRouteTableMatrix(unittest.TestCase):
    def test_route_table_matrix(self):
        self.assertEqual(len(ROUTE_TABLE_CASES), 22)
        run_case_matrix(self, TestRouteTable, ROUTE_TABLE_CASES)

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
