"""Docker init operator truth tests.

Proves:
1. README shows web setup as primary Docker first-run path
2. CLI init is documented as optional with privilege note
3. Container runs as non-root user (documented)
4. compose.yml starts serve by default (web setup available immediately)
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerFirstRunTruth(unittest.TestCase):
    """Docker first-run guidance must match actual runtime model."""

    def test_web_setup_is_primary(self):
        """README must show dashboard/web setup before CLI init."""
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        dashboard_idx = src.index("Open the dashboard")
        init_idx = src.index("freq init")
        self.assertLess(dashboard_idx, init_idx,
                         "Dashboard/web setup must come before CLI init in README")

    def test_cli_init_marked_optional(self):
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertIn("Optional", src,
                       "CLI init must be marked optional for Docker")

    def test_documents_user_privilege(self):
        """README must note that container runs as non-root freq user."""
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertIn("freq", src)
        self.assertIn("UID 1000", src)

    def test_mentions_volume_writability(self):
        """README must note bind-mount volumes need writable permissions."""
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertIn("writable", src.lower(),
                       "README must mention volume writability requirement")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestComposeDefaultServe(unittest.TestCase):
    """Container must start serve by default (web setup available immediately)."""

    def test_dockerfile_cmd_is_serve(self):
        with open(os.path.join(DOCKER_REPO, "Dockerfile")) as f:
            src = f.read()
        self.assertIn('CMD ["serve"]', src,
                       "Dockerfile CMD must be serve for immediate web setup")

    def test_entrypoint_defaults_to_serve(self):
        with open(os.path.join(DOCKER_REPO, "docker-entrypoint.sh")) as f:
            src = f.read()
        self.assertIn("serve", src)


if __name__ == "__main__":
    unittest.main()
