"""M-BLUETEAM-SECURITY-UX-20260413AK contract.

Pins the blue-team UX follow-through landed on top of Rick's token T
(3cd52ad). Four concrete surfaces:

  1. /api/auth/verify returns session_age_s / session_ttl_s /
     session_timeout_s so the UI can render a persistent session-age
     badge — pre-fix there was no way to tell a fresh session from
     one about to time out mid-operation.

  2. User menu rewritten via createElement + addEventListener (no
     more innerHTML with inline onclick/onmouseover attributes —
     same footgun class AJ closed on confirmAction). Menu now
     carries a SESSION AGE · EXPIRES IN badge and a CHANGE
     PASSWORD action.

  3. Change-password modal wires the dashboard to /api/auth/
     change-password (which Rick hardened under T-1/T-2) with all
     four UX affordances:
       - current_password + new + confirm fields
       - inline error surfacing "Current password is incorrect"
         distinctly from "too short" / "mismatch" / "same as current"
       - success toast names the sessions_purged count so the
         operator sees what just happened to their other tabs
       - bare fetch (not _authFetch) so a wrong-password 401 doesn't
         flow through the auth-failure teardown and kick the
         operator to the login card mid-rotation

  4. confirmDestructive type-to-confirm friction: a wrapper over
     confirmAction that requires the operator to type an expected
     string (VMID for vmDestroy, station prefix for gwipeWipeAll)
     before the CONFIRM button enables. Defeats muscle-memory
     click-through on run-of-the-mill destructive modals.

All tests are source-level — no running server required.
"""

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO_ROOT, "freq", "data", "web")


def _read(path):
    with open(path) as f:
        return f.read()


def _app_js():
    return _read(os.path.join(WEB, "js", "app.js"))


def _auth_py():
    return _read(os.path.join(REPO_ROOT, "freq", "api", "auth.py"))


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


def _py_fn_body(src, name):
    """Extract a Python def NAME(...) body by indentation."""
    lines = src.splitlines()
    start = None
    base_indent = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(\s*)def\s+" + re.escape(name) + r"\s*\(", ln)
        if m:
            start = i
            base_indent = len(m.group(1))
            break
    if start is None:
        return ""
    body = [lines[start]]
    for j in range(start + 1, len(lines)):
        ln = lines[j]
        stripped = ln.strip()
        if stripped == "":
            body.append(ln)
            continue
        indent = len(ln) - len(ln.lstrip())
        if indent <= base_indent:
            break
        body.append(ln)
    return "\n".join(body)


class TestAuthVerifyExposesSessionAgeAndTtl(unittest.TestCase):
    """handle_auth_verify must return session_age_s, session_ttl_s,
    and session_timeout_s so the UI session-age badge can render."""

    def test_verify_handler_sets_three_session_fields(self):
        body = _py_fn_body(_auth_py(), "handle_auth_verify")
        self.assertIn('"session_age_s"', body,
                      "handle_auth_verify must emit session_age_s")
        self.assertIn('"session_ttl_s"', body,
                      "handle_auth_verify must emit session_ttl_s")
        self.assertIn('"session_timeout_s"', body,
                      "handle_auth_verify must emit session_timeout_s")

    def test_verify_handler_computes_age_from_ts(self):
        body = _py_fn_body(_auth_py(), "handle_auth_verify")
        self.assertIn('session.get("ts"', body,
                      "age must be computed from session['ts']")
        self.assertIn("SESSION_TIMEOUT_SECONDS", body,
                      "ttl must reference SESSION_TIMEOUT_SECONDS")
        # Age must be clamped to >=0 so a clock skew doesn't produce
        # a negative number that breaks the UI badge color mapping.
        self.assertIn("max(0", body)


class TestUserMenuRewrite(unittest.TestCase):
    """openUserMenu must build the modal with createElement +
    addEventListener, carry the session badge slot, and expose the
    CHANGE PASSWORD action."""

    def test_user_menu_uses_createElement_not_innerHTML(self):
        body = _fn_body(_app_js(), "openUserMenu")
        self.assertIn("createElement", body,
                      "openUserMenu must build DOM via createElement")
        self.assertIn("addEventListener", body,
                      "openUserMenu must attach handlers via addEventListener")
        # Anti-regression: the old inline-handler patterns must be gone.
        self.assertNotIn("onclick=\"closeModal();doLogout()\"", body)
        self.assertNotIn("onmouseover=\\'this.style", body)
        # Must not reassign modal-container via ov.innerHTML = '<div...'.
        self.assertNotRegex(body, r"ov\.innerHTML\s*=\s*['\"]")

    def test_user_menu_has_session_badge_slot(self):
        body = _fn_body(_app_js(), "openUserMenu")
        self.assertIn("user-menu-session-badge", body,
                      "user menu must carry a session-badge slot")
        self.assertIn("SESSION AGE", body,
                      "badge must label the age field")
        self.assertIn("EXPIRES IN", body,
                      "badge must label the ttl field")
        self.assertIn("_formatDuration", body,
                      "badge must format via _formatDuration helper")
        # Must pull from /api/auth/verify so the server is the source
        # of truth for session age (not clock-drift on the client).
        self.assertIn("AUTH_VERIFY", body)

    def test_user_menu_has_change_password_button(self):
        body = _fn_body(_app_js(), "openUserMenu")
        self.assertIn("CHANGE PASSWORD", body)
        self.assertIn("openChangePasswordModal", body,
                      "CHANGE PASSWORD button must open the change-password modal")

    def test_format_duration_helper_exists(self):
        src = _app_js()
        self.assertIn("function _formatDuration", src)
        body = _fn_body(src, "_formatDuration")
        # Must handle seconds/minutes/hours and clamp to >= 0.
        self.assertIn("Math.max(0", body)
        self.assertIn("3600", body)


class TestChangePasswordModalWiring(unittest.TestCase):
    """openChangePasswordModal + _submitChangePassword must cover the
    four UX affordances required by AK."""

    def test_modal_function_exists(self):
        src = _app_js()
        self.assertIn("function openChangePasswordModal", src)
        self.assertIn("function _submitChangePassword", src)

    def test_modal_has_three_inputs(self):
        body = _fn_body(_app_js(), "openChangePasswordModal")
        for input_id in ("cp-current", "cp-new", "cp-confirm"):
            with self.subTest(input_id=input_id):
                self.assertIn(input_id, body,
                              f"modal must include input #{input_id}")
        # Error slot for inline messaging.
        self.assertIn("cp-err", body)
        # Uses createElement — not innerHTML.
        self.assertIn("createElement", body)
        self.assertNotRegex(body, r"ov\.innerHTML\s*=\s*['\"]<div")

    def test_submit_path_uses_bare_fetch_not_authfetch(self):
        body = _fn_body(_app_js(), "_submitChangePassword")
        self.assertIn("fetch(API.AUTH_CHANGE_PW", body,
                      "change-password must use bare fetch, not _authFetch")
        self.assertNotIn("_authFetch(API.AUTH_CHANGE_PW", body,
                         "bare fetch required so a 401 doesn't recurse "
                         "through the auth-failure teardown")
        # POST JSON body with both current_password and password.
        self.assertIn("current_password:cur", body)
        self.assertIn("password:pw", body)
        self.assertIn("Content-Type", body)

    def test_submit_validates_min_length_and_mismatch(self):
        body = _fn_body(_app_js(), "_submitChangePassword")
        self.assertIn("length<8", body,
                      "must enforce minimum password length client-side")
        self.assertIn("pw!==cfm", body,
                      "must check new/confirm mismatch")
        # Anti-footgun: new password must differ from current.
        self.assertIn("pw===cur", body,
                      "must reject new == current")

    def test_success_toast_names_sessions_purged_count(self):
        body = _fn_body(_app_js(), "_submitChangePassword")
        self.assertIn("sessions_purged", body,
                      "success path must surface d.sessions_purged")
        self.assertIn("stale session", body,
                      "success toast must name the purged count honestly")

    def test_error_path_surfaces_server_error_inline(self):
        body = _fn_body(_app_js(), "_submitChangePassword")
        # On a non-200/non-ok response the inline errEl must carry the
        # server's error string, not a generic "login failed".
        self.assertIn("errEl.textContent=d.error", body,
                      "error path must show d.error in the inline slot")


class TestConfirmDestructiveTypeToConfirm(unittest.TestCase):
    """confirmDestructive must require exact text input before the
    CONFIRM button enables, and the two highest-blast destructive
    actions (vmDestroy, gwipeWipeAll) must use it."""

    def test_helper_exists_and_builds_safely(self):
        src = _app_js()
        self.assertIn("function confirmDestructive", src)
        body = _fn_body(src, "confirmDestructive")
        # Must use createElement + _sanitizeHtmlFragment — no innerHTML
        # + concat of msg.
        self.assertIn("createElement", body)
        self.assertIn("_sanitizeHtmlFragment", body)
        # Input must match expected exactly, not substring / loose.
        self.assertIn("inp.value===expected", body,
                      "match must be strict equality on the full value")
        # Button must start disabled and flip on input match.
        self.assertIn("confirmBtn.disabled=true", body)
        self.assertIn("confirmBtn.disabled=!ok", body)
        # Escape-on-enter via the input itself.
        self.assertIn("e.key==='Enter'", body)
        # Destructive styling on the header border.
        self.assertIn("var(--red)", body)

    def test_vmDestroy_uses_confirmDestructive(self):
        body = _fn_body(_app_js(), "vmDestroy")
        self.assertIn("confirmDestructive", body,
                      "vmDestroy must route through confirmDestructive")
        # Expected string must be the VMID so the operator has to
        # type the specific target, not a generic "DESTROY".
        self.assertIn("String(vmid)", body)
        # The old plain confirmAction path must be gone.
        self.assertNotIn("confirmAction('Destroy VM", body)

    def test_gwipeWipeAll_uses_confirmDestructive(self):
        body = _fn_body(_app_js(), "gwipeWipeAll")
        self.assertIn("confirmDestructive", body,
                      "gwipeWipeAll must route through confirmDestructive")
        # Expected string must include the station prefix so an
        # operator on station A can't type-through a confirmation
        # belonging to station B.
        self.assertIn("'WIPE '+pfx", body)
        # The old plain confirmAction path must be gone.
        self.assertNotIn("confirmAction('<strong>WIPE ALL", body)


class TestPriorContractsStillGreen(unittest.TestCase):
    """Regression guard: AK must not regress AI / AJ / earlier tokens."""

    def _run(self, module_name):
        import unittest as _ut
        loader = _ut.TestLoader()
        suite = loader.loadTestsFromName(module_name)
        runner = _ut.TextTestRunner(verbosity=0, stream=open(os.devnull, "w"))
        result = runner.run(suite)
        return len(result.failures) + len(result.errors)

    def test_ai_operator_truth_still_green(self):
        self.assertEqual(self._run("tests.test_operator_truth_contract"), 0)

    def test_aj_blueteam_hardening_still_green(self):
        self.assertEqual(self._run("tests.test_blueteam_hardening_contract"), 0)


if __name__ == "__main__":
    unittest.main()
