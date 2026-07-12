"""Canonical deployment backend for the dependency-free FREQ metrics agent."""

from __future__ import annotations

import os
import time
from typing import Callable

from freq.core.ssh import run as ssh_run
from freq.modules.agent_health import remote_agent_health_command

AGENT_REMOTE_DIR = "/opt/freq-agent"
AGENT_REMOTE_PATH = f"{AGENT_REMOTE_DIR}/collector.py"
AGENT_SERVICE_NAME = "freq-agent"
AGENT_UNIT_PATH = f"/etc/systemd/system/{AGENT_SERVICE_NAME}.service"

DEPLOY_CONNECT_TIMEOUT = 5


def systemd_unit(port: int) -> str:
    """Return the one supported service definition for the metrics agent."""
    return f"""[Unit]
Description=FREQ Metrics Agent
After=network.target

[Service]
Type=simple
Environment=FREQ_AGENT_PORT={int(port)}
ExecStart=/usr/bin/env python3 {AGENT_REMOTE_PATH}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def _source_candidates(install_dir: str = "") -> list[str]:
    candidates = [os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent_collector.py")]
    if install_dir:
        candidates.append(os.path.join(install_dir, "freq", "agent_collector.py"))
    return candidates


def load_agent_source(install_dir: str = "") -> tuple[str, str]:
    """Load the packaged collector, with an install-tree fallback for init."""
    for path in _source_candidates(install_dir):
        try:
            with open(path) as source:
                return source.read(), path
        except FileNotFoundError:
            continue
    raise FileNotFoundError(_source_candidates(install_dir)[-1])


def _heredoc(path: str, content: str, marker: str) -> str:
    """Build a literal remote write whose delimiter cannot collide with data."""
    while marker in content:
        marker += "_X"
    return f"cat > {path} << '{marker}'\n{content.rstrip()}\n{marker}"


def _step_result(name: str, result) -> dict:
    ok = result.returncode == 0
    return {
        "step": name,
        "ok": ok,
        "returncode": result.returncode,
        "error": "" if ok else (result.stderr or result.stdout or "").strip(),
    }


def deploy_to_host(
    cfg,
    host,
    *,
    agent_code: str,
    key_path: str | None = None,
    settle_seconds: float = 1,
    runner: Callable = ssh_run,
) -> dict:
    """Deploy, restart, and verify the agent through the canonical SSH path."""
    port = int(getattr(cfg, "agent_port", 9990) or 9990)
    key_path = key_path or cfg.ssh_key_path
    outcome = {
        "host": host.label,
        "ip": host.ip,
        "agent_port": port,
        "status": "failed",
        "steps": [],
    }

    def run_step(name: str, command: str, timeout: int, *, use_sudo: bool = True):
        result = runner(
            host=host.ip,
            command=command,
            key_path=key_path,
            connect_timeout=DEPLOY_CONNECT_TIMEOUT,
            command_timeout=timeout,
            htype=host.htype,
            use_sudo=use_sudo,
            cfg=cfg,
        )
        step = _step_result(name, result)
        outcome["steps"].append(step)
        if not step["ok"]:
            outcome["error"] = f"{name} failed"
        return step["ok"]

    operations = (
        ("mkdir", f"mkdir -p {AGENT_REMOTE_DIR}", 10),
        ("upload", _heredoc(AGENT_REMOTE_PATH, agent_code, "FREQ_AGENT_SOURCE"), 30),
        ("chmod", f"chmod 0755 {AGENT_REMOTE_PATH}", 5),
        ("systemd_unit", _heredoc(AGENT_UNIT_PATH, systemd_unit(port), "FREQ_AGENT_UNIT"), 10),
        (
            "start",
            f"systemctl daemon-reload && systemctl enable {AGENT_SERVICE_NAME} && "
            f"systemctl restart {AGENT_SERVICE_NAME}",
            30,
        ),
    )
    for name, command, timeout in operations:
        if not run_step(name, command, timeout):
            return outcome

    if settle_seconds:
        time.sleep(settle_seconds)
    if run_step("verify", remote_agent_health_command(port), 5, use_sudo=False):
        outcome["status"] = "deployed"
        outcome.pop("error", None)
    else:
        outcome["status"] = "deployed_unverified"
        outcome["error"] = "health verification failed"
    return outcome
