"""Behavior contract for the credential-free ``freq doctor --local`` gate."""

from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from freq import cli
from freq.core import doctor


LOCAL_CHECKS = (
    "_check_python",
    "_check_platform",
    "_check_prerequisites",
    "_check_install_dir",
    "_check_config",
    "_check_data_dirs",
    "_check_personality",
    "_check_rbac_bootstrap",
    "_check_users_conf_fallback",
    "_check_ssh_binary",
    "_check_ssh_key",
    "_check_legacy_passwords",
    "_check_truenas_api_credentials_local",
    "_check_hosts",
    "_check_hosts_validity",
    "_check_vlans",
    "_check_distros",
    "_check_pve_token_local",
)

REMOTE_CHECKS = (
    "_check_fleet_connectivity",
    "_check_service_account",
    "_check_truenas_api_credentials",
    "_check_pve_nodes",
    "_check_pve_token_drift",
)


def _patched_local_checks(results=None):
    stack = ExitStack()
    results = results or {}
    for name in LOCAL_CHECKS:
        result = results.get(name, 0)

        def fake_check(_cfg, *, _result=result):
            return _result

        fake_check.__name__ = name
        stack.enter_context(patch.object(doctor, name, new=fake_check))
    for name in REMOTE_CHECKS:
        stack.enter_context(
            patch.object(doctor, name, side_effect=AssertionError(f"remote check ran: {name}"))
        )
    return stack


def test_cli_parses_local_doctor_scope():
    args = cli._build_parser().parse_args(["doctor", "--local", "--json"])

    assert args.domain == "doctor"
    assert args.local_only is True
    assert args.json_output is True


def test_hermetic_fixture_local_doctor_is_exit_zero(tmp_path):
    runtime = tmp_path / "runtime"
    shutil.copytree(Path("tests/fixtures/ci-runtime"), runtime)
    env = {**os.environ, "FREQ_DIR": str(runtime)}

    result = subprocess.run(
        [sys.executable, "-m", "freq", "doctor", "--local", "--json"],
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["scope"] == "local"
    assert payload["failed"] == 0
    assert payload["warnings"] >= 1


def test_local_scope_retains_config_and_fleet_data_without_remote_calls(capsys):
    with _patched_local_checks(), patch("freq.core.log.save_health") as save_health:
        rc = doctor.run(SimpleNamespace(), json_output=True, local_only=True)

    payload = json.loads(capsys.readouterr().out)
    names = {item["name"] for item in payload["checks"]}
    assert rc == 0
    assert payload["scope"] == "local"
    assert payload["total"] == len(LOCAL_CHECKS)
    assert {
        "check_prerequisites",
        "check_config",
        "check_data_dirs",
        "check_hosts",
        "check_hosts_validity",
        "check_vlans",
        "check_distros",
    } <= names
    assert not any(name.removeprefix("_") in names for name in REMOTE_CHECKS)
    save_health.assert_not_called()


def test_local_scope_exit_code_fails_only_for_retained_failures(capsys):
    results = {"_check_config": 1, "_check_ssh_key": 2}
    with _patched_local_checks(results):
        rc = doctor.run(SimpleNamespace(), json_output=True, local_only=True)

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["failed"] == 1
    assert payload["warnings"] == 1


def test_local_scope_warnings_remain_exit_zero(capsys):
    with _patched_local_checks({"_check_ssh_key": 2}):
        rc = doctor.run(SimpleNamespace(), json_output=True, local_only=True)

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["status"] == "degraded"
    assert payload["warnings"] == 1


def test_local_pve_token_check_never_probes_a_node():
    cfg = SimpleNamespace(
        pve_nodes=["10.0.0.1"],
        pve_api_token_secret="secret",
        pve_api_token_id="freq-admin@pam!freq-rw",
        ssh_service_account="freq-admin",
    )
    with patch.object(doctor, "_probe_pve_api_token") as probe:
        result = doctor._check_pve_token_local(cfg)

    assert result == 0
    probe.assert_not_called()


def test_local_truenas_credential_check_never_requests_target():
    device = SimpleNamespace(
        label="nas01",
        device_type="truenas",
        scope="core",
    )
    cfg = SimpleNamespace(
        fleet_boundaries=SimpleNamespace(physical={"nas01": device}),
        truenas_ip="",
    )
    with (
        patch("freq.core.truenas_api.settings", return_value={"api_key": "secret"}),
        patch("freq.core.truenas_api.request") as request,
    ):
        result = doctor._check_truenas_api_credentials_local(cfg)

    assert result == 0
    request.assert_not_called()
