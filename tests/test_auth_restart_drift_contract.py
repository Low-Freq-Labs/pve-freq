"""R-AUTH-RESTART-DRIFT-20260413W regression contract.

Finn reported that on the final RC at 896f6ef, a fresh headless init
seeded `auth/password_<bootstrap-user>` and the first login succeeded, but
after a dashboard restart the same password returned 401 — "Invalid
credentials". I could not reproduce the specific symptom on the same
commit at test time (repeated restart+login cycles all returned 200),
but the CLASS of bug that matches the symptom is:

  - A vault_set call that silently fails (returns False, or writes
    a file that isn't readable on the next open)
  - A write that doesn't round-trip through verify_password because
    the stored hash doesn't match the password we thought we wrote
    (wrong salt, truncated digest, encoding mismatch)
  - An atomic-rename leak that leaves a half-written tmp or a
    vault file with wrong ownership, so the first post-write read
    is cached / in-memory from the writer's own _encrypt call but
    the next process start can't decrypt.

This file pins the defensive hardening that would catch ANY member
of the class: every place that writes `auth/password_<user>` must
round-trip the hash through vault_get + verify_password immediately
after the write. If the round-trip fails the write must fail loudly
instead of reporting success.

  W-1: init's _seed_headless_dashboard_auth round-trips the hash.
  W-2: CLI's cmd_dashboard_passwd round-trips the hash.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
INIT_CMD_PY = REPO / "freq" / "modules" / "init_cmd.py"
USERS_PY = REPO / "freq" / "modules" / "users.py"


class TestSeedHeadlessRoundTripGuard(unittest.TestCase):
    """_seed_headless_dashboard_auth must round-trip verify the hash
    right after writing it. Silent vault_set failures must surface as
    init step_fail events, not step_ok."""

    def test_source_pins_round_trip_read_and_verify(self):
        src = INIT_CMD_PY.read_text()
        idx = src.find("def _seed_headless_dashboard_auth")
        self.assertGreater(idx, 0)
        window_end = src.find("\ndef ", idx + 50)
        window = src[idx:window_end]
        # After vault_set, the helper must vault_get the value back.
        self.assertIn("readback = vault_get(", window)
        # And run it through verify_password with the same password.
        self.assertIn("verify_password(bootstrap_pass, readback)", window)
        # On mismatch the helper emits step_fail, not step_ok.
        self.assertIn("round-trip verify_password FAILED", window)
        # vault_set return value must be checked (not just ignored).
        self.assertIn("write_ok = vault_set(", window)
        self.assertIn("if not write_ok:", window)

    def test_vault_set_returning_false_is_loud(self):
        """Simulate a vault_set that returns False (e.g. openssl binary
        missing, machine-id unreadable, disk full). The helper must log
        a step_fail rather than a silent step_ok."""
        from freq.modules import init_cmd
        from freq.core import fmt

        class Cfg:
            pass
        cfg = Cfg()
        cfg.conf_dir = "/tmp"
        cfg.vault_file = "/tmp/nonexistent-vault.enc"

        step_calls = {"ok": [], "fail": []}

        def fake_step_ok(msg):
            step_calls["ok"].append(msg)

        def fake_step_fail(msg):
            step_calls["fail"].append(msg)

        with mock.patch.object(fmt, "step_ok", side_effect=fake_step_ok), \
             mock.patch.object(fmt, "step_fail", side_effect=fake_step_fail), \
             mock.patch("freq.modules.vault.vault_set", return_value=False), \
             mock.patch("freq.modules.vault.vault_init", return_value=True), \
             mock.patch("freq.modules.vault.vault_get", return_value=""), \
             mock.patch("os.path.exists", return_value=False), \
             mock.patch("builtins.open", mock.mock_open(read_data="")):
            # Also patch the roles/users file reads — helper opens them
            # before doing the vault work.
            init_cmd._seed_headless_dashboard_auth(
                cfg, "alice", "somepassword", "freq-admin", verbose=True
            )

        fail_msgs = " ".join(step_calls["fail"])
        self.assertIn("vault_set returned False", fail_msgs,
                      "silent vault_set False must emit a loud step_fail")

    def test_round_trip_mismatch_surfaces_as_fail(self):
        """Simulate a successful vault_set but vault_get returning a
        hash that doesn't verify the password (corruption or wrong-
        entry write). The helper must emit step_fail."""
        from freq.modules import init_cmd
        from freq.core import fmt

        class Cfg:
            pass
        cfg = Cfg()
        cfg.conf_dir = "/tmp"
        cfg.vault_file = "/tmp/nonexistent-vault.enc"

        step_calls = {"ok": [], "fail": []}

        with mock.patch.object(fmt, "step_ok", side_effect=lambda m: step_calls["ok"].append(m)), \
             mock.patch.object(fmt, "step_fail", side_effect=lambda m: step_calls["fail"].append(m)), \
             mock.patch("freq.modules.vault.vault_set", return_value=True), \
             mock.patch("freq.modules.vault.vault_init", return_value=True), \
             mock.patch("freq.modules.vault.vault_get", return_value="corrupted-not-a-valid-hash"), \
             mock.patch("os.path.exists", return_value=False), \
             mock.patch("builtins.open", mock.mock_open(read_data="")):
            init_cmd._seed_headless_dashboard_auth(
                cfg, "alice", "correct-password", "freq-admin", verbose=True
            )

        fail_msgs = " ".join(step_calls["fail"])
        self.assertTrue(
            "round-trip verify_password FAILED" in fail_msgs
            or "vault_get returned empty" in fail_msgs,
            f"corrupted readback must surface; got fail msgs: {fail_msgs!r}"
        )


class TestDashboardPasswdCliRoundTripGuard(unittest.TestCase):
    """freq user dashboard-passwd must also round-trip the write so
    operators aren't told "password set" on a silent failure."""

    def test_source_pins_round_trip(self):
        src = USERS_PY.read_text()
        idx = src.find("def cmd_dashboard_passwd")
        self.assertGreater(idx, 0)
        window_end = src.find("\ndef ", idx + 50)
        window = src[idx:window_end]
        self.assertIn("write_ok = vault_set(", window)
        self.assertIn("readback = vault_get(", window)
        self.assertIn("verify_password", window)
        self.assertIn("Round-trip verify_password FAILED", window)
        self.assertIn(
            "Round-trip verify_password confirmed", window,
            "success path must advertise the round-trip confirmation so "
            "operators can see it fired"
        )

    def test_vault_set_false_returns_exit_1(self):
        """vault_set returning False must drive the CLI to exit 1."""
        import tempfile
        from freq.modules import users as users_mod

        with tempfile.TemporaryDirectory() as td:
            class Cfg:
                conf_dir = td
                vault_file = os.path.join(td, "vault.enc")
                ssh_service_account = "freq-admin"
                _toml_users = None
            cfg = Cfg()
            Path(os.path.join(td, "users.conf")).write_text("alice admin\n")
            pwfile = os.path.join(td, "pw.txt")
            Path(pwfile).write_text("correct-horse-battery-staple\n")
            args = mock.Mock(username="alice", file=pwfile)

            with mock.patch("freq.modules.vault.vault_init", return_value=True), \
                 mock.patch("freq.modules.vault.vault_set", return_value=False):
                rc = users_mod.cmd_dashboard_passwd(cfg, None, args)
            self.assertEqual(rc, 1, "vault_set=False must return rc=1")

    def test_readback_mismatch_returns_exit_1(self):
        """Successful write but corrupted readback must also exit 1 —
        the CLI must NOT report success if the stored hash doesn't
        verify the password just set."""
        import tempfile
        from freq.modules import users as users_mod

        with tempfile.TemporaryDirectory() as td:
            class Cfg:
                conf_dir = td
                vault_file = os.path.join(td, "vault.enc")
                ssh_service_account = "freq-admin"
                _toml_users = None
            cfg = Cfg()
            Path(os.path.join(td, "users.conf")).write_text("alice admin\n")
            pwfile = os.path.join(td, "pw.txt")
            Path(pwfile).write_text("correct-horse-battery-staple\n")
            args = mock.Mock(username="alice", file=pwfile)

            # vault_set says True but readback returns a hash that doesn't
            # verify the password — this is the exact class of bug Finn's
            # symptom would match if such a silent write ever happened.
            with mock.patch("freq.modules.vault.vault_init", return_value=True), \
                 mock.patch("freq.modules.vault.vault_set", return_value=True), \
                 mock.patch("freq.modules.vault.vault_get",
                            return_value="deadbeef$not-the-right-hash"):
                rc = users_mod.cmd_dashboard_passwd(cfg, None, args)
            self.assertEqual(rc, 1, "readback mismatch must return rc=1")


class TestHappyPathStillGreen(unittest.TestCase):
    """A successful real write + real readback + real verify_password
    still returns 0 and emits the round-trip-confirmed success message.
    This guards against the round-trip guard being too strict and
    breaking the normal path."""

    def test_cli_happy_path(self):
        import tempfile
        from freq.modules import users as users_mod
        from freq.api.auth import hash_password, verify_password

        with tempfile.TemporaryDirectory() as td:
            class Cfg:
                conf_dir = td
                vault_file = os.path.join(td, "vault.enc")
                ssh_service_account = "freq-admin"
                _toml_users = None
            cfg = Cfg()
            Path(os.path.join(td, "users.conf")).write_text("alice admin\n")
            pwfile = os.path.join(td, "pw.txt")
            Path(pwfile).write_text("correct-horse-battery-staple\n")
            args = mock.Mock(username="alice", file=pwfile)

            # Simulate a real write + real readback by computing the
            # hash and returning it from vault_get.
            real_hash_container = {}

            def fake_vault_set(cfg, host, key, value):
                real_hash_container["value"] = value
                return True

            def fake_vault_get(cfg, host, key):
                return real_hash_container.get("value", "")

            with mock.patch("freq.modules.vault.vault_init", return_value=True), \
                 mock.patch("freq.modules.vault.vault_set", side_effect=fake_vault_set), \
                 mock.patch("freq.modules.vault.vault_get", side_effect=fake_vault_get):
                rc = users_mod.cmd_dashboard_passwd(cfg, None, args)

            self.assertEqual(rc, 0, "happy path must return 0")
            # Confirm the hash that was stored verifies the password.
            stored = real_hash_container["value"]
            self.assertTrue(verify_password("correct-horse-battery-staple", stored))


if __name__ == "__main__":
    unittest.main()
