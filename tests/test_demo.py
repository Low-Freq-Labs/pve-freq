"""Tests for freq demo command."""
import os
import sys
from io import StringIO
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestDemoRun:
    """Test that the demo command runs successfully."""

    def _run_demo(self, pack=None):
        """Run demo and capture output."""
        from freq.modules.demo import run
        from freq.core.personality import PersonalityPack

        cfg = MagicMock()
        cfg.version = "2.0.0"
        if pack is None:
            pack = PersonalityPack()
        args = MagicMock()

        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            result = run(cfg, pack, args)
        finally:
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
        return result, output

    def test_returns_zero(self):
        result, _ = self._run_demo()
        assert result == 0

    def test_shows_splash(self):
        _, output = self._run_demo()
        assert "F R E Q" in output or "FREQ" in output

    def test_shows_doctor_section(self):
        _, output = self._run_demo()
        assert "Self-Diagnostic" in output

    def test_shows_fleet_status(self):
        _, output = self._run_demo()
        assert "Fleet Status" in output
        assert "pve01" in output

    def test_shows_command_reference(self):
        _, output = self._run_demo()
        assert "Command Reference" in output
        assert "65" in output

    def test_shows_personality_section(self):
        _, output = self._run_demo()
        assert "Personality System" in output

    def test_shows_dashboard_tease(self):
        _, output = self._run_demo()
        assert "Web Dashboard" in output
        assert "8888" in output

    def test_shows_closing(self):
        _, output = self._run_demo()
        assert "pve-freq" in output

    def test_works_with_default_pack(self):
        """Demo works with empty default PersonalityPack (no config file)."""
        from freq.core.personality import PersonalityPack
        pack = PersonalityPack()
        result, output = self._run_demo(pack)
        assert result == 0
        assert "Personality System" in output

    def test_works_with_populated_pack(self):
        """Demo works with a fully populated personality pack."""
        from freq.core.personality import PersonalityPack
        pack = PersonalityPack(
            name="test",
            celebrations=["test celebration 1", "test celebration 2", "test celebration 3"],
            taglines=["test tagline"],
            quotes=["test quote"],
            vibe_common=["# common vibe"],
            vibe_rare=["# rare vibe"],
            vibe_legendary=["legendary story line 1\nlegendary story line 2"],
        )
        result, output = self._run_demo(pack)
        assert result == 0
        assert "test celebration" in output

    def test_cli_parser_has_demo(self):
        """The demo command is registered in the CLI parser."""
        from freq.cli import _build_parser
        parser = _build_parser()
        args = parser.parse_args(["demo"])
        assert hasattr(args, "func")

    def test_demo_via_main(self):
        """Demo runs through the main dispatcher."""
        from freq.cli import main
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            result = main(["demo"])
        except SystemExit as e:
            result = e.code or 0
        finally:
            output = sys.stdout.getvalue()
            sys.stdout = old_stdout
        assert result == 0
        assert "Fleet Status" in output
