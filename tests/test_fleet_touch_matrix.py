"""Live fleet-touch matrix tests — prove reachability, auth, and command
execution from the current VM across the whole fleet.

These are infrastructure integration tests, not unit tests. They require
network access to the fleet and valid SSH credentials. Skip gracefully
when run in CI or environments without fleet access.

Proves: every registered host in hosts.conf is reachable via SSH, the
SSH user can authenticate, and a basic command executes successfully.
Also proves PVE API tokens are valid and return expected data.

Run: pytest tests/test_fleet_touch_matrix.py -v
"""
import os
import subprocess
import sys
import unittest
from functools import lru_cache

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
LIVE_INSTALL_DIR = (
    os.environ.get("FREQ_TEST_INSTALL_DIR")
    or os.environ.get("FREQ_DIR")
    or ("/opt/pve-freq" if os.path.isfile("/opt/pve-freq/conf/freq.toml") else "")
)


def _has_live_runtime_config():
    return bool(
        LIVE_INSTALL_DIR
        and os.path.isfile(os.path.join(LIVE_INSTALL_DIR, "conf", "freq.toml"))
        and os.path.isfile(os.path.join(LIVE_INSTALL_DIR, "conf", "hosts.toml"))
    )


@lru_cache(maxsize=1)
def _runtime_config():
    from freq.core.config import load_config

    return load_config(install_dir=LIVE_INSTALL_DIR, force=True)


def _service_account():
    """Resolve the configured deployed service account from freq.toml."""
    return _runtime_config().ssh_service_account


def _pve_rw_token_id():
    """Resolve the configured runtime PVE RW token identity."""
    cfg = _runtime_config()
    return cfg.pve_api_token_id or f"{cfg.ssh_service_account}@pam!freq-rw"


def _ssh(ip, cmd, timeout=10, htype="linux"):
    """Run a command through freq's configured SSH transport."""
    from freq.core.ssh import run

    cfg = _runtime_config()
    r = run(
        host=ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=5,
        command_timeout=timeout,
        htype=htype,
        use_sudo=False,
        cfg=cfg,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _ssh_switch(ip, cmd, password, timeout=10):
    """SSH to a legacy Cisco switch through freq's transport."""
    return _ssh(ip, cmd, timeout=timeout, htype="switch")


def _curl_pve_api(ip, path, token_id, token_secret):
    """Call the PVE API and return (status_code, body)."""
    try:
        r = subprocess.run(
            ["curl", "-sk", "--max-time", "5",
             "-w", "\n%{http_code}",
             "-H", f"Authorization: PVEAPIToken={token_id}={token_secret}",
             f"https://{ip}:8006/api2/json{path}"],
            capture_output=True, text=True, timeout=10,
        )
        stdout = r.stdout
        if "\n" in stdout:
            body, status = stdout.rsplit("\n", 1)
        else:
            body, status = "", stdout
        return int(status.strip()), body.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return -1, ""


def _has_fleet_access():
    """Check if we can reach the fleet (ping pve01)."""
    if not _has_live_runtime_config():
        return False
    try:
        r = subprocess.run(
            ["ping", "-c1", "-W2", "10.25.255.26"],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _read_credential(path):
    """Read a credential file (may need sudo)."""
    try:
        r = subprocess.run(
            ["sudo", "cat", path],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _managed_host_rows():
    """Return live managed hosts as (ip, label, htype, groups)."""
    if not _has_live_runtime_config():
        return []
    from freq.core.host_scope import managed_probe_hosts

    return [
        (h.ip, h.label, h.htype, h.groups)
        for h in managed_probe_hosts(_runtime_config())
    ]


FLEET_AVAILABLE = _has_fleet_access()
HOSTS = _managed_host_rows()
SKIP_MSG = "Live fleet tests require FREQ_TEST_INSTALL_DIR/FREQ_DIR pointing at an initialized runtime config"


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestFleetSSHReachability(unittest.TestCase):
    """Every registered host must be reachable via SSH."""

    def test_all_hosts_ssh_reachable(self):
        """SSH port must accept connections on every registered host."""
        unreachable = []
        for ip, label, htype, _ in HOSTS:
            if htype == "switch":
                continue  # switch tested separately
            rc, out, err = _ssh(ip, "hostname", htype=htype)
            if rc != 0:
                unreachable.append(f"{label} ({ip}): rc={rc} err={err[:80]}")
        self.assertEqual(unreachable, [],
                         f"Hosts unreachable via SSH:\n" + "\n".join(unreachable))

    def test_all_hosts_return_correct_hostname(self):
        """SSH hostname must match the label (or a known variant)."""
        mismatches = []
        for ip, label, htype, _ in HOSTS:
            if htype == "switch":
                continue
            rc, out, err = _ssh(ip, "hostname", htype=htype)
            if rc != 0:
                continue  # reachability tested above
            hostname = out.split(".")[0].lower()  # strip FQDN
            if htype == "pfsense":
                # pfSense may return FQDN like pfsense01.infra.dc01
                if "pfsense" not in hostname:
                    mismatches.append(f"{label}: expected pfsense*, got {hostname}")
            elif hostname != label.lower():
                mismatches.append(f"{label}: expected {label}, got {hostname}")
        self.assertEqual(mismatches, [],
                         f"Hostname mismatches:\n" + "\n".join(mismatches))


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestFleetSudoCapability(unittest.TestCase):
    """Linux/PVE/Docker hosts must have passwordless sudo for the service account."""

    SUDO_TYPES = {"pve", "linux", "docker", "truenas"}

    def test_sudo_works_on_managed_hosts(self):
        """sudo -n whoami must return root on all managed host types."""
        failures = []
        for ip, label, htype, _ in HOSTS:
            if htype not in self.SUDO_TYPES:
                continue
            rc, out, err = _ssh(ip, "sudo -n whoami", htype=htype)
            if rc != 0 or "root" not in out:
                failures.append(f"{label} ({ip}): rc={rc} out={out[:40]}")
        self.assertEqual(failures, [],
                         f"Sudo failures:\n" + "\n".join(failures))


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestPVENodeOperations(unittest.TestCase):
    """PVE nodes must support qm list (VM inventory)."""

    PVE_IPS = [ip for ip, _, htype, _ in HOSTS if htype == "pve"]

    def test_qm_list_on_all_pve_nodes(self):
        """sudo qm list must succeed on every PVE node."""
        failures = []
        for ip in self.PVE_IPS:
            rc, out, err = _ssh(ip, "sudo qm list", htype="pve")
            if rc != 0:
                failures.append(f"{ip}: rc={rc} err={err[:80]}")
            elif "VMID" not in out:
                failures.append(f"{ip}: qm list output missing VMID header")
        self.assertEqual(failures, [],
                         f"qm list failures:\n" + "\n".join(failures))


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestPVEAPIAccess(unittest.TestCase):
    """PVE API must be accessible with configured tokens."""

    PVE_IPS = [ip for ip, _, htype, _ in HOSTS if htype == "pve"]

    def test_rw_token_returns_200(self):
        """Configured runtime RW token must authenticate on all PVE nodes."""
        secret = _read_credential("/etc/freq/credentials/pve-token-rw")
        if not secret:
            self.skipTest("No PVE RW token available")
        token_id = _pve_rw_token_id()
        failures = []
        for ip in self.PVE_IPS:
            code, body = _curl_pve_api(ip, "/version", token_id, secret)
            if code != 200:
                failures.append(f"{ip}: HTTP {code}")
        self.assertEqual(failures, [],
                         f"PVE RW API failures:\n" + "\n".join(failures))

    def test_ro_token_returns_200(self):
        """freq-watch@pve!watch must authenticate on all PVE nodes."""
        secret = _read_credential("/etc/freq/credentials/pve-token")
        if not secret:
            self.skipTest("No PVE RO token available")
        # Parse the token file (key=value format)
        token_map = {}
        for line in secret.split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                token_map[k.strip()] = v.strip()
        token_secret = token_map.get("PVE_TOKEN_SECRET", "")
        if not token_secret:
            self.skipTest("Cannot parse PVE RO token")
        failures = []
        for ip in self.PVE_IPS:
            code, body = _curl_pve_api(ip, "/version",
                                       "freq-watch@pve!watch", token_secret)
            if code != 200:
                failures.append(f"{ip}: HTTP {code}")
        self.assertEqual(failures, [],
                         f"PVE RO API failures:\n" + "\n".join(failures))

    def test_pve_cluster_has_3_nodes(self):
        """PVE cluster must report exactly 3 nodes."""
        secret = _read_credential("/etc/freq/credentials/pve-token-rw")
        if not secret:
            self.skipTest("No PVE RW token available")
        token_id = _pve_rw_token_id()
        code, body = _curl_pve_api(
            self.PVE_IPS[0], "/nodes", token_id, secret,
        )
        self.assertEqual(code, 200)
        import json
        data = json.loads(body)["data"]
        self.assertEqual(len(data), 3,
                         f"Expected 3 PVE nodes, got {len(data)}")


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestSwitchAccess(unittest.TestCase):
    """Cisco switch must be reachable with legacy ciphers + password."""

    def test_switch_show_version(self):
        """show version must return Cisco IOS info."""
        pw = _read_credential("/etc/freq/credentials/switch-password")
        if not pw:
            self.skipTest("No switch password available")
        rc, out, err = _ssh_switch("10.25.255.5", "show version", pw)
        self.assertEqual(rc, 0, f"Switch SSH failed: {err[:80]}")
        self.assertIn("Cisco IOS", out)


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestDockerHostOperations(unittest.TestCase):
    """Docker hosts must be able to list containers."""

    DOCKER_HOSTS = [(ip, label) for ip, label, htype, _ in HOSTS
                    if htype == "docker"]

    def test_docker_ps_on_all_docker_hosts(self):
        """sudo docker ps must succeed on every docker-type host."""
        failures = []
        for ip, label in self.DOCKER_HOSTS:
            rc, out, err = _ssh(ip, "sudo docker ps --format '{{.Names}}'", htype="docker")
            if rc != 0:
                failures.append(f"{label} ({ip}): rc={rc} err={err[:80]}")
        self.assertEqual(failures, [],
                         f"docker ps failures:\n" + "\n".join(failures))


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestCrossVLANReachability(unittest.TestCase):
    """Prove which VLAN paths work from VM 5005."""

    def test_dev_vlan_reaches_freq_test(self):
        """DEV VLAN (10.25.10.x) must reach freq-test."""
        rc, out, _ = _ssh("10.25.10.55", "hostname")
        self.assertEqual(rc, 0)
        self.assertIn("freq-test", out)

    def test_dev_vlan_reaches_pve_freq(self):
        """DEV VLAN must reach pve-freq VM."""
        rc, out, _ = _ssh("10.25.10.50", "hostname")
        self.assertEqual(rc, 0)
        self.assertIn("pve-freq", out)


if __name__ == "__main__":
    unittest.main()
