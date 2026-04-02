"""Tests for Phase 6 — The Fleet (WS13-14, 17-18).
Covers: Module imports, CLI registration, Docker host filtering, hardware commands.
"""
import sys, unittest
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

@dataclass
class MockHost:
    ip: str; label: str; htype: str; groups: str = ""

class MockConfig:
    def __init__(self):
        self.hosts = [
            MockHost("10.0.0.1", "arr-stack", "docker"),
            MockHost("10.0.0.2", "plex", "docker"),
            MockHost("10.0.0.3", "pve01", "pve"),
        ]
        self.ssh_key_path = "/tmp/test"
        self.ssh_connect_timeout = 5

class TestDockerHostFilter(unittest.TestCase):
    def test_filters_docker_hosts(self):
        from freq.modules.docker_mgmt import _docker_hosts
        cfg = MockConfig()
        hosts = _docker_hosts(cfg)
        self.assertEqual(len(hosts), 2)
        self.assertTrue(all(h.htype == "docker" for h in hosts))

class TestPhase6Imports(unittest.TestCase):
    def test_docker_mgmt(self):
        from freq.modules.docker_mgmt import cmd_docker_containers, cmd_docker_images, cmd_docker_prune, cmd_docker_update_check
        self.assertTrue(callable(cmd_docker_containers))
    def test_hardware(self):
        from freq.modules.hardware import cmd_hw_smart, cmd_hw_ups, cmd_hw_power, cmd_hw_inventory
        self.assertTrue(callable(cmd_hw_smart))

class TestPhase6CLI(unittest.TestCase):
    def setUp(self):
        from freq.cli import _build_parser
        self.parser = _build_parser()
    def _parse(self, s):
        return self.parser.parse_args(s.split())
    def test_docker_list(self):
        self.assertTrue(hasattr(self._parse("docker list"), "func"))
    def test_docker_images(self):
        self.assertTrue(hasattr(self._parse("docker images"), "func"))
    def test_docker_prune(self):
        self.assertTrue(hasattr(self._parse("docker prune"), "func"))
    def test_docker_update_check(self):
        self.assertTrue(hasattr(self._parse("docker update-check"), "func"))
    def test_hw_smart(self):
        self.assertTrue(hasattr(self._parse("hw smart"), "func"))
    def test_hw_ups(self):
        self.assertTrue(hasattr(self._parse("hw ups"), "func"))
    def test_hw_power(self):
        self.assertTrue(hasattr(self._parse("hw power"), "func"))
    def test_hw_inventory(self):
        self.assertTrue(hasattr(self._parse("hw inventory"), "func"))

if __name__ == "__main__":
    unittest.main()
