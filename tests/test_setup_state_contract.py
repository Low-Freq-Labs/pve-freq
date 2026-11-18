"""Tests for setup state detection — must use resolved key path.

Bug: /api/setup/status reported ssh_key_exists=false and ssh_key_path
pointing to data/keys/freq_id_ed25519 (which doesn't exist) even though
the live resolved key was ~/.ssh/fleet_key (which works).

Root cause: _detect_ssh_key() didn't include fleet_key in search path
and didn't check readability. Fixed in earlier commits.

Contract:
- setup/status must use cfg.ssh_key_path (resolved by _detect_ssh_key)
- _detect_ssh_key resolves: ed25519 → fleet_key → rsa (first readable)
- ssh_key_exists reflects the RESOLVED key, not a hardcoded path
- ssh_key_readable checks os.access(R_OK)
"""
import errno
import os
import stat
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

FREQ_ROOT = Path(__file__).parent.parent


class TestSetupStatusUsesResolvedKey(unittest.TestCase):
    """Setup status handler must use cfg.ssh_key_path, not hardcoded path."""

    def test_serve_setup_uses_cfg_ssh_key_path(self):
        """_serve_setup_status must read from cfg.ssh_key_path."""
        path = FREQ_ROOT / "freq" / "modules" / "serve.py"
        with open(path) as f:
            content = f.read()
        # Find _serve_setup_status and verify it uses cfg.ssh_key_path
        self.assertIn("cfg.ssh_key_path", content)
        # Must NOT hardcode freq_id_ed25519 in setup status
        in_func = False
        for line in content.split("\n"):
            if "_serve_setup_status" in line and "def " in line:
                in_func = True
            if in_func:
                if "freq_id_ed25519" in line:
                    self.fail("_serve_setup_status hardcodes freq_id_ed25519")
                if line.strip().startswith("def ") and "_serve_setup_status" not in line:
                    break

    def test_setup_status_checks_readability(self):
        """Setup status must check key readability, not just existence."""
        path = FREQ_ROOT / "freq" / "modules" / "serve.py"
        with open(path) as f:
            content = f.read()
        self.assertIn("ssh_key_readable", content)
        self.assertIn("os.access(key_path, os.R_OK)", content)


class TestResolvedKeyIsLive(unittest.TestCase):
    """cfg.ssh_key_path must resolve to a live, readable key."""

    def test_resolved_key_exists(self):
        """The resolved SSH key must exist on disk."""
        from freq.core.config import load_config
        cfg = load_config()
        if cfg.ssh_key_path:
            self.assertTrue(os.path.isfile(cfg.ssh_key_path),
                            f"Resolved key must exist: {cfg.ssh_key_path}")

    def test_resolved_key_is_readable(self):
        """The resolved SSH key must be readable by current user."""
        from freq.core.config import load_config
        cfg = load_config()
        if cfg.ssh_key_path:
            self.assertTrue(os.access(cfg.ssh_key_path, os.R_OK),
                            f"Resolved key must be readable: {cfg.ssh_key_path}")

    def test_resolved_key_is_not_hardcoded_ed25519(self):
        """In this dev env, resolved key should be fleet_key (not freq_id_ed25519)."""
        from freq.core.config import load_config
        cfg = load_config()
        # freq_id_ed25519 doesn't exist in this checkout
        ed25519_path = os.path.join(cfg.key_dir, "freq_id_ed25519")
        if not os.path.isfile(ed25519_path):
            # If ed25519 doesn't exist, resolved key should NOT point to it
            self.assertNotEqual(cfg.ssh_key_path, ed25519_path,
                                "Resolved key must not point to non-existent ed25519")


class TestUnreadableSetupStateFailsClosed(unittest.TestCase):
    def test_permission_error_is_not_converted_into_cleanup_mutation(self):
        from types import SimpleNamespace

        from freq.core.setup_state import load_setup_state

        cfg = SimpleNamespace(data_dir="/nonexistent/test-runtime")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                load_setup_state(cfg)
        self._case_init_control_arbitration_is_atomic_and_fail_closed()

    def _case_init_control_arbitration_is_atomic_and_fail_closed(self):
        from types import SimpleNamespace

        from freq.core import setup_state
        from freq.core.setup_state import (
            _capture_init_control_topology,
            _claim_init_point_of_no_return,
            _init_control_path,
            _prepare_init_control_dir,
            _request_init_cancel,
            _rollback_init_control_topology,
            _transition_init_control,
        )
        from freq.core.types import _InitControlState

        with tempfile.TemporaryDirectory(prefix="freq-init-control-owner-") as root:
            data_dir = os.path.join(root, "data")
            cfg = SimpleNamespace(data_dir=data_dir)
            cancel_id = "0" * 32
            cancel_path = _init_control_path(cfg, cancel_id)
            self.assertEqual(
                cancel_path,
                os.path.join(data_dir, "init-control", f"{cancel_id}.state"),
            )
            self.assertFalse(os.path.exists(data_dir))
            self.assertEqual(
                _capture_init_control_topology(cfg),
                {
                    "data_dir_existed": False,
                    "control_dir_existed": False,
                },
            )
            with patch.object(
                setup_state.os, "fsync", wraps=setup_state.os.fsync
            ) as prepared_sync:
                self.assertEqual(
                    _prepare_init_control_dir(cfg),
                    os.path.dirname(cancel_path),
                )
            self.assertEqual(prepared_sync.call_count, 3)
            self.assertTrue(os.path.isdir(data_dir))
            self.assertTrue(os.path.isdir(os.path.dirname(cancel_path)))
            self.assertEqual(
                os.stat(os.path.dirname(cancel_path)).st_mode & 0o777,
                0o700,
            )
            with patch.object(
                setup_state.os, "fsync", wraps=setup_state.os.fsync
            ) as repeated_sync:
                self.assertEqual(
                    _prepare_init_control_dir(cfg),
                    os.path.dirname(cancel_path),
                )
            self.assertEqual(repeated_sync.call_count, 3)
            self.assertEqual(
                _capture_init_control_topology(cfg),
                {
                    "data_dir_existed": True,
                    "control_dir_existed": True,
                },
            )

            rollback_new_cfg = SimpleNamespace(
                data_dir=os.path.join(root, "rollback-new-data")
            )
            rollback_new_topology = _capture_init_control_topology(rollback_new_cfg)
            _prepare_init_control_dir(rollback_new_cfg)
            rollback_events = []
            real_rollback_rmdir = setup_state.os.rmdir
            real_rollback_fsync = setup_state.os.fsync

            def tracked_rollback_rmdir(path, *, dir_fd=None):
                rollback_events.append(("rmdir", path, dir_fd))
                return real_rollback_rmdir(path, dir_fd=dir_fd)

            def tracked_rollback_fsync(fd):
                rollback_events.append(("fsync", fd))
                return real_rollback_fsync(fd)

            with patch.object(
                setup_state.os, "rmdir", side_effect=tracked_rollback_rmdir
            ), patch.object(
                setup_state.os, "fsync", side_effect=tracked_rollback_fsync
            ):
                _rollback_init_control_topology(
                    rollback_new_cfg,
                    rollback_new_topology,
                )
            self.assertEqual(
                [event[0] for event in rollback_events],
                ["rmdir", "fsync", "rmdir", "fsync"],
            )
            self.assertEqual(rollback_events[0][1], "init-control")
            self.assertEqual(rollback_events[1][1], rollback_events[0][2])
            self.assertEqual(
                rollback_events[2][1],
                os.path.basename(rollback_new_cfg.data_dir),
            )
            self.assertEqual(rollback_events[3][1], rollback_events[2][2])
            self.assertFalse(os.path.lexists(rollback_new_cfg.data_dir))

            rollback_data_cfg = SimpleNamespace(
                data_dir=os.path.join(root, "rollback-existing-data")
            )
            os.mkdir(rollback_data_cfg.data_dir)
            retained_path = os.path.join(rollback_data_cfg.data_dir, "retained")
            with open(retained_path, "wb") as retained_file:
                retained_file.write(b"accepted\n")
            rollback_data_topology = _capture_init_control_topology(rollback_data_cfg)
            _prepare_init_control_dir(rollback_data_cfg)
            _rollback_init_control_topology(
                rollback_data_cfg,
                rollback_data_topology,
            )
            self.assertTrue(os.path.isdir(rollback_data_cfg.data_dir))
            self.assertFalse(
                os.path.lexists(
                    os.path.join(rollback_data_cfg.data_dir, "init-control")
                )
            )
            with open(retained_path, "rb") as retained_file:
                self.assertEqual(retained_file.read(), b"accepted\n")

            rollback_new_nonempty_cfg = SimpleNamespace(
                data_dir=os.path.join(root, "rollback-new-nonempty-data")
            )
            rollback_new_nonempty_topology = _capture_init_control_topology(
                rollback_new_nonempty_cfg
            )
            _prepare_init_control_dir(rollback_new_nonempty_cfg)
            unexpected_data_path = os.path.join(
                rollback_new_nonempty_cfg.data_dir,
                "unexpected",
            )
            with open(unexpected_data_path, "wb") as unexpected_data_file:
                unexpected_data_file.write(b"retain data\n")
            rollback_new_nonempty_events = []
            rollback_new_nonempty_errors = []

            def tracked_new_nonempty_rmdir(path, *, dir_fd=None):
                rollback_new_nonempty_events.append(("rmdir", path, dir_fd))
                try:
                    return real_rollback_rmdir(path, dir_fd=dir_fd)
                except OSError as error:
                    rollback_new_nonempty_errors.append(error)
                    raise

            def tracked_new_nonempty_fsync(fd):
                rollback_new_nonempty_events.append(("fsync", fd))
                return real_rollback_fsync(fd)

            with patch.object(
                setup_state.os,
                "rmdir",
                side_effect=tracked_new_nonempty_rmdir,
            ), patch.object(
                setup_state.os,
                "fsync",
                side_effect=tracked_new_nonempty_fsync,
            ):
                with self.assertRaises(OSError) as raised:
                    _rollback_init_control_topology(
                        rollback_new_nonempty_cfg,
                        rollback_new_nonempty_topology,
                    )
            self.assertEqual(len(rollback_new_nonempty_errors), 1)
            self.assertIs(
                raised.exception,
                rollback_new_nonempty_errors[0],
            )
            self.assertEqual(raised.exception.errno, errno.ENOTEMPTY)
            self.assertEqual(
                [event[0] for event in rollback_new_nonempty_events],
                ["rmdir", "fsync", "rmdir"],
            )
            self.assertEqual(
                rollback_new_nonempty_events[0][1],
                "init-control",
            )
            self.assertEqual(
                rollback_new_nonempty_events[1][1],
                rollback_new_nonempty_events[0][2],
            )
            self.assertEqual(
                rollback_new_nonempty_events[2][1],
                os.path.basename(rollback_new_nonempty_cfg.data_dir),
            )
            self.assertFalse(
                os.path.lexists(
                    os.path.join(
                        rollback_new_nonempty_cfg.data_dir,
                        "init-control",
                    )
                )
            )
            self.assertTrue(os.path.isdir(rollback_new_nonempty_cfg.data_dir))
            with open(unexpected_data_path, "rb") as unexpected_data_file:
                self.assertEqual(unexpected_data_file.read(), b"retain data\n")

            rollback_existing_cfg = SimpleNamespace(
                data_dir=os.path.join(root, "rollback-existing-control")
            )
            _prepare_init_control_dir(rollback_existing_cfg)
            rollback_existing_topology = _capture_init_control_topology(
                rollback_existing_cfg
            )
            _rollback_init_control_topology(
                rollback_existing_cfg,
                rollback_existing_topology,
            )
            self.assertTrue(
                os.path.isdir(
                    os.path.join(rollback_existing_cfg.data_dir, "init-control")
                )
            )

            rollback_nonempty_cfg = SimpleNamespace(
                data_dir=os.path.join(root, "rollback-nonempty-data")
            )
            rollback_nonempty_topology = _capture_init_control_topology(
                rollback_nonempty_cfg
            )
            rollback_nonempty_dir = _prepare_init_control_dir(rollback_nonempty_cfg)
            unexpected_path = os.path.join(rollback_nonempty_dir, "unexpected")
            with open(unexpected_path, "wb") as unexpected_file:
                unexpected_file.write(b"retain\n")
            with self.assertRaises(OSError):
                _rollback_init_control_topology(
                    rollback_nonempty_cfg,
                    rollback_nonempty_topology,
                )
            with open(unexpected_path, "rb") as unexpected_file:
                self.assertEqual(unexpected_file.read(), b"retain\n")

            rollback_swapped_cfg = SimpleNamespace(
                data_dir=os.path.join(root, "rollback-swapped-data")
            )
            rollback_swapped_topology = _capture_init_control_topology(
                rollback_swapped_cfg
            )
            rollback_swapped_dir = _prepare_init_control_dir(rollback_swapped_cfg)
            rollback_swapped_real = f"{rollback_swapped_dir}-real"
            os.rename(rollback_swapped_dir, rollback_swapped_real)
            os.symlink(rollback_swapped_real, rollback_swapped_dir)
            with self.assertRaises(OSError):
                _rollback_init_control_topology(
                    rollback_swapped_cfg,
                    rollback_swapped_topology,
                )
            self.assertTrue(os.path.islink(rollback_swapped_dir))
            self.assertTrue(os.path.isdir(rollback_swapped_real))

            for invalid_topology in (
                None,
                {},
                {"data_dir_existed": False},
                {"data_dir_existed": 0, "control_dir_existed": False},
            ):
                with self.assertRaises(TypeError):
                    _rollback_init_control_topology(cfg, invalid_topology)
            with self.assertRaises(ValueError):
                _rollback_init_control_topology(
                    cfg,
                    {
                        "data_dir_existed": False,
                        "control_dir_existed": True,
                    },
                )
            with patch.object(
                setup_state.fcntl, "flock", wraps=setup_state.fcntl.flock
            ) as locked, patch.object(
                setup_state.os, "fsync", wraps=setup_state.os.fsync
            ) as synced:
                self.assertIs(
                    _request_init_cancel(cfg, cancel_id),
                    _InitControlState.CANCEL_REQUESTED,
                )
                self.assertIs(
                    _request_init_cancel(cfg, cancel_id),
                    _InitControlState.CANCEL_REQUESTED,
                )
                self.assertIs(
                    _claim_init_point_of_no_return(cfg, cancel_id),
                    _InitControlState.CANCEL_REQUESTED,
                )
            self.assertEqual(locked.call_count, 3)
            self.assertTrue(
                all(
                    call.args[1] == setup_state.fcntl.LOCK_EX
                    for call in locked.call_args_list
                )
            )
            self.assertEqual(synced.call_count, 2)
            with open(cancel_path, "rb") as control_file:
                self.assertEqual(control_file.read(), b"cancel_requested\n")
            self.assertEqual(os.stat(cancel_path).st_mode & 0o777, 0o600)

            ponr_id = "1" * 32
            ponr_path = _init_control_path(cfg, ponr_id)
            self.assertIs(
                _claim_init_point_of_no_return(cfg, ponr_id),
                _InitControlState.POINT_OF_NO_RETURN,
            )
            self.assertIs(
                _claim_init_point_of_no_return(cfg, ponr_id),
                _InitControlState.POINT_OF_NO_RETURN,
            )
            self.assertIs(
                _request_init_cancel(cfg, ponr_id),
                _InitControlState.POINT_OF_NO_RETURN,
            )
            with open(ponr_path, "rb") as control_file:
                self.assertEqual(control_file.read(), b"point_of_no_return\n")

            delayed_id = "2" * 32
            delayed_path = _init_control_path(cfg, delayed_id)
            directory_sync_started = threading.Event()
            allow_directory_sync = threading.Event()
            directory_sync_completed = threading.Event()
            contender_lock_attempted = threading.Event()
            contender_lock_acquired = threading.Event()
            contender_thread = [None]
            sync_order = []
            real_fsync = setup_state.os.fsync
            real_flock = setup_state.fcntl.flock

            def delayed_fsync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    directory_sync_started.set()
                    if not allow_directory_sync.wait(timeout=5):
                        raise TimeoutError("directory fsync release was not signaled")
                    real_fsync(fd)
                    sync_order.append("directory")
                    directory_sync_completed.set()
                    return
                real_fsync(fd)
                sync_order.append("file")

            def observed_flock(fd, operation):
                is_contender = threading.get_ident() == contender_thread[0]
                if is_contender:
                    contender_lock_attempted.set()
                result = real_flock(fd, operation)
                if is_contender:
                    contender_lock_acquired.set()
                return result

            def request_ponr_as_contender():
                contender_thread[0] = threading.get_ident()
                return _claim_init_point_of_no_return(cfg, delayed_id)

            with patch.object(
                setup_state.os, "fsync", side_effect=delayed_fsync
            ), patch.object(
                setup_state.fcntl, "flock", side_effect=observed_flock
            ), ThreadPoolExecutor(max_workers=2) as pool:
                creator = pool.submit(_request_init_cancel, cfg, delayed_id)
                self.assertTrue(directory_sync_started.wait(timeout=5))
                contender = pool.submit(request_ponr_as_contender)
                self.assertTrue(contender_lock_attempted.wait(timeout=5))
                try:
                    self.assertFalse(contender_lock_acquired.wait(timeout=0.25))
                    self.assertFalse(directory_sync_completed.is_set())
                    self.assertFalse(creator.done())
                    self.assertFalse(contender.done())
                finally:
                    allow_directory_sync.set()
                delayed_outcomes = {creator.result(), contender.result()}
            self.assertTrue(directory_sync_completed.is_set())
            self.assertTrue(contender_lock_acquired.is_set())
            self.assertEqual(sync_order, ["directory", "file"])
            self.assertEqual(delayed_outcomes, {_InitControlState.CANCEL_REQUESTED})
            with open(delayed_path, "rb") as control_file:
                self.assertEqual(control_file.read(), b"cancel_requested\n")

            for index in range(24):
                race_id = f"{index + 3:032x}"
                race_path = _init_control_path(cfg, race_id)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    cancel = pool.submit(_request_init_cancel, cfg, race_id)
                    ponr = pool.submit(
                        _claim_init_point_of_no_return,
                        cfg,
                        race_id,
                    )
                    outcomes = {cancel.result(), ponr.result()}
                self.assertEqual(len(outcomes), 1)
                final_state = outcomes.pop()
                with open(race_path, "rb") as control_file:
                    self.assertEqual(
                        control_file.read(),
                        {
                            _InitControlState.CANCEL_REQUESTED: b"cancel_requested\n",
                            _InitControlState.POINT_OF_NO_RETURN: b"point_of_no_return\n",
                        }[final_state],
                    )

            malformed_id = "a" * 32
            malformed_path = _init_control_path(cfg, malformed_id)
            with open(malformed_path, "wb") as control_file:
                control_file.write(b"cancel_requested\npoint_of_no_return\n")
            for transition in (_request_init_cancel, _claim_init_point_of_no_return):
                with self.assertRaisesRegex(ValueError, "invalid init control state"):
                    transition(cfg, malformed_id)
                with open(malformed_path, "rb") as control_file:
                    self.assertEqual(
                        control_file.read(),
                        b"cancel_requested\npoint_of_no_return\n",
                    )

            symlink_id = "b" * 32
            symlink_path = _init_control_path(cfg, symlink_id)
            os.symlink(cancel_path, symlink_path)
            for transition in (_request_init_cancel, _claim_init_point_of_no_return):
                with self.assertRaises(OSError):
                    transition(cfg, symlink_id)

            hardlink_id = "c" * 32
            hardlink_path = _init_control_path(cfg, hardlink_id)
            os.link(cancel_path, hardlink_path)
            for transition in (_request_init_cancel, _claim_init_point_of_no_return):
                with self.assertRaises(OSError):
                    transition(cfg, hardlink_id)

            for invalid_cfg in (
                None,
                "arbitrary-absolute-path-is-not-an-api",
                SimpleNamespace(data_dir=None),
                SimpleNamespace(data_dir=""),
                SimpleNamespace(data_dir="relative"),
                SimpleNamespace(data_dir=" /absolute"),
                SimpleNamespace(data_dir="/"),
                SimpleNamespace(data_dir="//"),
                SimpleNamespace(data_dir="//tmp"),
                SimpleNamespace(data_dir=f"{data_dir}/"),
            ):
                with self.assertRaises(ValueError):
                    _request_init_cancel(invalid_cfg, cancel_id)
            for invalid_run_id in (
                None,
                "",
                "0" * 31,
                "0" * 33,
                "A" * 32,
                "g" * 32,
                "../" + "0" * 29,
            ):
                with self.assertRaises(ValueError):
                    _request_init_cancel(cfg, invalid_run_id)
            for invalid_state in (
                _InitControlState.PRE_PONR,
                "cancel_requested",
                None,
            ):
                with self.assertRaisesRegex(TypeError, "unsupported init control transition"):
                    _transition_init_control(cfg, cancel_id, invalid_state)

            symlink_target = os.path.join(root, "symlink-target")
            os.mkdir(symlink_target)
            symlink_data = os.path.join(root, "symlink-data")
            os.symlink(symlink_target, symlink_data)
            with self.assertRaises(OSError):
                _prepare_init_control_dir(SimpleNamespace(data_dir=symlink_data))
            self.assertFalse(os.path.exists(os.path.join(symlink_target, "init-control")))

            intermediate_target = os.path.join(root, "intermediate-target")
            os.mkdir(intermediate_target)
            intermediate_link = os.path.join(root, "intermediate-link")
            os.symlink(intermediate_target, intermediate_link)
            with self.assertRaises(OSError):
                _prepare_init_control_dir(
                    SimpleNamespace(data_dir=os.path.join(intermediate_link, "data"))
                )
            self.assertFalse(os.path.exists(os.path.join(intermediate_target, "data")))

            linked_control_data = os.path.join(root, "linked-control-data")
            linked_control_target = os.path.join(root, "linked-control-target")
            os.mkdir(linked_control_data)
            os.mkdir(linked_control_target)
            os.symlink(
                linked_control_target,
                os.path.join(linked_control_data, "init-control"),
            )
            with self.assertRaises(OSError):
                _prepare_init_control_dir(
                    SimpleNamespace(data_dir=linked_control_data)
                )

            file_control_data = os.path.join(root, "file-control-data")
            os.mkdir(file_control_data)
            with open(os.path.join(file_control_data, "init-control"), "wb"):
                pass
            with self.assertRaises(OSError):
                _prepare_init_control_dir(SimpleNamespace(data_dir=file_control_data))

            swapped_data = os.path.join(root, "swapped-data")
            swapped_cfg = SimpleNamespace(data_dir=swapped_data)
            _prepare_init_control_dir(swapped_cfg)
            swapped_data_real = os.path.join(root, "swapped-data-real")
            os.rename(swapped_data, swapped_data_real)
            os.symlink(swapped_data_real, swapped_data)
            swapped_id = "d" * 32
            with self.assertRaises(OSError):
                _request_init_cancel(swapped_cfg, swapped_id)
            self.assertFalse(
                os.path.exists(
                    os.path.join(swapped_data_real, "init-control", f"{swapped_id}.state")
                )
            )

            swapped_control_data = os.path.join(root, "swapped-control-data")
            swapped_control_cfg = SimpleNamespace(data_dir=swapped_control_data)
            swapped_control_dir = _prepare_init_control_dir(swapped_control_cfg)
            swapped_control_real = os.path.join(root, "swapped-control-real")
            os.rename(swapped_control_dir, swapped_control_real)
            os.symlink(swapped_control_real, swapped_control_dir)
            swapped_control_id = "e" * 32
            with self.assertRaises(OSError):
                _request_init_cancel(swapped_control_cfg, swapped_control_id)
            self.assertFalse(
                os.path.exists(
                    os.path.join(swapped_control_real, f"{swapped_control_id}.state")
                )
            )

            durability_parent = os.path.join(root, "durability-parent")
            os.mkdir(durability_parent)
            durability_cfg = SimpleNamespace(
                data_dir=os.path.join(durability_parent, "data")
            )
            durability_parent_stat = os.stat(durability_parent)
            parent_sync_started = {
                "creator": threading.Event(),
                "contender": threading.Event(),
            }
            allow_parent_sync = {
                "creator": threading.Event(),
                "contender": threading.Event(),
            }
            parent_sync_completed = {
                "creator": threading.Event(),
                "contender": threading.Event(),
            }
            thread_roles = {}
            real_prepare_fsync = setup_state.os.fsync

            def delayed_data_parent_fsync(fd):
                opened = os.fstat(fd)
                role = thread_roles.get(threading.get_ident())
                is_data_parent = (
                    opened.st_dev == durability_parent_stat.st_dev
                    and opened.st_ino == durability_parent_stat.st_ino
                )
                if role and is_data_parent:
                    parent_sync_started[role].set()
                    if not allow_parent_sync[role].wait(timeout=5):
                        raise TimeoutError(f"{role} data-parent fsync was not released")
                    real_prepare_fsync(fd)
                    parent_sync_completed[role].set()
                    return
                real_prepare_fsync(fd)

            def prepare_as(role):
                thread_roles[threading.get_ident()] = role
                return _prepare_init_control_dir(durability_cfg)

            with patch.object(
                setup_state.os,
                "fsync",
                side_effect=delayed_data_parent_fsync,
            ), ThreadPoolExecutor(max_workers=2) as pool:
                creator_prepare = pool.submit(prepare_as, "creator")
                self.assertTrue(parent_sync_started["creator"].wait(timeout=5))
                contender_prepare = pool.submit(prepare_as, "contender")
                self.assertTrue(parent_sync_started["contender"].wait(timeout=5))
                try:
                    self.assertFalse(creator_prepare.done())
                    self.assertFalse(contender_prepare.done())
                    self.assertFalse(parent_sync_completed["creator"].is_set())
                    self.assertFalse(parent_sync_completed["contender"].is_set())
                    allow_parent_sync["contender"].set()
                    contender_path = contender_prepare.result(timeout=5)
                    self.assertTrue(parent_sync_completed["contender"].is_set())
                    self.assertFalse(creator_prepare.done())
                finally:
                    allow_parent_sync["creator"].set()
                    allow_parent_sync["contender"].set()
                creator_path = creator_prepare.result(timeout=5)
            self.assertTrue(parent_sync_completed["creator"].is_set())
            self.assertEqual(creator_path, contender_path)
            self.assertEqual(
                os.stat(creator_path).st_mode & 0o777,
                0o700,
            )

            failure_parent = os.path.join(root, "failure-parent")
            os.mkdir(failure_parent)
            failure_data = os.path.join(failure_parent, "data")
            os.mkdir(failure_data)
            failure_cfg = SimpleNamespace(data_dir=failure_data)
            failure_parent_stat = os.stat(failure_parent)
            forced_error = OSError(errno.EIO, "forced data-parent fsync failure")
            opened_directory_fds = []
            real_prepare_open = setup_state.os.open

            def tracking_directory_open(*args, **kwargs):
                fd = real_prepare_open(*args, **kwargs)
                opened_directory_fds.append(fd)
                return fd

            def failing_data_parent_fsync(fd):
                opened = os.fstat(fd)
                if (
                    opened.st_dev == failure_parent_stat.st_dev
                    and opened.st_ino == failure_parent_stat.st_ino
                ):
                    raise forced_error
                real_prepare_fsync(fd)

            with patch.object(
                setup_state.os,
                "open",
                side_effect=tracking_directory_open,
            ), patch.object(
                setup_state.os,
                "fsync",
                side_effect=failing_data_parent_fsync,
            ):
                with self.assertRaises(OSError) as raised:
                    _prepare_init_control_dir(failure_cfg)
            self.assertIs(raised.exception, forced_error)
            self.assertGreater(len(opened_directory_fds), 1)
            for opened_fd in opened_directory_fds:
                with self.assertRaises(OSError) as closed:
                    os.fstat(opened_fd)
                self.assertEqual(closed.exception.errno, errno.EBADF)

            concurrent_cfg = SimpleNamespace(
                data_dir=os.path.join(root, "concurrent-data")
            )
            with ThreadPoolExecutor(max_workers=8) as pool:
                prepared = list(
                    pool.map(
                        _prepare_init_control_dir,
                        [concurrent_cfg] * 16,
                    )
                )
            self.assertEqual(
                set(prepared),
                {os.path.join(concurrent_cfg.data_dir, "init-control")},
            )
            self.assertEqual(
                os.stat(prepared[0]).st_mode & 0o777,
                0o700,
            )


if __name__ == "__main__":
    unittest.main()
