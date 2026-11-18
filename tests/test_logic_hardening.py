"""Logic hardening tests — Phase 3 of v2.1 upgrade.

Tests for config type coercion, FleetBoundaries fixes, and policy validation.
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Config type coercion ────────────────────────────────────────────────

class TestConfigSafeInt(unittest.TestCase):
    """_safe_int must coerce gracefully."""

    def test_valid_int(self):
        from freq.core.config import _safe_int
        assert _safe_int(42, 10) == 42

    def test_string_int(self):
        from freq.core.config import _safe_int
        assert _safe_int("42", 10) == 42

    def test_bad_string_uses_default(self):
        from freq.core.config import _safe_int
        assert _safe_int("not_a_number", 10) == 10

    def test_none_uses_default(self):
        from freq.core.config import _safe_int
        assert _safe_int(None, 5) == 5

    def test_float_truncates(self):
        from freq.core.config import _safe_int
        assert _safe_int(3.7, 10) == 3

    def test_empty_string_uses_default(self):
        from freq.core.config import _safe_int
        assert _safe_int("", 10) == 10

    def test_list_uses_default(self):
        from freq.core.config import _safe_int
        assert _safe_int([1, 2], 10) == 10


class TestConfigApplyTomlCoercion(unittest.TestCase):
    """_apply_toml must handle bad types without crashing."""

    def test_bad_int_in_ssh_uses_default(self):
        from freq.core.config import FreqConfig, _apply_toml
        cfg = FreqConfig()
        original = cfg.ssh_connect_timeout
        _apply_toml(cfg, {"ssh": {"connect_timeout": "banana"}})
        assert cfg.ssh_connect_timeout == original

    def test_bad_int_in_vm_uses_default(self):
        from freq.core.config import FreqConfig, _apply_toml
        cfg = FreqConfig()
        original = cfg.vm_default_cores
        _apply_toml(cfg, {"vm": {"defaults": {"cores": "many"}}})
        assert cfg.vm_default_cores == original

    def test_valid_string_int_coerces(self):
        from freq.core.config import FreqConfig, _apply_toml
        cfg = FreqConfig()
        _apply_toml(cfg, {"ssh": {"connect_timeout": "15"}})
        assert cfg.ssh_connect_timeout == 15


# ── PolicyExecutor validation ───────────────────────────────────────────

class TestPolicyExecutorValidation(unittest.TestCase):
    """PolicyExecutor must validate required keys."""

    def test_missing_name_raises(self):
        from freq.engine.policy import PolicyExecutor
        with self.assertRaisesRegex(ValueError, "missing required 'name'"):
            PolicyExecutor({})

    def test_valid_policy_creates(self):
        from freq.engine.policy import PolicyExecutor
        p = PolicyExecutor({"name": "test", "scope": ["pve"]})
        assert p.name == "test"
        assert p.scope == ["pve"]

    def test_missing_scope_defaults_empty(self):
        from freq.engine.policy import PolicyExecutor
        p = PolicyExecutor({"name": "test"})
        assert p.scope == []


# ── freq why command ────────────────────────────────────────────────────

class TestWhyCommand(unittest.TestCase):
    """freq why <vmid> must display category, tier, and permissions."""

    def test_known_vmid_returns_ok(self):
        from freq.modules.why import cmd_why
        from freq.core.types import FleetBoundaries
        cfg = MagicMock()
        cfg.fleet_boundaries = FleetBoundaries(
            tiers={"admin": ["view", "start", "stop", "destroy"]},
            categories={"lab": {
                "vmids": [5001], "tier": "admin", "description": "Lab VMs",
            }},
        )
        args = SimpleNamespace(target="5001")
        result = cmd_why(cfg, None, args)
        assert result == 0

    def test_unknown_vmid_returns_ok(self):
        from freq.modules.why import cmd_why
        from freq.core.types import FleetBoundaries
        cfg = MagicMock()
        cfg.fleet_boundaries = FleetBoundaries()
        args = SimpleNamespace(target="9999")
        result = cmd_why(cfg, None, args)
        assert result == 0

    def test_no_target_returns_1(self):
        from freq.modules.why import cmd_why
        cfg = MagicMock()
        args = SimpleNamespace(target=None)
        result = cmd_why(cfg, None, args)
        assert result == 1

    def test_invalid_vmid_returns_1(self):
        from freq.modules.why import cmd_why
        cfg = MagicMock()
        args = SimpleNamespace(target="abc")
        result = cmd_why(cfg, None, args)
        assert result == 1

    def test_protected_vmid(self):
        from freq.modules.why import cmd_why
        from freq.core.types import FleetBoundaries
        cfg = MagicMock()
        cfg.fleet_boundaries = FleetBoundaries(
            tiers={"probe": ["view"]},
            categories={"personal": {
                "vmids": [802], "tier": "probe", "description": "Personal",
            }},
        )
        args = SimpleNamespace(target="802")
        result = cmd_why(cfg, None, args)
        assert result == 0


# ── freq test-connection command ────────────────────────────────────────

class TestTestConnection(unittest.TestCase):
    """freq test-connection must test TCP, SSH, and sudo in sequence."""

    def test_no_target_returns_1(self):
        from freq.modules.fleet import cmd_test_connection
        cfg = MagicMock()
        cfg.hosts = []
        args = SimpleNamespace(target=None)
        result = cmd_test_connection(cfg, None, args)
        assert result == 1

    @patch("freq.modules.fleet.socket.socket")
    def test_unreachable_returns_1(self, mock_socket_cls):
        from freq.modules.fleet import cmd_test_connection
        cfg = MagicMock()
        cfg.hosts = []
        mock_conn = MagicMock()
        mock_conn.connect.side_effect = OSError("Connection refused")
        mock_socket_cls.return_value = mock_conn
        args = SimpleNamespace(target="10.0.0.1")
        result = cmd_test_connection(cfg, None, args)
        assert result == 1
