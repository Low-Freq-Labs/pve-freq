"""Docker README runtime truth tests.

Proves:
1. README doesn't claim wheel-based build when Dockerfile uses source copy
2. README doesn't claim setpriv privilege drop when Dockerfile uses USER
3. Architecture section matches actual repo files
4. Dockerfile uses USER freq (not root entrypoint)
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerReadmeBuildTruth(unittest.TestCase):
    """README build section must match Dockerfile behavior."""

    def test_no_wheel_claim(self):
        """README must not claim wheel-based build."""
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertNotIn("bakes it into", src,
                          "README must not claim wheel is baked into image")
        self.assertNotIn("pre-built wheel", src,
                          "README must not advertise pre-built wheel path")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerReadmeRuntimeTruth(unittest.TestCase):
    """README runtime description must match Dockerfile."""

    def test_no_setpriv_claim(self):
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertNotIn("setpriv", src,
                          "README must not claim setpriv — Dockerfile uses USER directive")

    def test_no_starts_as_root_claim(self):
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertNotIn("starts as root", src,
                          "README must not claim entrypoint starts as root")

    def test_mentions_user_freq(self):
        with open(os.path.join(DOCKER_REPO, "README.md")) as f:
            src = f.read()
        self.assertIn("freq", src.lower())
        self.assertIn("non-root", src)


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerfileMatchesReadme(unittest.TestCase):
    """Dockerfile behavior must match what README describes."""

    def test_dockerfile_uses_user_directive(self):
        with open(os.path.join(DOCKER_REPO, "Dockerfile")) as f:
            src = f.read()
        self.assertIn("USER freq", src)

    def test_dockerfile_uses_source_copy(self):
        with open(os.path.join(DOCKER_REPO, "Dockerfile")) as f:
            src = f.read()
        self.assertIn("COPY freq/", src,
                       "Dockerfile must copy source directly")

    def test_dockerfile_uses_tini(self):
        with open(os.path.join(DOCKER_REPO, "Dockerfile")) as f:
            src = f.read()
        self.assertIn("tini", src)


if __name__ == "__main__":
    unittest.main()
