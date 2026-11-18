import ast
import datetime
import inspect
import io
import json
import os
import tempfile
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.core.setup_discovery import (
    DiscoveryInputError,
    _http_fingerprint,
    _ssh_cluster_resources,
    derived_ipv4_networks,
    normalize_pve_resources,
    query_declared_pve_nodes,
    run_setup_discovery,
    scan_derived_devices,
    validate_discovery_request,
)
from freq.core.setup_state import SCHEMA, ensure_setup_state, update_setup_state
from freq.modules import serve
from freq.modules.serve import FreqHandler
from freq.services import setup_progress


def _cfg(root):
    return SimpleNamespace(
        data_dir=os.path.join(root, "data"),
        conf_dir=os.path.join(root, "conf"),
        vault_dir=os.path.join(root, "vault"),
        vault_file=os.path.join(root, "vault", "vault.enc"),
    )


def _request(setup_id="setup-id", request_id="123e4567-e89b-12d3-a456-426614174000"):
    return {
        "schema": SCHEMA,
        "setup_id": setup_id,
        "client_request_id": request_id,
        "cluster": {
            "name": "dc01",
            "nodes": [{"host": "10.25.255.26", "name": "pve01"}],
        },
        "bootstrap": {"username": "freq-ops", "password": "write-only"},
    }


def _handler(body=None, path="/api/setup/discovery/start", command="POST"):
    handler = FreqHandler.__new__(FreqHandler)
    handler.command = command
    handler.path = path
    handler.headers = {}
    handler.rfile = io.BytesIO()
    handler._session_user = "operator"
    handler._request_body = lambda: dict(body or {})
    handler._captured = None
    handler._status_code = None

    def respond(payload, status=200):
        handler._captured = payload
        handler._status_code = status

    handler._json_response = respond
    return handler


@pytest.fixture(autouse=True)
def _clear_discovery_job():
    with serve._setup_discovery_lock:
        serve._setup_discovery_job = None
    yield
    with serve._setup_discovery_lock:
        serve._setup_discovery_job = None


def _assert_setup_discovery_public_job_contract():
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_setup_discovery_payload"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "project_discovery_job"
        for node in service_tree.body
    ) == 1
    assert serve._setup_discovery_payload is setup_progress.project_discovery_job
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_discovery_payload"
        for node in ast.walk(serve_tree)
    ) == 3
    snapshot_adapter = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "snapshot_live_discovery_job"
    )
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_setup_discovery_snapshot"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "snapshot_discovery_job"
        for node in service_tree.body
    ) == 1
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_discovery_snapshot"
        for node in ast.walk(serve_tree)
    ) == 4
    assert isinstance(serve._setup_discovery_snapshot, partial)
    assert serve._setup_discovery_snapshot.func is setup_progress.snapshot_live_discovery_job
    assert set(serve._setup_discovery_snapshot.keywords) == {"current_lock", "current_job"}
    assert (
        serve._setup_discovery_snapshot.keywords["current_lock"]()
        is serve._setup_discovery_lock
    )
    assert (
        serve._setup_discovery_snapshot.keywords["current_job"]()
        is serve._setup_discovery_job
    )
    assert len(snapshot_adapter.body) == 2
    snapshot_with = snapshot_adapter.body[1]
    assert isinstance(snapshot_with, ast.With)
    assert len(snapshot_with.items) == 1
    assert ast.unparse(snapshot_with.items[0].context_expr) == "current_lock()"
    assert [ast.unparse(node) for node in snapshot_with.body] == [
        "return snapshot_discovery_job(current_job())"
    ]
    lower_snapshot = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "snapshot_discovery_job"
    )
    assert [ast.unparse(node) for node in lower_snapshot.body] == [
        "'Return one isolated internal discovery snapshot.'",
        "if not discovery_job:\n    return None",
        "return json.loads(json.dumps(discovery_job))",
    ]

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

        def __exit__(self, *_exc):
            assert self.active
            self.active = False
            self.exits += 1

    original_lock = serve._setup_discovery_lock
    original_job = serve._setup_discovery_job
    snapshot_lock = ObservedLock()
    try:
        serve._setup_discovery_lock = snapshot_lock
        serve._setup_discovery_job = None
        assert serve._setup_discovery_snapshot() is None
        assert snapshot_lock.entries == 1
        assert snapshot_lock.exits == 1
        assert snapshot_lock.active is False

        live_job = {
            "id": "private-snapshot-job",
            "state": "running",
            "cluster": {"nodes": [{"host": "10.0.0.1"}]},
            "progress": {"phase": "pve-bootstrap", "current": 1, "total": 2},
            "results": {"resources": [{"id": "vm:100"}]},
        }
        serve._setup_discovery_job = live_job
        snapshot = serve._setup_discovery_snapshot()
        assert snapshot == live_job
        assert snapshot is not live_job
        assert snapshot["cluster"] is not live_job["cluster"]
        assert snapshot["cluster"]["nodes"] is not live_job["cluster"]["nodes"]
        assert snapshot["progress"] is not live_job["progress"]
        assert snapshot["results"] is not live_job["results"]
        snapshot["cluster"]["nodes"][0]["host"] = "snapshot-only"
        snapshot["results"]["resources"].append({"id": "snapshot-only"})
        assert live_job["cluster"]["nodes"][0]["host"] == "10.0.0.1"
        assert live_job["results"] == {"resources": [{"id": "vm:100"}]}

        live_job["progress"]["current"] = 2
        assert serve._setup_discovery_snapshot()["progress"]["current"] == 2
        live_job["private_non_json"] = object()
        entries = snapshot_lock.entries
        with pytest.raises(TypeError):
            serve._setup_discovery_snapshot()
        assert snapshot_lock.entries == entries + 1
        assert snapshot_lock.exits == snapshot_lock.entries
        assert snapshot_lock.active is False
    finally:
        serve._setup_discovery_lock = original_lock
        serve._setup_discovery_job = original_job

    queued_job = {
        "id": "job-queued",
        "progress": {"phase": "waiting"},
        "setup_id": "private-setup",
        "bootstrap_username": "private-user",
        "cluster": {"nodes": [{"host": "private-host"}]},
        "client_request_id": "private-request",
        "process": object(),
    }
    queued = serve._setup_discovery_payload(queued_job)
    assert queued == {
        "id": "job-queued",
        "state": "queued",
        "started_at": None,
        "updated_at": None,
        "finished_at": None,
        "poll_after_ms": 1000,
        "progress": {"phase": "waiting"},
    }
    assert queued["progress"] is not queued_job["progress"]
    queued["progress"]["phase"] = "changed"
    assert queued_job["progress"] == {"phase": "waiting"}

    succeeded_job = {
        "id": "job-succeeded",
        "state": "succeeded",
        "started_at": "start",
        "updated_at": "update",
        "finished_at": "finish",
        "poll_after_ms": 0,
        "progress": {"phase": "complete", "current": 1, "total": 1},
        "results": {"resources": [{"id": "vm:100"}]},
        "error": {"code": "private-stale-error"},
    }
    succeeded = serve._setup_discovery_payload(succeeded_job)
    assert succeeded["results"] == succeeded_job["results"]
    assert succeeded["results"] is not succeeded_job["results"]
    assert succeeded["results"]["resources"] is not succeeded_job["results"]["resources"]
    assert "error" not in succeeded
    succeeded["results"]["resources"][0]["id"] = "changed"
    assert succeeded_job["results"]["resources"][0]["id"] == "vm:100"

    failed_job = {
        "id": "job-failed",
        "state": "failed",
        "poll_after_ms": 2500,
        "error": {"code": "discovery_failed", "retryable": True},
        "results": {"private": "stale"},
    }
    failed = serve._setup_discovery_payload(failed_job)
    assert failed["poll_after_ms"] == 2500
    assert failed["error"] == failed_job["error"]
    assert failed["error"] is not failed_job["error"]
    assert "results" not in failed
    failed["error"]["code"] = "changed"
    assert failed_job["error"]["code"] == "discovery_failed"

    running = serve._setup_discovery_payload(
        {"id": "job-running", "state": "running", "results": {"private": True}, "error": {"private": True}}
    )
    assert "results" not in running
    assert "error" not in running


def _assert_setup_discovery_progress_contract():
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_setup_discovery_progress"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "update_discovery_progress"
        for node in service_tree.body
    ) == 1
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_discovery_progress"
        for node in ast.walk(serve_tree)
    ) == 1
    assert isinstance(serve._setup_discovery_progress, partial)
    assert serve._setup_discovery_progress.func is setup_progress.update_discovery_progress
    assert set(serve._setup_discovery_progress.keywords) == {"current_lock", "current_job"}
    assert (
        serve._setup_discovery_progress.keywords["current_lock"]()
        is serve._setup_discovery_lock
    )
    assert (
        serve._setup_discovery_progress.keywords["current_job"]()
        is serve._setup_discovery_job
    )

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

        def __exit__(self, *_exc):
            assert self.active
            self.active = False
            self.exits += 1

    original_lock = serve._setup_discovery_lock
    original_job = serve._setup_discovery_job
    progress_lock = ObservedLock()
    try:
        serve._setup_discovery_lock = progress_lock
        serve._setup_discovery_job = None
        assert serve._setup_discovery_progress("missing", "ignored", object(), object(), object()) is None
        assert progress_lock.entries == 1
        assert progress_lock.exits == 1

        untouched = {
            "id": "other-job",
            "updated_at": "unchanged",
            "progress": {"phase": "waiting"},
        }
        serve._setup_discovery_job = untouched
        assert serve._setup_discovery_progress("job-1", "ignored", object(), object(), object()) is None
        assert untouched == {
            "id": "other-job",
            "updated_at": "unchanged",
            "progress": {"phase": "waiting"},
        }

        live_job = {
            "id": "job-1",
            "state": "running",
            "private": {"preserved": True},
            "progress": {"phase": "waiting"},
        }
        serve._setup_discovery_job = live_job
        assert (
            serve._setup_discovery_progress(
                "job-1",
                "pve-bootstrap",
                "2",
                3.9,
                "x" * 260,
            )
            is None
        )
        assert live_job["state"] == "running"
        assert live_job["private"] == {"preserved": True}
        assert live_job["progress"] == {
            "phase": "pve-bootstrap",
            "current": 2,
            "total": 3,
            "message": "x" * 240,
        }
        updated_at = live_job["updated_at"]
        parsed = datetime.datetime.fromisoformat(updated_at)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

        assert serve._setup_discovery_progress("job-1", "waiting", None, False, None) is None
        assert live_job["progress"] == {
            "phase": "waiting",
            "current": 0,
            "total": 0,
            "message": "",
        }
        assert datetime.datetime.fromisoformat(live_job["updated_at"]).tzinfo is not None

        with pytest.raises((TypeError, ValueError)):
            serve._setup_discovery_progress("job-1", "invalid", object(), 1, "bad")
        assert progress_lock.exits == progress_lock.entries
        assert progress_lock.active is False
    finally:
        serve._setup_discovery_lock = original_lock
        serve._setup_discovery_job = original_job


def _assert_setup_discovery_worker_contract(cfg, setup_id):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_run_setup_discovery_job"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "run_setup_discovery_job"
        for node in service_tree.body
    ) == 1
    assert sum(
        isinstance(node, ast.keyword)
        and node.arg == "worker_target"
        and isinstance(node.value, ast.Name)
        and node.value.id == "_run_setup_discovery_job"
        for node in ast.walk(serve_tree)
    ) == 1
    assert isinstance(serve._run_setup_discovery_job, partial)
    assert serve._run_setup_discovery_job.func is setup_progress.run_setup_discovery_job
    assert set(serve._run_setup_discovery_job.keywords) == {"runtime"}
    worker_runtime = serve._run_setup_discovery_job.keywords["runtime"]
    assert worker_runtime is serve._setup_discovery_worker_runtime
    assert worker_runtime.current_lock() is serve._setup_discovery_lock
    assert worker_runtime.setup_lock() is serve._setup_lock
    assert worker_runtime.current_job() is serve._setup_discovery_job

    with serve._setup_discovery_lock:
        serve._setup_discovery_job = {"id": "other-job"}
    with (
        patch("freq.modules.serve.vault_get") as get_secret,
        patch("freq.modules.serve.run_setup_discovery") as discover,
        patch("freq.modules.serve.update_setup_state") as update_state,
    ):
        assert serve._run_setup_discovery_job(cfg, "job-1") is None
    get_secret.assert_not_called()
    discover.assert_not_called()
    update_state.assert_not_called()
    assert serve._setup_discovery_job == {"id": "other-job"}

    base_job = {
        "id": "job-1",
        "setup_id": setup_id,
        "state": "running",
        "cluster": {"name": "dc01", "nodes": [{"host": "10.0.0.1"}]},
        "bootstrap_username": "operator",
        "progress": {"phase": "waiting"},
    }

    with serve._setup_discovery_lock:
        serve._setup_discovery_job = json.loads(json.dumps(base_job))
    with (
        patch("freq.modules.serve.vault_get", return_value=None),
        patch("freq.modules.serve.run_setup_discovery") as discover,
        patch("freq.modules.serve.update_setup_state") as update_state,
    ):
        assert serve._run_setup_discovery_job(cfg, "job-1") is None
    discover.assert_not_called()
    update_state.assert_called_once_with(
        cfg,
        phase="blocked",
        last_error_code="bootstrap_secret_missing",
    )
    missing_secret = serve._setup_discovery_snapshot()
    assert missing_secret["state"] == "failed"
    assert missing_secret["poll_after_ms"] == 0
    assert missing_secret["error"] == {
        "code": "bootstrap_secret_missing",
        "message": "Discovery could not complete from the declared PVE bootstrap targets.",
        "retryable": True,
    }
    assert missing_secret["finished_at"] == missing_secret["updated_at"]
    assert datetime.datetime.fromisoformat(missing_secret["finished_at"]).utcoffset().total_seconds() == 0

    for failure, expected_code in (
        (RuntimeError("pve_bootstrap_failed"), "pve_bootstrap_failed"),
        (RuntimeError("unexpected detail"), "discovery_failed"),
    ):
        captured = {}

        def fail_discovery(cluster, username, password_file, progress=None):
            captured["cluster"] = cluster
            captured["username"] = username
            captured["password_file"] = password_file
            captured["known_hosts_file"] = f"{password_file}.known-hosts"
            cluster["nodes"][0]["host"] = "worker-copy-only"
            with open(captured["known_hosts_file"], "w") as handle:
                handle.write("temporary-host-key")
            raise failure

        with serve._setup_discovery_lock:
            serve._setup_discovery_job = json.loads(json.dumps(base_job))
        with (
            patch("freq.modules.serve.vault_get", return_value="bootstrap-secret"),
            patch("freq.modules.serve.run_setup_discovery", side_effect=fail_discovery),
            patch("freq.modules.serve.update_setup_state") as update_state,
        ):
            assert serve._run_setup_discovery_job(cfg, "job-1") is None
        assert captured["username"] == "operator"
        assert captured["cluster"] is not serve._setup_discovery_job["cluster"]
        assert serve._setup_discovery_job["cluster"]["nodes"][0]["host"] == "10.0.0.1"
        assert not os.path.exists(captured["password_file"])
        assert not os.path.exists(captured["known_hosts_file"])
        update_state.assert_called_once_with(cfg, phase="blocked", last_error_code=expected_code)
        failed = serve._setup_discovery_snapshot()
        assert failed["state"] == "failed"
        assert failed["error"]["code"] == expected_code


def _assert_setup_discovery_admission_contract(cfg, state):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_admit_setup_discovery_job"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "admit_setup_discovery_job"
        for node in service_tree.body
    ) == 1
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_admit_setup_discovery_job"
        for node in ast.walk(serve_tree)
    ) == 1
    assert isinstance(serve._admit_setup_discovery_job, partial)
    assert serve._admit_setup_discovery_job.func is setup_progress.admit_setup_discovery_job
    assert set(serve._admit_setup_discovery_job.keywords) == {"runtime"}
    admission_runtime = serve._admit_setup_discovery_job.keywords["runtime"]
    assert admission_runtime is serve._setup_discovery_admission_runtime
    assert admission_runtime.current_lock() is serve._setup_discovery_lock
    assert admission_runtime.current_job() is serve._setup_discovery_job
    assert setup_progress.SetupDiscoveryAdmission.__dataclass_params__.frozen is True
    assert setup_progress.SetupDiscoveryAdmissionRuntime.__dataclass_params__.frozen is True

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

        def __exit__(self, *_exc):
            assert self.active
            self.active = False
            self.exits += 1

    request_id = "123e4567-e89b-12d3-a456-426614174000"
    original_lock = serve._setup_discovery_lock
    original_job = serve._setup_discovery_job
    admission_lock = ObservedLock()
    thread_calls = []

    class HeldThread:
        def __init__(self, **kwargs):
            thread_calls.append(("init", kwargs))

        def start(self):
            assert serve._setup_discovery_job["state"] == "running"
            thread_calls.append(("start", serve._setup_discovery_job["id"]))

    def invoke(existing, *, candidate_request_id=request_id, expected_error=None):
        serve._setup_discovery_job = existing
        handler = _handler(_request(state["setup_id"], candidate_request_id))

        def store_secret(*_args):
            assert serve._setup_discovery_job is not existing
            assert serve._setup_discovery_job["state"] == "queued"
            return True

        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._observe_setup_state", return_value=state),
            patch("freq.modules.serve.vault_init", return_value=True) as initialize,
            patch("freq.modules.serve.vault_set", side_effect=store_secret) as store,
            patch("freq.modules.serve.vault_get", return_value="write-only") as read,
            patch("freq.modules.serve.update_setup_state") as update_state,
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            if expected_error:
                with pytest.raises(expected_error):
                    handler._serve_setup_discovery_start()
            else:
                handler._serve_setup_discovery_start()
        return handler, initialize, store, read, update_state

    try:
        serve._setup_discovery_lock = admission_lock

        replay_source = {
            "id": "replay-job",
            "setup_id": state["setup_id"],
            "client_request_id": request_id,
            "state": "succeeded",
            "results": {"resources": [{"id": "vm:100"}]},
        }
        handler, initialize, store, read, update_state = invoke(replay_source)
        assert handler._status_code == 202
        assert handler._captured["discovery"]["id"] == "replay-job"
        assert handler._captured["discovery"]["results"] == replay_source["results"]
        assert handler._captured["discovery"]["results"] is not replay_source["results"]
        assert serve._setup_discovery_job is replay_source
        initialize.assert_not_called()
        store.assert_not_called()
        read.assert_not_called()
        update_state.assert_not_called()
        assert thread_calls == []

        active_replay_source = {
            "id": "active-replay-job",
            "setup_id": state["setup_id"],
            "client_request_id": request_id,
            "state": "queued",
        }
        handler, initialize, store, read, update_state = invoke(active_replay_source)
        assert handler._status_code == 202
        assert handler._captured["discovery"]["id"] == "active-replay-job"
        assert serve._setup_discovery_job is active_replay_source
        initialize.assert_not_called()
        store.assert_not_called()
        read.assert_not_called()
        update_state.assert_not_called()
        assert thread_calls == []

        for active_state in ("queued", "running"):
            conflict_source = {
                "id": f"{active_state}-job",
                "setup_id": state["setup_id"],
                "client_request_id": "123e4567-e89b-12d3-a456-426614174001",
                "state": active_state,
            }
            handler, initialize, store, read, update_state = invoke(conflict_source)
            assert handler._status_code == 409
            assert handler._captured["error"]["code"] == "discovery_running"
            assert handler._captured["error"]["retryable"] is True
            assert serve._setup_discovery_job is conflict_source
            initialize.assert_not_called()
            store.assert_not_called()
            read.assert_not_called()
            update_state.assert_not_called()
            assert thread_calls == []

        stale_source = {
            "id": "stale-job",
            "setup_id": "other-setup",
            "client_request_id": request_id,
            "state": "succeeded",
            "results": {"private": "stale"},
        }
        handler, initialize, store, read, update_state = invoke(stale_source)
        assert handler._status_code == 202
        assert handler._captured["discovery"]["id"] != "stale-job"
        assert serve._setup_discovery_job["setup_id"] == state["setup_id"]
        assert serve._setup_discovery_job["client_request_id"] == request_id
        assert "private" not in str(handler._captured)
        initialize.assert_called_once_with(cfg)
        store.assert_called_once()
        read.assert_called_once()
        update_state.assert_called_once()
        assert [kind for kind, _value in thread_calls] == ["init", "start"]

        thread_calls.clear()
        same_setup_without_key = {
            "id": "unkeyed-job",
            "setup_id": state["setup_id"],
            "client_request_id": "",
            "state": "succeeded",
        }
        handler, _initialize, store, _read, _update_state = invoke(
            same_setup_without_key,
            candidate_request_id="",
        )
        assert handler._status_code == 202
        assert handler._captured["discovery"]["id"] != "unkeyed-job"
        assert serve._setup_discovery_job["client_request_id"] == ""
        store.assert_called_once()
        assert [kind for kind, _value in thread_calls] == ["init", "start"]

        thread_calls.clear()
        non_json_source = {
            "id": "private-invalid-job",
            "setup_id": state["setup_id"],
            "client_request_id": request_id,
            "state": "succeeded",
            "private": object(),
        }
        entries = admission_lock.entries
        _handler_result, initialize, store, read, update_state = invoke(
            non_json_source,
            expected_error=TypeError,
        )
        assert admission_lock.entries == entries + 1
        assert admission_lock.exits == admission_lock.entries
        assert admission_lock.active is False
        assert serve._setup_discovery_job is non_json_source
        initialize.assert_not_called()
        store.assert_not_called()
        read.assert_not_called()
        update_state.assert_not_called()
        assert thread_calls == []
    finally:
        serve._setup_discovery_lock = original_lock
        serve._setup_discovery_job = original_job


def _assert_setup_discovery_secret_storage_contract(cfg, state):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_store_setup_discovery_bootstrap_secret"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef)
        and node.name == "store_setup_discovery_bootstrap_secret"
        for node in service_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module == "freq.modules" or (node.module or "").startswith("freq.modules."))
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name == "freq.modules" or alias.name.startswith("freq.modules.")
                for alias in node.names
            )
        )
        for node in ast.walk(service_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_store_setup_discovery_bootstrap_secret"
        for node in ast.walk(serve_tree)
    ) == 1
    assert isinstance(serve._store_setup_discovery_bootstrap_secret, partial)
    assert (
        serve._store_setup_discovery_bootstrap_secret.func
        is setup_progress.store_setup_discovery_bootstrap_secret
    )
    assert set(serve._store_setup_discovery_bootstrap_secret.keywords) == {"runtime"}
    secret_runtime = serve._store_setup_discovery_bootstrap_secret.keywords["runtime"]
    assert secret_runtime is serve._setup_discovery_secret_runtime
    assert setup_progress.SetupDiscoverySecretRuntime.__dataclass_params__.frozen is True
    assert secret_runtime.setup_lock() is serve._setup_lock
    assert secret_runtime.current_lock() is serve._setup_discovery_lock
    assert secret_runtime.current_job() is serve._setup_discovery_job

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

        def __exit__(self, *_exc):
            assert self.active
            self.active = False
            self.exits += 1

    original_setup_lock = serve._setup_lock
    original_job = serve._setup_discovery_job
    original_exists = os.path.exists
    storage_lock = ObservedLock()
    setup_vault_host = f"setup:{state['setup_id']}"

    def invoke(*, vault_exists=False, init_result=True, set_result=True, read_result="write-only"):
        events = []
        thread_calls = []
        serve._setup_discovery_job = None

        class HeldThread:
            def __init__(self, **kwargs):
                thread_calls.append(("init", kwargs))

            def start(self):
                assert serve._setup_discovery_job["state"] == "running"
                thread_calls.append(("start", serve._setup_discovery_job["id"]))

        def initialize(candidate_cfg):
            assert storage_lock.active
            assert candidate_cfg is cfg
            events.append(("init", candidate_cfg))
            if isinstance(init_result, BaseException):
                raise init_result
            return init_result

        def store(candidate_cfg, host, key, value):
            assert storage_lock.active
            events.append(("set", candidate_cfg, host, key, value))
            if callable(set_result):
                return set_result()
            if isinstance(set_result, BaseException):
                raise set_result
            return set_result

        def read(candidate_cfg, host, key):
            assert storage_lock.active
            events.append(("get", candidate_cfg, host, key))
            if isinstance(read_result, BaseException):
                raise read_result
            return read_result

        def persist_state(*args, **kwargs):
            assert not storage_lock.active
            assert [event[0] for event in events][-2:] == ["set", "get"]
            assert serve._setup_discovery_job["state"] == "queued"

        handler = _handler(_request(state["setup_id"]))
        entries = storage_lock.entries
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._observe_setup_state", return_value=state),
            patch(
                "freq.modules.serve.os.path.exists",
                side_effect=lambda path: vault_exists if path == cfg.vault_file else original_exists(path),
            ),
            patch("freq.modules.serve.vault_init", side_effect=initialize),
            patch("freq.modules.serve.vault_set", side_effect=store),
            patch("freq.modules.serve.vault_get", side_effect=read),
            patch("freq.modules.serve.update_setup_state", side_effect=persist_state) as update_state,
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            handler._serve_setup_discovery_start()
        assert storage_lock.entries == entries + 1
        assert storage_lock.exits == storage_lock.entries
        assert storage_lock.active is False
        return handler, events, thread_calls, update_state

    def assert_storage_failure(result, expected_events):
        handler, events, thread_calls, update_state = result
        assert handler._status_code == 500
        assert handler._captured["error"] == {
            "code": "bootstrap_secret_store_failed",
            "message": "Bootstrap secret storage failed.",
            "retryable": False,
        }
        assert "write-only" not in str(handler._captured)
        assert [event[0] for event in events] == expected_events
        update_state.assert_not_called()
        assert thread_calls == []

    try:
        serve._setup_lock = storage_lock

        handler, events, thread_calls, update_state = invoke()
        assert handler._status_code == 202
        assert [event[0] for event in events] == ["init", "set", "get"]
        assert events[1][1:] == (cfg, setup_vault_host, "bootstrap_password", "write-only")
        assert events[2][1:] == (cfg, setup_vault_host, "bootstrap_password")
        assert "write-only" not in str(handler._captured)
        assert "bootstrap_username" not in str(handler._captured)
        update_state.assert_called_once()
        assert [kind for kind, _value in thread_calls] == ["init", "start"]

        handler, events, thread_calls, update_state = invoke(vault_exists=True)
        assert handler._status_code == 202
        assert [event[0] for event in events] == ["set", "get"]
        assert events[0][1:] == (cfg, setup_vault_host, "bootstrap_password", "write-only")
        assert events[1][1:] == (cfg, setup_vault_host, "bootstrap_password")
        update_state.assert_called_once()
        assert [kind for kind, _value in thread_calls] == ["init", "start"]

        assert_storage_failure(invoke(init_result=False), ["init"])
        assert serve._setup_discovery_snapshot() is None
        assert_storage_failure(invoke(set_result=False), ["init", "set"])
        assert serve._setup_discovery_snapshot() is None
        assert_storage_failure(invoke(read_result="mismatch"), ["init", "set", "get"])
        assert serve._setup_discovery_snapshot() is None
        assert_storage_failure(
            invoke(read_result=RuntimeError("private storage detail")),
            ["init", "set", "get"],
        )
        assert serve._setup_discovery_snapshot() is None

        replacement = {
            "id": "replacement-job",
            "setup_id": "replacement-setup",
            "state": "queued",
        }

        def replace_job_then_fail():
            serve._setup_discovery_job = replacement
            raise OSError("private replacement race detail")

        assert_storage_failure(
            invoke(set_result=replace_job_then_fail),
            ["init", "set"],
        )
        assert serve._setup_discovery_job is replacement
    finally:
        serve._setup_lock = original_setup_lock
        serve._setup_discovery_job = original_job


def _assert_setup_discovery_state_publication_contract(cfg, state):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_persist_setup_discovery_state"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "persist_setup_discovery_state"
        for node in service_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module == "freq.modules" or (node.module or "").startswith("freq.modules."))
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name == "freq.modules" or alias.name.startswith("freq.modules.")
                for alias in node.names
            )
        )
        for node in ast.walk(service_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_persist_setup_discovery_state"
        for node in ast.walk(serve_tree)
    ) == 1
    assert isinstance(serve._persist_setup_discovery_state, partial)
    assert serve._persist_setup_discovery_state.func is setup_progress.persist_setup_discovery_state
    assert set(serve._persist_setup_discovery_state.keywords) == {"runtime"}
    state_runtime = serve._persist_setup_discovery_state.keywords["runtime"]
    assert state_runtime is serve._setup_discovery_state_runtime
    assert setup_progress.SetupDiscoveryStateRuntime.__dataclass_params__.frozen is True
    assert state_runtime.current_lock() is serve._setup_discovery_lock
    assert state_runtime.current_job() is serve._setup_discovery_job

    original_job = serve._setup_discovery_job
    setup_vault_host = f"setup:{state['setup_id']}"

    def invoke(state_result=None):
        events = []
        thread_calls = []
        serve._setup_discovery_job = None

        class HeldThread:
            def __init__(self, **kwargs):
                assert serve._setup_discovery_job["state"] == "running"
                thread_calls.append(("init", kwargs))

            def start(self):
                assert serve._setup_discovery_job["state"] == "running"
                thread_calls.append(("start", serve._setup_discovery_job["id"]))

        def store(candidate_cfg, host, key, value):
            assert candidate_cfg is cfg
            events.append(("store", host, key, value))
            return True

        def read(candidate_cfg, host, key):
            assert candidate_cfg is cfg
            events.append(("read", host, key))
            return "write-only"

        def persist(candidate_cfg, **kwargs):
            assert candidate_cfg is cfg
            assert serve._setup_discovery_job["state"] == "queued"
            events.append(("state", kwargs))
            if callable(state_result):
                return state_result()
            if isinstance(state_result, BaseException):
                raise state_result

        def delete(candidate_cfg, host, key):
            assert candidate_cfg is cfg
            events.append(("delete", host, key))

        handler = _handler(_request(state["setup_id"]))
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._observe_setup_state", return_value=state),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", side_effect=store),
            patch("freq.modules.serve.vault_get", side_effect=read),
            patch("freq.modules.serve.vault_delete", side_effect=delete) as delete_secret,
            patch("freq.modules.serve.update_setup_state", side_effect=persist) as update_state,
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            handler._serve_setup_discovery_start()
        return handler, events, thread_calls, update_state, delete_secret

    def assert_state_failure(result):
        handler, events, thread_calls, update_state, delete_secret = result
        assert handler._status_code == 500
        assert handler._captured["error"] == {
            "code": "setup_state_write_failed",
            "message": "Discovery state could not be persisted.",
            "retryable": False,
        }
        assert "write-only" not in str(handler._captured)
        assert "bootstrap_username" not in str(handler._captured)
        assert [event[0] for event in events] == ["store", "read", "state", "delete"]
        update_state.assert_called_once()
        delete_secret.assert_called_once_with(cfg, setup_vault_host, "bootstrap_password")
        assert thread_calls == []

    try:
        handler, events, thread_calls, update_state, delete_secret = invoke()
        assert handler._status_code == 202
        assert [event[0] for event in events] == ["store", "read", "state"]
        update_state.assert_called_once_with(
            cfg,
            phase="discovering",
            active_discovery_id=serve._setup_discovery_job["id"],
            active_contract_id=None,
            last_error_code=None,
        )
        delete_secret.assert_not_called()
        assert [kind for kind, _value in thread_calls] == ["init", "start"]
        assert serve._setup_discovery_job["state"] == "running"

        assert_state_failure(invoke(OSError("private state detail")))
        assert serve._setup_discovery_snapshot() is None
        assert_state_failure(invoke(ValueError("private state value detail")))
        assert serve._setup_discovery_snapshot() is None

        replacement = {
            "id": "replacement-state-job",
            "setup_id": "replacement-setup",
            "state": "queued",
        }

        def replace_job_then_fail():
            serve._setup_discovery_job = replacement
            raise OSError("private state replacement detail")

        assert_state_failure(invoke(replace_job_then_fail))
        assert serve._setup_discovery_job is replacement
        assert serve._setup_discovery_job["state"] == "queued"
    finally:
        serve._setup_discovery_job = original_job


def _assert_setup_discovery_worker_launch_contract(cfg, state):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_launch_setup_discovery_worker"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "launch_setup_discovery_worker"
        for node in service_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module == "freq.modules" or (node.module or "").startswith("freq.modules."))
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name == "freq.modules" or alias.name.startswith("freq.modules.")
                for alias in node.names
            )
        )
        for node in ast.walk(service_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_launch_setup_discovery_worker"
        for node in ast.walk(serve_tree)
    ) == 1
    assert isinstance(serve._launch_setup_discovery_worker, partial)
    assert (
        serve._launch_setup_discovery_worker.func
        is setup_progress.launch_setup_discovery_worker
    )
    assert set(serve._launch_setup_discovery_worker.keywords) == {"runtime"}
    launch_runtime = serve._launch_setup_discovery_worker.keywords["runtime"]
    assert launch_runtime is serve._setup_discovery_launch_runtime
    assert setup_progress.SetupDiscoveryLaunchRuntime.__dataclass_params__.frozen is True
    assert launch_runtime.current_lock() is serve._setup_discovery_lock
    assert launch_runtime.current_job() is serve._setup_discovery_job
    assert launch_runtime.worker_target is serve._run_setup_discovery_job

    original_lock = serve._setup_discovery_lock
    original_job = serve._setup_discovery_job
    setup_vault_host = f"setup:{state['setup_id']}"

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

        def __exit__(self, *_exc):
            assert self.active
            self.active = False
            self.exits += 1

    launch_lock = ObservedLock()

    def invoke(start_result=None, blocked_result=None):
        events = []
        serve._setup_discovery_job = None

        class ObservedJob(dict):
            def __setitem__(self, key, value):
                if key == "state" and value == "running":
                    assert launch_lock.active
                    events.append(("running", self["id"]))
                return super().__setitem__(key, value)

        class HeldThread:
            def __init__(self, **kwargs):
                assert not launch_lock.active
                assert serve._setup_discovery_job["state"] == "running"
                self.kwargs = kwargs
                self.job_id = serve._setup_discovery_job["id"]
                events.append(("thread_init", kwargs, self.job_id))

            def start(self):
                assert serve._setup_discovery_job["state"] == "running"
                events.append(("thread_start", self.job_id))
                if callable(start_result):
                    return start_result()
                if isinstance(start_result, BaseException):
                    raise start_result

        def persist(candidate_cfg, **kwargs):
            assert candidate_cfg is cfg
            events.append(("state", kwargs))
            if kwargs.get("phase") == "discovering":
                assert serve._setup_discovery_job["state"] == "queued"
                serve._setup_discovery_job = ObservedJob(serve._setup_discovery_job)
            elif isinstance(blocked_result, BaseException):
                raise blocked_result

        def delete(candidate_cfg, host, key):
            assert candidate_cfg is cfg
            events.append(("delete", host, key))

        handler = _handler(_request(state["setup_id"]))
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._observe_setup_state", return_value=state),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", return_value=True),
            patch("freq.modules.serve.vault_get", return_value="write-only"),
            patch("freq.modules.serve.vault_delete", side_effect=delete) as delete_secret,
            patch("freq.modules.serve.update_setup_state", side_effect=persist) as update_state,
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            handler._serve_setup_discovery_start()
        return handler, events, delete_secret, update_state

    def assert_start_failure(result):
        handler, events, delete_secret, update_state = result
        assert handler._status_code == 500
        assert handler._captured["error"] == {
            "code": "discovery_start_failed",
            "message": "Discovery worker could not start.",
            "retryable": False,
        }
        assert "private thread detail" not in str(handler._captured)
        assert "write-only" not in str(handler._captured)
        assert "bootstrap_username" not in str(handler._captured)
        delete_secret.assert_called_once_with(cfg, setup_vault_host, "bootstrap_password")
        assert update_state.call_args_list[-1].kwargs == {
            "phase": "blocked",
            "active_discovery_id": None,
            "last_error_code": "discovery_start_failed",
        }
        assert [event[0] for event in events] == [
            "state",
            "running",
            "thread_init",
            "thread_start",
            "delete",
            "state",
        ]
        assert serve._setup_discovery_snapshot() is None

    try:
        serve._setup_discovery_lock = launch_lock

        handler, events, delete_secret, update_state = invoke()
        assert handler._status_code == 202
        assert [event[0] for event in events] == [
            "state",
            "running",
            "thread_init",
            "thread_start",
        ]
        _kind, thread_kwargs, job_id = events[2]
        assert thread_kwargs == {
            "target": serve._run_setup_discovery_job,
            "args": (cfg, job_id),
            "daemon": True,
            "name": f"freq-setup-discovery-{job_id[:12]}",
        }
        assert handler._captured["discovery"] == serve._setup_discovery_payload(
            serve._setup_discovery_snapshot()
        )
        assert handler._captured["discovery"]["state"] == "running"
        delete_secret.assert_not_called()
        assert update_state.call_count == 1
        assert launch_lock.entries == launch_lock.exits
        assert launch_lock.active is False

        assert_start_failure(invoke(RuntimeError("private thread detail")))
        assert_start_failure(
            invoke(RuntimeError("private thread detail"), OSError("private blocked state detail"))
        )
        assert_start_failure(
            invoke(RuntimeError("private thread detail"), ValueError("private blocked value detail"))
        )

        replacement = {
            "id": "replacement-launch-job",
            "setup_id": "replacement-setup",
            "state": "queued",
        }

        def replace_job_then_fail():
            serve._setup_discovery_job = replacement
            raise RuntimeError("private thread replacement detail")

        handler, events, delete_secret, update_state = invoke(replace_job_then_fail)
        assert handler._status_code == 500
        delete_secret.assert_called_once_with(cfg, setup_vault_host, "bootstrap_password")
        assert update_state.call_args_list[-1].kwargs["last_error_code"] == "discovery_start_failed"
        assert [event[0] for event in events] == [
            "state",
            "running",
            "thread_init",
            "thread_start",
            "delete",
            "state",
        ]
        assert serve._setup_discovery_job is replacement
        assert serve._setup_discovery_job["state"] == "queued"
        assert launch_lock.entries == launch_lock.exits
        assert launch_lock.active is False
    finally:
        serve._setup_discovery_lock = original_lock
        serve._setup_discovery_job = original_job


def test_discovery_request_accepts_only_literal_declared_node_ips():
    payload = _request()
    normalized = validate_discovery_request(payload, SCHEMA)
    assert normalized["cluster"]["nodes"] == [{"host": "10.25.255.26", "name": "pve01"}]

    payload["cluster"]["nodes"][0]["host"] = "pve01.example.test"
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "invalid_node_ip"


def test_discovery_request_rejects_non_uuid_idempotency_key():
    payload = _request(request_id="not-a-uuid")
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "invalid_client_request_id"
    assert caught.value.field == "client_request_id"


def test_discovery_request_limits_secret_by_encoded_bytes():
    payload = _request()
    payload["bootstrap"]["password"] = "é" * 2049
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "secret_too_large"
    assert caught.value.field == "bootstrap.password"


def test_discovery_request_has_no_caller_subnet_surface():
    payload = _request()
    payload["cluster"]["subnet"] = "203.0.113.0/24"
    with pytest.raises(DiscoveryInputError) as caught:
        validate_discovery_request(payload, SCHEMA)
    assert caught.value.code == "unsupported_field"
    assert caught.value.field == "cluster.subnet"


def test_derived_networks_are_deduplicated_declared_node_prefixes_only():
    networks = derived_ipv4_networks([
        {"host": "10.25.255.26"},
        {"host": "10.25.255.27"},
        {"host": "10.25.10.1"},
        {"host": "2001:db8::1"},
    ])
    assert [str(network) for network in networks] == ["10.25.255.0/24", "10.25.10.0/24"]


def test_http_identification_disables_proxies_and_redirects():
    source = inspect.getsource(_http_fingerprint)
    assert "ProxyHandler({})" in source
    assert "_NoRedirect" in source
    assert "return None" in source


def test_pve_normalization_distinguishes_vm_container_and_template():
    resources = normalize_pve_resources([
        {"vmid": 100, "name": "app", "node": "pve01", "type": "qemu", "status": "running"},
        {"vmid": 200, "name": "ct", "node": "pve01", "type": "lxc", "status": "running"},
        {"vmid": 9000, "name": "debian", "node": "pve02", "type": "qemu", "template": 1},
    ])
    assert [resource["kind"] for resource in resources] == ["vm", "container", "template"]
    assert [resource["vmid"] for resource in resources] == [100, 200, 9000]
    assert all("suggested_disposition" not in resource for resource in resources)
    assert all("suggested_placement" not in resource for resource in resources)


def test_pve_query_never_leaves_declared_node_list():
    seen = []

    def query(host, _username, _password_file):
        seen.append(host)
        return ([{"vmid": 100, "type": "qemu", "node": "pve01"}], "")

    nodes = [{"host": "10.0.0.1", "name": "pve01"}, {"host": "10.0.0.2", "name": "pve02"}]
    with patch("freq.core.setup_discovery._ssh_cluster_resources", side_effect=query):
        node_rows, resources, warnings = query_declared_pve_nodes(nodes, "operator", "/secret")

    assert seen == ["10.0.0.1", "10.0.0.2"]
    assert all(row["host"] in seen for row in node_rows)
    assert resources[0]["vmid"] == 100
    assert warnings == []


def test_pve_ssh_password_is_stdin_and_never_argv():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as secret:
        secret.write("bootstrap-secret")
        secret_path = secret.name
    captured = {}

    def run(args, **kwargs):
        captured["args"] = args
        captured["stdin"] = kwargs["stdin"].read()
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    try:
        with patch("freq.core.setup_discovery.subprocess.run", side_effect=run):
            resources, error = _ssh_cluster_resources("10.0.0.1", "operator", secret_path)
    finally:
        os.unlink(secret_path)

    assert resources == []
    assert error == ""
    assert captured["stdin"] == "bootstrap-secret"
    assert "bootstrap-secret" not in " ".join(captured["args"])
    assert "10.0.0.1" in " ".join(captured["args"])
    assert "sudo -S" in captured["args"][-1]


def test_empty_but_reachable_pve_cluster_is_successful():
    with patch("freq.core.setup_discovery._ssh_cluster_resources", return_value=([], "")):
        node_rows, resources, warnings = query_declared_pve_nodes(
            [{"host": "10.0.0.1", "name": "pve01"}], "operator", "/secret"
        )
    assert node_rows[0]["reachable"] is True
    assert resources == []
    assert warnings == []


def test_derived_device_scan_reports_credential_free_truth():
    def ping(ip):
        return ip in {"10.0.0.10", "10.0.0.11"}

    def fingerprint(ip):
        return ("truenas", "https") if ip == "10.0.0.10" else ("unknown", "")

    with (
        patch("freq.core.setup_discovery._ping", side_effect=ping),
        patch("freq.core.setup_discovery._http_fingerprint", side_effect=fingerprint),
    ):
        devices, warnings = scan_derived_devices([{"host": "10.0.0.1"}], set())

    assert warnings == []
    assert devices == [
        {
            "id": "device:truenas:10.0.0.10",
            "kind": "truenas",
            "label": "truenas-10-0-0-10",
            "host": "10.0.0.10",
            "source": "credential-free-http",
            "reachable": True,
            "credential_fields": ["username", "password", "api_key"],
        },
        {
            "id": "device:unknown:10.0.0.11",
            "kind": "unknown",
            "label": "unknown-10-0-0-11",
            "host": "10.0.0.11",
            "source": "credential-free-ping",
            "reachable": True,
            "credential_fields": [],
        },
    ]


def test_network_scan_uses_only_nodes_proven_to_be_pve():
    cluster = {
        "name": "dc01",
        "nodes": [
            {"host": "10.0.0.1", "name": "pve01"},
            {"host": "203.0.113.7", "name": "not-pve"},
        ],
    }
    proven = [
        {"id": "pve-node:10.0.0.1", "host": "10.0.0.1", "name": "pve01", "reachable": True, "version": ""},
        {"id": "pve-node:203.0.113.7", "host": "203.0.113.7", "name": "not-pve", "reachable": False, "version": ""},
    ]
    captured = {}

    def scan(nodes, _resource_ips, progress=None):
        captured["nodes"] = nodes
        return [], []

    with (
        patch("freq.core.setup_discovery.query_declared_pve_nodes", return_value=(proven, [], [])),
        patch("freq.core.setup_discovery.scan_derived_devices", side_effect=scan),
    ):
        run_setup_discovery(cluster, "operator", "/secret")

    assert captured["nodes"] == [{"host": "10.0.0.1", "name": "pve01"}]


def test_discovery_start_rejects_nested_subnet_before_probe():
    body = _request()
    body["cluster"]["subnet"] = "203.0.113.0/24"
    handler = _handler(body)
    with patch("freq.modules.serve._check_session_role", return_value=("admin", None)):
        handler._serve_setup_discovery_start()
    assert handler._status_code == 400
    assert handler._captured["error"]["code"] == "manual_contract_not_allowed"
    assert handler._captured["error"]["field"] == "cluster.subnet"


def test_discovery_start_stores_password_but_never_returns_it():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        body = _request(setup_id=state["setup_id"])

        class HeldThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

        handler = _handler(body)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", return_value=True) as store,
            patch("freq.modules.serve.vault_get", return_value="write-only"),
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            handler._serve_setup_discovery_start()

        assert handler._status_code == 202
        assert "write-only" not in str(handler._captured)
        assert "bootstrap_username" not in str(handler._captured)
        store.assert_called_once_with(cfg, f"setup:{state['setup_id']}", "bootstrap_password", "write-only")
        assert handler._captured["discovery"]["state"] == "running"


def test_discovery_start_failure_clears_secret_and_reports_blocked_truth():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        body = _request(setup_id=state["setup_id"])

        class BrokenThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                raise RuntimeError("thread unavailable")

        handler = _handler(body)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", return_value=True),
            patch("freq.modules.serve.vault_get", return_value="write-only"),
            patch("freq.modules.serve.vault_delete") as delete,
            patch("freq.modules.serve.threading.Thread", BrokenThread),
        ):
            handler._serve_setup_discovery_start()

        assert handler._status_code == 500
        assert handler._captured["error"]["code"] == "discovery_start_failed"
        delete.assert_called_once_with(
            cfg,
            f"setup:{state['setup_id']}",
            "bootstrap_password",
        )
        assert serve._setup_discovery_snapshot() is None


def test_discovery_worker_deletes_password_and_tofu_adapter_files():
    _assert_setup_discovery_public_job_contract()
    _assert_setup_discovery_progress_contract()
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        _assert_setup_discovery_admission_contract(cfg, state)
        _assert_setup_discovery_secret_storage_contract(cfg, state)
        _assert_setup_discovery_state_publication_contract(cfg, state)
        _assert_setup_discovery_worker_launch_contract(cfg, state)
        _assert_setup_discovery_worker_contract(cfg, state["setup_id"])
        update_setup_state(cfg, phase="discovering", active_discovery_id="job-1")
        with serve._setup_discovery_lock:
            serve._setup_discovery_job = {
                "id": "job-1",
                "setup_id": state["setup_id"],
                "state": "running",
                "cluster": {"name": "dc01", "nodes": [{"host": "10.0.0.1", "name": "pve01"}]},
                "bootstrap_username": "operator",
                "progress": {},
            }
        captured = {}

        def discover(_cluster, _username, password_file, progress=None):
            captured["password_file"] = password_file
            captured["known_hosts_file"] = f"{password_file}.known-hosts"
            assert os.stat(password_file).st_mode & 0o777 == 0o600
            with open(password_file) as handle:
                assert handle.read() == "bootstrap-secret"
            with open(captured["known_hosts_file"], "w") as handle:
                handle.write("tofu-host-key")
            if progress:
                progress("pve-bootstrap", 1, 1, "Declared PVE node reached.")
            return {"pve_nodes": [], "resources": [], "devices": [], "warnings": []}

        with (
            patch("freq.modules.serve.vault_get", return_value="bootstrap-secret"),
            patch("freq.modules.serve.run_setup_discovery", side_effect=discover),
        ):
            serve._run_setup_discovery_job(cfg, "job-1")

        assert not os.path.exists(captured["password_file"])
        assert not os.path.exists(captured["known_hosts_file"])
        snapshot = serve._setup_discovery_snapshot()
        assert snapshot["state"] == "succeeded"
        assert "bootstrap-secret" not in str(snapshot)


def _assert_setup_discovery_status_resolution_contract(cfg, state):
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_resolve_setup_discovery_status"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "resolve_setup_discovery_status"
        for node in service_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module == "freq.modules" or (node.module or "").startswith("freq.modules."))
        )
        or (
            isinstance(node, ast.Import)
            and any(
                alias.name == "freq.modules" or alias.name.startswith("freq.modules.")
                for alias in node.names
            )
        )
        for node in ast.walk(service_tree)
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_resolve_setup_discovery_status"
        for node in ast.walk(serve_tree)
    ) == 1
    assert (
        serve._resolve_setup_discovery_status
        is setup_progress.resolve_setup_discovery_status
    )
    assert setup_progress.SetupDiscoveryStatusResolution.__dataclass_params__.frozen is True

    def invoke(path, snapshot, *, active_discovery_id=None):
        current_state = dict(state)
        current_state["active_discovery_id"] = active_discovery_id
        handler = _handler(path=path, command="GET")
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve._zero_state_setup_complete", return_value=False),
            patch("freq.modules.serve._observe_setup_state", return_value=current_state),
            patch("freq.modules.serve._setup_discovery_snapshot", return_value=snapshot) as read_job,
            patch(
                "freq.modules.serve._setup_discovery_payload",
                wraps=setup_progress.project_discovery_job,
            ) as project_job,
        ):
            handler._serve_setup_discovery_status()
        return handler, read_job, project_job

    handler, read_job, project_job = invoke(
        "/api/setup/discovery/status",
        {"id": "private-unread-job"},
    )
    assert handler._status_code == 400
    assert handler._captured["error"] == {
        "code": "required_field",
        "message": "Discovery id is required.",
        "retryable": False,
        "field": "id",
    }
    read_job.assert_not_called()
    project_job.assert_not_called()

    handler, read_job, project_job = invoke(
        "/api/setup/discovery/status?id=job-1",
        None,
        active_discovery_id="job-1",
    )
    assert handler._status_code == 410
    assert handler._captured["error"]["code"] == "discovery_expired"
    read_job.assert_called_once_with()
    project_job.assert_not_called()

    handler, read_job, project_job = invoke(
        "/api/setup/discovery/status?id=job-1",
        None,
        active_discovery_id="other-job",
    )
    assert handler._status_code == 404
    assert handler._captured["error"]["code"] == "discovery_not_found"
    read_job.assert_called_once_with()
    project_job.assert_not_called()

    base_job = {
        "id": "job-1",
        "setup_id": state["setup_id"],
        "state": "succeeded",
        "started_at": "2026-07-21T00:00:00+00:00",
        "updated_at": "2026-07-21T00:00:01+00:00",
        "finished_at": "2026-07-21T00:00:01+00:00",
        "poll_after_ms": 0,
        "progress": {"phase": "complete", "current": 1, "total": 1},
        "results": {"resources": [{"id": "vm-100"}]},
        "bootstrap_username": "private-operator",
        "cluster": {"nodes": [{"host": "private-node"}]},
    }

    handler, read_job, project_job = invoke(
        "/api/setup/discovery/status?id=job-1",
        {**base_job, "id": "other-job"},
        active_discovery_id="job-1",
    )
    assert handler._status_code == 404
    assert handler._captured["error"]["code"] == "discovery_not_found"
    read_job.assert_called_once_with()
    project_job.assert_not_called()

    handler, read_job, project_job = invoke(
        "/api/setup/discovery/status?id=job-1",
        {**base_job, "setup_id": "other-setup"},
        active_discovery_id="job-1",
    )
    assert handler._status_code == 404
    assert handler._captured["error"]["code"] == "discovery_not_found"
    read_job.assert_called_once_with()
    project_job.assert_not_called()

    handler, read_job, project_job = invoke(
        "/api/setup/discovery/status?id=%20job-1%20",
        base_job,
        active_discovery_id="job-1",
    )
    assert handler._status_code == 200
    assert handler._captured == {
        "ok": True,
        "schema": SCHEMA,
        "discovery": setup_progress.project_discovery_job(base_job),
    }
    assert "private-operator" not in str(handler._captured)
    assert "private-node" not in str(handler._captured)
    read_job.assert_called_once_with()
    project_job.assert_called_once_with(base_job)


def test_discovery_status_returns_410_when_active_job_was_lost():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        update_setup_state(cfg, phase="discovering", active_discovery_id="lost-job")
        handler = _handler(path="/api/setup/discovery/status?id=lost-job", command="GET")
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
        ):
            handler._serve_setup_discovery_status()

        assert handler._status_code == 410
        assert handler._captured["error"]["code"] == "discovery_expired"
        assert state["setup_id"] == load_setup_id(cfg)
        _assert_setup_discovery_status_resolution_contract(cfg, state)


def test_discovery_status_rejects_admin_who_does_not_own_setup():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        handler = _handler(path="/api/setup/discovery/status?id=job-1", command="GET")
        handler._session_user = "other-admin"
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
        ):
            handler._serve_setup_discovery_status()

        assert handler._status_code == 403
        assert handler._captured["error"]["code"] == "setup_owner_mismatch"
        assert state["username"] == "operator"


def test_idempotency_replay_is_bound_to_current_setup_identity():
    with tempfile.TemporaryDirectory() as root:
        cfg = _cfg(root)
        state = ensure_setup_state(cfg, "operator")
        body = _request(setup_id=state["setup_id"])
        with serve._setup_discovery_lock:
            serve._setup_discovery_job = {
                "id": "stale-job",
                "setup_id": "different-setup",
                "client_request_id": body["client_request_id"],
                "state": "succeeded",
                "results": {"resources": [{"id": "private-stale-result"}]},
            }

        class HeldThread:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                pass

        handler = _handler(body)
        with (
            patch("freq.modules.serve._check_session_role", return_value=("admin", None)),
            patch("freq.modules.serve.load_config", return_value=cfg),
            patch("freq.modules.serve.vault_init", return_value=True),
            patch("freq.modules.serve.vault_set", return_value=True),
            patch("freq.modules.serve.vault_get", return_value="write-only"),
            patch("freq.modules.serve.threading.Thread", HeldThread),
        ):
            handler._serve_setup_discovery_start()

        assert handler._status_code == 202
        assert handler._captured["discovery"]["id"] != "stale-job"
        assert "private-stale-result" not in str(handler._captured)


def load_setup_id(cfg):
    from freq.core.setup_state import load_setup_state

    return load_setup_state(cfg)["setup_id"]


def test_discovery_routes_require_auth_and_csrf():
    for route in ("/api/setup/discovery/start", "/api/setup/discovery/status"):
        assert route not in FreqHandler._AUTH_WHITELIST
    assert "/api/setup/discovery/start" not in FreqHandler._CSRF_EXEMPT
