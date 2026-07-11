import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestSingleViewRouterContract(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "freq/data/web/app.html").read_text()
        self.js = (ROOT / "freq/data/web/js/app.js").read_text()
        self.router = (ROOT / "freq/data/web/js/router.js").read_text()
        self.css = (ROOT / "freq/data/web/css/app.css").read_text()

    def test_dashboard_has_one_router_root_and_no_page_islands(self):
        self.assertEqual(self.html.count('id="dashboard-root"'), 1)
        self.assertNotIn('id="p-home"', self.html)
        self.assertNotIn('id="p-infra"', self.html)
        self.assertNotIn('id="p-system"', self.html)
        self.assertNotIn('class="page', self.html)
        self.assertNotIn(".page {", self.css)
        self.assertNotIn(".page.active", self.css)

    def test_legacy_content_is_preserved_as_normal_views(self):
        for view in ("infra", "system", "lab"):
            self.assertIn(f'id="{view}-view"', self.html)
            self.assertIn(f"{view}:function()", self.js)

    def test_empty_media_stub_is_an_alias_not_fake_dom(self):
        self.assertNotIn('id="media-view"', self.html)
        self.assertNotIn("getElementById('media-view')", self.js)
        self.assertIn("var VIEW_ALIASES={media:'docker'}", self.js)

    def test_all_navigation_uses_the_view_router(self):
        self.assertIn('src="/static/js/router.js?v={{VERSION}}"', self.html)
        self.assertLess(
            self.html.index('<script src="/static/js/router.js'),
            self.html.index('<script src="/static/js/app.js'),
        )
        self.assertIn("global.FreqViewRouter={create:create}", self.router)
        self.assertIn("window.FreqViewRouter.create", self.js)
        self.assertIn("function _resolveView(view)", self.js)
        self.assertIn("function _viewFromLocation()", self.js)
        self.assertIn("function switchView(view,skipPush)", self.js)
        self.assertNotIn("function nav(p)", self.js)
        self.assertNotIn("function load(p)", self.js)
        self.assertNotIn("getElementById('p-home')", self.js)
        self.assertNotIn("querySelectorAll('.page')", self.js)

    def test_unknown_routes_fail_closed_to_home(self):
        self.assertIn("return loaders[view]?view:'home'", self.router)
        self.assertIn("history.replaceState({view:view}", self.router)
        self.assertIn("handlePopState:handlePopState", self.router)


if __name__ == "__main__":
    unittest.main()
