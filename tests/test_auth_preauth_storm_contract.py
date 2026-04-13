"""Pre-auth logout-storm contract tests (M-E2E-CHROMIUM-LOGIN-STATE-20260413AD).

Proves the browser auth path is free of the recursive-logout storm that
made a fresh-tab first-login impossible on the live 8888 instance.

Symptoms caught by Playwright on a clean page load with freq-ops creds:
  - overlay stays visible after login
  - #mn-body stays hidden
  - header-user-btn stays empty
  - watchdog reads 'Watchdog: Authentication required'
  - no cookies are present
  - #login-error ends up 'Enter username and password'
  - POST /api/auth/logout -> 403 loop (674 requests in 4s)

Root cause chain:
  1. Bottom-of-file bootstrap fired `loadHome()`, `startSparklines()` and
     `startSSE()` synchronously at script load — BEFORE the user had a
     session cookie. `loadHome()` called `_authFetch('/api/info')` and
     `_authFetch('/api/watchdog/health')`, both of which returned 403.
  2. `_authFetch`'s 401/403 branch called `doLogout()` directly.
  3. `doLogout()` itself called `_authFetch('/api/auth/logout', POST)`.
     That endpoint is NOT in `_AUTH_WHITELIST`, so it returned 403 with
     no session — triggering `doLogout()` again through `_authFetch`'s
     own 401/403 branch. Infinite recursion.
  4. Each `doLogout()` call cleared `#login-user.value` and
     `#login-pass.value`, so any post-bootstrap credential-fill
     raced against the storm and frequently saw empty values at
     `doLogin()` read-time.

Contract: the fix must hold all of the following invariants
simultaneously. Any one of them regressing is enough to put us back
in the recursive-logout state, so each has its own test.
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


def _function_body(src: str, name: str) -> str:
    """Extract a function body by name. Returns text from `function NAME`
    up to the next top-level `\\nfunction ` declaration."""
    idx = src.index(f"function {name}(")
    # Find the matching closing brace for the top-level function by
    # scanning for the next `\nfunction ` (top-level) or end of file.
    rest = src[idx:]
    m = re.search(r"\n(?:function |var [A-Za-z_]+=function)", rest[1:])
    if m is None:
        return rest
    return rest[: m.start() + 1]


class TestAuthFetchHasRecursionGuard(unittest.TestCase):
    """`_authFetch` must hold a module-level guard flag so concurrent
    401/403 responses do not stack doLogout() calls on top of each
    other."""

    def test_auth_failing_flag_defined(self):
        src = _js()
        self.assertRegex(
            src,
            r"var\s+_authFailing\s*=\s*false",
            "_authFailing guard flag must be declared at module scope",
        )

    def test_auth_fetch_gates_dologout_with_flag(self):
        src = _js()
        body = _function_body(src, "_authFetch")
        self.assertIn("_authFailing", body,
                      "_authFetch must consult _authFailing before calling doLogout")
        self.assertIn("doLogout()", body,
                      "_authFetch must still call doLogout once per auth-failure")
        # The guard must wrap the doLogout call, not sit after it.
        m = re.search(r"if\s*\(\s*!\s*_authFailing\s*\)\s*\{[^}]*doLogout\(\)",
                      body, re.DOTALL)
        self.assertIsNotNone(
            m,
            "_authFetch must only call doLogout() when !_authFailing",
        )

    def test_auth_fetch_sends_credentials_same_origin(self):
        """Cookie auth must reach the server on every _authFetch so
        the cookie re-entry path works even when _authToken is empty
        (e.g., fresh refresh with a valid session cookie)."""
        src = _js()
        body = _function_body(src, "_authFetch")
        self.assertIn("credentials", body,
                      "_authFetch must set credentials on fetch opts")
        self.assertIn("same-origin", body,
                      "_authFetch credentials default must be 'same-origin'")


class TestDoLoginUsesBareFetch(unittest.TestCase):
    """`doLogin` is the credential-carrying endpoint. Routing it
    through `_authFetch` meant a wrong-password 401 fell through the
    auto-logout branch and kicked off the storm instead of surfacing
    the error in #login-error."""

    def test_login_uses_bare_fetch(self):
        src = _js()
        body = _function_body(src, "doLogin")
        # doLogin must call fetch(...) for the login endpoint, not _authFetch.
        self.assertNotIn(
            "_authFetch(API.AUTH_LOGIN",
            body,
            "doLogin must not route the login POST through _authFetch",
        )
        self.assertIn(
            "fetch(API.AUTH_LOGIN",
            body,
            "doLogin must POST to API.AUTH_LOGIN via bare fetch",
        )

    def test_login_clears_auth_failing_on_success(self):
        src = _js()
        body = _function_body(src, "doLogin")
        self.assertIn(
            "_authFailing=false",
            body.replace(" ", ""),
            "doLogin success path must reset _authFailing so future "
            "401/403 responses are handled once more",
        )

    def test_login_sends_credentials_same_origin(self):
        src = _js()
        body = _function_body(src, "doLogin")
        self.assertIn("credentials", body)
        self.assertIn("same-origin", body,
                      "doLogin fetch must send credentials so the "
                      "freq_session Set-Cookie persists")


class TestDoLogoutUsesBareFetch(unittest.TestCase):
    """`doLogout` must invalidate the server session via BARE fetch,
    not through `_authFetch`. Routing the logout POST through
    `_authFetch` re-entered the 401/403 branch (because the logout
    endpoint is not whitelisted) and called doLogout() recursively."""

    def test_logout_uses_bare_fetch_for_server_invalidation(self):
        src = _js()
        body = _function_body(src, "doLogout")
        self.assertNotIn(
            "_authFetch('/api/auth/logout",
            body,
            "doLogout must not call _authFetch('/api/auth/logout') — "
            "that was the recursion entry point",
        )
        self.assertIn(
            "fetch('/api/auth/logout'",
            body,
            "doLogout must call bare fetch() for the server logout",
        )

    def test_logout_restores_login_card(self):
        src = _js()
        body = _function_body(src, "doLogout")
        self.assertIn(
            "_restoreLoginCard()",
            body,
            "doLogout must call _restoreLoginCard() so a mid-session "
            "logout replaces the COLD START boot sequence with the "
            "original login form markup",
        )

    def test_logout_tears_down_app_chrome(self):
        """mn-body and header-user-btn must be hidden on logout so
        the authenticated app chrome doesn't bleed through the
        restored login overlay."""
        src = _js()
        body = _function_body(src, "doLogout")
        self.assertIn("mn-body", body)
        self.assertIn("header-user-btn", body)


class TestLoginCardCaptureAndRestore(unittest.TestCase):
    """The login overlay HTML must be captured before `_showApp()`
    replaces it with the COLD START boot log, and restored by
    `_restoreLoginCard()` on logout. Without the capture, a mid-session
    logout left the overlay showing the boot sequence with no inputs."""

    def test_capture_helper_exists(self):
        src = _js()
        self.assertIn("function _captureLoginOverlay",
                      src,
                      "_captureLoginOverlay helper must exist")
        self.assertIn("function _restoreLoginCard",
                      src,
                      "_restoreLoginCard helper must exist")

    def test_restore_reinvokes_register_login_bindings(self):
        src = _js()
        body = _function_body(src, "_restoreLoginCard")
        self.assertIn(
            "registerLoginBindings()",
            body,
            "_restoreLoginCard must re-run registerLoginBindings so "
            "the new DOM nodes get fresh submit/keydown handlers",
        )

    def test_show_app_captures_before_replacing_overlay(self):
        """_showApp replaces the overlay innerHTML with the cold-start
        sequence. The capture must happen BEFORE that replacement."""
        src = _js()
        body = _function_body(src, "_showApp")
        cap = body.index("_captureLoginOverlay()")
        # The old innerHTML= replacement that writes the COLD START
        # layout uses the `login.innerHTML='<div ...` pattern.
        replace = body.index("login.innerHTML")
        self.assertLess(
            cap, replace,
            "_captureLoginOverlay() must run before login.innerHTML "
            "is overwritten by the cold-start sequence",
        )


class TestPreAuthBootstrapIsGated(unittest.TestCase):
    """No data-fetching function may run unconditionally at script
    load. Every `_authFetch` caller that bootstraps the dashboard
    must be reachable only after _showApp() confirms auth."""

    def test_no_unconditional_load_home(self):
        """The old bottom-of-file bootstrap called loadHome() inside
        a try block synchronously at script load. That's the
        origin of the pre-auth 403 → logout storm."""
        src = _js()
        # Forbid the exact legacy pattern: a bare `loadHome()` call
        # at module scope (not inside a function body). We scan the
        # last ~400 characters of the file for it.
        tail = src[-600:]
        self.assertNotIn(
            "else loadHome();",
            tail,
            "Bottom-of-file bootstrap must not call loadHome() "
            "unconditionally — move the initial route into _showApp()",
        )

    def test_no_unconditional_start_sparklines(self):
        """startSparklines() fired _authFetch('/api/pve/rrd') 5s
        after page load regardless of auth state."""
        src = _js()
        # Forbid a module-scope `startSparklines();` line.
        self.assertNotRegex(
            src,
            r"\n\s*startSparklines\(\);\s*\n",
            "startSparklines() must not be invoked at module scope — "
            "call it from _showApp() after auth",
        )

    def test_no_unconditional_start_sse(self):
        """startSSE() opens an EventSource against /api/events, which
        returns 403 pre-auth and triggers noisy auto-retry traffic."""
        src = _js()
        self.assertNotRegex(
            src,
            r"\n\s*startSSE\(\);\s*\n",
            "startSSE() must not be invoked at module scope — call it "
            "from _showApp() after auth",
        )

    def test_show_app_kicks_off_loaders(self):
        """_showApp must be the single entry point that starts
        loadHome (or the deep-linked view), startSparklines, and
        startSSE."""
        src = _js()
        body = _function_body(src, "_showApp")
        self.assertIn("startSparklines()", body,
                      "_showApp must call startSparklines()")
        self.assertIn("startSSE()", body,
                      "_showApp must call startSSE()")
        self.assertIn("loadHome()", body,
                      "_showApp must call loadHome() as the fallback "
                      "initial route")
        self.assertIn("switchView", body,
                      "_showApp must honor a deep-linked initial view")


class TestNoRecursiveLogoutInAuthFetch(unittest.TestCase):
    """Source-level grep guard. If any future edit reintroduces the
    exact recursion pattern, this test catches it before runtime."""

    def test_auth_fetch_does_not_nest_dologout_calls(self):
        """`_authFetch` must not call itself with /api/auth/logout.
        Use bare fetch for any server logout POST inside doLogout."""
        src = _js()
        # Extract doLogout and assert it does not re-enter _authFetch.
        body = _function_body(src, "doLogout")
        self.assertNotIn(
            "_authFetch(",
            body,
            "doLogout body must contain NO _authFetch() calls — "
            "every fetch inside doLogout must be bare to prevent "
            "the pre-auth 403 → doLogout → _authFetch recursion",
        )


if __name__ == "__main__":
    unittest.main()
