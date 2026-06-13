"""Core watchdog contract tests.

The watchdog is allowed to audit local FREQ truth surfaces. It is not allowed
to become another fleet probe loop or privileged repair daemon.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from freq.core.config import FreqConfig, _safe_bool
from freq.modules import watchdog


REPO_ROOT = Path(__file__).parent.parent


class TestWatchdogNoFleetProbeContract(unittest.TestCase):
    def test_watchdog_module_has_no_ssh_imports(self):
        src = (REPO_ROOT / "freq" / "modules" / "watchdog.py").read_text()
        self.assertNotIn("freq.core.ssh", src)
        self.assertNotIn("ssh_run", src)
        self.assertNotIn("run_many", src)
        self.assertNotIn("paramiko", src)

    def test_old_observe_watch_fleet_loop_removed(self):
        src = (REPO_ROOT / "freq" / "modules" / "infrastructure.py").read_text()
        body = src.split("def cmd_watch", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("cmd_status", body)
        self.assertNotIn("while True", body)

    def test_watchdog_cli_skips_generic_log_bootstrap(self):
        src = (REPO_ROOT / "freq" / "cli.py").read_text()
        self.assertIn("watchdog_command", src)
        self.assertIn('getattr(args, "domain", "") == "watchdog"', src)
        self.assertIn('getattr(args, "subcmd", "") == "watch"', src)
        self.assertIn("not watchdog_command", src)


class TestWatchdogSystemdSafety(unittest.TestCase):
    def test_init_unit_uses_least_privilege_identity_and_limits(self):
        src = (REPO_ROOT / "freq" / "modules" / "init_cmd.py").read_text()
        self.assertIn('watch_user = "freq-watch"', src)
        self.assertIn("User={watch_user}", src)
        self.assertIn("NoNewPrivileges=true", src)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", src)
        self.assertIn("MemoryMax=96M", src)
        self.assertIn("CPUQuota=5%", src)
        self.assertIn("ReadWritePaths={watch_dir}", src)
        self.assertIn("IPAddressDeny=any", src)
        self.assertIn("IPAddressAllow=localhost", src)

    def test_installer_installs_watchdog_unit(self):
        src = (REPO_ROOT / "install.sh").read_text()
        self.assertIn("freq-watchdog.service", src)
        self.assertIn("User=freq-watch", src)
        self.assertIn("NoNewPrivileges=true", src)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", src)
        self.assertIn("MemoryMax=96M", src)
        self.assertIn("CPUQuota=5%", src)
        self.assertIn("IPAddressDeny=any", src)
        self.assertIn("IPAddressAllow=localhost", src)

    def test_listener_is_localhost_only(self):
        src = (REPO_ROOT / "freq" / "modules" / "watchdog.py").read_text()
        self.assertIn('ThreadingHTTPServer(("127.0.0.1", port)', src)
        self.assertNotIn('ThreadingHTTPServer(("0.0.0.0"', src)


class TestWatchdogEvaluation(unittest.TestCase):
    def _cfg(self, root):
        cfg = FreqConfig()
        cfg.conf_dir = os.path.join(root, "conf")
        cfg.data_dir = os.path.join(root, "data")
        cfg.dashboard_port = 65530
        os.makedirs(cfg.conf_dir, exist_ok=True)
        os.makedirs(os.path.join(cfg.data_dir, "cache"), exist_ok=True)
        Path(cfg.conf_dir, ".initialized").write_text("initialized\n")
        return cfg

    def _write_cache(self, cfg, name, data, ts=9999999999):
        path = Path(cfg.data_dir, "cache", f"{name}.json")
        path.write_text(json.dumps({"data": data, "ts": ts}))

    @patch("freq.modules.watchdog._check_freq_serve_systemd")
    @patch("freq.modules.watchdog._check_dashboard_port")
    def test_evaluate_is_local_and_clean(self, port_check, systemd_check):
        with tempfile.TemporaryDirectory() as root:
            cfg = self._cfg(root)
            self._write_cache(cfg, "health", {"hosts": [{"label": "h1", "state": "live", "status": "healthy"}]})
            self._write_cache(cfg, "infra_quick", {"devices": [], "core_devices": []})
            Path(cfg.data_dir, "cache", "alert_history.json").write_text("[]")
            Path(cfg.data_dir, "cache", "rule_state.json").write_text("{}")
            systemd_check.return_value = watchdog.Check("freq_serve_systemd", "pass", "active")
            port_check.return_value = watchdog.Check("dashboard_port", "pass", "listening")

            status = watchdog.evaluate(cfg, state={"checks": {}})

        self.assertEqual(status["status"], "healthy")
        self.assertEqual(status["hosts"], 1)
        self.assertEqual(status["errors"], 0)

    @patch("freq.modules.watchdog._check_freq_serve_systemd")
    @patch("freq.modules.watchdog._check_dashboard_port")
    def test_null_physical_metrics_do_not_degrade_alert_contract(self, port_check, systemd_check):
        with tempfile.TemporaryDirectory() as root:
            cfg = self._cfg(root)
            self._write_cache(
                cfg,
                "health",
                {
                    "hosts": [
                        {
                            "label": "bmc-10",
                            "type": "idrac",
                            "state": "live",
                            "status": "healthy",
                            "ram": None,
                            "disk": None,
                            "load": "-",
                        }
                    ]
                },
            )
            self._write_cache(cfg, "infra_quick", {"devices": [], "core_devices": []})
            Path(cfg.data_dir, "cache", "alert_history.json").write_text("[]")
            Path(cfg.data_dir, "cache", "rule_state.json").write_text("{}")
            systemd_check.return_value = watchdog.Check("freq_serve_systemd", "pass", "active")
            port_check.return_value = watchdog.Check("dashboard_port", "pass", "listening")

            status = watchdog.evaluate(cfg, state={"checks": {}})

        self.assertEqual(status["status"], "healthy")
        self.assertEqual(status["errors"], 0)
        self.assertFalse(status["warnings"])

    @patch("freq.modules.watchdog._check_freq_serve_systemd")
    @patch("freq.modules.watchdog._check_dashboard_port")
    def test_transient_failures_are_pending_first(self, port_check, systemd_check):
        with tempfile.TemporaryDirectory() as root:
            cfg = self._cfg(root)
            self._write_cache(cfg, "health", {"hosts": [{"label": "h1", "state": "auth_failed", "status": "auth_failed"}]})
            self._write_cache(cfg, "infra_quick", {"devices": [], "core_devices": []})
            Path(cfg.data_dir, "cache", "alert_history.json").write_text("[]")
            Path(cfg.data_dir, "cache", "rule_state.json").write_text("{}")
            systemd_check.return_value = watchdog.Check("freq_serve_systemd", "pass", "active")
            port_check.return_value = watchdog.Check("dashboard_port", "pass", "listening")
            state = {"checks": {}}

            first = watchdog.evaluate(cfg, state=state)
            second = watchdog.evaluate(cfg, state=state)

        self.assertEqual(first["status"], "pending")
        self.assertTrue(first["pending"])
        self.assertEqual(second["status"], "failing")
        self.assertTrue(second["failures"])

    @patch("freq.modules.watchdog._check_freq_serve_systemd")
    @patch("freq.modules.watchdog._check_dashboard_port")
    def test_stale_current_cache_never_reports_healthy(self, port_check, systemd_check):
        with tempfile.TemporaryDirectory() as root:
            cfg = self._cfg(root)
            self._write_cache(cfg, "health", {"hosts": []}, ts=1)
            self._write_cache(cfg, "infra_quick", {"devices": [], "core_devices": []}, ts=1)
            Path(cfg.data_dir, "cache", "alert_history.json").write_text("[]")
            Path(cfg.data_dir, "cache", "rule_state.json").write_text("{}")
            systemd_check.return_value = watchdog.Check("freq_serve_systemd", "pass", "active")
            port_check.return_value = watchdog.Check("dashboard_port", "pass", "listening")
            state = {"checks": {}}

            first = watchdog.evaluate(cfg, state=state, max_age=60)
            second = watchdog.evaluate(cfg, state=state, max_age=60)

        self.assertEqual(first["status"], "pending")
        self.assertNotEqual(first["status"], "healthy")
        self.assertEqual(second["status"], "failing")
        self.assertTrue(any("stale" in msg for msg in second["failures"]))

    def test_state_retention_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "state.json")
            state = {"checks": {f"check-{i}": {"consecutive": i} for i in range(watchdog.MAX_STATE_CHECKS + 10)}}
            watchdog._save_state(state, path)
            saved = json.loads(Path(path).read_text())
        self.assertLessEqual(len(saved["checks"]), watchdog.MAX_STATE_CHECKS)

    def test_status_file_is_operator_readable(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "status.json")
            watchdog._atomic_write_json(path, {"ok": True}, mode=0o644)
            mode = os.stat(path).st_mode & 0o777
        self.assertEqual(mode, 0o644)

    def test_stale_status_file_cannot_read_healthy(self):
        stale = {
            "ok": True,
            "status": "healthy",
            "checked_at": 1,
            "errors": 0,
            "failures": [],
            "watchdog_installed": True,
        }
        rendered = watchdog._freshen_status_for_read(stale, max_age=60)
        self.assertFalse(rendered["ok"])
        self.assertEqual(rendered["status"], "stale")
        self.assertGreaterEqual(rendered["errors"], 1)
        self.assertTrue(any("watchdog status stale" in msg for msg in rendered["failures"]))


class TestConfigBoolParsing(unittest.TestCase):
    def test_safe_bool_does_not_treat_false_string_as_true(self):
        self.assertFalse(_safe_bool("false", True))
        self.assertFalse(_safe_bool("off", True))
        self.assertTrue(_safe_bool("true", False))
        self.assertTrue(_safe_bool("yes", False))


if __name__ == "__main__":
    unittest.main()
