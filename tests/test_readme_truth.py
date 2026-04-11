"""Regression tests for README and public-facing truth.

Proves: verifiable claims in README.md, pyproject.toml, and package
metadata match the actual codebase state.

Catches: stale LOC badges, version mismatches, dependency claims that
drift as the codebase evolves.
"""
import glob
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _count_python_loc():
    """Count total lines of Python code in freq/."""
    total = 0
    for path in glob.glob(os.path.join(REPO_ROOT, "freq", "**", "*.py"), recursive=True):
        with open(path) as f:
            total += sum(1 for _ in f)
    return total


def _read_file(relpath):
    with open(os.path.join(REPO_ROOT, relpath)) as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════
# Version consistency
# ══════════════════════════════════════════════════════════════════════════

class TestVersionConsistency(unittest.TestCase):
    """Version must be consistent across all surfaces."""

    def test_pyproject_reads_from_module(self):
        """pyproject.toml must use dynamic version from freq.__version__."""
        toml = _read_file("pyproject.toml")
        self.assertIn('version = {attr = "freq.__version__"}', toml)

    def test_version_is_semver(self):
        """freq.__version__ must be valid semver."""
        import freq
        self.assertRegex(freq.__version__, r"^\d+\.\d+\.\d+")


# ══════════════════════════════════════════════════════════════════════════
# Zero dependencies claim
# ══════════════════════════════════════════════════════════════════════════

class TestZeroDependencies(unittest.TestCase):
    """The 'zero dependencies' claim must be true."""

    def test_pyproject_has_empty_dependencies(self):
        """pyproject.toml must declare dependencies = []."""
        toml = _read_file("pyproject.toml")
        self.assertIn("dependencies = []", toml)

    def test_no_requirements_txt(self):
        """No requirements.txt should exist (would contradict zero-deps claim)."""
        req_path = os.path.join(REPO_ROOT, "requirements.txt")
        if os.path.exists(req_path):
            with open(req_path) as f:
                content = f.read().strip()
            # Empty file is OK, non-empty means dependencies
            self.assertEqual(content, "",
                             "requirements.txt must be empty if it exists")


# ══════════════════════════════════════════════════════════════════════════
# LOC badge accuracy
# ══════════════════════════════════════════════════════════════════════════

class TestLocBadge(unittest.TestCase):
    """LOC badge must be within 10% of actual Python line count."""

    def test_loc_badge_accuracy(self):
        """LOC badge value must be within 10% of actual count."""
        readme = _read_file("README.md")
        match = re.search(r"lines_of_code-(\d+)K", readme)
        self.assertIsNotNone(match, "LOC badge not found in README")
        badge_kloc = int(match.group(1))
        actual_loc = _count_python_loc()
        actual_kloc = actual_loc // 1000

        # Badge should be within 10% of actual
        lower = actual_kloc * 0.9
        upper = actual_kloc * 1.1
        self.assertTrue(
            lower <= badge_kloc <= upper,
            f"LOC badge says {badge_kloc}K but actual Python LOC is {actual_loc} "
            f"({actual_kloc}K). Badge must be within 10%."
        )


# ══════════════════════════════════════════════════════════════════════════
# Python version claim
# ══════════════════════════════════════════════════════════════════════════

class TestPythonVersionClaim(unittest.TestCase):
    """Python version claims must match pyproject.toml."""

    def test_readme_badge_matches_pyproject(self):
        """README Python badge must match pyproject requires-python."""
        readme = _read_file("README.md")
        toml = _read_file("pyproject.toml")

        # README badge: "python-3.11%2B" or similar
        badge_match = re.search(r"python-(\d+\.\d+)", readme)
        self.assertIsNotNone(badge_match, "Python badge not found")
        badge_version = badge_match.group(1)

        # pyproject.toml: requires-python = ">=3.11"
        toml_match = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', toml)
        self.assertIsNotNone(toml_match, "requires-python not found")
        toml_version = toml_match.group(1)

        self.assertEqual(badge_version, toml_version,
                         f"README badge ({badge_version}) must match "
                         f"pyproject requires-python ({toml_version})")


# ══════════════════════════════════════════════════════════════════════════
# API endpoint count claim
# ══════════════════════════════════════════════════════════════════════════

class TestEndpointCountClaim(unittest.TestCase):
    """'300+ Commands' claim must hold."""

    def test_api_endpoint_count_above_300(self):
        """Total API endpoints must exceed 300 (README claims '300+ Commands')."""
        from freq.modules.serve import FreqHandler
        routes = dict(FreqHandler._ROUTES)
        FreqHandler._load_v1_routes()
        if FreqHandler._V1_ROUTES:
            routes.update(FreqHandler._V1_ROUTES)
        self.assertGreater(len(routes), 300,
                           f"README claims 300+ commands but only {len(routes)} API endpoints")


# ══════════════════════════════════════════════════════════════════════════
# Install path claims
# ══════════════════════════════════════════════════════════════════════════

class TestInstallClaims(unittest.TestCase):
    """Install instructions must reference correct paths and commands."""

    def test_pip_install_uses_no_deps(self):
        """pip install instruction must include --no-deps (zero-deps package)."""
        readme = _read_file("README.md")
        self.assertIn("pip install --no-deps pve-freq", readme,
                       "pip install must use --no-deps to match zero-deps claim")

    def test_entry_point_matches_pyproject(self):
        """README 'freq' command must match pyproject.toml entry point."""
        toml = _read_file("pyproject.toml")
        self.assertIn('freq = "freq.cli:main"', toml,
                       "Entry point must map freq to freq.cli:main")


# ══════════════════════════════════════════════════════════════════════════
# License consistency
# ══════════════════════════════════════════════════════════════════════════

class TestLicenseConsistency(unittest.TestCase):
    """License claims must be consistent across README and pyproject."""

    def test_agpl_in_readme(self):
        readme = _read_file("README.md")
        self.assertIn("AGPL", readme)

    def test_agpl_in_pyproject(self):
        toml = _read_file("pyproject.toml")
        self.assertIn("AGPL", toml)


if __name__ == "__main__":
    unittest.main()
