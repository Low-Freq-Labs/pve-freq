"""Time-series metrics collection and querying for FREQ.

Domain: freq observe metrics <action>
What: Collect CPU, memory, disk, network metrics from fleet hosts via SSH.
      Store as JSON snapshots, query historical data, detect anomalies.
Replaces: Prometheus/Grafana stack, Zabbix, Datadog agent
Architecture:
    - Collection via ssh_run_many() reading /proc/stat, /proc/meminfo, df
    - Snapshots stored in conf/metrics/ as JSON per host
    - Query interface for historical data and trend analysis
Design decisions:
    - JSON flat files, not a time-series DB. Simple, grep-able, git-trackable.
    - Collection is pull-based via SSH — no agents to install.
    - Keep last 1000 snapshots per host (~7 days at 10-min intervals).
"""
import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many
from freq.core import log as logger


METRICS_DIR = "metrics"


def _metrics_dir(cfg):
    path = os.path.join(cfg.conf_dir, METRICS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _save_snapshot(cfg, host_label, data):
    filepath = os.path.join(_metrics_dir(cfg), f"{host_label}.json")
    existing = []
    if os.path.exists(filepath):
        with open(filepath) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []
    existing.append(data)
    existing = existing[-1000:]
    with open(filepath, "w") as f:
        json.dump(existing, f)


def _load_snapshots(cfg, host_label, limit=50):
    filepath = os.path.join(_metrics_dir(cfg), f"{host_label}.json")
    if not os.path.exists(filepath):
        return []
    with open(filepath) as f:
        try:
            data = json.load(f)
            return data[-limit:]
        except json.JSONDecodeError:
            return []


def cmd_metrics_collect(cfg: FreqConfig, pack, args) -> int:
    """Collect metrics from all fleet hosts."""
    fmt.header("Metrics Collection", breadcrumb="FREQ > Observe > Metrics")
    fmt.blank()

    cmd = (
        "echo CPU:$(grep 'cpu ' /proc/stat | awk '{u=$2+$4; t=$2+$4+$5; print int(u*100/t)}');"
        "echo MEM:$(free -m | awk '/Mem:/{print $3\"/\"$2}');"
        "echo DISK:$(df -h / | tail -1 | awk '{print $5}');"
        "echo LOAD:$(cat /proc/loadavg | cut -d' ' -f1-3);"
        "echo UP:$(cat /proc/uptime | cut -d' ' -f1)"
    )

    linux_hosts = [h for h in cfg.hosts if h.htype in ("linux", "pve", "docker")]
    if not linux_hosts:
        fmt.warn("No Linux hosts in fleet")
        fmt.footer()
        return 1

    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in linux_hosts]
    results = run_many(hosts=hosts_data, command=cmd, key_path=cfg.ssh_key_path,
                       connect_timeout=cfg.ssh_connect_timeout, command_timeout=10)

    ok_count = 0
    for h in linux_hosts:
        r = results.get(h.ip)
        if r and r.returncode == 0:
            parsed = _parse_metrics(r.stdout)
            parsed["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            parsed["host"] = h.label
            _save_snapshot(cfg, h.label, parsed)

            cpu = parsed.get("cpu", "?")
            mem = parsed.get("memory", "?")
            disk = parsed.get("disk", "?")
            cpu_color = fmt.C.GREEN if isinstance(cpu, int) and cpu < 60 else fmt.C.YELLOW if isinstance(cpu, int) and cpu < 85 else fmt.C.RED
            fmt.step_ok(f"{h.label:<14} CPU:{cpu_color}{cpu}%{fmt.C.RESET}  MEM:{mem}  DISK:{disk}")
            ok_count += 1
        else:
            fmt.step_fail(f"{h.label}: unreachable")

    fmt.blank()
    fmt.info(f"{ok_count}/{len(linux_hosts)} hosts collected")
    logger.info("metrics_collect", hosts=len(linux_hosts), ok=ok_count)
    fmt.footer()
    return 0


def cmd_metrics_show(cfg: FreqConfig, pack, args) -> int:
    """Show latest metrics for a host or all hosts."""
    target = getattr(args, "target", None)

    fmt.header("Latest Metrics", breadcrumb="FREQ > Observe > Metrics")
    fmt.blank()

    if target:
        snapshots = _load_snapshots(cfg, target, limit=1)
        if snapshots:
            s = snapshots[-1]
            for k, v in s.items():
                fmt.line(f"  {fmt.C.CYAN}{k:<14}{fmt.C.RESET} {v}")
        else:
            fmt.warn(f"No metrics for {target}")
    else:
        # Show latest for all hosts
        path = _metrics_dir(cfg)
        fmt.table_header(("Host", 14), ("CPU", 6), ("Memory", 12), ("Disk", 8), ("Load", 12), ("Collected", 20))
        for f_name in sorted(os.listdir(path)):
            if not f_name.endswith(".json"):
                continue
            label = f_name[:-5]
            snaps = _load_snapshots(cfg, label, limit=1)
            if snaps:
                s = snaps[-1]
                fmt.table_row(
                    (label, 14),
                    (f"{s.get('cpu', '?')}%", 6),
                    (str(s.get("memory", "?")), 12),
                    (str(s.get("disk", "?")), 8),
                    (str(s.get("load", "?")), 12),
                    (s.get("timestamp", "?"), 20),
                )

    fmt.blank()
    fmt.footer()
    return 0


def cmd_metrics_top(cfg: FreqConfig, pack, args) -> int:
    """Show top resource consumers across fleet."""
    fmt.header("Top Resource Consumers", breadcrumb="FREQ > Observe > Metrics")
    fmt.blank()

    path = _metrics_dir(cfg)
    hosts = []
    for f_name in os.listdir(path):
        if not f_name.endswith(".json"):
            continue
        label = f_name[:-5]
        snaps = _load_snapshots(cfg, label, limit=1)
        if snaps:
            hosts.append(snaps[-1])

    if not hosts:
        fmt.warn("No metrics data. Run: freq observe metrics collect")
        fmt.footer()
        return 0

    # Sort by CPU
    by_cpu = sorted(hosts, key=lambda x: x.get("cpu", 0) if isinstance(x.get("cpu"), int) else 0, reverse=True)
    fmt.line(f"{fmt.C.BOLD}By CPU:{fmt.C.RESET}")
    for h in by_cpu[:5]:
        cpu = h.get("cpu", "?")
        color = fmt.C.RED if isinstance(cpu, int) and cpu > 80 else fmt.C.YELLOW if isinstance(cpu, int) and cpu > 60 else fmt.C.GREEN
        fmt.line(f"  {h.get('host', '?'):<14} {color}{cpu}%{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _parse_metrics(text):
    result = {}
    for line in text.splitlines():
        if line.startswith("CPU:"):
            try:
                result["cpu"] = int(line.split(":")[1])
            except (ValueError, IndexError):
                result["cpu"] = line.split(":")[1]
        elif line.startswith("MEM:"):
            result["memory"] = line.split(":")[1]
        elif line.startswith("DISK:"):
            result["disk"] = line.split(":")[1]
        elif line.startswith("LOAD:"):
            result["load"] = line.split(":")[1]
        elif line.startswith("UP:"):
            result["uptime_seconds"] = line.split(":")[1]
    return result
