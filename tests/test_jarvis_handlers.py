"""Tests for Jarvis route handlers in serve.py.

Tests the HTTP handler methods for rules, capacity, chaos, federation,
cost, gitops, and playbook routes using the MockFreqHandler pattern.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from freq.modules.serve import FreqHandler, _bg_cache, _bg_lock


# ── Mock handler factory (same pattern as test_serve_handlers.py) ────

class MockWfile(io.BytesIO):
    pass


def _make_handler(path="/api/info"):
    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.wfile = MockWfile()
    h.rfile = io.BytesIO()
    h.requestline = f"GET {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = {}
    h._headers_buffer = []
    h.responses = {200: ("OK", ""), 404: ("Not Found", ""), 500: ("Error", ""), 503: ("Unavailable", "")}
    h._status_code = None
    h._resp_headers = []

    def mock_send(code, msg=None):
        h._status_code = code

    h.send_response = mock_send
    h.send_header = lambda k, v: h._resp_headers.append((k, v))
    h.end_headers = lambda: None
    return h


def _get_json(handler):
    handler.wfile.seek(0)
    body = handler.wfile.read()
    if not body:
        return None
    return json.loads(body.decode())


def _mock_cfg(**overrides):
    from freq.core.types import FleetBoundaries
    fb = FleetBoundaries(
        tiers={
            "probe": {"actions": ["view"]},
            "operator": {"actions": ["view", "start", "stop"]},
            "admin": {"actions": ["view", "start", "stop", "destroy"]},
        },
        categories={},
    )
    defaults = dict(
        hosts=[],
        pve_nodes=["192.168.10.1"],
        ssh_key_path="/tmp/fake_key",
        ssh_connect_timeout=5,
        brand="FREQ",
        build="dev",
        cluster_name="testcluster",
        install_dir="/opt/freq",
        vault_file="/tmp/fake_vault",
        conf_dir=tempfile.mkdtemp(prefix="freq_handler_conf_"),
        data_dir=tempfile.mkdtemp(prefix="freq_handler_data_"),
        dashboard_port=8888,
        fleet_boundaries=fb,
        infrastructure={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# Rules Handler Tests
# ═══════════════════════════════════════════════════════════════════════

class TestRulesHandlers:
    def setup_method(self):
        self.cfg = _mock_cfg()
        self.addCleanup = []

    def teardown_method(self):
        shutil.rmtree(self.cfg.conf_dir, True)
        shutil.rmtree(self.cfg.data_dir, True)

    @patch("freq.modules.serve.load_config")
    @patch("freq.modules.serve.CACHE_DIR", "/tmp/freq_test_cache_rules")
    def test_rules_list(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        os.makedirs("/tmp/freq_test_cache_rules", exist_ok=True)
        h = _make_handler("/api/rules")
        h._serve_rules()
        data = _get_json(h)
        assert "rules" in data
        assert data["count"] == 3  # defaults

    @patch("freq.modules.serve.load_config")
    def test_rules_create_happy(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/rules/create?name=test-rule&condition=cpu_above&threshold=80&severity=critical")
        h._serve_rules_create()
        data = _get_json(h)
        assert data["ok"] is True
        assert data["name"] == "test-rule"

    @patch("freq.modules.serve.load_config")
    def test_rules_create_invalid_condition(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/rules/create?name=bad&condition=explode")
        h._serve_rules_create()
        data = _get_json(h)
        assert "error" in data
        assert "Invalid" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_rules_create_missing_fields(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/rules/create?name=test")
        h._serve_rules_create()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_rules_create_duplicate(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h1 = _make_handler("/api/rules/create?name=dup&condition=cpu_above")
        h1._serve_rules_create()
        h2 = _make_handler("/api/rules/create?name=dup&condition=cpu_above")
        h2._serve_rules_create()
        data = _get_json(h2)
        assert "error" in data
        assert "already exists" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_rules_update_happy(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        # Create first
        h1 = _make_handler("/api/rules/create?name=upd&condition=cpu_above")
        h1._serve_rules_create()
        # Update
        h2 = _make_handler("/api/rules/update?name=upd&enabled=false&threshold=95")
        h2._serve_rules_update()
        data = _get_json(h2)
        assert data["ok"] is True

    @patch("freq.modules.serve.load_config")
    def test_rules_update_not_found(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/rules/update?name=nonexistent")
        h._serve_rules_update()
        data = _get_json(h)
        assert "error" in data
        assert "not found" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_rules_delete_happy(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h1 = _make_handler("/api/rules/create?name=del-me&condition=cpu_above")
        h1._serve_rules_create()
        h2 = _make_handler("/api/rules/delete?name=del-me")
        h2._serve_rules_delete()
        data = _get_json(h2)
        assert data["ok"] is True

    @patch("freq.modules.serve.load_config")
    def test_rules_delete_not_found(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/rules/delete?name=ghost")
        h._serve_rules_delete()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.CACHE_DIR", "/tmp/freq_test_cache_hist")
    def test_rules_history(self):
        os.makedirs("/tmp/freq_test_cache_hist", exist_ok=True)
        h = _make_handler("/api/rules/history")
        h._serve_rules_history()
        data = _get_json(h)
        assert "alerts" in data
        assert "count" in data


# ═══════════════════════════════════════════════════════════════════════
# Capacity Handler Tests
# ═══════════════════════════════════════════════════════════════════════

class TestCapacityHandlers:
    def setup_method(self):
        self.cfg = _mock_cfg()

    def teardown_method(self):
        shutil.rmtree(self.cfg.conf_dir, True)
        shutil.rmtree(self.cfg.data_dir, True)

    @patch("freq.modules.serve.load_config")
    def test_capacity_no_data(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/capacity")
        h._serve_capacity()
        data = _get_json(h)
        assert data["snapshot_count"] == 0
        assert data["hosts"] == 0

    @patch("freq.modules.serve.load_config")
    def test_capacity_with_snapshots(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        from freq.jarvis.capacity import save_snapshot
        save_snapshot(self.cfg.data_dir, {"hosts": [
            {"label": "h1", "ram": "4096/8192MB", "disk": "50%", "load": "2.0", "status": "ok"},
        ]})
        h = _make_handler("/api/capacity")
        h._serve_capacity()
        data = _get_json(h)
        assert data["snapshot_count"] >= 1

    @patch("freq.modules.serve._bg_cache", {"health": None, "infra_quick": None, "update": None})
    @patch("freq.modules.serve.load_config")
    def test_capacity_snapshot_no_health(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/capacity/snapshot")
        h._serve_capacity_snapshot()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve._bg_cache", {"health": {"hosts": [{"label": "h1", "status": "ok"}]}, "infra_quick": None, "update": None})
    @patch("freq.modules.serve.load_config")
    def test_capacity_snapshot_happy(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/capacity/snapshot")
        h._serve_capacity_snapshot()
        data = _get_json(h)
        assert data["ok"] is True
        assert "snapshot" in data


# ═══════════════════════════════════════════════════════════════════════
# Chaos Handler Tests
# ═══════════════════════════════════════════════════════════════════════

class TestChaosHandlers:
    def setup_method(self):
        self.cfg = _mock_cfg()

    def teardown_method(self):
        shutil.rmtree(self.cfg.conf_dir, True)
        shutil.rmtree(self.cfg.data_dir, True)

    def test_chaos_types(self):
        h = _make_handler("/api/chaos/types")
        h._serve_chaos_types()
        data = _get_json(h)
        assert "types" in data
        assert len(data["types"]) >= 4

    @patch("freq.modules.serve.load_config")
    def test_chaos_run_missing_params(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/chaos/run?name=test")
        h._serve_chaos_run()
        data = _get_json(h)
        assert "error" in data
        assert "Missing" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_chaos_run_bad_duration(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/chaos/run?name=test&type=cpu_stress&target=h1&duration=abc")
        h._serve_chaos_run()
        data = _get_json(h)
        assert "error" in data
        assert "integer" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_chaos_log(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/chaos/log")
        h._serve_chaos_log()
        data = _get_json(h)
        assert "experiments" in data

    @patch("freq.modules.serve.load_config")
    def test_chaos_log_bad_count(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/chaos/log?count=abc")
        h._serve_chaos_log()
        data = _get_json(h)
        assert "experiments" in data  # falls back to 20


# ═══════════════════════════════════════════════════════════════════════
# Federation Handler Tests
# ═══════════════════════════════════════════════════════════════════════

class TestFederationHandlers:
    def setup_method(self):
        self.cfg = _mock_cfg()

    def teardown_method(self):
        shutil.rmtree(self.cfg.conf_dir, True)
        shutil.rmtree(self.cfg.data_dir, True)

    @patch("freq.modules.serve.load_config")
    def test_federation_status(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/federation/status")
        h._serve_federation_status()
        data = _get_json(h)
        assert "sites" in data
        assert "summary" in data

    @patch("freq.modules.serve.load_config")
    def test_federation_register_happy(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/federation/register?name=dc02&url=https://dc02.example.com")
        h._serve_federation_register()
        data = _get_json(h)
        assert data["ok"] is True

    @patch("freq.modules.serve.load_config")
    def test_federation_register_missing(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/federation/register?name=dc02")
        h._serve_federation_register()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_federation_register_dup(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h1 = _make_handler("/api/federation/register?name=dc02&url=https://dc02.example.com")
        h1._serve_federation_register()
        h2 = _make_handler("/api/federation/register?name=dc02&url=https://other.example.com")
        h2._serve_federation_register()
        data = _get_json(h2)
        assert data.get("ok") is False or "error" in data
        msg = data.get("error", data.get("message", ""))
        assert "already" in msg

    @patch("freq.modules.serve.load_config")
    def test_federation_unregister(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h1 = _make_handler("/api/federation/register?name=dc02&url=https://dc02.example.com")
        h1._serve_federation_register()
        h2 = _make_handler("/api/federation/unregister?name=dc02")
        h2._serve_federation_unregister()
        data = _get_json(h2)
        assert data["ok"] is True

    @patch("freq.modules.serve.load_config")
    def test_federation_unregister_missing_name(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/federation/unregister")
        h._serve_federation_unregister()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_federation_toggle(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h1 = _make_handler("/api/federation/register?name=dc02&url=https://dc02.example.com")
        h1._serve_federation_register()
        h2 = _make_handler("/api/federation/toggle?name=dc02")
        h2._serve_federation_toggle()
        data = _get_json(h2)
        assert data["ok"] is True
        assert data["enabled"] is False  # toggled from True to False

    @patch("freq.modules.serve.load_config")
    def test_federation_toggle_not_found(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/federation/toggle?name=ghost")
        h._serve_federation_toggle()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    @patch("freq.jarvis.federation.urllib.request.urlopen")
    def test_federation_poll(self, mock_urlopen, mock_cfg):
        mock_cfg.return_value = self.cfg
        # Register a site first
        h1 = _make_handler("/api/federation/register?name=dc02&url=https://dc02.example.com")
        h1._serve_federation_register()
        # Mock unreachable
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("refused")
        h2 = _make_handler("/api/federation/poll")
        h2._serve_federation_poll()
        data = _get_json(h2)
        assert data["ok"] is True
        assert "sites" in data


# ═══════════════════════════════════════════════════════════════════════
# Cost Handler Tests
# ═══════════════════════════════════════════════════════════════════════

class TestCostHandlers:
    def setup_method(self):
        self.cfg = _mock_cfg()

    def teardown_method(self):
        shutil.rmtree(self.cfg.conf_dir, True)
        shutil.rmtree(self.cfg.data_dir, True)

    @patch("freq.modules.serve._bg_cache", {"health": None, "infra_quick": None, "update": None})
    @patch("freq.modules.serve.load_config")
    def test_cost_no_health_data(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/cost")
        h._serve_cost()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve._bg_cache", {
        "health": {"hosts": [
            {"label": "h1", "status": "ok", "ram": "4096/8192MB", "load": "2.0"},
        ]},
        "infra_quick": None,
        "update": None,
    })
    @patch("freq.modules.serve.load_config")
    def test_cost_happy(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/cost")
        h._serve_cost()
        data = _get_json(h)
        assert "hosts" in data
        assert "summary" in data
        assert len(data["hosts"]) == 1

    @patch("freq.modules.serve.load_config")
    def test_cost_config(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/cost/config")
        h._serve_cost_config()
        data = _get_json(h)
        assert "rate_per_kwh" in data
        assert "currency" in data
        assert "pue" in data


# ═══════════════════════════════════════════════════════════════════════
# GitOps Handler Tests
# ═══════════════════════════════════════════════════════════════════════

class TestGitOpsHandlers:
    def setup_method(self):
        self.cfg = _mock_cfg()

    def teardown_method(self):
        shutil.rmtree(self.cfg.conf_dir, True)
        shutil.rmtree(self.cfg.data_dir, True)

    @patch("freq.modules.serve.load_config")
    def test_gitops_status(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/status")
        h._serve_gitops_status()
        data = _get_json(h)
        assert "enabled" in data
        assert "state" in data

    @patch("freq.modules.serve.load_config")
    def test_gitops_sync_unconfigured(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/sync")
        h._serve_gitops_sync()
        data = _get_json(h)
        assert "error" in data
        assert "not configured" in data["error"].lower()

    @patch("freq.jarvis.gitops._run_git")
    @patch("freq.modules.serve.load_config")
    def test_gitops_sync_happy(self, mock_cfg, mock_git):
        # Write gitops config
        toml = b'[gitops]\nrepo_url = "git@github.com:org/cfg.git"\nbranch = "main"\n'
        with open(os.path.join(self.cfg.conf_dir, "freq.toml"), "wb") as f:
            f.write(toml)
        # Create .git dir
        go_dir = os.path.join(self.cfg.data_dir, "gitops")
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)

        def side_effect(cwd, *args, **kwargs):
            r = MagicMock()
            r.returncode = 0
            cmd = args[0] if args else ""
            if cmd == "rev-list":
                r.stdout = "0\n"
            elif cmd == "log":
                r.stdout = "abc123456789|commit msg\n"
            else:
                r.stdout = ""
            return r

        mock_git.side_effect = side_effect
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/sync")
        h._serve_gitops_sync()
        data = _get_json(h)
        assert data["ok"] is True

    @patch("freq.modules.serve.load_config")
    def test_gitops_apply_unconfigured(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/apply")
        h._serve_gitops_apply()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_gitops_diff(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/diff")
        h._serve_gitops_diff()
        data = _get_json(h)
        assert "diff" in data

    @patch("freq.modules.serve.load_config")
    def test_gitops_log(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/log")
        h._serve_gitops_log()
        data = _get_json(h)
        assert "commits" in data

    @patch("freq.modules.serve.load_config")
    def test_gitops_log_bad_count(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/log?count=abc")
        h._serve_gitops_log()
        data = _get_json(h)
        assert "commits" in data

    @patch("freq.modules.serve.load_config")
    def test_gitops_rollback_missing_commit(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/rollback")
        h._serve_gitops_rollback()
        data = _get_json(h)
        assert "error" in data
        assert "Missing" in data["error"]

    @patch("freq.jarvis.gitops._run_git")
    @patch("freq.modules.serve.load_config")
    def test_gitops_rollback_happy(self, mock_cfg, mock_git):
        mock_cfg.return_value = self.cfg
        go_dir = os.path.join(self.cfg.data_dir, "gitops")
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(returncode=0)
        h = _make_handler("/api/gitops/rollback?commit=abc1234def56")
        h._serve_gitops_rollback()
        data = _get_json(h)
        assert data["ok"] is True

    @patch("freq.modules.serve.load_config")
    def test_gitops_rollback_invalid_hash(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        go_dir = os.path.join(self.cfg.data_dir, "gitops")
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        h = _make_handler("/api/gitops/rollback?commit=not-valid!")
        h._serve_gitops_rollback()
        data = _get_json(h)
        assert "error" in data or data.get("ok") is False

    @patch("freq.modules.serve.load_config")
    def test_gitops_init_no_repo_url(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/init")
        h._serve_gitops_init()
        data = _get_json(h)
        assert "error" in data
        assert "repo_url" in data["error"]

    @patch("freq.jarvis.gitops._run_git")
    @patch("freq.modules.serve.load_config")
    def test_gitops_init_happy(self, mock_cfg, mock_git):
        toml = b'[gitops]\nrepo_url = "git@github.com:org/cfg.git"\n'
        with open(os.path.join(self.cfg.conf_dir, "freq.toml"), "wb") as f:
            f.write(toml)
        mock_git.return_value = MagicMock(returncode=0)
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/gitops/init")
        h._serve_gitops_init()
        data = _get_json(h)
        assert data["ok"] is True


# ═══════════════════════════════════════════════════════════════════════
# Playbook Handler Tests
# ═══════════════════════════════════════════════════════════════════════

class TestPlaybookHandlers:
    def setup_method(self):
        self.cfg = _mock_cfg()
        self.pb_dir = os.path.join(self.cfg.conf_dir, "playbooks")
        os.makedirs(self.pb_dir, exist_ok=True)

    def teardown_method(self):
        shutil.rmtree(self.cfg.conf_dir, True)
        shutil.rmtree(self.cfg.data_dir, True)

    def _write_playbook(self, filename="test.toml", name="Test Playbook"):
        toml = f"""[playbook]
name = "{name}"
description = "A test"
trigger = "docker_down"

[[step]]
name = "Check status"
type = "check"
command = "echo ok"
target = "h1"
expect = "ok"
""".encode()
        with open(os.path.join(self.pb_dir, filename), "wb") as f:
            f.write(toml)

    @patch("freq.modules.serve.load_config")
    def test_playbooks_list(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        self._write_playbook()
        h = _make_handler("/api/playbooks")
        h._serve_playbooks()
        data = _get_json(h)
        assert "playbooks" in data
        assert len(data["playbooks"]) == 1

    @patch("freq.modules.serve.load_config")
    def test_playbooks_list_empty(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks")
        h._serve_playbooks()
        data = _get_json(h)
        assert data["playbooks"] == []

    @patch("freq.modules.serve.load_config")
    def test_playbooks_run_missing_filename(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks/run")
        h._serve_playbooks_run()
        data = _get_json(h)
        assert "error" in data
        assert "Invalid" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_playbooks_run_path_traversal(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks/run?filename=../../etc/passwd")
        h._serve_playbooks_run()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_playbooks_run_not_found(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks/run?filename=nonexistent.toml")
        h._serve_playbooks_run()
        data = _get_json(h)
        assert "error" in data
        assert "not found" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_playbooks_step_missing_params(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks/step?filename=test.toml")
        h._serve_playbooks_step()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_playbooks_step_bad_index(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks/step?filename=test.toml&step=abc")
        h._serve_playbooks_step()
        data = _get_json(h)
        assert "error" in data
        assert "integer" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_playbooks_step_out_of_range(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        self._write_playbook()
        h = _make_handler("/api/playbooks/step?filename=test.toml&step=99")
        h._serve_playbooks_step()
        data = _get_json(h)
        assert "error" in data
        assert "out of range" in data["error"]

    @patch("freq.modules.serve.load_config")
    def test_playbooks_create_happy(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks/create?name=New%20Playbook&description=test&trigger=docker_down")
        h._serve_playbooks_create()
        data = _get_json(h)
        assert data["ok"] is True
        assert data["filename"].endswith(".toml")

    @patch("freq.modules.serve.load_config")
    def test_playbooks_create_missing_name(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h = _make_handler("/api/playbooks/create")
        h._serve_playbooks_create()
        data = _get_json(h)
        assert "error" in data

    @patch("freq.modules.serve.load_config")
    def test_playbooks_create_duplicate(self, mock_cfg):
        mock_cfg.return_value = self.cfg
        h1 = _make_handler("/api/playbooks/create?name=dup")
        h1._serve_playbooks_create()
        h2 = _make_handler("/api/playbooks/create?name=dup")
        h2._serve_playbooks_create()
        data = _get_json(h2)
        assert "error" in data
        assert "already exists" in data["error"]
