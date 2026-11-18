"""Behavior ownership for the dedicated GWIPE mutation route."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from freq.api import hw


class _Response:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


class TestGwipeMutationBehavior(unittest.TestCase):
    @staticmethod
    def _handler(path="/api/gwipe?action=wipe-all&confirm=YES", command="POST"):
        return SimpleNamespace(path=path, command=command)

    @staticmethod
    def _response_sink(responses):
        def respond(_handler, payload, status=200):
            responses.append((status, payload))

        return respond

    def test_method_then_admin_role_gate_precede_query_and_side_effects(self):
        responses = []
        with (
            patch.object(hw, "require_post", return_value=True),
            patch.object(hw, "_check_session_role") as role,
            patch.object(hw, "_parse_query") as parse,
            patch.object(hw, "load_config") as load,
            patch.object(hw, "vault_get") as vault,
            patch("urllib.request.urlopen") as urlopen,
        ):
            hw.handle_gwipe(self._handler(command="GET"))
        role.assert_not_called()
        parse.assert_not_called()
        load.assert_not_called()
        vault.assert_not_called()
        urlopen.assert_not_called()

        with (
            patch.object(hw, "require_post", return_value=False),
            patch.object(
                hw,
                "_check_session_role",
                return_value=("operator", "Admin role required"),
            ),
            patch.object(hw, "_parse_query") as parse,
            patch.object(hw, "load_config") as load,
            patch.object(hw, "vault_get") as vault,
            patch("urllib.request.urlopen") as urlopen,
            patch.object(
                hw,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            hw.handle_gwipe(self._handler())
        self.assertEqual(responses, [(403, {"error": "Admin role required"})])
        parse.assert_not_called()
        load.assert_not_called()
        vault.assert_not_called()
        urlopen.assert_not_called()

    def test_action_and_confirmation_are_exact_before_config_or_secrets(self):
        invalid_paths = (
            "/api/gwipe",
            "/api/gwipe?action=status&confirm=YES",
            "/api/gwipe?action=wipe-all",
            "/api/gwipe?action=wipe-all&confirm=yes",
            "/api/gwipe?action=wipe-all&action=status&confirm=YES",
            "/api/gwipe?action=wipe-all&confirm=YES&confirm=YES",
        )
        for path in invalid_paths:
            responses = []
            with (
                self.subTest(path=path),
                patch.object(hw, "require_post", return_value=False),
                patch.object(
                    hw,
                    "_check_session_role",
                    return_value=("admin", None),
                ),
                patch.object(hw, "load_config") as load,
                patch.object(hw, "vault_get") as vault,
                patch("urllib.request.urlopen") as urlopen,
                patch.object(
                    hw,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                hw.handle_gwipe(self._handler(path=path))
            self.assertEqual(responses[0][0], 400)
            load.assert_not_called()
            vault.assert_not_called()
            urlopen.assert_not_called()

    def test_vault_only_post_request_success_and_failures_preserve_envelopes(self):
        cfg = object()
        override_path = (
            "/api/gwipe?action=wipe-all&confirm=YES"
            "&host=evil.example&host=other.example&key=stolen"
            "&method=DELETE&endpoint=status"
        )

        for missing_key in ("gwipe_host", "gwipe_api_key"):
            responses = []

            def missing_value(_cfg, _namespace, key):
                return "" if key == missing_key else "vault-value"

            with (
                self.subTest(missing=missing_key),
                patch.object(hw, "require_post", return_value=False),
                patch.object(
                    hw,
                    "_check_session_role",
                    return_value=("admin", None),
                ),
                patch.object(hw, "load_config", return_value=cfg),
                patch.object(hw, "vault_get", side_effect=missing_value),
                patch("urllib.request.urlopen") as urlopen,
                patch.object(
                    hw,
                    "json_response",
                    side_effect=self._response_sink(responses),
                ),
            ):
                hw.handle_gwipe(self._handler(path=override_path))
            self.assertEqual(
                responses,
                [(400, {"error": "GWIPE station not configured in vault"})],
            )
            urlopen.assert_not_called()

        responses = []

        def vault_value(_cfg, namespace, key):
            self.assertEqual(namespace, "gwipe")
            return {
                "gwipe_host": "192.0.2.80",
                "gwipe_api_key": "vault-api-key",
            }[key]

        with (
            patch.object(hw, "require_post", return_value=False),
            patch.object(
                hw,
                "_check_session_role",
                return_value=("admin", None),
            ),
            patch.object(hw, "load_config", return_value=cfg),
            patch.object(hw, "vault_get", side_effect=vault_value),
            patch("urllib.request.urlopen", return_value=_Response({"message": "started"})) as urlopen,
            patch.object(
                hw,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            hw.handle_gwipe(self._handler(path=override_path))
        self.assertEqual(
            responses,
            [
                (
                    200,
                    {
                        "ok": True,
                        "action": "wipe-all",
                        "data": {"message": "started"},
                    },
                )
            ],
        )
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://192.0.2.80:7980/api/v1/wipe-all",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.data, b'{"confirm":"YES"}')
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["x-api-key"], "vault-api-key")
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": 10})

        responses.clear()
        with (
            patch.object(hw, "require_post", return_value=False),
            patch.object(
                hw,
                "_check_session_role",
                return_value=("admin", None),
            ),
            patch.object(hw, "load_config", return_value=cfg),
            patch.object(hw, "vault_get", side_effect=vault_value),
            patch("urllib.request.urlopen", side_effect=OSError("station down")),
            patch.object(hw.logger, "error") as log_error,
            patch.object(
                hw,
                "json_response",
                side_effect=self._response_sink(responses),
            ),
        ):
            hw.handle_gwipe(self._handler(path=override_path))
        self.assertEqual(
            responses,
            [(500, {"error": "GWIPE operation failed: station down"})],
        )
        log_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
