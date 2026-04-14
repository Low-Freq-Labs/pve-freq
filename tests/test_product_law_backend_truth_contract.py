"""R-PRODUCT-LAW-BACKEND-TRUTH regression contract.

Translation of pve-freq-product-law.md into enforceable tests:

  - probes must encode expected state, not only current state
  - health/recovery contracts must distinguish:
      live / stale / degraded / auth_failed / unreachable / recovering
  - remediation paths must capture evidence before acting
  - no boolean-only "healthy" abstractions where reason/timestamp/
    last-success are required

Pin the six-state contract on every probe return path in:
  - freq/core/health_state.py (the shared classifier)
  - freq/modules/serve.py _bg_probe_health (background probe)
  - freq/api/fleet.py handle_health_api fallback (cold-cache path)
  - circuit breaker engage / reset must write audit.jsonl evidence

The frontend-compat alias (`status = "healthy"|"unreachable"`) must
remain set alongside the new `state` field so Morty's ~20 app.js
`h.status === 'healthy'` checks keep working.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
SERVE_PY = REPO / "freq" / "modules" / "serve.py"
FLEET_API_PY = REPO / "freq" / "api" / "fleet.py"
HEALTH_STATE_PY = REPO / "freq" / "core" / "health_state.py"


class TestHealthStateModuleExists(unittest.TestCase):
    """Shared classifier module must define the six canonical states
    plus the helpers that callers use to build entries."""

    def test_six_states_defined(self):
        from freq.core import health_state as hs
        self.assertEqual(hs.STATE_LIVE, "live")
        self.assertEqual(hs.STATE_STALE, "stale")
        self.assertEqual(hs.STATE_DEGRADED, "degraded")
        self.assertEqual(hs.STATE_AUTH_FAILED, "auth_failed")
        self.assertEqual(hs.STATE_UNREACHABLE, "unreachable")
        self.assertEqual(hs.STATE_RECOVERING, "recovering")
        self.assertEqual(
            hs.ALL_STATES,
            frozenset({"live", "stale", "degraded",
                       "auth_failed", "unreachable", "recovering"}),
        )

    def test_legacy_status_for_mapping(self):
        from freq.core import health_state as hs
        # live + recovering = 'healthy' (frontend compat)
        self.assertEqual(hs.legacy_status_for("live"), "healthy")
        self.assertEqual(hs.legacy_status_for("recovering"), "healthy")
        # Everything else collapses to 'unreachable' in the legacy alias
        # so the frontend does not paint stale/degraded/auth_failed as up.
        self.assertEqual(hs.legacy_status_for("stale"), "unreachable")
        self.assertEqual(hs.legacy_status_for("degraded"), "unreachable")
        self.assertEqual(hs.legacy_status_for("auth_failed"), "unreachable")
        self.assertEqual(hs.legacy_status_for("unreachable"), "unreachable")


class TestClassifyProbeFailure(unittest.TestCase):
    """classify_probe_failure must map real-world ssh failure strings to
    the correct six-state token + an operator-readable reason."""

    def test_timeout_kill_is_unreachable(self):
        from freq.core.health_state import classify_probe_failure
        state, reason = classify_probe_failure(124, "command timed out after 10s", "")
        self.assertEqual(state, "unreachable")
        self.assertIn("timed out", reason.lower())

    def test_permission_denied_is_auth_failed(self):
        from freq.core.health_state import classify_probe_failure
        state, reason = classify_probe_failure(
            255, "Permission denied (publickey).\r\n", ""
        )
        self.assertEqual(state, "auth_failed")
        self.assertIn("auth", reason.lower())

    def test_publickey_only_is_auth_failed(self):
        from freq.core.health_state import classify_probe_failure
        state, _ = classify_probe_failure(255, "publickey\n", "")
        self.assertEqual(state, "auth_failed")

    def test_connection_refused_is_unreachable(self):
        from freq.core.health_state import classify_probe_failure
        state, reason = classify_probe_failure(
            255, "ssh: connect to host 10.0.0.9 port 22: Connection refused", ""
        )
        self.assertEqual(state, "unreachable")
        self.assertIn("unreachable", reason.lower())

    def test_no_route_is_unreachable(self):
        from freq.core.health_state import classify_probe_failure
        state, _ = classify_probe_failure(
            255, "ssh: connect to host 10.0.0.9 port 22: No route to host", ""
        )
        self.assertEqual(state, "unreachable")

    def test_banner_exchange_is_unreachable(self):
        from freq.core.health_state import classify_probe_failure
        state, _ = classify_probe_failure(
            255, "kex_exchange_identification: Connection timed out during banner exchange", ""
        )
        self.assertEqual(state, "unreachable")

    def test_exit_nonzero_empty_output_is_degraded(self):
        from freq.core.health_state import classify_probe_failure
        state, reason = classify_probe_failure(1, "bash: racadm: command not found", "")
        self.assertEqual(state, "degraded")
        self.assertIn("no output", reason.lower())


class TestEntryBase(unittest.TestCase):
    """entry_base must always emit the operator-required fields: state,
    reason, probed_at, last_success_at, failure_count, plus the legacy
    status alias."""

    def _fake_host(self):
        class H:
            label = "pve01"
            ip = "10.25.255.26"
            htype = "pve"
        return H()

    def test_live_entry_has_all_fields(self):
        from freq.core.health_state import entry_base
        now = time.time()
        e = entry_base(self._fake_host(), state="live", reason="probe OK",
                       probed_at=now, last_success_at=now, failure_count=0)
        self.assertEqual(e["state"], "live")
        self.assertEqual(e["status"], "healthy")  # legacy alias
        self.assertEqual(e["reason"], "probe OK")
        self.assertEqual(e["probed_at"], now)
        self.assertEqual(e["last_success_at"], now)
        self.assertEqual(e["failure_count"], 0)

    def test_auth_failed_entry_is_legacy_unreachable(self):
        from freq.core.health_state import entry_base
        e = entry_base(self._fake_host(), state="auth_failed",
                       reason="publickey rejected", probed_at=time.time())
        self.assertEqual(e["state"], "auth_failed")
        self.assertEqual(e["status"], "unreachable")
        self.assertEqual(e["reason"], "publickey rejected")
        # Stores None when we have no prior success on record.
        self.assertIsNone(e["last_success_at"])

    def test_invalid_state_raises(self):
        """A bogus state must crash the probe at the source instead of
        silently leaking to the dashboard."""
        from freq.core.health_state import entry_base
        with self.assertRaises(ValueError):
            entry_base(self._fake_host(), state="bogus",
                       reason="x", probed_at=time.time())


class TestMarkStale(unittest.TestCase):
    """mark_stale must flip a cached entry to state='stale' + attach
    age_seconds, but preserve the metrics so the dashboard still has
    something to show."""

    def test_flips_state_and_legacy_status(self):
        from freq.core.health_state import mark_stale
        now = time.time()
        cached = {
            "label": "pve02", "ip": "10.25.255.27", "type": "pve",
            "state": "live", "status": "healthy",
            "reason": "probe OK",
            "probed_at": now - 300,
            "cores": "8", "ram": "16/32GB", "disk": "42%",
            "load": "0.05", "docker": "0",
        }
        stale = mark_stale(cached, now, "circuit breaker backoff (120s remaining)")
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["status"], "unreachable")
        self.assertIn("circuit breaker", stale["reason"])
        self.assertGreaterEqual(stale["age_seconds"], 299)
        self.assertLessEqual(stale["age_seconds"], 301)
        # Metrics preserved so the UI still shows something.
        self.assertEqual(stale["cores"], "8")
        self.assertEqual(stale["ram"], "16/32GB")

    def test_handles_missing_probed_at_gracefully(self):
        from freq.core.health_state import mark_stale
        cached = {"label": "x", "ip": "10.0.0.1", "type": "linux",
                  "state": "live", "status": "healthy"}
        stale = mark_stale(cached, time.time(), "cache without probed_at")
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["age_seconds"], 0.0)


class TestAggregateProbeState(unittest.TestCase):
    """aggregate_probe_state feeds the operator-truth banner in the
    dashboard. Worst state must win; reason must name the worst host."""

    def test_all_live_reports_live(self):
        from freq.core.health_state import aggregate_probe_state
        hosts = [
            {"label": "a", "state": "live"},
            {"label": "b", "state": "live"},
        ]
        state, reason = aggregate_probe_state(hosts)
        self.assertEqual(state, "live")
        self.assertIn("all 2", reason)

    def test_auth_failed_wins_over_everything(self):
        from freq.core.health_state import aggregate_probe_state
        hosts = [
            {"label": "a", "state": "live"},
            {"label": "b", "state": "unreachable", "reason": "host down"},
            {"label": "c", "state": "auth_failed", "reason": "publickey rejected"},
        ]
        state, reason = aggregate_probe_state(hosts)
        self.assertEqual(state, "auth_failed")
        self.assertIn("c", reason)
        self.assertIn("publickey rejected", reason)

    def test_stale_beats_live(self):
        from freq.core.health_state import aggregate_probe_state
        hosts = [
            {"label": "a", "state": "live"},
            {"label": "b", "state": "stale", "reason": "cache 180s old"},
        ]
        state, _ = aggregate_probe_state(hosts)
        self.assertEqual(state, "stale")

    def test_empty_fleet_is_degraded(self):
        from freq.core.health_state import aggregate_probe_state
        state, reason = aggregate_probe_state([])
        self.assertEqual(state, "degraded")
        self.assertIn("no hosts", reason)

    def test_legacy_only_entry_falls_back_cleanly(self):
        """Cache entries from before the six-state contract only carry
        `status`. Aggregator must not crash on mixed-shape data."""
        from freq.core.health_state import aggregate_probe_state
        hosts = [
            {"label": "old1", "status": "healthy"},  # no `state`
            {"label": "old2", "status": "unreachable"},
        ]
        state, _ = aggregate_probe_state(hosts)
        self.assertEqual(state, "unreachable")  # worst wins


class TestServePyUsesSixStateContract(unittest.TestCase):
    """Source-pin the _bg_probe_health + supporting code in serve.py."""

    def _serve_src(self):
        return SERVE_PY.read_text()

    def test_imports_health_state(self):
        src = self._serve_src()
        self.assertIn("from freq.core.health_state import", src)
        self.assertIn("STATE_LIVE", src)
        self.assertIn("classify_probe_failure", src)
        self.assertIn("entry_base", src)
        self.assertIn("mark_stale", src)
        self.assertIn("aggregate_probe_state", src)

    def test_no_raw_healthy_return_in_probe_host(self):
        """_probe_host must not build a raw 'status: healthy' dict —
        every return must go through entry_base which sets state first."""
        src = self._serve_src()
        start = src.find("def _probe_host(h):")
        self.assertGreater(start, 0)
        end = src.find("\n    # ── Circuit breaker", start)
        window = src[start:end]
        # The prior version used literal `"status": "healthy"` in 3 places.
        # After the rewrite, no such literal may remain in _probe_host.
        self.assertNotIn('"status": "healthy"', window,
                         "_probe_host must route returns through entry_base, not raw dicts")
        self.assertNotIn('"status": "unreachable"', window,
                         "_probe_host must route returns through entry_base, not raw dicts")

    def test_top_level_probe_state_emitted(self):
        src = self._serve_src()
        self.assertIn("aggregate_probe_state(host_data)", src)
        self.assertIn('"probe_state": probe_state', src)
        self.assertIn('"probe_reason": probe_reason', src)

    def test_circuit_breaker_engage_writes_audit(self):
        src = self._serve_src()
        self.assertIn('"circuit_breaker_engage"', src)
        # Find the engage call and verify its kwargs capture evidence.
        idx = src.find('"circuit_breaker_engage"')
        self.assertGreater(idx, 0)
        tail = src[idx:idx + 800]
        self.assertIn("error_state=", tail,
                      "circuit_breaker_engage must capture error_state kwarg")
        self.assertIn("failure_count=", tail,
                      "circuit_breaker_engage must capture failure_count kwarg")
        self.assertIn("last_error=", tail,
                      "circuit_breaker_engage must capture last_error kwarg")
        self.assertIn("backoff_seconds=", tail,
                      "circuit_breaker_engage must capture backoff_seconds kwarg")

    def test_circuit_breaker_reset_writes_audit(self):
        src = self._serve_src()
        self.assertIn('"circuit_breaker_reset"', src)
        idx = src.find('"circuit_breaker_reset"')
        self.assertGreater(idx, 0)
        # audit.record call can appear a few hundred chars after the
        # label occurrence (there's also a logger.info use just above).
        tail = src[idx:idx + 1200]
        self.assertIn("backoff_duration_s", tail)
        self.assertIn("prior_failure_count", tail)
        self.assertIn("healed_with", tail)

    def test_skipped_hosts_logged_with_reason(self):
        src = self._serve_src()
        self.assertIn("health_probe_skipped", src,
                      "skipped hosts must emit a logger event with reason")

    def test_skipped_hosts_marked_stale_not_silent(self):
        src = self._serve_src()
        self.assertIn("mark_stale(prev, now_wall, skip_reason)", src)

    def test_state_tracking_dicts_declared(self):
        src = self._serve_src()
        self.assertIn("_host_last_success_at", src)
        self.assertIn("_host_last_error", src)
        self.assertIn("_host_backoff_started_at", src)
        self.assertIn("_host_recovering", src)


class TestFleetApiFallbackUsesSixStateContract(unittest.TestCase):
    """api/fleet.py cold-cache fallback (_probe_host in handle_health_api)
    must use the same classifier so a cold dashboard open does not see
    a different shape from the warm-cache path."""

    def test_imports_health_state(self):
        src = FLEET_API_PY.read_text()
        self.assertIn("from freq.core.health_state import", src)
        self.assertIn("classify_probe_failure", src)
        self.assertIn("entry_base", src)
        self.assertIn("aggregate_probe_state", src)

    def test_no_raw_healthy_return_in_fallback(self):
        src = FLEET_API_PY.read_text()
        start = src.find("def _probe_host(h):")
        self.assertGreater(start, 0, "fallback _probe_host must still exist")
        end = src.find("    host_data = []", start)
        window = src[start:end]
        self.assertNotIn('"status": "healthy"', window)
        self.assertNotIn('"status": "unreachable"', window)

    def test_fallback_emits_probe_state(self):
        src = FLEET_API_PY.read_text()
        # Only the fallback (below `if cached:` block) should build result.
        self.assertIn("aggregate_probe_state(host_data)", src)
        self.assertIn('"probe_state": probe_state', src)


class TestHandleHealthApiFieldsStable(unittest.TestCase):
    """Morty's field-tolerant readers expect these top-level keys to
    survive future refactors: state / probe_state / reason /
    age_seconds / probe_status. Pin them so a rename fails loud."""

    def test_primary_cache_path_emits_fields(self):
        src = FLEET_API_PY.read_text()
        start = src.find("def handle_health_api(handler):")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        window = src[start:end]
        # Existing surface
        self.assertIn('"probe_status"', window)
        self.assertIn('response["age_seconds"]', window)


if __name__ == "__main__":
    unittest.main()
