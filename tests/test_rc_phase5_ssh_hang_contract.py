"""R-RC-PHASE5-SSH-HANG-20260414X regression contract.

Finn's RC repeatability run on clean 5005 at d55934a stalled in Phase 5.
Live proof: root `python3 -m freq init` was stuck on a child
`ssh -n -i /home/freq-admin/.ssh/id_ed25519 -o ConnectTimeout=3
 -o BatchMode=yes -o StrictHostKeyChecking=accept-new
 freq-admin@<pve-ip> echo OK`.

Root cause: the post-deploy FREQ-key verify probes in _deploy_linux
(`echo OK` + `sudo -n true`) and _deploy_pfsense (`echo OK`) called
`_run([...])` with NO explicit `timeout=` kwarg, defaulting to
DEFAULT_CMD_TIMEOUT=30s. `ConnectTimeout=3` only bounds the TCP
connect — once TCP is up, banner/handshake/auth can stall
indefinitely (MaxStartups backoff, slow reverse DNS, authorized_keys
reload race). A 30s wall-clock hang per host on a 3-node PVE cluster
means Phase 5 can visibly wedge for ~90s without progress.

Fix: pin `timeout=QUICK_CHECK_TIMEOUT` (10s) on every verify _run,
add ServerAliveInterval=3 / ServerAliveCountMax=2 so even a post-auth
stall during `echo OK` execution drops the session at ~6s, and
branch on rc==124 so a timed-out verify surfaces as a clean
`step_fail` instead of a mute wedge.
"""
import os
import re
import subprocess as sp
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
INIT_CMD_PY = REPO / "freq" / "modules" / "init_cmd.py"


class TestDeployLinuxVerifyBounded(unittest.TestCase):
    """_deploy_linux's FREQ-key verify and sudo verify must both pass
    timeout=QUICK_CHECK_TIMEOUT and use ServerAlive* to bound a hung
    post-connect ssh handshake."""

    def _deploy_linux_window(self):
        src = INIT_CMD_PY.read_text()
        start = src.find("def _deploy_linux(")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        return src[start:end]

    def test_echo_ok_verify_has_explicit_timeout(self):
        window = self._deploy_linux_window()
        # Use rfind: the first `"echo OK"` is the bootstrap connectivity
        # test via _init_ssh (already bounded). The second is the
        # post-deploy FREQ-key verify that we're pinning here.
        idx = window.rfind('"echo OK"')
        self.assertGreater(idx, 0, "echo OK verify block must exist")
        tail = window[idx:idx + 400]
        self.assertIn("timeout=QUICK_CHECK_TIMEOUT", tail,
                      "echo OK verify _run must pass timeout=QUICK_CHECK_TIMEOUT")

    def test_echo_ok_verify_has_server_alive_opts(self):
        window = self._deploy_linux_window()
        idx = window.rfind('"echo OK"')
        head = window[max(0, idx - 600):idx]
        self.assertIn('"ServerAliveInterval=3"', head,
                      "echo OK verify must carry ServerAliveInterval=3")
        self.assertIn('"ServerAliveCountMax=2"', head,
                      "echo OK verify must carry ServerAliveCountMax=2")

    def test_sudo_verify_has_explicit_timeout(self):
        window = self._deploy_linux_window()
        idx = window.find('"sudo -n true"')
        self.assertGreater(idx, 0, "sudo -n true verify block must exist")
        tail = window[idx:idx + 400]
        self.assertIn("timeout=QUICK_CHECK_TIMEOUT", tail,
                      "sudo -n true verify _run must pass timeout=QUICK_CHECK_TIMEOUT")

    def test_sudo_verify_has_server_alive_opts(self):
        window = self._deploy_linux_window()
        idx = window.find('"sudo -n true"')
        head = window[max(0, idx - 600):idx]
        self.assertIn('"ServerAliveInterval=3"', head)
        self.assertIn('"ServerAliveCountMax=2"', head)

    def test_timeout_rc_124_surfaces_as_step_fail(self):
        """On rc == 124 (bounded-kill timeout) the verify must emit a
        distinct 'TIMED OUT' step_fail — not silently report pass."""
        window = self._deploy_linux_window()
        self.assertIn("if rc2 == 124:", window,
                      "echo OK verify must branch on rc==124 timeout")
        self.assertIn("if rc3 == 124:", window,
                      "sudo verify must branch on rc==124 timeout")
        self.assertIn("TIMED OUT", window,
                      "timeout branch must surface 'TIMED OUT' in step_fail")


class TestDeployPfsenseVerifyBounded(unittest.TestCase):
    """Same contract applies to _deploy_pfsense's echo OK verify."""

    def _deploy_pfsense_window(self):
        src = INIT_CMD_PY.read_text()
        start = src.find("def _deploy_pfsense(")
        self.assertGreater(start, 0)
        end = src.find("\ndef ", start + 10)
        return src[start:end]

    def test_echo_ok_verify_has_explicit_timeout(self):
        window = self._deploy_pfsense_window()
        idx = window.find('"echo OK"')
        # pfsense has an earlier _ssh("echo OK") connectivity test too;
        # take the LAST occurrence which is the key verify block.
        idx = window.rfind('"echo OK"')
        self.assertGreater(idx, 0)
        tail = window[idx:idx + 400]
        self.assertIn("timeout=QUICK_CHECK_TIMEOUT", tail)

    def test_echo_ok_verify_has_server_alive_opts(self):
        window = self._deploy_pfsense_window()
        idx = window.rfind('"echo OK"')
        head = window[max(0, idx - 600):idx]
        self.assertIn('"ServerAliveInterval=3"', head)
        self.assertIn('"ServerAliveCountMax=2"', head)

    def test_timeout_rc_124_surfaces_as_step_fail(self):
        window = self._deploy_pfsense_window()
        self.assertIn("if rc2 == 124:", window)
        self.assertIn("TIMED OUT", window)


class TestRunBoundedKillsHungChild(unittest.TestCase):
    """Live behavior: _run with timeout=QUICK_CHECK_TIMEOUT must return
    within ~1.5x the timeout even when the spawned child hangs. This is
    the ground-truth guarantee that Phase 5 cannot wedge on a dead ssh
    handshake anymore — the wall-clock bound is real."""

    def test_hung_sleep_child_returns_bounded(self):
        from freq.modules import init_cmd
        # Simulate a wedged ssh handshake with a plain 60s sleep.
        start = time.monotonic()
        rc, out, err = init_cmd._run(
            ["sleep", "60"],
            timeout=init_cmd.QUICK_CHECK_TIMEOUT,
        )
        elapsed = time.monotonic() - start
        self.assertEqual(rc, 124,
                         f"bounded kill must surface rc=124; got {rc} {out!r} {err!r}")
        self.assertIn("timed out", err.lower())
        # 10s timeout + 5s grace drain = 15s absolute ceiling.
        self.assertLess(elapsed, 16,
                        f"_run exceeded bound: {elapsed:.1f}s")


class TestPhase5HangClassCoverage(unittest.TestCase):
    """Guard against re-introducing the class of bug: any raw `_run([ssh, ...`
    in init_cmd.py that uses `-o ConnectTimeout=` MUST either pass an
    explicit timeout= or route through _init_ssh (which clamps its own
    timeout). This is a source-pin sweep over the whole file."""

    def test_no_unbounded_connect_timeout_ssh_run(self):
        src = INIT_CMD_PY.read_text()
        # Find every `_run(` call that contains `ConnectTimeout=` in its
        # argument list. Each such call must also contain `timeout=`
        # before the next `)` at top level.
        offenders = []
        pattern = re.compile(r"_run\(\s*\[", re.MULTILINE)
        for m in pattern.finditer(src):
            # Walk forward, balancing brackets, to find the _run call end.
            i = m.end() - 1  # on the '['
            depth_sq = 0
            depth_pa = 1  # we're inside _run(
            j = i
            while j < len(src) and depth_pa > 0:
                c = src[j]
                if c == "[":
                    depth_sq += 1
                elif c == "]":
                    depth_sq -= 1
                elif c == "(" and depth_sq == 0:
                    depth_pa += 1
                elif c == ")" and depth_sq == 0:
                    depth_pa -= 1
                j += 1
            call_text = src[m.start():j]
            if "ConnectTimeout=" not in call_text:
                continue
            if "timeout=" not in call_text:
                # Record with a short context to help debugging.
                line_no = src[:m.start()].count("\n") + 1
                offenders.append((line_no, call_text[:160]))
        self.assertEqual(
            offenders, [],
            "Unbounded _run([ssh ... ConnectTimeout=... ]) calls found; "
            "each must pass an explicit timeout= kwarg:\n"
            + "\n".join(f"  line {ln}: {txt!r}" for ln, txt in offenders),
        )


if __name__ == "__main__":
    unittest.main()
