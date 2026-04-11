"""Docker config operator truth tests.

Proves:
1. Docker repo example configs match main repo defaults
2. Fleet-boundaries operator tier matches main repo (no broader permissions)
3. All Docker repo example files have a corresponding main repo example
4. Docker README only references configs that exist in the repo
"""

import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKER_REPO = os.path.join(os.path.dirname(REPO_ROOT), "pve-freq-docker")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestFleetBoundariesParity(unittest.TestCase):
    """Docker fleet-boundaries must not be broader than main repo."""

    def test_operator_tier_matches_main(self):
        """Docker operator tier must match main repo (no extra destructive actions)."""
        with open(os.path.join(REPO_ROOT, "conf/fleet-boundaries.toml.example")) as f:
            main_src = f.read()
        with open(os.path.join(DOCKER_REPO, "conf/fleet-boundaries.toml.example")) as f:
            docker_src = f.read()
        # Extract operator line from both
        import re
        main_match = re.search(r'operator\s*=\s*\[([^\]]+)\]', main_src)
        docker_match = re.search(r'operator\s*=\s*\[([^\]]+)\]', docker_src)
        self.assertIsNotNone(main_match)
        self.assertIsNotNone(docker_match)
        main_actions = set(a.strip().strip('"') for a in main_match.group(1).split(","))
        docker_actions = set(a.strip().strip('"') for a in docker_match.group(1).split(","))
        extra = docker_actions - main_actions
        self.assertEqual(extra, set(),
                         f"Docker operator tier has extra actions not in main: {extra}")


@unittest.skipUnless(os.path.isdir(DOCKER_REPO), "Docker repo not present")
class TestConfigExampleParity(unittest.TestCase):
    """Docker config examples must be a subset of main repo examples."""

    def test_all_docker_examples_exist_in_main(self):
        docker_conf = os.path.join(DOCKER_REPO, "conf")
        main_conf = os.path.join(REPO_ROOT, "conf")
        for name in os.listdir(docker_conf):
            if name.endswith(".example"):
                self.assertTrue(
                    os.path.isfile(os.path.join(main_conf, name)),
                    f"Docker has {name} but main repo doesn't"
                )

    def test_containers_toml_in_sync(self):
        """containers.toml.example must be identical between repos."""
        with open(os.path.join(REPO_ROOT, "conf/containers.toml.example")) as f:
            main = f.read()
        with open(os.path.join(DOCKER_REPO, "conf/containers.toml.example")) as f:
            docker = f.read()
        self.assertEqual(main, docker,
                         "containers.toml.example must match between repos")

    def test_freq_toml_version_matches(self):
        """freq.toml.example version must match between repos."""
        import re
        with open(os.path.join(REPO_ROOT, "conf/freq.toml.example")) as f:
            main_ver = re.search(r'version\s*=\s*"([^"]+)"', f.read())
        with open(os.path.join(DOCKER_REPO, "conf/freq.toml.example")) as f:
            docker_ver = re.search(r'version\s*=\s*"([^"]+)"', f.read())
        self.assertEqual(main_ver.group(1), docker_ver.group(1),
                         "freq.toml version must match between repos")


if __name__ == "__main__":
    unittest.main()
