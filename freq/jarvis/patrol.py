"""Continuous fleet monitoring with auto-remediation for FREQ.

Domain: freq auto patrol

Runs an infinite monitoring loop: connectivity checks, HTTP endpoint probes,
and policy drift detection every N seconds. Optionally auto-fixes drift when
--auto-fix is set.

Replaces: Nagios / Zabbix monitoring + cron-based remediation ($15k+/yr)

Architecture:
    - Main loop: SSH ping all hosts, check HTTP monitors, run policy engine
    - Policy drift checked every 3rd cycle to reduce SSH load
    - Uses run_sync() from engine.runner for fleet-wide policy evaluation

Design decisions:
    - Drift checks every 3rd cycle balances detection speed vs SSH overhead
    - auto-fix is opt-in and requires explicit flag — safety first
"""

import time
import urllib.request
import urllib.error

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many, result_for
from freq.engine.policies import ALL_POLICIES
from freq.engine.runner import run_sync
from freq.core.types import Phase

# Patrol timeouts
PATROL_CHECK_TIMEOUT = 10


def check_http_monitors(monitors: list) -> list:
    """Check HTTP endpoints defined in [[monitor]] config.

    Returns list of {name, url, status, ok, latency_ms, error} dicts.
    """
    results = []
    for mon in monitors:
        result = {
            "name": mon.name,
            "url": mon.url,
            "expected": mon.expected_status,
            "ok": False,
            "status": 0,
            "latency_ms": 0,
            "error": "",
        }

        start = time.monotonic()
        try:
            req = urllib.request.Request(mon.url, method=mon.method)
            req.add_header("User-Agent", "FREQ-Patrol/1.0")
            resp = urllib.request.urlopen(req, timeout=mon.timeout)
            result["status"] = resp.status
            result["latency_ms"] = int((time.monotonic() - start) * 1000)

            # Check status code
            if resp.status == mon.expected_status:
                result["ok"] = True

            # Check keyword if configured
            if mon.keyword and result["ok"]:
                body = resp.read(8192).decode("utf-8", errors="replace")
                if mon.keyword not in body:
                    result["ok"] = False
                    result["error"] = f"keyword '{mon.keyword}' not found"

        except urllib.error.HTTPError as e:
            result["status"] = e.code
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            result["error"] = str(e.reason)
        except urllib.error.URLError as e:
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            result["error"] = str(e.reason)
        except Exception as e:
            result["latency_ms"] = int((time.monotonic() - start) * 1000)
            result["error"] = str(e)

        results.append(result)

    return results


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
            down_hosts = [
                h.label for h in cfg.hosts if result_for(results, h) is None or result_for(results, h).returncode != 0
            ]

            if down > 0:
                print(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {down} host(s) DOWN: {', '.join(down_hosts)}")
            else:
                print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {up}/{len(cfg.hosts)} hosts UP")

            # 2. HTTP endpoint checks
            if cfg.monitors:
                mon_results = check_http_monitors(cfg.monitors)
                mon_ok = sum(1 for r in mon_results if r["ok"])
                mon_fail = len(mon_results) - mon_ok

                if mon_fail > 0:
                    for r in mon_results:
                        if not r["ok"]:
                            err = r["error"] or f"HTTP {r['status']}"
                            print(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {r['name']}: {err} ({r['latency_ms']}ms)")
                else:
                    print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {mon_ok}/{len(mon_results)} HTTP endpoints OK")

            # 3. Policy drift check (every 3rd cycle to reduce load)
            if cycle % 3 == 1:
                total_drift = 0
                for policy in ALL_POLICIES:
                    mode = "fix" if auto_fix else "check"
                    result = run_sync(
                        cfg.hosts,
                        policy,
                        cfg.ssh_key_path,
                        mode=mode,
                        max_parallel=cfg.ssh_max_parallel,
                    )
                    drift_hosts = [h for h in result.hosts if h.phase in (Phase.DRIFT, Phase.PLANNED)]
                    fixed_hosts = [h for h in result.hosts if h.phase == Phase.DONE]

                    if drift_hosts:
                        total_drift += len(drift_hosts)
                        for h in drift_hosts:
                            print(
                                f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}  {policy['name']}: {h.label} — {len(h.findings)} drift"
                            )
                    if fixed_hosts:
                        for h in fixed_hosts:
                            print(
                                f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {policy['name']}: {h.label} — auto-fixed {len(h.changes)} items"
                            )

                if total_drift == 0:
                    print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} All policies compliant")

            cycle_duration = time.monotonic() - cycle_start
            print(f"\n  {fmt.C.DIM}Cycle {cycle} complete ({cycle_duration:.1f}s). Next in {interval}s...{fmt.C.RESET}")
            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n\n  {fmt.C.YELLOW}Patrol stopped after {cycle} cycles.{fmt.C.RESET}\n")
        return 0
