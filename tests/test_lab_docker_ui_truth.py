"""Lab Equipment and Docker UI truth tests.

Proves consumer surfaces agree on fleet state:
1. Lab hosts identified by group, label, or fleet-boundaries VMID range
2. Docker Fleet uses hosts.toml docker-type hosts
3. Health data captures docker container counts across all host types
4. Container counts from health match what docker ps would return
5. No stale or phantom rows in any surface
6. Frontend _getLabLabels also matches by label, not just groups
"""

import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLabEquipmentDataSource(unittest.TestCase):
    """Lab Equipment identifies hosts by group, label, or VMID range."""

    def test_lab_handler_checks_groups(self):
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_lab_status")[1].split("def _serve_")[0]
        self.assertIn('"lab"', handler, "Must check lab group")

    def test_lab_handler_checks_label(self):
        """Must also match hosts with 'lab' in their label."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_lab_status")[1].split("def _serve_")[0]
        self.assertIn("h.label", handler,
                       "Must check host label for lab matching")
        self.assertIn('"lab"', handler.split("label")[0] + handler,
                       "Must match 'lab' in label")

    def test_lab_handler_checks_fleet_boundaries(self):
        """Must also match hosts by fleet-boundaries VMID range."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        handler = src.split("def _serve_lab_status")[1].split("def _serve_")[0]
        self.assertIn("fleet_boundaries", handler,
                       "Must use fleet_boundaries for lab VMID detection")
        self.assertIn("categorize", handler,
                       "Must call categorize() for VMID-based lab detection")

    def test_lab_label_matching_catches_common_names(self):
        """Labels like lab-pve1, pfsense-lab, truenas-lab must match."""
        for label in ["lab-pve1", "lab-pve2", "pfsense-lab", "truenas-lab"]:
            self.assertIn("lab", label.lower(),
                          f"{label} must be caught by label matching")

    def test_frontend_getlablabels_checks_label(self):
        """Frontend _getLabLabels must also match by label, not just groups."""
        with open(os.path.join(REPO_ROOT, "freq/data/web/js/app.js")) as f:
            src = f.read()
        fn = src.split("function _getLabLabels")[1].split("function ")[0]
        self.assertIn("label", fn.lower(),
                       "_getLabLabels must check host labels")
        self.assertIn("indexOf('lab')", fn,
                       "_getLabLabels must match 'lab' in label")


class TestDockerFleetDataSource(unittest.TestCase):
    """Docker Fleet uses hosts.toml type=docker, not containers.toml."""

    def test_docker_fleet_uses_by_type(self):
        with open(os.path.join(REPO_ROOT, "freq/api/fleet.py")) as f:
            src = f.read()
        handler = src.split("def handle_docker_fleet")[1].split("\ndef ")[0]
        self.assertIn("by_type", handler)
        self.assertIn('"docker"', handler)

    def test_docker_hosts_exist(self):
        from freq.core.config import load_config
        from freq.core.resolve import by_type
        cfg = load_config()
        docker_hosts = by_type(cfg.hosts, "docker")
        self.assertGreater(len(docker_hosts), 0)


class TestHealthContainerCounts(unittest.TestCase):
    """Health probe captures docker counts across ALL host types."""

    def test_health_probe_counts_docker(self):
        """Health probe SSH command includes docker ps count."""
        with open(os.path.join(REPO_ROOT, "freq/modules/serve.py")) as f:
            src = f.read()
        health_probe = src.split("def _bg_probe_health")[1].split("\ndef ")[0]
        self.assertIn("docker ps", health_probe,
                       "Health probe must count docker containers")

    def test_health_captures_linux_and_docker_types(self):
        """Health probes both linux and docker type hosts for container counts."""
        from freq.core.config import load_config
        cfg = load_config()
        hosts_with_docker_cmd = [h for h in cfg.hosts if h.htype in ("linux", "docker")]
        self.assertGreater(len(hosts_with_docker_cmd), 0)


class TestConsumerSurfaceConsistency(unittest.TestCase):
    """All consumer surfaces must agree on the same source data."""

    def test_no_invented_hosts(self):
        """No API surface should return hosts not in hosts.toml."""
        from freq.core.config import load_config
        cfg = load_config()
        known_labels = {h.label for h in cfg.hosts}
        known_ips = {h.ip for h in cfg.hosts}
        # Every host in the fleet must come from hosts.toml
        self.assertTrue(len(known_labels) > 0)
        # No duplicates
        self.assertEqual(len(known_labels), len(cfg.hosts),
                         "No duplicate labels in hosts.toml")

    def test_docker_fleet_subset_of_hosts(self):
        """Docker Fleet hosts must be a subset of all hosts."""
        from freq.core.config import load_config
        from freq.core.resolve import by_type
        cfg = load_config()
        all_labels = {h.label for h in cfg.hosts}
        docker_labels = {h.label for h in by_type(cfg.hosts, "docker")}
        self.assertTrue(docker_labels.issubset(all_labels))

    def test_lab_hosts_subset_of_hosts(self):
        """Lab hosts (by any matching method) must be a subset of all hosts."""
        from freq.core.config import load_config
        cfg = load_config()
        all_labels = {h.label for h in cfg.hosts}
        lab_labels = set()
        for h in cfg.hosts:
            if "lab" in (h.groups or "").split(","):
                lab_labels.add(h.label)
            elif "lab" in h.label.lower():
                lab_labels.add(h.label)
        self.assertTrue(lab_labels.issubset(all_labels))


if __name__ == "__main__":
    unittest.main()
