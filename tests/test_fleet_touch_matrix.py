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
import tomllib
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _service_account():
    """Resolve the configured deployed service account from freq.toml."""
    path = os.path.join(REPO_ROOT, "conf", "freq.toml")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return data.get("ssh", {}).get("service_account", "freq-admin")
    except OSError:
        return "freq-admin"


def _ssh(ip, cmd, timeout=10):
    """Run a command on a remote host via SSH. Returns (rc, stdout, stderr)."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
             "-o", "StrictHostKeyChecking=no", ip, cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1, "", "timeout or ssh not found"


def _ssh_switch(ip, cmd, password, timeout=10):
    """SSH to a legacy Cisco switch with password auth and old ciphers."""
    try:
        r = subprocess.run(
            ["sshpass", "-p", password,
             "ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
             "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
             "-o", "HostKeyAlgorithms=+ssh-rsa",
             "-o", "PubkeyAcceptedKeyTypes=+ssh-rsa",
             f"{_service_account()}@{ip}", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1, "", "timeout or sshpass not found"


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
        lines = r.stdout.strip().rsplit("\n", 1)
        if len(lines) == 2:
            return int(lines[1]), lines[0]
        return -1, r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return -1, ""


def _has_fleet_access():
    """Check if we can reach the fleet (ping pve01)."""
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


# Parse hosts.conf for the registered fleet
def _parse_hosts_conf():
    """Parse hosts.conf and return list of (ip, label, htype, groups)."""
    hosts = []
    path = os.path.join(REPO_ROOT, "conf", "hosts.conf")
    if not os.path.isfile(path):
        return hosts
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                ip, label, htype = parts[0], parts[1], parts[2]
                groups = parts[3] if len(parts) > 3 else ""
                hosts.append((ip, label, htype, groups))
    return hosts


FLEET_AVAILABLE = _has_fleet_access()
HOSTS = _parse_hosts_conf()
SKIP_MSG = "Fleet not reachable from this environment"


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestFleetSSHReachability(unittest.TestCase):
    """Every registered host must be reachable via SSH."""

    def test_all_hosts_ssh_reachable(self):
        """SSH port must accept connections on every registered host."""
        unreachable = []
        for ip, label, htype, _ in HOSTS:
            if htype == "switch":
                continue  # switch tested separately
            rc, out, err = _ssh(ip, "hostname")
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
            rc, out, err = _ssh(ip, "hostname")
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
            rc, out, err = _ssh(ip, "sudo -n whoami")
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
            rc, out, err = _ssh(ip, "sudo qm list")
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
        """freq-ops@pam!freq-rw must authenticate on all PVE nodes."""
        secret = _read_credential("/etc/freq/credentials/pve-token-rw")
        if not secret:
            self.skipTest("No PVE RW token available")
        failures = []
        for ip in self.PVE_IPS:
            code, body = _curl_pve_api(ip, "/version",
                                       "freq-ops@pam!freq-rw", secret)
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
        code, body = _curl_pve_api(
            self.PVE_IPS[0], "/nodes",
            "freq-ops@pam!freq-rw", secret,
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
            rc, out, err = _ssh(ip, "sudo docker ps --format '{{.Names}}'")
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
