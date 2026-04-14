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


class TestSetupHealthDegradedAllowlist(unittest.TestCase):
    """AI regression fix: setup_health='configured' must be treated as
    healthy. The guard lives in a named helper so both the pre- and
    post-auth banner renderers share the same deny-list."""

    def test_helper_function_exists(self):
        self.assertIn("function _isDegradedSetupHealth", _app_js())

    def test_helper_deny_lists_known_bad_values(self):
        body = _fn_body(_app_js(), "_isDegradedSetupHealth")
        for bad in ("partial", "incomplete", "degraded",
                    "error", "failed", "unhealthy", "broken"):
            with self.subTest(bad=bad):
                self.assertIn(f"'{bad}'", body,
                              f"deny-list must include '{bad}'")

    def test_helper_returns_false_for_unknown_and_healthy_values(self):
        """Static check: the helper's only positive return is the
        comparison chain against the deny-list. Any value that doesn't
        match must fall through to `return false`."""
        body = _fn_body(_app_js(), "_isDegradedSetupHealth")
        self.assertIn("return false", body,
                      "helper must early-return false on falsy input")
        # No string compares for 'configured' / 'ok' / 'healthy' —
        # those are implicitly healthy via the deny-list fall-through.
        self.assertNotIn("'configured'", body,
                         "'configured' must NOT be in the deny-list")

    def test_both_banner_renderers_use_the_helper(self):
        """After the product-law refactor both renderers consume the
        shared _setupTruthSummary helper which calls
        _isDegradedSetupHealth — so the deny-list allowlist applies to
        both surfaces transitively. The anti-regression check stays:
        the deny-by-default 'not ok and not healthy' pattern must not
        return anywhere in the pipeline."""
        src = _app_js()
        pre_body = _fn_body(src, "_renderSetupTruthBanner")
        post_body = _fn_body(src, "_renderPostAuthTruthBanner")
        summary = _fn_body(src, "_setupTruthSummary")
        self.assertIn("_setupTruthSummary", pre_body,
                      "pre-auth renderer must consume _setupTruthSummary")
        self.assertIn("_setupTruthSummary", post_body,
                      "post-auth renderer must consume _setupTruthSummary")
        self.assertIn("_isDegradedSetupHealth", summary,
                      "_setupTruthSummary must apply the deny-list helper "
                      "so both renderers transitively use the allowlist")
        # Anti-regression: the old off-by-one string comparison must
        # not return anywhere in the pipeline.
        for body in (pre_body, post_body, summary):
            self.assertNotRegex(
                body,
                r"setup_health!=='ok'&&d\.setup_health!=='healthy'",
                "old 'not ok and not healthy' deny-by-default pattern "
                "must not return — use _isDegradedSetupHealth allowlist",
            )


class TestCspFrameAncestorsAndLockdown(unittest.TestCase):
    """CSP must carry frame-ancestors 'none' (clickjacking defense-in-
    depth with X-Frame-Options), base-uri 'none' (no attacker <base>),
    form-action 'self' (no attacker form target), object-src 'none'
    (no plugin surface)."""

    def test_security_header_block_carries_each_directive(self):
        body = _py_fn_body(_serve_py(), "_send_security_headers")
        for directive in (
            "frame-ancestors 'none'",
            "base-uri 'none'",
            "form-action 'self'",
            "object-src 'none'",
        ):
            with self.subTest(directive=directive):
                self.assertIn(directive, body,
                              f"_send_security_headers CSP must carry {directive}")


class TestPermissionsPolicyHeader(unittest.TestCase):
    """Permissions-Policy must explicitly deny every browser feature
    the dashboard never uses so an XSS cannot pivot to hardware."""

    def test_permissions_policy_sent(self):
        body = _py_fn_body(_serve_py(), "_send_security_headers")
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

    def test_hsts_gated_on_ssl_socket(self):
        body = _py_fn_body(_serve_py(), "_send_security_headers")
        self.assertIn("Strict-Transport-Security", body)
        self.assertIn("SSLSocket", body,
                      "HSTS must be gated on an isinstance(request, SSLSocket) check")
        self.assertIn("max-age=31536000", body)
        self.assertIn("includeSubDomains", body)
        # Explicit: must not be inside an unconditional send_header at
        # the top of the function. The isinstance gate must lexically
        # precede the Strict-Transport-Security send_header call.
        hsts_idx = body.find("Strict-Transport-Security")
        ssl_idx = body.find("SSLSocket")
        self.assertLess(ssl_idx, hsts_idx,
                        "SSLSocket isinstance check must lexically precede "
                        "the HSTS send_header call")


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

    def test_helpers_json_response_drops_acao_send_header(self):
        body = _py_fn_body(_helpers_py(), "json_response")
        self.assertNotRegex(
            body,
            r"send_header\(\s*['\"]Access-Control-Allow-Origin",
            "helpers.py json_response must not send ACAO",
        )
        self.assertNotIn('handler.headers.get("Origin"', body)

    def test_auth_login_drops_acao_send_header(self):
        body = _py_fn_body(_auth_py(), "handle_auth_login")
        self.assertNotRegex(
            body,
            r"send_header\(\s*['\"]Access-Control-Allow-Origin",
            "auth.py handle_auth_login must not send ACAO",
        )

    def test_no_reflected_origin_pattern_remains_in_web_paths(self):
        """Any file under freq/api or freq/modules that still CALLS
        send_header with an ACAO directive is a regression. Grep-level
        guard — catches future drift even if a new helper is added.
        Comment mentions are allowed so the post-fix rationale can
        reference the header name."""
        import subprocess
        rg = subprocess.run(
            ["grep", "-rIn",
             "send_header.*Access-Control-Allow-Origin",
             os.path.join(REPO_ROOT, "freq", "api"),
             os.path.join(REPO_ROOT, "freq", "modules")],
            capture_output=True, text=True,
        )
        hits = [line for line in rg.stdout.splitlines()
                if "agent_collector" not in line]
        self.assertEqual(hits, [],
                         "no send_header('Access-Control-Allow-Origin'...) "
                         "should remain in freq/api or freq/modules "
                         "(agent_collector.py is a separate airgapped "
                         "surface, excluded). Hits:\n" + "\n".join(hits))


class TestConfirmActionSanitizer(unittest.TestCase):
    """confirmAction must build the DOM via createElement and pass
    msg through _sanitizeHtmlFragment, which whitelists an inert tag
    set and strips all attributes."""

    def test_sanitize_helper_exists_and_strips_attributes(self):
        src = _app_js()
        self.assertIn("function _sanitizeHtmlFragment", src)
        body = _fn_body(src, "_sanitizeHtmlFragment")
        self.assertIn("removeAttribute", body,
                      "sanitizer must strip attributes on surviving tags")
        for allowed in ("STRONG", "EM", "B", "I", "BR"):
            with self.subTest(allowed=allowed):
                self.assertIn(f"'{allowed}':1", body,
                              f"sanitizer allowlist must include {allowed}")
        # Comment nodes must be removed (they can't execute but they
        # leak payloads via dev tools).
        self.assertIn("nodeType===8", body)

    def test_confirmAction_uses_createElement_and_sanitizer(self):
        body = _fn_body(_app_js(), "confirmAction")
        self.assertIn("_sanitizeHtmlFragment", body,
                      "confirmAction must pass msg through _sanitizeHtmlFragment")
        self.assertIn("createElement", body,
                      "confirmAction must build the modal via createElement")
        self.assertIn("addEventListener('click'", body,
                      "confirmAction must attach click handlers via addEventListener")
        # The pre-fix inline onclick attribute on the Cancel button
        # must be gone.
        self.assertNotIn("onclick=\"closeModal()\"", body)
        self.assertNotIn("onclick='closeModal()'", body)


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
        body = _fn_body(_app_js(), "vaultReveal")
        self.assertIn("setTimeout", body,
                      "vaultReveal must arm a setTimeout on reveal")
        self.assertIn("VAULT_REVEAL_TIMEOUT_MS", body,
                      "vaultReveal must use the VAULT_REVEAL_TIMEOUT_MS constant")
        self.assertIn("_vaultRevealTimers", body,
                      "vaultReveal must track timers in _vaultRevealTimers")

    def test_hide_helper_clears_timer(self):
        body = _fn_body(_app_js(), "_hideVaultSecret")
        self.assertIn("_clearVaultRevealTimer", body,
                      "_hideVaultSecret must clear the pending timer")
        self.assertIn("removeAttribute('data-revealed')", body)


class TestAiContractStillGreen(unittest.TestCase):
    """Regression guard: the AI truth-banner contract must still pass
    after AJ lands. Runs the AI test module programmatically and
    asserts 0 failures / 0 errors."""

    def test_ai_contract_still_passes(self):
        import unittest as _ut
        loader = _ut.TestLoader()
        suite = loader.loadTestsFromName("tests.test_operator_truth_contract")
        runner = _ut.TextTestRunner(verbosity=0, stream=open(os.devnull, "w"))
        result = runner.run(suite)
        self.assertEqual(
            len(result.failures) + len(result.errors), 0,
            f"AI contract regressed under AJ: {result.failures} {result.errors}",
        )


if __name__ == "__main__":
    unittest.main()
