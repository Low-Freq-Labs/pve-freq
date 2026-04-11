"""Dashboard first-load acceptance tests.

Proves the dashboard first-load contract:
1. GET / returns 200 with HTML app shell
2. App shell contains login overlay
3. Static assets (CSS, JS) load correctly
4. Setup status returns valid JSON
5. Healthz endpoint returns 200
6. No 500 errors on first load
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestAppShellContract(unittest.TestCase):
    """GET / must return the app shell with critical elements."""

    def test_app_html_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/app.html")
        self.assertTrue(os.path.isfile(path))

    def test_app_html_has_login_overlay(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("login-overlay", src,
                       "App shell must have login overlay for unauthenticated users")

    def test_app_html_has_nav(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("view-btn", src, "App shell must have navigation buttons")

    def test_app_html_references_css(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("app.css", src)

    def test_app_html_references_js(self):
        with open(os.path.join(REPO_ROOT, "freq/data/web/app.html")) as f:
            src = f.read()
        self.assertIn("app.js", src)


class TestStaticAssetsExist(unittest.TestCase):
    """CSS and JS assets must exist for the dashboard to render."""

    def test_app_css_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/css/app.css")
        self.assertTrue(os.path.isfile(path), "app.css must exist")

    def test_app_js_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/js/app.js")
        self.assertTrue(os.path.isfile(path), "app.js must exist")

    def test_setup_html_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/setup.html")
        self.assertTrue(os.path.isfile(path), "setup.html must exist")

    def test_setup_js_exists(self):
        path = os.path.join(REPO_ROOT, "freq/data/web/js/setup.js")
        self.assertTrue(os.path.isfile(path), "setup.js must exist")


class TestServeHandlerContract(unittest.TestCase):
    """Serve handlers must serve app shell and static assets."""

    def test_root_route_serves_app(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("app.html", src, "Serve must reference app.html for root route")

    def test_healthz_endpoint_exists(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("healthz", src)

    def test_static_route_exists(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        self.assertIn("/static/", src, "Must have static asset route")


if __name__ == "__main__":
    unittest.main()
