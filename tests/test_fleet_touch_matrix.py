"""Disposable fleet-touch matrix: transport, sudo, PVE API, and shims."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from freq.modules.pve import _pve_api_call


class _Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({"data": self.data}).encode()


def _pve_cfg(token_id="freqtest@pam!fixture", secret="fixture-secret"):
    return SimpleNamespace(
        pve_api_token_id=token_id,
        pve_api_token_secret=secret,
        pve_api_verify_ssl=False,
        credentials_dir="/nonexistent",
    )


def _fake_pve_call(endpoint, data, cfg=None):
    with patch(
        "freq.modules.pve.urllib.request.urlopen",
        return_value=_Response(data),
    ) as urlopen:
        result, ok = _pve_api_call(cfg or _pve_cfg(), "127.0.0.1", endpoint)
    return result, ok, urlopen.call_args.args[0]


def test_fixture_ssh_is_reachable(ephemeral_lab):
    result = ephemeral_lab.ssh("hostname")
    assert result.returncode == 0, result.stderr


def test_fixture_returns_expected_hostname(ephemeral_lab):
    result = ephemeral_lab.ssh("hostname")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "freq-lab"


def test_sudo_works_on_managed_fixture(ephemeral_lab):
    result = ephemeral_lab.ssh("whoami", use_sudo=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "root"


def test_qm_list_runs_on_pve_profile(ephemeral_lab):
    result = ephemeral_lab.ssh("qm list", htype="pve", use_sudo=True)
    assert result.returncode == 0, result.stderr
    assert "VMID NAME" in result.stdout
    assert "6000 freq-lab-fixture" in result.stdout


def test_pve_rw_token_returns_data_from_hermetic_boundary():
    data, ok, request = _fake_pve_call("/version", {"version": "8.2"})
    assert ok is True
    assert data["version"] == "8.2"
    assert request.get_header("Authorization").startswith(
        "PVEAPIToken=freqtest@pam!fixture="
    )


def test_pve_ro_token_returns_data_from_hermetic_boundary():
    cfg = _pve_cfg("freq-watch@pve!watch", "read-only-secret")
    data, ok, request = _fake_pve_call("/version", {"version": "8.2"}, cfg)
    assert ok is True
    assert data["version"] == "8.2"
    assert request.get_header("Authorization") == (
        "PVEAPIToken=freq-watch@pve!watch=read-only-secret"
    )


def test_pve_cluster_nodes_are_parsed_from_api_response():
    nodes = [{"node": "pve-lab", "status": "online"}]
    data, ok, _ = _fake_pve_call("/nodes", nodes)
    assert ok is True
    assert data == nodes


def test_physical_switch_access_stays_in_live_hardware_gate():
    pytest.skip(
        "physical Cisco IOS has no disposable emulator; no fake green switch result"
    )


def test_docker_ps_runs_on_docker_profile(ephemeral_lab):
    result = ephemeral_lab.ssh(
        "docker ps --format '{{.Names}}'", htype="docker", use_sudo=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "freq-lab-container"


def test_ephemeral_target_is_loopback_only(ephemeral_lab):
    assert ephemeral_lab.host == "127.0.0.1"


def test_strict_host_key_rejects_an_untrusted_key(ephemeral_lab, tmp_path):
    wrong_known_hosts = tmp_path / "known_hosts"
    wrong_known_hosts.write_text(
        f"[{ephemeral_lab.host}]:{ephemeral_lab.port} "
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForNegativeTestOnly\n"
    )
    from freq.core.ssh import run

    result = run(
        host=ephemeral_lab.host,
        command="hostname",
        user=ephemeral_lab.user,
        key_path=str(ephemeral_lab.key),
        connect_timeout=2,
        command_timeout=5,
        htype="linux",
        use_sudo=False,
        cfg=ephemeral_lab.config(),
        port=ephemeral_lab.port,
        known_hosts_file=str(wrong_known_hosts),
    )
    assert result.returncode != 0
    assert "Host key verification failed" in result.stderr
