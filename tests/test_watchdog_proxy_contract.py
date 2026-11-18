"""Runtime contract for the one public watchdog-health proxy."""
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import URLError


class TestWatchdogProxyRuntime(unittest.TestCase):
    """The public watchdog endpoint preserves upstream truth at runtime."""

    class _Response:
        def __init__(self, payload: bytes, status: int):
            self._payload = payload
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self._payload

    def _invoke(self, cfg, *, path="/api/watchdog/health", command="GET", upstream=None):
        from freq.api import fleet
        from freq.modules.serve import FreqHandler

        handler = FreqHandler.__new__(FreqHandler)
        handler.path = path
        handler.command = command
        sent = []

        def capture(actual_handler, payload, status=200):
            self.assertIs(actual_handler, handler)
            sent.append((payload, status))

        load = MagicMock(return_value=cfg)
        urlopen = MagicMock(side_effect=upstream) if isinstance(upstream, BaseException) else MagicMock(return_value=upstream)
        with (
            patch.object(fleet, "load_config", load),
            patch.object(fleet, "json_response", side_effect=capture),
            patch("urllib.request.urlopen", urlopen),
        ):
            fleet.handle_watchdog_health(handler)
        self.assertEqual(len(sent), 1)
        return sent[0], load, urlopen

    def _dispatch(self, path):
        from freq.modules import serve

        handler = serve.FreqHandler.__new__(serve.FreqHandler)
        handler.path = path
        handler.command = "GET"
        handler._session_user = "watchdog-contract"
        sent = []
        handler._json_response = lambda payload, status=200: sent.append((payload, status))
        with (
            patch.object(serve, "_check_session_role", return_value=("viewer", None)),
            patch("urllib.request.urlopen") as urlopen,
        ):
            handler._dispatch()
        self.assertEqual(len(sent), 1)
        return sent[0], urlopen

    def _openapi(self):
        from freq.modules.serve import FreqHandler

        handler = FreqHandler.__new__(FreqHandler)
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler._serve_openapi_json()
        return json.loads(handler.wfile.getvalue())

    def test_runtime_contract(self):
        disabled = SimpleNamespace(watchdog_enabled=False)
        (payload, status), loaded, opened = self._invoke(disabled)
        self.assertEqual(
            (payload, status),
            ({"ok": True, "watchdog_installed": False, "status": "not_installed"}, 200),
        )
        loaded.assert_called_once_with()
        opened.assert_not_called()

        (payload, status), loaded, opened = self._invoke(disabled, command="POST")
        self.assertEqual(
            (payload, status),
            ({"error": "GET required for watchdog health"}, 405),
        )
        self.assertNotIn("watchdog_down", payload)
        loaded.assert_not_called()
        opened.assert_not_called()

        cfg = SimpleNamespace(watchdog_enabled=True, watchdog_port=9917)
        upstream_payload = {"ok": False, "status": "degraded", "hosts": 3}
        response = self._Response(json.dumps(upstream_payload).encode(), 207)
        (payload, status), loaded, opened = self._invoke(
            cfg,
            path="/api/watchdog/health?detail=full&site=dc01",
            upstream=response,
        )
        self.assertEqual((payload, status), (upstream_payload, 207))
        loaded.assert_called_once_with()
        request = opened.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:9917/api/watchdog/health?detail=full&site=dc01",
        )
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.get_header("Accept"), "application/json")
        self.assertEqual(opened.call_args.kwargs, {"timeout": 10})

        (payload, status), _, _ = self._invoke(cfg, upstream=URLError("refused"))
        self.assertEqual(
            (payload, status),
            (
                {
                    "error": "WATCHDOG daemon not reachable at localhost:9917",
                    "watchdog_down": True,
                },
                503,
            ),
        )

        for upstream in (
            self._Response(b"not-json", 200),
            RuntimeError("sentinel proxy failure"),
        ):
            with self.subTest(upstream=type(upstream).__name__):
                (payload, status), _, _ = self._invoke(cfg, upstream=upstream)
                self.assertEqual(status, 502)
                self.assertTrue(payload["error"].startswith("Proxy error: "))

        for path in ("/api/watch/status?detail=1", "/api/comms/test?detail=1"):
            with self.subTest(retired_path=path):
                (payload, status), opened = self._dispatch(path)
                self.assertEqual(status, 404)
                self.assertEqual(payload, {"error": "not found", "path": path.split("?", 1)[0]})
                opened.assert_not_called()

        paths = self._openapi()["paths"]
        self.assertNotIn("/api/watch/{path}", paths)
        self.assertNotIn("/api/comms/{path}", paths)


if __name__ == "__main__":
    unittest.main()
