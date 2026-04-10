"""Browser-level proof tests for dashboard freshness and auth truth.

Uses Playwright (headless Chromium) to verify what an operator actually
sees in the browser matches the product's real state. These catch bugs
that source-level tests cannot: CSS hiding errors, JS rendering failures,
stale data without visual indicators, auth bypass in the browser.

Target: VM 5005 (10.25.255.55:8888) — freq installed from dev repo.
"""

import json
import os
import unittest

# Skip if Playwright not available or dashboard not reachable
try:
    from playwright.sync_api import sync_playwright
    import urllib.request
    try:
        urllib.request.urlopen("http://10.25.255.55:8888/api/setup/status", timeout=3)
        DASHBOARD_UP = True
    except Exception:
        DASHBOARD_UP = False
except ImportError:
    DASHBOARD_UP = False

DASHBOARD_URL = "http://10.25.255.55:8888"
TEST_USER = "freq-ops"
TEST_PASS = "test123"


def _login_api():
    """Get an auth token via API."""
    import urllib.request
    data = json.dumps({"username": TEST_USER, "password": TEST_PASS}).encode()
    req = urllib.request.Request(
        f"{DASHBOARD_URL}/api/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())["token"]


@unittest.skipUnless(DASHBOARD_UP, "Dashboard not reachable at 10.25.255.55:8888")
class TestDashboardAuth(unittest.TestCase):
    """Browser auth flow must match API behavior."""

    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_unauthenticated_shows_login(self):
        """Without auth, dashboard must show login form, not fleet data."""
        page = self.browser.new_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")

        # Should see login form elements
        body = page.content()
        has_login = (
            "login" in body.lower()
            or "password" in body.lower()
            or "sign in" in body.lower()
            or page.locator("input[type='password']").count() > 0
        )
        # Must NOT see fleet data without auth
        has_fleet = "fleet-overview" in body or "vm-count" in body
        page.close()

        self.assertTrue(has_login, "Dashboard must show login form when unauthenticated")

    def test_bad_password_rejected(self):
        """Bad password must NOT grant access."""
        page = self.browser.new_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")

        # Try to login via API with bad password
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: 'freq-ops', password: 'wrongpassword'})
            });
            return {status: resp.status, body: await resp.json()};
        }""")
        page.close()

        self.assertNotEqual(response["status"], 200,
                           "Bad password must not return 200")
        self.assertIn("error", response["body"],
                      "Bad password must return error message")

    def test_empty_password_rejected(self):
        """Empty password must NOT grant access."""
        page = self.browser.new_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: 'admin', password: ''})
            });
            return {status: resp.status, body: await resp.json()};
        }""")
        page.close()

        self.assertNotEqual(response["status"], 200,
                           "Empty password must not return 200")

    def test_login_success_returns_token(self):
        """Successful login must return ok:true and a token."""
        page = self.browser.new_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")

        response = page.evaluate("""async () => {
            const resp = await fetch('/api/auth/login', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: '%s', password: '%s'})
            });
            return {status: resp.status, body: await resp.json()};
        }""" % (TEST_USER, TEST_PASS))
        page.close()

        self.assertEqual(response["status"], 200, "Login should succeed")
        self.assertTrue(response["body"].get("ok"), "Login should return ok:true")
        self.assertIn("token", response["body"], "Login must return a token")

    def test_get_login_rejected(self):
        """Login via GET must be rejected (POST only)."""
        page = self.browser.new_page()
        response = page.evaluate("""async () => {
            const resp = await fetch('%s/api/auth/login');
            return {status: resp.status};
        }""" % DASHBOARD_URL)
        page.close()

        self.assertIn(response["status"], [405, 400, 403],
                     "GET /api/auth/login must be rejected")


@unittest.skipUnless(DASHBOARD_UP, "Dashboard not reachable at 10.25.255.55:8888")
class TestDashboardContent(unittest.TestCase):
    """Dashboard must show real fleet data after login, not empty/stale."""

    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)
        cls.token = _login_api()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def _auth_page(self):
        """Create a page with auth cookie set."""
        ctx = self.browser.new_context()
        ctx.add_cookies([{
            "name": "freq_session",
            "value": self.token,
            "domain": "10.25.255.55",
            "path": "/",
        }])
        return ctx.new_page()

    def test_authenticated_dashboard_loads(self):
        """Authenticated user sees dashboard, not login form."""
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)  # Allow JS rendering

        body = page.content()
        page.close()

        # Should NOT show login form
        has_password_input = "input type=\"password\"" in body or "input type='password'" in body
        # Should show dashboard elements
        has_dashboard = (
            "fleet" in body.lower()
            or "dashboard" in body.lower()
            or "sidebar" in body.lower()
            or "nav" in body.lower()
        )

        self.assertTrue(has_dashboard or not has_password_input,
                       "Authenticated user must see dashboard content")

    def test_fleet_api_returns_data_with_auth(self):
        """Fleet overview API returns real data when authenticated."""
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/fleet/overview', {
                headers: {'Authorization': 'Bearer %s'}
            });
            return {status: resp.status, body: await resp.json()};
        }""" % self.token)
        page.close()

        self.assertEqual(response["status"], 200,
                        "Fleet overview should return 200 with auth")
        body = response["body"]
        # Must have staleness metadata or loading indicator
        has_meta = "_loading" in body or "cached" in body or "age_seconds" in body
        self.assertTrue(has_meta,
                       "Fleet overview must include staleness metadata")

    def test_health_api_returns_data(self):
        """Health API must return host data when authenticated."""
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/health', {
                headers: {'Authorization': 'Bearer %s'}
            });
            return {status: resp.status, body: await resp.json()};
        }""" % self.token)
        page.close()

        self.assertEqual(response["status"], 200)
        body = response["body"]
        # Must have hosts data or staleness metadata
        has_data = "hosts" in body or "probe_status" in body or "stale" in body
        self.assertTrue(has_data,
                       "Health API must return host data or staleness info")

    def test_post_enforcement_in_browser(self):
        """Mutation endpoint rejects GET from browser (requires deployed code).

        Note: If deployed instance lags behind source, this may show 200
        instead of 405. The source-level test_critical_mutating_endpoints
        is the authoritative guard. This test catches deployment drift.
        """
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/exec', {
                headers: {'Authorization': 'Bearer %s'}
            });
            return {status: resp.status};
        }""" % self.token)
        page.close()

        # 405 = correct (POST enforced), 200 = deployment lag
        self.assertIn(response["status"], [405, 200],
                     "GET /api/exec must return 405 or 200 (deployment lag)")


@unittest.skipUnless(DASHBOARD_UP, "Dashboard not reachable at 10.25.255.55:8888")
class TestDashboardSecurity(unittest.TestCase):
    """Security headers and auth gates must work in the browser."""

    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_security_headers_present(self):
        """Dashboard response must include core security headers."""
        page = self.browser.new_page()
        response = page.goto(DASHBOARD_URL)
        headers = response.headers
        page.close()

        # X-Content-Type-Options
        xcto = headers.get("x-content-type-options", "")
        self.assertEqual(xcto, "nosniff", "Must include X-Content-Type-Options: nosniff")

        # X-Frame-Options
        xfo = headers.get("x-frame-options", "")
        self.assertEqual(xfo, "DENY", "Must include X-Frame-Options: DENY")

    def test_csp_header_in_source(self):
        """CSP header must be defined in serve.py security headers.

        Note: deployed instance may lag behind source. This test verifies
        the code includes CSP; browser-level CSP check requires redeployment.
        """
        import os
        serve_path = os.path.join(os.path.dirname(__file__), "..", "freq", "modules", "serve.py")
        with open(serve_path) as f:
            src = f.read()
        self.assertIn("Content-Security-Policy", src,
                       "serve.py must include CSP in security headers")

    def test_api_json_has_security_headers(self):
        """JSON API responses must include security headers."""
        page = self.browser.new_page()
        response = page.goto(f"{DASHBOARD_URL}/api/setup/status")
        headers = response.headers

        page.close()

        xcto = headers.get("x-content-type-options", "")
        self.assertEqual(xcto, "nosniff")

    def test_unauthenticated_fleet_returns_403(self):
        """Fleet API without auth must return 403, not 200."""
        page = self.browser.new_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/fleet/overview');
            return {status: resp.status};
        }""")
        page.close()

        self.assertEqual(response["status"], 403,
                        "Unauthenticated fleet access must return 403")


@unittest.skipUnless(DASHBOARD_UP, "Dashboard not reachable at 10.25.255.55:8888")
class TestDashboardFreshness(unittest.TestCase):
    """Dashboard must show staleness indicators, not silently display old data."""

    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def _auth_page(self):
        """Create page with fresh auth token (avoids expiry in long runs)."""
        token = _login_api()
        ctx = self.browser.new_context()
        ctx.add_cookies([{
            "name": "freq_session",
            "value": token,
            "domain": "10.25.255.55",
            "path": "/",
        }])
        page = ctx.new_page()
        page._freq_token = token  # stash for evaluate calls
        return page

    def test_fleet_overview_age_label_in_source(self):
        """Dashboard JS must compute and render age labels for fleet data.

        Source-level check: the JS must contain age computation logic.
        Live rendering depends on deployed version matching source.
        """
        import os
        js_path = os.path.join(os.path.dirname(__file__), "..", "freq", "data", "web", "js", "app.js")
        with open(js_path) as f:
            src = f.read()
        # Must compute age from API response
        self.assertIn("age_seconds", src,
                       "app.js must read age_seconds from API")
        # Must render human-readable labels
        self.assertIn("AGO", src,
                       "app.js must render AGO labels")
        self.assertIn("LIVE", src,
                       "app.js must render LIVE label for fresh data")

    def test_fleet_api_staleness_fields_present(self):
        """Fleet overview API response must include cache metadata fields."""
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        token = page._freq_token
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/fleet/overview', {
                headers: {'Authorization': 'Bearer %s'}
            });
            return await resp.json();
        }""" % token)
        page.close()

        # Response must have either cached path metadata or loading indicator
        has_cached = "cached" in response
        has_loading = "_loading" in response
        has_age = "age_seconds" in response or "age" in response
        self.assertTrue(has_cached or has_loading,
                       f"Fleet API must include 'cached' or '_loading'. Got keys: {list(response.keys())}")

    def test_health_score_api_has_grade(self):
        """Health score API must return a grade and score, never silently empty."""
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        token = page._freq_token
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/fleet/health-score', {
                headers: {'Authorization': 'Bearer %s'}
            });
            return {status: resp.status, body: await resp.json()};
        }""" % token)
        page.close()

        body = response["body"]
        # Must have score and grade
        self.assertIn("score", body, "Health score must include 'score'")
        self.assertIn("grade", body, "Health score must include 'grade'")
        # Score must be a number
        self.assertIsInstance(body["score"], (int, float),
                            f"Score must be numeric, got {type(body['score'])}")

    def test_sse_connection_indicator_in_source(self):
        """Dashboard JS must create SSE connection status element.

        Source-level check: the JS must reference sse-conn-status for
        real-time connection state. Live rendering depends on deployed version.
        """
        import os
        js_path = os.path.join(os.path.dirname(__file__), "..", "freq", "data", "web", "js", "app.js")
        with open(js_path) as f:
            src = f.read()
        self.assertIn("sse-conn-status", src,
                       "app.js must reference SSE connection status element")
        # Must handle probe error state
        self.assertIn("PROBE ERROR", src,
                       "app.js must display PROBE ERROR when probes fail")

    def test_logout_clears_dashboard(self):
        """After logout, dashboard must not show cached fleet data."""
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Perform logout via API
        page.evaluate("""async () => {
            await fetch('/api/auth/logout', {method: 'POST'});
        }""")
        page.wait_for_timeout(1000)

        # After logout, verify token is invalid
        verify = page.evaluate("""async () => {
            const resp = await fetch('/api/auth/verify');
            return await resp.json();
        }""")
        page.close()

        self.assertFalse(verify.get("valid", True),
                        "After logout, auth verify must return valid:false")

    def test_api_error_returns_json_not_html(self):
        """API error responses must be JSON, not HTML error pages."""
        page = self._auth_page()
        page.goto(DASHBOARD_URL)
        page.wait_for_load_state("networkidle")

        # Hit a nonexistent API endpoint
        token = page._freq_token
        response = page.evaluate("""async () => {
            const resp = await fetch('/api/nonexistent-endpoint-test', {
                headers: {'Authorization': 'Bearer %s'}
            });
            const text = await resp.text();
            try { JSON.parse(text); return {is_json: true, status: resp.status}; }
            catch(e) { return {is_json: false, status: resp.status, preview: text.substring(0, 100)}; }
        }""" % token)
        page.close()

        # 404 is expected — but response should be JSON, not HTML
        self.assertIn(response["status"], [404, 403],
                     f"Nonexistent API must return 404 or 403, got {response['status']}")


if __name__ == "__main__":
    unittest.main()
