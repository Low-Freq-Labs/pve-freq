"""Login form robustness contract tests.

Proves two real defects found by the M-UI-CHROMIUM-USABILITY-20260413X
playwright pass are fixed:

DEFECT A: login form brittle to synthetic/autofill input
  The old doLogin() had a 'Force browser to flush autofill values'
  dispatchEvent hack that masked a deeper bug — chromium holds .value
  in the autofill layer for inputs with autocomplete=username /
  current-password until a real form submission reads them. Fix:
  wrap the inputs in a real <form> with onsubmit so browser autofill
  and synthetic testing both resolve .value reliably.

DEFECT B: login overlay intercepts clicks post-auth
  After a successful login, mn-body becomes visible but the
  #login-overlay element stayed in the DOM intercepting pointer
  events during the 600ms hand-off animation. Fix: drop
  pointer-events on login-overlay immediately when _showApp() runs,
  not on the delayed display-flip.
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _html():
    with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
        return f.read()


def _js():
    with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
        return f.read()


class TestLoginInputsWrappedInForm(unittest.TestCase):
    """Defect A fix: login inputs must be inside a real <form>."""

    def test_login_form_element_exists(self):
        html = _html()
        self.assertIn('id="login-form"', html,
                       "Login inputs must be wrapped in a <form id='login-form'>")

    def test_login_form_has_method_post(self):
        html = _html()
        idx = html.index('id="login-form"')
        form = html[idx: html.index("</form>", idx)]
        self.assertIn('method="post"', form,
                       "Login form must declare method=post for autofill reliability")

    def test_login_form_has_action(self):
        html = _html()
        idx = html.index('id="login-form"')
        form = html[idx: html.index("</form>", idx)]
        self.assertIn('action=', form,
                       "Login form must declare an action (# is fine)")

    def test_login_inputs_have_name_attrs(self):
        """Browser autofill + password managers need name attrs, not
        just id, to populate credentials reliably."""
        html = _html()
        idx = html.index('id="login-form"')
        form = html[idx: html.index("</form>", idx)]
        self.assertIn('name="username"', form,
                       "login-user input must have name='username'")
        self.assertIn('name="password"', form,
                       "login-pass input must have name='password'")

    def test_login_submit_button_is_type_submit(self):
        """Submit button must be type=submit so <form> onsubmit fires
        on Enter AND click, unifying the submission path."""
        html = _html()
        idx = html.index('id="login-submit-btn"')
        btn = html[idx: html.index(">", idx)]
        self.assertIn('type="submit"', btn,
                       "Login submit button must be type='submit'")


class TestDoLoginDropsAutofillFlushHack(unittest.TestCase):
    """The 'Force browser to flush autofill values' dispatchEvent hack
    in doLogin() was a READ-only trick that masked the deeper bug.
    With the form wrapper in place, the hack is no longer needed."""

    def test_no_dispatch_event_autofill_flush(self):
        src = _js()
        idx = src.index("function doLogin")
        fn = src[idx: src.index("\nfunction ", idx)]
        self.assertNotIn(
            "userEl.dispatchEvent(new Event('input'",
            fn,
            "doLogin must not dispatch synthetic input events as an autofill-flush hack",
        )
        self.assertNotIn(
            "passEl.dispatchEvent(new Event('input'",
            fn,
            "doLogin must not dispatch synthetic input events as an autofill-flush hack",
        )


class TestLoginFormSubmitHandler(unittest.TestCase):
    """registerLoginBindings must attach an onsubmit handler that calls
    preventDefault() + doLogin() — same entry point for click, Enter,
    and autofill-triggered submission."""

    def _binding_fn(self):
        src = _js()
        idx = src.index("function registerLoginBindings")
        return src[idx: src.index("\n}", idx) + 2]

    def test_binds_form_submit(self):
        fn = self._binding_fn()
        self.assertIn("login-form", fn,
                       "registerLoginBindings must target #login-form")
        self.assertIn("addEventListener('submit'", fn,
                       "must attach a submit event listener")

    def test_submit_handler_prevents_default(self):
        fn = self._binding_fn()
        self.assertIn("preventDefault()", fn,
                       "Submit handler must call preventDefault()")

    def test_submit_handler_calls_do_login(self):
        fn = self._binding_fn()
        self.assertIn("doLogin()", fn,
                       "Submit handler must call doLogin()")

    def test_submit_handler_idempotent(self):
        """The binding must be idempotent (._freqBound guard) so
        repeated calls to registerLoginBindings() don't stack handlers."""
        fn = self._binding_fn()
        self.assertIn("_freqBound", fn,
                       "registerLoginBindings must be idempotent via _freqBound guard")


class TestLoginOverlayDropsPointerInterception(unittest.TestCase):
    """Defect B fix: _showApp() must drop pointer-events on
    login-overlay immediately, not on the 600ms delayed display-flip.
    Otherwise the overlay intercepts clicks during the hand-off."""

    def test_show_app_drops_pointer_events_before_setTimeout(self):
        src = _js()
        idx = src.index("function _showApp")
        # _showApp is long — just grab 3000 chars
        block = src[idx: idx + 3000]
        # Find the Promise.all().then( block and the setTimeout
        promise_idx = block.index("Promise.all")
        post_promise = block[promise_idx:]
        setTimeout_idx = post_promise.index("setTimeout")
        # Before the setTimeout, we must drop pointer-events on login
        pre_setTimeout = post_promise[:setTimeout_idx]
        self.assertIn("pointerEvents='none'", pre_setTimeout,
                       "_showApp must set login.style.pointerEvents='none' before setTimeout hide")

    def test_pointer_events_drop_targets_login_overlay(self):
        src = _js()
        idx = src.index("function _showApp")
        block = src[idx: idx + 3000]
        # login var is already scoped in _showApp — we use it
        self.assertIn("login.style.pointerEvents='none'", block,
                       "pointerEvents drop must target the login overlay reference")


if __name__ == "__main__":
    unittest.main()
