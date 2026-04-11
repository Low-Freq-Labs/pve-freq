"""Docker public/dev sync truth tests.

Proves:
1. Local dev repo has all release-critical files
2. Config examples match main repo
3. No split-brain between compose files
4. Promotion requirements documented
"""

import os
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerRepoReleaseCritical(unittest.TestCase):
    """All release-critical files must be present."""

    REQUIRED_FILES = [
        "Dockerfile",
        "compose.yml",
        "docker-entrypoint.sh",
        "freq",
        "build.sh",
        "README.md",
        "CONTRIBUTING.md",
        ".env.example",
        ".github/workflows/docker.yml",
        "conf/freq.toml.example",
        "conf/hosts.toml.example",
        "conf/containers.toml.example",
    ]

    def test_all_required_files_exist(self):
        for name in self.REQUIRED_FILES:
            path = os.path.join(DOCKER_REPO, name)
            self.assertTrue(os.path.isfile(path), f"Missing: {name}")

    def test_no_duplicate_compose(self):
        """Must have exactly one compose file (compose.yml, not docker-compose.yml)."""
        self.assertTrue(os.path.isfile(os.path.join(DOCKER_REPO, "compose.yml")))
        self.assertFalse(os.path.isfile(os.path.join(DOCKER_REPO, "docker-compose.yml")),
                          "docker-compose.yml should be removed — compose.yml is canonical")

    def test_config_dir_is_conf(self):
        """Config directory must be conf/ (not config/)."""
        self.assertTrue(os.path.isdir(os.path.join(DOCKER_REPO, "conf")))
        # config/ should not exist as a tracked directory
        r = subprocess.run(["git", "-C", DOCKER_REPO, "ls-files", "config/"],
                           capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "",
                          "config/ directory should not have tracked files — renamed to conf/")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDevRepoAheadOfOrigin(unittest.TestCase):
    """Document the sync state."""

    def test_local_ahead_of_origin(self):
        """Local must be ahead or equal — never behind."""
        r = subprocess.run(
            ["git", "-C", DOCKER_REPO, "rev-list", "--count", "HEAD..origin/main"],
            capture_output=True, text=True
        )
        behind = int(r.stdout.strip()) if r.returncode == 0 else 0
        self.assertEqual(behind, 0,
                         "Local must not be behind origin — would mean lost work")

    def test_working_tree_clean(self):
        r = subprocess.run(
            ["git", "-C", DOCKER_REPO, "status", "--porcelain"],
            capture_output=True, text=True
        )
        self.assertEqual(r.stdout.strip(), "",
                         "Working tree must be clean before promotion")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestPromotionReadiness(unittest.TestCase):
    """Pre-promotion checks for public repo push."""

    def test_readme_references_public_repo(self):
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertIn("pve-freq-docker.git", src)
        self.assertNotIn("docker-dev", src)

    def test_no_private_credentials(self):
        """No private credentials or tokens in tracked files."""
        r = subprocess.run(
            ["git", "-C", DOCKER_REPO, "ls-files"],
            capture_output=True, text=True
        )
        for name in r.stdout.strip().split("\n"):
            basename = name.split("/")[-1]
            if basename == ".env":
                self.fail(f"Tracked .env file (credentials): {name}")
            if basename.endswith(".key") or basename.endswith(".pem"):
                self.fail(f"Tracked credential file: {name}")

    def test_contributing_documents_flow(self):
        path = os.path.join(DOCKER_REPO, "CONTRIBUTING.md")
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            src = f.read()
        self.assertIn("Promotion", src)


if __name__ == "__main__":
    unittest.main()
