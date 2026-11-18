"""Web setup init status/log contract tests."""

import io
import json
import os
import sys
from functools import partial
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


def _assert_setup_init_status_resolution_contract():
    import ast
    import inspect

    from freq.modules import serve
    from freq.services import setup_progress

    cfg = object()

    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    status_handler = next(
        node
        for node in ast.walk(serve_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_serve_setup_init_status"
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resolve_setup_init_status"
        for node in ast.walk(status_handler)
    ) == 1
    assert sum(
        isinstance(node, ast.FunctionDef)
        and node.name == "resolve_setup_init_status"
        for node in service_tree.body
    ) == 1
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_resolve_setup_init_status"
        for node in serve_tree.body
    )
    assert not any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("freq.modules")
        for node in ast.walk(service_tree)
    )
    assert isinstance(serve._resolve_setup_init_status, partial)
    assert (
        serve._resolve_setup_init_status.func
        is setup_progress.resolve_setup_init_status
    )
    assert (
        serve._resolve_setup_init_status.keywords["runtime"]
        is serve._setup_init_status_runtime
    )
    assert setup_progress.SetupInitStatusRuntime.__dataclass_params__.frozen
    assert setup_progress.SetupInitStatusResolution.__dataclass_params__.frozen

    def invoke(
        path,
        snapshot,
        *,
        command="GET",
        role=("admin", None),
        owner="sonny",
        state=None,
    ):
        h = _handler(path)
        h.command = command
        h._session_user = owner
        observed_state = {} if state is None else state
        with (
            patch("freq.modules.serve._check_session_role", return_value=role) as check_role,
            patch("freq.modules.serve.load_config", return_value=cfg) as load_cfg,
            patch(
                "freq.modules.serve._observe_setup_state",
                return_value=observed_state,
            ) as observe_state,
            patch(
                "freq.modules.serve._setup_init_snapshot",
                return_value=snapshot,
            ) as read_job,
            patch(
                "freq.modules.serve._setup_init_public_job",
                wraps=setup_progress.project_init_job,
            ) as project_job,
        ):
            serve.FreqHandler._serve_setup_init_status(h)
        return h, check_role, load_cfg, observe_state, read_job, project_job

    h, check_role, load_cfg, observe_state, read_job, project_job = invoke(
        "/api/setup/init/status?id=private-unread-job",
        {"job": {"id": "private-unread-job"}},
        command="POST",
    )
    assert h._status == 405
    assert _json(h)["error"] == {
        "code": "method_not_allowed",
        "message": "Setup init status requires GET.",
        "retryable": False,
    }
    check_role.assert_not_called()
    load_cfg.assert_not_called()
    observe_state.assert_not_called()
    read_job.assert_not_called()
    project_job.assert_not_called()

    h, check_role, load_cfg, observe_state, read_job, project_job = invoke(
        "/api/setup/init/status?id=private-unread-job",
        {"job": {"id": "private-unread-job"}},
        role=(None, "Authentication required"),
    )
    assert h._status == 403
    assert _json(h)["error"]["code"] == "admin_required"
    check_role.assert_called_once_with(h, "admin")
    load_cfg.assert_not_called()
    observe_state.assert_not_called()
    read_job.assert_not_called()
    project_job.assert_not_called()

    h, _check_role, load_cfg, observe_state, read_job, project_job = invoke(
        "/api/setup/init/status",
        {"job": {"id": "private-unread-job"}},
    )
    assert h._status == 400
    assert _json(h)["error"] == {
        "code": "required_field",
        "message": "Init job id is required.",
        "retryable": False,
        "field": "id",
    }
    load_cfg.assert_called_once_with()
    observe_state.assert_not_called()
    read_job.assert_not_called()
    project_job.assert_not_called()

    h, _check_role, load_cfg, observe_state, read_job, project_job = invoke(
        "/api/setup/init/status?id=lost-job",
        {"running": False, "job": None},
        state={"active_init_job_id": "lost-job"},
    )
    assert h._status == 410
    assert _json(h)["error"]["code"] == "init_expired"
    load_cfg.assert_called_once_with()
    observe_state.assert_called_once_with(cfg)
    read_job.assert_called_once_with()
    project_job.assert_not_called()

    for active_job_id in (None, "other-job"):
        h, _check_role, _load_cfg, observe_state, read_job, project_job = invoke(
            "/api/setup/init/status?id=lost-job",
            {"running": False, "job": None},
            state={"active_init_job_id": active_job_id},
        )
        assert h._status == 404
        assert _json(h)["error"]["code"] == "init_not_found"
        observe_state.assert_called_once_with(cfg)
        read_job.assert_called_once_with()
        project_job.assert_not_called()

    base_job = {
        "id": "job-1",
        "owner": "sonny",
        "state": "succeeded",
        "lines": ["complete"],
        "returncode": 0,
        "initialized": True,
        "web_setup_complete": True,
        "pid": 4199,
        "process": object(),
        "private_runtime": "never-project",
    }
    for mismatched_job in (
        {**base_job, "id": "other-job"},
        {**base_job, "owner": "other-operator"},
    ):
        h, _check_role, _load_cfg, observe_state, read_job, project_job = invoke(
            "/api/setup/init/status?id=job-1",
            {"running": False, "job": mismatched_job},
            state={"active_init_job_id": "job-1"},
        )
        assert h._status == 404
        assert _json(h)["error"]["code"] == "init_not_found"
        observe_state.assert_called_once_with(cfg)
        read_job.assert_called_once_with()
        project_job.assert_not_called()

    h, check_role, load_cfg, observe_state, read_job, project_job = invoke(
        "/api/setup/init/status?id=%20job-1%20",
        {"running": False, "job": base_job},
        state={"active_init_job_id": "job-1"},
    )
    assert h._status == 200
    assert _json(h) == {
        "ok": True,
        "schema": serve.ZERO_STATE_WEB_SCHEMA,
        "job": setup_progress.project_init_job(base_job),
    }
    response_text = h.wfile.getvalue().decode()
    assert "never-project" not in response_text
    assert "private_runtime" not in response_text
    assert "pid" not in response_text
    assert "process" not in response_text
    assert "owner" not in response_text
    check_role.assert_called_once_with(h, "admin")
    load_cfg.assert_called_once_with()
    observe_state.assert_called_once_with(cfg)
    read_job.assert_called_once_with()
    project_job.assert_called_once_with(base_job)


def _assert_setup_init_logs_resolution_contract():
    import ast
    import inspect

    from freq.modules import serve
    from freq.services import setup_progress

    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    logs_handler = next(
        node
        for node in ast.walk(serve_tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_serve_setup_init_logs"
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resolve_setup_init_logs"
        for node in ast.walk(logs_handler)
    ) == 1
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_init_snapshot"
        for node in ast.walk(logs_handler)
    )
    assert sum(
        isinstance(node, ast.FunctionDef)
        and node.name == "resolve_setup_init_logs"
        for node in service_tree.body
    ) == 1
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_resolve_setup_init_logs"
        for node in serve_tree.body
    )
    assert not any(
        isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("freq.modules")
        for node in ast.walk(service_tree)
    )
    assert isinstance(serve._resolve_setup_init_logs, partial)
    assert serve._resolve_setup_init_logs.func is setup_progress.resolve_setup_init_logs
    assert (
        serve._resolve_setup_init_logs.keywords["runtime"]
        is serve._setup_init_logs_runtime
    )
    assert set(serve._setup_init_logs_runtime.__dataclass_fields__) == {
        "snapshot_job"
    }
    assert setup_progress.SetupInitLogsRuntime.__dataclass_params__.frozen
    assert setup_progress.SetupInitLogsResolution.__dataclass_params__.frozen

    def invoke(
        path,
        snapshot,
        *,
        role=("admin", None),
        owner="sonny",
    ):
        h = _handler(path)
        h._session_user = owner
        with (
            patch("freq.modules.serve._check_session_role", return_value=role) as check_role,
            patch(
                "freq.modules.serve._setup_init_snapshot",
                return_value=snapshot,
            ) as read_job,
            patch(
                "freq.modules.serve._setup_init_public_job",
                wraps=setup_progress.project_init_job,
            ) as project_job,
        ):
            serve.FreqHandler._serve_setup_init_logs(h)
        return h, check_role, read_job, project_job

    h, check_role, read_job, project_job = invoke(
        "/api/setup/init/logs?id=private-unread-job",
        {"job": {"id": "private-unread-job"}},
        role=(None, "Authentication required"),
    )
    assert h._status == 403
    assert _json(h)["error"]["code"] == "admin_required"
    check_role.assert_called_once_with(h, "admin")
    read_job.assert_not_called()
    project_job.assert_not_called()

    h, check_role, read_job, project_job = invoke(
        "/api/setup/init/logs",
        {"job": {"id": "private-unread-job"}},
    )
    assert h._status == 400
    assert _json(h)["error"] == {
        "code": "required_field",
        "message": "Init job id is required.",
        "retryable": False,
        "field": "id",
    }
    check_role.assert_called_once_with(h, "admin")
    read_job.assert_not_called()
    project_job.assert_not_called()

    lines = [f"line-{index}" for index in range(305)]
    base_job = {
        "id": "job-1",
        "owner": "sonny",
        "state": "running",
        "lines": lines,
        "pid": 4200,
        "process": object(),
        "private_runtime": "never-project",
    }
    for rejected_job in (
        None,
        {**base_job, "id": "other-job"},
        {**base_job, "owner": "other-operator"},
    ):
        h, _check_role, read_job, project_job = invoke(
            "/api/setup/init/logs?id=job-1",
            {"running": False, "job": rejected_job},
        )
        assert h._status == 404
        assert _json(h)["error"]["code"] == "init_not_found"
        read_job.assert_called_once_with()
        project_job.assert_not_called()

    h, check_role, read_job, project_job = invoke(
        "/api/setup/init/logs?id=%20job-1%20",
        {"running": True, "job": base_job},
    )
    assert h._status == 200
    assert _json(h) == {
        "ok": True,
        "schema": serve.ZERO_STATE_WEB_SCHEMA,
        "job": setup_progress.project_init_job(base_job, log_limit=300),
    }
    assert _json(h)["job"]["log_tail"] == lines[-300:]
    response_text = h.wfile.getvalue().decode()
    assert "never-project" not in response_text
    assert "private_runtime" not in response_text
    assert "pid" not in response_text
    assert "process" not in response_text
    assert "owner" not in response_text
    check_role.assert_called_once_with(h, "admin")
    read_job.assert_called_once_with()
    project_job.assert_called_once_with(base_job, log_limit=300)


def test_setup_init_status_promotes_job_state_and_log_tail():
    import ast
    import inspect

    from freq.modules import serve
    from freq.services import setup_progress

    FreqHandler = serve.FreqHandler
    _setup_init_public_job = serve._setup_init_public_job
    assert serve._redact_setup_init_line is setup_progress.redact_init_line
    assert serve._setup_init_progress is setup_progress.parse_init_progress
    assert serve._setup_init_public_job is setup_progress.project_init_job
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name in {
            "_redact_setup_init_line",
            "_setup_init_progress",
            "_setup_init_public_job",
        }
        for node in ast.walk(ast.parse(inspect.getsource(serve)))
    )
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert {
        alias.name
        for node in ast.walk(service_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } == {"datetime", "json", "os", "re", "signal", "subprocess", "tempfile"}
    assert {
        node.module
        for node in ast.walk(service_tree)
        if isinstance(node, ast.ImportFrom)
    } == {
        "collections.abc",
        "dataclasses",
        "freq.core.setup_contract",
        "freq.core.setup_state",
        "typing",
    }
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "_setup_init_snapshot"
        for node in serve_tree.body
    ) == 0
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_init_snapshot"
        for node in ast.walk(serve_tree)
    ) == 4
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "snapshot_init_job"
        for node in service_tree.body
    ) == 1
    snapshot_adapter = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "snapshot_live_init_job"
    )
    assert isinstance(serve._setup_init_snapshot, partial)
    assert serve._setup_init_snapshot.func is setup_progress.snapshot_live_init_job
    assert set(serve._setup_init_snapshot.keywords) == {"current_lock", "current_job"}
    assert serve._setup_init_snapshot.keywords["current_lock"]() is serve._setup_init_lock
    assert serve._setup_init_snapshot.keywords["current_job"]() is serve._setup_init_job
    assert len(snapshot_adapter.body) == 2
    snapshot_with = snapshot_adapter.body[1]
    assert isinstance(snapshot_with, ast.With)
    assert len(snapshot_with.items) == 1
    assert isinstance(snapshot_with.items[0].context_expr, ast.Call)
    assert ast.unparse(snapshot_with.items[0].context_expr) == "current_lock()"
    assert len(snapshot_with.body) == 1
    snapshot_return = snapshot_with.body[0]
    assert isinstance(snapshot_return, ast.Return)
    assert isinstance(snapshot_return.value, ast.Call)
    assert ast.unparse(snapshot_return.value) == "snapshot_init_job(current_job())"

    h = _handler("/api/setup/init/status?id=abc")
    h._session_user = "sonny"
    snap = {
        "running": False,
        "job": {
            "id": "abc",
            "owner": "sonny",
            "state": "succeeded",
            "lines": ["phase one", "done"],
            "returncode": 0,
            "initialized": True,
            "cancel_requested": True,
            "cancel_signal_sent": True,
            "cancel_delivery_failed": False,
        },
    }
    with patch("freq.modules.serve._check_session_role", return_value=("admin", None)), \
         patch("freq.modules.serve._setup_init_snapshot", return_value=snap):
        FreqHandler._serve_setup_init_status(h)

    assert h._status == 200
    body = _json(h)
    assert body["schema"] == "zero-state-web-v1"
    assert body["job"]["state"] == "succeeded"
    assert body["job"]["log_tail"] == ["phase one", "done"]
    assert body["job"]["cancellation"] == {
        "requested": True,
        "delivery": "delivered",
        "retryable": False,
    }
    assert "pid" not in body["job"]
    assert "process" not in body["job"]

    class ObservedLock:
        def __init__(self):
            self.entries = 0
            self.exits = 0
            self.active = False

        def __enter__(self):
            assert not self.active
            self.active = True
            self.entries += 1
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            assert self.active
            self.active = False
            self.exits += 1

    snapshot_lock = ObservedLock()
    original_lock = serve._setup_init_lock
    original_job = serve._setup_init_job

    def snapshot():
        entries = snapshot_lock.entries
        result = serve._setup_init_snapshot()
        assert snapshot_lock.entries == entries + 1
        assert snapshot_lock.entries == snapshot_lock.exits
        assert snapshot_lock.active is False
        return result

    try:
        serve._setup_init_lock = snapshot_lock
        serve._setup_init_job = None
        assert snapshot() == {"running": False, "job": None}

        live_job = {"id": "live-job", "state": "queued"}
        lower_result = object()
        serve._setup_init_job = live_job
        with patch(
            "freq.services.setup_progress.snapshot_init_job",
            return_value=lower_result,
        ) as lower_snapshot:
            entries = snapshot_lock.entries
            assert serve._setup_init_snapshot() is lower_result
        assert snapshot_lock.entries == entries + 1
        assert snapshot_lock.entries == snapshot_lock.exits
        assert snapshot_lock.active is False
        lower_snapshot.assert_called_once_with(live_job)

        projection_error = RuntimeError("snapshot projection failed")
        with patch(
            "freq.services.setup_progress.snapshot_init_job",
            side_effect=projection_error,
        ) as lower_snapshot:
            entries = snapshot_lock.entries
            try:
                serve._setup_init_snapshot()
            except RuntimeError as caught:
                assert caught is projection_error
            else:
                raise AssertionError("snapshot projection error was swallowed")
        assert snapshot_lock.entries == entries + 1
        assert snapshot_lock.entries == snapshot_lock.exits
        assert snapshot_lock.active is False
        lower_snapshot.assert_called_once_with(live_job)

        private_process = object()
        private_lines = [f"line-{index}" for index in range(305)]
        private_job = {
            "id": "snapshot-job",
            "state": "queued",
            "process": private_process,
            "lines": private_lines,
            "progress": {"phase": 4},
        }
        serve._setup_init_job = private_job
        queued = snapshot()
        assert queued["running"] is True
        assert queued["job"] is not private_job
        assert "process" not in queued["job"]
        assert queued["job"]["lines"] == private_lines[-300:]
        assert queued["job"]["lines"] is not private_lines
        queued["job"]["lines"].append("snapshot-only")
        assert len(private_lines) == 305
        assert private_job["process"] is private_process

        for state, expected_running in (
            ("running", True),
            ("succeeded", False),
            ("failed", False),
            (None, False),
        ):
            if state is None:
                private_job.pop("state", None)
            else:
                private_job["state"] = state
            assert snapshot()["running"] is expected_running
    finally:
        serve._setup_init_lock = original_lock
        serve._setup_init_job = original_job

    cancellation_cases = (
        ({}, {"requested": False, "delivery": "not_requested", "retryable": False}),
        (
            {"cancel_requested": True},
            {"requested": True, "delivery": "pending", "retryable": False},
        ),
        (
            {"cancel_requested": True, "cancel_signal_sent": True},
            {"requested": True, "delivery": "delivered", "retryable": False},
        ),
        (
            {
                "cancel_requested": True,
                "cancel_signal_sent": True,
                "cancel_delivery_failed": True,
            },
            {"requested": True, "delivery": "failed", "retryable": True},
        ),
        (
            {"cancel_signal_sent": True, "cancel_delivery_failed": True},
            {"requested": False, "delivery": "not_requested", "retryable": False},
        ),
        (
            {
                "state": "succeeded",
                "cancel_requested": True,
                "cancel_delivery_failed": True,
            },
            {"requested": True, "delivery": "failed", "retryable": False},
        ),
        (
            {"state": "succeeded", "cancel_requested": True},
            {"requested": True, "delivery": "failed", "retryable": False},
        ),
        (
            {
                "state": "failed",
                "cancel_requested": True,
                "cancel_delivery_failed": True,
            },
            {"requested": True, "delivery": "failed", "retryable": False},
        ),
        (
            {"state": "failed", "cancel_requested": True},
            {"requested": True, "delivery": "failed", "retryable": False},
        ),
    )
    for private_state, expected in cancellation_cases:
        public_job = _setup_init_public_job({"id": "abc", **private_state})
        assert public_job["cancellation"] == expected
        assert "pid" not in public_job
        assert "process" not in public_job

    assert _setup_init_public_job(None) == {
        "id": None,
        "state": "queued",
        "returncode": None,
        "initialized": False,
        "web_setup_complete": False,
        "poll_after_ms": 1000,
        "progress": {},
        "log_tail": [],
        "cancellation": {
            "requested": False,
            "delivery": "not_requested",
            "retryable": False,
        },
    }

    private_progress = {"phase": 4, "message": "Running configure."}
    projected = _setup_init_public_job(
        {
            "id": "job-4",
            "state": "running",
            "returncode": 9,
            "initialized": 1,
            "web_setup_complete": "yes",
            "progress": private_progress,
            "lines": ["one", "two", "three"],
            "pid": 123,
            "process": object(),
            "owner": "sonny",
        },
        log_limit=2,
    )
    assert projected == {
        "id": "job-4",
        "state": "running",
        "returncode": 9,
        "initialized": True,
        "web_setup_complete": True,
        "poll_after_ms": 1000,
        "progress": private_progress,
        "log_tail": ["two", "three"],
        "cancellation": {
            "requested": False,
            "delivery": "not_requested",
            "retryable": False,
        },
    }
    assert projected["progress"] is not private_progress
    assert projected["initialized"] is True
    assert projected["web_setup_complete"] is True
    assert _setup_init_public_job({"lines": ["private"]}, log_limit=0)["log_tail"] == []
    assert not ({"pid", "process", "owner"} & projected.keys())

    succeeded = _setup_init_public_job({"state": "succeeded", "error": "private"})
    assert succeeded["poll_after_ms"] == 0
    assert "error" not in succeeded
    for private_error, expected_message in (
        ("", "Setup initialization failed."),
        ("exact failure", "exact failure"),
    ):
        failed = _setup_init_public_job({"state": "failed", "error": private_error})
        assert failed["poll_after_ms"] == 0
        assert failed["error"] == {
            "code": "init_failed",
            "message": expected_message,
            "retryable": True,
        }

    redaction_cases = (
        (None, "", ""),
        (123, "", "123"),
        ("  leading and trailing  \n", "", "  leading and trailing"),
        ("read /tmp/setup-secret/a then /tmp/setup-secret/b\n", "/tmp/setup-secret", "read [setup-secret-dir]/a then [setup-secret-dir]/b"),
    )
    for line, secret_dir, expected in redaction_cases:
        assert serve._redact_setup_init_line(line, secret_dir) == expected

    long_name = "x" * 121
    progress_cases = (
        ("not a phase", None),
        ("phase two / 12: invalid", None),
        (
            "phase 2 / 12:  Fleet discovery  ",
            {
                "phase": 2,
                "phase_name": "Fleet discovery",
                "current": 2,
                "total": 12,
                "message": "Running Fleet discovery.",
            },
        ),
        (
            "Phase 3 of 13 —   ",
            {
                "phase": 3,
                "phase_name": "Initialization",
                "current": 3,
                "total": 13,
                "message": "Running Initialization.",
            },
        ),
        (
            "prefix Phase 4/12 - Configure suffix",
            {
                "phase": 4,
                "phase_name": "Configure suffix",
                "current": 4,
                "total": 12,
                "message": "Running Configure suffix.",
            },
        ),
        (
            f"Phase 5 / 12: {long_name}",
            {
                "phase": 5,
                "phase_name": "x" * 120,
                "current": 5,
                "total": 12,
                "message": f"Running {'x' * 120}.",
            },
        ),
    )
    for line, expected in progress_cases:
        assert serve._setup_init_progress(line) == expected

    _assert_setup_init_status_resolution_contract()


def test_setup_init_logs_route_returns_lines():
    from freq.modules.serve import FreqHandler

    h = _handler("/api/setup/init/logs?id=abc")
    h._session_user = "sonny"
    snap = {
        "running": False,
        "job": {
            "id": "abc",
            "owner": "sonny",
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
    assert body["job"]["state"] == "failed"
    assert body["job"]["log_tail"] == ["starting", "failed"]

    _assert_setup_init_logs_resolution_contract()
