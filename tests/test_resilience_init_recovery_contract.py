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

  S-4 LEGACY HEALTH PROBE CHURN — bmc-10/bmc-11 flip UP→DOWN under
  repeated fleet status polls because HEALTH_CMDS has no "idrac" entry,
  so the probe falls back to the linux `echo "$(hostname)|..."` string
  which the Dell racadm shell rejects. Fix: add "idrac": "racadm
  getsysinfo -s" to HEALTH_CMDS in both serve.py._bg_probe_health and
  api/fleet.py, with a dedicated return branch that reports "healthy"
  and "-" for the columns iDRAC doesn't populate.

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
FLEET_API_PY = REPO / "freq" / "api" / "fleet.py"
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


class TestLegacyHealthProbeIdrac(unittest.TestCase):
    """HEALTH_CMDS in both serve.py (_bg_probe_health) and api/fleet.py
    must carry an iDRAC entry so the health probe doesn't send POSIX
    linux shell strings to Dell racadm. Missing entry was the root cause
    of the UP→DOWN flip under repeated polls."""

    def test_serve_py_has_idrac_health_cmd(self):
        src = SERVE_PY.read_text()
        # Find the _bg_probe_health function window.
        idx = src.find("def _bg_probe_health(")
        self.assertGreater(idx, 0)
        window_end = src.find("def _bg_probe", idx + 20)
        window = src[idx:window_end]
        self.assertIn('"idrac": "racadm getsysinfo -s"', window)

    def test_serve_py_has_idrac_return_branch(self):
        src = SERVE_PY.read_text()
        idx = src.find("def _bg_probe_health(")
        window_end = src.find("def _bg_probe", idx + 20)
        window = src[idx:window_end]
        self.assertIn('if htype == "idrac":', window)

    def test_fleet_api_has_idrac_health_cmd(self):
        src = FLEET_API_PY.read_text()
        self.assertIn('"idrac": "racadm getsysinfo -s"', src)

    def test_fleet_api_has_idrac_return_branch(self):
        src = FLEET_API_PY.read_text()
        self.assertIn('if htype == "idrac":', src)


class TestShutdownMuxCleanupBudgeted(unittest.TestCase):
    """_cleanup_ssh_mux must parallelize ssh -O exit and cap the total
    wall-clock to a short budget so a ~20-host fleet can't breach
    systemd's TimeoutStopSec when the dashboard is restarted."""

    def test_cleanup_uses_thread_pool(self):
        src = SERVE_PY.read_text()
        idx = src.find("def _cleanup_ssh_mux(")
        self.assertGreater(idx, 0)
        end = src.find("\ndef ", idx + 30)
        window = src[idx:end]
        self.assertIn("ThreadPoolExecutor", window)
        self.assertIn("start_new_session=True", window)
        # Budget cap (find the numeric literal).
        self.assertRegex(window, r"budget\s*=\s*\d+")

    def test_cleanup_runs_fast_on_many_sockets(self):
        """Smoke test: 20 fake mux sockets, each `ssh -O exit` monkey-
        patched to Popen a 5s sleep. Shutdown must return within the
        8s budget, not 20 × 5s serially."""
        import subprocess as sp
        import tempfile
        import time as _time
        from freq.modules import serve as serve_mod

        with tempfile.TemporaryDirectory() as td:
            mux_dir = Path(td) / "mux"
            mux_dir.mkdir()
            for i in range(20):
                (mux_dir / f"sock{i}").write_text("")

            class FakeCfg:
                pass

            fake_cfg = FakeCfg()
            fake_cfg.ssh_service_account = "fake-svc"

            # Redirect ~fake-svc/.ssh/freq-mux to our temp dir via
            # os.path.expanduser monkeypatch.
            orig_expanduser = os.path.expanduser

            def fake_expanduser(p):
                if "fake-svc" in p and "freq-mux" in p:
                    return str(mux_dir)
                return orig_expanduser(p)

            # The ssh -O exit command would hang on a real socket; our
            # fake simulates hang by sleeping 5s. With the parallel +
            # budgeted fix this whole call must finish in ~8s even
            # though serial would be 100s.
            original_popen = sp.Popen
            slow_args_marker = "slow_sock_sentinel_%d" % os.getpid()

            def fake_popen(cmd, *a, **kw):
                if isinstance(cmd, list) and any("ssh" in str(c) for c in cmd):
                    return original_popen(
                        ["sleep", "5"],
                        stdin=sp.DEVNULL,
                        stdout=sp.PIPE,
                        stderr=sp.PIPE,
                        start_new_session=kw.get("start_new_session", False),
                    )
                return original_popen(cmd, *a, **kw)

            with mock.patch("os.path.expanduser", side_effect=fake_expanduser), \
                 mock.patch.object(sp, "Popen", side_effect=fake_popen):
                start = _time.monotonic()
                serve_mod._cleanup_ssh_mux(fake_cfg)
                elapsed = _time.monotonic() - start

        # Parallel budget is 8s + minor overhead; definitely not 100s.
        self.assertLess(
            elapsed, 12,
            f"_cleanup_ssh_mux blocked for {elapsed:.1f}s on 20 slow "
            f"sockets — parallel + budget not honored",
        )


if __name__ == "__main__":
    unittest.main()
