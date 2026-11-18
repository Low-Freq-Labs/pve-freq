"""Zero-state browser init must stay value-only and preserve frozen truth."""

import ast
import copy
import inspect
import io
import os
import shlex
import stat
import subprocess
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from freq.api import auth
from freq.core.setup_contract import (
    SetupContractError,
    credential_storage_value,
    credential_vault_key,
)
from freq.core.setup_state import ensure_setup_state, setup_state_path
from freq.modules.init_cmd import _device_creds_for_host, _load_device_credentials
from freq.modules.serve import (
    ZERO_STATE_WEB_SCHEMA,
    FreqHandler,
    _setup_init_command_from_contract,
    _setup_init_request,
)


def _objects():
    setup_id = "setup-1"
    discovery_id = "discovery-1"
    contract_id = "contract-1"
    state = {"setup_id": setup_id}
    discovery = {
        "id": discovery_id,
        "setup_id": setup_id,
        "state": "succeeded",
        "bootstrap_username": "freq-ops",
        "cluster": {
            "name": "dc01",
            "nodes": [
                {"host": "10.25.0.11", "name": "pve01"},
                {"host": "10.25.0.12", "name": "pve02"},
            ],
        },
    }
    resources = ["device:idrac:10.25.0.21", "device:idrac:10.25.0.22"]
    contract = {
        "schema": ZERO_STATE_WEB_SCHEMA,
        "setup_id": setup_id,
        "discovery_id": discovery_id,
        "contract_id": contract_id,
        "owned_vmids": [100, 101],
        "template_vmids": [9000],
        "acknowledged_out_of_contract_vmids": [777],
        "acknowledged_devices": [
            {
                "resource_id": "device:unknown:10.25.0.99",
                "kind": "unknown",
                "host": "10.25.0.99",
                "label": "unknown-99",
            }
        ],
        "owned_devices": [
            {
                "resource_id": resource,
                "kind": "idrac",
                "host": f"10.25.0.2{index}",
                "label": f"idrac-{index}",
                "placement": "production",
            }
            for index, resource in enumerate(resources, 1)
        ],
        "credential_requirements": [
            {
                "resource_id": resource,
                "kind": "idrac",
                "required_any": [["username", "password"]],
                "allowed_fields": ["username", "password"],
            }
            for resource in resources
        ],
    }
    body = {
        "schema": ZERO_STATE_WEB_SCHEMA,
        "setup_id": setup_id,
        "discovery_id": discovery_id,
        "contract_id": contract_id,
        "client_request_id": str(uuid.uuid4()),
        "service_account": {"username": "freq-admin", "password": "long-password"},
        "options": {
            "ssh_mode": "sudo",
            "pdm": {"mode": "skip"},
            "ssl": {"mode": "defer"},
        },
    }
    return state, discovery, contract, body, resources


def _assert_setup_contract_vault_reader_contract():
    from freq.api import auth
    from freq.modules import serve
    from freq.services import setup_progress

    assert serve._setup_vault_host is auth._setup_vault_host
    assert serve._setup_contract_getter is auth._setup_contract_getter
    serve_tree = ast.parse(inspect.getsource(serve))
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name in {"_setup_vault_host", "_setup_contract_getter"}
        for node in serve_tree.body
    )
    serve_vault_host_calls = sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_vault_host"
        for node in ast.walk(serve_tree)
    )
    serve_getter_calls = sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_contract_getter"
        for node in ast.walk(serve_tree)
    )
    service_tree = ast.parse(inspect.getsource(setup_progress))
    service_getter_calls = sum(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "build_getter")
            or (
                isinstance(node.func, ast.Attribute)
                and ast.unparse(node.func) == "runtime.build_getter"
            )
        )
        for node in ast.walk(service_tree)
    )
    service_vault_host_calls = sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func) == "runtime.vault_host"
        for node in ast.walk(service_tree)
    )
    assert serve_vault_host_calls == 3
    assert service_vault_host_calls == 2
    assert serve_getter_calls == 3
    assert service_getter_calls == 3
    assert serve_getter_calls + service_getter_calls == 6
    auth_tree = ast.parse(inspect.getsource(auth))
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_contract_getter"
        for node in ast.walk(auth_tree)
    ) == 1
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_vault_host"
        for node in ast.walk(auth_tree)
    ) == 4
    assert sum(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            name.startswith("freq.modules")
            for name in (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
        )
        for node in ast.walk(auth_tree)
    ) == 1

    assert serve._setup_vault_host("") == "setup:"
    assert serve._setup_vault_host(" setup ") == "setup: setup "
    assert serve._setup_vault_host("site:contract") == "setup:site:contract"

    cfg = object()
    setup_id = object()
    first = object()
    final = object()
    ignored = object()
    entries = [
        ("setup:selected", "identity", first),
        ("setup:other", "ignored", ignored),
        ("setup:selected", "duplicate", first),
        ("setup:selected", "duplicate", final),
        ("setup:selected", "falsey", 0),
        ("setup:selected", "none", None),
    ]
    with patch.object(
        auth, "_setup_vault_host", return_value="setup:selected"
    ) as vault_host, patch.object(auth, "vault_list", return_value=entries) as vault_list:
        getter = serve._setup_contract_getter(cfg, setup_id)

    vault_host.assert_called_once_with(setup_id)
    vault_list.assert_called_once_with(cfg)
    assert getter("identity") is first
    assert getter("duplicate") is final
    assert getter("falsey") == 0
    assert getter("none") is None
    assert getter("ignored") == ""
    assert getter("missing") == ""

    entries[:] = [("setup:selected", "identity", ignored)]
    assert getter("identity") is first

    host_error = RuntimeError("namespace failed")
    with patch.object(
        auth, "_setup_vault_host", side_effect=host_error
    ), patch.object(auth, "vault_list") as vault_list:
        with pytest.raises(RuntimeError) as caught:
            serve._setup_contract_getter(cfg, setup_id)
    assert caught.value is host_error
    vault_list.assert_not_called()

    list_error = OSError("vault snapshot failed")
    with patch.object(
        auth, "_setup_vault_host", return_value="setup:selected"
    ), patch.object(auth, "vault_list", side_effect=list_error):
        with pytest.raises(OSError) as caught:
            serve._setup_contract_getter(cfg, setup_id)
    assert caught.value is list_error


def _assert_setup_init_command_from_contract_owner():
    from freq.api import auth
    from freq.modules import serve
    from freq.services import setup_inputs

    serve_tree = ast.parse(inspect.getsource(serve))
    auth_tree = ast.parse(inspect.getsource(auth))
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_setup_init_command_from_contract"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef)
        and node.name == "setup_init_command_from_contract"
        for node in auth_tree.body
    ) == 1
    assert auth.resolved_bootstrap_username is setup_inputs.resolved_bootstrap_username
    assert (
        serve._setup_init_command_from_contract
        is auth.setup_init_command_from_contract
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_init_command_from_contract"
        for node in ast.walk(serve_tree)
    ) == 1

    cfg = SimpleNamespace(
        data_dir="/owner/data",
        install_dir="/opt/pve-freq-owner",
    )
    contract = {"setup_id": "setup-owner"}
    base_request = {
        "service_account": {
            "username": "freq-owner",
            "password": "service-owner-secret",
        },
        "ssh_mode": "sudo",
        "pdm_mode": "install",
        "pdm_password": "pdm-owner-secret",
    }
    base_discovery = {
        "bootstrap_username": "bootstrap-owner",
        "cluster": {
            "name": "owner-cluster",
            "nodes": [
                {"host": "10.25.0.11", "name": "pve-owner-a"},
                {"name": "ignored-without-host"},
                {"host": "10.25.0.12"},
            ],
        },
    }

    def invoke(
        *,
        request=None,
        discovery=None,
        bootstrap_password="bootstrap-owner-secret",
        device_file="/owner/secrets/device-credentials.toml",
        euid=0,
        vm_error=None,
        trace=None,
    ):
        events = trace if trace is not None else []
        secret_dir = "/owner/secrets/job-owner"

        def setup_secret_dir(actual_cfg, job_id):
            events.append(("secret_dir", actual_cfg, job_id))
            return secret_dir

        def write_secret(actual_dir, name, value):
            events.append(("secret", actual_dir, name, value))
            return f"{actual_dir}/{name}" if value else ""

        def setup_vault_host(setup_id):
            events.append(("vault_host", setup_id))
            return f"setup:{setup_id}"

        def read_vault(actual_cfg, host, key):
            events.append(("vault_get", actual_cfg, host, key))
            return bootstrap_password

        def write_vm_contract(actual_dir, actual_contract):
            events.append(("vm_contract", actual_dir, actual_contract))
            if vm_error is not None:
                raise vm_error
            return f"{actual_dir}/vm-contract.toml"

        def write_device_credentials(actual_cfg, actual_dir, actual_contract):
            events.append(
                ("device_credentials", actual_cfg, actual_dir, actual_contract)
            )
            return device_file

        cleanup = MagicMock(
            side_effect=lambda path, **kwargs: events.append(
                ("cleanup", path, kwargs)
            )
        )
        with patch.object(auth, "setup_secret_dir", side_effect=setup_secret_dir), patch.object(
            auth, "write_setup_secret", side_effect=write_secret
        ), patch.object(
            auth, "_setup_vault_host", side_effect=setup_vault_host
        ), patch.object(
            auth, "vault_get", side_effect=read_vault
        ), patch.object(
            auth, "write_vm_contract", side_effect=write_vm_contract
        ), patch.object(
            auth,
            "write_setup_contract_credentials",
            side_effect=write_device_credentials,
        ), patch.object(
            auth.os, "environ", {"OWNER_ENV": "preserved"}
        ), patch.object(
            auth.os, "geteuid", return_value=euid
        ), patch.object(
            auth.shutil, "rmtree", cleanup
        ):
            result = serve._setup_init_command_from_contract(
                cfg,
                copy.deepcopy(request or base_request),
                contract,
                copy.deepcopy(discovery or base_discovery),
                "job-owner",
            )
        return result, events, cleanup

    (cmd, env, secret_dir), events, cleanup = invoke()
    code = "import sys; from freq.cli import main; raise SystemExit(main(sys.argv[1:]))"
    assert cmd == [
        sys.executable,
        "-c",
        code,
        "--yes",
        "init",
        "--headless",
        "--password-file",
        "/owner/secrets/job-owner/service-account-password",
        "--bootstrap-user",
        "bootstrap-owner",
        "--bootstrap-password-file",
        "/owner/secrets/job-owner/bootstrap-password",
        "--service-account",
        "freq-owner",
        "--pve-nodes",
        "10.25.0.11,10.25.0.12",
        "--pve-node-names",
        "pve-owner-a,10.25.0.12",
        "--cluster-name",
        "owner-cluster",
        "--ssh-mode",
        "sudo",
        "--vm-contract",
        "/owner/secrets/job-owner/vm-contract.toml",
        "--device-credentials",
        "/owner/secrets/device-credentials.toml",
        "--install-pdm",
        "--pdm-pass",
        "/owner/secrets/job-owner/pdm-password",
    ]
    assert env == {
        "OWNER_ENV": "preserved",
        "FREQ_DIR": "/opt/pve-freq-owner",
        "FREQ_WEB_INIT": "1",
        "PYTHONUNBUFFERED": "1",
    }
    assert secret_dir == "/owner/secrets/job-owner"
    assert events == [
        ("secret_dir", cfg, "job-owner"),
        (
            "secret",
            secret_dir,
            "service-account-password",
            "service-owner-secret",
        ),
        ("vault_host", "setup-owner"),
        ("vault_get", cfg, "setup:setup-owner", "bootstrap_password"),
        (
            "secret",
            secret_dir,
            "bootstrap-password",
            "bootstrap-owner-secret",
        ),
        ("vm_contract", secret_dir, contract),
        ("device_credentials", cfg, secret_dir, contract),
        ("secret", secret_dir, "pdm-password", "pdm-owner-secret"),
    ]
    cleanup.assert_not_called()

    skip_request = copy.deepcopy(base_request)
    skip_request.update({"pdm_mode": "skip", "pdm_password": ""})
    fallback_discovery = {"cluster": {"nodes": [{"host": "pve-fallback"}]}}
    (fallback_cmd, fallback_env, _), fallback_events, cleanup = invoke(
        request=skip_request,
        discovery=fallback_discovery,
        device_file="",
        euid=1000,
    )
    assert fallback_cmd[:6] == [
        "sudo",
        "-n",
        "env",
        "FREQ_DIR=/opt/pve-freq-owner",
        "FREQ_WEB_INIT=1",
        "PYTHONUNBUFFERED=1",
    ]
    assert fallback_cmd[6:9] == [sys.executable, "-c", code]
    assert fallback_cmd[fallback_cmd.index("--bootstrap-user") + 1] == "root"
    assert fallback_cmd[fallback_cmd.index("--cluster-name") + 1] == "pve"
    assert fallback_cmd[fallback_cmd.index("--pve-nodes") + 1] == "pve-fallback"
    assert fallback_cmd[fallback_cmd.index("--pve-node-names") + 1] == "pve-fallback"
    assert "--skip-pdm" in fallback_cmd
    assert "--install-pdm" not in fallback_cmd
    assert "--pdm-pass" not in fallback_cmd
    assert "--device-credentials" not in fallback_cmd
    assert fallback_env["OWNER_ENV"] == "preserved"
    assert fallback_events[-1] == ("secret", secret_dir, "pdm-password", "")
    cleanup.assert_not_called()

    bootstrap_events = []
    with pytest.raises(SetupContractError) as caught:
        invoke(bootstrap_password="", trace=bootstrap_events)
    assert caught.value.code == "bootstrap_secret_missing"
    assert caught.value.status == 409
    assert caught.value.field == ""
    assert str(caught.value) == "Bootstrap credentials expired; run discovery again."
    assert bootstrap_events[-1] == (
        "cleanup",
        secret_dir,
        {"ignore_errors": True},
    )
    assert not any(event[0] == "vm_contract" for event in bootstrap_events)

    empty_discovery = {"cluster": {"nodes": [{"name": "missing-host"}]}}
    empty_events = []
    with pytest.raises(SetupContractError) as caught:
        invoke(discovery=empty_discovery, trace=empty_events)
    assert caught.value.code == "stale_discovery"
    assert caught.value.status == 409
    assert caught.value.field == "discovery_id"
    assert str(caught.value) == "Discovery has no PVE nodes."
    assert empty_events[-1] == (
        "cleanup",
        secret_dir,
        {"ignore_errors": True},
    )
    assert any(event[0] == "device_credentials" for event in empty_events)

    writer_error = OSError("VM contract owner failure")
    writer_events = []
    with pytest.raises(OSError) as caught:
        invoke(vm_error=writer_error, trace=writer_events)
    assert caught.value is writer_error
    assert writer_events[-1] == (
        "cleanup",
        secret_dir,
        {"ignore_errors": True},
    )
    assert not any(event[0] == "device_credentials" for event in writer_events)


def test_init_request_rejects_all_browser_paths_and_stale_ids():
    state, discovery, contract, body, _resources = _objects()
    from freq.modules import serve
    from freq.services import setup_inputs

    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_inputs))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_setup_init_request"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "validate_init_request"
        for node in service_tree.body
    ) == 1
    assert serve._setup_init_request is setup_inputs.validate_init_request
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_init_request"
        for node in ast.walk(serve_tree)
    ) == 1
    assert not any(
        isinstance(node, ast.ImportFrom)
        and str(node.module or "").startswith("freq.modules")
        for node in ast.walk(service_tree)
    )

    def rejected(
        candidate,
        code,
        field="",
        status=400,
        *,
        current_state=None,
        current_contract=None,
    ):
        with pytest.raises(SetupContractError) as caught:
            _setup_init_request(
                candidate,
                state if current_state is None else current_state,
                contract if current_contract is None else current_contract,
                discovery,
            )
        assert caught.value.code == code
        assert caught.value.field == field
        assert caught.value.status == status

    rejected(None, "invalid_json")
    rejected(
        {**body, "vm_contract": "/tmp/operator.toml"},
        "unsupported_field",
        "vm_contract",
    )
    rejected({**body, "schema": "wrong"}, "unsupported_schema", "schema")
    rejected({**body, "setup_id": "old"}, "setup_expired", "setup_id", 410)
    rejected(body, "setup_expired", "setup_id", 410, current_state={})
    rejected({**body, "discovery_id": "old"}, "stale_discovery", "discovery_id", 409)
    rejected({**body, "contract_id": "old"}, "stale_contract", "contract_id", 409)
    rejected(
        {**body, "client_request_id": "not-a-uuid"},
        "invalid_client_request_id",
        "client_request_id",
    )
    rejected({**body, "service_account": None}, "required_field", "service_account")
    rejected(
        {**body, "service_account": {**body["service_account"], "token": "forbidden"}},
        "unsupported_field",
        "service_account.token",
    )
    rejected(
        {**body, "service_account": {**body["service_account"], "username": "Root"}},
        "invalid_service_account",
        "service_account.username",
        422,
    )
    equal_service = copy.deepcopy(body)
    equal_service["service_account"]["username"] = discovery["bootstrap_username"]
    rejected(
        equal_service,
        "service_account_matches_bootstrap",
        "service_account.username",
        422,
    )
    absent_bootstrap = copy.deepcopy(discovery)
    absent_bootstrap.pop("bootstrap_username")
    root_service = copy.deepcopy(body)
    root_service["service_account"]["username"] = "root"
    with pytest.raises(SetupContractError) as caught:
        _setup_init_request(root_service, state, contract, absent_bootstrap)
    assert caught.value.code == "service_account_matches_bootstrap"
    assert caught.value.field == "service_account.username"
    assert caught.value.status == 422
    assert setup_inputs.resolved_bootstrap_username(absent_bootstrap) == "root"
    for invalid_password in (
        None,
        7,
        "short",
        "x" * 4097,
        "bad\x00value",
        "bad\nvalue",
        "bad\rvalue",
    ):
        candidate = copy.deepcopy(body)
        candidate["service_account"]["password"] = invalid_password
        rejected(candidate, "invalid_service_password", "service_account.password", 422)
    long_idrac_password = copy.deepcopy(body)
    long_idrac_password["service_account"]["password"] = "x" * 21
    rejected(
        long_idrac_password,
        "service_password_device_limit",
        "service_account.password",
        422,
    )

    rejected({**body, "options": ["invalid"]}, "invalid_options", "options")
    rejected(
        {**body, "options": {**body["options"], "manual_path": "forbidden"}},
        "unsupported_field",
        "options.manual_path",
    )
    invalid_ssh = copy.deepcopy(body)
    invalid_ssh["options"]["ssh_mode"] = "root"
    rejected(invalid_ssh, "invalid_ssh_mode", "options.ssh_mode", 422)
    invalid_pdm_shape = copy.deepcopy(body)
    invalid_pdm_shape["options"]["pdm"] = ["invalid"]
    rejected(invalid_pdm_shape, "invalid_pdm_options", "options.pdm", 422)
    invalid_pdm_field = copy.deepcopy(body)
    invalid_pdm_field["options"]["pdm"] = {"mode": "skip", "path": "/tmp/pdm"}
    rejected(invalid_pdm_field, "invalid_pdm_options", "options.pdm", 422)
    invalid_ssl_shape = copy.deepcopy(body)
    invalid_ssl_shape["options"]["ssl"] = {"mode": "defer", "path": "/tmp/tls"}
    rejected(invalid_ssl_shape, "invalid_ssl_options", "options.ssl", 422)
    invalid_pdm_mode = copy.deepcopy(body)
    invalid_pdm_mode["options"]["pdm"] = {"mode": "later"}
    rejected(invalid_pdm_mode, "invalid_pdm_mode", "options.pdm.mode", 422)
    invalid_ssl_mode = copy.deepcopy(body)
    invalid_ssl_mode["options"]["ssl"] = {"mode": "manual"}
    rejected(invalid_ssl_mode, "invalid_ssl_mode", "options.ssl.mode", 422)
    for invalid_pdm_password in (
        None,
        7,
        "",
        "x" * 4097,
        "bad\x00value",
        "bad\nvalue",
        "bad\rvalue",
    ):
        candidate = copy.deepcopy(body)
        candidate["options"]["pdm"] = {"mode": "install", "password": invalid_pdm_password}
        rejected(candidate, "required_field", "options.pdm.password", 422)
    skip_with_password = copy.deepcopy(body)
    skip_with_password["options"]["pdm"]["password"] = "not-accepted"
    rejected(skip_with_password, "unsupported_field", "options.pdm.password", 422)

    defaulted = _setup_init_request({**body, "options": {}}, state, contract, discovery)
    assert defaulted == {
        "client_request_id": body["client_request_id"],
        "service_account": body["service_account"],
        "ssh_mode": "sudo",
        "pdm_mode": "skip",
        "pdm_password": "",
    }
    install = copy.deepcopy(body)
    install["client_request_id"] = f"  {body['client_request_id']}  "
    install["service_account"] = {"username": " freq-admin ", "password": "x" * 21}
    install["options"] = {
        "ssh_mode": " SUDO ",
        "pdm": {"mode": " INSTALL ", "password": "pdm-password"},
        "ssl": {"mode": " DEFER "},
    }
    non_idrac = copy.deepcopy(contract)
    for device in non_idrac["owned_devices"]:
        device["kind"] = "switch"
    assert _setup_init_request(install, state, non_idrac, discovery) == {
        "client_request_id": body["client_request_id"],
        "service_account": {"username": "freq-admin", "password": "x" * 21},
        "ssh_mode": "sudo",
        "pdm_mode": "install",
        "pdm_password": "pdm-password",
    }
    _assert_setup_init_start_admission_contract(state, discovery, contract, body)


def _assert_setup_init_start_admission_contract(state, discovery, contract, body):
    from freq.modules import serve
    from freq.services import setup_progress

    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_start_setup_init"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "start_setup_init"
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
        and node.func.id == "_start_setup_init"
        for node in ast.walk(serve_tree)
    ) == 1
    assert serve._start_setup_init.func is setup_progress.start_setup_init
    assert (
        serve._start_setup_init.keywords["runtime"]
        is serve._setup_init_start_runtime
    )
    assert setup_progress.SetupInitStartRuntime.__dataclass_params__.frozen is True
    assert setup_progress.SetupInitStartResult.__dataclass_params__.frozen is True

    state = {
        **state,
        "username": "operator",
        "active_discovery_id": discovery["id"],
        "active_contract_id": contract["contract_id"],
    }
    normalized = {
        "client_request_id": body["client_request_id"],
        "service_account": body["service_account"],
        "ssh_mode": "sudo",
        "pdm_mode": "skip",
        "pdm_password": "",
    }
    cfg = SimpleNamespace(data_dir="/private/setup-state")
    command = ["python", "-m", "freq", "init", "--headless"]
    environment = {"FREQ_WEB_INIT": "1"}
    secret_dir = "/private/setup-state/secrets/setup-init/job-new"
    expected_job = {
        "id": "job-new",
        "setup_id": state["setup_id"],
        "owner": state["username"],
        "client_request_id": normalized["client_request_id"],
        "state": "queued",
        "pid": None,
        "started_at": 123.0,
        "updated_at": 123.0,
        "finished_at": None,
        "returncode": None,
        "initialized": False,
        "web_setup_complete": False,
        "progress": {
            "phase": 0,
            "phase_name": "Queued",
            "current": 0,
            "total": 12,
            "message": "Initialization queued.",
        },
        "lines": ["starting web-launched freq init --headless"],
    }

    def handler_for(request=body):
        handler = FreqHandler.__new__(FreqHandler)
        handler.command = "POST"
        handler.path = "/api/setup/init/start"
        handler.headers = {}
        handler.rfile = io.BytesIO()
        handler._session_user = "operator"
        handler._request_body = lambda: request
        handler._captured = None
        handler._status_code = None

        def respond(payload, status=200):
            handler._captured = payload
            handler._status_code = status

        handler._json_response = respond
        return handler

    def invoke(
        *,
        current_state=state,
        current_contract=contract,
        current_discovery=discovery,
        ready=True,
        existing=None,
        prepare_error=None,
        start_error=None,
    ):
        handler = handler_for()
        worker = MagicMock()
        worker.start.side_effect = start_error
        update_snapshots = []

        def update_state(*args, **kwargs):
            update_snapshots.append(copy.deepcopy(serve._setup_init_job))
            if prepare_error is not None and len(update_snapshots) == 1:
                raise prepare_error

        original_job = serve._setup_init_job
        try:
            with serve._setup_init_lock:
                serve._setup_init_job = copy.deepcopy(existing)
            with (
                patch.object(serve, "_check_session_role", return_value=("admin", None)),
                patch.object(serve, "load_config", return_value=cfg),
                patch.object(serve, "_zero_state_setup_complete", return_value=False),
                patch.object(
                    serve,
                    "_observe_setup_state",
                    side_effect=[state, current_state],
                ) as observe_state,
                patch.object(
                    serve,
                    "load_setup_contract",
                    return_value=current_contract,
                ) as load_contract,
                patch.object(
                    serve,
                    "_setup_discovery_snapshot",
                    return_value=current_discovery,
                ) as snapshot_discovery,
                patch.object(
                    serve,
                    "_setup_contract_getter",
                    return_value=lambda _key: "private-credential",
                ) as build_getter,
                patch.object(
                    serve,
                    "contract_payload",
                    return_value={"ready": ready},
                ) as project_contract,
                patch.object(
                    serve,
                    "_setup_init_request",
                    return_value=normalized,
                ) as validate_request,
                patch.object(
                    serve,
                    "_setup_init_command_from_contract",
                    return_value=(command, environment, secret_dir),
                ) as prepare_command,
                patch.object(
                    serve,
                    "_setup_init_public_job",
                    return_value={"id": "job-existing", "state": "running"},
                ) as project_job,
                patch.object(serve, "update_setup_state", side_effect=update_state) as update,
                patch.object(serve.shutil, "rmtree") as remove_tree,
                patch.object(serve.threading, "Thread", return_value=worker) as thread,
                patch.object(serve.uuid, "uuid4", return_value=SimpleNamespace(hex="job-new")),
                patch.object(serve.time, "time", return_value=123.0),
            ):
                handler._serve_setup_init_start()
            with serve._setup_init_lock:
                published = copy.deepcopy(serve._setup_init_job)
        finally:
            with serve._setup_init_lock:
                serve._setup_init_job = original_job
        return SimpleNamespace(
            handler=handler,
            worker=worker,
            observe_state=observe_state,
            load_contract=load_contract,
            snapshot_discovery=snapshot_discovery,
            build_getter=build_getter,
            project_contract=project_contract,
            validate_request=validate_request,
            prepare_command=prepare_command,
            project_job=project_job,
            update=update,
            update_snapshots=update_snapshots,
            remove_tree=remove_tree,
            thread=thread,
            published=published,
        )

    lost = invoke(current_state=None)
    assert lost.handler._status_code == 410
    assert lost.handler._captured["error"]["code"] == "setup_expired"
    lost.validate_request.assert_not_called()
    lost.prepare_command.assert_not_called()
    lost.thread.assert_not_called()

    wrong_owner = invoke(current_state={**state, "username": "other-operator"})
    assert wrong_owner.handler._status_code == 403
    assert wrong_owner.handler._captured["error"]["code"] == "setup_owner_mismatch"
    wrong_owner.validate_request.assert_not_called()
    wrong_owner.prepare_command.assert_not_called()

    for stale in (
        None,
        {**contract, "setup_id": "other-setup"},
        {**contract, "contract_id": "other-contract"},
    ):
        rejected = invoke(current_contract=stale)
        assert rejected.handler._status_code == 409
        assert rejected.handler._captured["error"]["code"] == "stale_contract"
        assert rejected.handler._captured["error"]["field"] == "contract_id"
        rejected.validate_request.assert_not_called()
        rejected.prepare_command.assert_not_called()

    for stale in (
        {**discovery, "state": "running"},
        {**discovery, "id": "other-discovery"},
        {**discovery, "setup_id": "other-setup"},
    ):
        rejected = invoke(current_discovery=stale)
        assert rejected.handler._status_code == 409
        assert rejected.handler._captured["error"]["code"] == "stale_discovery"
        assert rejected.handler._captured["error"]["field"] == "discovery_id"
        rejected.build_getter.assert_not_called()
        rejected.validate_request.assert_not_called()

    incomplete = invoke(ready=False)
    assert incomplete.handler._status_code == 422
    assert incomplete.handler._captured["error"]["code"] == "credentials_incomplete"
    incomplete.validate_request.assert_not_called()
    incomplete.prepare_command.assert_not_called()

    replay_job = {
        "id": "job-existing",
        "setup_id": state["setup_id"],
        "client_request_id": normalized["client_request_id"],
        "state": "running",
    }
    replay = invoke(existing=replay_job)
    assert replay.handler._status_code == 202
    assert replay.handler._captured == {
        "ok": True,
        "schema": ZERO_STATE_WEB_SCHEMA,
        "job": {"id": "job-existing", "state": "running"},
    }
    replay.project_job.assert_called_once_with(replay_job, log_limit=0)
    replay.prepare_command.assert_not_called()
    replay.update.assert_not_called()
    replay.thread.assert_not_called()
    assert replay.published == replay_job

    conflict_job = {
        "id": "job-conflict",
        "setup_id": state["setup_id"],
        "client_request_id": "different-request",
        "state": "queued",
    }
    conflict = invoke(existing=conflict_job)
    assert conflict.handler._status_code == 409
    assert conflict.handler._captured["error"]["code"] == "init_running"
    conflict.prepare_command.assert_not_called()
    conflict.update.assert_not_called()
    conflict.thread.assert_not_called()
    assert conflict.published == conflict_job

    admitted = invoke()
    assert admitted.handler._status_code == 202
    assert admitted.handler._captured == {
        "ok": True,
        "schema": ZERO_STATE_WEB_SCHEMA,
        "job": {"id": "job-new", "state": "queued", "poll_after_ms": 1000},
    }
    admitted.validate_request.assert_called_once_with(body, state, contract, discovery)
    admitted.prepare_command.assert_called_once_with(
        cfg,
        normalized,
        contract,
        discovery,
        "job-new",
    )
    assert admitted.update_snapshots == [expected_job]
    admitted.update.assert_called_once_with(
        cfg,
        phase="initializing",
        active_init_job_id="job-new",
        last_error_code=None,
    )
    admitted.thread.assert_called_once_with(
        target=serve._run_setup_init_job,
        args=("job-new", command, environment, secret_dir, state["setup_id"]),
        daemon=True,
        name="freq-setup-init-job-new",
    )
    admitted.worker.start.assert_called_once_with()
    admitted.remove_tree.assert_not_called()
    assert admitted.published == expected_job

    prepare_error = OSError("state publication failed")
    failed_prepare = invoke(prepare_error=prepare_error)
    assert failed_prepare.handler._status_code == 500
    assert failed_prepare.handler._captured["error"]["code"] == "init_prepare_failed"
    failed_prepare.remove_tree.assert_called_once_with(secret_dir, ignore_errors=True)
    failed_prepare.thread.assert_not_called()
    assert failed_prepare.published is None

    start_error = RuntimeError("thread start failed")
    failed_start = invoke(start_error=start_error)
    assert failed_start.handler._status_code == 500
    assert failed_start.handler._captured["error"]["code"] == "init_start_failed"
    failed_start.remove_tree.assert_called_once_with(secret_dir, ignore_errors=True)
    assert failed_start.update.call_args_list == [
        call(
            cfg,
            phase="initializing",
            active_init_job_id="job-new",
            last_error_code=None,
        ),
        call(cfg, phase="blocked", last_error_code="init_start_failed"),
    ]
    assert failed_start.published == {
        **expected_job,
        "state": "failed",
        "error": "setup init worker could not start",
    }


def _assert_setup_secret_file_contract(tmp_path):
    from freq.api import auth
    from freq.modules import serve
    from freq.services import setup_inputs

    auth_tree = ast.parse(inspect.getsource(auth))
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_inputs))
    expected_contracts = {
        "_setup_secret_dir": (setup_inputs.setup_secret_dir, "setup_secret_dir", 0, 1, 1),
        "_write_setup_secret": (setup_inputs.write_setup_secret, "write_setup_secret", 0, 6, 4),
    }
    for name, (
        service_function,
        service_name,
        serve_calls,
        service_calls,
        auth_calls,
    ) in expected_contracts.items():
        assert not any(
            isinstance(node, ast.FunctionDef) and node.name == name
            for node in serve_tree.body
        )
        assert sum(
            isinstance(node, ast.FunctionDef) and node.name == service_name
            for node in service_tree.body
        ) == 1
        assert getattr(serve, name) is service_function
        assert sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == name
            for node in ast.walk(serve_tree)
        ) == serve_calls
        assert sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == service_name
            for node in ast.walk(service_tree)
        ) == service_calls
        assert sum(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == service_name
            for node in ast.walk(auth_tree)
        ) == auth_calls

    cfg = SimpleNamespace(data_dir=str(tmp_path / "state"))
    expected_dir = tmp_path / "state" / "secrets" / "setup-init" / "job-1"
    expected_dir.mkdir(parents=True, mode=0o755)
    os.chmod(expected_dir, 0o755)
    assert serve._setup_secret_dir(cfg, "job-1") == str(expected_dir)
    assert stat.S_IMODE(expected_dir.stat().st_mode) == 0o700

    tolerated_dir = tmp_path / "state" / "secrets" / "setup-init" / "job-2"
    with patch.object(serve.os, "chmod", side_effect=OSError("mode unavailable")):
        assert serve._setup_secret_dir(cfg, "job-2") == str(tolerated_dir)
    assert tolerated_dir.is_dir()

    assert serve._write_setup_secret(str(expected_dir), "empty", "") == ""
    assert not (expected_dir / "empty").exists()
    for name, value, expected in (
        ("plain", "secret", b"secret\n"),
        ("terminated", "secret\n", b"secret\n"),
        ("coerced", 7, b"7\n"),
    ):
        path = serve._write_setup_secret(str(expected_dir), name, value)
        assert path == str(expected_dir / name)
        assert (expected_dir / name).read_bytes() == expected
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600

    chmod_error = OSError("secret mode failed")
    with patch.object(serve.os, "chmod", side_effect=chmod_error):
        with pytest.raises(OSError) as caught:
            serve._write_setup_secret(str(expected_dir), "mode-failure", "secret")
    assert caught.value is chmod_error


def _assert_setup_contract_credentials_writer(tmp_path):
    from freq.api import auth
    from freq.modules import serve

    serve_tree = ast.parse(inspect.getsource(serve))
    auth_tree = ast.parse(inspect.getsource(auth))
    assert not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "_write_setup_contract_credentials"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef)
        and node.name == "write_setup_contract_credentials"
        for node in auth_tree.body
    ) == 1
    assert serve._write_setup_contract_credentials is auth.write_setup_contract_credentials
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_write_setup_contract_credentials"
        for node in ast.walk(serve_tree)
    ) == 0
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "write_setup_contract_credentials"
        for node in ast.walk(auth_tree)
    ) == 1
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "toml_scalar"
        for node in ast.walk(auth_tree)
    ) == 7
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "write_setup_secret"
        for node in ast.walk(auth_tree)
    ) == 4
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (
                node.module == "freq.modules.serve"
                or (
                    node.module == "freq.modules"
                    and any(alias.name == "serve" for alias in node.names)
                )
            )
        )
        or (
            isinstance(node, ast.Import)
            and any(alias.name == "freq.modules.serve" for alias in node.names)
        )
        for node in ast.walk(auth_tree)
    )

    empty_dir = tmp_path / "contract-writer-empty"
    empty_dir.mkdir()
    with patch.object(auth, "_setup_contract_getter") as getter_factory:
        assert serve._write_setup_contract_credentials(object(), str(empty_dir), {}) == ""
    getter_factory.assert_not_called()
    assert list(empty_dir.iterdir()) == []

    writer_dir = tmp_path / "contract-writer"
    writer_dir.mkdir()
    resources = {
        "idrac": "device:idrac:10.25.0.31",
        "truenas": "device:truenas:10.25.0.41",
        "switch": "device:switch:10.25.0.51",
        "pfsense": "device:pfsense:10.25.0.61",
    }
    contract = {
        "setup_id": "setup-writer",
        "owned_devices": [
            {
                "resource_id": resources["idrac"],
                "kind": " IDRAC ",
                "host": "10.25.0.31",
                "label": "bmc-one",
                "placement": "production",
            },
            {
                "resource_id": resources["truenas"],
                "kind": "TrueNAS",
                "host": "10.25.0.41",
                "label": "nas-one",
                "placement": "lab",
            },
            {
                "resource_id": resources["switch"],
                "kind": "switch",
                "host": "10.25.0.51",
            },
            {
                "resource_id": resources["pfsense"],
                "kind": "pfsense",
                "host": "10.25.0.61",
                "label": "firewall-one",
            },
        ],
        "credential_requirements": [
            {
                "resource_id": resources["idrac"],
                "allowed_fields": ["username", "password"],
            },
            {
                "resource_id": resources["truenas"],
                "allowed_fields": ["username", "api_key"],
            },
            {
                "resource_id": resources["switch"],
                "allowed_fields": ["username", "ssh_private_key", "sudo_password"],
            },
        ],
    }
    private_key = "-----BEGIN PRIVATE KEY-----\nline-two\n-----END PRIVATE KEY-----"
    values = {
        credential_vault_key(resources["idrac"], "username"): "root-idrac",
        credential_vault_key(resources["idrac"], "password"): "idrac-secret",
        credential_vault_key(resources["truenas"], "username"): "root-nas",
        credential_vault_key(resources["truenas"], "api_key"): "nas-api-key",
        credential_vault_key(resources["truenas"], "password"): "not-allowed",
        credential_vault_key(resources["switch"], "username"): "switch-admin",
        credential_vault_key(resources["switch"], "ssh_private_key"):
            credential_storage_value("ssh_private_key", private_key),
        credential_vault_key(resources["switch"], "sudo_password"): "switch-sudo",
    }
    requested = []

    def getter(key):
        requested.append(key)
        return values.get(key, "")

    writer_cfg = object()
    with patch.object(auth, "_setup_contract_getter", return_value=getter) as getter_factory:
        device_path = serve._write_setup_contract_credentials(
            writer_cfg, str(writer_dir), contract
        )
    getter_factory.assert_called_once_with(writer_cfg, "setup-writer")
    assert requested == [
        credential_vault_key(resources["idrac"], "username"),
        credential_vault_key(resources["idrac"], "password"),
        credential_vault_key(resources["truenas"], "username"),
        credential_vault_key(resources["truenas"], "api_key"),
        credential_vault_key(resources["switch"], "username"),
        credential_vault_key(resources["switch"], "ssh_private_key"),
        credential_vault_key(resources["switch"], "sudo_password"),
    ]
    sections = {
        kind: f"{kind}-{credential_vault_key(resource, 'section').split('_')[1]}"
        for kind, resource in resources.items()
    }
    expected = (
        f"[{sections['idrac']}]\n"
        'type = "idrac"\n'
        'host = "10.25.0.31"\n'
        'label = "bmc-one"\n'
        'scope = "core"\n'
        'user = "root-idrac"\n'
        f'password_file = "{writer_dir / (sections["idrac"] + "-password")}"\n\n'
        f"[{sections['truenas']}]\n"
        'type = "truenas"\n'
        'host = "10.25.0.41"\n'
        'label = "nas-one"\n'
        'scope = "lab"\n'
        'user = "root-nas"\n'
        "browser_probe_only = true\n"
        f'api_key_file = "{writer_dir / (sections["truenas"] + "-api-key")}"\n\n'
        f"[{sections['switch']}]\n"
        'type = "switch"\n'
        'host = "10.25.0.51"\n'
        f'label = "{resources["switch"]}"\n'
        'scope = "core"\n'
        'user = "switch-admin"\n'
        f'ssh_key_file = "{writer_dir / (sections["switch"] + "-ssh-key")}"\n'
        f'sudo_password_file = "{writer_dir / (sections["switch"] + "-sudo-password")}"\n\n'
        f"[{sections['pfsense']}]\n"
        'type = "pfsense"\n'
        'host = "10.25.0.61"\n'
        'label = "firewall-one"\n'
        'scope = "core"\n'
    )
    assert device_path == str(writer_dir / "device-credentials.toml")
    assert (writer_dir / "device-credentials.toml").read_text(encoding="utf-8") == expected
    assert "idrac-secret" not in expected
    assert "nas-api-key" not in expected
    assert "switch-sudo" not in expected
    assert "not-allowed" not in expected
    expected_secrets = {
        f"{sections['idrac']}-password": b"idrac-secret\n",
        f"{sections['truenas']}-api-key": b"nas-api-key\n",
        f"{sections['switch']}-ssh-key": private_key.encode() + b"\n",
        f"{sections['switch']}-sudo-password": b"switch-sudo\n",
    }
    for name, payload in expected_secrets.items():
        path = writer_dir / name
        assert path.read_bytes() == payload
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(os.stat(device_path).st_mode) == 0o600
    assert sorted(path.name for path in writer_dir.iterdir()) == sorted(
        ["device-credentials.toml", *expected_secrets]
    )

    getter_error = RuntimeError("credential snapshot failed")
    getter_failure_dir = tmp_path / "contract-writer-getter-failure"
    getter_failure_dir.mkdir()
    with patch.object(auth, "_setup_contract_getter", side_effect=getter_error):
        with pytest.raises(RuntimeError) as caught:
            serve._write_setup_contract_credentials(
                object(), str(getter_failure_dir), contract
            )
    assert caught.value is getter_error
    assert list(getter_failure_dir.iterdir()) == []

    mode_failure_dir = tmp_path / "contract-writer-mode-failure"
    mode_failure_dir.mkdir()
    mode_contract = {
        "setup_id": "setup-mode-failure",
        "owned_devices": [
            {
                "resource_id": "device:pfsense:10.25.0.71",
                "kind": "pfsense",
                "host": "10.25.0.71",
            }
        ],
        "credential_requirements": [],
    }
    mode_error = OSError("credential contract mode failed")
    with patch.object(auth, "_setup_contract_getter", return_value=lambda _key: ""), patch.object(
        auth.os, "chmod", side_effect=mode_error
    ):
        with pytest.raises(OSError) as caught:
            serve._write_setup_contract_credentials(
                object(), str(mode_failure_dir), mode_contract
            )
    assert caught.value is mode_error
    assert (mode_failure_dir / "device-credentials.toml").is_file()


def test_contract_adapter_is_0600_and_preserves_exact_per_device_credentials(tmp_path):
    _assert_setup_init_command_from_contract_owner()
    _assert_setup_contract_credentials_writer(tmp_path)
    _assert_setup_secret_file_contract(tmp_path)
    _assert_setup_contract_vault_reader_contract()
    state, discovery, contract, body, resources = _objects()
    request = _setup_init_request(body, state, contract, discovery)
    cfg = SimpleNamespace(data_dir=str(tmp_path), install_dir=str(tmp_path))
    values = {
        credential_vault_key(resources[0], "username"): "root-one",
        credential_vault_key(resources[0], "password"): "secret-one",
        credential_vault_key(resources[1], "username"): "root-two",
        credential_vault_key(resources[1], "password"): "secret-two",
    }

    with patch("freq.api.auth.vault_get", return_value="bootstrap-secret"), patch(
        "freq.api.auth._setup_contract_getter",
        return_value=lambda key: values.get(key, ""),
    ):
        cmd, env, secret_dir = _setup_init_command_from_contract(
            cfg, request, contract, discovery, "job-1"
        )

    assert env["FREQ_WEB_INIT"] == "1"
    assert "--vm-contract" in cmd
    assert "--device-credentials" in cmd
    assert "--owned-vmids" not in cmd
    paths = [os.path.join(secret_dir, name) for name in os.listdir(secret_dir)]
    assert paths
    assert all(stat.S_IMODE(os.stat(path).st_mode) == 0o600 for path in paths)
    device_path = cmd[cmd.index("--device-credentials") + 1]
    loaded = _load_device_credentials(device_path)
    first = SimpleNamespace(ip="10.25.0.21", label="idrac-1", htype="idrac")
    second = SimpleNamespace(ip="10.25.0.22", label="idrac-2", htype="idrac")
    first_cred, first_section = _device_creds_for_host(first, loaded)
    second_cred, second_section = _device_creds_for_host(second, loaded)
    assert first_section != second_section
    assert (first_cred["user"], first_cred["password"]) == ("root-one", "secret-one")
    assert (second_cred["user"], second_cred["password"]) == ("root-two", "secret-two")


def test_contract_adapter_vm_toml_drives_cli_contract_semantics(tmp_path):
    from freq.api import auth
    from freq.modules import serve
    from freq.services import setup_inputs

    auth_tree = ast.parse(inspect.getsource(auth))
    serve_tree = ast.parse(inspect.getsource(serve))
    service_tree = ast.parse(inspect.getsource(setup_inputs))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_write_setup_vm_contract"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "write_vm_contract"
        for node in service_tree.body
    ) == 1
    assert serve._write_setup_vm_contract is setup_inputs.write_vm_contract
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_write_setup_vm_contract"
        for node in ast.walk(serve_tree)
    ) == 0
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "write_vm_contract"
        for node in ast.walk(auth_tree)
    ) == 1
    assert not any(
        isinstance(node, ast.ImportFrom)
        and str(node.module or "").startswith("freq.modules")
        for node in ast.walk(service_tree)
    )

    state, discovery, contract, body, _resources = _objects()
    direct_contract = copy.deepcopy(contract)
    direct_contract["acknowledged_devices"].extend(
        [
            {"host": " 10.25.0.98 "},
            {"host": "10.25.0.99"},
            {"host": "   "},
        ]
    )
    direct_path = serve._write_setup_vm_contract(str(tmp_path), direct_contract)
    assert direct_path == str(tmp_path / "vm-contract.toml")
    assert (tmp_path / "vm-contract.toml").read_text(encoding="utf-8") == (
        "[fleet]\n"
        "owned_vmids = [100, 101]\n"
        "template_vmids = [9000]\n"
        "acknowledged_out_of_contract_vmids = [777]\n"
        'acknowledged_device_hosts = ["10.25.0.98", "10.25.0.99"]\n'
    )
    assert stat.S_IMODE(os.stat(direct_path).st_mode) == 0o600

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    assert serve._write_setup_vm_contract(str(empty_dir), {}) == str(
        empty_dir / "vm-contract.toml"
    )
    assert (empty_dir / "vm-contract.toml").read_text(encoding="utf-8") == (
        "[fleet]\n"
        "owned_vmids = []\n"
        "template_vmids = []\n"
        "acknowledged_out_of_contract_vmids = []\n"
        "acknowledged_device_hosts = []\n"
    )

    failure_dir = tmp_path / "mode-failure"
    failure_dir.mkdir()
    mode_error = OSError("contract mode failed")
    with patch.object(serve.os, "chmod", side_effect=mode_error):
        with pytest.raises(OSError) as caught:
            serve._write_setup_vm_contract(str(failure_dir), {})
    assert caught.value is mode_error
    assert (failure_dir / "vm-contract.toml").is_file()

    contract["owned_devices"] = []
    contract["credential_requirements"] = []
    request = _setup_init_request(body, state, contract, discovery)
    cfg = SimpleNamespace(data_dir=str(tmp_path), install_dir=str(tmp_path))
    with patch("freq.api.auth.vault_get", return_value="bootstrap-secret"):
        cmd, _env, _secret_dir = _setup_init_command_from_contract(
            cfg, request, contract, discovery, "job-2"
        )
    contract_path = cmd[cmd.index("--vm-contract") + 1]
    with open(contract_path, encoding="utf-8") as handle:
        text = handle.read()
    assert "owned_vmids = [100, 101]" in text
    assert "template_vmids = [9000]" in text
    assert "acknowledged_out_of_contract_vmids = [777]" in text
    assert 'acknowledged_device_hosts = ["10.25.0.99"]' in text
    assert "--pve-nodes" in cmd and "10.25.0.11,10.25.0.12" in cmd
    assert "--pve-node-names" in cmd and "pve01,pve02" in cmd


def test_acknowledged_device_remains_unmanaged_after_known_type_fingerprint(tmp_path):
    from freq.modules.init_cmd import (
        _apply_acknowledged_device_contract,
        _apply_operator_vm_contract_args,
        _reconcile_existing_managed_hosts,
    )

    contract_path = tmp_path / "contract.toml"
    contract_path.write_text(
        '[fleet]\nacknowledged_device_hosts = ["10.25.0.99"]\n',
        encoding="utf-8",
    )
    cfg = SimpleNamespace(
        hosts=[],
        hosts_file=str(tmp_path / "hosts.toml"),
        pve_nodes=[],
        fleet_boundaries=None,
    )
    args = SimpleNamespace(
        vm_contract=str(contract_path),
        owned_vmids=None,
        template_vmids=None,
        acknowledged_out_of_contract_vmids=None,
    )
    _apply_operator_vm_contract_args(cfg, args)
    discovered = {
        "10.25.0.99": {
            "label": "truenas",
            "htype": "truenas",
            "managed": True,
            "all_ips": ["10.25.0.99"],
        }
    }
    _apply_acknowledged_device_contract(cfg, discovered)
    assert discovered["10.25.0.99"]["managed"] is False
    host = SimpleNamespace(
        ip="10.25.0.99",
        all_ips=["10.25.0.99"],
        label="truenas",
        htype="truenas",
        vmid=0,
        managed=True,
    )
    cfg.hosts = [host]
    with patch("freq.core.config.save_hosts_toml") as save:
        changed = _reconcile_existing_managed_hosts(cfg, {})

    assert host.managed is False
    assert changed == ["truenas (10.25.0.99) — browser-acknowledged device 10.25.0.99"]
    save.assert_called_once_with(cfg.hosts_file, cfg.hosts)


def test_web_init_finalizer_switches_managed_tls_then_runtime_ownership(tmp_path):
    from freq.modules import init_cmd

    conf = tmp_path / "conf"
    tls = tmp_path / "tls"
    conf.mkdir()
    tls.mkdir()
    (conf / "freq.toml").write_text(
        '[services]\ntls_cert = "/bootstrap.crt"\ntls_key = "/bootstrap.key"\n',
        encoding="utf-8",
    )
    (tls / "freq.crt").write_text("cert", encoding="utf-8")
    (tls / "freq.key").write_text("key", encoding="utf-8")
    cfg = SimpleNamespace(
        conf_dir=str(conf),
        data_dir=str(tmp_path / "data"),
        key_dir=str(tmp_path / "data" / "keys"),
        vault_file=str(tmp_path / "data" / "vault" / "vault.enc"),
        log_dir=str(tmp_path / "data" / "log"),
        credentials_dir=str(tmp_path / "credentials"),
    )
    with patch.object(
        init_cmd, "normalize_owned_install_root"
    ) as normalize_root, patch.object(
        init_cmd, "_ensure_post_init_runtime_state_ownership", return_value=True
    ) as ownership, patch.object(init_cmd, "_chown", return_value=True) as chown:
        assert init_cmd._finalize_web_init_runtime_ownership(cfg, "freq-admin") is True

    content = (conf / "freq.toml").read_text(encoding="utf-8")
    assert f'tls_cert = "{tls / "freq.crt"}"' in content
    assert f'tls_key = "{tls / "freq.key"}"' in content
    normalize_root.assert_called_once_with(str(tmp_path))
    ownership.assert_called_once_with(cfg, "freq-admin")
    chown.assert_any_call("freq-admin:freq-admin", str(tls), recursive=True)


def test_web_init_runtime_owner_stays_setup_user_until_success_handoff():
    from freq.modules import init_cmd

    result = SimpleNamespace(returncode=0, stdout="freq-ops\n")
    with patch.dict(os.environ, {"FREQ_WEB_INIT": "1"}), patch.object(
        init_cmd.subprocess, "run", return_value=result
    ) as run:
        assert init_cmd._post_init_runtime_owner("freq-admin") == "freq-ops"

    assert run.call_args.args[0][2] == "pve-freq-setup.service"


def test_success_handoff_shell_is_valid_and_finalizes_before_setup_removal(tmp_path):
    import ast
    import inspect

    from freq.modules import serve
    from freq.services import setup_handoff

    assert serve._schedule_setup_runtime_handoff is setup_handoff.schedule_setup_runtime_handoff
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_schedule_setup_runtime_handoff"
        for node in ast.walk(ast.parse(inspect.getsource(serve)))
    )
    service_tree = ast.parse(inspect.getsource(setup_handoff))
    assert {
        alias.name
        for node in ast.walk(service_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } == {"os", "pwd", "shlex", "subprocess", "sys"}
    assert {
        node.module
        for node in ast.walk(service_tree)
        if isinstance(node, ast.ImportFrom)
    } == {"freq.core"}

    cfg = SimpleNamespace(
        install_dir=str(tmp_path),
        ssh_service_account="freq-admin",
    )
    accepted = SimpleNamespace(returncode=0)
    rejected = SimpleNamespace(returncode=1)
    probe_cmd = ["systemctl", "cat", "freq-serve.service"]
    probe_kwargs = {
        "stdout": setup_handoff.subprocess.DEVNULL,
        "stderr": setup_handoff.subprocess.DEVNULL,
        "timeout": 5,
    }

    def expected_handoff(prefix):
        setup_unit = "/etc/systemd/system/pve-freq-setup.service"
        bootstrap_tls_dir = os.path.join(cfg.install_dir, "tls", "bootstrap")
        finalize_code = (
            "from freq.core.config import load_config; "
            "from freq.modules.init_cmd import _finalize_web_init_runtime_ownership; "
            "cfg=load_config(force=True); "
            "raise SystemExit(0 if _finalize_web_init_runtime_ownership("
            "cfg, cfg.ssh_service_account) else 1)"
        )
        finalize_cmd = prefix + [
            "env",
            f"FREQ_DIR={cfg.install_dir}",
            f"PYTHONPATH={cfg.install_dir}",
            sys.executable,
            "-c",
            finalize_code,
        ]
        prepare_switch = (
            " ".join(shlex.quote(part) for part in finalize_cmd)
            + " && "
            + " ".join(
                shlex.quote(part)
                for part in prefix
                + ["systemctl", "disable", "--now", "pve-freq-setup.service"]
            )
            + " >/dev/null 2>&1 && "
            + " ".join(
                shlex.quote(part) for part in prefix + ["rm", "-f", setup_unit]
            )
            + " && "
            + " ".join(
                shlex.quote(part)
                for part in prefix + ["rm", "-rf", bootstrap_tls_dir]
            )
            + " && "
            + " ".join(
                shlex.quote(part)
                for part in prefix + ["systemctl", "daemon-reload"]
            )
            + " >/dev/null 2>&1"
        )
        start_managed = (
            "sleep 2; "
            + " ".join(
                shlex.quote(part)
                for part in prefix + ["systemctl", "restart", "freq-serve.service"]
            )
            + " >/dev/null 2>&1 || "
            + " ".join(
                shlex.quote(part)
                for part in prefix + ["systemctl", "start", "freq-serve.service"]
            )
            + " >/dev/null 2>&1"
        )
        retire_setup_identity = " ".join(
            shlex.quote(part)
            for part in prefix
            + [
                "/bin/sh",
                "-c",
                "rm -f /etc/sudoers.d/pve-freq-setup; "
                "userdel -r pve-freq-setup >/dev/null 2>&1 || true",
            ]
        )
        script = (
            f"if {prepare_switch}; then if {start_managed}; then "
            f"{retire_setup_identity}; else exit 1; fi; else exit 1; fi"
        )
        return (
            prefix
            + [
                "systemd-run",
                "--quiet",
                "--collect",
                "--unit=pve-freq-web-init-handoff",
                "--on-active=5",
                "/bin/sh",
                "-c",
                script,
            ],
            script,
        )

    with patch.object(
        setup_handoff.subprocess,
        "run",
        side_effect=OSError("systemctl unavailable"),
    ) as run, patch.object(setup_handoff.subprocess, "Popen") as popen:
        assert serve._schedule_setup_runtime_handoff(cfg) is False
    assert run.call_args.args == (probe_cmd,)
    assert run.call_args.kwargs == probe_kwargs
    popen.assert_not_called()

    with patch.object(
        setup_handoff.subprocess,
        "run",
        return_value=accepted,
    ) as run, patch.object(setup_handoff.os, "getpid", return_value=4242), patch.object(
        setup_handoff.os, "geteuid", return_value=1001
    ), patch(
        "pwd.getpwuid",
        return_value=SimpleNamespace(pw_name="freq-admin"),
    ), patch.object(setup_handoff.subprocess, "Popen") as popen:
        assert serve._schedule_setup_runtime_handoff(cfg) is False
    assert len(run.call_args_list) == 1
    popen.assert_not_called()

    expected_nonroot_cmd, nonroot_script = expected_handoff(["sudo", "-n"])
    with patch.object(
        setup_handoff.subprocess,
        "run",
        side_effect=[accepted, accepted],
    ) as run, patch.object(setup_handoff.os, "getpid", return_value=4242), patch.object(
        setup_handoff.os, "geteuid", return_value=1001
    ), patch(
        "pwd.getpwuid",
        return_value=SimpleNamespace(pw_name="setup-user"),
    ), patch.object(setup_handoff.subprocess, "Popen") as popen, patch.object(
        setup_handoff.logger,
        "info",
    ) as info:
        assert serve._schedule_setup_runtime_handoff(cfg) is True
    assert run.call_args_list[0].args == (probe_cmd,)
    assert run.call_args_list[0].kwargs == probe_kwargs
    assert run.call_args_list[1].args == (expected_nonroot_cmd,)
    assert run.call_args_list[1].kwargs == probe_kwargs
    popen.assert_not_called()
    info.assert_called_once_with(
        "setup_runtime_handoff_scheduled",
        pid=4242,
        method="systemd-run",
    )
    assert nonroot_script.index("_finalize_web_init_runtime_ownership") < nonroot_script.index(
        "disable --now pve-freq-setup.service"
    )
    assert nonroot_script.index("disable --now pve-freq-setup.service") < nonroot_script.index(
        "rm -f /etc/systemd/system/pve-freq-setup.service"
    )
    assert nonroot_script.index("rm -rf") < nonroot_script.index("daemon-reload")
    assert nonroot_script.index("restart freq-serve.service") < nonroot_script.index(
        "userdel -r pve-freq-setup"
    )
    parsed = subprocess.run(
        ["/bin/sh", "-n", "-c", nonroot_script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert parsed.returncode == 0, parsed.stderr

    expected_root_cmd, root_script = expected_handoff([])
    with patch.object(
        setup_handoff.subprocess,
        "run",
        side_effect=[accepted, rejected],
    ) as run, patch.object(setup_handoff.os, "getpid", return_value=5252), patch.object(
        setup_handoff.os, "geteuid", return_value=0
    ), patch(
        "pwd.getpwuid",
        return_value=SimpleNamespace(pw_name="root"),
    ), patch.object(setup_handoff.subprocess, "Popen") as popen, patch.object(
        setup_handoff.logger,
        "info",
    ) as info:
        assert serve._schedule_setup_runtime_handoff(cfg) is True
    assert run.call_args_list[1].args == (expected_root_cmd,)
    popen.assert_called_once_with(
        ["/bin/sh", "-c", f"sleep 5; {root_script}"],
        stdin=setup_handoff.subprocess.DEVNULL,
        stdout=setup_handoff.subprocess.DEVNULL,
        stderr=setup_handoff.subprocess.DEVNULL,
        start_new_session=True,
    )
    info.assert_called_once_with(
        "setup_runtime_handoff_scheduled",
        pid=5252,
        method="detached-shell",
    )

    with patch.object(
        setup_handoff.subprocess,
        "run",
        side_effect=[accepted, setup_handoff.subprocess.SubprocessError("schedule failed")],
    ), patch.object(setup_handoff.os, "getpid", return_value=6262), patch.object(
        setup_handoff.os, "geteuid", return_value=0
    ), patch(
        "pwd.getpwuid",
        return_value=SimpleNamespace(pw_name="root"),
    ), patch.object(
        setup_handoff.subprocess,
        "Popen",
        side_effect=OSError("launch failed"),
    ), patch.object(setup_handoff.logger, "warn") as warning:
        assert serve._schedule_setup_runtime_handoff(cfg) is False
    warning.assert_called_once_with("setup runtime handoff scheduling failed: launch failed")


class _Proc:
    pid = 123
    stdout = []

    def __init__(self, returncode):
        self.returncode = returncode

    def wait(self):
        return self.returncode


def _assert_setup_init_worker_owner(tmp_path):
    import freq.modules.serve as serve
    from freq.services import setup_progress

    serve_tree = ast.parse(inspect.getsource(serve))
    worker_tree = ast.parse(inspect.getsource(setup_progress))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_run_setup_init_job"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.FunctionDef) and node.name == "run_setup_init_job"
        for node in worker_tree.body
    ) == 1
    assert not any(
        (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("freq.modules")
        )
        or (
            isinstance(node, ast.Import)
            and any(alias.name.startswith("freq.modules") for alias in node.names)
        )
        for node in ast.walk(worker_tree)
    )
    assert serve._run_setup_init_job.func is setup_progress.run_setup_init_job
    assert serve._run_setup_init_job.keywords == {
        "runtime": serve._setup_init_worker_runtime,
    }
    assert serve._setup_init_worker_runtime.init_lock is serve._setup_init_lock
    assert serve._setup_init_worker_runtime.setup_lock is serve._setup_lock
    assert sum(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == "_run_setup_init_job"
        for node in ast.walk(serve_tree)
    ) == 1

    class StreamingProc:
        pid = 4242
        stdout = ["phase-one secret-path\n", "phase-two\n"]

        def wait(self):
            return 0

    cfg = SimpleNamespace(
        conf_dir=str(tmp_path / "owner-etc"),
        data_dir=str(tmp_path / "owner-data"),
    )
    os.makedirs(cfg.conf_dir)
    os.makedirs(cfg.data_dir)
    open(os.path.join(cfg.conf_dir, ".initialized"), "w").close()
    secret_dir = tmp_path / "owner-adapters"
    secret_dir.mkdir()
    open(secret_dir / "secret", "w").close()
    env = {
        "FREQ_DIR": str(tmp_path / "owner-runtime"),
        "FREQ_WEB_INIT": "1",
        "OWNER_ENV": "preserved",
    }
    serve._setup_init_job = {
        "id": "owner-job",
        "state": "queued",
        "lines": ["queued"],
    }

    def markers(_cfg):
        open(os.path.join(_cfg.conf_dir, ".web-setup-complete"), "w").close()

    parsed_progress = {
        "phase": 2,
        "phase_name": "Discovery",
        "current": 1,
        "total": 12,
        "message": "parsed",
    }
    with patch.object(serve.subprocess, "Popen", return_value=StreamingProc()) as popen, patch.object(
        serve, "_publish_setup_init_process"
    ) as publish, patch.object(
        serve,
        "_redact_setup_init_line",
        side_effect=lambda line, _secret_dir: f"safe:{line.strip()}",
    ) as redact, patch.object(
        serve,
        "_setup_init_progress",
        side_effect=[None, parsed_progress],
    ) as progress, patch.object(
        serve, "load_config", return_value=cfg
    ), patch.object(
        serve, "_write_web_setup_markers", side_effect=markers
    ), patch.object(
        serve, "_delete_setup_vault_namespace"
    ) as delete_namespace, patch.object(
        serve, "clear_setup_contract"
    ) as clear_contract, patch.object(
        serve, "clear_setup_state"
    ) as clear_state, patch.object(
        serve, "update_setup_state"
    ) as update_state, patch.object(
        serve, "_schedule_setup_runtime_handoff", return_value=True
    ) as handoff:
        serve._run_setup_init_job(
            "owner-job", ["freq", "init"], env, str(secret_dir), "setup-owner"
        )

    popen.assert_called_once_with(
        ["freq", "init"],
        cwd=env["FREQ_DIR"],
        env=env,
        stdin=serve.subprocess.DEVNULL,
        stdout=serve.subprocess.PIPE,
        stderr=serve.subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    publish.assert_called_once()
    assert publish.call_args.args[0] == "owner-job"
    assert publish.call_args.args[1].pid == 4242
    assert redact.call_args_list == [
        call("phase-one secret-path\n", str(secret_dir)),
        call("phase-two\n", str(secret_dir)),
    ]
    assert progress.call_args_list == [call("safe:phase-one secret-path"), call("safe:phase-two")]
    delete_namespace.assert_called_once_with(cfg, "setup-owner")
    clear_contract.assert_called_once_with(cfg)
    clear_state.assert_called_once_with(cfg)
    update_state.assert_not_called()
    handoff.assert_called_once_with(cfg)
    assert not secret_dir.exists()
    assert serve._setup_init_job["state"] == "succeeded"
    assert serve._setup_init_job["returncode"] == 0
    assert serve._setup_init_job["initialized"] is True
    assert serve._setup_init_job["web_setup_complete"] is True
    assert serve._setup_init_job["process"] is None
    assert serve._setup_init_job["progress"] == {
        "phase": 12,
        "phase_name": "Verification",
        "current": 12,
        "total": 12,
        "message": "Initialization and browser setup completed.",
    }
    assert serve._setup_init_job["lines"] == [
        "queued",
        "safe:phase-one secret-path",
        "safe:phase-two",
        "scheduled dashboard handoff to freq-serve.service",
    ]

    marker_dir = tmp_path / "marker-failure-adapters"
    marker_dir.mkdir()
    serve._setup_init_job = {"id": "marker-job", "state": "queued", "lines": []}
    marker_error = OSError("marker owner failure")
    with patch.object(serve.subprocess, "Popen", return_value=_Proc(0)), patch.object(
        serve, "load_config", return_value=cfg
    ), patch.object(
        serve, "_write_web_setup_markers", side_effect=marker_error
    ), patch.object(
        serve, "_delete_setup_vault_namespace"
    ) as delete_namespace, patch.object(
        serve, "update_setup_state"
    ) as update_state, patch.object(
        serve, "_schedule_setup_runtime_handoff"
    ) as handoff:
        serve._run_setup_init_job(
            "marker-job", ["freq"], {"FREQ_DIR": ""}, str(marker_dir), "setup-owner"
        )
    assert not marker_dir.exists()
    delete_namespace.assert_not_called()
    handoff.assert_not_called()
    update_state.assert_called_once_with(
        cfg, phase="blocked", last_error_code="init_failed"
    )
    assert serve._setup_init_job["state"] == "failed"
    assert serve._setup_init_job["error"] == "setup markers could not be written"

    exception_dir = tmp_path / "exception-adapters"
    exception_dir.mkdir()
    serve._setup_init_job = {"id": "exception-job", "state": "queued", "lines": []}
    launch_error = OSError("worker launch failed")
    with patch.object(serve.subprocess, "Popen", side_effect=launch_error), patch.object(
        serve, "load_config", return_value=cfg
    ), patch.object(
        serve, "update_setup_state"
    ) as update_state, patch.object(
        serve, "_schedule_setup_runtime_handoff"
    ) as handoff:
        serve._run_setup_init_job(
            "exception-job", ["freq"], {"FREQ_DIR": ""}, str(exception_dir)
        )
    assert not exception_dir.exists()
    handoff.assert_not_called()
    update_state.assert_called_once_with(
        cfg, phase="blocked", last_error_code="init_failed"
    )
    assert serve._setup_init_job["state"] == "failed"
    assert serve._setup_init_job["error"] == "setup init worker failed"
    assert serve._setup_init_job["process"] is None

    cleanup_dir = tmp_path / "cleanup-failure-adapters"
    cleanup_dir.mkdir()
    serve._setup_init_job = {"id": "cleanup-job", "state": "queued", "lines": []}
    with patch.object(serve.subprocess, "Popen", return_value=_Proc(0)), patch.object(
        serve, "load_config", return_value=cfg
    ), patch.object(
        serve, "_write_web_setup_markers", side_effect=markers
    ), patch.object(
        serve.shutil,
        "rmtree",
        side_effect=[OSError("cleanup failed"), None],
    ) as rmtree, patch.object(
        serve, "_delete_setup_vault_namespace"
    ) as delete_namespace, patch.object(
        serve, "update_setup_state"
    ) as update_state, patch.object(
        serve, "_schedule_setup_runtime_handoff"
    ) as handoff:
        serve._run_setup_init_job(
            "cleanup-job", ["freq"], {"FREQ_DIR": ""}, str(cleanup_dir), "setup-owner"
        )
    assert rmtree.call_count == 2
    delete_namespace.assert_not_called()
    handoff.assert_not_called()
    update_state.assert_called_once_with(
        cfg, phase="blocked", last_error_code="init_failed"
    )
    assert serve._setup_init_job["state"] == "failed"
    assert serve._setup_init_job["error"] == "transient init adapters could not be removed"

    vault_dir = tmp_path / "vault-failure-adapters"
    vault_dir.mkdir()
    serve._setup_init_job = {"id": "vault-job", "state": "queued", "lines": []}
    vault_error = OSError("setup namespace cleanup failed")
    with patch.object(serve.subprocess, "Popen", return_value=_Proc(0)), patch.object(
        serve, "load_config", return_value=cfg
    ), patch.object(
        serve, "_write_web_setup_markers", side_effect=markers
    ), patch.object(
        serve, "_delete_setup_vault_namespace", side_effect=vault_error
    ), patch.object(
        serve, "clear_setup_contract"
    ) as clear_contract, patch.object(
        serve, "clear_setup_state"
    ) as clear_state, patch.object(
        serve, "update_setup_state"
    ) as update_state, patch.object(
        serve, "_schedule_setup_runtime_handoff"
    ) as handoff:
        serve._run_setup_init_job(
            "vault-job", ["freq"], {"FREQ_DIR": ""}, str(vault_dir), "setup-owner"
        )
    assert not vault_dir.exists()
    assert not os.path.exists(os.path.join(cfg.conf_dir, ".web-setup-complete"))
    clear_contract.assert_not_called()
    clear_state.assert_not_called()
    handoff.assert_not_called()
    update_state.assert_called_once_with(
        cfg, phase="blocked", last_error_code="init_failed"
    )
    assert serve._setup_init_job["state"] == "failed"
    assert serve._setup_init_job["web_setup_complete"] is False
    assert serve._setup_init_job["error"] == "setup secrets could not be removed"


def test_init_worker_removes_adapters_before_success_and_clears_setup_vault(tmp_path):
    import freq.modules.serve as serve

    _assert_setup_init_worker_owner(tmp_path)
    cfg = SimpleNamespace(conf_dir=str(tmp_path / "etc"), data_dir=str(tmp_path / "data"))
    os.makedirs(cfg.conf_dir)
    os.makedirs(cfg.data_dir)
    open(os.path.join(cfg.conf_dir, ".initialized"), "w").close()
    secret_dir = tmp_path / "adapters"
    secret_dir.mkdir()
    open(secret_dir / "secret", "w").close()
    serve._setup_init_job = {"id": "job", "state": "queued", "lines": []}

    def markers(_cfg):
        open(os.path.join(_cfg.conf_dir, ".web-setup-complete"), "w").close()

    with patch("freq.modules.serve.subprocess.Popen", return_value=_Proc(0)), patch(
        "freq.modules.serve.load_config", return_value=cfg
    ), patch("freq.modules.serve._write_web_setup_markers", side_effect=markers), patch(
        "freq.modules.serve._delete_setup_vault_namespace"
    ) as delete_namespace, patch("freq.modules.serve.clear_setup_contract"), patch(
        "freq.modules.serve.clear_setup_state"
    ), patch("freq.modules.serve._schedule_setup_runtime_handoff", return_value=False):
        serve._run_setup_init_job(
            "job", ["freq"], {"FREQ_DIR": str(tmp_path), "FREQ_WEB_INIT": "1"},
            str(secret_dir), "setup-1",
        )

    assert not secret_dir.exists()
    delete_namespace.assert_called_once_with(cfg, "setup-1")
    assert serve._setup_init_job["state"] == "succeeded"
    assert serve._setup_init_job["web_setup_complete"] is True


def test_init_worker_failure_removes_adapters_but_retains_retry_secrets(tmp_path):
    import freq.modules.serve as serve

    cfg = SimpleNamespace(conf_dir=str(tmp_path / "etc"), data_dir=str(tmp_path / "data"))
    os.makedirs(cfg.conf_dir)
    os.makedirs(cfg.data_dir)
    secret_dir = tmp_path / "adapters"
    secret_dir.mkdir()
    open(secret_dir / "secret", "w").close()
    serve._setup_init_job = {"id": "job", "state": "queued", "lines": []}
    with patch("freq.modules.serve.subprocess.Popen", return_value=_Proc(1)), patch(
        "freq.modules.serve.load_config", return_value=cfg
    ), patch("freq.modules.serve._delete_setup_vault_namespace") as delete_namespace, patch(
        "freq.modules.serve.update_setup_state"
    ), patch("freq.modules.serve._schedule_setup_runtime_handoff", return_value=False):
        serve._run_setup_init_job(
            "job", ["freq"], {"FREQ_DIR": str(tmp_path), "FREQ_WEB_INIT": "1"},
            str(secret_dir), "setup-1",
        )

    assert not secret_dir.exists()
    delete_namespace.assert_not_called()
    assert serve._setup_init_job["state"] == "failed"


def test_web_headless_init_preserves_the_existing_browser_operator():
    from freq.modules import init_cmd

    source = inspect.getsource(init_cmd._init_headless)
    assert 'web_init_runner = os.environ.get("FREQ_WEB_INIT") == "1"' in source
    assert "preserve_dashboard_auth" in source
    assert "Preserving existing dashboard operator" in source
    assert "Existing dashboard operator" in source


def _assert_setup_vault_namespace_deletion_contract():
    from freq.modules import serve

    assert serve._delete_setup_vault_namespace is auth._delete_setup_vault_namespace
    serve_tree = ast.parse(inspect.getsource(serve))
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_delete_setup_vault_namespace"
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_delete_setup_vault_namespace"
        for node in ast.walk(serve_tree)
    ) == 1
    auth_tree = ast.parse(inspect.getsource(auth))
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_delete_setup_vault_namespace"
        for node in ast.walk(auth_tree)
    ) == 1
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_setup_vault_host"
        for node in ast.walk(auth_tree)
    ) == 4
    assert sum(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            name.startswith("freq.modules")
            for name in (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
        )
        for node in ast.walk(auth_tree)
    ) == 1

    cfg = object()
    setup_id = object()
    host = object()
    other_host = object()
    keep_value = object()
    drop_value = object()
    first_snapshot = [
        (host, "keep", keep_value),
        (other_host, "cross-host", object()),
        (host, "drop", drop_value),
        (host, "keep", object()),
    ]
    verified_snapshot = [(other_host, "keep", keep_value)]

    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ) as vault_host, patch(
        "freq.api.auth.vault_list", side_effect=[first_snapshot, verified_snapshot]
    ) as vault_list, patch(
        "freq.api.auth.vault_update", return_value=True
    ) as vault_update:
        assert serve._delete_setup_vault_namespace(cfg, setup_id) is None
    vault_host.assert_called_once_with(setup_id)
    assert vault_list.call_args_list == [call(cfg), call(cfg)]
    vault_update.assert_called_once_with(cfg, host, {"keep": None, "drop": None})

    cross_host_only = [(other_host, "keep", keep_value)]
    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list", side_effect=[cross_host_only, cross_host_only]
    ) as vault_list, patch("freq.api.auth.vault_update") as vault_update:
        assert serve._delete_setup_vault_namespace(cfg, setup_id) is None
    assert vault_list.call_args_list == [call(cfg), call(cfg)]
    vault_update.assert_not_called()

    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list", side_effect=[first_snapshot, verified_snapshot]
    ) as vault_list, patch("freq.api.auth.vault_update", return_value=False):
        with pytest.raises(OSError, match="^setup secret cleanup failed$"):
            serve._delete_setup_vault_namespace(cfg, setup_id)
    vault_list.assert_called_once_with(cfg)

    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list",
        side_effect=[first_snapshot, [(host, "drop", drop_value)]],
    ) as vault_list, patch("freq.api.auth.vault_update", return_value=True):
        with pytest.raises(OSError, match="^setup secret cleanup failed$"):
            serve._delete_setup_vault_namespace(cfg, setup_id)
    assert vault_list.call_args_list == [call(cfg), call(cfg)]

    namespace_error = RuntimeError("namespace failed")
    with patch(
        "freq.api.auth._setup_vault_host", side_effect=namespace_error
    ), patch("freq.api.auth.vault_list") as vault_list, patch(
        "freq.api.auth.vault_update"
    ) as vault_update:
        with pytest.raises(RuntimeError) as caught:
            serve._delete_setup_vault_namespace(cfg, setup_id)
    assert caught.value is namespace_error
    vault_list.assert_not_called()
    vault_update.assert_not_called()

    list_error = OSError("verification snapshot failed")
    with patch(
        "freq.api.auth._setup_vault_host", return_value=host
    ), patch(
        "freq.api.auth.vault_list", side_effect=[first_snapshot, list_error]
    ) as vault_list, patch("freq.api.auth.vault_update", return_value=True):
        with pytest.raises(OSError) as caught:
            serve._delete_setup_vault_namespace(cfg, setup_id)
    assert caught.value is list_error
    assert vault_list.call_args_list == [call(cfg), call(cfg)]


def _assert_setup_expiry_observation_contract():
    from freq.modules import serve

    assert serve._cleanup_expired_setup is auth._cleanup_expired_setup
    assert serve._bg_cleanup_expired_setup is auth._bg_cleanup_expired_setup
    assert serve._observe_setup_state is auth._observe_setup_state
    serve_tree = ast.parse(inspect.getsource(serve))
    auth_tree = ast.parse(inspect.getsource(auth))
    lifecycle_names = {
        "_cleanup_expired_setup",
        "_bg_cleanup_expired_setup",
        "_observe_setup_state",
    }
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name in lifecycle_names
        for node in serve_tree.body
    )
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_cleanup_expired_setup"
        for node in ast.walk(serve_tree)
    ) == 0
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_observe_setup_state"
        for node in ast.walk(serve_tree)
    ) == 8
    assert sum(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id == "_bg_cleanup_expired_setup"
        for node in ast.walk(serve_tree)
    ) == 1
    assert sum(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_cleanup_expired_setup"
        for node in ast.walk(auth_tree)
    ) == 2
    assert sum(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(
            name.startswith("freq.modules")
            for name in (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
            )
        )
        for node in ast.walk(auth_tree)
    ) == 1

    cfg = SimpleNamespace(data_dir="/missing-gate91-expiry-owner")
    missing_state = "/missing-gate91-expiry-owner/setup/state.json"
    active_state = {"setup_id": "active-setup"}
    with patch(
        "freq.api.auth.setup_state_path", return_value=missing_state
    ), patch(
        "freq.api.auth.load_setup_state", return_value=active_state
    ) as load_state, patch(
        "freq.api.auth.load_setup_contract"
    ) as load_contract, patch(
        "freq.api.auth._delete_setup_vault_namespace"
    ) as delete_namespace, patch(
        "freq.api.auth.clear_setup_contract"
    ) as clear_contract:
        assert serve._cleanup_expired_setup(cfg) is False
    load_state.assert_called_once_with(cfg)
    load_contract.assert_not_called()
    delete_namespace.assert_not_called()
    clear_contract.assert_not_called()

    contract = {"setup_id": "contract-setup"}
    events = []
    with patch(
        "freq.api.auth.setup_state_path", return_value=missing_state
    ), patch(
        "freq.api.auth.load_setup_state", return_value={}
    ), patch(
        "freq.api.auth.load_setup_contract", return_value=contract
    ), patch(
        "freq.api.auth._delete_setup_vault_namespace",
        side_effect=lambda target_cfg, setup_id: events.append(
            ("delete", target_cfg, setup_id)
        ),
    ) as delete_namespace, patch(
        "freq.api.auth.clear_setup_contract",
        side_effect=lambda target_cfg: events.append(("clear", target_cfg)),
    ) as clear_contract:
        assert serve._cleanup_expired_setup(cfg) is True
    assert events == [
        ("delete", cfg, contract["setup_id"]),
        ("clear", cfg),
    ]
    delete_namespace.assert_called_once_with(cfg, contract["setup_id"])
    clear_contract.assert_called_once_with(cfg)

    cleanup_error = RuntimeError("namespace cleanup failed")
    with patch(
        "freq.api.auth.setup_state_path", return_value=missing_state
    ), patch(
        "freq.api.auth.load_setup_state", return_value={}
    ), patch(
        "freq.api.auth.load_setup_contract", return_value=contract
    ), patch(
        "freq.api.auth._delete_setup_vault_namespace",
        side_effect=cleanup_error,
    ), patch(
        "freq.api.auth.clear_setup_contract"
    ) as clear_contract:
        with pytest.raises(RuntimeError) as caught:
            serve._cleanup_expired_setup(cfg)
    assert caught.value is cleanup_error
    clear_contract.assert_not_called()

    with patch(
        "freq.api.auth.setup_state_path", return_value=missing_state
    ), patch(
        "freq.api.auth.load_setup_state", return_value={}
    ), patch(
        "freq.api.auth.load_setup_contract", return_value={}
    ), patch(
        "freq.api.auth._delete_setup_vault_namespace"
    ) as delete_namespace, patch(
        "freq.api.auth.clear_setup_contract"
    ) as clear_contract:
        assert serve._cleanup_expired_setup(cfg) is False
    delete_namespace.assert_not_called()
    clear_contract.assert_not_called()

    observed = {"setup_id": "observed-setup"}
    events = []
    with patch(
        "freq.api.auth._cleanup_expired_setup",
        side_effect=lambda target_cfg: events.append(("cleanup", target_cfg)),
    ), patch(
        "freq.api.auth.load_setup_state",
        side_effect=lambda target_cfg: (
            events.append(("load", target_cfg)),
            observed,
        )[1],
    ):
        assert serve._observe_setup_state(cfg) is observed
    assert events == [("cleanup", cfg), ("load", cfg)]

    observation_error = OSError("expiry observation failed")
    with patch(
        "freq.api.auth._cleanup_expired_setup",
        side_effect=observation_error,
    ), patch("freq.api.auth.load_setup_state") as load_state:
        with pytest.raises(OSError) as caught:
            serve._observe_setup_state(cfg)
    assert caught.value is observation_error
    load_state.assert_not_called()

    background_error = RuntimeError("background cleanup failed")
    with patch(
        "freq.api.auth.load_config", return_value=cfg
    ), patch(
        "freq.api.auth._cleanup_expired_setup",
        side_effect=background_error,
    ) as cleanup, patch("freq.api.auth.logger.warn") as warning:
        assert serve._bg_cleanup_expired_setup() is None
    cleanup.assert_called_once_with(cfg)
    warning.assert_called_once_with(
        "setup_expiry_cleanup_failed: background cleanup failed"
    )


def test_expiry_observation_cleans_the_exact_setup_namespace(tmp_path):
    from freq.modules.serve import _cleanup_expired_setup

    _assert_setup_vault_namespace_deletion_contract()
    _assert_setup_expiry_observation_contract()
    cfg = SimpleNamespace(data_dir=str(tmp_path))
    state = ensure_setup_state(cfg, "sonny", now=1)
    with patch("freq.api.auth._delete_setup_vault_namespace") as cleanup:
        assert _cleanup_expired_setup(cfg) is True
    cleanup.assert_called_once_with(cfg, state["setup_id"])
    assert not os.path.exists(setup_state_path(cfg))
