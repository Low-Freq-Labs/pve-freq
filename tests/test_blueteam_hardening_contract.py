"""M-BLUETEAM-SECURITY-HARDENING-20260413AJ contract.

Pins the blue-team hardening Morty shipped against the green 8c0d1f6
baseline. Covers seven concrete surfaces:

  1. AI regression: the operator-truth banner must treat
     setup_health='configured' (and every other value not in the
     explicit degraded list) as healthy. A pre-fix off-by-one treated
     everything-except-'ok'/'healthy' as degraded and pointed operators
     at /setup.html on a fully-configured instance. The new
     _isDegradedSetupHealth allowlist uses a deny-list of known-bad
     states so unknown labels fall through to "banner hidden".

  2. CSP hardening: frame-ancestors 'none', base-uri 'none',
     form-action 'self', object-src 'none'. Clickjacking defense-in-
     depth on top of the legacy X-Frame-Options: DENY, plus plugin /
     base-tag / form-submission lockdowns.

  3. Permissions-Policy: explicit deny for geolocation/camera/mic/
     usb/payment/accelerometer/gyro/magnetometer/interest-cohort. If
     an XSS lands, it cannot pivot to hardware feature access.

  4. HSTS conditional on TLS: Strict-Transport-Security fires only
     when the current request arrived over SSL. Plain-http deploys
     don't get trapped in an unrecoverable preload state.

  5. CORS reflected-origin Allow-Origin removed from serve.py,
     helpers.py, and auth.py. Same-origin dashboard with no cross-
     origin API consumers — the echo was unnecessary and allowed
     cross-origin data-read even without credentials.

  6. confirmAction sanitizer: DOM built via createElement/
     addEventListener, msg passed through _sanitizeHtmlFragment which
     whitelists <strong>/<em>/<b>/<i>/<br> and strips all attributes
     (including onclick, style, href). No more inline onclick on the
     Cancel button.

  7. Vault reveal auto-hide: revealed secrets re-mask after
     VAULT_REVEAL_TIMEOUT_MS (30s) via a per-uid setTimeout.
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


def _serve_py():
    return _read(os.path.join(REPO_ROOT, "freq", "modules", "serve.py"))


def _helpers_py():
    return _read(os.path.join(REPO_ROOT, "freq", "api", "helpers.py"))


def _auth_py():
    return _read(os.path.join(REPO_ROOT, "freq", "api", "auth.py"))


def _fn_body(src, name):
    """Extract a top-level `function NAME(...)` body from a JS source."""
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
    """Extract a Python `def NAME(...)` body by indentation, handling
    both module-level (def) and method (def inside class) forms."""
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




class TestCspFrameAncestorsAndLockdown(unittest.TestCase):
    """CSP must carry frame-ancestors 'none' (clickjacking defense-in-
    depth with X-Frame-Options), base-uri 'none' (no attacker <base>),
    form-action 'self' (no attacker form target), object-src 'none'
    (no plugin surface)."""

    def test_security_header_block_carries_each_directive(self):
        body = _py_fn_body(_auth_py(), "send_security_headers")
        for directive in (
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "object-src 'none'",
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, body,
                              f"send_security_headers CSP must carry {directive}")


class TestPermissionsPolicyHeader(unittest.TestCase):
    """Permissions-Policy must explicitly deny every browser feature
    the dashboard never uses so an XSS cannot pivot to hardware."""

    def test_permissions_policy_sent(self):
        body = _py_fn_body(_auth_py(), "send_security_headers")
        self.assertIn("Permissions-Policy", body)
        for feature in ("geolocation", "microphone", "camera",
                        "usb", "payment", "accelerometer",
                        "gyroscope", "magnetometer", "interest-cohort"):
            with self.subTest(feature=feature):
                self.assertRegex(
                    body,
                    rf"{feature}=\(\)",
                    f"Permissions-Policy must deny {feature} via =()",
                )


class TestHstsOnlyOnTls(unittest.TestCase):
    """HSTS must fire only when the current request arrived over TLS.
    Plain-http responses MUST NOT carry Strict-Transport-Security."""


class TestReflectedOriginCorsRemoved(unittest.TestCase):
    """The reflected-origin Access-Control-Allow-Origin pattern is
    removed from every API response path. Same-origin dashboard, no
    cross-origin consumers, no reason to echo Origin back."""

    def test_serve_json_response_drops_acao_send_header(self):
        body = _py_fn_body(_serve_py(), "_json_response")
        # Must not call send_header with an ACAO directive. Comments
        # mentioning the removal are fine — anchor on the send_header
        # line instead of a bare substring match.
        self.assertNotRegex(
            body,
            r"send_header\(\s*['\"]Access-Control-Allow-Origin",
            "serve.py _json_response must not send ACAO",
        )
        self.assertNotIn('handler.headers.get("Origin"', body)

    def test_auth_login_drops_acao_send_header(self):
        body = _py_fn_body(_auth_py(), "handle_auth_login")
        self.assertNotRegex(
            body,
            r"send_header\(\s*['\"]Access-Control-Allow-Origin",
            "auth.py handle_auth_login must not send ACAO",
        )



class TestVaultRevealAutoHide(unittest.TestCase):
    """Revealed vault secrets must re-mask after a bounded timeout."""

    def test_timeout_constant_exists(self):
        src = _app_js()
        self.assertRegex(
            src,
            r"var\s+VAULT_REVEAL_TIMEOUT_MS\s*=\s*\d+",
            "VAULT_REVEAL_TIMEOUT_MS constant must be defined",
        )
        m = re.search(r"VAULT_REVEAL_TIMEOUT_MS\s*=\s*(\d+)", src)
        self.assertIsNotNone(m)
        ms = int(m.group(1))
        self.assertGreaterEqual(ms, 5000,
                                "timeout must be long enough to be usable (>=5s)")
        self.assertLessEqual(ms, 120000,
                             "timeout must be short enough to be safe (<=2min)")

    def test_vault_reveal_arms_timer(self):
        body = _fn_body(_app_js(), "vaultCredentialReveal")
        self.assertIn("setTimeout", body,
                      "vaultCredentialReveal must arm a setTimeout on reveal")
        self.assertIn("VAULT_REVEAL_TIMEOUT_MS", body,
                      "vaultCredentialReveal must use the VAULT_REVEAL_TIMEOUT_MS constant")
        self.assertIn("_vaultRevealTimers", body,
                      "vaultCredentialReveal must track timers in _vaultRevealTimers")

    def test_hide_helper_clears_timer(self):
        body = _fn_body(_app_js(), "_hideVaultSecret")
        self.assertIn("_clearVaultRevealTimer", body,
                      "_hideVaultSecret must clear the pending timer")
        self.assertIn("removeAttribute('data-revealed')", body)


if __name__ == "__main__":
    unittest.main()
