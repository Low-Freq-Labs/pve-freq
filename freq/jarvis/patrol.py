"""Continuous monitoring with auto-remediation — FREQ patrol.

Like freq watch but smarter: monitors fleet health and automatically
triggers policy checks when drift is detected.

Usage:
  freq patrol                  # start monitoring (30s intervals)
  freq patrol --interval 60    # custom interval
  freq patrol --auto-fix       # auto-remediate drift (dangerous)
"""
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many
from freq.engine.policies import ALL_POLICIES
from freq.engine.runner import run_sync
from freq.core.types import Phase

# Patrol timeouts
PATROL_CHECK_TIMEOUT = 10


def cmd_patrol(cfg: FreqConfig, pack, args) -> int:
    """Continuous fleet monitoring with drift detection."""
    interval = getattr(args, "interval", None) or 30
    auto_fix = getattr(args, "auto_fix", False)

    fmt.header("Patrol" + (" — AUTO-FIX" if auto_fix else ""))
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Fleet:{fmt.C.RESET} {len(cfg.hosts)} hosts")
    fmt.line(f"{fmt.C.BOLD}Interval:{fmt.C.RESET} {interval}s")
    fmt.line(f"{fmt.C.BOLD}Policies:{fmt.C.RESET} {len(ALL_POLICIES)}")
    fmt.line(f"{fmt.C.BOLD}Auto-fix:{fmt.C.RESET} {'YES (will make changes)' if auto_fix else 'No (alert only)'}")
    fmt.blank()
    fmt.line(f"{fmt.C.DIM}Ctrl+C to stop{fmt.C.RESET}")
    fmt.blank()

    cycle = 0
    try:
        while True:
            cycle += 1
            cycle_start = time.monotonic()
            timestamp = time.strftime("%H:%M:%S")

            fmt.divider(f"Cycle {cycle} — {timestamp}")
            fmt.blank()

            # 1. Connectivity check
            results = ssh_run_many(
                hosts=cfg.hosts,
                command="echo ok",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=PATROL_CHECK_TIMEOUT,
                max_parallel=cfg.ssh_max_parallel,
                use_sudo=False,
            )

            up = sum(1 for r in results.values() if r and r.returncode == 0)
            down = len(cfg.hosts) - up
            down_hosts = [h.label for h in cfg.hosts if results.get(h.label) is None or results.get(h.label).returncode != 0]

            if down > 0:
                print(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {down} host(s) DOWN: {', '.join(down_hosts)}")
            else:
                print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {up}/{len(cfg.hosts)} hosts UP")

            # 2. Policy drift check (every 3rd cycle to reduce load)
            if cycle % 3 == 1:
                total_drift = 0
                for policy in ALL_POLICIES:
                    mode = "fix" if auto_fix else "check"
                    result = run_sync(
                        cfg.hosts, policy, cfg.ssh_key_path,
                        mode=mode, max_parallel=cfg.ssh_max_parallel,
                    )
                    drift_hosts = [h for h in result.hosts if h.phase in (Phase.DRIFT, Phase.PLANNED)]
                    fixed_hosts = [h for h in result.hosts if h.phase == Phase.DONE]

                    if drift_hosts:
                        total_drift += len(drift_hosts)
                        for h in drift_hosts:
                            print(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}  {policy['name']}: {h.label} — {len(h.findings)} drift")
                    if fixed_hosts:
                        for h in fixed_hosts:
                            print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {policy['name']}: {h.label} — auto-fixed {len(h.changes)} items")

                if total_drift == 0:
                    print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} All policies compliant")

            cycle_duration = time.monotonic() - cycle_start
            print(f"\n  {fmt.C.DIM}Cycle {cycle} complete ({cycle_duration:.1f}s). Next in {interval}s...{fmt.C.RESET}")
            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n  {fmt.C.YELLOW}Patrol stopped after {cycle} cycles.{fmt.C.RESET}\n")
        return 0
