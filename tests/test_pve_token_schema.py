"""Tests for PVE token schema — both canonical and legacy field names must work.

Bug: freq.toml used token_id and token_secret_file (legacy names set by
init), but config.py only parsed api_token_id and api_token_secret_path
(canonical names from docs). Result: pve_api_token_id stayed empty →
doctor reported PVE cluster 0/3 reachable even with valid token.

Fix: config.py now reads both canonical and legacy names:
- api_token_id OR token_id → cfg.pve_api_token_id
- api_token_secret_path OR token_secret_file → loads secret from file

Contract: canonical names preferred, legacy names supported as aliases.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPveTokenParsing(unittest.TestCase):
    """Both canonical and legacy PVE token field names must be parsed."""

    def _load_with_toml(self, toml_content):
        """Create a temp freq.toml and load config from it."""
        tmpdir = tempfile.mkdtemp()
        try:
            conf_dir = os.path.join(tmpdir, "conf")
            os.makedirs(conf_dir)
            with open(os.path.join(conf_dir, "freq.toml"), "w") as f:
                f.write(toml_content)
            # Create minimal data dirs
            for d in ("data/log", "data/vault", "data/keys"):
                os.makedirs(os.path.join(tmpdir, d), exist_ok=True)
            from freq.core.config import FreqConfig, load_toml, _apply_toml
            cfg = FreqConfig()
            cfg.install_dir = tmpdir
            cfg.conf_dir = conf_dir
            data = load_toml(os.path.join(conf_dir, "freq.toml"))
            _apply_toml(cfg, data)
            return cfg
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_canonical_api_token_id(self):
        """api_token_id (canonical name) must be parsed."""
        cfg = self._load_with_toml('[pve]\napi_token_id = "test@pam!token"\n')
        self.assertEqual(cfg.pve_api_token_id, "test@pam!token")

    def test_legacy_token_id(self):
        """token_id (legacy name) must be parsed as alias."""
        cfg = self._load_with_toml('[pve]\ntoken_id = "legacy@pam!tok"\n')
        self.assertEqual(cfg.pve_api_token_id, "legacy@pam!tok")

    def test_canonical_takes_precedence(self):
        """If both canonical and legacy exist, canonical wins."""
        cfg = self._load_with_toml(
            '[pve]\napi_token_id = "canonical@pam!tok"\ntoken_id = "legacy@pam!tok"\n'
        )
        self.assertEqual(cfg.pve_api_token_id, "canonical@pam!tok")

    def test_legacy_token_secret_file(self):
        """token_secret_file (legacy name) must be read."""
        tmpdir = tempfile.mkdtemp()
        try:
            secret_file = os.path.join(tmpdir, "token-secret")
            with open(secret_file, "w") as f:
                f.write("abc123-secret-value\n")
            cfg = self._load_with_toml(
                f'[pve]\ntoken_id = "test@pam!tok"\ntoken_secret_file = "{secret_file}"\n'
            )
            self.assertEqual(cfg.pve_api_token_secret, "abc123-secret-value")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestPveTokenConfigContract(unittest.TestCase):
    """The config parser must support both field name conventions."""

    def test_parser_has_token_id_alias(self):
        """config.py must read 'token_id' as alias for 'api_token_id'."""
        path = Path(__file__).parent.parent / "freq" / "core" / "config.py"
        with open(path) as f:
            content = f.read()
        self.assertIn('"token_id"', content,
                       "config.py must read legacy token_id field")

    def test_parser_has_token_secret_file_alias(self):
        """config.py must read 'token_secret_file' as alias."""
        path = Path(__file__).parent.parent / "freq" / "core" / "config.py"
        with open(path) as f:
            content = f.read()
        self.assertIn('"token_secret_file"', content,
                       "config.py must read legacy token_secret_file field")


if __name__ == "__main__":
    unittest.main()
