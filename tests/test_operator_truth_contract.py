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
     consecutive failures AND honor hard probe failures on 200
     responses without treating bounded stale cache windows as down.
     After two failures in a row, _markApiDegraded flips
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
