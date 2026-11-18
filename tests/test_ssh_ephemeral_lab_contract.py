"""Behavioral contract for disposable SSH integration targets."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from freq.core.ssh import _build_ssh_cmd, run, run_many
from freq.core.types import CmdResult, Host

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return SimpleNamespace(
        ssh_service_account="freqtest",
        ssh_connect_timeout=2,
        legacy_password_file="",
    )


def test_default_transport_keeps_accept_new_and_port_22_behavior(tmp_path):
    cmd = _build_ssh_cmd(
        host="127.0.0.1",
        command="hostname",
        key_path=str(tmp_path / "id"),
        use_sudo=False,
        cfg=_cfg(),
    )

    assert "StrictHostKeyChecking=accept-new" in cmd
    assert "-p" not in cmd
    assert not any(item.startswith("UserKnownHostsFile=") for item in cmd)


def test_ephemeral_target_uses_mapped_port_and_pinned_known_hosts(tmp_path):
    known_hosts = tmp_path / "known_hosts"
    known_hosts.write_text("[127.0.0.1]:42022 ssh-ed25519 fixture-key\n")
    cmd = _build_ssh_cmd(
        host="127.0.0.1",
        command="hostname",
        key_path=str(tmp_path / "id"),
        use_sudo=False,
        cfg=_cfg(),
        port=42022,
        known_hosts_file=str(known_hosts),
    )

    assert cmd[cmd.index("-p") + 1] == "42022"
    assert "StrictHostKeyChecking=yes" in cmd
    assert "StrictHostKeyChecking=accept-new" not in cmd
    assert f"UserKnownHostsFile={known_hosts}" in cmd
    assert "ControlMaster=auto" not in cmd
    assert not any(item.startswith("ControlPath=") for item in cmd)


def test_sync_run_propagates_ephemeral_transport_options(tmp_path):
    completed = SimpleNamespace(returncode=0, stdout="freq-lab\n", stderr="")
    with patch("freq.core.ssh.subprocess.run", return_value=completed) as subprocess_run:
        result = run(
            host="127.0.0.1",
            command="hostname",
            user="freqtest",
            key_path=str(tmp_path / "id"),
            use_sudo=False,
            cfg=_cfg(),
            port=42022,
            known_hosts_file=str(tmp_path / "known_hosts"),
        )

    command = subprocess_run.call_args.args[0]
    assert result.returncode == 0
    assert command[command.index("-p") + 1] == "42022"
    assert f"UserKnownHostsFile={tmp_path / 'known_hosts'}" in command

    with patch("freq.core.ssh.subprocess.run", return_value=completed) as subprocess_run:
        result = run(
            host="127.0.0.1",
            command='midclt call sharing.nfs.create "$(cat)"',
            user="freqtest",
            key_path=str(tmp_path / "id"),
            use_sudo=False,
            cfg=_cfg(),
            input_text='{"path":"/mnt/tank/share","networks":["192.0.2.0/24"]}',
        )

    assert result.returncode == 0
    assert subprocess_run.call_args.kwargs["input"] == (
        '{"path":"/mnt/tank/share","networks":["192.0.2.0/24"]}'
    )
    assert subprocess_run.call_args.kwargs["stdin"] is None


def test_run_many_propagates_one_ephemeral_endpoint_contract(tmp_path):
    result = CmdResult(stdout="freq-lab", stderr="", returncode=0, duration=0.01)
    fake_async_run = AsyncMock(return_value=result)
    host = Host(ip="127.0.0.1", label="freq-lab", htype="linux")

    with patch("freq.core.ssh.async_run", fake_async_run):
        results = run_many(
            hosts=[host],
            command="hostname",
            key_path=str(tmp_path / "id"),
            use_sudo=False,
            cfg=_cfg(),
            port=42022,
            known_hosts_file=str(tmp_path / "known_hosts"),
        )

    assert results["freq-lab"] is result
    assert fake_async_run.await_args.kwargs["port"] == 42022
    assert fake_async_run.await_args.kwargs["known_hosts_file"] == str(
        tmp_path / "known_hosts"
    )


def test_integration_wrapper_opts_live_nodes_into_collection(tmp_path):
    wrapper = tmp_path / "run-integration"
    shutil.copy(REPO_ROOT / "tests/ephemeral-lab/run-integration", wrapper)
    wrapper.chmod(0o755)

    lab = tmp_path / "ephemeral-lab"
    lab.write_text("#!/usr/bin/env bash\nexit 0\n")
    lab.chmod(0o755)

    python = tmp_path / "python"
    python.write_text(
        "#!/usr/bin/env bash\n"
        'test "${FREQ_EPHEMERAL_LAB_TESTS:-}" = "1" || exit 91\n'
        'test "$*" = "-m pytest -q -rs '
        "tests/test_ssh_ephemeral_lab_contract.py "
        "tests/test_fleet_auth_drift.py "
        "tests/test_fleet_status_e2e.py "
        'tests/test_fleet_touch_matrix.py" || exit 92\n'
    )
    python.chmod(0o755)

    completed = subprocess.run(
        [str(wrapper)],
        cwd=REPO_ROOT,
        env={**os.environ, "PVE_FREQ_PYTHON": str(python)},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
