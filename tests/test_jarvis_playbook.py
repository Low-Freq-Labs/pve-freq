"""Tests for freq.jarvis.playbook — incident playbook runner."""
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from freq.jarvis.playbook import (
    PlaybookStep, Playbook, StepResult,
    load_playbooks, playbooks_to_dicts, run_step, result_to_dict,
)


class TestDataTypes(unittest.TestCase):
    def test_step_defaults(self):
        s = PlaybookStep(name="test", step_type="check", command="echo hi")
        self.assertEqual(s.target, "")
        self.assertEqual(s.expect, "")
        self.assertFalse(s.confirm)
        self.assertEqual(s.timeout, 30)

    def test_playbook_defaults(self):
        pb = Playbook(filename="test.toml", name="Test")
        self.assertEqual(pb.description, "")
        self.assertEqual(pb.trigger, "")
        self.assertEqual(pb.steps, [])

    def test_result_defaults(self):
        r = StepResult(step_name="s1", step_type="check", status="pass")
        self.assertEqual(r.output, "")
        self.assertEqual(r.error, "")
        self.assertEqual(r.duration, 0.0)


class TestPlaybookLoading(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_pb_test_")
        self.pb_dir = os.path.join(self.tmpdir, "playbooks")
        os.makedirs(self.pb_dir, exist_ok=True)
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_load_empty_dir(self):
        pbs = load_playbooks(self.tmpdir)
        self.assertEqual(len(pbs), 0)

    def test_load_no_dir(self):
        pbs = load_playbooks("/tmp/nonexistent_freq_test_dir")
        self.assertEqual(len(pbs), 0)

    def test_load_valid_toml(self):
        toml = b"""[playbook]
name = "Test Playbook"
description = "A test"
trigger = "docker_down"

[[step]]
name = "Check status"
type = "check"
command = "echo ok"
target = "h1"
expect = "ok"
"""
        with open(os.path.join(self.pb_dir, "test.toml"), "wb") as f:
            f.write(toml)
        pbs = load_playbooks(self.tmpdir)
        self.assertEqual(len(pbs), 1)
        self.assertEqual(pbs[0].name, "Test Playbook")
        self.assertEqual(pbs[0].trigger, "docker_down")
        self.assertEqual(len(pbs[0].steps), 1)
        self.assertEqual(pbs[0].steps[0].step_type, "check")
        self.assertEqual(pbs[0].steps[0].expect, "ok")

    def test_load_malformed_toml_skipped(self):
        with open(os.path.join(self.pb_dir, "bad.toml"), "wb") as f:
            f.write(b"{{{{invalid")
        pbs = load_playbooks(self.tmpdir)
        self.assertEqual(len(pbs), 0)

    def test_load_multiple_sorted(self):
        for name in ["beta.toml", "alpha.toml"]:
            toml = f'[playbook]\nname = "{name}"\n'.encode()
            with open(os.path.join(self.pb_dir, name), "wb") as f:
                f.write(toml)
        pbs = load_playbooks(self.tmpdir)
        self.assertEqual(len(pbs), 2)
        self.assertEqual(pbs[0].filename, "alpha.toml")

    def test_load_skips_non_toml(self):
        with open(os.path.join(self.pb_dir, "readme.md"), "w") as f:
            f.write("# Not a playbook")
        pbs = load_playbooks(self.tmpdir)
        self.assertEqual(len(pbs), 0)

    def test_step_confirm_flag(self):
        toml = b"""[playbook]
name = "Confirm Test"

[[step]]
name = "Dangerous action"
type = "action"
command = "docker restart plex"
target = "h1"
confirm = true
"""
        with open(os.path.join(self.pb_dir, "confirm.toml"), "wb") as f:
            f.write(toml)
        pbs = load_playbooks(self.tmpdir)
        self.assertTrue(pbs[0].steps[0].confirm)


class TestSerialization(unittest.TestCase):
    def test_playbooks_to_dicts(self):
        steps = [PlaybookStep(name="s1", step_type="check", command="echo ok", target="h1")]
        pbs = [Playbook(filename="test.toml", name="Test", steps=steps)]
        dicts = playbooks_to_dicts(pbs)
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]["name"], "Test")
        self.assertEqual(len(dicts[0]["steps"]), 1)
        self.assertEqual(dicts[0]["steps"][0]["type"], "check")

    def test_playbooks_to_dicts_empty(self):
        self.assertEqual(playbooks_to_dicts([]), [])

    def test_result_to_dict(self):
        r = StepResult(step_name="s1", step_type="check", status="pass", output="ok", duration=1.5)
        d = result_to_dict(r)
        self.assertEqual(d["step_name"], "s1")
        self.assertEqual(d["status"], "pass")
        self.assertEqual(d["duration"], 1.5)

    def test_result_to_dict_truncates_output(self):
        r = StepResult(step_name="s1", step_type="check", status="pass", output="x" * 500)
        d = result_to_dict(r)
        self.assertLessEqual(len(d["output"]), 200)


class TestRunStep(unittest.TestCase):
    def _make_cfg(self):
        cfg = MagicMock()
        cfg.hosts = []
        cfg.ssh_key_path = "/tmp/test_key"
        cfg.ssh_connect_timeout = 5
        return cfg

    def _make_ssh_result(self, stdout="", stderr="", returncode=0):
        r = MagicMock()
        r.stdout = stdout
        r.stderr = stderr
        r.returncode = returncode
        return r

    @patch("freq.core.resolve.by_target")
    def test_step_pass(self, mock_by_target):
        host = MagicMock()
        host.ip = "10.0.0.1"
        host.htype = "linux"
        mock_by_target.return_value = host

        ssh = MagicMock(return_value=self._make_ssh_result(stdout="ok"))
        step = PlaybookStep(name="check", step_type="check", command="echo ok", target="h1", expect="ok")
        result = run_step(step, ssh, self._make_cfg())
        self.assertEqual(result.status, "pass")

    @patch("freq.core.resolve.by_target")
    def test_step_fail_exit_code(self, mock_by_target):
        host = MagicMock()
        host.ip = "10.0.0.1"
        host.htype = "linux"
        mock_by_target.return_value = host

        ssh = MagicMock(return_value=self._make_ssh_result(returncode=1, stderr="error"))
        step = PlaybookStep(name="action", step_type="action", command="restart svc", target="h1")
        result = run_step(step, ssh, self._make_cfg())
        self.assertEqual(result.status, "fail")

    @patch("freq.core.resolve.by_target")
    def test_step_fail_wrong_output(self, mock_by_target):
        host = MagicMock()
        host.ip = "10.0.0.1"
        host.htype = "linux"
        mock_by_target.return_value = host

        ssh = MagicMock(return_value=self._make_ssh_result(stdout="down"))
        step = PlaybookStep(name="check", step_type="check", command="docker ps", target="h1", expect="Up")
        result = run_step(step, ssh, self._make_cfg())
        self.assertEqual(result.status, "fail")
        self.assertIn("Expected", result.error)

    @patch("freq.core.resolve.by_target")
    def test_missing_host(self, mock_by_target):
        mock_by_target.return_value = None
        ssh = MagicMock()
        step = PlaybookStep(name="check", step_type="check", command="echo hi", target="missing")
        result = run_step(step, ssh, self._make_cfg())
        self.assertEqual(result.status, "fail")
        self.assertIn("not found", result.error)

    @patch("freq.core.resolve.by_target")
    def test_no_target(self, mock_by_target):
        mock_by_target.return_value = None
        ssh = MagicMock()
        step = PlaybookStep(name="check", step_type="check", command="echo hi", target="")
        result = run_step(step, ssh, self._make_cfg())
        self.assertEqual(result.status, "fail")
        self.assertIn("No target", result.error)
