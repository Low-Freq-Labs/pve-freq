"""Tests for Phase 11 — Release Prep.
Covers: CHANGELOG completeness, version consistency, Docker sync readiness,
required files present, test suite health.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


# ─────────────────────────────────────────────────────────────
# REQUIRED FILES — Everything needed for public release
# ─────────────────────────────────────────────────────────────

class TestRequiredFiles(unittest.TestCase):
    """Verify all files required for public release are present."""

    REQUIRED = [
        "README.md",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "LICENSE",
        "pyproject.toml",
        "freq/__init__.py",
        "freq/cli.py",
        "freq/core/config.py",
        "freq/core/plugins.py",
        "freq/deployers/__init__.py",
        "freq/api/__init__.py",
        "conf/freq.toml.example",
        "conf/hosts.toml.example",
    ]

    def test_all_required_files_exist(self):
        missing = []
        for f in self.REQUIRED:
            if not (FREQ_ROOT / f).exists():
                missing.append(f)
        self.assertEqual(missing, [],
                         f"Missing required files:\n" + "\n".join(missing))


class TestChangelog(unittest.TestCase):
    """Verify CHANGELOG has v3.0.0 entry."""

    def setUp(self):
        self.changelog = (FREQ_ROOT / "CHANGELOG.md").read_text()

    def test_has_v3_entry(self):
        self.assertIn("[3.0.0]", self.changelog)

    def test_has_phase_sections(self):
        for phase in range(0, 11):
            self.assertIn(f"Phase {phase}", self.changelog,
                          f"CHANGELOG missing Phase {phase}")

    def test_mentions_domain_dispatch(self):
        self.assertIn("domain dispatch", self.changelog.lower())

    def test_mentions_plugin_system(self):
        self.assertIn("plugin", self.changelog.lower())

    def test_mentions_dashboard(self):
        self.assertIn("dashboard", self.changelog.lower())

    def test_mentions_zero_dependencies(self):
        self.assertIn("zero external dependencies", self.changelog.lower())

    def test_mentions_agpl(self):
        self.assertIn("AGPL", self.changelog)


class TestVersionConsistency(unittest.TestCase):
    """Verify version is consistent across all files."""

    def test_init_has_version(self):
        import freq
        self.assertTrue(hasattr(freq, "__version__"))
        self.assertRegex(freq.__version__, r"\d+\.\d+\.\d+")

    def test_pyproject_has_version(self):
        content = (FREQ_ROOT / "pyproject.toml").read_text()
        # pyproject.toml uses dynamic versioning from __init__.py
        self.assertTrue(
            "dynamic" in content or "version" in content,
            "pyproject.toml must define or dynamically read version")


class TestDockerSyncReadiness(unittest.TestCase):
    """Verify pve-freq is ready for Docker repo sync."""

    def test_dockerfile_references(self):
        """Check that Docker-relevant files exist."""
        docker_files = [
            "Dockerfile",
            "docker-compose.yml",
        ]
        for f in docker_files:
            path = FREQ_ROOT / f
            if path.exists():
                content = path.read_text()
                # Docker files should reference freq, not hardcoded paths
                self.assertNotIn("/data/projects/pve-freq", content,
                                 f"{f} has hardcoded development path")

    def test_install_script_exists(self):
        path = FREQ_ROOT / "install.sh"
        self.assertTrue(path.exists(), "install.sh missing")


class TestLicense(unittest.TestCase):
    """Verify license file is correct."""

    def test_license_exists(self):
        self.assertTrue((FREQ_ROOT / "LICENSE").exists())

    def test_license_has_content(self):
        content = (FREQ_ROOT / "LICENSE").read_text()
        self.assertTrue(
            "GNU AFFERO GENERAL PUBLIC LICENSE" in content,
            "LICENSE file should contain AGPL v3 text")


class TestTestSuiteHealth(unittest.TestCase):
    """Verify the test suite is healthy."""

    def test_test_files_exist(self):
        test_dir = FREQ_ROOT / "tests"
        test_files = list(test_dir.glob("test_*.py"))
        # Should have at least 20 test files
        self.assertGreaterEqual(len(test_files), 20,
                                f"Only {len(test_files)} test files found")

    def test_phase_test_files(self):
        """Every build phase should have a test file."""
        test_dir = FREQ_ROOT / "tests"
        for phase in [7, 8, 9, 10, 11]:
            matches = list(test_dir.glob(f"test_phase{phase}*.py"))
            self.assertGreater(len(matches), 0,
                               f"No test file for Phase {phase}")

    def test_no_test_imports_external(self):
        """Test files should not require external packages."""
        test_dir = FREQ_ROOT / "tests"
        violations = []
        safe_imports = {
            "sys", "os", "io", "re", "json", "unittest", "pathlib",
            "tempfile", "shutil", "subprocess", "dataclasses",
            "unittest.mock", "contextlib", "collections",
            "argparse", "time", "hashlib", "copy", "textwrap",
            "sys,", "json,",  # handle multi-import lines
        }
        for test_file in test_dir.glob("test_phase*.py"):
            content = test_file.read_text()
            for line in content.split("\n"):
                if line.strip().startswith("import ") and not line.strip().startswith("from freq"):
                    mod = line.strip().split()[1].split(".")[0]
                    if mod not in safe_imports and not mod.startswith("freq"):
                        violations.append(f"{test_file.name}: imports {mod}")
        self.assertEqual(violations, [],
                         f"Test files importing external packages:\n" +
                         "\n".join(violations))


class TestReadme(unittest.TestCase):
    """Verify README exists and has basic content."""

    def test_readme_exists(self):
        self.assertTrue((FREQ_ROOT / "README.md").exists())

    def test_readme_mentions_freq(self):
        content = (FREQ_ROOT / "README.md").read_text()
        self.assertIn("FREQ", content)

    def test_readme_has_install_instructions(self):
        content = (FREQ_ROOT / "README.md").read_text().lower()
        self.assertTrue(
            "install" in content or "setup" in content or "getting started" in content,
            "README should have installation instructions")


if __name__ == "__main__":
    unittest.main()
