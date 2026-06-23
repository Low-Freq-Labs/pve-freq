"""Web setup init status/log contract tests."""

import io
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _handler(path):
    from freq.modules.serve import FreqHandler

    h = FreqHandler.__new__(FreqHandler)
    h.path = path
    h.command = "GET"
    h.wfile = io.BytesIO()
    h.rfile = io.BytesIO()
    h.requestline = f"GET {path} HTTP/1.1"
    h.client_address = ("127.0.0.1", 9999)
    h.request_version = "HTTP/1.1"
    h.headers = {}
    h._headers_buffer = []
    h._status = None
    h.send_response = lambda code, msg=None: setattr(h, "_status", code)
    h.send_header = lambda k, v: None
    h.end_headers = lambda: None
    return h


def _json(h):
    return json.loads(h.wfile.getvalue().decode())


def test_setup_init_status_promotes_job_state_and_log_tail():
    from freq.modules.serve import FreqHandler

    h = _handler("/api/setup/init/status")
    snap = {
        "running": False,
        "job": {
            "id": "abc",
            "state": "succeeded",
            "lines": ["phase one", "done"],
            "returncode": 0,
            "initialized": True,
        },
    }
    with patch("freq.modules.serve._check_session_role", return_value=("admin", None)), \
         patch("freq.modules.serve._setup_init_snapshot", return_value=snap):
        FreqHandler._serve_setup_init_status(h)

    assert h._status == 200
    body = _json(h)
    assert body["state"] == "complete"
    assert body["phase"] == "done"
    assert body["log_tail"] == ["phase one", "done"]


def test_setup_init_logs_route_returns_lines():
    from freq.modules.serve import FreqHandler

    h = _handler("/api/setup/init/logs")
    snap = {
        "running": False,
        "job": {
            "id": "abc",
            "state": "failed",
            "lines": ["starting", "failed"],
            "returncode": 1,
            "initialized": False,
        },
    }
    with patch("freq.modules.serve._check_session_role", return_value=("admin", None)), \
         patch("freq.modules.serve._setup_init_snapshot", return_value=snap):
        FreqHandler._serve_setup_init_logs(h)

    assert h._status == 200
    body = _json(h)
    assert body["state"] == "failed"
    assert body["lines"] == ["starting", "failed"]
