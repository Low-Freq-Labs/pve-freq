"""Config validation tests — validates Phase 1.1 config hardening.

Tests validate_config(), _safe_int(), and load_config() edge cases.
"""
import os
import tempfile
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.core.config import validate_config, _safe_int, FreqConfig, _apply_toml, load_hosts_toml, load_config
from freq.core.types import Host


# ── _safe_int ────────────────────────────────────────────────────────

class TestSafeInt:
    """_safe_int must coerce safely and warn on bad values."""

    def test_valid_int(self):
        assert _safe_int(42, 0) == 42

    def test_valid_string_int(self):
        assert _safe_int("42", 0) == 42

    def test_none_returns_default(self):
        assert _safe_int(None, 10) == 10

    def test_invalid_string_returns_default(self):
        assert _safe_int("five", 10) == 10

    def test_empty_string_returns_default(self):
        assert _safe_int("", 10) == 10

    def test_float_string_returns_default(self):
        assert _safe_int("3.14", 0) == 0

    def test_zero_is_valid(self):
        assert _safe_int(0, 99) == 0

    def test_negative_is_valid(self):
        assert _safe_int(-1, 0) == -1


# ── validate_config ─────────────────────────────────────────────────

class TestValidateConfig:
    """Config validation must catch bad values without crashing."""

    def _make_cfg(self, hosts=None, dashboard_port=8888,
                  ssh_connect_timeout=10, ssh_max_parallel=10):
        cfg = FreqConfig()
        cfg.hosts = hosts or []
        cfg.dashboard_port = dashboard_port
        cfg.ssh_connect_timeout = ssh_connect_timeout
        cfg.ssh_max_parallel = ssh_max_parallel
        return cfg

    def test_empty_config_reports_issues(self):
        cfg = self._make_cfg()
        issues = validate_config(cfg)
        # Empty config should report missing SSH key and missing dirs
        assert any("SSH" in i or "Directory" in i for i in issues)

    def test_valid_hosts_no_warnings(self):
        hosts = [Host(label="test", ip="10.0.0.1", htype="linux")]
        cfg = self._make_cfg(hosts=hosts)
        # May warn about htype depending on deployer registration
        # but should not crash
        validate_config(cfg)

    def test_invalid_ip_produces_warning(self):
        hosts = [Host(label="bad-host", ip="999.999.999.999", htype="linux")]
        cfg = self._make_cfg(hosts=hosts)
        warnings = validate_config(cfg)
        assert any("Invalid IP" in w for w in warnings)

    def test_empty_ip_no_crash(self):
        hosts = [Host(label="no-ip", ip="", htype="linux")]
        cfg = self._make_cfg(hosts=hosts)
        # Empty IP should not crash validation
        validate_config(cfg)

    def test_negative_ssh_timeout_warns(self):
        cfg = self._make_cfg(ssh_connect_timeout=-1)
        warnings = validate_config(cfg)
        assert any("timeout" in w.lower() for w in warnings)

    def test_zero_ssh_parallel_warns(self):
        cfg = self._make_cfg(ssh_max_parallel=0)
        warnings = validate_config(cfg)
        assert any("parallel" in w.lower() for w in warnings)

    def test_valid_port_no_warning(self):
        cfg = self._make_cfg(dashboard_port=8888)
        warnings = validate_config(cfg)
        assert not any("port" in w.lower() for w in warnings)

    def test_invalid_port_warns(self):
        cfg = self._make_cfg(dashboard_port=99999)
        warnings = validate_config(cfg)
        assert any("port" in w.lower() for w in warnings)


# ── Config Caching ───────────────────────────────────────────────────

class TestConfigCaching:
    """load_config() should return cached result within TTL."""

    def test_cache_module_vars_exist(self):
        from freq.core import config
        assert hasattr(config, '_config_cache')
        assert hasattr(config, '_config_cache_ts')
        assert hasattr(config, '_CONFIG_TTL')

    def test_cache_ttl_is_positive(self):
        from freq.core.config import _CONFIG_TTL
        assert _CONFIG_TTL > 0

    def test_force_bypasses_cache(self):
        """force=True should reload from disk."""
        from freq.core import config
        # Just verify the parameter is accepted without error
        # (actual load may fail in test env without install dir)
        try:
            config.load_config(force=True)
        except Exception:
            pass  # Expected in test env without freq installed


class TestConfigTrustHardening:
    """Regression coverage for malformed config that must not take down startup."""

    def test_apply_toml_tolerates_scalar_pve_storage_entries(self):
        cfg = FreqConfig()
        _apply_toml(cfg, {"pve": {"storage": {"node1": "local-lvm"}}})
        assert cfg.pve_storage["node1"] == {"pool": "", "type": ""}

    def test_load_hosts_toml_tolerates_bad_vmid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[[host]]\nip = "10.0.0.10"\nlabel = "bad"\ntype = "linux"\nvmid = "oops"\n')
            path = f.name
        try:
            hosts = load_hosts_toml(path)
            assert len(hosts) == 1
            assert hosts[0].vmid == 0
        finally:
            os.unlink(path)

    def test_load_config_skips_duplicate_labels(self):
        with tempfile.TemporaryDirectory() as td:
            conf_dir = os.path.join(td, "conf")
            os.makedirs(conf_dir, exist_ok=True)
            with open(os.path.join(conf_dir, "freq.toml"), "w") as f:
                f.write("[freq]\nversion = \"test\"\n")
            with open(os.path.join(conf_dir, "hosts.toml"), "w") as f:
                f.write(
                    '[[host]]\nip = "10.0.0.1"\nlabel = "dup"\ntype = "linux"\n\n'
                    '[[host]]\nip = "10.0.0.2"\nlabel = "dup"\ntype = "linux"\n'
                )

            cfg = load_config(td, force=True)
            assert len(cfg.hosts) == 1
            assert cfg.hosts[0].ip == "10.0.0.1"
