"""Behavior and dependency contracts for shared iDRAC session pacing."""

import subprocess
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from freq.api import fleet, hw, terminal
from freq.modules import serve
from freq.services import idrac_session
from tests.case_matrix import run_case_matrix


class IdracSessionServiceTests(unittest.TestCase):
    def setUp(self):
        self._last = idrac_session._idrac_last_session_at

    def tearDown(self):
        idrac_session._idrac_last_session_at = self._last

    def _case_exact_consumer_identities(self):
        self.assertIs(serve.IDRAC_SESSION_LOCK, idrac_session.IDRAC_SESSION_LOCK)
        self.assertEqual(serve.IDRAC_SESSION_GAP_SECONDS, idrac_session.IDRAC_SESSION_GAP_SECONDS)
        self.assertIs(serve._run_idrac_session, idrac_session._run_idrac_session)
        self.assertIs(serve._run_idrac_subprocess, idrac_session._run_idrac_subprocess)
        self.assertIs(hw._run_idrac_session, idrac_session._run_idrac_session)
        self.assertIs(terminal._run_idrac_session, idrac_session._run_idrac_session)
        self.assertIs(fleet._run_idrac_session, idrac_session._run_idrac_session)

    def _case_waits_exact_remainder_holds_lock_and_returns_identity(self):
        result = object()
        idrac_session._idrac_last_session_at = 9.5

        def operation():
            self.assertFalse(idrac_session.IDRAC_SESSION_LOCK.acquire(blocking=False))
            return result

        with (
            patch.object(idrac_session.time, "monotonic", side_effect=[10.0, 20.0]) as clock,
            patch.object(idrac_session.time, "sleep") as sleep,
        ):
            actual = idrac_session._run_idrac_session(operation)

        self.assertIs(actual, result)
        sleep.assert_called_once_with(1.5)
        self.assertEqual(clock.call_count, 2)
        self.assertEqual(idrac_session._idrac_last_session_at, 20.0)

    def _case_no_wait_when_gap_is_satisfied(self):
        idrac_session._idrac_last_session_at = 1.0
        with (
            patch.object(idrac_session.time, "monotonic", side_effect=[10.0, 11.0]),
            patch.object(idrac_session.time, "sleep") as sleep,
        ):
            self.assertEqual(idrac_session._run_idrac_session(lambda: "ok"), "ok")
        sleep.assert_not_called()

    def _case_base_exception_propagates_without_advancing_timestamp(self):
        idrac_session._idrac_last_session_at = 5.0
        with (
            patch.object(idrac_session.time, "monotonic", return_value=10.0) as clock,
            self.assertRaisesRegex(KeyboardInterrupt, "stop"),
        ):
            idrac_session._run_idrac_session(lambda: (_ for _ in ()).throw(KeyboardInterrupt("stop")))
        clock.assert_called_once_with()
        self.assertEqual(idrac_session._idrac_last_session_at, 5.0)

    def _case_subprocess_helper_preserves_signature_and_result(self):
        completed = subprocess.CompletedProcess(["racadm"], 0, "ok", "")
        with (
            patch.object(idrac_session, "_run_idrac_session", side_effect=lambda operation: operation()),
            patch.object(idrac_session.subprocess, "run", return_value=completed) as run,
        ):
            actual = idrac_session._run_idrac_subprocess(["racadm"], 30)
        self.assertIs(actual, completed)
        run.assert_called_once_with(["racadm"], capture_output=True, text=True, timeout=30)

    def _case_two_calls_are_serialized(self):
        entered = []
        first_entered = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()
        second_finished = threading.Event()

        def first():
            entered.append("first")
            first_entered.set()
            release_first.wait(2)

        def second():
            entered.append("second")

        def run_second():
            second_started.set()
            idrac_session._run_idrac_session(second, 0)
            second_finished.set()

        idrac_session._idrac_last_session_at = 0.0
        with patch.object(idrac_session.time, "sleep"):
            one = threading.Thread(target=lambda: idrac_session._run_idrac_session(first, 0))
            two = threading.Thread(target=run_second)
            one.start()
            self.assertTrue(first_entered.wait(1))
            two.start()
            self.assertTrue(second_started.wait(1))
            self.assertFalse(second_finished.wait(0.1))
            self.assertEqual(entered, ["first"])
            release_first.set()
            one.join(2)
            two.join(2)
        self.assertFalse(one.is_alive())
        self.assertFalse(two.is_alive())
        self.assertTrue(second_finished.is_set())
        self.assertEqual(entered, ["first", "second"])

    def _case_terminal_openpty_failure_leaves_timestamp(self):
        idrac_session._idrac_last_session_at = 5.0
        with (
            patch.object(terminal.pty, "openpty", side_effect=OSError("open")),
            patch.object(idrac_session.time, "monotonic", return_value=10.0),
            self.assertRaisesRegex(OSError, "open"),
        ):
            idrac_session._run_idrac_session(lambda: terminal._spawn_idrac_pty("cmd"), 10.0)
        self.assertEqual(idrac_session._idrac_last_session_at, 5.0)

    def _case_terminal_spawn_failure_closes_slave_without_advancing(self):
        idrac_session._idrac_last_session_at = 0.0
        with (
            patch.object(terminal.pty, "openpty", return_value=(10, 11)),
            patch.object(terminal.subprocess, "Popen", side_effect=OSError("spawn")),
            patch.object(terminal.os, "close") as close,
            patch.object(idrac_session.time, "monotonic", return_value=20.0),
            self.assertRaisesRegex(OSError, "spawn"),
        ):
            idrac_session._run_idrac_session(lambda: terminal._spawn_idrac_pty("cmd"), 10.0)
        close.assert_called_once_with(11)
        self.assertEqual(idrac_session._idrac_last_session_at, 0.0)

    def _case_terminal_close_error_wins_over_spawn_error_without_advance(self):
        idrac_session._idrac_last_session_at = 0.0
        with (
            patch.object(terminal.pty, "openpty", return_value=(10, 11)),
            patch.object(terminal.subprocess, "Popen", side_effect=OSError("spawn")),
            patch.object(terminal.os, "close", side_effect=OSError("close")),
            patch.object(idrac_session.time, "monotonic", return_value=20.0),
            self.assertRaisesRegex(OSError, "close"),
        ):
            idrac_session._run_idrac_session(lambda: terminal._spawn_idrac_pty("cmd"), 10.0)
        self.assertEqual(idrac_session._idrac_last_session_at, 0.0)

    def _case_terminal_successful_spawn_close_failure_advances_before_reraise(self):
        idrac_session._idrac_last_session_at = 0.0
        proc = Mock(pid=123)
        with (
            patch.object(terminal.pty, "openpty", return_value=(10, 11)),
            patch.object(terminal.subprocess, "Popen", return_value=proc),
            patch.object(terminal.os, "close", side_effect=OSError("close")),
            patch.object(idrac_session.time, "monotonic", side_effect=[20.0, 21.0]),
        ):
            pid, fd, close_error = idrac_session._run_idrac_session(
                lambda: terminal._spawn_idrac_pty("cmd"), 10.0
            )
        self.assertEqual((pid, fd), (123, 10))
        self.assertRegex(str(close_error), "close")
        self.assertEqual(idrac_session._idrac_last_session_at, 21.0)

    def _case_terminal_full_success_signature_result_gap_and_advance(self):
        proc = Mock(pid=123)
        idrac_session._idrac_last_session_at = 0.0
        with (
            patch.object(terminal.pty, "openpty", return_value=(10, 11)),
            patch.object(terminal.subprocess, "Popen", return_value=proc) as popen,
            patch.object(terminal.os, "close") as close,
            patch.object(idrac_session.time, "monotonic", side_effect=[20.0, 21.0]),
        ):
            result = idrac_session._run_idrac_session(
                lambda: terminal._spawn_idrac_pty("ssh command"), 10.0
            )
        self.assertEqual(result, (123, 10, None))
        close.assert_called_once_with(11)
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["bash", "-c", "ssh command"])
        self.assertEqual((kwargs["stdin"], kwargs["stdout"], kwargs["stderr"]), (11, 11, 11))
        self.assertTrue(kwargs["close_fds"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["env"]["TERM"], "xterm-256color")
        self.assertEqual(idrac_session._idrac_last_session_at, 21.0)

    def _case_terminal_consumer_reraises_close_error_after_unlock_as_500(self):
        handler = SimpleNamespace(command="POST", _session_user="operator-a")
        cfg = SimpleNamespace(ssh_service_account="freq-admin")
        responses = []

        def respond(_handler, payload, status):
            acquired = idrac_session.IDRAC_SESSION_LOCK.acquire(blocking=False)
            self.assertTrue(acquired)
            idrac_session.IDRAC_SESSION_LOCK.release()
            responses.append((payload, status))

        idrac_session._idrac_last_session_at = 0.0
        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(terminal, "_cleanup_stale"),
            patch.object(terminal, "load_config", return_value=cfg),
            patch.object(terminal, "get_params", return_value={"type": ["host"], "target": ["10.0.0.2"], "htype": ["idrac"]}),
            patch.object(terminal, "_terminal_ssh_auth", return_value={"key_path": "/key", "user": "u"}),
            patch.object(terminal, "_terminal_preflight", return_value=(True, "")),
            patch.object(terminal, "_build_ssh_cmd", return_value=["ssh"]),
            patch.object(terminal, "_spawn_idrac_pty", return_value=(123, 10, OSError("close"))),
            patch.object(terminal.os, "killpg") as killpg,
            patch.object(terminal.os, "close") as close,
            patch.object(terminal, "json_response", side_effect=respond),
            patch.object(idrac_session.time, "monotonic", side_effect=[20.0, 21.0]),
        ):
            terminal.handle_terminal_open(handler)
        self.assertEqual(responses, [({"error": "PTY spawn failed: close"}, 500)])
        killpg.assert_called_once_with(123, terminal.signal.SIGTERM)
        close.assert_called_once_with(10)
        self.assertEqual(idrac_session._idrac_last_session_at, 21.0)

    def _case_hw_key_fallback_and_cache_store_after_unlock(self):
        self.assertEqual(hw.IDRAC_READ_CONNECT_TIMEOUT, 10)
        self.assertEqual(hw.IDRAC_READ_COMMAND_TIMEOUT, 30)
        cfg = SimpleNamespace(
            ssh_rsa_key_path="/rsa",
            ssh_key_path="/key",
            ssh_service_account="freq-admin",
            legacy_password_file="/password",
        )
        denied = SimpleNamespace(returncode=1, stderr="Permission denied", stdout="")
        accepted = SimpleNamespace(returncode=0, stderr="", stdout="ok")

        def store(ip, cmd, result):
            acquired = idrac_session.IDRAC_SESSION_LOCK.acquire(blocking=False)
            self.assertTrue(acquired)
            idrac_session.IDRAC_SESSION_LOCK.release()
            self.assertIs(result, accepted)

        idrac_session._idrac_last_session_at = 0.0
        with (
            patch.object(hw, "ssh_single", side_effect=[denied, accepted]) as ssh,
            patch.object(hw, "_store_idrac_result", side_effect=store) as cache,
            patch.object(idrac_session.time, "monotonic", side_effect=[20.0, 21.0]),
        ):
            result = hw._run_idrac_read(cfg, "10.0.0.2", "racadm hwinventory")
        self.assertIs(result, accepted)
        self.assertEqual(ssh.call_count, 2)
        first = ssh.call_args_list[0].kwargs
        second = ssh.call_args_list[1].kwargs
        for call in (first, second):
            self.assertEqual(call["user"], "freq-admin")
            self.assertEqual(call["key_path"], "/rsa")
            self.assertEqual(call["connect_timeout"], hw.IDRAC_READ_CONNECT_TIMEOUT)
            self.assertEqual(call["command_timeout"], hw.IDRAC_READ_COMMAND_TIMEOUT)
            self.assertEqual(call["htype"], "idrac")
            self.assertFalse(call["use_sudo"])
        self.assertEqual(first["cfg"].legacy_password_file, "")
        self.assertIs(ssh.call_args_list[1].kwargs["cfg"], cfg)
        cache.assert_called_once_with("10.0.0.2", "racadm hwinventory", accepted)

    def _case_hw_failure_evidence_never_empty(self):
        cases = (
            (SimpleNamespace(stderr="permission denied", stdout="", returncode=1), "permission denied"),
            (SimpleNamespace(stderr="", stdout="controller busy", returncode=1), "controller busy"),
            (
                SimpleNamespace(stderr="", stdout="", returncode=255),
                "SSH command failed with rc=255 and no stderr",
            ),
        )
        for result, expected in cases:
            with self.subTest(expected=expected):
                evidence = hw._idrac_failure_evidence(result)
                self.assertEqual(evidence, expected)
                self.assertTrue(evidence.strip())

    def _case_fleet_cold_health_uses_shared_auth_session_and_management_truth(self):
        host = fleet.Host(ip="10.0.0.2", label="bmc-10", htype="idrac", groups="bmc")
        cfg = SimpleNamespace(
            hosts=[host],
            conf_dir="",
            pve_nodes=[],
            ssh_key_path="/key",
            ssh_rsa_key_path="/rsa",
            ssh_connect_timeout=7,
            ssh_max_parallel=1,
        )
        auth = {
            "user": "freq-admin",
            "key_path": "/staged-rsa",
            "local_user": "freq-ops",
            "password_file": "/staged-password",
            "sudo_password_file": True,
        }
        ssh_result = SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=(
                "System Model = PowerEdge R730\n"
                "Power Status = ON\n"
                "Inlet Temp = 23 C"
            ),
        )
        responses = []

        with (
            patch.dict(fleet._bg_cache, {}, clear=True),
            patch.dict(fleet._bg_cache_ts, {}, clear=True),
            patch.dict(fleet._bg_cache_errors, {}, clear=True),
            patch.object(fleet, "_bg_cache_from_disk", set()),
            patch.object(fleet, "_check_session_role", return_value=("viewer", None)),
            patch.object(fleet, "load_config", return_value=cfg),
            patch.object(fleet, "resolve_staged_device_ssh_auth", return_value=auth) as resolve,
            patch.object(fleet, "_run_idrac_session", side_effect=lambda operation: operation()) as session,
            patch.object(fleet, "ssh_single", return_value=ssh_result) as ssh,
            patch.object(fleet, "json_response", side_effect=lambda _handler, payload: responses.append(payload)),
        ):
            fleet.handle_health_api(SimpleNamespace())

        resolve.assert_called_once_with(cfg, "idrac")
        session.assert_called_once()
        call = ssh.call_args.kwargs
        self.assertEqual(call["host"], "10.0.0.2")
        self.assertEqual(call["command"], "racadm getsysinfo -s")
        self.assertEqual(call["key_path"], "/staged-rsa")
        self.assertEqual(call["user"], "freq-admin")
        self.assertEqual(call["local_user"], "freq-ops")
        self.assertEqual(call["password_file"], "/staged-password")
        self.assertTrue(call["sudo_password_file"])
        self.assertEqual(call["connect_timeout"], 7)
        self.assertEqual(call["command_timeout"], 15)
        self.assertEqual(call["htype"], "idrac")
        self.assertFalse(call["use_sudo"])
        self.assertIs(call["cfg"], cfg)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["probe_state"], "live")
        self.assertEqual(responses[0]["probe_reason"], "all 1 hosts live")
        row = responses[0]["hosts"][0]
        self.assertEqual(row["state"], "live")
        self.assertEqual(row["reason"], "racadm getsysinfo -s returned OK")
        self.assertFalse(row["resource_metrics_supported"])
        self.assertEqual((row["cores"], row["ram"], row["disk"]), (None, None, None))
        self.assertEqual(
            row["management_metrics"],
            {"model": "PowerEdge R730", "power": "ON", "inlet_temp": "23 C"},
        )


IDRAC_SESSION_SERVICE_CASES = (
    "_case_exact_consumer_identities",
    "_case_waits_exact_remainder_holds_lock_and_returns_identity",
    "_case_no_wait_when_gap_is_satisfied",
    "_case_base_exception_propagates_without_advancing_timestamp",
    "_case_subprocess_helper_preserves_signature_and_result",
    "_case_two_calls_are_serialized",
    "_case_terminal_openpty_failure_leaves_timestamp",
    "_case_terminal_spawn_failure_closes_slave_without_advancing",
    "_case_terminal_close_error_wins_over_spawn_error_without_advance",
    "_case_terminal_successful_spawn_close_failure_advances_before_reraise",
    "_case_terminal_full_success_signature_result_gap_and_advance",
    "_case_terminal_consumer_reraises_close_error_after_unlock_as_500",
    "_case_hw_key_fallback_and_cache_store_after_unlock",
    "_case_hw_failure_evidence_never_empty",
    "_case_fleet_cold_health_uses_shared_auth_session_and_management_truth",
)


class TestIdracSessionServiceMatrix(unittest.TestCase):
    def test_idrac_session_service_matrix(self):
        self.assertEqual(len(IDRAC_SESSION_SERVICE_CASES), 15)
        run_case_matrix(self, IdracSessionServiceTests, IDRAC_SESSION_SERVICE_CASES)


if __name__ == "__main__":
    unittest.main()
