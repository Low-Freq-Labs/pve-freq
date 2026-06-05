"""Regression tests for fleet auth configuration drift.

Proves: the SSH service account and key configured in freq.toml
actually work for fleet operations. Catches drift between config
and deployed credentials.
"""
import os
import subprocess
import sys
import unittest
from functools import lru_cache

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


def _load_freq_config():
    """Load freq.toml SSH settings."""
    import tomllib
    toml_path = os.path.join(REPO_ROOT, "conf", "freq.toml")
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    return data.get("ssh", {})


@lru_cache(maxsize=1)
def _load_runtime_config():
    from freq.core.config import load_config

    return load_config(install_dir=REPO_ROOT)


def _parse_hosts_conf():
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
                hosts.append((parts[0], parts[1], parts[2]))
    return hosts


FLEET_AVAILABLE = _has_fleet_access()
SKIP_MSG = "Fleet not reachable from this environment"


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestSSHServiceAccountExists(unittest.TestCase):
    """The configured SSH service account must exist on fleet hosts."""

    def test_service_account_exists_on_pve_nodes(self):
        ssh_cfg = _load_freq_config()
        account = ssh_cfg.get("service_account", "freq-admin")
        hosts = _parse_hosts_conf()
        pve_hosts = [ip for ip, _, htype in hosts if htype == "pve"]
        failures = []
        cfg = _load_runtime_config()
        from freq.core.ssh import run
        for ip in pve_hosts:
            r = run(
                host=ip,
                command=f"id {account}",
                key_path=cfg.ssh_key_path,
                connect_timeout=5,
                command_timeout=10,
                htype="pve",
                use_sudo=False,
                cfg=cfg,
            )
            if r.returncode != 0:
                reason = (r.stderr or r.stdout or "").strip()[:80]
                failures.append(f"{ip}: {reason or 'unable to verify account'}")
        self.assertEqual(failures, [],
                         f"Account '{account}' could not be verified:\n" + "\n".join(failures))

    def test_service_account_has_sudo_on_pve_nodes(self):
        ssh_cfg = _load_freq_config()
        account = ssh_cfg.get("service_account", "freq-admin")
        hosts = _parse_hosts_conf()
        pve_hosts = [ip for ip, _, htype in hosts if htype == "pve"]
        failures = []
        cfg = _load_runtime_config()
        from freq.core.ssh import run
        for ip in pve_hosts:
            r = run(
                host=ip,
                command="sudo -n whoami",
                key_path=cfg.ssh_key_path,
                connect_timeout=5,
                command_timeout=10,
                htype="pve",
                use_sudo=False,
                cfg=cfg,
            )
            if r.returncode != 0 or "root" not in r.stdout:
                reason = (r.stderr or r.stdout or "").strip()[:80]
                failures.append(f"{ip}: {reason or 'sudo check failed'}")
        self.assertEqual(failures, [],
                         f"Account '{account}' sudo could not be verified:\n" + "\n".join(failures))


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestSSHKeyDeployment(unittest.TestCase):
    """An SSH key must be available for freq to use."""

    def test_key_exists_in_data_keys_or_ssh(self):
        """At least one SSH key must be detectable by freq's key resolution."""
        candidates = [
            os.path.join(REPO_ROOT, "data", "keys", "freq_id_ed25519"),
            os.path.expanduser("~/.ssh/id_ed25519"),
            os.path.expanduser("~/.ssh/fleet_key"),
            os.path.join(REPO_ROOT, "data", "keys", "freq_id_rsa"),
            os.path.expanduser("~/.ssh/id_rsa"),
        ]
        found = [p for p in candidates if os.path.isfile(p)]
        self.assertGreater(len(found), 0,
                           f"No SSH key found in freq key search path: {candidates}")

    def test_key_permissions_are_600(self):
        """SSH key files must have 600 permissions."""
        candidates = [
            os.path.join(REPO_ROOT, "data", "keys", "freq_id_ed25519"),
            os.path.expanduser("~/.ssh/id_ed25519"),
            os.path.expanduser("~/.ssh/fleet_key"),
            os.path.join(REPO_ROOT, "data", "keys", "freq_id_rsa"),
            os.path.expanduser("~/.ssh/id_rsa"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                mode = oct(os.stat(path).st_mode)[-3:]
                self.assertEqual(mode, "600",
                                 f"Key {path} has permissions {mode}, expected 600")


@unittest.skipUnless(FLEET_AVAILABLE, SKIP_MSG)
class TestPVETokenValidity(unittest.TestCase):
    """PVE API tokens must authenticate successfully."""

    PVE_IPS = ["10.25.255.26", "10.25.255.27", "10.25.255.28"]

    def _read_credential(self, path):
        try:
            r = subprocess.run(
                ["sudo", "cat", path],
                capture_output=True, text=True, timeout=5,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def test_rw_token_authenticates(self):
        secret = self._read_credential("/etc/freq/credentials/pve-token-rw")
        if not secret:
            self.skipTest("No RW token file")
        import tomllib
        with open(os.path.join(REPO_ROOT, "conf", "freq.toml"), "rb") as f:
            data = tomllib.load(f)
        token_id = data.get("pve", {}).get("token_id") or (
            data.get("ssh", {}).get("service_account", "freq-admin") + "@pam!freq-rw"
        )
        for ip in self.PVE_IPS:
            r = subprocess.run(
                ["curl", "-sk", "--max-time", "5", "-w", "%{http_code}",
                 "-o", "/dev/null",
                 "-H", f"Authorization: PVEAPIToken={token_id}={secret}",
                 f"https://{ip}:8006/api2/json/version"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(r.stdout.strip(), "200",
                             f"RW token failed on {ip}: HTTP {r.stdout.strip()}")
