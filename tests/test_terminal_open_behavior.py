"""Behavior ownership for terminal admission, orchestration, and PTY cleanup."""

import itertools
import struct
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from freq.api import terminal


class TestTerminalOpenBehavior(unittest.TestCase):
    def setUp(self):
        with terminal._sessions_lock:
            terminal._sessions.clear()
            terminal._pending_sessions = 0

    def tearDown(self):
        with terminal._sessions_lock:
            terminal._sessions.clear()
            terminal._pending_sessions = 0

    @staticmethod
    def _handler():
        return SimpleNamespace(command="POST", _session_user="operator-a")

    @staticmethod
    def _cfg(*, hosts=()):
        return SimpleNamespace(
            hosts=list(hosts),
            ssh_service_account="freq-admin",
        )

    @staticmethod
    def _response_sink(responses):
        def respond(_handler, payload, status=200):
            responses.append((status, payload))

        return respond

    def test_query_and_resize_validation_are_bounded_and_side_effect_free(self):
        self.assertEqual(terminal._parse_terminal_geometry({}), (120, 30))
        self.assertEqual(
            terminal._parse_terminal_geometry({"cols": ["1"], "rows": ["65535"]}),
            (1, 65535),
        )
        for params in (
            {"cols": []},
            {"cols": [""], "rows": ["30"]},
            {"cols": [" 80"], "rows": ["30"]},
            {"cols": ["+80"], "rows": ["30"]},
            {"cols": ["1.5"], "rows": ["30"]},
            {"cols": ["0"], "rows": ["30"]},
            {"cols": ["65536"], "rows": ["30"]},
            {"cols": ["80"], "rows": ["-1"]},
            {"cols": ["80"], "rows": [None]},
        ):
            with self.subTest(geometry=params):
                self.assertIsNone(terminal._parse_terminal_geometry(params))

        invalid_open = (
            ({"type": ["shell"], "target": ["192.0.2.1"]}, "Invalid terminal type"),
            ({"type": ["host"]}, "target parameter required"),
            (
                {"type": ["host"], "target": ["host;id"]},
                "Invalid target",
            ),
            (
                {"type": ["ct"], "target": ["101"], "node": ["pve01;id"]},
                "Invalid node",
            ),
            (
                {"type": ["ct"], "target": ["not-a-ctid"]},
                "numeric CTID",
            ),
            (
                {"type": ["host"], "target": ["192.0.2.1"], "cols": ["wide"]},
                "ASCII decimal integers",
            ),
        )
        for params, expected_error in invalid_open:
            responses = []
            with (
                self.subTest(params=params),
                patch.object(terminal, "require_post", return_value=False),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                patch.object(terminal, "get_params", return_value=params),
                patch.object(terminal, "_cleanup_stale") as cleanup,
                patch.object(terminal, "load_config") as load,
                patch.object(terminal, "_reserve_session_slot") as reserve,
                patch.object(terminal.pty, "fork") as fork,
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_open(self._handler())
            self.assertEqual(responses[0][0], 400)
            self.assertIn(expected_error, responses[0][1]["error"])
            cleanup.assert_not_called()
            load.assert_not_called()
            reserve.assert_not_called()
            fork.assert_not_called()

        session = {"fd": 44, "cols": 80, "rows": 24, "user": "operator-a"}
        terminal._sessions["owned"] = session
        responses = []
        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(
                terminal,
                "get_params",
                return_value={"session": ["owned"], "cols": ["nope"], "rows": ["40"]},
            ),
            patch("fcntl.ioctl") as ioctl,
            patch.object(
                terminal,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            terminal.handle_terminal_resize(self._handler())
        self.assertEqual(responses[0][0], 400)
        self.assertEqual((session["cols"], session["rows"]), (80, 24))
        ioctl.assert_not_called()

        responses.clear()
        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(terminal, "get_params", return_value={"session": ["owned"]}),
            patch("fcntl.ioctl") as ioctl,
            patch.object(
                terminal,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            terminal.handle_terminal_resize(self._handler())
        self.assertEqual(responses, [(200, {"ok": True})])
        self.assertEqual((session["cols"], session["rows"]), (120, 30))
        ioctl.assert_called_once_with(44, unittest.mock.ANY, struct.pack("HHHH", 30, 120, 0, 0))

    def test_open_orchestrates_each_target_family_without_retesting_helpers(self):
        scenarios = (
            {
                "name": "direct-host",
                "params": {"type": ["host"], "target": ["192.0.2.10"]},
                "host": "192.0.2.10",
                "command": "",
            },
            {
                "name": "direct-node",
                "params": {"type": ["node"], "target": ["pve01"]},
                "host": "pve01",
                "command": "",
            },
            {
                "name": "registered-vm",
                "params": {"type": ["vm"], "target": ["201"]},
                "cfg": self._cfg(hosts=[SimpleNamespace(vmid=201, ip="192.0.2.201")]),
                "host": "192.0.2.201",
                "command": "",
            },
            {
                "name": "live-vm",
                "params": {"type": ["vm"], "target": ["202"], "node": ["pve02"]},
                "live_node": ("192.0.2.2", "pve02"),
                "guest": ("guest-json", True, "pve_api"),
                "guest_ip": "192.0.2.202",
                "host": "192.0.2.202",
                "command": "",
            },
            {
                "name": "ct-supplied-node",
                "params": {"type": ["ct"], "target": ["301"], "node": ["pve03"]},
                "host": "pve03",
                "command": "sudo pct enter 301",
            },
            {
                "name": "ct-reachable-node",
                "params": {"type": ["ct"], "target": ["302"]},
                "reachable": "192.0.2.3",
                "host": "192.0.2.3",
                "command": "sudo pct enter 302",
            },
        )
        for index, scenario in enumerate(scenarios):
            responses = []
            cfg = scenario.get("cfg", self._cfg())
            params = dict(scenario["params"])
            params["htype"] = ["linux"]
            with (
                self.subTest(scenario=scenario["name"]),
                patch.object(terminal, "require_post", return_value=False),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                patch.object(terminal, "get_params", return_value=params),
                patch.object(terminal, "_cleanup_stale"),
                patch.object(terminal, "load_config", return_value=cfg),
                patch.object(
                    terminal,
                    "_find_live_vm_node_ip",
                    return_value=scenario.get("live_node", ("", "")),
                ) as find_live,
                patch.object(
                    terminal,
                    "_guest_agent_network_json",
                    return_value=scenario.get("guest", ("", False, "pve_ssh")),
                ) as guest,
                patch.object(
                    terminal,
                    "_extract_guest_ipv4",
                    return_value=scenario.get("guest_ip", ""),
                ) as extract,
                patch("freq.modules.pve._find_reachable_node", return_value=scenario.get("reachable", "")) as reachable,
                patch.object(
                    terminal,
                    "_terminal_ssh_auth",
                    return_value={
                        "user": "terminal-user",
                        "key_path": "/keys/terminal",
                        "password_file": "/secrets/password",
                        "sudo_password_file": True,
                        "local_user": "freq-admin",
                    },
                ) as auth,
                patch.object(terminal, "_terminal_preflight", return_value=(True, "")) as preflight,
                patch.object(terminal, "_build_ssh_cmd", return_value=["ssh", scenario["host"]]) as build,
                patch.object(terminal.pty, "fork", return_value=(1000 + index, 2000 + index)),
                patch("fcntl.ioctl"),
                patch.object(terminal, "current_user", return_value="operator-a"),
                patch.object(
                    terminal.secrets,
                    "token_urlsafe",
                    side_effect=[f"session-{index}", f"nonce-{index}"],
                ),
                patch.object(terminal.time, "time", return_value=100.0 + index),
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_open(self._handler())

            self.assertEqual(responses[0][0], 200)
            self.assertEqual(responses[0][1]["session"], f"session-{index}")
            auth.assert_called_once_with(cfg, "linux")
            preflight.assert_called_once_with(cfg, "linux", scenario["host"] if scenario["name"] != "ct-supplied-node" and scenario["name"] != "ct-reachable-node" else scenario["params"]["target"][0], unittest.mock.ANY)
            build.assert_called_once_with(
                host=scenario["host"],
                command=scenario["command"],
                user="terminal-user",
                key_path="/keys/terminal",
                htype="linux",
                use_sudo=False,
                extra_opts=["-tt"],
                local_user="freq-admin",
                password_file="/secrets/password",
                sudo_password_file=True,
                cfg=cfg,
            )
            session = terminal._sessions[f"session-{index}"]
            self.assertEqual((session["type"], session["target"]), (params["type"][0], params["target"][0]))
            self.assertEqual((session["user"], session["ws_nonce"]), ("operator-a", f"nonce-{index}"))
            self.assertEqual(terminal._pending_sessions, 0)

            if scenario["name"] == "registered-vm":
                find_live.assert_not_called()
            elif scenario["name"] == "live-vm":
                find_live.assert_called_once_with(cfg, 202, "pve02")
                guest.assert_called_once_with(cfg, 202, "192.0.2.2", "pve02")
                extract.assert_called_once_with("guest-json")
            if scenario["name"] == "ct-reachable-node":
                reachable.assert_called_once_with(cfg)
            else:
                reachable.assert_not_called()

            with terminal._sessions_lock:
                terminal._sessions.clear()

        for name, params, live_node, reachable_error in (
            ("vm-unresolved", {"type": ["vm"], "target": ["404"]}, ("", ""), None),
            ("ct-no-node", {"type": ["ct"], "target": ["404"]}, ("", ""), ""),
        ):
            responses = []
            with (
                self.subTest(scenario=name),
                patch.object(terminal, "require_post", return_value=False),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                patch.object(terminal, "get_params", return_value=params),
                patch.object(terminal, "_cleanup_stale"),
                patch.object(terminal, "load_config", return_value=self._cfg()),
                patch.object(terminal, "_find_live_vm_node_ip", return_value=live_node),
                patch("freq.modules.pve._find_reachable_node", return_value=reachable_error),
                patch.object(terminal, "_terminal_ssh_auth", return_value={"user": "u", "key_path": "/k"}),
                patch.object(terminal, "_terminal_preflight", return_value=(True, "")),
                patch.object(terminal, "_build_ssh_cmd") as build,
                patch.object(terminal.pty, "fork") as fork,
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_open(self._handler())
            self.assertEqual(responses[0][0], 400)
            build.assert_not_called()
            fork.assert_not_called()
            self.assertEqual(terminal._pending_sessions, 0)

    def test_admission_and_spawn_lifecycle_are_atomic_and_orphan_free(self):
        base_params = {"type": ["host"], "target": ["192.0.2.10"]}
        cfg = self._cfg()

        responses = []
        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(terminal, "get_params", return_value=base_params),
            patch.object(terminal, "_cleanup_stale", side_effect=RuntimeError("cleanup failed")),
            patch.object(terminal, "_reserve_session_slot") as reserve,
            patch.object(terminal, "load_config") as load,
            patch.object(
                terminal,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            terminal.handle_terminal_open(self._handler())
        self.assertEqual(responses, [(500, {"error": "Terminal setup failed"})])
        reserve.assert_not_called()
        load.assert_not_called()

        failures = (
            ("config", RuntimeError("config failed"), None, False),
            ("fork", None, OSError("fork failed"), False),
            ("idrac-close", None, (501, 601, OSError("close failed")), True),
        )
        for name, config_error, spawn_result, idrac in failures:
            responses = []
            params = dict(base_params)
            if idrac:
                params["htype"] = ["idrac"]
            load = Mock(side_effect=config_error) if config_error else Mock(return_value=cfg)
            fork = Mock(side_effect=spawn_result) if isinstance(spawn_result, OSError) else Mock()
            idrac_runner = Mock(return_value=spawn_result) if idrac else Mock()
            with (
                self.subTest(failure=name),
                patch.object(terminal, "require_post", return_value=False),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                patch.object(terminal, "get_params", return_value=params),
                patch.object(terminal, "_cleanup_stale"),
                patch.object(terminal, "load_config", load),
                patch.object(terminal, "_terminal_ssh_auth", return_value={"user": "u", "key_path": "/k"}),
                patch.object(terminal, "_terminal_preflight", return_value=(True, "")),
                patch.object(terminal, "_build_ssh_cmd", return_value=["ssh"]),
                patch.object(terminal.pty, "fork", fork),
                patch.object(terminal, "_run_idrac_session", idrac_runner),
                patch.object(terminal.os, "kill") as kill,
                patch.object(terminal.os, "killpg") as killpg,
                patch.object(terminal.os, "close") as close,
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_open(self._handler())
            self.assertEqual(responses[0][0], 500)
            self.assertEqual(terminal._pending_sessions, 0)
            self.assertEqual(terminal._sessions, {})
            if idrac:
                killpg.assert_called_once_with(501, terminal.signal.SIGTERM)
                close.assert_called_once_with(601)
                kill.assert_not_called()
            else:
                kill.assert_not_called()
                killpg.assert_not_called()
                close.assert_not_called()

        responses = []
        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(terminal, "get_params", return_value=base_params),
            patch.object(terminal, "_cleanup_stale"),
            patch.object(terminal, "load_config", return_value=cfg),
            patch.object(terminal, "_terminal_ssh_auth", return_value={"user": "u", "key_path": "/k"}),
            patch.object(terminal, "_terminal_preflight", return_value=(False, "preflight denied")),
            patch.object(terminal, "_build_ssh_cmd") as build,
            patch.object(terminal.pty, "fork") as fork,
            patch.object(
                terminal,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            terminal.handle_terminal_open(self._handler())
        self.assertEqual(responses, [(400, {"error": "preflight denied"})])
        self.assertEqual(terminal._pending_sessions, 0)
        build.assert_not_called()
        fork.assert_not_called()

        for identity_mode in ("missing-empty", "missing-error", "cached-empty"):
            responses.clear()
            identity_lookup = (
                patch.object(terminal, "current_user", return_value="revived-user")
                if identity_mode == "cached-empty"
                else patch.object(terminal, "current_user", return_value="")
                if identity_mode == "missing-empty"
                else patch.object(
                    terminal,
                    "current_user",
                    side_effect=RuntimeError("identity failed"),
                )
            )
            with (
                self.subTest(identity=identity_mode),
                patch.object(terminal, "require_post", return_value=False),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                identity_lookup as fallback,
                patch.object(terminal, "get_params") as get_params,
                patch.object(terminal, "_cleanup_stale") as cleanup,
                patch.object(terminal, "_reserve_session_slot") as reserve,
                patch.object(terminal, "load_config") as load,
                patch.object(terminal.pty, "fork") as fork,
                patch.object(terminal.secrets, "token_urlsafe") as token,
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_open(
                    SimpleNamespace(command="POST", _session_user="")
                    if identity_mode == "cached-empty"
                    else SimpleNamespace(command="POST")
                )
            self.assertEqual(responses, [(500, {"error": "Terminal setup failed"})])
            self.assertEqual(terminal._pending_sessions, 0)
            get_params.assert_not_called()
            cleanup.assert_not_called()
            reserve.assert_not_called()
            load.assert_not_called()
            fork.assert_not_called()
            token.assert_not_called()
            if identity_mode == "cached-empty":
                fallback.assert_not_called()

        responses = []
        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(terminal, "get_params", return_value=base_params),
            patch.object(terminal, "_cleanup_stale"),
            patch.object(terminal, "load_config", return_value=cfg),
            patch.object(terminal, "_terminal_ssh_auth", return_value={"user": "u", "key_path": "/k"}),
            patch.object(terminal, "_terminal_preflight", return_value=(True, "")),
            patch.object(terminal, "_build_ssh_cmd", return_value=["ssh"]),
            patch.object(terminal.pty, "fork", return_value=(701, 801)),
            patch("fcntl.ioctl", side_effect=OSError("resize unavailable")),
            patch.object(
                terminal,
                "current_user",
                side_effect=RuntimeError("cached identity must win"),
            ) as identity_lookup,
            patch.object(terminal.secrets, "token_urlsafe", side_effect=["session-ok", "nonce-ok"]),
            patch.object(terminal.time, "time", return_value=123.0),
            patch.object(terminal.os, "kill") as kill,
            patch.object(terminal.os, "close") as close,
            patch.object(
                terminal,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            terminal.handle_terminal_open(
                SimpleNamespace(command="POST", _session_user="operator-a")
            )
        self.assertEqual(responses, [(200, {"ok": True, "session": "session-ok", "ws_nonce": "nonce-ok", "type": "host", "target": "192.0.2.10"})])
        self.assertEqual(terminal._pending_sessions, 0)
        self.assertIn("session-ok", terminal._sessions)
        self.assertEqual(terminal._sessions["session-ok"]["user"], "operator-a")
        identity_lookup.assert_not_called()
        kill.assert_not_called()
        close.assert_not_called()

        with terminal._sessions_lock:
            terminal._sessions.clear()

        condition = threading.Condition()
        release_preflight = threading.Event()
        preflight_started = 0
        responses = []
        token_counter = itertools.count()
        spawn_counter = itertools.count(1000)

        def preflight(*_args):
            nonlocal preflight_started
            with condition:
                preflight_started += 1
                condition.notify_all()
            if not release_preflight.wait(5):
                raise RuntimeError("contention gate timed out")
            return True, ""

        def respond(_handler, payload, status=200):
            with condition:
                responses.append((status, payload))
                condition.notify_all()

        def token(_size):
            with condition:
                return f"token-{next(token_counter)}"

        def spawn():
            with condition:
                value = next(spawn_counter)
            return value, value + 10000

        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(terminal, "get_params", return_value=base_params),
            patch.object(terminal, "_cleanup_stale"),
            patch.object(terminal, "load_config", return_value=cfg),
            patch.object(terminal, "_terminal_ssh_auth", return_value={"user": "u", "key_path": "/k"}),
            patch.object(terminal, "_terminal_preflight", side_effect=preflight),
            patch.object(terminal, "_build_ssh_cmd", return_value=["ssh"]),
            patch.object(terminal.pty, "fork", side_effect=spawn),
            patch("fcntl.ioctl"),
            patch.object(terminal, "current_user", return_value="operator-a"),
            patch.object(terminal.secrets, "token_urlsafe", side_effect=token),
            patch.object(terminal, "json_response", side_effect=respond),
        ):
            threads = [
                threading.Thread(target=terminal.handle_terminal_open, args=(self._handler(),))
                for _ in range(terminal._MAX_SESSIONS + 5)
            ]
            for thread in threads:
                thread.start()
            with condition:
                reached_decision = condition.wait_for(
                    lambda: preflight_started > terminal._MAX_SESSIONS
                    or sum(status == 429 for status, _payload in responses) >= 5,
                    timeout=5,
                )
                observed_preflight = preflight_started
                observed_429 = sum(status == 429 for status, _payload in responses)
            with terminal._sessions_lock:
                observed_total = len(terminal._sessions) + terminal._pending_sessions
            release_preflight.set()
            for thread in threads:
                thread.join(5)
                self.assertFalse(thread.is_alive())

        self.assertTrue(reached_decision)
        self.assertEqual(observed_preflight, terminal._MAX_SESSIONS)
        self.assertEqual(observed_429, 5)
        self.assertEqual(observed_total, terminal._MAX_SESSIONS)
        self.assertEqual(sum(status == 200 for status, _payload in responses), 20)
        self.assertEqual(sum(status == 429 for status, _payload in responses), 5)
        self.assertEqual(len(terminal._sessions), terminal._MAX_SESSIONS)
        self.assertEqual(terminal._pending_sessions, 0)


if __name__ == "__main__":
    unittest.main()
