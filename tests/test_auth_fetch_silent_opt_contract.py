"""_authFetch silent-opt + 501-never-toast contract.

M-UI-CHROMIUM-POLISH-20260413AE polish: every non-ok response used to
fire a red corner toast ('API error: watchdog/health (501)') even for
optional endpoints where the caller rendered its own inline state.
The toast overlapped the 'Watchdog: not installed (optional add-on)'
inline label on HOME and the 'experiment log unavailable' inline
message on SYSTEM → CHAOS.

Fix: `_authFetch` accepts `{silent:true}` to suppress the toast and
always skips toasting on HTTP 501 (which by definition means the
feature is an optional add-on, not a real error). Callers that render
their own failure state opt in to silent mode so the chrome doesn't
duplicate information.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


def _function_body(src: str, name: str) -> str:
    idx = src.index(f"function {name}(")
    rest = src[idx:]
    m = re.search(r"\n(?:function |var [A-Za-z_]+=function)", rest[1:])
    if m is None:
        return rest
    return rest[: m.start() + 1]


class TestAuthFetchAcceptsSilentOpt(unittest.TestCase):
    """The silent escape hatch must exist and be observed by the
    non-ok toast branch."""

    def test_silent_flag_is_extracted_from_opts(self):
        body = _function_body(_js(), "_authFetch")
        self.assertRegex(
            body,
            r"var\s+silent\s*=\s*opts\.silent\s*===\s*true",
            "_authFetch must extract `silent` from opts",
        )
        self.assertIn(
            "delete opts.silent",
            body,
            "_authFetch must delete opts.silent before passing to fetch()"
            " so the raw fetch call doesn't see an unknown option",
        )

    def test_silent_suppresses_non_ok_toast(self):
        body = _function_body(_js(), "_authFetch")
        # Toast is gated by `!silent`
        self.assertRegex(
            body,
            r"!\s*r\.ok\s*&&\s*!\s*silent",
            "_authFetch must check `!silent` before toasting non-ok responses",
        )

    def test_501_never_toasts(self):
        body = _function_body(_js(), "_authFetch")
        self.assertIn(
            "r.status!==501",
            body,
            "_authFetch must never toast on 501 — Not Implemented means "
            "the endpoint is an optional add-on, not an error",
        )


class TestWatchdogProbeIsSilent(unittest.TestCase):
    """HOME renders `Watchdog: not installed (optional add-on)` inline.
    The _authFetch toast for the 501 response must NOT duplicate that
    information as a red corner toast."""

    def test_load_home_watchdog_call_is_silent(self):
        src = _js()
        # Find the loadHome watchdog fetch line
        idx = src.find("_authFetch(API.WATCHDOG_HEALTH")
        self.assertGreater(
            idx, -1, "loadHome must still call WATCHDOG_HEALTH via _authFetch")
        call = src[idx: src.index(")", idx) + 1]
        self.assertIn(
            "silent:true",
            call,
            "loadHome watchdog probe must pass {silent:true} so the "
            "inline 'Watchdog: not installed' label isn't duplicated "
            "as a red API-error toast",
        )


class TestChaosLogIsSilentAndRendersInlineFailure(unittest.TestCase):
    """SYSTEM → CHAOS renders the experiment log inline. On a 500 from
    /api/chaos/log, the page must render an inline 'experiment log
    unavailable' row, not flash a red toast and leave the skeleton up."""

    def test_chaos_log_fetch_is_silent(self):
        src = _js()
        body = _function_body(src, "loadChaos")
        self.assertIn(
            "_authFetch('/api/chaos/log',{silent:true}",
            body,
            "loadChaos must fetch /api/chaos/log with {silent:true}",
        )

    def test_chaos_log_renders_inline_on_non_ok(self):
        body = _function_body(_js(), "loadChaos")
        self.assertIn(
            "experiment log unavailable",
            body,
            "loadChaos must render 'experiment log unavailable' inline "
            "when the /api/chaos/log fetch returns a non-ok status",
        )


class TestDriveWipeOfflineCardIsEvidenceFirst(unittest.TestCase):
    """LAB → Drive Wipe offline state previously rendered a 48px
    gradient ghost of the tool name at opacity 0.15 — marketing hero,
    not an ops console. Replace with a dense STATION OFFLINE card."""

    def _offline_html(self):
        src = _js()
        idx = src.index("lt-offline")
        # Grab ~900 chars of the offline-card template
        return src[idx: idx + 1600]

    def test_no_gradient_ghost_hero_text(self):
        html = self._offline_html()
        self.assertNotIn(
            "font-size:48px;opacity:0.15",
            html,
            "Drive Wipe offline card must not render a 48px opacity:0.15 "
            "ghost hero of the tool name",
        )
        self.assertNotIn(
            "-webkit-background-clip:text",
            html,
            "Drive Wipe offline card must not use gradient background-clip",
        )

    def test_has_station_offline_monospace_tag(self):
        html = self._offline_html()
        self.assertIn(
            "STATION OFFLINE",
            html,
            "Drive Wipe offline card must render a 'STATION OFFLINE' "
            "monospace status tag",
        )
        self.assertIn(
            "Courier New",
            html,
            "STATION OFFLINE tag must use a monospace font family",
        )

    def test_offline_hint_still_present(self):
        html = self._offline_html()
        self.assertIn(
            "offlineHint",
            html,
            "Drive Wipe offline card must still render the tool's "
            "offlineHint CLI bootstrap text",
        )


if __name__ == "__main__":
    unittest.main()
