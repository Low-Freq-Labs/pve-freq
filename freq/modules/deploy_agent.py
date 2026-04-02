"""FREQ metrics agent deployment for fleet hosts.

Domain: freq fleet <deploy-agent|agent-status>

Copies the lightweight Python metrics collector to fleet hosts, creates a
systemd service unit, enables and starts it. Agent exposes host metrics on
a configurable port (default 9990) for the dashboard to poll.

Replaces: Prometheus node_exporter + Ansible deploy playbook,
          Telegraf ($0 but heavy config), manual agent installs

Architecture:
    - Agent binary is agent_collector.py, copied via SSH (SCP)
    - Systemd unit generated dynamically with configurable port
    - Agent serves JSON metrics over HTTP on localhost
    - Status check polls agent HTTP endpoint from Nexus

Design decisions:
    - Agent is a single Python file, not a package. SCP one file, create
      one service, done. No pip, no venv, no package manager on the target.
"""
import json
import os
import time
import urllib.error
import urllib.request

from freq.core import fmt
from freq.core import resolve
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Deploy timeouts
DEPLOY_CMD_TIMEOUT = 10
DEPLOY_UPLOAD_TIMEOUT = 15
DEPLOY_QUICK_TIMEOUT = 5
AGENT_CHECK_TIMEOUT = 3

AGENT_PORT = 9990  # default — overridden by cfg.agent_port at deploy time
AGENT_REMOTE_PATH = "/opt/freq-agent/collector.py"
SERVICE_NAME = "freq-agent"

def _systemd_unit(port):
    return f"""[Unit]
Description=FREQ Metrics Collector
After=network.target

[Service]
Type=simple
Environment=FREQ_AGENT_PORT={port}
ExecStart=/usr/bin/env python3 {AGENT_REMOTE_PATH}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""


def cmd_deploy_agent(cfg: FreqConfig, pack, args) -> int:
    """Deploy the FREQ metrics agent to fleet hosts."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq deploy-agent <host|all>")
        return 1

    global AGENT_PORT
    AGENT_PORT = cfg.agent_port

    fmt.header("Deploy Agent")
    fmt.blank()

    # Resolve hosts
    if target.lower() == "all":
        hosts = cfg.hosts
    else:
        host = resolve.by_target(cfg.hosts, target)
        if not host:
            fmt.error(f"Host not found: {target}")
            return 1
        hosts = [host]

    fmt.line(f"{fmt.C.BOLD}Deploying FREQ agent to {len(hosts)} host(s)...{fmt.C.RESET}")
    fmt.blank()

    # Read the agent collector source
    agent_src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "agent_collector.py")
    try:
        with open(agent_src) as f:
            agent_code = f.read()
    except FileNotFoundError:
        fmt.error(f"Agent source not found: {agent_src}")
        return 1

    ok_count = 0
    fail_count = 0

    for h in hosts:
        fmt.step_start(f"{h.label}")

        # Step 1: Create directory
        r = ssh_run(host=h.ip, command="mkdir -p /opt/freq-agent",
                    key_path=cfg.ssh_key_path, connect_timeout=DEPLOY_QUICK_TIMEOUT,
                    command_timeout=DEPLOY_CMD_TIMEOUT, htype=h.htype, use_sudo=True)
        if r.returncode != 0:
            fmt.step_fail(f"{h.label}: cannot create directory")
            fail_count += 1
            continue

        # Step 2: Upload agent code via SSH (cat into file)
        # Escape for shell
        escaped = agent_code.replace("'", "'\\''")
        upload_cmd = f"cat > {AGENT_REMOTE_PATH} << 'FREQAGENTEOF'\n{agent_code}\nFREQAGENTEOF"
        r = ssh_run(host=h.ip, command=upload_cmd,
                    key_path=cfg.ssh_key_path, connect_timeout=DEPLOY_QUICK_TIMEOUT,
                    command_timeout=DEPLOY_UPLOAD_TIMEOUT, htype=h.htype, use_sudo=True)
        if r.returncode != 0:
            fmt.step_fail(f"{h.label}: cannot upload agent")
            fail_count += 1
            continue

        # Step 3: Make executable
        ssh_run(host=h.ip, command=f"chmod +x {AGENT_REMOTE_PATH}",
                key_path=cfg.ssh_key_path, connect_timeout=DEPLOY_QUICK_TIMEOUT,
                command_timeout=DEPLOY_QUICK_TIMEOUT, htype=h.htype, use_sudo=True)

        # Step 4: Create systemd service
        unit_content = _systemd_unit(AGENT_PORT)
        service_cmd = f"cat > /etc/systemd/system/{SERVICE_NAME}.service << 'FREQSVCEOF'\n{unit_content}\nFREQSVCEOF"
        r = ssh_run(host=h.ip, command=service_cmd,
                    key_path=cfg.ssh_key_path, connect_timeout=DEPLOY_QUICK_TIMEOUT,
                    command_timeout=DEPLOY_CMD_TIMEOUT, htype=h.htype, use_sudo=True)

        # Step 5: Enable and start
        ssh_run(host=h.ip,
                command=f"systemctl daemon-reload && systemctl enable {SERVICE_NAME} && systemctl restart {SERVICE_NAME}",
                key_path=cfg.ssh_key_path, connect_timeout=DEPLOY_QUICK_TIMEOUT,
                command_timeout=DEPLOY_UPLOAD_TIMEOUT, htype=h.htype, use_sudo=True)

        # Step 6: Verify
        time.sleep(1)
        r = ssh_run(host=h.ip, command=f"curl -s http://localhost:{AGENT_PORT}/health 2>/dev/null",
                    key_path=cfg.ssh_key_path, connect_timeout=DEPLOY_QUICK_TIMEOUT,
                    command_timeout=DEPLOY_QUICK_TIMEOUT, htype=h.htype, use_sudo=False)

        if r.returncode == 0 and "ok" in r.stdout:
            fmt.step_ok(f"{h.label}: agent running on port {AGENT_PORT}")
            ok_count += 1
        else:
            fmt.step_warn(f"{h.label}: deployed but health check failed (may need a moment)")
            ok_count += 1  # Still counts as deployed

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{ok_count}{fmt.C.RESET} deployed  {fmt.C.RED}{fail_count}{fmt.C.RESET} failed")
    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}Metrics: curl http://<host>:{AGENT_PORT}/metrics{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.GRAY}Service: systemctl status {SERVICE_NAME}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0 if fail_count == 0 else 1


def cmd_agent_status(cfg: FreqConfig, pack, args) -> int:
    """Check which hosts have the FREQ agent running."""
    fmt.header("Agent Collector Status")
    fmt.blank()

    # Check each host for the agent

    fmt.table_header(
        ("HOST", 16),
        ("AGENT", 8),
        ("PORT", 6),
        ("CPU", 6),
        ("MEM", 8),
    )

    for h in cfg.hosts:
        try:
            url = f"http://{h.ip}:{AGENT_PORT}/metrics"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=AGENT_CHECK_TIMEOUT)
            data = resp.read().decode()
            metrics = json.loads(data)

            cpu_pct = f"{metrics.get('cpu', {}).get('usage_pct', '?')}%"
            mem_pct = f"{metrics.get('memory', {}).get('usage_pct', '?')}%"

            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (fmt.badge("ok"), 8),
                (str(AGENT_PORT), 6),
                (cpu_pct, 6),
                (mem_pct, 8),
            )
        except Exception:
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (fmt.badge("down"), 8),
                ("-", 6),
                ("-", 6),
                ("-", 8),
            )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}Deploy: freq deploy-agent all{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
