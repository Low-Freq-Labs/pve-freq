"""R-RESILIENCE-INIT-RECOVERY-20260413S regression contract.

Findings from live 5005 churn after dfb8ced:

  S-1 AUTH RECOVERY GAP — /api/auth/login rejects every known password
  for the bootstrap admin while users/roles.conf still list it as admin. Root cause:
  headless init in bootstrap-key mode never seeds a dashboard password
  (the _seed_headless_dashboard_auth path only fires when bootstrap_pass
  is set), and F1 of the security audit removed the silent first-login
  seeding path, so there was no CLI recovery for a forgotten dashboard
  password. Fix: new `freq user dashboard-passwd <user>` break-glass
  subcommand that writes a PBKDF2-SHA256 hash to vault auth/password_<user>.

  S-2 MISLEADING STARTUP HINT — dashboard startup prints "First login
  sets password for: X" on every boot, which is a lie after F1 (login
  refuses empty stored_hash). Fix: replace with "Users without dashboard
  password: X" plus a pointer at the new dashboard-passwd CLI.

  S-5 iDRAC RERUN IDEMPOTENCY — second init run against an iDRAC that
  already holds this service account errors with RAC1016 "user already
  exists" on the `racadm set ...UserName` command. Fix: skip UserName
  set when existing_slot is truthy; Password/Privilege/Enable are safe
  to re-issue.

This file pins the contracts so the fixes can't drift away again.
"""
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
INIT_CMD_PY = REPO / "freq" / "modules" / "init_cmd.py"
SERVE_PY = REPO / "freq" / "modules" / "serve.py"
SSH_MUX_CLEANUP_PY = REPO / "freq" / "services" / "ssh_mux_cleanup.py"
USERS_PY = REPO / "freq" / "modules" / "users.py"
CLI_PY = REPO / "freq" / "cli.py"


class TestDashboardPasswdCliRegistered(unittest.TestCase):
    """The break-glass dashboard-passwd subcommand must be wired up in
    freq user <...> and the handler must exist in freq.modules.users."""

    def test_cli_registers_dashboard_passwd_subcommand(self):
        src = CLI_PY.read_text()
        self.assertIn('add_parser(\n        "dashboard-passwd",', src)
        self.assertIn("_cmd_dashboard_passwd", src)

    def test_cli_cmd_function_exists(self):
        src = CLI_PY.read_text()
        self.assertIn("def _cmd_dashboard_passwd(", src)

    def test_users_module_exports_handler(self):
        from freq.modules import users as users_mod
        self.assertTrue(hasattr(users_mod, "cmd_dashboard_passwd"))
        self.assertTrue(callable(users_mod.cmd_dashboard_passwd))


class TestDashboardPasswdHandlerBehavior(unittest.TestCase):
    """End-to-end behavior of cmd_dashboard_passwd with a fake cfg/vault."""

    def _make_fake_cfg(self, tmp_path):
        class Cfg:
            conf_dir = str(tmp_path)
            vault_file = str(tmp_path / "vault.enc")
            ssh_service_account = "freq-admin"
            _toml_users = None

        (tmp_path / "users.conf").write_text("bootstrap-admin admin\nalice operator\n")
        return Cfg()

    def test_rejects_service_account(self):
        import tempfile
        from freq.modules import users as users_mod
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._make_fake_cfg(tmp)
            args = mock.Mock(username="freq-admin", file=None)
            rc = users_mod.cmd_dashboard_passwd(cfg, None, args)
            self.assertEqual(rc, 1, "service account must be refused")

    def test_rejects_unknown_user(self):
        import tempfile
        from freq.modules import users as users_mod
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._make_fake_cfg(tmp)
            args = mock.Mock(username="nobody", file=None)
            rc = users_mod.cmd_dashboard_passwd(cfg, None, args)
            self.assertEqual(rc, 1, "unknown user must be refused")

    def test_rejects_short_password(self):
        import tempfile
        from freq.modules import users as users_mod
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._make_fake_cfg(tmp)
            pwfile = tmp / "pw.txt"
            pwfile.write_text("short\n")
            args = mock.Mock(username="bootstrap-admin", file=str(pwfile))
            rc = users_mod.cmd_dashboard_passwd(cfg, None, args)
            self.assertEqual(rc, 1, "<8 char password must be refused")

    def test_writes_pbkdf2_hash_to_vault_on_success(self):
        import tempfile
        from freq.modules import users as users_mod
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._make_fake_cfg(tmp)
            pwfile = tmp / "pw.txt"
            pwfile.write_text("correct-horse-battery-staple\n")
            args = mock.Mock(username="bootstrap-admin", file=str(pwfile))

            written = {}

            def fake_vault_init(c):
                written["init"] = True
                return True

            def fake_vault_set(c, section, key, value):
                written.setdefault("writes", []).append((section, key, value))
                return True

            def fake_vault_get(c, section, key):
                # R-AUTH-RESTART-DRIFT-20260413W: cmd_dashboard_passwd now
                # round-trips the write. Return the last-written value so
                # the round-trip verify_password passes in the happy path.
                writes = written.get("writes", [])
                for s, k, v in reversed(writes):
                    if s == section and k == key:
                        return v
                return ""

            with mock.patch("freq.modules.vault.vault_init", side_effect=fake_vault_init), \
                 mock.patch("freq.modules.vault.vault_set", side_effect=fake_vault_set), \
                 mock.patch("freq.modules.vault.vault_get", side_effect=fake_vault_get):
                rc = users_mod.cmd_dashboard_passwd(cfg, None, args)

            self.assertEqual(rc, 0)
            self.assertEqual(len(written.get("writes", [])), 1)
            section, key, value = written["writes"][0]
            self.assertEqual(section, "auth")
            self.assertEqual(key, "password_bootstrap-admin")
            # PBKDF2 format: <salt-hex>$<digest-hex>
            self.assertRegex(value, r"^[0-9a-f]+\$[0-9a-f]+$")

    def test_roundtrip_hash_verifies_against_entered_password(self):
        """The written hash must successfully verify_password() the input."""
        from freq.api.auth import hash_password, verify_password
        pw = "correct-horse-battery-staple"
        h = hash_password(pw)
        self.assertTrue(verify_password(pw, h))
        self.assertFalse(verify_password("wrong-password", h))


class TestMisleadingStartupHintReplaced(unittest.TestCase):
    """serve.py startup banner must no longer claim 'First login sets
    password' and must point at the dashboard-passwd recovery CLI."""

    def test_no_first_login_sets_password_string(self):
        src = SERVE_PY.read_text()
        self.assertNotIn(
            "First login sets password for:",
            src,
            "the misleading pre-F1 hint string must be gone",
        )

    def test_recovery_hint_points_at_cli(self):
        src = SERVE_PY.read_text()
        self.assertIn("Users without dashboard password:", src)
        self.assertIn("freq user dashboard-passwd", src)


class TestIdracRerunIdempotency(unittest.TestCase):
    """_deploy_idrac must skip the UserName set command when the target
    slot already carries this user, preventing RAC1016 on reruns."""

    def test_existing_slot_skips_username_set(self):
        """Source-pin: when existing_slot is truthy the setup_cmds tuple
        must not include a `racadm set ...UserName` command."""
        src = INIT_CMD_PY.read_text()
        # Find the _deploy_idrac function window.
        start = src.find("def _deploy_idrac(")
        self.assertGreater(start, 0)
        # Locate the setup_cmds construction within the deploy function.
        window_end = src.find("def _deploy_switch(", start)
        window = src[start:window_end]
        # The fix must have a branch that skips UserName on existing_slot.
        self.assertIn("if existing_slot:", window)
        # base_cmds must not include UserName.
        base_idx = window.find("base_cmds = [")
        self.assertGreater(base_idx, 0, "base_cmds list must exist")
        base_end = window.find("]", base_idx)
        base_block = window[base_idx:base_end]
        self.assertNotIn(".UserName ", base_block,
                         "base_cmds (used on existing_slot rerun) must NOT "
                         "carry a UserName set — that's the RAC1016 trigger")
        # And Password/Privilege/Enable/IpmiLanPrivilege stay in base_cmds.
        self.assertIn(".Password ", base_block)
        self.assertIn(".Privilege ", base_block)
        self.assertIn(".Enable ", base_block)
        self.assertIn(".IpmiLanPrivilege ", base_block)


class TestShutdownMuxCleanupBudgeted(unittest.TestCase):
    """_cleanup_ssh_mux must parallelize ssh -O exit and cap the total
    wall-clock to a short budget so a ~20-host fleet can't breach
    systemd's TimeoutStopSec when the dashboard is restarted."""

    def test_cleanup_uses_thread_pool(self):
        src = SSH_MUX_CLEANUP_PY.read_text()
        idx = src.find("def cleanup_ssh_mux(")
        self.assertGreater(idx, 0)
        end = src.find("\ndef ", idx + 30)
        window = src[idx:end]
        self.assertIn("ThreadPoolExecutor", window)
        self.assertIn("start_new_session=True", window)
        # Budget cap (find the numeric literal).
        self.assertRegex(window, r"budget\s*=\s*\d+")

    def test_cleanup_runs_fast_on_many_sockets(self):
        """Exercise the complete bounded cleanup contract without real SSH."""
        import ast
        import concurrent.futures
        import glob
        import inspect
        import subprocess as sp

        from freq.modules import serve as serve_mod
        from freq.services import ssh_mux_cleanup

        self.assertIs(serve_mod._cleanup_ssh_mux, ssh_mux_cleanup.cleanup_ssh_mux)
        service_tree = ast.parse(inspect.getsource(ssh_mux_cleanup))
        imports = {
            alias.name
            for node in ast.walk(service_tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertEqual(
            imports,
            {"concurrent.futures", "glob", "os", "signal", "subprocess", "time"},
        )
        imported_from = {
            node.module
            for node in ast.walk(service_tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertEqual(imported_from, {"freq.core"})

        class FakeCfg:
            ssh_service_account = "fake-svc"

        fake_cfg = FakeCfg()
        mux_dir = "/run/freq-test/mux"
        socket_paths = [f"{mux_dir}/sock{i}" for i in range(4)]

        # Missing and empty mux directories are strict zero-process exits.
        with mock.patch.object(
            ssh_mux_cleanup.os.path, "expanduser", return_value=mux_dir
        ) as expanduser, mock.patch.object(
            ssh_mux_cleanup.os.path, "isdir", return_value=False
        ), mock.patch.object(glob, "glob") as glob_paths, mock.patch.object(
            ssh_mux_cleanup.subprocess, "Popen"
        ) as popen:
            serve_mod._cleanup_ssh_mux(fake_cfg)
        expanduser.assert_called_once_with("~fake-svc/.ssh/freq-mux")
        glob_paths.assert_not_called()
        popen.assert_not_called()

        with mock.patch.object(
            ssh_mux_cleanup.os.path, "expanduser", return_value=mux_dir
        ), mock.patch.object(
            ssh_mux_cleanup.os.path, "isdir", return_value=True
        ), mock.patch.object(
            glob, "glob", return_value=[]
        ) as glob_paths, mock.patch.object(
            ssh_mux_cleanup.subprocess, "Popen"
        ) as popen:
            serve_mod._cleanup_ssh_mux(fake_cfg)
        glob_paths.assert_called_once_with(f"{mux_dir}/*")
        popen.assert_not_called()

        class FakeProcess:
            def __init__(self, pid, *, times_out=False):
                self.pid = pid
                self.times_out = times_out
                self.communicate_timeouts = []
                self.kill = mock.Mock()

            def communicate(self, *, timeout):
                self.communicate_timeouts.append(timeout)
                if self.times_out and len(self.communicate_timeouts) == 1:
                    raise sp.TimeoutExpired(cmd="ssh", timeout=timeout)
                return b"", b""

        class ImmediateFuture:
            def __init__(self, result):
                self._result = result
                self.result_timeouts = []

            def result(self, timeout=None):
                self.result_timeouts.append(timeout)
                return self._result

        class ImmediatePool:
            instances = []

            def __init__(self, *, max_workers):
                self.max_workers = max_workers
                self.submitted = []
                self.futures = []
                self.__class__.instances.append(self)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, function, sock):
                self.submitted.append(sock)
                future = ImmediateFuture(function(sock))
                self.futures.append(future)
                return future

        normal = FakeProcess(100)
        group_timeout = FakeProcess(200, times_out=True)
        fallback_timeout = FakeProcess(300, times_out=True)
        completed = {}

        def immediate_as_completed(futures, *, timeout):
            completed["futures"] = futures
            completed["timeout"] = timeout
            return iter(futures)

        with mock.patch.object(
            ssh_mux_cleanup.os.path, "expanduser", return_value=mux_dir
        ), mock.patch.object(
            ssh_mux_cleanup.os.path, "isdir", return_value=True
        ), mock.patch.object(
            glob, "glob", return_value=socket_paths
        ), mock.patch.object(
            ssh_mux_cleanup.subprocess,
            "Popen",
            side_effect=[normal, group_timeout, fallback_timeout, RuntimeError("gone")],
        ) as popen, mock.patch.object(
            concurrent.futures, "ThreadPoolExecutor", ImmediatePool
        ), mock.patch.object(
            concurrent.futures, "as_completed", side_effect=immediate_as_completed
        ), mock.patch.object(
            ssh_mux_cleanup.os, "getpgid", side_effect=[901, OSError("reaped")]
        ) as getpgid, mock.patch.object(
            ssh_mux_cleanup.os, "killpg"
        ) as killpg:
            serve_mod._cleanup_ssh_mux(fake_cfg)

        pool = ImmediatePool.instances[-1]
        self.assertEqual(pool.max_workers, 4)
        self.assertEqual(pool.submitted, socket_paths)
        self.assertEqual(completed["futures"], pool.futures)
        self.assertEqual(completed["timeout"], 8)
        self.assertEqual([f.result_timeouts for f in pool.futures], [[0.1]] * 4)
        expected_process_calls = [
            mock.call(
                ["ssh", "-O", "exit", "-o", f"ControlPath={sock}", "dummy"],
                stdin=sp.DEVNULL,
                stdout=sp.PIPE,
                stderr=sp.PIPE,
                start_new_session=True,
            )
            for sock in socket_paths
        ]
        self.assertEqual(popen.call_args_list, expected_process_calls)
        self.assertEqual(normal.communicate_timeouts, [2])
        self.assertEqual(group_timeout.communicate_timeouts, [2, 1])
        self.assertEqual(fallback_timeout.communicate_timeouts, [2, 1])
        self.assertEqual(getpgid.call_args_list, [mock.call(200), mock.call(300)])
        killpg.assert_called_once_with(901, __import__("signal").SIGKILL)
        group_timeout.kill.assert_not_called()
        fallback_timeout.kill.assert_called_once_with()

        # Aggregate expiry is contained and reports the exact bounded context.
        class PendingPool(ImmediatePool):
            def submit(self, function, sock):
                self.submitted.append(sock)
                future = ImmediateFuture(None)
                self.futures.append(future)
                return future

        with mock.patch.object(
            ssh_mux_cleanup.os.path, "expanduser", return_value=mux_dir
        ), mock.patch.object(
            ssh_mux_cleanup.os.path, "isdir", return_value=True
        ), mock.patch.object(
            glob, "glob", return_value=socket_paths[:1]
        ), mock.patch.object(
            concurrent.futures, "ThreadPoolExecutor", PendingPool
        ), mock.patch.object(
            concurrent.futures,
            "as_completed",
            side_effect=concurrent.futures.TimeoutError,
        ), mock.patch.object(
            ssh_mux_cleanup.time, "monotonic", side_effect=[100.0, 108.37]
        ), mock.patch.object(ssh_mux_cleanup.logger, "warning") as warning:
            serve_mod._cleanup_ssh_mux(fake_cfg)
        warning.assert_called_once_with(
            "ssh_mux cleanup exceeded 8s budget — leaving stragglers to systemd",
            elapsed=8.4,
            sockets=1,
        )


if __name__ == "__main__":
    unittest.main()
