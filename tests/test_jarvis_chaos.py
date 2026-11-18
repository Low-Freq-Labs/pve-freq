"""Tests for freq.jarvis.chaos — chaos engineering."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.case_matrix import run_case_matrix

from freq.jarvis.chaos import (
    Experiment, ExperimentResult,
    validate_experiment, build_commands, check_safety,
    run_experiment, load_experiment_log, result_to_dict,
    list_experiment_types, _chaos_dir, _log_experiment,
    EXPERIMENTS, MAX_DURATION,
)


class TestValidation(unittest.TestCase):
    def _case_unknown_type(self):
        exp = Experiment(name="t", experiment_type="explode", target_host="h1")
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)
        self.assertIn("Unknown", err)

    def _case_missing_target(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="")
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)
        self.assertIn("required", err.lower())

    def _case_duration_too_long(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=9999)
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)
        self.assertIn("maximum", err.lower())

    def _case_duration_too_short(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=0)
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)
        self.assertIn("at least", err.lower())

    def _case_missing_service_for_service_kill(self):
        exp = Experiment(name="t", experiment_type="service_kill", target_host="h1", target_service="")
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)
        self.assertIn("service", err.lower())

    def _case_missing_service_for_service_restart(self):
        exp = Experiment(name="t", experiment_type="service_restart", target_host="h1", target_service="")
        ok, err = validate_experiment(exp)
        self.assertFalse(ok)

    def _case_valid_cpu_stress(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=60)
        ok, err = validate_experiment(exp)
        self.assertTrue(ok)

    def _case_valid_service_kill(self):
        exp = Experiment(name="t", experiment_type="service_kill", target_host="h1", target_service="plex", duration=30)
        ok, err = validate_experiment(exp)
        self.assertTrue(ok)


class TestBuildCommands(unittest.TestCase):
    def _case_service_kill(self):
        exp = Experiment(name="t", experiment_type="service_kill", target_host="h1", target_service="plex")
        cmds = build_commands(exp)
        self.assertIn("docker stop plex", cmds["inject"])
        self.assertIn("docker start plex", cmds["rollback"])
        self.assertIn("plex", cmds["verify"])

    def _case_network_delay(self):
        exp = Experiment(name="t", experiment_type="network_delay", target_host="h1",
                         parameters={"interface": "ens18"})
        cmds = build_commands(exp)
        self.assertIn("ens18", cmds["inject"])
        self.assertIn("ens18", cmds["rollback"])

    def _case_disk_fill(self):
        exp = Experiment(name="t", experiment_type="disk_fill", target_host="h1",
                         parameters={"size_mb": 200})
        cmds = build_commands(exp)
        self.assertIn("200", cmds["inject"])

    def _case_cpu_stress_includes_duration(self):
        exp = Experiment(name="t", experiment_type="cpu_stress", target_host="h1", duration=30)
        cmds = build_commands(exp)
        self.assertIn("30", cmds["inject"])


class TestSafetyGates(unittest.TestCase):
    def _make_cfg(self, hosts=None):
        cfg = MagicMock()
        cfg.hosts = hosts or []
        cfg.fleet_boundaries = None
        return cfg

    def _case_safe_target_allowed(self):
        host = MagicMock()
        host.label = "lab-01"
        host.vmid = 5001  # Lab VMID, not in blocked range
        cfg = self._make_cfg(hosts=[host])
        safe, reason = check_safety("lab-01", cfg)
        self.assertTrue(safe)

    def _case_unknown_host_allowed(self):
        cfg = self._make_cfg()
        safe, reason = check_safety("nonexistent", cfg)
        self.assertTrue(safe)


class TestLogging(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_chaos_log_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _case_log_and_load(self):
        result = ExperimentResult(
            experiment_name="test-exp",
            experiment_type="cpu_stress",
            target_host="h1",
            status="completed",
            start_time=time.time() - 60,
            end_time=time.time(),
        )
        _log_experiment(self.tmpdir, result)
        logs = load_experiment_log(self.tmpdir)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["experiment_name"], "test-exp")
        self.assertEqual(logs[0]["status"], "completed")

    def _case_load_empty(self):
        logs = load_experiment_log(self.tmpdir)
        self.assertEqual(len(logs), 0)

    def _case_load_skips_corrupt(self):
        log_dir = _chaos_dir(self.tmpdir)
        with open(os.path.join(log_dir, "experiment_bad.json"), "w") as f:
            f.write("{{{invalid")
        logs = load_experiment_log(self.tmpdir)
        self.assertEqual(len(logs), 0)

    def _case_load_respects_count(self):
        for i in range(5):
            result = ExperimentResult(
                experiment_name=f"exp-{i}",
                experiment_type="cpu_stress",
                target_host="h1",
                status="completed",
            )
            _log_experiment(self.tmpdir, result)
            time.sleep(0.01)  # distinct timestamps
        logs = load_experiment_log(self.tmpdir, count=3)
        self.assertLessEqual(len(logs), 3)


class TestRunExperiment(unittest.TestCase):
    def _make_cfg(self):
        cfg = MagicMock()
        cfg.hosts = []
        cfg.fleet_boundaries = None
        cfg.ssh_key_path = "/tmp/test_key"
        cfg.ssh_connect_timeout = 5
        cfg.data_dir = tempfile.mkdtemp(prefix="freq_chaos_run_test_")
        return cfg

    def _make_ssh_result(self, stdout="", stderr="", returncode=0):
        r = MagicMock()
        r.stdout = stdout
        r.stderr = stderr
        r.returncode = returncode
        return r

    @patch("freq.core.resolve.by_target")
    @patch("freq.jarvis.chaos.time.sleep")
    def _case_run_inject_fail(self, mock_sleep, mock_by_target):
        host = MagicMock()
        host.ip = "10.0.0.1"
        host.htype = "linux"
        mock_by_target.return_value = host

        ssh = MagicMock(return_value=self._make_ssh_result(returncode=1, stderr="permission denied"))
        exp = Experiment(name="test", experiment_type="cpu_stress", target_host="h1", duration=1)
        cfg = self._make_cfg()
        result = run_experiment(exp, ssh, cfg)
        self.assertEqual(result.status, "failed")
        shutil.rmtree(cfg.data_dir, True)

    @patch("freq.core.resolve.by_target")
    def _case_run_host_not_found(self, mock_by_target):
        mock_by_target.return_value = None
        ssh = MagicMock()
        exp = Experiment(name="test", experiment_type="cpu_stress", target_host="missing", duration=1)
        cfg = self._make_cfg()
        result = run_experiment(exp, ssh, cfg)
        self.assertEqual(result.status, "failed")
        self.assertIn("not found", result.error)
        shutil.rmtree(cfg.data_dir, True)

    def _case_run_validation_fail(self):
        ssh = MagicMock()
        exp = Experiment(name="test", experiment_type="fake_type", target_host="h1")
        cfg = self._make_cfg()
        result = run_experiment(exp, ssh, cfg)
        self.assertEqual(result.status, "failed")
        self.assertIn("Unknown", result.error)
        shutil.rmtree(cfg.data_dir, True)


class TestSerialization(unittest.TestCase):
    def _case_result_to_dict(self):
        result = ExperimentResult(
            experiment_name="test", experiment_type="cpu_stress", target_host="h1",
            status="completed", start_time=1000.0, end_time=1060.0,
            inject_output="started", recovery_time=5.0,
        )
        d = result_to_dict(result)
        self.assertEqual(d["experiment_name"], "test")
        self.assertEqual(d["status"], "completed")
        self.assertEqual(d["duration"], 60.0)
        self.assertEqual(d["recovery_time"], 5.0)

    def _case_result_to_dict_truncates(self):
        result = ExperimentResult(
            experiment_name="test", experiment_type="cpu_stress", target_host="h1",
            inject_output="x" * 500, error="e" * 500,
        )
        d = result_to_dict(result)
        self.assertLessEqual(len(d["inject_output"]), 200)
        self.assertLessEqual(len(d["error"]), 200)

    def _case_list_experiment_types(self):
        types = list_experiment_types()
        self.assertEqual(len(types), len(EXPERIMENTS))
        type_names = [t["type"] for t in types]
        self.assertIn("service_kill", type_names)
        self.assertIn("cpu_stress", type_names)
        self.assertIn("network_delay", type_names)
        for t in types:
            self.assertIn("description", t)


CHAOS_VALIDATION_CASES = (
    "_case_unknown_type", "_case_missing_target", "_case_duration_too_long",
    "_case_duration_too_short", "_case_missing_service_for_service_kill",
    "_case_missing_service_for_service_restart", "_case_valid_cpu_stress",
    "_case_valid_service_kill",
)
CHAOS_BUILD_COMMAND_CASES = (
    "_case_service_kill", "_case_network_delay", "_case_disk_fill",
    "_case_cpu_stress_includes_duration",
)
CHAOS_SAFETY_CASES = ("_case_safe_target_allowed", "_case_unknown_host_allowed")
CHAOS_LOGGING_CASES = (
    "_case_log_and_load", "_case_load_empty", "_case_load_skips_corrupt",
    "_case_load_respects_count",
)
CHAOS_RUN_CASES = (
    "_case_run_inject_fail", "_case_run_host_not_found",
    "_case_run_validation_fail",
)
CHAOS_SERIALIZATION_CASES = (
    "_case_result_to_dict", "_case_result_to_dict_truncates",
    "_case_list_experiment_types",
)


class TestChaosValidationMatrix(unittest.TestCase):
    def test_chaos_validation_matrix(self):
        run_case_matrix(self, TestValidation, CHAOS_VALIDATION_CASES)


class TestChaosBuildCommandsMatrix(unittest.TestCase):
    def test_chaos_build_commands_matrix(self):
        run_case_matrix(self, TestBuildCommands, CHAOS_BUILD_COMMAND_CASES)


class TestChaosSafetyGatesMatrix(unittest.TestCase):
    def test_chaos_safety_gates_matrix(self):
        run_case_matrix(self, TestSafetyGates, CHAOS_SAFETY_CASES)


class TestChaosLoggingMatrix(unittest.TestCase):
    def test_chaos_logging_matrix(self):
        run_case_matrix(self, TestLogging, CHAOS_LOGGING_CASES)


class TestChaosRunExperimentMatrix(unittest.TestCase):
    def test_chaos_run_experiment_matrix(self):
        run_case_matrix(self, TestRunExperiment, CHAOS_RUN_CASES)


class TestChaosSerializationMatrix(unittest.TestCase):
    def test_chaos_serialization_matrix(self):
        run_case_matrix(self, TestSerialization, CHAOS_SERIALIZATION_CASES)


if __name__ == "__main__":
    unittest.main()
