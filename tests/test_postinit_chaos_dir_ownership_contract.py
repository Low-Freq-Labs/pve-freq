""" regression contract.

The actual root-cause fix for the chaos log 500 Finn saw on 5005 (T-6
of the red-team pass only caught the symptom with a PermissionError
fallback). Two concrete contracts pinned:

  1. Post-init ownership helper exists and pre-creates every canonical
     data/ subdir the runtime touches — chaos, cache, backups, log,
     jarvis, jarvis/agents, observe, state, snapshots, federation.
     POST_INIT_DATA_SUBDIRS is the authoritative list.

  2. Both interactive init (_init_cmd around line 706) AND headless
     init (_init_headless around line 7181) call
     _ensure_post_init_data_ownership. Headless was the drift path
     — it used to skip the recursive chown of data_dir that the
     interactive path already did, so data/ stayed owned by whatever
     user created it first and never got re-chown'd when the service
     account changed across installs.

  3. The helper is idempotent on subsequent calls (re-running init
     must not fail or leak perms).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
INIT_CMD_PY = REPO / "freq" / "modules" / "init_cmd.py"


class TestPostInitSubdirList(unittest.TestCase):
    """The canonical POST_INIT_DATA_SUBDIRS list must include every
    data subdir the runtime writes into. Dropping a subdir would
    silently reopen the PermissionError fallback path."""

    def test_chaos_in_post_init_subdirs(self):
        from freq.modules import init_cmd
        self.assertIn("chaos", init_cmd.POST_INIT_DATA_SUBDIRS,
                      "chaos MUST be in the post-init subdir list — "
                      "this is the exact dir Finn's V token targets")

    def test_all_runtime_subdirs_covered(self):
        """Every subdir literal that lives under cfg.data_dir in the
        runtime modules must be in the list."""
        from freq.modules import init_cmd
        expected = {"cache", "chaos", "backups", "log", "jarvis", "observe", "state"}
        subdirs = set(init_cmd.POST_INIT_DATA_SUBDIRS)
        missing = expected - subdirs
        self.assertFalse(
            missing,
            f"POST_INIT_DATA_SUBDIRS is missing runtime subdir(s) {missing} — "
            f"add them or the first dashboard os.makedirs call will fail"
        )


class TestEnsurePostInitDataOwnership(unittest.TestCase):
    """Behavioral pin for the _ensure_post_init_data_ownership helper."""

    def _make_fake_cfg(self, data_dir):
        class Cfg:
            pass
        cfg = Cfg()
        cfg.data_dir = data_dir
        return cfg

    def _fake_pwnam(self, uid=9999, gid=9999):
        class PwEntry:
            pw_uid = uid
            pw_gid = gid
        return PwEntry()

    def test_creates_every_canonical_subdir(self):
        from freq.modules import init_cmd
        with tempfile.TemporaryDirectory() as td:
            cfg = self._make_fake_cfg(td)
            # Don't attempt a real chown or pwd.getpwnam in the test — patch.
            def fake_chown_run(*a, **kw):
                return (0, "", "")
            with mock.patch.object(init_cmd, "_run", side_effect=fake_chown_run), \
                 mock.patch("pwd.getpwnam", return_value=self._fake_pwnam()):
                ok = init_cmd._ensure_post_init_data_ownership(cfg, "testadmin")
            self.assertTrue(ok)
            for sub in init_cmd.POST_INIT_DATA_SUBDIRS:
                self.assertTrue(
                    os.path.isdir(os.path.join(td, sub)),
                    f"{sub} must be pre-created by the helper"
                )

    def test_idempotent_on_rerun(self):
        """Calling the helper twice must not fail even if subdirs
        already exist."""
        from freq.modules import init_cmd
        with tempfile.TemporaryDirectory() as td:
            cfg = self._make_fake_cfg(td)
            # Pre-create one of the subdirs to simulate a re-run.
            os.makedirs(os.path.join(td, "chaos"), exist_ok=True)
            os.makedirs(os.path.join(td, "cache"), exist_ok=True)

            def fake_chown_run(*a, **kw):
                return (0, "", "")
            with mock.patch.object(init_cmd, "_run", side_effect=fake_chown_run), \
                 mock.patch("pwd.getpwnam", return_value=self._fake_pwnam()):
                ok1 = init_cmd._ensure_post_init_data_ownership(cfg, "testadmin")
                ok2 = init_cmd._ensure_post_init_data_ownership(cfg, "testadmin")
            self.assertTrue(ok1)
            self.assertTrue(ok2)

    def test_missing_svc_user_returns_false(self):
        """If the target service account doesn't exist on the host
        (typo in init args, stale freq.toml), the helper refuses and
        doesn't crash init — caller logs a warning."""
        from freq.modules import init_cmd
        with tempfile.TemporaryDirectory() as td:
            cfg = self._make_fake_cfg(td)
            with mock.patch("pwd.getpwnam", side_effect=KeyError("nosuchuser")):
                ok = init_cmd._ensure_post_init_data_ownership(cfg, "nosuchuser")
            self.assertFalse(ok)

    def test_python_fallback_when_chown_binary_fails(self):
        """If `chown -R` returns non-zero (missing binary, busybox
        edge cases), the helper falls back to a Python walk and
        still chowns the tree."""
        from freq.modules import init_cmd
        chown_calls = {"n": 0}

        def fake_run(cmd, timeout=30):
            # First call is the chown -R attempt — simulate failure.
            chown_calls["n"] += 1
            return (1, "", "chown: command not found")

        with tempfile.TemporaryDirectory() as td:
            cfg = self._make_fake_cfg(td)
            os_chown_count = {"n": 0}

            real_chown = os.chown

            def counting_chown(path, uid, gid):
                os_chown_count["n"] += 1
                # Don't actually chown (may fail in CI sandbox without root).
                return None

            with mock.patch.object(init_cmd, "_run", side_effect=fake_run), \
                 mock.patch("pwd.getpwnam", return_value=self._fake_pwnam()), \
                 mock.patch("os.chown", side_effect=counting_chown):
                ok = init_cmd._ensure_post_init_data_ownership(cfg, "testadmin")

            self.assertTrue(ok)
            self.assertEqual(chown_calls["n"], 1, "chown -R must be tried once")
            # At least the data_dir itself + every subdir got os.chown'd via fallback.
            self.assertGreaterEqual(
                os_chown_count["n"], 1 + len(init_cmd.POST_INIT_DATA_SUBDIRS),
                "fallback Python walk must chown every pre-created subdir"
            )


class TestInitCallSites(unittest.TestCase):
    """Both init entry points must invoke the helper."""

    def test_interactive_init_calls_helper(self):
        src = INIT_CMD_PY.read_text()
        # Find the interactive init's post-summary block.
        idx = src.find("Fix post-init ownership")
        self.assertGreater(idx, 0, "interactive init post-init comment must exist")
        window = src[idx:idx + 1500]
        self.assertIn("_ensure_post_init_data_ownership(cfg, svc_name)", window)

    def test_headless_init_calls_helper(self):
        src = INIT_CMD_PY.read_text()
        idx = src.find("Post-init permissions")
        self.assertGreater(idx, 0, "headless init post-init comment must exist")
        window = src[idx:idx + 1500]
        self.assertIn("_ensure_post_init_data_ownership(cfg, ctx[\"svc_name\"])", window)


class TestChaosLogStillHasDefensiveCatch(unittest.TestCase):
    """The T-6 PermissionError catch in handle_chaos_log stays as a
    safety net. V fixes the ROOT cause (the dir contract) but the
    catch is still correct behavior during the transient window
    between a fresh init and the post-init chown landing — the
    dashboard may start probing before init fully completes, and
    an honest empty response beats a 500."""

    def test_t6_defensive_catch_preserved(self):
        auto_py = REPO / "freq" / "api" / "auto.py"
        src = auto_py.read_text()
        idx = src.find("handle_chaos_log")
        region_end = src.find("load_experiment_log(cfg.data_dir, count)", idx)
        window = src[idx:region_end + 300]
        self.assertIn("PermissionError", window,
                      "T-6 defensive catch must stay — V fixes the root "
                      "cause but the catch is still the right safety net")
        self.assertIn("FileNotFoundError", window)


if __name__ == "__main__":
    unittest.main()
