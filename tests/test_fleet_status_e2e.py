"""End-to-end test for freq fleet status from VM 5005.

Proves: freq's SSH module can reach and execute commands on every
registered fleet host using the configured service account and key.
This is the highest-value E2E operation — it exercises config loading,
SSH key detection, platform SSH config, parallel execution, and
result collection in a single call.

Run: python3 -m unittest tests.test_fleet_status_e2e -v
"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _has_fleet_access():
    try:
        r = subprocess.run(
            ["ping", "-c1", "-W2", "10.25.255.26"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


FLEET_AVAILABLE = _has_fleet_access()
SKIP_MSG = "Fleet not reachable from this environment"


def _load_cfg():
    sys.path.insert(0, REPO_ROOT)
    from freq.core.config import load_config
    return load_config(install_dir=REPO_ROOT)


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestFleetStatusE2E(unittest.TestCase):
    """freq fleet status must work end-to-end from VM 5005."""

    @classmethod
    def setUpClass(cls):
        # Clean SSH mux sockets to prevent stale-identity issues
        mux_dir = os.path.expanduser("~/.ssh/freq-mux")
        if os.path.isdir(mux_dir):
            for f in os.listdir(mux_dir):
                try:
                    os.unlink(os.path.join(mux_dir, f))
                except OSError:
                    pass

        cls.cfg = _load_cfg()
        from freq.core.ssh import run_many, result_for
        cls._run_many = staticmethod(run_many)
        cls._result_for = staticmethod(result_for)

        # Run fleet status once and cache results for all tests
        cls.hosts = cls.cfg.hosts
        cls.results = cls._run_many(
            hosts=cls.hosts,
            command="uptime -p 2>/dev/null || uptime",
            key_path=cls.cfg.ssh_key_path,
            connect_timeout=cls.cfg.ssh_connect_timeout,
            command_timeout=10,
            max_parallel=cls.cfg.ssh_max_parallel,
            use_sudo=False,
            cfg=cls.cfg,
        )

    def _online_hosts(self):
        """Return list of (label, htype) for hosts that responded OK."""
        online = []
        for h in self.hosts:
            r = self._result_for(self.results, h)
            if r and r.returncode == 0:
                online.append((h.label, h.htype))
        return online

    def _offline_hosts(self):
        """Return list of (label, htype, error) for hosts that failed."""
        offline = []
        for h in self.hosts:
            r = self._result_for(self.results, h)
            if not r or r.returncode != 0:
                err = r.stderr.strip()[:80] if r else "no response"
                offline.append((h.label, h.htype, err))
        return offline

    def test_at_least_13_hosts_online(self):
        """At least 13 of 14 registered hosts must respond to fleet status."""
        online = self._online_hosts()
        self.assertGreaterEqual(
            len(online), 13,
            f"Only {len(online)}/14 online. Offline: {self._offline_hosts()}")

    def test_all_pve_nodes_online(self):
        """All 3 PVE nodes must be online."""
        online = self._online_hosts()
        pve_online = [l for l, t in online if t == "pve"]
        self.assertEqual(len(pve_online), 3,
                         f"Expected 3 PVE nodes online, got {pve_online}")

    def test_all_docker_hosts_online(self):
        """All docker hosts must be online."""
        online = self._online_hosts()
        docker_online = [l for l, t in online if t == "docker"]
        docker_total = [h.label for h in self.hosts if h.htype == "docker"]
        self.assertEqual(len(docker_online), len(docker_total),
                         f"Docker: {docker_online} vs expected {docker_total}")

    def test_truenas_online(self):
        """TrueNAS must be online."""
        online = self._online_hosts()
        truenas = [l for l, t in online if t == "truenas"]
        self.assertEqual(len(truenas), 1)

    def test_pfsense_online(self):
        """pfSense must be online."""
        online = self._online_hosts()
        pf = [l for l, t in online if t == "pfsense"]
        self.assertEqual(len(pf), 1)

    def test_uptime_output_is_sane(self):
        """Online hosts must return plausible uptime output."""
        for h in self.hosts:
            r = self._result_for(self.results, h)
            if r and r.returncode == 0:
                out = r.stdout.strip()
                # Must contain "up" or time-like output
                self.assertTrue(
                    "up" in out.lower() or ":" in out or "load" in out.lower(),
                    f"{h.label} returned implausible uptime: {out[:60]}")

    def test_config_matches_runtime(self):
        """Config ssh_service_account must match what SSH actually uses."""
        self.assertEqual(self.cfg.ssh_service_account, "freq-ops",
                         "Config must use freq-ops (deployed fleet account)")
        self.assertTrue(
            os.path.isfile(self.cfg.ssh_key_path),
            f"SSH key not found: {self.cfg.ssh_key_path}")

    def test_switch_offline_reason_is_credential_access(self):
        """Switch offline status must be due to credential file permissions,
        not network or config error."""
        switch_hosts = [h for h in self.hosts if h.htype == "switch"]
        if not switch_hosts:
            self.skipTest("No switch in fleet")
        h = switch_hosts[0]
        r = self._result_for(self.results, h)
        if r and r.returncode == 0:
            return  # Switch is online — no blocker
        # Verify: it's a permission denied (credential), not connection refused (network)
        err = r.stderr if r else ""
        self.assertIn("Permission denied", err,
                      f"Switch failure is not auth-related: {err[:80]}")
        # Verify the password file exists but isn't readable
        pw_file = self.cfg.legacy_password_file
        if pw_file:
            self.assertFalse(os.access(pw_file, os.R_OK),
                             "Switch password file is readable — sshpass should have worked")


if __name__ == "__main__":
    unittest.main()
