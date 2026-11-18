"""TUI truth audit contract.

Per Finn (Apr 14 product-law translation pass): the TUI surfaces
must carry the same six-state truth as CLI / API / web banner /
audit. Pre-fix the TUI splash showed a bare 'Hosts: 14 PVE: 3'
static line with no probe state, no freshness, no failure-class
breakdown — a tired operator at 2AM had no idea which hosts were
reachable, when the data was last refreshed, or what was broken.

This contract pins the densified splash header:

  STATIC IMPORT — freq/tui/menu.py reads ALL_STATES from
  freq/core/health_state.py, NOT a sibling taxonomy. If a future
  refactor invents a parallel six-state set in the TUI module, the
  test catches it.

  HELPER SHAPE — _load_probe_state_summary(cfg) returns the
  documented dict shape (has_data / total / counts / max_age_s /
  min_age_s / cache_age_s). _render_probe_state_summary(summary)
  produces a non-empty densified line that mentions the live/total
  form, names any non-live state by its canonical name, and surfaces
  freshness either as 'cached Ns' or as 'no probe data — run [!]
  dashboard'.

  NEXT-USEFUL-PATH — the no-probe-data path must name the [!]
  dashboard menu key explicitly so the operator knows what to press
  next. Anti-comfort-copy pin.

  RACE FRIENDLINESS — the splash render must NOT crash if cfg is
  missing data_dir or the cache file is unreadable. The TUI must
  always render even if probe data is missing entirely.
"""

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TUI_PATH = os.path.join(REPO_ROOT, "freq", "tui", "menu.py")


def _read_tui():
    with open(TUI_PATH) as f:
        return f.read()


class TestTuiNoSiblingTaxonomy(unittest.TestCase):
    """The TUI must read ALL_STATES from the canonical health_state.py
    module, not redefine its own six-state set. Cross-surface
    invariant: every observation channel — CLI / API / banner / TUI —
    points at the same source of truth."""

    def test_tui_imports_all_states_from_health_state(self):
        src = _read_tui()
        self.assertIn(
            "from freq.core.health_state import",
            src,
            "freq/tui/menu.py must import from freq.core.health_state",
        )
        self.assertIn("ALL_STATES", src,
            "freq/tui/menu.py must import ALL_STATES — using a literal "
            "set of state names would create a sibling taxonomy")

    def test_tui_does_not_define_state_constants(self):
        """A defensive pin: the TUI must NOT define STATE_LIVE /
        STATE_STALE / etc as module-level constants. Those live in
        freq/core/health_state.py only."""
        src = _read_tui()
        for const in ("STATE_LIVE", "STATE_STALE", "STATE_DEGRADED",
                      "STATE_AUTH_FAILED", "STATE_UNREACHABLE",
                      "STATE_RECOVERING"):
            with self.subTest(const=const):
                pat = re.compile(r"^\s*" + const + r"\s*=", re.MULTILINE)
                self.assertIsNone(
                    pat.search(src),
                    f"freq/tui/menu.py must not define {const} — it "
                    f"belongs to freq/core/health_state.py only",
                )


class TestTuiProbeStateSummary(unittest.TestCase):
    """_load_probe_state_summary reads the same health.json cache the
    API consumes, aggregates per six-state count, and returns a dict
    the renderer can consume. Same field source as the CLI / API
    surfaces — no parallel parsing path."""

    def setUp(self):
        from freq.tui import menu
        self.menu = menu

    def test_summary_returns_documented_shape(self):
        # Pass a minimal config-like object so the helper hits the
        # missing-cache branch deterministically.
        class _Cfg:
            data_dir = "/nonexistent/dir/should/not/exist"
        s = self.menu._load_probe_state_summary(_Cfg())
        self.assertIsInstance(s, dict)
        for key in ("has_data", "total", "counts",
                    "max_age_s", "min_age_s", "cache_age_s"):
            self.assertIn(key, s,
                "summary dict must carry " + key)
        self.assertFalse(s["has_data"])
        self.assertEqual(s["counts"], {})

    def test_summary_handles_missing_data_dir_attribute(self):
        """A defensive pin — if cfg has no data_dir, the helper must
        return has_data=False rather than crash and block the TUI."""
        class _BadCfg:
            pass
        s = self.menu._load_probe_state_summary(_BadCfg())
        self.assertFalse(s["has_data"])

    def test_render_no_data_names_next_useful_path(self):
        out = self.menu._render_probe_state_summary({"has_data": False, "total": 14})
        # Strip ANSI for assertion.
        bare = re.sub(r"\x1b\[[0-9;]*m", "", out)
        self.assertIn("no probe data", bare,
            "no-cache render must name the missing state honestly")
        self.assertIn("[!]", bare,
            "no-cache render must name the next-useful-path keystroke")
        self.assertIn("dashboard", bare,
            "no-cache render must name the dashboard target")

    def test_render_with_data_uses_live_total_form(self):
        out = self.menu._render_probe_state_summary({
            "has_data": True, "total": 14,
            "counts": {"live": 13, "stale": 1},
            "max_age_s": 12, "min_age_s": 12, "cache_age_s": 12,
        })
        bare = re.sub(r"\x1b\[[0-9;]*m", "", out)
        self.assertIn("13/14", bare,
            "render must show live/total form, not bare live count")
        self.assertIn("live", bare)
        self.assertIn("stale", bare)
        self.assertIn("12s", bare,
            "render must show cached age in s/m/h form")
        self.assertIn("cached", bare,
            "render must label the freshness as a cache age")

    def test_render_names_failure_classes_individually(self):
        """When the fleet has multiple failure classes the renderer
        must name each by its canonical state name, not collapse them
        into 'unhealthy' or similar comfort-bucket."""
        out = self.menu._render_probe_state_summary({
            "has_data": True, "total": 14,
            "counts": {"live": 11, "auth_failed": 2, "unreachable": 1},
            "max_age_s": 8, "min_age_s": 4, "cache_age_s": 4,
        })
        bare = re.sub(r"\x1b\[[0-9;]*m", "", out)
        self.assertIn("11/14", bare)
        self.assertIn("auth_failed", bare,
            "render must name auth_failed state explicitly — never "
            "collapse into a comfort bucket like 'unhealthy'")
        self.assertIn("unreachable", bare,
            "render must name unreachable state explicitly")
        self.assertNotIn("unhealthy", bare.lower(),
            "render must not use the legacy 'unhealthy' bucket — "
            "the six-state taxonomy is the only allowed vocabulary")

    def test_legacy_status_field_falls_through_to_state(self):
        """Defensive: if a cache entry lacks the new 'state' field,
        the helper must fall back to the legacy 'status' field
        rather than dropping the host from the count."""
        # Construct a fake cache and patch the helper temporarily.
        import json as _json
        import tempfile
        import time as _t
        from freq.tui import menu as m
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "cache"))
            with open(os.path.join(d, "cache", "health.json"), "w") as f:
                _json.dump({
                    "ts": _t.time(),
                    "data": {"hosts": [
                        {"label": "old1", "ip": "10.0.0.1",
                         "status": "healthy"},  # legacy field only
                        {"label": "old2", "ip": "10.0.0.2",
                         "status": "unreachable"},
                    ]},
                }, f)
            class _Cfg:
                data_dir = d
            s = m._load_probe_state_summary(_Cfg())
            self.assertTrue(s["has_data"])
            self.assertEqual(s["total"], 2)
            self.assertEqual(s["counts"].get("live", 0), 1,
                "legacy status='healthy' must map to state='live'")
            self.assertEqual(s["counts"].get("unreachable", 0), 1,
                "legacy status='unreachable' must map to state='unreachable'")


class TestTuiSplashWiring(unittest.TestCase):
    """The main run() function must call into the densified renderer
    on first paint. Pre-densification it printed a static line with
    bare host count + PVE count + USER. The pin verifies the call
    site so a future refactor can't quietly revert."""

    def test_run_calls_load_probe_state_summary(self):
        src = _read_tui()
        self.assertIn("_load_probe_state_summary(cfg)", src,
            "run() must invoke _load_probe_state_summary so the splash "
            "shows the densified fleet truth instead of bare counts")
        self.assertIn("_render_probe_state_summary(", src,
            "run() must call the renderer to format the splash line")

    def test_run_no_longer_uses_bare_hosts_label(self):
        """The exact pre-fix string was '{fmt.S.DOT} Hosts: {host_count}'
        which encoded zero state, zero freshness. Make sure no caller
        re-introduces it."""
        src = _read_tui()
        self.assertNotIn(
            "Hosts: {host_count}", src,
            "run() must not print the bare 'Hosts: <count>' label "
            "from the pre-densification splash — use _render_probe_"
            "state_summary instead",
        )


if __name__ == "__main__":
    unittest.main()
