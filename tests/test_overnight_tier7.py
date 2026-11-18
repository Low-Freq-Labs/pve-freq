"""Deterministic personality pack, selection, vibe, and splash contracts."""
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPersonalityBehaviorContract(unittest.TestCase):
    """Comprehensive behavior contract for personality packs and output."""

    def test_pack_loading_and_fallbacks(self):
        from freq.core.personality import PersonalityPack, load_pack
        from freq.data import get_data_path

        packaged_conf = str(get_data_path() / "conf-templates")
        built_in = PersonalityPack()
        self.assertEqual(
            {
                "name": built_in.name,
                "subtitle": built_in.subtitle,
                "vibe_enabled": built_in.vibe_enabled,
                "vibe_probability": built_in.vibe_probability,
                "dashboard_header": built_in.dashboard_header,
                "lists": (
                    built_in.celebrations,
                    built_in.taglines,
                    built_in.quotes,
                    built_in.vibe_common,
                    built_in.vibe_rare,
                    built_in.vibe_legendary,
                ),
            },
            {
                "name": "default",
                "subtitle": "P V E  F R E Q",
                "vibe_enabled": True,
                "vibe_probability": 47,
                "dashboard_header": "PVE FREQ Dashboard",
                "lists": ([], [], [], [], [], []),
            },
        )

        for name, expected in (
            (
                "default",
                {
                    "subtitle": "P V E  F R E Q",
                    "vibe_enabled": False,
                    "vibe_probability": 47,
                    "dashboard_header": "PVE FREQ Dashboard",
                },
            ),
            (
                "personal",
                {
                    "subtitle": "L O W  F R E Q  L A B S",
                    "vibe_enabled": True,
                    "vibe_probability": 47,
                    "dashboard_header": "LOW FREQ Labs Dashboard",
                },
            ),
        ):
            with self.subTest(pack=name):
                loaded = load_pack(packaged_conf, name)
                self.assertEqual(loaded.name, name)
                for field, value in expected.items():
                    self.assertEqual(getattr(loaded, field), value)
                self.assertTrue(loaded.celebrations)
                self.assertTrue(loaded.taglines)
                self.assertTrue(loaded.quotes)

        for conf_dir, name in (
            (packaged_conf, "enterprise"),
            ("/definitely/missing/personality-conf", "default"),
        ):
            with self.subTest(fallback=name, conf_dir=conf_dir):
                fallback = load_pack(conf_dir, name)
                self.assertEqual(fallback.name, name)
                self.assertEqual(fallback.subtitle, "P V E  F R E Q")
                self.assertEqual(fallback.vibe_probability, 47)
                self.assertEqual(fallback.celebrations, [])
                self.assertEqual(fallback.taglines, [])
                self.assertEqual(fallback.quotes, [])

        with tempfile.TemporaryDirectory() as tmpdir:
            pack_dir = Path(tmpdir) / "personality"
            pack_dir.mkdir()
            (pack_dir / "custom.toml").write_text(
                'subtitle = "Custom Pack"\n'
                "vibe_enabled = false\n"
                "vibe_probability = 9\n"
                'dashboard_header = "Custom Dashboard"\n'
                'celebrations = ["celebrate"]\n'
                'taglines = ["tagline"]\n'
                'quotes = ["quote"]\n'
                "[premier]\n"
                'create = "created"\n'
                "[vibes]\n"
                'common = ["common"]\n'
                'rare = ["rare"]\n'
                'legendary = ["legendary"]\n'
            )
            (pack_dir / "broken.toml").write_text("this is [not valid toml {{{}}}}")

            custom = load_pack(tmpdir, "custom")
            self.assertEqual(
                (
                    custom.name,
                    custom.subtitle,
                    custom.vibe_enabled,
                    custom.vibe_probability,
                    custom.dashboard_header,
                    custom.celebrations,
                    custom.premier,
                    custom.taglines,
                    custom.quotes,
                    custom.vibe_common,
                    custom.vibe_rare,
                    custom.vibe_legendary,
                ),
                (
                    "custom",
                    "Custom Pack",
                    False,
                    9,
                    "Custom Dashboard",
                    ["celebrate"],
                    {"create": "created"},
                    ["tagline"],
                    ["quote"],
                    ["common"],
                    ["rare"],
                    ["legendary"],
                ),
            )

            with self.assertLogs("freq.core.personality", level="WARNING"):
                broken = load_pack(tmpdir, "broken")
            self.assertEqual(broken.name, "broken")
            self.assertEqual(broken.subtitle, "P V E  F R E Q")
            self.assertEqual(broken.celebrations, [])

    @patch("freq.core.personality.random.choice", side_effect=lambda values: values[0])
    def test_message_selection_and_fallbacks(self, choose):
        from freq.core.personality import PersonalityPack, celebrate, quote, tagline

        empty = PersonalityPack()
        self.assertEqual(celebrate(empty), "Done.")
        self.assertEqual(tagline(empty), "Full frequency. Full efficiency.")
        self.assertEqual(quote(empty), '"configure once. deploy everywhere." -- freq')

        populated = PersonalityPack(
            celebrations=["celebration"],
            premier={"create": "premier"},
            taglines=["tagline"],
            quotes=["quote"],
        )
        self.assertEqual(celebrate(populated), "celebration")
        before_premier = choose.call_count
        self.assertEqual(celebrate(populated, "create"), "premier")
        self.assertEqual(choose.call_count, before_premier)
        self.assertEqual(celebrate(populated, "destroy"), "celebration")
        self.assertEqual(tagline(populated), "tagline")
        self.assertEqual(quote(populated), "quote")
        self.assertEqual(choose.call_count, 4)

    def test_vibe_routing_and_output(self):
        from freq.core.personality import PersonalityPack, show_vibe, vibe_check

        disabled = PersonalityPack(vibe_enabled=False)
        with patch("freq.core.personality.random.randint") as randint:
            self.assertIsNone(vibe_check(disabled))
            randint.assert_not_called()

        def routed(pack, rolls):
            with (
                patch("freq.core.personality.random.randint", side_effect=rolls),
                patch(
                    "freq.core.personality.random.choice",
                    side_effect=lambda values: values[0],
                ),
            ):
                return vibe_check(pack)

        base = {
            "vibe_enabled": True,
            "vibe_probability": 47,
            "vibe_common": ["common"],
            "vibe_rare": ["rare"],
            "vibe_legendary": ["legendary"],
        }
        cases = (
            ("probability miss", PersonalityPack(**base), [2], None),
            ("common", PersonalityPack(**base), [1, 60], "common"),
            ("rare", PersonalityPack(**base), [1, 85], "rare"),
            ("legendary", PersonalityPack(**base), [1, 86], "legendary"),
            (
                "common fallback",
                PersonalityPack(**(base | {"vibe_legendary": []})),
                [1, 86],
                "common",
            ),
            (
                "common missing routes rare",
                PersonalityPack(**(base | {"vibe_common": []})),
                [1, 60],
                "rare",
            ),
            (
                "rare missing routes legendary",
                PersonalityPack(**(base | {"vibe_rare": []})),
                [1, 85],
                "legendary",
            ),
            (
                "empty messages",
                PersonalityPack(
                    vibe_enabled=True,
                    vibe_probability=1,
                ),
                [1, 50],
                None,
            ),
        )
        for label, pack, rolls, expected in cases:
            with self.subTest(label=label):
                self.assertEqual(routed(pack, rolls), expected)

        output = StringIO()
        with patch("freq.core.personality.vibe_check", return_value=None):
            with redirect_stdout(output):
                show_vibe(PersonalityPack())
        self.assertEqual(output.getvalue(), "")

        output = StringIO()
        with patch("freq.core.personality.vibe_check", return_value="vibe message"):
            with redirect_stdout(output):
                show_vibe(PersonalityPack())
        self.assertIn("vibe message", output.getvalue())

    def test_splash_output_contract(self):
        from freq.core import personality
        from freq.data import get_data_path

        packaged_conf = str(get_data_path() / "conf-templates")
        cases = (
            ("default", 72, personality.LOGO, personality.LOGO_SMALL),
            ("personal", 71, personality.LOGO_SMALL, personality.LOGO),
        )
        for name, width, expected_logo, other_logo in cases:
            with self.subTest(pack=name, width=width):
                pack = personality.load_pack(packaged_conf, name)
                output = StringIO()
                with (
                    patch("freq.core.personality.term_width", return_value=width),
                    patch("freq.core.personality.tagline", return_value="tagline line"),
                    patch("freq.core.personality.quote", return_value="quote line"),
                    redirect_stdout(output),
                ):
                    personality.splash(pack, "2.0.0")
                rendered = output.getvalue()
                self.assertIn(expected_logo, rendered)
                self.assertNotIn(other_logo, rendered)
                self.assertIn(pack.subtitle, rendered)
                self.assertIn("v2.0.0", rendered)
                self.assertIn("tagline line", rendered)
                self.assertIn("quote line", rendered)


if __name__ == "__main__":
    unittest.main()
