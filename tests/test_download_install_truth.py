"""Proof surfaces for what a public downloader actually gets.

Proves: package metadata, install paths, entry points, required files,
and Docker config all match what the README promises.

A fresh downloader who follows README instructions must not hit:
- Missing files (LICENSE, CHANGELOG, install.sh)
- Broken entry point (freq.cli:main doesn't import)
- Wrong install path in install.sh vs pyproject.toml
- Missing web assets in package data
- Docker Compose that references wrong port or missing Dockerfile
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


# ══════════════════════════════════════════════════════════════════════════
# Required files exist
# ══════════════════════════════════════════════════════════════════════════

class TestRequiredFilesExist(unittest.TestCase):
    """Every file a downloader expects must exist in the repo."""

    REQUIRED = [
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "pyproject.toml",
        "install.sh",
        "Dockerfile",
        "docker-compose.yml",
        "freq/__init__.py",
        "freq/cli.py",
    ]

    def test_all_required_files_exist(self):
        missing = [f for f in self.REQUIRED
                   if not os.path.isfile(os.path.join(REPO_ROOT, f))]
        self.assertEqual(missing, [],
                         f"Required files missing from repo: {missing}")


# ══════════════════════════════════════════════════════════════════════════
# Entry point is importable
# ══════════════════════════════════════════════════════════════════════════

class TestEntryPointImportable(unittest.TestCase):
    """The freq.cli:main entry point must be importable."""

    def test_freq_cli_main_exists(self):
        """freq.cli.main must be a callable function."""
        from freq.cli import main
        self.assertTrue(callable(main),
                        "freq.cli.main must be callable")

    def test_freq_version_importable(self):
        """freq.__version__ must be importable."""
        from freq import __version__
        self.assertIsInstance(__version__, str)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+")


# ══════════════════════════════════════════════════════════════════════════
# install.sh correctness
# ══════════════════════════════════════════════════════════════════════════

class TestInstallShTruth(unittest.TestCase):
    """install.sh must reference correct paths and Python version."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "install.sh")) as f:
            self.content = f.read()

    def test_min_python_matches_pyproject(self):
        """install.sh MIN_PYTHON must match pyproject requires-python."""
        # install.sh: MIN_PYTHON_MAJOR=3, MIN_PYTHON_MINOR=11
        major_match = re.search(r"MIN_PYTHON_MAJOR=(\d+)", self.content)
        minor_match = re.search(r"MIN_PYTHON_MINOR=(\d+)", self.content)
        self.assertIsNotNone(major_match)
        self.assertIsNotNone(minor_match)
        install_version = f"{major_match.group(1)}.{minor_match.group(1)}"

        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            toml = f.read()
        toml_match = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', toml)
        self.assertIsNotNone(toml_match)

        self.assertEqual(install_version, toml_match.group(1),
                         f"install.sh Python {install_version} must match "
                         f"pyproject {toml_match.group(1)}")

    def test_install_dir_default(self):
        """install.sh default INSTALL_DIR must be /opt/pve-freq."""
        self.assertIn('/opt/pve-freq', self.content)

    def test_repo_url_correct(self):
        """install.sh REPO_URL must match pyproject homepage."""
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            toml = f.read()
        url_match = re.search(r'Homepage\s*=\s*"([^"]+)"', toml)
        self.assertIsNotNone(url_match)
        self.assertIn(url_match.group(1), self.content,
                       "install.sh must reference the same repo URL as pyproject")

    def test_has_uninstall_option(self):
        """install.sh must support --uninstall (README promises it)."""
        self.assertIn("--uninstall", self.content)


# ══════════════════════════════════════════════════════════════════════════
# Package data includes web assets
# ══════════════════════════════════════════════════════════════════════════

class TestPackageDataInclusion(unittest.TestCase):
    """pyproject.toml must include all web assets for pip install."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "pyproject.toml")) as f:
            self.toml = f.read()

    def test_web_html_included(self):
        self.assertIn('"web/*.html"', self.toml)

    def test_web_css_included(self):
        self.assertIn('"web/css/*.css"', self.toml)

    def test_web_js_included(self):
        self.assertIn('"web/js/*.js"', self.toml)

    def test_conf_templates_included(self):
        self.assertIn('"conf-templates/*.example"', self.toml)

    def test_web_assets_actually_exist(self):
        """Referenced web assets must exist on disk."""
        import glob
        html = glob.glob(os.path.join(REPO_ROOT, "freq", "data", "web", "*.html"))
        css = glob.glob(os.path.join(REPO_ROOT, "freq", "data", "web", "css", "*.css"))
        js = glob.glob(os.path.join(REPO_ROOT, "freq", "data", "web", "js", "*.js"))
        self.assertGreater(len(html), 0, "No HTML files in web/")
        self.assertGreater(len(css), 0, "No CSS files in web/css/")
        self.assertGreater(len(js), 0, "No JS files in web/js/")


# ══════════════════════════════════════════════════════════════════════════
# Docker Compose validity
# ══════════════════════════════════════════════════════════════════════════

class TestDockerComposeTruth(unittest.TestCase):
    """docker-compose.yml must match README promises."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "docker-compose.yml")) as f:
            self.content = f.read()

    def test_port_8888_exposed(self):
        """Dashboard port 8888 must be exposed."""
        self.assertIn("8888", self.content)

    def test_references_dockerfile(self):
        """Must use local build (Dockerfile must exist)."""
        self.assertIn("build:", self.content)
        self.assertTrue(
            os.path.isfile(os.path.join(REPO_ROOT, "Dockerfile")),
            "Dockerfile must exist for docker compose build"
        )

    def test_read_only_root(self):
        """Container must use read_only root for security."""
        self.assertIn("read_only: true", self.content)

    def test_no_new_privileges(self):
        """Container must prevent privilege escalation."""
        self.assertIn("no-new-privileges", self.content)


# ══════════════════════════════════════════════════════════════════════════
# CHANGELOG references current version
# ══════════════════════════════════════════════════════════════════════════

class TestChangelogTruth(unittest.TestCase):
    """CHANGELOG must reference the current version."""

    def test_current_version_in_changelog(self):
        """freq.__version__ must appear in CHANGELOG.md."""
        from freq import __version__
        with open(os.path.join(REPO_ROOT, "CHANGELOG.md")) as f:
            content = f.read()
        self.assertIn(__version__, content,
                       f"CHANGELOG.md must reference current version {__version__}")


if __name__ == "__main__":
    unittest.main()
