""" regression contract.

Live clean 5005 init at e361cb2 emitted a real warning during Phase 7
Step 6 (freq.toml [infrastructure] update):

    Could not update freq.toml infrastructure: [Errno 2] No such file
    or directory

while Phase 7 Step 5 (fleet-boundaries auto-add) succeeded. The cause
was a layered seeding gap: bootstrap_conf in freq.core.config used to
gate template-file copies on full_bootstrap=True, so a partially
populated conf_dir (e.g. one that already contained personality/ from
a prior run) never got freq.toml.example back. Phase 1's
_seed_config_files then had nothing to copy from, freq.toml stayed
absent through Phase 7, and the [infrastructure] read at Step 6 hit
ENOENT.

The fix is layered:

1. bootstrap_conf incrementally heals missing template files on every
   call (drops the full_bootstrap gate around the file-copy loop). The
   inner exists() check keeps it idempotent.

2. _seed_config_files in Phase 1 falls back to the packaged
   conf-templates if the in-conf .example is missing — so even a
   conf_dir bootstrap_conf couldn't reach still ends up with the
   live file seeded.

3. Phase 7 Step 6 self-heals: if freq.toml is missing right before the
   infra read, it calls _seed_config_files one more time before the
   open(). Belt-and-suspenders so a green init never carries the
   warning even if upstream seeding silently dropped the file.

These tests pin all three guarantees so the warning can never come
back without someone touching this file.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.core.config import FreqConfig, _resolve_paths, bootstrap_conf  # noqa: E402
from freq.modules.init_cmd import _seed_config_files  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent
PKG_TEMPLATES = REPO_ROOT / "freq" / "data" / "conf-templates"


def _make_cfg(install_dir: str) -> FreqConfig:
    cfg = FreqConfig()
    cfg.install_dir = install_dir
    _resolve_paths(cfg)
    return cfg


class TestBootstrapConfHealsPartialConfDir(unittest.TestCase):
    """bootstrap_conf must heal a partially populated conf_dir, not
    silently skip the file copy because some other file was already
    present. This is the upstream root-cause fix for N."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freq-N-bootstrap-")
        self.conf_dir = os.path.join(self.tmp, "conf")
        os.makedirs(self.conf_dir)
        # Simulate "partially populated" — drop one file unrelated to
        # freq.toml so the directory is non-empty but freq.toml.example
        # is missing.
        with open(os.path.join(self.conf_dir, "marker.txt"), "w") as f:
            f.write("partial state from a prior init")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bootstrap_conf_seeds_freq_toml_example_into_partial_dir(self):
        """Even with conf_dir non-empty, bootstrap_conf must still copy
        freq.toml.example from the packaged templates."""
        if not (PKG_TEMPLATES / "freq.toml.example").is_file():
            self.skipTest("packaged freq.toml.example not present in source tree")

        bootstrap_conf(self.tmp)

        seeded_example = os.path.join(self.conf_dir, "freq.toml.example")
        self.assertTrue(
            os.path.isfile(seeded_example),
            f"bootstrap_conf must heal partial conf_dir by copying "
            f"freq.toml.example into {self.conf_dir}, but file is missing"
        )
        # Pre-existing marker untouched
        self.assertTrue(os.path.isfile(os.path.join(self.conf_dir, "marker.txt")))

    def test_bootstrap_conf_is_idempotent_does_not_overwrite(self):
        """Calling bootstrap_conf twice must not re-copy or clobber."""
        if not (PKG_TEMPLATES / "freq.toml.example").is_file():
            self.skipTest("packaged freq.toml.example not present in source tree")

        bootstrap_conf(self.tmp)
        seeded_example = os.path.join(self.conf_dir, "freq.toml.example")
        # Mutate the seeded copy to detect any overwrite
        with open(seeded_example, "w") as f:
            f.write("# user-modified\n")
        bootstrap_conf(self.tmp)
        with open(seeded_example) as f:
            self.assertEqual(f.read(), "# user-modified\n")


class TestSeedConfigFilesFallsBackToPackageTemplates(unittest.TestCase):
    """_seed_config_files must fall back to the packaged templates when
    the in-conf .example is missing. Belt-and-suspenders for the case
    where bootstrap_conf wasn't reached or its copy failed silently."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freq-N-seed-")
        self.conf_dir = os.path.join(self.tmp, "conf")
        os.makedirs(self.conf_dir)
        self.cfg = _make_cfg(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_seed_uses_pkg_template_when_in_conf_example_missing(self):
        """conf_dir has NO freq.toml and NO freq.toml.example. After
        _seed_config_files, freq.toml must exist (sourced from package
        templates)."""
        if not (PKG_TEMPLATES / "freq.toml.example").is_file():
            self.skipTest("packaged freq.toml.example not present in source tree")

        live = os.path.join(self.conf_dir, "freq.toml")
        in_conf_example = os.path.join(self.conf_dir, "freq.toml.example")
        self.assertFalse(os.path.isfile(live))
        self.assertFalse(os.path.isfile(in_conf_example))

        # _seed_config_files prints via fmt — silence it
        with patch("freq.modules.init_cmd.fmt") as _fmt:
            _fmt.step_ok = MagicMock()
            _fmt.step_warn = MagicMock()
            _seed_config_files(self.cfg)

        self.assertTrue(
            os.path.isfile(live),
            "freq.toml must be seeded from packaged template even when "
            "in-conf .example is missing"
        )

    def test_seed_does_not_overwrite_existing_live_file(self):
        """Existing freq.toml must not be touched by the seed."""
        live = os.path.join(self.conf_dir, "freq.toml")
        with open(live, "w") as f:
            f.write("# user-edited freq.toml\n")

        with patch("freq.modules.init_cmd.fmt") as _fmt:
            _fmt.step_ok = MagicMock()
            _fmt.step_warn = MagicMock()
            _seed_config_files(self.cfg)

        with open(live) as f:
            self.assertEqual(f.read(), "# user-edited freq.toml\n")


class TestPhase7Step6SelfHealsMissingFreqToml(unittest.TestCase):
    """Phase 7 Step 6 (freq.toml [infrastructure] update) must call
    _seed_config_files when freq.toml is missing right before the read,
    so the warning never fires on a green init even if upstream seeding
    was incomplete. We assert the source file contains the self-heal
    pattern; a behavioral test would require importing init_cmd's
    _phase_fleet_discover and stubbing 6 phases of state, which is more
    fragile than pinning the contract directly."""

    def setUp(self):
        self.src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()

    def test_step6_self_heal_calls_seed_when_freq_toml_missing(self):
        """The Step 6 block must contain an `if not isfile(toml_path):
        _seed_config_files(cfg)` immediately before the open(). We
        anchor on the section header inside _phase_fleet_discover and
        slice forward until the read."""
        # The Phase 7 implementation header (not the docstring at line ~2752).
        marker = "# ── Step 6: Update freq.toml [infrastructure] ──"
        idx = self.src.find(marker)
        self.assertNotEqual(idx, -1, f"Step 6 implementation marker missing: {marker}")
        block = self.src[idx:idx + 2000]
        self.assertIn("toml_path = os.path.join(cfg.conf_dir", block)
        self.assertIn("if not os.path.isfile(toml_path)", block,
                      "Step 6 must check for missing freq.toml before reading")
        self.assertIn("_seed_config_files(cfg)", block,
                      "Step 6 must call _seed_config_files when freq.toml is missing")
        self.assertIn("", block,
                      "Step 6 self-heal must reference the token so the contract is traceable")

    def test_step6_warning_text_unchanged(self):
        """The honest warning text must still exist as the LAST-RESORT
        fallback path — if the seed self-heal also fails, the operator
        still sees a clear message instead of a silent skip."""
        self.assertIn(
            'Could not update freq.toml infrastructure',
            self.src,
            "honest fallback warning must remain for the truly-broken case"
        )


class TestEndToEndPartialConfDirRecoversByPhase1(unittest.TestCase):
    """The full bootstrap_conf -> _seed_config_files chain must produce
    a live freq.toml even when the conf_dir starts in the broken state
    we hypothesize triggered N (non-empty but missing freq.toml.example)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freq-N-e2e-")
        self.conf_dir = os.path.join(self.tmp, "conf")
        os.makedirs(self.conf_dir)
        # Drop a stale leftover so conf_dir is non-empty but freq.toml*
        # is absent — the exact trigger condition.
        os.makedirs(os.path.join(self.conf_dir, "personality"))
        with open(os.path.join(self.conf_dir, "personality", "ghost.toml"), "w") as f:
            f.write("# leftover from a prior partial init\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_partial_conf_dir_ends_with_live_freq_toml(self):
        if not (PKG_TEMPLATES / "freq.toml.example").is_file():
            self.skipTest("packaged freq.toml.example not present in source tree")

        # 1. bootstrap_conf heals .example into the partial conf_dir
        bootstrap_conf(self.tmp)
        self.assertTrue(
            os.path.isfile(os.path.join(self.conf_dir, "freq.toml.example")),
            "bootstrap_conf must heal freq.toml.example into partial conf_dir"
        )

        # 2. Phase 1 _seed_config_files copies .example -> live
        cfg = _make_cfg(self.tmp)
        with patch("freq.modules.init_cmd.fmt") as _fmt:
            _fmt.step_ok = MagicMock()
            _fmt.step_warn = MagicMock()
            _seed_config_files(cfg)

        live = os.path.join(self.conf_dir, "freq.toml")
        self.assertTrue(
            os.path.isfile(live),
            "live freq.toml must exist after bootstrap_conf + Phase 1 seed "
            "even when conf_dir started in the partial state that triggered N"
        )


if __name__ == "__main__":
    unittest.main()
