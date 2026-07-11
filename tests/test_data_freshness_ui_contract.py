import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestDataFreshnessUIContract(unittest.TestCase):
    def setUp(self):
        self.js = (ROOT / "freq/data/web/js/app.js").read_text()
        self.css = (ROOT / "freq/data/web/css/app.css").read_text()

    def test_successful_fetches_receive_panel_context_and_timestamp(self):
        for token in (
            "var _panelFetchContext=null",
            "_panelFetchContext=da.closest('.section')",
            "_verifyAndMarkPanelFetch(r,panelContext)",
            "if(!section||!response||!response.ok",
            "stamp.textContent='AS OF '+label",
        ):
            self.assertIn(token, self.js)

    def test_failed_or_unparseable_fetches_do_not_advance_freshness(self):
        self.assertIn("contentType.indexOf('json')>=0?copy.json():copy.text()", self.js)
        self.assertIn(".then(function(){_markPanelFetched(section,Date.now());}).catch(function(){})", self.js)

    def test_expanding_section_invokes_only_read_loader_actions(self):
        self.assertIn("function _fetchSectionOnExpand(section)", self.js)
        self.assertIn('[data-action^="load"]', self.js)
        self.assertIn('[data-action^="fetch"]', self.js)
        self.assertNotIn('[data-action^="run"]', self.js)

    def test_timestamp_uses_existing_dim_visual_language(self):
        self.assertIn(".panel-updated", self.css)
        self.assertIn("color: var(--text-dim)", self.css)


if __name__ == "__main__":
    unittest.main()
