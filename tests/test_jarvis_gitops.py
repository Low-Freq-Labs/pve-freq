"""Tests for freq.jarvis.gitops — GitOps config sync."""
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from freq.jarvis.gitops import (
    GitOpsConfig, SyncState,
    load_gitops_config, load_state, save_state,
    init_repo, sync, apply_changes, get_diff, get_diff_full,
    get_log, rollback, should_sync, state_to_dict,
    _gitops_dir, _state_path, STATE_FILE, GITOPS_DIR_NAME,
)


class TestGitOpsConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_cfg_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_defaults(self):
        cfg = GitOpsConfig()
        self.assertEqual(cfg.repo_url, "")
        self.assertEqual(cfg.branch, "main")
        self.assertEqual(cfg.sync_interval, 300)
        self.assertFalse(cfg.auto_apply)
        self.assertFalse(cfg.enabled)

    def test_load_missing_file(self):
        cfg = load_gitops_config(self.tmpdir)
        self.assertFalse(cfg.enabled)

    def test_load_valid_toml(self):
        toml = b'[gitops]\nrepo_url = "git@github.com:org/cfg.git"\nbranch = "prod"\nsync_interval = 600\nauto_apply = true\n'
        with open(os.path.join(self.tmpdir, "freq.toml"), "wb") as f:
            f.write(toml)
        cfg = load_gitops_config(self.tmpdir)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.branch, "prod")
        self.assertEqual(cfg.sync_interval, 600)
        self.assertTrue(cfg.auto_apply)

    def test_load_no_gitops_section(self):
        toml = b'[server]\nport = 8888\n'
        with open(os.path.join(self.tmpdir, "freq.toml"), "wb") as f:
            f.write(toml)
        cfg = load_gitops_config(self.tmpdir)
        self.assertFalse(cfg.enabled)


class TestStateIO(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_state_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_load_missing_returns_default(self):
        state = load_state(self.tmpdir)
        self.assertEqual(state.status, "idle")
        self.assertEqual(state.last_sync, 0.0)

    def test_save_and_load_roundtrip(self):
        state = SyncState(last_sync=1000.0, last_commit="abc123", status="idle")
        save_state(self.tmpdir, state)
        loaded = load_state(self.tmpdir)
        self.assertEqual(loaded.last_commit, "abc123")
        self.assertEqual(loaded.last_sync, 1000.0)

    def test_load_corrupt_json(self):
        path = _state_path(self.tmpdir)
        with open(path, "w") as f:
            f.write("{{{corrupt")
        state = load_state(self.tmpdir)
        self.assertEqual(state.status, "idle")

    def test_state_to_dict(self):
        state = SyncState(last_sync=1000.5, last_commit="abc", status="idle", pending_changes=3)
        d = state_to_dict(state)
        self.assertEqual(d["last_sync"], 1000)
        self.assertEqual(d["pending_changes"], 3)


class TestInitRepo(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_init_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    @patch("freq.jarvis.gitops._run_git")
    def test_init_success(self, mock_git):
        mock_git.return_value = MagicMock(returncode=0)
        ok, msg = init_repo(self.tmpdir, "git@github.com:org/cfg.git")
        self.assertTrue(ok)
        self.assertIn("cloned", msg.lower())

    @patch("freq.jarvis.gitops._run_git")
    def test_init_fail(self, mock_git):
        mock_git.return_value = MagicMock(returncode=128, stderr="fatal: not a repo")
        ok, msg = init_repo(self.tmpdir, "bad-url")
        self.assertFalse(ok)

    def test_already_initialized(self):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        ok, msg = init_repo(self.tmpdir, "any-url")
        self.assertTrue(ok)
        self.assertIn("already", msg.lower())


class TestSync(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_sync_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_sync_no_repo(self):
        state = sync(self.tmpdir)
        self.assertEqual(state.status, "error")
        self.assertIn("not initialized", state.last_error.lower())

    @patch("freq.jarvis.gitops._run_git")
    def test_sync_no_changes(self, mock_git):
        # Setup .git dir
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)

        def side_effect(cwd, *args, **kwargs):
            cmd = args[0] if args else ""
            r = MagicMock()
            if cmd == "fetch":
                r.returncode = 0
            elif cmd == "rev-list":
                r.returncode = 0
                r.stdout = "0\n"
            elif cmd == "log":
                r.returncode = 0
                r.stdout = "abc123456789|initial commit\n"
            else:
                r.returncode = 0
                r.stdout = ""
            return r

        mock_git.side_effect = side_effect
        state = sync(self.tmpdir)
        self.assertEqual(state.status, "idle")
        self.assertEqual(state.pending_changes, 0)

    @patch("freq.jarvis.gitops._run_git")
    def test_sync_pending_changes(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)

        def side_effect(cwd, *args, **kwargs):
            cmd = args[0] if args else ""
            r = MagicMock()
            if cmd == "fetch":
                r.returncode = 0
            elif cmd == "rev-list":
                r.returncode = 0
                r.stdout = "3\n"
            elif cmd == "log":
                r.returncode = 0
                r.stdout = "abc123456789|update config\n"
            else:
                r.returncode = 0
                r.stdout = ""
            return r

        mock_git.side_effect = side_effect
        state = sync(self.tmpdir)
        self.assertEqual(state.status, "changes_pending")
        self.assertEqual(state.pending_changes, 3)

    @patch("freq.jarvis.gitops._run_git")
    def test_sync_fetch_error(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)

        mock_git.return_value = MagicMock(returncode=1, stderr="connection refused")
        state = sync(self.tmpdir)
        self.assertEqual(state.status, "error")


class TestApplyChanges(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_apply_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_apply_no_repo(self):
        ok, msg = apply_changes(self.tmpdir)
        self.assertFalse(ok)
        self.assertIn("not initialized", msg.lower())

    @patch("freq.jarvis.gitops._run_git")
    def test_apply_success(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)

        def side_effect(cwd, *args, **kwargs):
            cmd = args[0] if args else ""
            r = MagicMock()
            r.returncode = 0
            if cmd == "log":
                r.stdout = "abc123456789|applied changes\n"
            else:
                r.stdout = ""
            return r

        mock_git.side_effect = side_effect
        ok, msg = apply_changes(self.tmpdir)
        self.assertTrue(ok)

    @patch("freq.jarvis.gitops._run_git")
    def test_apply_fail(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(returncode=1, stderr="merge conflict")
        ok, msg = apply_changes(self.tmpdir)
        self.assertFalse(ok)


class TestDiff(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_diff_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_diff_no_repo(self):
        self.assertEqual(get_diff(self.tmpdir), "")
        self.assertEqual(get_diff_full(self.tmpdir), "")

    @patch("freq.jarvis.gitops._run_git")
    def test_diff_stat(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(returncode=0, stdout=" hosts.conf | 2 +-\n 1 file changed")
        diff = get_diff(self.tmpdir)
        self.assertIn("hosts.conf", diff)

    @patch("freq.jarvis.gitops._run_git")
    def test_diff_full_capped(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(returncode=0, stdout="x" * 10000)
        diff = get_diff_full(self.tmpdir)
        self.assertLessEqual(len(diff), 5000)


class TestLog(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_log_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_log_no_repo(self):
        self.assertEqual(get_log(self.tmpdir), [])

    @patch("freq.jarvis.gitops._run_git")
    def test_log_valid(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(
            returncode=0,
            stdout="abc123456789abcdef|update hosts|2026-03-25 12:00:00 -0500|Sonny\ndef456789012abcdef|initial|2026-03-24 12:00:00 -0500|Sonny\n",
        )
        commits = get_log(self.tmpdir)
        self.assertEqual(len(commits), 2)
        self.assertEqual(commits[0]["hash"], "abc123456789")
        self.assertEqual(commits[0]["author"], "Sonny")

    @patch("freq.jarvis.gitops._run_git")
    def test_log_empty(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(returncode=0, stdout="")
        self.assertEqual(get_log(self.tmpdir), [])


class TestRollback(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_rb_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_rollback_no_repo(self):
        ok, msg = rollback(self.tmpdir, "abc1234")
        self.assertFalse(ok)

    def test_rollback_invalid_hash(self):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        ok, msg = rollback(self.tmpdir, "not-a-hash!")
        self.assertFalse(ok)
        self.assertIn("Invalid", msg)

    @patch("freq.jarvis.gitops._run_git")
    def test_rollback_success(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(returncode=0)
        ok, msg = rollback(self.tmpdir, "abc1234def5678")
        self.assertTrue(ok)
        self.assertIn("abc1234def56", msg)

    @patch("freq.jarvis.gitops._run_git")
    def test_rollback_checkout_fail(self, mock_git):
        go_dir = _gitops_dir(self.tmpdir)
        os.makedirs(os.path.join(go_dir, ".git"), exist_ok=True)
        mock_git.return_value = MagicMock(returncode=1, stderr="error: pathspec")
        ok, msg = rollback(self.tmpdir, "abc1234")
        self.assertFalse(ok)


class TestShouldSync(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="freq_gitops_ss_test_")
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def test_no_state_should_sync(self):
        self.assertTrue(should_sync(self.tmpdir, interval=300))

    def test_recent_sync_should_not(self):
        state = SyncState(last_sync=time.time())
        save_state(self.tmpdir, state)
        self.assertFalse(should_sync(self.tmpdir, interval=300))

    def test_old_sync_should(self):
        state = SyncState(last_sync=time.time() - 600)
        save_state(self.tmpdir, state)
        self.assertTrue(should_sync(self.tmpdir, interval=300))
