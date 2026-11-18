"""Executable contract for the one metrics-agent deployment backend."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from freq.modules import agent_deployment


def _cfg():
    return SimpleNamespace(agent_port=9990, ssh_key_path="/tmp/fake-key", install_dir="/opt/pve-freq")


def _host(label="worker-1"):
    return SimpleNamespace(label=label, ip="192.0.2.10", htype="linux")


def _result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_systemd_unit_is_portable_and_uses_environment_contract():
    unit = agent_deployment.systemd_unit(10090)

    assert "Environment=FREQ_AGENT_PORT=10090" in unit
    assert f"ExecStart=/usr/bin/env python3 {agent_deployment.AGENT_REMOTE_PATH}" in unit
    assert " --port " not in unit
    assert "RestartSec=10" in unit
    assert unit.count("[Service]") == 1


def test_deploy_executes_one_fail_closed_plan_and_verifies_without_sudo():
    calls = []

    def runner(**kwargs):
        calls.append(kwargs)
        return _result(stdout='{"status":"ok"}')

    outcome = agent_deployment.deploy_to_host(
        _cfg(),
        _host(),
        agent_code="print('collector')\n",
        settle_seconds=0,
        runner=runner,
    )

    assert outcome["status"] == "deployed"
    assert [step["step"] for step in outcome["steps"]] == [
        "mkdir",
        "upload",
        "chmod",
        "systemd_unit",
        "start",
        "verify",
    ]
    assert all(call["cfg"] is not None for call in calls)
    assert all(call["key_path"] == "/tmp/fake-key" for call in calls)
    assert all(call["use_sudo"] for call in calls[:-1])
    assert calls[-1]["use_sudo"] is False
    assert "print('collector')" in calls[1]["command"]
    assert "Environment=FREQ_AGENT_PORT=9990" in calls[3]["command"]
    assert "systemctl restart freq-agent" in calls[4]["command"]
    assert "FREQ_AGENT_HEALTH_CHECK_NO_CLIENT" in calls[5]["command"]


def test_deploy_stops_at_first_failed_step():
    runner = Mock(side_effect=[_result(), _result(returncode=23, stderr="upload denied")])

    outcome = agent_deployment.deploy_to_host(
        _cfg(),
        _host(),
        agent_code="code",
        settle_seconds=0,
        runner=runner,
    )

    assert outcome["status"] == "failed"
    assert outcome["error"] == "upload failed"
    assert outcome["steps"][-1]["error"] == "upload denied"
    assert runner.call_count == 2


def test_deploy_distinguishes_installed_but_unverified():
    runner = Mock(side_effect=[_result()] * 5 + [_result(returncode=7, stderr="connection refused")])

    outcome = agent_deployment.deploy_to_host(
        _cfg(),
        _host(),
        agent_code="code",
        settle_seconds=0,
        runner=runner,
    )

    assert outcome["status"] == "deployed_unverified"
    assert outcome["error"] == "health verification failed"


def test_literal_upload_delimiter_cannot_collide_with_collector_source():
    command = agent_deployment._heredoc("/tmp/collector", "FREQ_AGENT_SOURCE\n", "FREQ_AGENT_SOURCE")
    lines = command.splitlines()

    assert lines[0].endswith("<< 'FREQ_AGENT_SOURCE_X'")
    assert lines[-1] == "FREQ_AGENT_SOURCE_X"


def test_cli_surface_calls_canonical_backend_for_each_host():
    from freq.modules import deploy_agent

    cfg = _cfg()
    cfg.hosts = [_host("one"), _host("two")]
    args = SimpleNamespace(target="all")
    with patch.object(deploy_agent, "load_agent_source", return_value=("code", "/source")), patch.object(
        deploy_agent,
        "deploy_to_host",
        side_effect=lambda cfg, host, **kwargs: {"status": "deployed", "host": host.label},
    ) as deploy:
        rc = deploy_agent.cmd_deploy_agent(cfg, None, args)

    assert rc == 0
    assert deploy.call_count == 2


def test_api_surface_calls_canonical_backend_and_preserves_results():
    from freq.api import fleet

    cfg = _cfg()
    cfg.hosts = [_host("one"), _host("two")]
    handler = SimpleNamespace(command="POST")
    responses = []
    results = [
        {"host": "one", "status": "deployed"},
        {"host": "two", "status": "failed", "error": "upload failed"},
    ]
    with patch.object(fleet, "require_post", return_value=False), patch.object(
        fleet, "_check_session_role", return_value=("admin", None)
    ), patch.object(fleet, "get_params", return_value={"target": ["all"]}), patch.object(
        fleet, "load_config", return_value=cfg
    ), patch("freq.modules.agent_deployment.load_agent_source", return_value=("code", "/source")), patch(
        "freq.modules.agent_deployment.deploy_to_host", side_effect=results
    ) as deploy, patch.object(fleet, "json_response", side_effect=lambda handler, payload, *args: responses.append(payload)):
        fleet.handle_deploy_agent(handler)

    assert deploy.call_count == 2
    assert responses[0]["deployed"] == 1
    assert responses[0]["failed"] == 1
    assert responses[0]["results"] == results


def test_init_surface_imports_the_same_backend_function():
    from freq.modules import init_cmd

    assert init_cmd.deploy_metrics_agent is agent_deployment.deploy_to_host
