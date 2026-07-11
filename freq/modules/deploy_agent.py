"""FREQ metrics agent deployment for fleet hosts.

Domain: freq fleet <deploy-agent|agent-status>

Copies the lightweight Python metrics collector to fleet hosts, creates a
systemd service unit, enables and starts it. Agent exposes host metrics on
a configurable port (default 9990) for the dashboard to poll.

Replaces: Prometheus node_exporter + Ansible deploy playbook,
          Telegraf ($0 but heavy config), manual agent installs

Architecture:
    - agent_deployment.py owns upload, service, restart, and verification
    - Agent binary is agent_collector.py, written through the shared SSH path
    - One systemd unit is generated dynamically with configurable port
    - Agent serves JSON metrics over HTTP on localhost
    - Status check polls agent HTTP endpoint from Nexus

Design decisions:
    - Agent is a single Python file, not a package. SCP one file, create
      one service, done. No pip, no venv, no package manager on the target.
"""

import json
import urllib.error
import urllib.request

from freq.core import fmt
from freq.core import resolve
from freq.core.config import FreqConfig
from freq.modules.agent_deployment import deploy_to_host, load_agent_source

AGENT_CHECK_TIMEOUT = 3

AGENT_PORT = 9990  # default — overridden by cfg.agent_port at deploy time


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
    try:
        agent_code, _agent_src = load_agent_source(cfg.install_dir)
    except FileNotFoundError as exc:
        fmt.error(f"Agent source not found: {exc}")
        return 1

    ok_count = 0
    fail_count = 0

    for h in hosts:
        fmt.step_start(f"{h.label}")

        outcome = deploy_to_host(cfg, h, agent_code=agent_code)
        if outcome["status"] == "deployed":
            fmt.step_ok(f"{h.label}: agent running on port {AGENT_PORT}")
            ok_count += 1
        elif outcome["status"] == "deployed_unverified":
            fmt.step_warn(f"{h.label}: deployed but health check failed (may need a moment)")
            ok_count += 1
        else:
            fmt.step_fail(f"{h.label}: {outcome.get('error', 'deployment failed')}")
            fail_count += 1

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{ok_count}{fmt.C.RESET} deployed  {fmt.C.RED}{fail_count}{fmt.C.RESET} failed")
    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}Metrics: curl http://<host>:{AGENT_PORT}/metrics{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.GRAY}Service: systemctl status freq-agent{fmt.C.RESET}")
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
