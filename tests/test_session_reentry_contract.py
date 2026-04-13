"""Session re-entry contract tests.

Proves _checkSession() honors the real server session cookie instead
of forcing a login overlay on every page load. DC01 operators should
not have to retype credentials after a tab refresh when the
freq_session HttpOnly cookie is still valid.

Re-entry flow:
1. GET /api/auth/verify with credentials: same-origin
2. If {valid: true}, rehydrate _currentUser / _currentRole from the
   response and call _showApp() directly
3. If {valid: false} OR the request errors, show the login overlay
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


def _check_session_fn():
    src = _js()
    idx = src.index("function _checkSession")
    end = src.index("\nfunction ", idx + 10)
    return src[idx:end]


class TestCheckSessionCallsVerify(unittest.TestCase):
    """_checkSession must call /api/auth/verify before showing login."""

    def test_calls_auth_verify_endpoint(self):
        fn = _check_session_fn()
        self.assertIn("AUTH_VERIFY", fn,
                       "_checkSession must call API.AUTH_VERIFY")

    def test_uses_same_origin_credentials(self):
        """The verify fetch must include the session cookie."""
        fn = _check_session_fn()
        self.assertIn("credentials", fn,
                       "_checkSession verify fetch must set credentials")
        self.assertIn("same-origin", fn,
                       "_checkSession verify fetch must use 'same-origin' credentials")


class TestCheckSessionRehydratesOnValid(unittest.TestCase):
    """If verify returns valid:true, _checkSession must rehydrate
    _currentUser / _currentRole and hand off to _showApp — no login."""

    def test_rehydrates_current_user(self):
        fn = _check_session_fn()
        self.assertIn("_currentUser=d.user", fn,
                       "_checkSession must rehydrate _currentUser from verify response")

    def test_rehydrates_current_role(self):
        fn = _check_session_fn()
        self.assertIn("_currentRole=d.role", fn,
                       "_checkSession must rehydrate _currentRole from verify response")

    def test_calls_show_app_directly(self):
        fn = _check_session_fn()
        self.assertIn("_showApp()", fn,
                       "_checkSession must call _showApp() directly on valid session")


class TestCheckSessionFallsBackToLoginOverlay(unittest.TestCase):
    """If verify returns valid:false OR errors, show the login overlay."""

    def test_invalid_branch_shows_login(self):
        fn = _check_session_fn()
        self.assertIn("_showLoginOverlay", fn,
                       "_checkSession must call _showLoginOverlay on invalid session")

    def test_error_catch_shows_login(self):
        fn = _check_session_fn()
        self.assertIn(".catch(", fn,
                       "_checkSession must handle network/server errors via .catch")
        # The catch handler must also reach _showLoginOverlay
        catch_idx = fn.find(".catch(")
        catch_body = fn[catch_idx:]
        self.assertIn("_showLoginOverlay", catch_body,
                       ".catch branch must show login overlay")


class TestShowLoginOverlayHelper(unittest.TestCase):
    """The helper that actually displays the overlay + focuses the
    username field must exist and be reused."""

    def test_helper_exists(self):
        src = _js()
        self.assertIn("function _showLoginOverlay", src,
                       "_showLoginOverlay() helper must be defined")

    def test_helper_focuses_username_field(self):
        src = _js()
        idx = src.index("function _showLoginOverlay")
        end = src.index("\n}", idx)
        fn = src[idx: end + 2]
        self.assertIn("login-user", fn,
                       "_showLoginOverlay must focus the username field")
        self.assertIn(".focus()", fn,
                       "_showLoginOverlay must call .focus()")


class TestLegacyTokenCleanupStillHappens(unittest.TestCase):
    """Legacy JS-stored freq_auth_token / freq_auth_user keys must still
    be cleared on every _checkSession call — we never trusted those."""

    def test_clears_session_storage_legacy(self):
        fn = _check_session_fn()
        self.assertIn("sessionStorage.removeItem('freq_auth_token')", fn)
        self.assertIn("sessionStorage.removeItem('freq_auth_user')", fn)

    def test_clears_local_storage_legacy(self):
        fn = _check_session_fn()
        self.assertIn("localStorage.removeItem('freq_auth_token')", fn)
        self.assertIn("localStorage.removeItem('freq_auth_user')", fn)


if __name__ == "__main__":
    unittest.main()
