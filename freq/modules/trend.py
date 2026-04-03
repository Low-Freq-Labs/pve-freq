"""Historical capacity trending for FREQ.

Domain: freq observe <trend-show|trend-snapshot|trend-history>

Not just "where is it now" but "where is it going." Stores periodic
snapshots of CPU, RAM, and disk usage across the fleet. Shows trends over
time so you can plan capacity before you are in trouble.

Replaces: New Relic (bill shock), Datadog (surprise invoices),
          Prometheus + Grafana ($0 but complex multi-component stack)

Architecture:
    - Snapshots gathered via parallel SSH (nproc, free, df per host)
    - Data stored in conf/trends/trend-data.json, rolling window (1000 max)
    - Trend display calculates deltas between snapshots over time
    - At 2-hour intervals, 1000 snapshots covers ~83 days of history

Design decisions:
    - Snapshots, not continuous streams. Trend data is sampled, not
      real-time. Keeps storage flat and queries instant.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many

# Storage
TREND_DIR = "trends"
TREND_FILE = "trend-data.json"
TREND_CMD_TIMEOUT = 15
MAX_SNAPSHOTS = 1000  # ~83 days at 2h intervals


def _trend_dir(cfg: FreqConfig) -> str:
    """Get or create trends directory."""
    path = os.path.join(cfg.conf_dir, TREND_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_trend_data(cfg: FreqConfig) -> list:
    """Load trend snapshots from disk."""
    filepath = os.path.join(_trend_dir(cfg), TREND_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_trend_data(cfg: FreqConfig, data: list):
    """Save trend data, keeping last MAX_SNAPSHOTS entries."""
    filepath = os.path.join(_trend_dir(cfg), TREND_FILE)
    with open(filepath, "w") as f:
        json.dump(data[-MAX_SNAPSHOTS:], f)


def _take_snapshot(cfg: FreqConfig) -> dict:
    """Take a point-in-time capacity snapshot of the fleet."""
    hosts = cfg.hosts
    if not hosts:
        return {}

    command = (
        'echo "$('
        "nproc"
        ")|$("
        "cat /proc/loadavg | awk '{print $1}'"
        ")|$("
        "free -m | awk '/Mem:/ {printf \"%d|%d\", $3, $2}'"
        ")|$("
        "df -BG / | awk 'NR==2 {printf \"%d|%d\", $3, $2}' | tr -d 'G'"
        ')"'
    )

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=TREND_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    snapshot = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "epoch": int(time.time()),
        "hosts": {},
        "fleet": {
            "total_cores": 0,
            "total_ram_mb": 0,
            "used_ram_mb": 0,
            "total_disk_gb": 0,
            "used_disk_gb": 0,
            "avg_load_ratio": 0,
        },
    }

    load_ratios = []
    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            continue

        parts = r.stdout.strip().split("|")
        if len(parts) >= 5:
            try:
                cores = int(parts[0])
                load = float(parts[1])
                ram_used = int(parts[2])
                ram_total = int(parts[3])
                disk_used = int(parts[4])
                disk_total = int(parts[5]) if len(parts) > 5 else 0

                snapshot["hosts"][h.label] = {
                    "cores": cores,
                    "load": load,
                    "ram_used": ram_used,
                    "ram_total": ram_total,
                    "disk_used": disk_used,
                    "disk_total": disk_total,
                }

                snapshot["fleet"]["total_cores"] += cores
                snapshot["fleet"]["total_ram_mb"] += ram_total
                snapshot["fleet"]["used_ram_mb"] += ram_used
                snapshot["fleet"]["total_disk_gb"] += disk_total
                snapshot["fleet"]["used_disk_gb"] += disk_used
                load_ratios.append(load / max(cores, 1))
            except (ValueError, IndexError):
                pass

    if load_ratios:
        snapshot["fleet"]["avg_load_ratio"] = round(sum(load_ratios) / len(load_ratios), 2)

    # Calculate percentages
    fleet = snapshot["fleet"]
    fleet["ram_pct"] = round(fleet["used_ram_mb"] / max(fleet["total_ram_mb"], 1) * 100, 1)
    fleet["disk_pct"] = round(fleet["used_disk_gb"] / max(fleet["total_disk_gb"], 1) * 100, 1)

    return snapshot


def _render_sparkline(values: list, width: int = 20) -> str:
    """Render a simple ASCII sparkline."""
    if not values:
        return ""
    bars = " ▁▂▃▄▅▆▇█"
    mn = min(values)
    mx = max(values)
    rng = mx - mn if mx != mn else 1

    # Downsample if needed
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values

    return "".join(bars[min(int((v - mn) / rng * 8), 8)] for v in sampled)


def cmd_trend(cfg: FreqConfig, pack, args) -> int:
    """Fleet capacity trends."""
    action = getattr(args, "action", None) or "show"

    if action == "snapshot":
        return _cmd_snapshot(cfg, args)
    elif action == "show":
        return _cmd_show(cfg, args)
    elif action == "history":
        return _cmd_history(cfg, args)

    fmt.error(f"Unknown trend action: {action}")
    fmt.info("Available: show, snapshot, history")
    return 1


def _cmd_snapshot(cfg: FreqConfig, args) -> int:
    """Take a capacity snapshot right now."""
    fmt.header("Trend Snapshot")
    fmt.blank()

    fmt.step_start("Capturing fleet metrics")
    snapshot = _take_snapshot(cfg)
    if not snapshot:
        fmt.step_fail("No hosts reachable")
        fmt.blank()
        fmt.footer()
        return 1

    data = _load_trend_data(cfg)
    data.append(snapshot)
    _save_trend_data(cfg, data)

    fleet = snapshot["fleet"]
    fmt.step_ok(f"Snapshot #{len(data)} captured")
    fmt.blank()
    fmt.line(f"  RAM:  {fleet['used_ram_mb']}MB / {fleet['total_ram_mb']}MB ({fleet['ram_pct']}%)")
    fmt.line(f"  Disk: {fleet['used_disk_gb']}GB / {fleet['total_disk_gb']}GB ({fleet['disk_pct']}%)")
    fmt.line(f"  Load: {fleet['avg_load_ratio']:.2f}x avg across {fleet['total_cores']} cores")
    fmt.line(f"  Hosts scanned: {len(snapshot['hosts'])}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_show(cfg: FreqConfig, args) -> int:
    """Show fleet capacity trends."""
    fmt.header("Fleet Capacity Trends")
    fmt.blank()

    data = _load_trend_data(cfg)
    if not data:
        fmt.line(f"  {fmt.C.YELLOW}No trend data yet. Take a snapshot first:{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}  freq trend snapshot{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Show summary
    first = data[0]
    last = data[-1]
    first_ts = first.get("timestamp", "?")[:10]
    last_ts = last.get("timestamp", "?")[:10]
    span_days = max(1, (last.get("epoch", 0) - first.get("epoch", 0)) / 86400)

    fmt.line(f"  Data points: {len(data)}")
    fmt.line(f"  Period:      {first_ts} → {last_ts} ({span_days:.0f} days)")
    fmt.blank()

    # Extract fleet-level time series
    ram_pcts = [s["fleet"]["ram_pct"] for s in data if "fleet" in s]
    disk_pcts = [s["fleet"]["disk_pct"] for s in data if "fleet" in s]
    load_ratios = [s["fleet"]["avg_load_ratio"] for s in data if "fleet" in s]

    # RAM trend
    fmt.divider("RAM Usage")
    fmt.blank()
    if ram_pcts:
        spark = _render_sparkline(ram_pcts, 30)
        delta = ram_pcts[-1] - ram_pcts[0]
        direction = (
            f"{fmt.C.RED}↑ +{delta:.1f}%{fmt.C.RESET}"
            if delta > 1
            else (f"{fmt.C.GREEN}↓ {delta:.1f}%{fmt.C.RESET}" if delta < -1 else f"{fmt.C.GREEN}→ stable{fmt.C.RESET}")
        )
        fmt.line(f"  {spark}  {ram_pcts[-1]:.1f}%  {direction}")
        fmt.line(
            f"  {fmt.C.DIM}Min: {min(ram_pcts):.1f}%  Max: {max(ram_pcts):.1f}%  "
            f"Avg: {sum(ram_pcts) / len(ram_pcts):.1f}%{fmt.C.RESET}"
        )
    fmt.blank()

    # Disk trend
    fmt.divider("Disk Usage")
    fmt.blank()
    if disk_pcts:
        spark = _render_sparkline(disk_pcts, 30)
        delta = disk_pcts[-1] - disk_pcts[0]
        direction = (
            f"{fmt.C.RED}↑ +{delta:.1f}%{fmt.C.RESET}"
            if delta > 1
            else (f"{fmt.C.GREEN}↓ {delta:.1f}%{fmt.C.RESET}" if delta < -1 else f"{fmt.C.GREEN}→ stable{fmt.C.RESET}")
        )
        fmt.line(f"  {spark}  {disk_pcts[-1]:.1f}%  {direction}")
        fmt.line(
            f"  {fmt.C.DIM}Min: {min(disk_pcts):.1f}%  Max: {max(disk_pcts):.1f}%  "
            f"Avg: {sum(disk_pcts) / len(disk_pcts):.1f}%{fmt.C.RESET}"
        )

        # Projection: if disk is growing, when does it hit 90%?
        if delta > 0 and disk_pcts[-1] < 90 and span_days > 0:
            rate_per_day = delta / span_days
            remaining = 90 - disk_pcts[-1]
            days_to_90 = remaining / rate_per_day if rate_per_day > 0 else 999
            if days_to_90 < 365:
                fmt.line(
                    f"  {fmt.C.YELLOW}{fmt.S.WARN} At current rate, "
                    f"disk hits 90% in ~{days_to_90:.0f} days{fmt.C.RESET}"
                )
    fmt.blank()

    # Load trend
    fmt.divider("CPU Load")
    fmt.blank()
    if load_ratios:
        spark = _render_sparkline(load_ratios, 30)
        fmt.line(f"  {spark}  {load_ratios[-1]:.2f}x")
        fmt.line(
            f"  {fmt.C.DIM}Min: {min(load_ratios):.2f}x  Max: {max(load_ratios):.2f}x  "
            f"Avg: {sum(load_ratios) / len(load_ratios):.2f}x{fmt.C.RESET}"
        )
    fmt.blank()

    # Per-host current state
    latest = data[-1]
    if latest.get("hosts"):
        fmt.divider("Per-Host (Latest)")
        fmt.blank()
        fmt.table_header(("HOST", 14), ("RAM %", 8), ("DISK %", 8), ("LOAD", 8))
        for label, h in sorted(latest["hosts"].items()):
            ram_pct = round(h.get("ram_used", 0) / max(h.get("ram_total", 1), 1) * 100, 1)
            disk_pct = round(h.get("disk_used", 0) / max(h.get("disk_total", 1), 1) * 100, 1)
            load_r = h.get("load", 0) / max(h.get("cores", 1), 1)
            fmt.table_row(
                (f"{fmt.C.BOLD}{label}{fmt.C.RESET}", 14),
                (f"{ram_pct:.0f}%", 8),
                (f"{disk_pct:.0f}%", 8),
                (f"{load_r:.2f}x", 8),
            )
        fmt.blank()

    fmt.line(f"  {fmt.C.DIM}Add snapshots: freq trend snapshot (cron for auto){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_history(cfg: FreqConfig, args) -> int:
    """Show raw trend snapshot history."""
    fmt.header("Trend History")
    fmt.blank()

    data = _load_trend_data(cfg)
    if not data:
        fmt.line(f"  {fmt.C.DIM}No trend data.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    lines = getattr(args, "lines", 20) or 20
    recent = data[-lines:]

    fmt.table_header(
        ("TIME", 20),
        ("HOSTS", 6),
        ("RAM %", 8),
        ("DISK %", 8),
        ("LOAD", 8),
    )

    for snap in recent:
        ts = snap.get("timestamp", "")[:19]
        fleet = snap.get("fleet", {})
        host_count = len(snap.get("hosts", {}))
        fmt.table_row(
            (ts, 20),
            (str(host_count), 6),
            (f"{fleet.get('ram_pct', 0):.1f}%", 8),
            (f"{fleet.get('disk_pct', 0):.1f}%", 8),
            (f"{fleet.get('avg_load_ratio', 0):.2f}x", 8),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(data)} total snapshots ({len(recent)} shown){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
