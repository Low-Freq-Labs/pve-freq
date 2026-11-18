import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestSingleViewRouterContract(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "freq/data/web/app.html").read_text()
        self.css = (ROOT / "freq/data/web/css/app.css").read_text()

    def test_dashboard_has_one_router_root_and_no_page_islands(self):
        self.assertEqual(self.html.count('id="dashboard-root"'), 1)
        self.assertNotIn('id="p-home"', self.html)
        self.assertNotIn('id="p-infra"', self.html)
        self.assertNotIn('id="p-system"', self.html)
        self.assertNotIn('class="page', self.html)
        self.assertNotIn(".page {", self.css)
        self.assertNotIn(".page.active", self.css)

if __name__ == "__main__":
    unittest.main()
