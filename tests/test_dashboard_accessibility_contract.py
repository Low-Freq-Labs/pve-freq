import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestDashboardAccessibilityContract(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "freq/data/web/app.html").read_text()
        self.js = (ROOT / "freq/data/web/js/app.js").read_text()

    def test_symbol_only_static_buttons_have_accessible_names(self):
        symbol_buttons = re.findall(r"<button\b[^>]*>(?:&times;|&#10005;)</button>", self.html)
        self.assertTrue(symbol_buttons)
        for button in symbol_buttons:
            self.assertIn("aria-label=", button)

    def test_dynamic_close_controls_are_real_named_buttons(self):
        self.assertNotIn('<span class="close-x"', self.js)
        for tag in re.findall(r"<button\b[^>]*class=\\?['\"]close-x[^>]*>", self.js):
            self.assertIn("aria-label=", tag)

    def test_overlay_surfaces_have_dialog_semantics(self):
        for overlay_id in ("host-overlay", "modal-container", "terminal-overlay", "search-overlay", "shortcuts-modal"):
            tag = re.search(rf'<div\b[^>]*id="{overlay_id}"[^>]*>', self.html)
            self.assertIsNotNone(tag, overlay_id)
            self.assertIn('role="dialog"', tag.group(0))
            self.assertIn('aria-modal="true"', tag.group(0))

    def test_placeholder_only_controls_receive_explicit_names(self):
        controls = re.findall(r"<(?:input|textarea)\b[^>]*placeholder=\"[^\"]*\"[^>]*>", self.html)
        unnamed = []
        for control in controls:
            match = re.search(r'id="([^"]+)"', control)
            control_id = match.group(1) if match else control
            associated = f'for="{control_id}"' in self.html
            nested = control_id.startswith("vault-")
            if "aria-label=" not in control and not associated and not nested:
                unnamed.append(control_id)
        self.assertEqual(unnamed, [])


if __name__ == "__main__":
    unittest.main()
