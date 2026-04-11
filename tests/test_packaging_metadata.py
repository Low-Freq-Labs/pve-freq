"""Regression tests for packaging and repo metadata consistency.

Proves: all public-facing metadata surfaces (pyproject, CI, badges,
issue templates, security policy) are internally consistent and
reference the correct project coordinates.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

REPO_ORG = "Low-Freq-Labs"
REPO_NAME = "pve-freq"
REPO_FULL = f"{REPO_ORG}/{REPO_NAME}"


def _read(relpath):
    with open(os.path.join(REPO_ROOT, relpath)) as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════
# Cross-file repo URL consistency
# ══════════════════════════════════════════════════════════════════════════

class TestRepoUrlConsistency(unittest.TestCase):
    """All files must reference the same GitHub org/repo."""

    def test_pyproject_urls(self):
        toml = _read("pyproject.toml")
        self.assertIn(REPO_FULL, toml)

    def test_readme_badges(self):
        readme = _read("README.md")
        self.assertIn(REPO_FULL, readme)

    def test_install_sh_repo(self):
        install = _read("install.sh")
        self.assertIn(REPO_FULL, install)

    def test_contributing_clone_url(self):
        contrib = _read("CONTRIBUTING.md")
        self.assertIn(REPO_FULL, contrib)

    def test_security_policy(self):
        security = _read("SECURITY.md")
        self.assertIn(REPO_FULL, security)


# ══════════════════════════════════════════════════════════════════════════
# CI workflow consistency
# ══════════════════════════════════════════════════════════════════════════

class TestCiWorkflowTruth(unittest.TestCase):
    """CI workflow must be consistent with project requirements."""

    def setUp(self):
        self.workflow = _read(".github/workflows/test.yml")

    def test_ci_tests_debian(self):
        """CI must test on Debian (primary target)."""
        self.assertIn("debian:", self.workflow)

    def test_ci_tests_ubuntu(self):
        """CI must test on Ubuntu."""
        self.assertIn("ubuntu:", self.workflow)

    def test_ci_tests_rocky(self):
        """CI must test on Rocky Linux (RHEL family)."""
        self.assertIn("rockylinux:", self.workflow)

    def test_ci_runs_pytest(self):
        """CI must run pytest."""
        self.assertIn("pytest", self.workflow)

    def test_ci_distro_count_matches_badge(self):
        """CI distro count must be >= badge claim."""
        readme = _read("README.md")
        badge_match = re.search(r"tested_on-(\d+)_distros", readme)
        self.assertIsNotNone(badge_match)
        badge_count = int(badge_match.group(1))

        # Count unique distro images in CI matrix
        unique_images = set(re.findall(r"- '([^']+)'", self.workflow))
        ci_count = len(unique_images)

        self.assertGreaterEqual(
            ci_count, badge_count,
            f"CI tests {ci_count} distros but badge claims {badge_count}"
        )


# ══════════════════════════════════════════════════════════════════════════
# Pyproject classifiers match reality
# ══════════════════════════════════════════════════════════════════════════

class TestPyprojectClassifiers(unittest.TestCase):
    """pyproject.toml classifiers must match project reality."""

    def setUp(self):
        self.toml = _read("pyproject.toml")

    def test_production_stable_status(self):
        self.assertIn("Production/Stable", self.toml)

    def test_console_environment(self):
        self.assertIn("Environment :: Console", self.toml)

    def test_linux_only(self):
        self.assertIn("POSIX :: Linux", self.toml)

    def test_python_versions_listed(self):
        """Classifiers must list Python 3.11, 3.12, 3.13."""
        self.assertIn("Python :: 3.11", self.toml)
        self.assertIn("Python :: 3.12", self.toml)
        self.assertIn("Python :: 3.13", self.toml)

    def test_agpl_license_classifier(self):
        self.assertIn("AGPLv3", self.toml)

    def test_sysadmin_audience(self):
        self.assertIn("System Administrators", self.toml)


# ══════════════════════════════════════════════════════════════════════════
# Issue templates reference correct project
# ══════════════════════════════════════════════════════════════════════════

class TestIssueTemplates(unittest.TestCase):
    """GitHub issue templates must reference correct tooling."""

    def test_bug_template_asks_for_freq_doctor(self):
        """Bug report must ask for freq doctor output."""
        bug = _read(".github/ISSUE_TEMPLATE/bug_report.md")
        self.assertIn("freq doctor", bug)

    def test_bug_template_asks_for_version(self):
        """Bug report must ask for freq version."""
        bug = _read(".github/ISSUE_TEMPLATE/bug_report.md")
        self.assertIn("freq --version", bug)

    def test_bug_template_lists_install_methods(self):
        """Bug report must list all install methods."""
        bug = _read(".github/ISSUE_TEMPLATE/bug_report.md")
        self.assertIn("curl", bug)
        self.assertIn("pip", bug)


# ══════════════════════════════════════════════════════════════════════════
# Security policy references correct paths
# ══════════════════════════════════════════════════════════════════════════

class TestSecurityPolicyTruth(unittest.TestCase):
    """SECURITY.md must reference correct file paths."""

    def setUp(self):
        self.security = _read("SECURITY.md")

    def test_references_vault_module(self):
        self.assertIn("vault", self.security)

    def test_references_ssh_module(self):
        self.assertIn("ssh", self.security)

    def test_references_rbac(self):
        self.assertIn("RBAC", self.security)

    def test_vault_dir_permissions(self):
        """Must document vault dir as 600."""
        self.assertIn("600", self.security)


if __name__ == "__main__":
    unittest.main()
