"""Docker repo flow truth tests.

Proves:
1. Docker repo README clone URL points to public repo
2. Docker repo has CONTRIBUTING.md documenting dev→public flow
3. Config examples exist and match expected set
4. compose.yml uses correct runtime paths
5. No private/dev references leak into user-facing docs
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerRepoReadme(unittest.TestCase):
    """README must give honest instructions for public users."""

    def test_clone_url_is_public(self):
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertIn("pve-freq-docker.git", src,
                       "Clone URL must reference public repo")
        self.assertNotIn("docker-dev", src,
                          "README must NOT reference dev repo")

    def test_compose_reference_is_compose_yml(self):
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertIn("compose.yml", src)


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerRepoContributing(unittest.TestCase):
    """CONTRIBUTING.md must document the dev→public promotion flow."""

    def test_contributing_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(DOCKER_REPO, "CONTRIBUTING.md")))

    def test_documents_promotion_flow(self):
        with open(os.path.join(DOCKER_REPO, "CONTRIBUTING.md")) as f:
            src = f.read()
        self.assertIn("pve-freq-docker-dev", src,
                       "Must document the dev repo")
        self.assertIn("pve-freq-docker", src,
                       "Must document the public repo")
        self.assertIn("Promotion", src,
                       "Must document the promotion process")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerRepoConfigExamples(unittest.TestCase):
    """Config examples must exist for all critical files."""

    REQUIRED_EXAMPLES = [
        "containers.toml.example",
        "freq.toml.example",
        "hosts.toml.example",
        "users.conf.example",
        "vlans.toml.example",
    ]

    def test_required_examples_exist(self):
        conf_dir = os.path.join(DOCKER_REPO, "conf")
        for name in self.REQUIRED_EXAMPLES:
            self.assertTrue(
                os.path.isfile(os.path.join(conf_dir, name)),
                f"Missing required config example: {name}"
            )


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerComposeHonesty(unittest.TestCase):
    """compose.yml must use correct runtime paths."""

    def test_mounts_to_opt_pve_freq(self):
        with open(os.path.join(DOCKER_REPO, "compose.yml")) as f:
            src = f.read()
        self.assertIn("/opt/pve-freq/conf", src,
                       "Config must mount to /opt/pve-freq/conf")
        self.assertIn("/opt/pve-freq/data", src,
                       "Data must mount to /opt/pve-freq/data")


if __name__ == "__main__":
    unittest.main()
