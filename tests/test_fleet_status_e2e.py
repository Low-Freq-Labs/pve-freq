"""End-to-end fleet status behavior against the disposable SSH lab."""

from __future__ import annotations

import pytest

from freq.core.ssh import result_for


def _fleet_result(ephemeral_lab, *, htype="linux", command="uptime -p"):
    host, results = ephemeral_lab.ssh_many(command, htype=htype)
    return host, result_for(results, host)


def test_all_managed_fixture_hosts_are_online(ephemeral_lab):
    host, result = _fleet_result(ephemeral_lab)
    assert host.label == "freq-lab"
    assert result is not None
    assert result.returncode == 0, result.stderr


def test_pve_transport_profile_is_online(ephemeral_lab):
    _, result = _fleet_result(ephemeral_lab, htype="pve")
    assert result.returncode == 0, result.stderr


def test_docker_transport_and_command_are_online(ephemeral_lab):
    _, result = _fleet_result(
        ephemeral_lab,
        htype="docker",
        command="docker ps --format '{{.Names}}'",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "freq-lab-container"


def test_truenas_transport_profile_is_online(ephemeral_lab):
    _, result = _fleet_result(ephemeral_lab, htype="truenas")
    assert result.returncode == 0, result.stderr


def test_pfsense_transport_profile_is_online(ephemeral_lab):
    _, result = _fleet_result(ephemeral_lab, htype="pfsense")
    assert result.returncode == 0, result.stderr


def test_uptime_output_is_sane(ephemeral_lab):
    result = ephemeral_lab.ssh("uptime -p")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "up 1 hour, 2 minutes"


def test_runtime_config_matches_ephemeral_contract(ephemeral_lab):
    cfg = ephemeral_lab.config()
    assert cfg.ssh_service_account == ephemeral_lab.user
    assert cfg.ssh_key_path == str(ephemeral_lab.key)
    assert cfg.ssh_connect_timeout == 3


def test_physical_cisco_switch_is_explicitly_outside_hermetic_lab():
    pytest.skip(
        "physical Cisco IOS has no disposable emulator; keep in the separate live hardware gate"
    )
