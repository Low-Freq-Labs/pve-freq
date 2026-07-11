import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestDashboardOperatorTruthContract(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "freq/data/web/app.html").read_text()
        self.js = (ROOT / "freq/data/web/js/app.js").read_text()

    def test_hardening_requires_an_explicit_target(self):
        self.assertIn('id="harden-target"', self.html)
        self.assertIn('<option value="all">ALL FLEET HOSTS</option>', self.html)
        self.assertIn("if(!target){toast('Select a hardening target','error');return;}", self.js)
        self.assertIn("'?target='+encodeURIComponent(target)", self.js)
        harden = self.js[self.js.index("function hardenAction(action)"):self.js.index("function runSshSweep()")]
        self.assertNotIn("target=all", harden)

    def test_ooc_is_expanded_for_operators(self):
        self.assertIn("OOC (out of contract)", self.html)

    def test_shortcut_help_matches_the_implemented_map(self):
        self.assertIn('<kbd class="kbd-tag">1-6</kbd>', self.html)
        self.assertNotIn('<kbd class="kbd-tag">1-8</kbd>', self.html)
        self.assertIn("var _NAV_KEYS={'1':'home','2':'fleet','3':'docker','4':'certs','5':'tools','6':'settings'}", self.js)
        self.assertIn("/* 1-6 — navigate the six mapped top-level destinations", self.js)
        self.assertIn("getComputedStyle(m).display==='none'?'block':'none'", self.js)


if __name__ == "__main__":
    unittest.main()
