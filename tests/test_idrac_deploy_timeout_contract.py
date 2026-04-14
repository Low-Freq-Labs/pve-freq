"""R-E2E-IDRAC-PRIVILEGE-HANG-20260413R regression contract.

Final clean 5005 E2E on HEAD 285fa68 was hard-stuck in Phase 8 because
a hung iDRAC racadm command wedged subprocess.run(timeout=) — the
Python timeout killed sshpass but the ssh grandchild held the pipe
FDs open and the loop crawled forward one slow step at a time with no
real per-host ceiling. Fixes:

  1. init_cmd._run_bounded spawns its child in a new session and on
     timeout SIGKILLs the whole process group, reaching ssh + racadm
     alongside sshpass. rc=124 on timeout.
  2. init_cmd._run and init_cmd._run_with_input delegate to
     _run_bounded so every caller inherits the tree-kill.
  3. init_cmd._init_ssh(deploy_start=…, deploy_budget=…) clamps each
     step's timeout to the remaining per-host wall-clock budget and
     short-circuits rc=124 when the budget is exhausted.
  4. _deploy_idrac / _deploy_switch pass their deploy_start and
     DEVICE_DEPLOY_TIMEOUT into _init_ssh so the whole host can never
     exceed DEVICE_DEPLOY_TIMEOUT regardless of how many individual
     racadm commands hang.

This file pins each of those guarantees so a regression fails fast.
"""
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from freq.modules import init_cmd  # noqa: E402


class TestRunBoundedTimeoutKillsTree(unittest.TestCase):
    """_run_bounded must return within timeout+drain regardless of
    whether the child tree still holds the pipes open."""

    def test_direct_child_hang_returns_on_time(self):
        """A plain `sleep 9999` child must be SIGKILL'd on timeout
        and _run_bounded must return rc=124 within ~timeout+2s."""
        start = time.monotonic()
        rc, out, err = init_cmd._run_bounded(
            ["sleep", "9999"], timeout=2,
        )
        elapsed = time.monotonic() - start
        self.assertEqual(rc, 124, f"expected rc=124 (timeout), got rc={rc} err={err!r}")
        self.assertLess(
            elapsed, 8,
            f"_run_bounded blocked for {elapsed:.1f}s on a 2s timeout — "
            f"the process-group kill is not firing",
        )
        self.assertIn("timed out", err.lower())

    def test_grandchild_hang_pipe_inheritance(self):
        """Reproduces the exact iDRAC class of bug: parent spawns a
        grandchild that holds stdout open, parent exits. Without a
        process-group kill, communicate() would hang reading the
        inherited pipe. With start_new_session+killpg, both die.
        """
        # sh -c 'sleep 9999 & disown; echo started' — the grandchild
        # holds nothing BUT the shell pipe. Use a python one-liner
        # that forks and keeps stdout open to pin the exact pattern.
        script = (
            "import os, sys, time\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    # grandchild — keep stdout open forever\n"
            "    time.sleep(9999)\n"
            "else:\n"
            "    sys.stdout.write('started\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(9999)\n"
        )
        start = time.monotonic()
        rc, out, err = init_cmd._run_bounded(
            [sys.executable, "-c", script], timeout=2,
        )
        elapsed = time.monotonic() - start
        self.assertEqual(rc, 124, f"expected rc=124, got rc={rc}")
        self.assertLess(
            elapsed, 10,
            f"_run_bounded blocked for {elapsed:.1f}s on a forked "
            f"grandchild — killpg is not reaching the grandchild",
        )

    def test_fast_command_still_works(self):
        """_run_bounded must still return rc=0 + stdout on success."""
        rc, out, err = init_cmd._run_bounded(["echo", "hello"], timeout=5)
        self.assertEqual(rc, 0)
        self.assertIn("hello", out)

    def test_input_text_passed_through(self):
        """_run_bounded must honor input_text for stdin-driven callers
        (used by IOS switch config via _run_with_input)."""
        rc, out, err = init_cmd._run_bounded(["cat"], timeout=5, input_text="hi\n")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "hi")

    def test_nonexistent_binary_returns_error(self):
        """Missing binary must return rc=1 with a useful message,
        not blow up the caller."""
        rc, out, err = init_cmd._run_bounded(
            ["/nonexistent/binary/definitely-not-here"], timeout=2,
        )
        self.assertEqual(rc, 1)
        self.assertTrue(err)


class TestRunDelegatesToRunBounded(unittest.TestCase):
    """_run and _run_with_input must inherit the tree-kill fix."""

    def test_run_inherits_tree_kill(self):
        """_run(sleep 9999, timeout=2) must return within ~4s."""
        start = time.monotonic()
        rc, out, err = init_cmd._run(["sleep", "9999"], timeout=2)
        elapsed = time.monotonic() - start
        self.assertEqual(rc, 124)
        self.assertLess(elapsed, 8)

    def test_run_with_input_inherits_tree_kill(self):
        """_run_with_input on a hung child must return within timeout."""
        start = time.monotonic()
        rc, out, err = init_cmd._run_with_input(
            ["sleep", "9999"], "hello\n", timeout=2,
        )
        elapsed = time.monotonic() - start
        self.assertEqual(rc, 124)
        self.assertLess(elapsed, 8)


class TestInitSshRemainingBudget(unittest.TestCase):
    """_init_ssh with deploy_start+deploy_budget must clamp each step
    and short-circuit once the budget is exhausted."""

    def test_budget_exhausted_short_circuits(self):
        """When wall-clock exceeds the budget, _ssh must return
        rc=124 immediately without spawning a subprocess."""
        # deploy_start in the past by more than the budget.
        deploy_start = time.monotonic() - 200.0
        _ssh = init_cmd._init_ssh(
            "10.0.0.1", "password", "", "root",
            deploy_start=deploy_start, deploy_budget=120,
        )
        # Patch _run_bounded to detect whether we got that far.
        with mock.patch.object(init_cmd, "_run_bounded") as m:
            start = time.monotonic()
            rc, out, err = _ssh("echo hi", timeout=30)
            elapsed = time.monotonic() - start
        self.assertEqual(rc, 124)
        self.assertIn("budget exhausted", err)
        self.assertLess(elapsed, 0.5, "short-circuit must not spawn a subprocess")
        m.assert_not_called()

    def test_budget_remaining_clamps_timeout(self):
        """When only 5s remain and a step requests 60s, the step
        must be capped to ~5s so it can't blow the ceiling."""
        deploy_start = time.monotonic() - 115.0  # 5s remaining on a 120s budget
        _ssh = init_cmd._init_ssh(
            "10.0.0.1", "", "/fake/key", "root",
            deploy_start=deploy_start, deploy_budget=120,
        )
        captured = {}

        def fake_run_bounded(cmd, timeout=30, input_text=None):
            captured["timeout"] = timeout
            return 0, "", ""

        with mock.patch.object(init_cmd, "_run_bounded", side_effect=fake_run_bounded):
            _ssh("echo hi", timeout=60)
        self.assertIn("timeout", captured)
        self.assertLessEqual(
            captured["timeout"], 6,
            f"requested 60s with 5s remaining budget, got timeout={captured['timeout']}",
        )
        self.assertGreaterEqual(captured["timeout"], 1)

    def test_no_budget_leaves_timeout_alone(self):
        """When deploy_start/deploy_budget are not passed, behavior
        must match the pre-fix path — no clamping."""
        _ssh = init_cmd._init_ssh("10.0.0.1", "", "/fake/key", "root")
        captured = {}

        def fake_run_bounded(cmd, timeout=30, input_text=None):
            captured["timeout"] = timeout
            return 0, "", ""

        with mock.patch.object(init_cmd, "_run_bounded", side_effect=fake_run_bounded):
            _ssh("echo hi", timeout=60)
        self.assertEqual(captured["timeout"], 60)


class TestInitSshKeepaliveOptions(unittest.TestCase):
    """_init_ssh must add ServerAliveInterval/ServerAliveCountMax so
    stuck SSH sessions self-terminate client-side within ~15s even if
    the Python subprocess timeout is mid-flight."""

    def test_keepalives_in_ssh_opts(self):
        """Inspect the generated ssh command to confirm keepalives."""
        _ssh = init_cmd._init_ssh("10.0.0.1", "", "/fake/key", "root")
        captured = {}

        def fake_run_bounded(cmd, timeout=30, input_text=None):
            captured["cmd"] = cmd
            return 0, "", ""

        with mock.patch.object(init_cmd, "_run_bounded", side_effect=fake_run_bounded):
            _ssh("racadm getsysinfo", timeout=15)
        cmd_str = " ".join(captured["cmd"])
        self.assertIn("ServerAliveInterval=5", cmd_str)
        self.assertIn("ServerAliveCountMax=3", cmd_str)


class TestDeployIdracCeiling(unittest.TestCase):
    """_deploy_idrac must never exceed DEVICE_DEPLOY_TIMEOUT when every
    racadm call hangs forever. This is the top-level contract Finn
    cares about: one bad host must not wedge the whole init."""

    def test_hung_racadm_bails_within_ceiling(self):
        """Monkeypatch _run_bounded so every SSH call hangs at the
        subprocess layer. _deploy_idrac must still return False
        within DEVICE_DEPLOY_TIMEOUT + a small drain margin."""
        ctx = {
            "svc_name": "freq",
            "svc_pass": "testpass",
            "rsa_pubkey": "ssh-rsa AAAAB3Nzab test@host",
            "dry_run": False,
        }
        call_count = {"n": 0}

        def hung_run_bounded(cmd, timeout=30, input_text=None):
            # Simulate a subprocess that hangs up to its given timeout
            # but respects the clamp applied by _init_ssh. Sleep up to
            # 90% of the passed timeout then return rc=124 (tree-kill).
            call_count["n"] += 1
            time.sleep(max(0.1, min(timeout * 0.9, 5)))
            return 124, "", f"command timed out after {timeout}s"

        with mock.patch.object(init_cmd, "_run_bounded", side_effect=hung_run_bounded):
            start = time.monotonic()
            result = init_cmd._deploy_idrac(
                "10.0.0.1", ctx, auth_pass="adminpass",
                auth_key="", auth_user="root",
            )
            elapsed = time.monotonic() - start

        self.assertFalse(result, "_deploy_idrac must return False on hang")
        self.assertLess(
            elapsed, init_cmd.DEVICE_DEPLOY_TIMEOUT + 10,
            f"_deploy_idrac ran for {elapsed:.1f}s on an all-hung host — "
            f"DEVICE_DEPLOY_TIMEOUT={init_cmd.DEVICE_DEPLOY_TIMEOUT} ceiling breached",
        )
        self.assertGreater(call_count["n"], 0, "at least the connect probe must run")


if __name__ == "__main__":
    unittest.main()
