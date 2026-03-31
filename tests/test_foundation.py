"""FREQ Foundation Tests — Phase 1 smoke tests.

Tests that the core foundation works: config loading, types, validation,
formatting, personality, CLI dispatch.
"""
import os
import sys
import unittest
from pathlib import Path

# Ensure we can import freq
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestTypes(unittest.TestCase):
    """Test core data types."""

    def test_host_creation(self):
        from freq.core.types import Host, Phase
        h = Host(ip="192.168.255.26", label="pve01", htype="pve", groups="cluster,prod")
        self.assertEqual(h.ip, "192.168.255.26")
        self.assertEqual(h.label, "pve01")
        self.assertEqual(h.htype, "pve")
        self.assertEqual(h.phase, Phase.PENDING)
        self.assertEqual(h.findings, [])

    def test_host_defaults(self):
        from freq.core.types import Host
        h = Host(ip="10.0.0.1", label="test", htype="linux")
        self.assertEqual(h.groups, "")
        self.assertEqual(h.error, "")
        self.assertEqual(h.duration, 0.0)

    def test_finding_creation(self):
        from freq.core.types import Finding, Severity
        f = Finding(resource_type="file_line", key="PermitRootLogin",
                    current="yes", desired="prohibit-password")
        self.assertEqual(f.severity, Severity.WARN)

    def test_vlan_creation(self):
        from freq.core.types import VLAN
        v = VLAN(id=10, name="DEV", subnet="192.168.10.0/24", prefix="192.168.10")
        self.assertEqual(v.id, 10)
        self.assertEqual(v.gateway, "")

    def test_phase_enum(self):
        from freq.core.types import Phase
        self.assertEqual(Phase.PENDING.name, "PENDING")
        self.assertEqual(Phase.FAILED.name, "FAILED")

    def test_severity_enum(self):
        from freq.core.types import Severity
        self.assertEqual(Severity.CRIT.value, "crit")

    def test_role_enum(self):
        from freq.core.types import Role
        self.assertEqual(Role.ADMIN.value, "admin")


class TestConfig(unittest.TestCase):
    """Test configuration loading."""

    def test_safe_defaults(self):
        """Config loads with safe defaults even without a config file."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        import freq
        self.assertEqual(cfg.version, freq.__version__)
        self.assertEqual(cfg.brand, "PVE FREQ")
        self.assertEqual(cfg.ssh_service_account, "freq-admin")
        self.assertEqual(cfg.ssh_max_parallel, 5)

    def test_load_config(self):
        """Load config from workspace."""
        from freq.core.config import load_config
        cfg = load_config()
        # Brand depends on whether freq.toml exists (personal = "LOW FREQ Labs", default = "PVE FREQ")
        self.assertIn(cfg.brand, ("PVE FREQ", "LOW FREQ Labs"))
        self.assertTrue(len(cfg.install_dir) > 0)
        self.assertTrue(os.path.isdir(cfg.install_dir))

    def test_hosts_file_path(self):
        """Hosts file path is resolved correctly."""
        from freq.core.config import load_config
        cfg = load_config()
        self.assertTrue(cfg.hosts_file.endswith("hosts.conf"))

    def test_load_hosts_empty(self):
        """Loading an empty hosts.conf returns empty list."""
        from freq.core.config import load_hosts
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write("# empty\n")
            path = f.name
        try:
            hosts = load_hosts(path)
            self.assertEqual(hosts, [])
        finally:
            os.unlink(path)

    def test_load_hosts_with_data(self):
        """Loading a hosts.conf with entries returns Host objects."""
        from freq.core.config import load_hosts
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write("# Fleet\n")
            f.write("192.168.255.26  pve01  pve  cluster,prod\n")
            f.write("192.168.255.30  vm101  linux  media\n")
            path = f.name
        try:
            hosts = load_hosts(path)
            self.assertEqual(len(hosts), 2)
            self.assertEqual(hosts[0].label, "pve01")
            self.assertEqual(hosts[0].htype, "pve")
            self.assertEqual(hosts[0].groups, "cluster,prod")
            self.assertEqual(hosts[1].label, "vm101")
        finally:
            os.unlink(path)

    def test_load_hosts_missing_file(self):
        """Loading a nonexistent hosts.conf returns empty list."""
        from freq.core.config import load_hosts
        hosts = load_hosts("/nonexistent/path/hosts.conf")
        self.assertEqual(hosts, [])

    def test_ssh_key_detection(self):
        """SSH key is detected when available."""
        from freq.core.config import load_config
        cfg = load_config()
        # SSH key may not exist in CI containers — just verify the field is a string
        self.assertIsInstance(cfg.ssh_key_path, str)


class TestValidation(unittest.TestCase):
    """Test input validation."""

    def test_valid_ip(self):
        from freq.core.validate import ip
        self.assertTrue(ip("192.168.255.26"))
        self.assertTrue(ip("192.168.1.1"))
        self.assertTrue(ip("0.0.0.0"))

    def test_invalid_ip(self):
        from freq.core.validate import ip
        self.assertFalse(ip("256.1.1.1"))
        self.assertFalse(ip("192.168.255"))
        self.assertFalse(ip("not-an-ip"))
        self.assertFalse(ip(""))

    def test_valid_hostname(self):
        from freq.core.validate import hostname
        self.assertTrue(hostname("pve01"))
        self.assertTrue(hostname("my-host"))
        self.assertTrue(hostname("host.homelab.local"))

    def test_invalid_hostname(self):
        from freq.core.validate import hostname
        self.assertFalse(hostname(""))
        self.assertFalse(hostname("-starts-with-dash"))
        self.assertFalse(hostname("a" * 254))

    def test_valid_username(self):
        from freq.core.validate import username
        self.assertTrue(username("svc-admin"))
        self.assertTrue(username("root"))
        self.assertTrue(username("_backup"))

    def test_invalid_username(self):
        from freq.core.validate import username
        self.assertFalse(username(""))
        self.assertFalse(username("1starts-with-number"))
        self.assertFalse(username("a" * 33))

    def test_valid_vmid(self):
        from freq.core.validate import vmid
        self.assertTrue(vmid(100))
        self.assertTrue(vmid(5000))
        self.assertTrue(vmid("999"))

    def test_invalid_vmid(self):
        from freq.core.validate import vmid
        self.assertFalse(vmid(99))
        self.assertFalse(vmid("not-a-number"))
        self.assertFalse(vmid(None))

    def test_protected_vmid(self):
        from freq.core.validate import is_protected_vmid
        protected = [100, 101, 102, 999]
        ranges = [[900, 999], [9000, 9999]]
        self.assertTrue(is_protected_vmid(101, protected, ranges))
        self.assertTrue(is_protected_vmid(950, protected, ranges))
        self.assertTrue(is_protected_vmid(9500, protected, ranges))
        self.assertFalse(is_protected_vmid(5000, protected, ranges))
        self.assertFalse(is_protected_vmid(200, protected, ranges))

    def test_valid_ssh_pubkey(self):
        from freq.core.validate import ssh_pubkey
        self.assertTrue(ssh_pubkey("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5 user@host"))
        self.assertTrue(ssh_pubkey("ssh-rsa AAAAB3NzaC1yc2E user@host"))

    def test_invalid_ssh_pubkey(self):
        from freq.core.validate import ssh_pubkey
        self.assertFalse(ssh_pubkey(""))
        self.assertFalse(ssh_pubkey("not-a-key"))


class TestFormatting(unittest.TestCase):
    """Test display formatting."""

    def test_strip_ansi(self):
        from freq.core.fmt import strip_ansi
        self.assertEqual(strip_ansi("\033[38;5;93mhello\033[0m"), "hello")
        self.assertEqual(strip_ansi("no ansi"), "no ansi")

    def test_visible_len(self):
        from freq.core.fmt import visible_len
        self.assertEqual(visible_len("\033[1mhello\033[0m"), 5)
        self.assertEqual(visible_len("hello"), 5)

    def test_badge(self):
        from freq.core.fmt import badge, strip_ansi
        b = badge("ok")
        self.assertIn("OK", strip_ansi(b))

    def test_symbols_unicode(self):
        from freq.core.fmt import S
        S.set_ascii(False)
        self.assertEqual(S.TICK, "\u2714")
        self.assertEqual(S.CROSS, "\u2718")

    def test_symbols_ascii(self):
        from freq.core.fmt import S
        S.set_ascii(True)
        self.assertEqual(S.TICK, "[OK]")
        self.assertEqual(S.CROSS, "[X]")
        S.set_ascii(False)  # Reset


class TestPersonality(unittest.TestCase):
    """Test personality system."""

    @classmethod
    def _get_personality_dir(cls):
        """Find personality dir — conf/ if present, else package data."""
        from freq.core.config import load_config
        cfg = load_config()
        conf_personality = os.path.join(cfg.conf_dir, "personality")
        if os.path.isdir(conf_personality) and os.path.isfile(
            os.path.join(conf_personality, "personal.toml")
        ):
            return conf_personality
        # Fall back to package data
        try:
            from freq.data import get_data_path
            pkg = str(get_data_path() / "conf-templates" / "personality")
            if os.path.isdir(pkg):
                return pkg
        except ImportError:
            pass
        return conf_personality

    def test_load_personal_pack(self):
        from freq.core.personality import load_pack
        pdir = os.path.dirname(self._get_personality_dir())
        pack = load_pack(pdir, "personal")
        self.assertEqual(pack.name, "personal")
        if pack.celebrations:  # Only assert counts when data is available
            self.assertTrue(len(pack.celebrations) > 50)
            self.assertTrue(len(pack.taglines) > 20)
            self.assertTrue(len(pack.quotes) > 10)
            self.assertEqual(pack.vibe_probability, 47)

    def test_celebrate(self):
        from freq.core.personality import load_pack, celebrate
        pdir = os.path.dirname(self._get_personality_dir())
        pack = load_pack(pdir, "personal")
        msg = celebrate(pack)
        self.assertTrue(len(msg) > 0)

    def test_premier_message(self):
        from freq.core.personality import load_pack, celebrate
        pdir = os.path.dirname(self._get_personality_dir())
        pack = load_pack(pdir, "personal")
        if pack.premier and "create" in pack.premier:
            msg = celebrate(pack, "create")
            self.assertIn("VM", msg)
        else:
            msg = celebrate(pack)
            self.assertTrue(len(msg) > 0)

    def test_missing_pack_returns_defaults(self):
        from freq.core.personality import load_pack
        pack = load_pack("/nonexistent", "missing")
        self.assertEqual(pack.name, "missing")
        self.assertEqual(pack.celebrations, [])

    def test_vibe_check_probability(self):
        """Vibe check should return None most of the time (1/47 chance)."""
        from freq.core.personality import load_pack, vibe_check
        pdir = os.path.dirname(self._get_personality_dir())
        pack = load_pack(pdir, "personal")
        if not pack.vibe_enabled:
            self.skipTest("Personal pack not available — no vibe check to test")
        # Run 100 times, should get mostly None
        results = [vibe_check(pack) for _ in range(100)]
        none_count = results.count(None)
        self.assertGreater(none_count, 80)  # At least 80% should be None


class TestCLI(unittest.TestCase):
    """Test CLI dispatch."""

    def test_version_command(self):
        from freq.cli import main
        # Should return 0
        result = main(["version"])
        self.assertEqual(result, 0)

    def test_help_command(self):
        from freq.cli import main
        result = main(["help"])
        self.assertEqual(result, 0)

    def test_doctor_command(self):
        from freq.cli import main
        result = main(["doctor"])
        self.assertEqual(result, 0)

    def test_configure_command(self):
        from freq.cli import main
        result = main(["configure"])
        self.assertEqual(result, 0)


class TestLogging(unittest.TestCase):
    """Test structured logging."""

    def test_redact_password(self):
        from freq.core.log import _redact
        msg = "password=secret123 done"
        redacted = _redact(msg)
        self.assertNotIn("secret123", redacted)
        self.assertIn("REDACTED", redacted)

    def test_redact_token(self):
        from freq.core.log import _redact
        msg = "token=abc123def done"
        redacted = _redact(msg)
        self.assertNotIn("abc123def", redacted)

    def test_log_to_file(self):
        import tempfile
        import json
        from freq.core import log as logger
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            path = f.name
        try:
            logger.init(path)
            logger.info("test message", extra_field="value")
            with open(path) as f:
                line = f.readline()
            entry = json.loads(line)
            self.assertEqual(entry["level"], "INFO")
            self.assertEqual(entry["msg"], "test message")
        finally:
            os.unlink(path)


# ═══════════════════════════════════════════════════════════════════
# Config Unification Tests
# ═══════════════════════════════════════════════════════════════════

class TestHostsToml(unittest.TestCase):
    """Tests for TOML-based hosts loading."""

    def test_load_hosts_toml_basic(self):
        """Load hosts from TOML format."""
        import tempfile
        from freq.core.config import load_hosts_toml
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[[host]]\nip = "10.0.0.1"\nlabel = "node1"\ntype = "pve"\ngroups = "prod"\n')
            f.write('[[host]]\nip = "10.0.0.2"\nlabel = "nas"\ntype = "truenas"\ngroups = "storage"\n')
            path = f.name
        try:
            hosts = load_hosts_toml(path)
            self.assertEqual(len(hosts), 2)
            self.assertEqual(hosts[0].ip, "10.0.0.1")
            self.assertEqual(hosts[0].label, "node1")
            self.assertEqual(hosts[0].htype, "pve")
            self.assertEqual(hosts[0].groups, "prod")
            self.assertEqual(hosts[1].label, "nas")
        finally:
            os.unlink(path)

    def test_load_hosts_toml_empty(self):
        """Empty TOML returns empty list."""
        import tempfile
        from freq.core.config import load_hosts_toml
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("# empty\n")
            path = f.name
        try:
            hosts = load_hosts_toml(path)
            self.assertEqual(hosts, [])
        finally:
            os.unlink(path)

    def test_load_hosts_toml_with_all_ips(self):
        """Hosts with all_ips field (list format)."""
        import tempfile
        from freq.core.config import load_hosts_toml
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[[host]]\nip = "10.0.0.1"\nlabel = "multi"\ntype = "linux"\n')
            f.write('all_ips = ["10.0.0.1", "10.0.1.1"]\n')
            path = f.name
        try:
            hosts = load_hosts_toml(path)
            self.assertEqual(len(hosts), 1)
            self.assertEqual(hosts[0].all_ips, ["10.0.0.1", "10.0.1.1"])
        finally:
            os.unlink(path)

    def test_load_hosts_toml_missing_file(self):
        """Missing TOML file returns empty list."""
        from freq.core.config import load_hosts_toml
        hosts = load_hosts_toml("/nonexistent/hosts.toml")
        self.assertEqual(hosts, [])


class TestTomlUsers(unittest.TestCase):
    """Tests for TOML-based user loading."""

    def test_toml_users_from_config(self):
        """Users defined in [users] section override users.conf."""
        from freq.core.config import FreqConfig
        from freq.modules.users import _load_users
        cfg = FreqConfig()
        cfg._toml_users = [
            {"username": "admin1", "role": "admin", "groups": ""},
            {"username": "viewer1", "role": "viewer", "groups": "lab"},
        ]
        users = _load_users(cfg)
        self.assertEqual(len(users), 2)
        self.assertEqual(users[0]["username"], "admin1")
        self.assertEqual(users[1]["role"], "viewer")

    def test_toml_users_fallback_to_conf(self):
        """When no TOML users, falls back to users.conf."""
        from freq.core.config import FreqConfig
        from freq.modules.users import _load_users
        cfg = FreqConfig()
        cfg._toml_users = []
        cfg.conf_dir = "/nonexistent"
        users = _load_users(cfg)
        self.assertEqual(users, [])


class TestPveApiConfig(unittest.TestCase):
    """Tests for PVE API configuration fields."""

    def test_pve_api_defaults(self):
        """PVE API fields have safe defaults."""
        from freq.core.config import FreqConfig
        cfg = FreqConfig()
        self.assertEqual(cfg.pve_api_token_id, "")
        self.assertEqual(cfg.pve_api_token_secret, "")
        self.assertFalse(cfg.pve_api_verify_ssl)

    def test_pve_api_call_no_token(self):
        """_pve_api_call returns failure when no token configured."""
        from freq.core.config import FreqConfig
        from freq.modules.pve import _pve_api_call
        cfg = FreqConfig()
        result, ok = _pve_api_call(cfg, "10.0.0.1", "/version")
        self.assertFalse(ok)
        self.assertEqual(result, "")

    def test_pve_call_no_token_uses_ssh(self):
        """_pve_call falls back to SSH when no token configured."""
        from unittest.mock import patch, MagicMock
        from freq.core.config import FreqConfig
        from freq.modules.pve import _pve_call
        cfg = FreqConfig()
        cfg.ssh_key_path = "/tmp/fake"
        cfg.ssh_connect_timeout = 5
        mock_result = MagicMock()
        mock_result.stdout = '{"version": "8.0"}'
        mock_result.returncode = 0
        with patch("freq.modules.pve.ssh_run", return_value=mock_result):
            result, ok = _pve_call(cfg, "10.0.0.1",
                                   api_endpoint="/version",
                                   ssh_command="pvesh get /version --output-format json")
            self.assertTrue(ok)
            self.assertIn("version", result)


if __name__ == "__main__":
    unittest.main()
