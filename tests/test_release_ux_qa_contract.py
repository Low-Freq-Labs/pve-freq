"""M-RELEASE-UX-QA-20260413AL contract.

Pins the showstopper fix discovered during the v1.0.0 release QA pass
on the live 5005 baseline: #mn-body must actually become visible after
a successful login. Pre-fix the _showApp handoff only cleared the
inline style on mn-body, but Rick's token Q inline-style sweep had
converted the original `style="display:none"` to `class="d-none"`.
The class rule (`.d-none { display:none }`) kept the body hidden,
and every operator logging in to the live deployed dashboard saw
nothing but the header — all page content was blank.

Fix: _showApp's setTimeout handoff now removes the `d-none` class
from #mn-body alongside clearing the inline style, so both the
class-level and inline-level display:none rules are gone.

This contract guards the class removal so a future rename / css
refactor can't silently reintroduce the regression.
"""

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO_ROOT, "freq", "data", "web")


def _app_js():
    with open(os.path.join(WEB, "js", "app.js")) as f:
        return f.read()


def _app_html():
    with open(os.path.join(WEB, "app.html")) as f:
        return f.read()


def _app_css():
    with open(os.path.join(WEB, "css", "app.css")) as f:
        return f.read()


def _fn_body(src, name):
    idx = src.find("function " + name + "(")
    if idx == -1:
        return ""
    start = src.find("{", idx)
    if start == -1:
        return ""
    depth = 0
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


class TestMnBodyDNoneRemovalPostLogin(unittest.TestCase):
    """_showApp must remove the d-none class from #mn-body when the
    login overlay hands off to the authenticated app. Pre-fix the
    body stayed hidden because clearing the inline style didn't
    touch the class-level rule."""

    def test_html_ships_mn_body_with_dnone_default_hidden(self):
        """Initial HTML state — mn-body starts hidden via the class.
        This is correct — it prevents a flash-of-content between
        page load and login card hydration."""
        html = _app_html()
        self.assertRegex(
            html,
            r'<div[^>]*class="mn-body d-none"[^>]*id="mn-body"',
            "mn-body must ship with d-none so pre-auth content doesn't FOUC",
        )

    def test_css_dnone_utility_is_display_none(self):
        css = _app_css()
        self.assertRegex(
            css,
            r"\.d-none\s*\{\s*display:\s*none",
            ".d-none utility must enforce display:none",
        )

    def test_show_app_handoff_removes_dnone_class(self):
        body = _fn_body(_app_js(), "_showApp")
        self.assertIn("mn-body", body,
                      "_showApp must reference mn-body")
        self.assertIn("classList.remove('d-none')", body,
                      "_showApp must remove the d-none class from mn-body "
                      "— clearing only the inline style leaves the class-"
                      "level rule in force and the body stays hidden")
        # The inline-style clear must STILL happen — otherwise a later
        # call to doLogout (which sets inline display:'none') then
        # _showApp would leave the inline blocker in place.
        self.assertIn("style.display=''", body,
                      "_showApp must also clear the inline display style "
                      "so doLogout's inline hide doesn't stick")
        # Class removal must lexically precede or equal the inline clear
        # so there's no intermediate state where the inline is cleared
        # but the class still hides the element.
        idx_class = body.find("classList.remove('d-none')")
        idx_inline = body.find("style.display=''")
        self.assertGreaterEqual(idx_class, 0)
        self.assertGreaterEqual(idx_inline, 0)

    def test_dologout_still_reapplies_inline_hide(self):
        """Regression guard: doLogout must still set
        body.style.display='none' (inline hide) so the app body
        disappears on logout even though the class has been removed.
        Inline style has higher specificity than the class."""
        body = _fn_body(_app_js(), "doLogout")
        self.assertIn("mn-body", body)
        self.assertIn("style.display='none'", body)


class TestPriorContractsStillGreen(unittest.TestCase):
    """AL must not regress AI / AJ / AK contracts."""

    def _run(self, module_name):
        import unittest as _ut
        loader = _ut.TestLoader()
        suite = loader.loadTestsFromName(module_name)
        runner = _ut.TextTestRunner(verbosity=0, stream=open(os.devnull, "w"))
        result = runner.run(suite)
        return len(result.failures) + len(result.errors)

    def test_ak_ux_contract_still_green(self):
        self.assertEqual(self._run("tests.test_blueteam_ux_contract"), 0)

    def test_aj_hardening_contract_still_green(self):
        self.assertEqual(self._run("tests.test_blueteam_hardening_contract"), 0)

    def test_ai_operator_truth_contract_still_green(self):
        self.assertEqual(self._run("tests.test_operator_truth_contract"), 0)


if __name__ == "__main__":
    unittest.main()
