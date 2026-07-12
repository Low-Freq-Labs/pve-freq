"""Zero-state browser init must stay value-only and preserve frozen truth."""

import inspect
import os
import stat
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.core.setup_contract import SetupContractError, credential_vault_key
from freq.core.setup_state import ensure_setup_state, setup_state_path
from freq.modules.init_cmd import _device_creds_for_host, _load_device_credentials
from freq.modules.serve import (
    ZERO_STATE_WEB_SCHEMA,
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


def test_init_request_rejects_all_browser_paths_and_stale_ids():
    state, discovery, contract, body, _resources = _objects()
    bad = {**body, "vm_contract": "/tmp/operator.toml"}
    with pytest.raises(SetupContractError) as caught:
        _setup_init_request(bad, state, contract, discovery)
    assert caught.value.code == "unsupported_field"

    stale = {**body, "contract_id": "old"}
    with pytest.raises(SetupContractError) as caught:
        _setup_init_request(stale, state, contract, discovery)
    assert caught.value.code == "stale_contract"


def test_contract_adapter_is_0600_and_preserves_exact_per_device_credentials(tmp_path):
    state, discovery, contract, body, resources = _objects()
    request = _setup_init_request(body, state, contract, discovery)
    cfg = SimpleNamespace(data_dir=str(tmp_path), install_dir=str(tmp_path))
    values = {
        credential_vault_key(resources[0], "username"): "root-one",
        credential_vault_key(resources[0], "password"): "secret-one",
        credential_vault_key(resources[1], "username"): "root-two",
        credential_vault_key(resources[1], "password"): "secret-two",
    }

    with patch("freq.modules.serve.vault_get", return_value="bootstrap-secret"), patch(
        "freq.modules.serve._setup_contract_getter",
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
    state, discovery, contract, body, _resources = _objects()
    contract["owned_devices"] = []
    contract["credential_requirements"] = []
    request = _setup_init_request(body, state, contract, discovery)
    cfg = SimpleNamespace(data_dir=str(tmp_path), install_dir=str(tmp_path))
    with patch("freq.modules.serve.vault_get", return_value="bootstrap-secret"):
        cmd, _env, _secret_dir = _setup_init_command_from_contract(
            cfg, request, contract, discovery, "job-2"
        )
    contract_path = cmd[cmd.index("--vm-contract") + 1]
    text = open(contract_path, encoding="utf-8").read()
    assert "owned_vmids = [100, 101]" in text
    assert "template_vmids = [9000]" in text
    assert "acknowledged_out_of_contract_vmids = [777]" in text
    assert "--pve-nodes" in cmd and "10.25.0.11,10.25.0.12" in cmd
    assert "--pve-node-names" in cmd and "pve01,pve02" in cmd


class _Proc:
    pid = 123
    stdout = []

    def __init__(self, returncode):
        self.returncode = returncode

    def wait(self):
        return self.returncode


def test_init_worker_removes_adapters_before_success_and_clears_setup_vault(tmp_path):
    import freq.modules.serve as serve

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


def test_expiry_observation_cleans_the_exact_setup_namespace(tmp_path):
    from freq.modules.serve import _cleanup_expired_setup

    cfg = SimpleNamespace(data_dir=str(tmp_path))
    state = ensure_setup_state(cfg, "sonny", now=1)
    with patch("freq.modules.serve._delete_setup_vault_namespace") as cleanup:
        assert _cleanup_expired_setup(cfg) is True
    cleanup.assert_called_once_with(cfg, state["setup_id"])
    assert not os.path.exists(setup_state_path(cfg))
