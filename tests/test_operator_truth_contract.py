"""M-RESILIENCE-OPERATOR-TRUTH-20260413AI contract.

Pins the resilience / operator-truth guarantees against the shipped
web surface so the four classes of lie Morty repro'd under AI stay
fixed:

  1. Pre-auth setup-truth banner: when the backend reports
     initialized=false / first_run=true / setup_health=partial, the
     login card renders a visible SETUP REQUIRED banner with a link
     to /setup.html — NOT a naked 401 against "Invalid credentials".

  2. Post-auth operator-truth banner: the same truth is also surfaced
     in the header after a successful login so the operator doesn't
     lose the degraded-state warning the moment they cross the auth
     boundary.

  3. Persistent stream-status indicator: a header-level badge always
     shows LIVE / CACHED / STREAM DEAD based on the SSE readyState so
     the operator can see at a glance whether the dashboard is
     reading live push events or polling-cached data — this used to
     live only inside the hw-fleet-stats widget, which vanished on
     any view that didn't load it.

  4. API-degrade streak + probe_status honesty: the background silent
     refreshers (_silentHealthRefresh / _silentFleetRefresh) count
     consecutive failures AND honor probe_status=stale/error on 200
     responses. After two failures in a row, _markApiDegraded flips
     the stream indicator to CACHED and writes an "API DEGRADED"
     message into the operator-truth banner with the specific
     failing endpoint + reason.

Proof is anchored on the app.js source and the static HTML/CSS that
ships with the dashboard, not on a running server — this file runs in
CI alongside the other contract tests and must not require playwright.
"""

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO_ROOT, "freq", "data", "web")


def _read(name):
    with open(os.path.join(WEB, name)) as f:
        return f.read()


def _app_js():
    return _read("js/app.js")


def _app_html():
    return _read("app.html")


def _app_css():
    return _read("css/app.css")


def _fn_body(src, name):
    """Extract the source body of a top-level `function NAME(...)` so
    subsequent regex checks can anchor to one function without false-
    positives from unrelated matches elsewhere in the 7000+ line file."""
    idx = src.find("function " + name + "(")
    if idx == -1:
        return ""
    depth = 0
    start = src.find("{", idx)
    if start == -1:
        return ""
    i = start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return src[start:]


class TestPreAuthSetupTruthBanner(unittest.TestCase):
    """Login card must carry a pre-auth setup-truth banner element and
    a probe that populates it from /api/setup/status."""

    def test_login_card_has_setup_banner_slot(self):
        html = _app_html()
        self.assertIn('id="login-setup-banner"', html,
                      "app.html must include the pre-auth setup banner slot")
        self.assertIn("login-setup-banner d-none", html,
                      "banner must start hidden until the probe resolves")

    def test_css_defines_login_setup_banner(self):
        css = _app_css()
        self.assertRegex(css, r"\.login-setup-banner\s*\{",
                         "app.css must define .login-setup-banner")
        self.assertRegex(css, r"\.login-setup-banner\.lsb-err\s*\{",
                         "app.css must define the error variant .lsb-err")

    def test_probe_function_exists(self):
        src = _app_js()
        self.assertIn("function _probeSetupTruth", src)
        self.assertIn("function _renderSetupTruthBanner", src)

    def test_show_login_overlay_triggers_probe(self):
        body = _fn_body(_app_js(), "_showLoginOverlay")
        self.assertIn("_probeSetupTruth", body,
                      "_showLoginOverlay must call _probeSetupTruth so the "
                      "banner is populated every time the login card is shown")

    def test_banner_mentions_setup_link_and_initialized(self):
        """The setup-truth strings live in the shared _setupTruthSummary
        helper after the product-law refactor — both pre-auth and post-
        auth renderers consume it so they cannot disagree about state."""
        src = _app_js()
        renderer = _fn_body(src, "_renderSetupTruthBanner")
        self.assertIn("_setupTruthSummary", renderer,
                      "pre-auth renderer must read _setupTruthSummary so "
                      "the banner content is shared with the post-auth path")
        summary = _fn_body(src, "_setupTruthSummary")
        self.assertIn("/setup.html", summary,
                      "summary body must link to /setup.html")
        self.assertIn("initialized: false", summary,
                      "summary must name the initialized=false state verbatim")
        self.assertIn("SETUP REQUIRED", summary)
        self.assertIn("_probe_failed", summary,
                      "backend-unreachable branch must carry its own message")


class TestLogin401RePropesTruth(unittest.TestCase):
    """A 401 on login is ambiguous — it might mean wrong password, or
    that the backend has no seeded hash yet. doLogin's error path must
    re-probe setup/status so the banner stays honest."""

    def test_dologin_error_reprobes_setup_on_401(self):
        body = _fn_body(_app_js(), "doLogin")
        self.assertIn("_probeSetupTruth", body,
                      "doLogin must re-probe setup-status on failed login")
        # The re-probe must be gated on the 401 status code, not fire on
        # every failure (a 500 from a dead backend is a different story).
        self.assertRegex(
            body,
            r"res\.status===401.*_probeSetupTruth",
            "re-probe must be gated on res.status===401",
        )


class TestPersistentStreamStatus(unittest.TestCase):
    """A persistent header stream indicator must be part of the shipped
    surface, with LIVE / CACHED / STREAM DEAD states driven by the SSE
    readyState. The pre-fix indicator only lived inside the hw-fleet-stats
    widget and vanished on every view that didn't render it."""

    def test_header_contains_stream_status_slot(self):
        html = _app_html()
        self.assertIn('id="stream-status"', html,
                      "app.html must include the header stream-status slot")
        self.assertIn('class="stream-status"', html,
                      "header slot must carry the stream-status class")

    def test_css_defines_all_three_states(self):
        css = _app_css()
        for state_cls in ("s-live", "s-cached", "s-dead"):
            with self.subTest(state_cls=state_cls):
                self.assertRegex(
                    css, rf"\.stream-status\.{state_cls}\s*\{{",
                    f"app.css must define .stream-status.{state_cls}",
                )

    def test_render_stream_status_function_exists(self):
        src = _app_js()
        self.assertIn("function _renderStreamStatus", src)
        body = _fn_body(src, "_renderStreamStatus")
        for label in ("LIVE", "CACHED", "STREAM DEAD"):
            with self.subTest(label=label):
                self.assertIn(label, body,
                              f"_renderStreamStatus must map to {label}")

    def test_sse_handlers_feed_stream_indicator(self):
        src = _app_js()
        # SSE onopen must drive stream to live.
        self.assertRegex(
            src,
            r"_evtSource\.onopen\s*=\s*function[\s\S]*?_renderStreamStatus\('live'\)",
            "SSE onopen must call _renderStreamStatus('live')",
        )
        # SSE onerror must call _renderStreamStatus with cached OR dead
        # depending on readyState — never leave the header lying LIVE.
        self.assertRegex(
            src,
            r"_evtSource\.onerror\s*=\s*function[\s\S]*?_renderStreamStatus\(rs===2\?'dead':'cached'\)",
            "SSE onerror must differentiate closed (dead) vs reconnecting (cached)",
        )


class TestOperatorTruthBannerPostAuth(unittest.TestCase):
    """The post-auth header banner must be wired up in HTML/CSS and
    rendered from the same setup-status probe after a successful login."""

    def test_html_has_operator_truth_banner_slot(self):
        html = _app_html()
        self.assertIn('id="operator-truth-banner"', html,
                      "app.html must include #operator-truth-banner")
        self.assertIn('id="operator-truth-text"', html,
                      "app.html must include the text slot #operator-truth-text")
        self.assertIn("operator-truth-banner d-none", html,
                      "banner must start hidden")

    def test_css_defines_banner_and_err_variant(self):
        css = _app_css()
        self.assertRegex(css, r"\.operator-truth-banner\s*\{")
        self.assertRegex(css, r"\.operator-truth-banner\.otb-err\s*\{")

    def test_render_post_auth_truth_banner_function(self):
        src = _app_js()
        self.assertIn("function _renderPostAuthTruthBanner", src)
        body = _fn_body(src, "_renderPostAuthTruthBanner")
        self.assertIn("_setupTruthSummary", body,
                      "post-auth renderer must read the shared summary so "
                      "it cannot disagree with the pre-auth banner")
        self.assertIn("otb-err", body)
        # The strings themselves live in _setupTruthSummary now — check
        # them at the source rather than the renderer.
        summary = _fn_body(src, "_setupTruthSummary")
        self.assertIn("/setup.html", summary)
        self.assertIn("initialized: false", summary)
        self.assertIn("SETUP REQUIRED", summary)
        self.assertIn("SETUP INCOMPLETE", summary)

    def test_show_app_triggers_post_auth_probe(self):
        body = _fn_body(_app_js(), "_showApp")
        self.assertIn("_renderPostAuthTruthBanner", body,
                      "_showApp must pipe setup/status into the post-auth "
                      "banner after a successful login")
        self.assertIn("_probeSetupTruth(_renderPostAuthTruthBanner", body,
                      "probe must run the post-auth renderer as its callback")


class TestApiDegradedStreakAndProbeStatus(unittest.TestCase):
    """Silent background refreshers must count consecutive failures
    AND honor probe_status=stale/error on 200 responses, flipping the
    operator-truth banner + stream indicator after two strikes."""

    def test_degraded_helpers_exist(self):
        src = _app_js()
        self.assertIn("function _markApiDegraded", src)
        self.assertIn("function _clearApiDegraded", src)
        self.assertIn("var _healthFailStreak", src)
        self.assertIn("var _fleetFailStreak", src)
        self.assertIn("var _apiDegradedState", src)

    def test_mark_api_degraded_flips_stream_and_banner(self):
        """After the product-law refactor _markApiDegraded routes the
        API-degraded line through _renderPostAuthTruthBanner so it
        stacks on top of setup + doctor truth instead of overwriting
        them. The intent is unchanged: stream → cached, banner → red,
        API DEGRADED message rendered."""
        body = _fn_body(_app_js(), "_markApiDegraded")
        self.assertIn("_renderStreamStatus('cached')", body,
                      "_markApiDegraded must force stream indicator to cached")
        self.assertIn("_apiDegradedDetail", body,
                      "_markApiDegraded must record kind+reason in "
                      "_apiDegradedDetail so the renderer can layer it")
        self.assertIn("_renderPostAuthTruthBanner", body,
                      "_markApiDegraded must delegate to the unified "
                      "renderer so api/setup/doctor truth all stack")
        # The literal strings live in the renderer now — verify there.
        renderer = _fn_body(_app_js(), "_renderPostAuthTruthBanner")
        self.assertIn("API DEGRADED", renderer)
        self.assertIn("otb-err", renderer)
        self.assertIn("operator-truth-banner", renderer)

    def test_health_refresh_counts_http_failures(self):
        body = _fn_body(_app_js(), "_silentHealthRefresh")
        # Must use the silent opt so the generic toaster doesn't race it.
        self.assertIn("{silent:true}", body)
        # Must check r.ok and increment streak on failure.
        self.assertRegex(body, r"!r\.ok[\s\S]*?_healthFailStreak\+\+")
        # Must trip _markApiDegraded at or above 2.
        self.assertRegex(body, r"_healthFailStreak>=2[\s\S]*?_markApiDegraded")
        # Must reset streak + clear on success.
        self.assertIn("_healthFailStreak=0", body)
        self.assertIn("_clearApiDegraded", body)
        # Catch branch must also bump the streak.
        self.assertRegex(body, r"\.catch\(function\(\)\{[\s\S]*?_healthFailStreak\+\+")

    def test_health_refresh_honors_probe_status_stale(self):
        """After the product-law refactor the refresher reads multiple
        equivalent state field names (probe_status / probe_state /
        state) into a single var, then checks for stale/error/degraded/
        unreachable/auth_failed. The intent is unchanged: a stale probe
        on a 200 response must still flip the streak."""
        body = _fn_body(_app_js(), "_silentHealthRefresh")
        self.assertIn("probe_status", body,
                      "_silentHealthRefresh must read probe_status (legacy)")
        self.assertIn("'stale'", body,
                      "_silentHealthRefresh must treat 'stale' as degraded")
        self.assertIn("'error'", body)
        self.assertRegex(body, r"_markApiDegraded\('health probe'")

    def test_fleet_refresh_counts_http_failures(self):
        body = _fn_body(_app_js(), "_silentFleetRefresh")
        self.assertIn("{silent:true}", body)
        self.assertRegex(body, r"!r\.ok[\s\S]*?_fleetFailStreak\+\+")
        self.assertRegex(body, r"_fleetFailStreak>=2[\s\S]*?_markApiDegraded")
        self.assertIn("_fleetFailStreak=0", body)
        self.assertRegex(body, r"\.catch\(function\(\)\{[\s\S]*?_fleetFailStreak\+\+")

    def test_fleet_refresh_honors_probe_status_stale(self):
        body = _fn_body(_app_js(), "_silentFleetRefresh")
        self.assertIn("probe_status", body)
        self.assertIn("'stale'", body)
        self.assertRegex(body, r"_markApiDegraded\('fleet probe'")


class TestSessionExpiryRehydrationStillHolds(unittest.TestCase):
    """Regression guard: the AD token pinned the no-logout-storm path.
    AI must not have removed those invariants. If any of these checks
    fail, AI's banner work collided with the login restore path."""

    def test_dologin_still_uses_bare_fetch_not_authfetch(self):
        body = _fn_body(_app_js(), "doLogin")
        # The login call itself must NOT go through _authFetch, otherwise
        # a 401 would recurse through _authFetch's auth-failure branch
        # and kick off another logout storm.
        self.assertIn("fetch(API.AUTH_LOGIN", body,
                      "doLogin must use bare fetch, not _authFetch")

    def test_dologout_still_tears_down_evtsource(self):
        body = _fn_body(_app_js(), "doLogout")
        self.assertIn("_evtSource.close()", body)
        self.assertIn("_authFailing=true", body)
        self.assertIn("_restoreLoginCard", body)


if __name__ == "__main__":
    unittest.main()
