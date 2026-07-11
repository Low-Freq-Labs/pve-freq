import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestChaosConfirmationUIContract(unittest.TestCase):
    def test_chaos_run_uses_sanitized_styled_confirmation(self):
        source = (ROOT / "freq/data/web/js/app.js").read_text()
        start = source.index("function chaosRun()")
        end = source.index("\nfunction runDoctor()", start)
        body = source[start:end]
        self.assertIn("confirmAction('Run chaos experiment", body)
        self.assertIn("_esc(name)", body)
        self.assertIn("_esc(type)", body)
        self.assertIn("_esc(target)", body)
        self.assertNotIn("confirm(", body)
        self.assertLess(body.index("confirmAction("), body.index("_authFetch(q)"))


if __name__ == "__main__":
    unittest.main()
