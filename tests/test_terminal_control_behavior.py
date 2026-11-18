"""Behavior ownership for terminal creator-scoped control endpoints."""

import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from freq.api import terminal


class TestTerminalControlBehavior(unittest.TestCase):
    def setUp(self):
        with terminal._sessions_lock:
            terminal._sessions.clear()
            terminal._pending_sessions = 0

    def tearDown(self):
        with terminal._sessions_lock:
            terminal._sessions.clear()
            terminal._pending_sessions = 0

    @staticmethod
    def _handler(*, user=None, path="/"):
        values = {
            "command": "POST",
            "path": path,
            "headers": {},
            "send_error": Mock(),
        }
        if user is not None:
            values["_session_user"] = user
        return SimpleNamespace(**values)

    @staticmethod
    def _session(user, *, target="192.0.2.10"):
        now = time.time()
        return {
            "fd": 44,
            "pid": 123,
            "type": "host",
            "htype": "linux",
            "target": target,
            "created": now - 100,
            "last_active": now - 1,
            "cols": 80,
            "rows": 24,
            "user": user,
            "ws_nonce": "nonce-a",
            "kill_pgrp": False,
        }

    @staticmethod
    def _response_sink(responses):
        def respond(_handler, payload, status=200):
            responses.append((status, payload))

        return respond

    def test_sessions_are_filtered_to_one_cached_or_fallback_requester(self):
        terminal._sessions.update(
            {
                "alice-session": self._session("alice"),
                "bob-session": self._session("bob", target="192.0.2.11"),
                "legacy-session": self._session("", target="192.0.2.12"),
            }
        )
        responses = []
        with (
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(
                terminal,
                "current_user",
                side_effect=RuntimeError("cached identity must win"),
            ) as identity_lookup,
            patch.object(terminal, "_cleanup_stale") as cleanup,
            patch.object(
                terminal,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            terminal.handle_terminal_sessions(self._handler(user="bob"))
        identity_lookup.assert_not_called()
        cleanup.assert_called_once_with()
        self.assertEqual(
            responses,
            [
                (
                    200,
                    {
                        "sessions": [
                            {
                                "session": "bob-sess...",
                                "type": "host",
                                "target": "192.0.2.11",
                                "age": unittest.mock.ANY,
                                "idle": unittest.mock.ANY,
                            }
                        ],
                        "count": 1,
                    },
                )
            ],
        )

        for identity_mode in ("missing-empty", "missing-error", "cached-empty"):
            responses.clear()
            fallback = (
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
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                fallback as identity_lookup,
                patch.object(terminal, "_cleanup_stale") as cleanup,
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_sessions(
                    self._handler(user="")
                    if identity_mode == "cached-empty"
                    else self._handler()
                )
            self.assertEqual(responses, [(403, {"error": "Authentication required"})])
            cleanup.assert_not_called()
            if identity_mode == "cached-empty":
                identity_lookup.assert_not_called()

    def test_resize_and_close_are_creator_scoped_without_existence_leaks(self):
        alice = self._session("alice")
        terminal._sessions.update(
            {
                "alice-session": alice,
                "legacy-session": self._session(""),
            }
        )

        resize_cases = (
            ("different-owner", "bob", "alice-session"),
            ("missing-session", "alice", "missing-session"),
            ("missing-owner", "alice", "legacy-session"),
        )
        for name, requester, session_id in resize_cases:
            responses = []
            with (
                self.subTest(operation="resize", case=name),
                patch.object(terminal, "require_post", return_value=False),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                patch.object(
                    terminal,
                    "current_user",
                    side_effect=RuntimeError("cached identity must win"),
                ) as identity_lookup,
                patch.object(
                    terminal,
                    "get_params",
                    return_value={
                        "session": [session_id],
                        "cols": ["100"],
                        "rows": ["40"],
                    },
                ),
                patch("fcntl.ioctl") as ioctl,
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_resize(self._handler(user=requester))
            identity_lookup.assert_not_called()
            self.assertEqual(responses, [(404, {"error": "Session not found"})])
            self.assertEqual((alice["cols"], alice["rows"]), (80, 24))
            ioctl.assert_not_called()

        responses = []
        with (
            patch.object(terminal, "require_post", return_value=False),
            patch.object(terminal, "_check_session_role", return_value=("operator", None)),
            patch.object(
                terminal,
                "current_user",
                side_effect=RuntimeError("cached identity must win"),
            ) as identity_lookup,
            patch.object(
                terminal,
                "get_params",
                return_value={
                    "session": ["alice-session"],
                    "cols": ["100"],
                    "rows": ["40"],
                },
            ),
            patch("fcntl.ioctl") as ioctl,
            patch.object(
                terminal,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            terminal.handle_terminal_resize(self._handler(user="alice"))
        identity_lookup.assert_not_called()
        self.assertEqual(responses, [(200, {"ok": True})])
        self.assertEqual((alice["cols"], alice["rows"]), (100, 40))
        ioctl.assert_called_once()

        for name, requester, session_id, expected_kill in (
            ("different-owner", "bob", "alice-session", False),
            ("missing-session", "alice", "missing-session", False),
            ("missing-owner", "alice", "legacy-session", False),
            ("owner", "alice", "alice-session", True),
        ):
            responses = []
            with (
                self.subTest(operation="close", case=name),
                patch.object(terminal, "require_post", return_value=False),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                patch.object(
                    terminal,
                    "current_user",
                    side_effect=RuntimeError("cached identity must win"),
                ) as identity_lookup,
                patch.object(
                    terminal,
                    "get_params",
                    return_value={"session": [session_id]},
                ),
                patch.object(terminal, "_kill_session") as kill,
                patch.object(
                    terminal,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                terminal.handle_terminal_close(self._handler(user=requester))
            identity_lookup.assert_not_called()
            self.assertEqual(responses, [(200, {"ok": True})])
            self.assertEqual(kill.call_count, int(expected_kill))

        for operation, handler_fn in (
            ("resize", terminal.handle_terminal_resize),
            ("close", terminal.handle_terminal_close),
        ):
            for identity_mode in ("missing-empty", "missing-error", "cached-empty"):
                responses = []
                fallback = (
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
                    self.subTest(operation=operation, identity=identity_mode),
                    patch.object(terminal, "require_post", return_value=False),
                    patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                    fallback as identity_lookup,
                    patch.object(terminal, "get_params") as get_params,
                    patch("fcntl.ioctl") as ioctl,
                    patch.object(terminal, "_kill_session") as kill,
                    patch.object(
                        terminal,
                        "json_response",
                        side_effect=self._response_sink(responses),
                    ),
                ):
                    handler_fn(
                        self._handler(user="")
                        if identity_mode == "cached-empty"
                        else self._handler()
                    )
                self.assertEqual(responses, [(403, {"error": "Authentication required"})])
                get_params.assert_not_called()
                ioctl.assert_not_called()
                kill.assert_not_called()
                if identity_mode == "cached-empty":
                    identity_lookup.assert_not_called()

    def test_websocket_creator_and_nonce_checks_fail_closed_before_handshake(self):
        terminal._sessions.update(
            {
                "alice-session": self._session("alice"),
                "legacy-session": self._session(""),
            }
        )

        for name, requester, session_id, nonce, expected in (
            (
                "missing-owner",
                "alice",
                "legacy-session",
                "nonce-a",
                call(403, "Session belongs to another user"),
            ),
            (
                "different-owner",
                "bob",
                "alice-session",
                "nonce-a",
                call(403, "Session belongs to another user"),
            ),
            (
                "wrong-nonce",
                "alice",
                "alice-session",
                "wrong",
                call(403, "Terminal websocket nonce required"),
            ),
            (
                "owner",
                "alice",
                "alice-session",
                "nonce-a",
                call(400, "Missing Sec-WebSocket-Key"),
            ),
        ):
            handler = self._handler(
                user=requester,
                path=f"/api/terminal/ws?session={session_id}&nonce={nonce}",
            )
            with (
                self.subTest(case=name),
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                patch.object(
                    terminal,
                    "current_user",
                    side_effect=RuntimeError("cached identity must win"),
                ) as identity_lookup,
                patch.object(terminal, "same_origin_or_absent", return_value=True),
            ):
                terminal.handle_terminal_ws(handler)
            identity_lookup.assert_not_called()
            self.assertEqual(handler.send_error.call_args_list, [expected])

        for identity_mode in ("missing-empty", "missing-error", "cached-empty"):
            handler = self._handler(
                user="" if identity_mode == "cached-empty" else None,
                path="/api/terminal/ws?session=alice-session&nonce=nonce-a"
            )
            fallback = (
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
                patch.object(terminal, "_check_session_role", return_value=("operator", None)),
                fallback as identity_lookup,
                patch.object(terminal, "same_origin_or_absent") as same_origin,
                patch.object(terminal.secrets, "compare_digest") as compare,
            ):
                terminal.handle_terminal_ws(handler)
            self.assertEqual(
                handler.send_error.call_args_list,
                [call(403, "Authentication required")],
            )
            same_origin.assert_not_called()
            compare.assert_not_called()
            if identity_mode == "cached-empty":
                identity_lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
