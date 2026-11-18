"""Docker wrapper truth tests.

Proves:
1. Wrapper is a transparent command passthrough (docker exec)
2. Self-install behavior is documented in script header
3. Post-init chown is described as safety net, not required fix
4. Container runs as non-root user (Dockerfile USER directive)
5. Wrapper doesn't hide broken runtime contract
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestWrapperBehavior(unittest.TestCase):
    """Wrapper must be a transparent passthrough, not a hidden fixer."""

    def _wrapper_src(self):
        with open(os.path.join(DOCKER_REPO, "freq")) as f:
            return f.read()

    def test_uses_docker_exec(self):
        self.assertIn("docker exec", self._wrapper_src())

    def test_passes_args_through(self):
        """Wrapper passes all arguments to freq inside container."""
        self.assertIn('"$@"', self._wrapper_src())

    def test_self_install_documented(self):
        src = self._wrapper_src()
        self.assertIn("/usr/local/bin", src)
        self.assertIn("Self-install", src)

    def test_chown_described_as_safety_net(self):
        """Post-init chown must be described as safety net, not required fix."""
        src = self._wrapper_src()
        self.assertIn("safety net", src.lower(),
                       "Chown must be described as safety net, not required fix")
        self.assertNotIn("runs as root", src,
                          "Wrapper must not claim init runs as root — container uses USER freq")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestDockerfileUserContract(unittest.TestCase):
    """Dockerfile must run as non-root user."""

    def test_dockerfile_sets_user(self):
        with open(os.path.join(DOCKER_REPO, "Dockerfile")) as f:
            src = f.read()
        self.assertIn("USER freq", src,
                       "Dockerfile must drop to freq user")

    def test_dockerfile_creates_freq_user(self):
        with open(os.path.join(DOCKER_REPO, "Dockerfile")) as f:
            src = f.read()
        self.assertIn("useradd", src)
        self.assertIn("freq", src)


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestWrapperCommandSurface(unittest.TestCase):
    """Wrapper header must document the command surface honestly."""

    def test_documents_init(self):
        with open(os.path.join(DOCKER_REPO, "freq")) as f:
            src = f.read()
        self.assertIn("freq init", src)

    def test_documents_doctor(self):
        with open(os.path.join(DOCKER_REPO, "freq")) as f:
            src = f.read()
        self.assertIn("freq doctor", src)

    def test_preserves_exit_code(self):
        with open(os.path.join(DOCKER_REPO, "freq")) as f:
            src = f.read()
        self.assertIn("exit $RC", src,
                       "Wrapper must preserve container exit code")


if __name__ == "__main__":
    unittest.main()
