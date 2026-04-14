"""Fleet operations for FREQ.

Domain: freq fleet <status|exec|info|diagnose|docker|keys|dashboard|test-connection>

The core of fleet management. Every command talks to real hosts via SSH.
Status pings the entire fleet. Exec runs arbitrary commands fleet-wide.
Info shows detailed host specs. Diagnose runs health checks on a single host.

Replaces: Ansible ad-hoc commands ($0 but slow), ClusterSSH (no structure),
          manual SSH loops in bash

Architecture:
    - Parallel SSH via ssh_run_many for fleet-wide operations
    - Single-host SSH via ssh_run for targeted commands
    - Host resolution via freq/core/resolve.py (label, IP, or group)
    - Output formatting via freq/core/fmt.py (tables, status indicators)

Design decisions:
    - Status checks use a non-privileged command (uptime) so it works even
      if sudo is broken on a host. Diagnose uses sudo for deeper checks.
"""

import os
import socket
import subprocess
import time

from freq.core import fmt
from freq.core import resolve
from freq.core.config import FreqConfig
from freq.core.health_state import (
    STATE_LIVE,
    STATE_STALE,
    STATE_DEGRADED,
    STATE_AUTH_FAILED,
    STATE_UNREACHABLE,
    aggregate_probe_state,
    classify_probe_failure,
)
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many, result_for

# ─────────────────────────────────────────────────────────────
# CONSTANTS — Timeouts for fleet SSH operations
# ─────────────────────────────────────────────────────────────

FLEET_QUICK_TIMEOUT = 10
FLEET_CMD_TIMEOUT = 15
FLEET_SLOW_TIMEOUT = 30
FLEET_EXEC_TIMEOUT = 600


# ─────────────────────────────────────────────────────────────
# FLEET STATUS — Health check and dashboard overview
# ─────────────────────────────────────────────────────────────


def _load_dashboard_health_cache(cfg: FreqConfig) -> dict:
    """Read the dashboard's cached health data for legacy devices.

    The dashboard runs as the service account and has SSH key access
    to iDRAC/switch that operator CLI doesn't. Its background probe
    writes results to data/cache/health.json. Operators can read this
    (cache files are chmod 644) and merge it with their own SSH results.

    Returns dict keyed by IP → {status, cores, ram, disk, load, uptime, ...}
    or empty dict if cache is missing/stale (>120s old).
    """
    import json as _json
    try:
        cache_path = os.path.join(cfg.data_dir, "cache", "health.json")
        if not os.path.isfile(cache_path):
            return {}
        with open(cache_path) as f:
            entry = _json.load(f)
        ts = entry.get("ts", 0)
        if time.time() - ts > 120:
            return {}  # Too stale — prefer direct SSH
        data = entry.get("data", {})
        hosts_list = data.get("hosts", [])
        return {h.get("ip"): h for h in hosts_list if h.get("ip")}
    except (OSError, _json.JSONDecodeError, Exception):
        return {}


def cmd_status(cfg: FreqConfig, pack, args) -> int:
    """Fleet health summary — ping every host and report status."""
    json_mode = getattr(args, "json_output", False)

    hosts = cfg.hosts
    if not hosts:
        if json_mode:
            import json as _json
            print(_json.dumps({"hosts": [], "total": 0, "online": 0, "offline": 0}))
            return 0
        fmt.header("Fleet Status")
        fmt.blank()
        fmt.line(f"{fmt.C.YELLOW}No hosts registered. Run: freq host add{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    if not json_mode:
        fmt.header("Fleet Status")
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Checking {len(hosts)} hosts...{fmt.C.RESET}")
        fmt.blank()

    # Device-appropriate verify commands. Legacy devices (iDRAC, switch)
    # don't have 'uptime' — racadm and IOS shells have their own syntax.
    # Running a generic SSH command produces false DOWN for successfully
    # deployed devices.
    VERIFY_CMDS = {
        "linux": "uptime -p 2>/dev/null || uptime",
        "pve": "uptime -p 2>/dev/null || uptime",
        "docker": "uptime -p 2>/dev/null || uptime",
        "truenas": "uptime -p 2>/dev/null || uptime",
        "pfsense": "uptime",
        "idrac": "racadm getsysinfo -s",
        "switch": "show version | include uptime",
    }

    # Parallel ping all hosts — split by htype so each class gets its own verify command.
    start = time.monotonic()
    results = {}
    from collections import defaultdict
    by_cmd = defaultdict(list)
    for h in hosts:
        cmd = VERIFY_CMDS.get(h.htype, "uptime -p 2>/dev/null || uptime")
        by_cmd[cmd].append(h)
    for cmd, cmd_hosts in by_cmd.items():
        # Legacy devices use RSA key, not ed25519
        is_legacy = cmd_hosts and cmd_hosts[0].htype in ("idrac", "switch")
        key = (cfg.ssh_rsa_key_path or cfg.ssh_key_path) if is_legacy else cfg.ssh_key_path
        ct = 10 if is_legacy else cfg.ssh_connect_timeout
        cmd_timeout = 15 if is_legacy else FLEET_QUICK_TIMEOUT
        batch = ssh_run_many(
            hosts=cmd_hosts,
            command=cmd,
            key_path=key,
            connect_timeout=ct,
            command_timeout=cmd_timeout,
            max_parallel=cfg.ssh_max_parallel,
            use_sudo=False,
            cfg=cfg,
        )
        results.update(batch)
    total_duration = time.monotonic() - start

    # R-PRODUCT-LAW-BACKEND-TRUTH: parity with /api/health — every
    # failure is classified through the shared six-state classifier so
    # the CLI surface is not vaguer than the web surface. Sonny's rule:
    # no surface gets to be vaguer than the others.
    #
    # Classify every result first so both JSON and table render off the
    # same structured dict (one source of truth inside the command).
    dashboard_health = _load_dashboard_health_cache(cfg)
    now_wall = time.time()
    classified = []
    for h in hosts:
        r = result_for(results, h)
        rc = r.returncode if r else 1
        stderr = (r.stderr or "") if r else "no response"
        stdout = (r.stdout or "") if r else ""
        duration = round(r.duration, 2) if r else None
        if r and rc == 0:
            classified.append({
                "label": h.label, "ip": h.ip, "type": h.htype,
                "state": STATE_LIVE, "reason": "probe OK",
                "uptime": stdout.strip(),
                "probed_at": now_wall,
                "duration": duration,
                # Legacy compat for the JSON mode's prior shape.
                "status": "online",
            })
            continue

        state, reason = classify_probe_failure(rc, stderr, stdout)

        # Legacy-device auth failures against the operator's own key
        # are not a real DOWN — the dashboard holds the service
        # account's cached verdict via the RSA key. If the dashboard
        # says healthy, we trust it and flip to live-via-cache; else
        # surface the honest reason.
        is_legacy = h.htype in ("idrac", "switch")
        operator_auth_issue = (
            is_legacy and state == STATE_AUTH_FAILED
        )
        cached = dashboard_health.get(h.ip) if operator_auth_issue else None
        cached_live = cached and cached.get("state") in (STATE_LIVE, "live") or (
            cached and cached.get("status") == "healthy"
        )
        if cached_live:
            detail = cached.get("load", "") or cached.get("ram", "") or "healthy"
            classified.append({
                "label": h.label, "ip": h.ip, "type": h.htype,
                "state": STATE_LIVE,
                "reason": f"via dashboard cache: {detail}",
                "uptime": f"via dashboard: {detail}",
                "probed_at": now_wall,
                "duration": duration,
                "status": "online",
            })
            continue

        classified.append({
            "label": h.label, "ip": h.ip, "type": h.htype,
            "state": state, "reason": reason,
            "uptime": "",
            "probed_at": now_wall,
            "duration": duration,
            "status": "offline",
            "operator_auth_issue": operator_auth_issue,
        })

    # JSON output mode
    if json_mode:
        import json as _json

        probe_state, probe_reason = aggregate_probe_state(classified)
        fleet_data = []
        for c in classified:
            entry = {
                "label": c["label"], "ip": c["ip"], "type": c["type"],
                "state": c["state"], "reason": c["reason"],
                "probed_at": c["probed_at"],
                "duration": c["duration"],
                # Legacy aliases preserved for existing machine readers.
                "status": c["status"],
            }
            if c["status"] == "online":
                entry["uptime"] = c.get("uptime", "")
            else:
                entry["error"] = c["reason"]
            fleet_data.append(entry)
        online_n = sum(1 for c in classified if c["state"] == STATE_LIVE)
        offline_n = len(classified) - online_n
        print(_json.dumps({
            "hosts": fleet_data,
            "total": len(hosts),
            "online": online_n,
            "offline": offline_n,
            "probe_state": probe_state,
            "probe_reason": probe_reason,
            "duration": round(total_duration, 2),
        }, indent=2))
        return 0

    # Display results — DETAIL column now carries state+reason on
    # failure instead of a raw stderr snippet, so an operator reading
    # the terminal output sees WHY each host is in each state.
    fmt.table_header(
        ("HOST", 16),
        ("STATUS", 10),
        ("DETAIL", 38),
        ("TIME", 6),
    )

    up = 0
    down = 0
    na = 0
    degraded = 0
    auth_failed = 0
    for c in classified:
        duration_s = f"{c['duration']:.1f}s" if c.get("duration") is not None else "—"
        label_cell = (f"{fmt.C.BOLD}{c['label']}{fmt.C.RESET}", 16)
        state = c["state"]
        reason = c["reason"]

        if state == STATE_LIVE:
            up += 1
            uptime = c.get("uptime", "").replace("up ", "")
            if len(uptime) > 38:
                uptime = uptime[:35] + "..."
            if uptime.startswith("via dashboard"):
                detail_cell = (f"{fmt.C.DIM}{uptime}{fmt.C.RESET}", 38)
            else:
                detail_cell = (uptime, 38)
            fmt.table_row(label_cell, (fmt.badge("up"), 10), detail_cell, (duration_s, 6))
        elif state == STATE_AUTH_FAILED:
            if c.get("operator_auth_issue"):
                na += 1
                fmt.table_row(
                    label_cell,
                    (f"{fmt.C.DIM}n/a{fmt.C.RESET}", 10),
                    (f"{fmt.C.DIM}needs svc account (legacy device){fmt.C.RESET}", 38),
                    (duration_s, 6),
                )
            else:
                auth_failed += 1
                down += 1
                detail = f"auth_failed: {reason[9:]}" if reason.startswith("ssh auth ") else f"auth_failed: {reason}"
                if len(detail) > 38:
                    detail = detail[:35] + "..."
                fmt.table_row(
                    label_cell,
                    (fmt.badge("down"), 10),
                    (f"{fmt.C.RED}{detail}{fmt.C.RESET}", 38),
                    (duration_s, 6),
                )
        elif state == STATE_DEGRADED:
            degraded += 1
            detail = f"degraded: {reason}"
            if len(detail) > 38:
                detail = detail[:35] + "..."
            fmt.table_row(
                label_cell,
                (f"{fmt.C.YELLOW}degraded{fmt.C.RESET}", 10),
                (f"{fmt.C.YELLOW}{detail}{fmt.C.RESET}", 38),
                (duration_s, 6),
            )
        else:
            down += 1
            detail = f"{state}: {reason}"
            if len(detail) > 38:
                detail = detail[:35] + "..."
            fmt.table_row(
                label_cell,
                (fmt.badge("down"), 10),
                (f"{fmt.C.RED}{detail}{fmt.C.RESET}", 38),
                (duration_s, 6),
            )

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    probe_state, probe_reason = aggregate_probe_state(classified)
    summary = (
        f"  {fmt.C.GREEN}{up}{fmt.C.RESET} up  "
        f"{fmt.C.RED}{down}{fmt.C.RESET} down  "
    )
    if auth_failed:
        summary += f"{fmt.C.RED}{auth_failed}{fmt.C.RESET} auth_failed  "
    if degraded:
        summary += f"{fmt.C.YELLOW}{degraded}{fmt.C.RESET} degraded  "
    if na:
        summary += f"{fmt.C.DIM}{na}{fmt.C.RESET} n/a  "
    summary += f"({len(hosts)} total, {total_duration:.1f}s)"
    fmt.line(summary)
    # Top-level probe_state + reason parity with /api/health.
    fmt.line(
        f"  {fmt.C.DIM}fleet state:{fmt.C.RESET} "
        f"{fmt.C.BOLD}{probe_state}{fmt.C.RESET} "
        f"{fmt.C.DIM}— {probe_reason}{fmt.C.RESET}"
    )
    fmt.blank()
    fmt.footer()

    return 0 if down == 0 else 1


# ─────────────────────────────────────────────────────────────
# FLEET EXEC — Run commands across multiple hosts in parallel
# ─────────────────────────────────────────────────────────────


def cmd_exec(cfg: FreqConfig, pack, args) -> int:
    """Run a command across fleet hosts."""
    target = getattr(args, "target", None)
    cmd_parts = getattr(args, "cmd", [])

    if not cmd_parts:
        fmt.error("Usage: freq fleet exec <target> <command>")
        fmt.info("  target: host label, group name, or 'all'")
        fmt.info("  Example: freq fleet exec all uptime")
        fmt.info("  Example: freq fleet exec distro 'cat /etc/os-release | head -1'")
        return 1

    command = " ".join(cmd_parts)

    # Safety gate: dangerous commands on "all" require YES confirmation
    DANGEROUS_PATTERNS = [
        "rm ",
        "dd ",
        "mkfs",
        "reboot",
        "shutdown",
        "halt",
        "systemctl stop",
        "wipefs",
        "fdisk",
        "parted",
    ]
    if target and target.lower() == "all":
        cmd_lower = command.lower()
        for pattern in DANGEROUS_PATTERNS:
            if pattern in cmd_lower:
                fmt.warn("Dangerous command detected: {}".format(command[:60]))
                fmt.line("  Target: ALL hosts")
                try:
                    confirm = input("  {}Type YES to confirm:{} ".format(fmt.C.RED, fmt.C.RESET)).strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return 1
                if confirm != "YES":
                    fmt.info("Cancelled.")
                    return 0
                break

    # Resolve targets
    hosts = _resolve_targets(cfg, target)
    if not hosts:
        fmt.error("No hosts matched: {}".format(target))
        _host_groups = [g for h in cfg.hosts for g in h.groups.split(",") if g]
        available = sorted(set(_host_groups)) if _host_groups else []
        if available:
            fmt.info("Available groups: {}".format(", ".join(available)))
        fmt.info("Try: freq host list")
        return 1

    fmt.header("Fleet Exec")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Running on {len(hosts)} host(s):{fmt.C.RESET} {fmt.C.CYAN}{command}{fmt.C.RESET}")
    fmt.blank()

    # Execute in parallel (no sudo by default — user can prefix sudo in their command)
    start = time.monotonic()
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_SLOW_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )
    total_duration = time.monotonic() - start

    # Color rotation for host prefixes
    host_colors = [
        fmt.C.CYAN,
        fmt.C.GREEN,
        fmt.C.YELLOW,
        fmt.C.MAGENTA,
        fmt.C.BLUE,
        fmt.C.ORANGE,
        fmt.C.PURPLE,
        fmt.C.WHITE,
        fmt.C.RED,
    ]

    # Display results with colored host prefixes
    ok_count = 0
    fail_count = 0
    for i, h in enumerate(hosts):
        r = result_for(results, h)
        color = host_colors[i % len(host_colors)]
        prefix = f"{color}{h.label:>14}{fmt.C.RESET}"

        if r and r.returncode == 0:
            ok_count += 1
            if r.stdout:
                for line in r.stdout.split("\n"):
                    print(f"  {prefix} {fmt.C.DIM}{fmt.S.DOT}{fmt.C.RESET} {line}")
            else:
                print(f"  {prefix} {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} (no output)")
        else:
            fail_count += 1
            err = r.stderr.split("\n")[0][:50] if r and r.stderr else "no response"
            print(f"  {prefix} {fmt.C.RED}{fmt.S.CROSS} {err}{fmt.C.RESET}")

    print()
    fmt.line(
        f"  {fmt.C.GREEN}{ok_count}{fmt.C.RESET} ok  "
        f"{fmt.C.RED}{fail_count}{fmt.C.RESET} failed  "
        f"({len(hosts)} hosts, {total_duration:.1f}s)"
    )
    print()

    return 0 if fail_count == 0 else 1


# ─────────────────────────────────────────────────────────────
# HOST INFO & DETAIL — Single-host system inventory and diagnostics
# ─────────────────────────────────────────────────────────────


def cmd_info(cfg: FreqConfig, pack, args) -> int:
    """System info for a single host."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq fleet info <host>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    fmt.header(f"Host Info: {host.label}")
    fmt.blank()

    # Gather system info in parallel (multiple commands, one host)
    commands = {
        "hostname": "hostname -f 2>/dev/null || hostname",
        "os": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
        "kernel": "uname -r",
        "uptime": "uptime -p 2>/dev/null || uptime",
        "cpu": "nproc",
        "ram_total": "free -m | awk '/Mem:/ {print $2}'",
        "ram_used": "free -m | awk '/Mem:/ {print $3}'",
        "disk": 'df -h / | awk \'NR==2 {print $3"/"$2" ("$5" used)"}\'',
        "ip_addrs": "ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $2}' | tr '\\n' ' '",
        "load": "cat /proc/loadavg | awk '{print $1, $2, $3}'",
        "docker": "docker ps --format '{{.Names}}' 2>/dev/null | wc -l",
    }

    info = {}
    for key, cmd in commands.items():
        r = ssh_run(
            host=host.ip,
            command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            htype=host.htype,
            use_sudo=False,
            cfg=cfg,
        )
        info[key] = r.stdout if r.returncode == 0 else "—"

    # Display
    _info_field("Label", f"{fmt.C.BOLD}{host.label}{fmt.C.RESET}")
    _info_field("IP", host.ip)
    _info_field("Type", host.htype)
    _info_field("Groups", host.groups or "—")
    fmt.blank()
    _info_field("Hostname", info["hostname"])
    _info_field("OS", info["os"])
    _info_field("Kernel", info["kernel"])
    _info_field("Uptime", info["uptime"].replace("up ", ""))
    fmt.blank()
    _info_field("CPU Cores", info["cpu"])
    ram_pct = ""
    try:
        used = int(info["ram_used"])
        total = int(info["ram_total"])
        ram_pct = f" ({used * 100 // total}%)" if total > 0 else ""
    except (ValueError, ZeroDivisionError):
        pass
    _info_field("RAM", f"{info['ram_used']}MB / {info['ram_total']}MB{ram_pct}")
    _info_field("Disk (/)", info["disk"])
    _info_field("Load Avg", info["load"])
    _info_field("IPs", info["ip_addrs"])

    docker_count = info.get("docker", "0").strip()
    if docker_count and docker_count != "0" and docker_count != "—":
        fmt.blank()
        _info_field("Docker", f"{docker_count} containers running")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_detail(cfg: FreqConfig, pack, args) -> int:
    """Deep host detail — full system inventory (mirrors /api/host/detail)."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq fleet detail <host>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    fmt.header(f"Host Detail: {host.label}")
    fmt.blank()

    def _cmd(command, timeout=10):
        r = ssh_run(
            host=host.ip,
            command=command,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            htype=host.htype,
            use_sudo=False,
            cfg=cfg,
        )
        return r.stdout.strip() if r.returncode == 0 else "—"

    # Identity
    _info_field("Label", f"{fmt.C.BOLD}{host.label}{fmt.C.RESET}")
    _info_field("IP", host.ip)
    _info_field("Type", host.htype)
    _info_field("Groups", host.groups or "—")
    fmt.blank()

    # System
    _info_field("Hostname", _cmd("hostname -f 2>/dev/null || hostname"))
    _info_field("OS", _cmd("cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'"))
    _info_field("Kernel", _cmd("uname -r"))
    _info_field("Uptime", _cmd("uptime -p 2>/dev/null || uptime").replace("up ", ""))
    fmt.blank()

    # Hardware
    _info_field("CPU Model", _cmd("grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs"))
    _info_field("Cores", _cmd("nproc"))
    _info_field("RAM", _cmd("free -m | awk '/Mem:/ {printf \"%d/%dMB (%d%%)\", $3, $2, $3/$2*100}'"))
    _info_field("Load Avg", _cmd("cat /proc/loadavg | awk '{print $1, $2, $3}'"))
    _info_field("Disk (/)", _cmd('df -h / | awk \'NR==2 {print $3"/"$2" ("$5" used)"}\''))
    fmt.blank()

    # Network
    _info_field("IPs", _cmd("ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $NF\": \"$2}'"))
    _info_field("Gateway", _cmd("ip route show default 2>/dev/null | awk '{print $3}' | head -1"))
    _info_field("DNS", _cmd("grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | tr '\\n' ' '"))
    _info_field(
        "Listening",
        _cmd("ss -tlnp 2>/dev/null | grep LISTEN | awk '{print $4}' | sed 's/.*://' | sort -un | tr '\\n' ' '"),
    )
    fmt.blank()

    # Security
    _info_field("SSH Root", _cmd("grep -i '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'"))
    _info_field(
        "SSH PwAuth", _cmd("grep -i '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'")
    )
    _info_field("Last Login", _cmd("last -1 --time-format iso 2>/dev/null | head -1"))
    fmt.blank()

    # Services
    _info_field("NTP Synced", _cmd("timedatectl show --property=NTPSynchronized --value 2>/dev/null"))
    _info_field("NTP Service", _cmd("systemctl is-active systemd-timesyncd 2>/dev/null"))
    _info_field(
        "Running Svcs", _cmd("systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l")
    )
    _info_field("Failed Svcs", _cmd("systemctl --failed --no-legend 2>/dev/null | head -5 || echo none"))
    _info_field(
        "Pkg Manager",
        _cmd(
            "if command -v apt >/dev/null 2>&1; then echo APT; "
            "elif command -v dnf >/dev/null 2>&1; then echo DNF; "
            "elif command -v zypper >/dev/null 2>&1; then echo ZYPPER; "
            "else echo UNKNOWN; fi"
        ),
    )
    _info_field(
        "Updates",
        _cmd(
            "if command -v apt >/dev/null 2>&1; then "
            "  apt list --upgradable 2>/dev/null | grep -c upgradable; "
            "elif command -v dnf >/dev/null 2>&1; then "
            "  dnf check-update 2>/dev/null | grep -c '^[a-zA-Z]'; "
            "else echo 0; fi"
        ),
    )
    fmt.blank()

    # Docker
    dc_count = _cmd("docker ps -q 2>/dev/null | wc -l")
    if dc_count and dc_count not in ("0", "—"):
        _info_field("Docker", f"{dc_count} containers")
        containers = _cmd("docker ps --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>/dev/null")
        if containers and containers != "—":
            for line in containers.split("\n"):
                parts = line.split("|")
                if len(parts) >= 3:
                    fmt.line(f"    {fmt.C.CYAN}{parts[0]:<20}{fmt.C.RESET} {parts[1]:<25} {parts[2]}")
        fmt.blank()

    fmt.footer()
    return 0


def cmd_boundaries(cfg: FreqConfig, pack, args) -> int:
    """Fleet boundaries — show permission tiers and VM categories."""
    action = getattr(args, "action", None) or "show"
    fb = cfg.fleet_boundaries

    if action == "show":
        fmt.header("Fleet Boundaries")
        fmt.blank()

        # Tiers
        fmt.line(f"{fmt.C.BOLD}Permission Tiers{fmt.C.RESET}")
        fmt.blank()
        for tier_name, actions in fb.tiers.items():
            fmt.line(f"  {fmt.C.CYAN}{tier_name:<12}{fmt.C.RESET} {', '.join(actions)}")
        fmt.blank()

        # Categories
        fmt.line(f"{fmt.C.BOLD}VM Categories{fmt.C.RESET}")
        fmt.blank()
        fmt.table_header(("CATEGORY", 20), ("TIER", 10), ("VMIDS", 15), ("RANGE", 15))
        for cat_name, cat in fb.categories.items():
            vmids = cat.get("vmids", [])
            vmid_str = ", ".join(str(v) for v in vmids[:5])
            if len(vmids) > 5:
                vmid_str += f" (+{len(vmids) - 5})"
            rs = cat.get("range_start")
            re = cat.get("range_end")
            range_str = f"{rs}-{re}" if rs is not None and re is not None else "—"
            fmt.table_row(
                (cat_name, 20),
                (cat.get("tier", "probe"), 10),
                (vmid_str or "—", 15),
                (range_str, 15),
            )
        fmt.blank()

        # Physical devices
        if fb.physical:
            fmt.line(f"{fmt.C.BOLD}Physical Devices{fmt.C.RESET}")
            fmt.blank()
            for key, dev in fb.physical.items():
                fmt.line(
                    f"  {fmt.C.CYAN}{dev.label:<16}{fmt.C.RESET} {dev.ip:<16} {dev.device_type:<10} tier={dev.tier}"
                )
            fmt.blank()

        # PVE nodes
        if fb.pve_nodes:
            fmt.line(f"{fmt.C.BOLD}PVE Nodes{fmt.C.RESET}")
            fmt.blank()
            for name, node in fb.pve_nodes.items():
                fmt.line(f"  {fmt.C.CYAN}{name:<12}{fmt.C.RESET} {node.ip}")
            fmt.blank()

        fmt.footer()
        return 0

    elif action == "lookup":
        # Look up a specific VMID
        target = getattr(args, "target", None)
        if not target:
            fmt.error("Usage: freq boundaries lookup <vmid>")
            return 1
        try:
            vmid = int(target)
        except ValueError:
            fmt.error(f"Invalid VMID: {target}")
            return 1
        cat_name, tier = fb.categorize(vmid)
        actions = fb.allowed_actions(vmid)
        is_prod = fb.is_prod(vmid)
        desc = fb.category_description(vmid)

        fmt.header(f"Boundaries: VM {vmid}")
        fmt.blank()
        _info_field("Category", cat_name)
        _info_field("Description", desc)
        _info_field("Tier", tier)
        _info_field("Production", "YES" if is_prod else "no")
        _info_field("Allowed", ", ".join(actions))
        fmt.blank()
        fmt.footer()
        return 0

    else:
        fmt.error(f"Unknown action: {action}. Use: show, lookup")
        return 1


def cmd_dashboard(cfg: FreqConfig, pack, args) -> int:
    """Fleet dashboard — overview of all hosts with key metrics."""
    fmt.header(pack.dashboard_header if hasattr(pack, "dashboard_header") else "Fleet Dashboard")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"{fmt.C.YELLOW}No hosts registered.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.line(f"{fmt.C.BOLD}Scanning {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    # Gather key metrics from all hosts in parallel
    command = (
        'echo "$(hostname)|'
        "$(cat /etc/os-release 2>/dev/null | grep -oP '(?<=PRETTY_NAME=\\\").*(?=\\\")' || echo unknown)|"
        "$(nproc)|"
        "$(free -m | awk '/Mem:/ {printf \\\"%d/%dMB\\\", $3, $2}')|"
        "$(df -h / | awk 'NR==2 {print $5}')|"
        "$(uptime -p 2>/dev/null | sed 's/up //' || echo unknown)|"
        '$(docker ps -q 2>/dev/null | wc -l)"'
    )

    start = time.monotonic()
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )
    total_duration = time.monotonic() - start

    # Table header
    fmt.table_header(
        ("HOST", 14),
        ("STATUS", 8),
        ("OS", 16),
        ("CPU", 4),
        ("RAM", 14),
        ("DISK", 6),
    )

    up = 0
    down = 0
    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode == 0 and r.stdout:
            up += 1
            parts = r.stdout.split("|")
            os_name = parts[1][:16] if len(parts) > 1 else "?"
            cpus = parts[2] if len(parts) > 2 else "?"
            ram = parts[3] if len(parts) > 3 else "?"
            disk = parts[4] if len(parts) > 4 else "?"

            # Color disk usage
            try:
                disk_pct = int(disk.replace("%", ""))
                if disk_pct >= 90:
                    disk_colored = f"{fmt.C.RED}{disk}{fmt.C.RESET}"
                elif disk_pct >= 75:
                    disk_colored = f"{fmt.C.YELLOW}{disk}{fmt.C.RESET}"
                else:
                    disk_colored = f"{fmt.C.GREEN}{disk}{fmt.C.RESET}"
            except ValueError:
                disk_colored = disk

            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                (fmt.badge("up"), 8),
                (os_name, 16),
                (cpus, 4),
                (ram, 14),
                (disk_colored, 6),
            )
        else:
            down += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                (fmt.badge("down"), 8),
                ("—", 16),
                ("—", 4),
                ("—", 14),
                ("—", 6),
            )

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{up}{fmt.C.RESET} up  "
        f"{fmt.C.RED}{down}{fmt.C.RESET} down  "
        f"({len(hosts)} total, {total_duration:.1f}s)"
    )
    fmt.blank()
    fmt.footer()

    return 0 if down == 0 else 1


# ─────────────────────────────────────────────────────────────
# DOCKER OPERATIONS — Container discovery and fleet-wide Docker management
# ─────────────────────────────────────────────────────────────


def cmd_docker(cfg: FreqConfig, pack, args) -> int:
    """Docker container discovery on a host."""
    target = getattr(args, "target", None)

    # If no target, find all docker-type hosts
    if not target:
        docker_hosts = resolve.by_type(cfg.hosts, "docker")
        if not docker_hosts:
            fmt.error("No docker hosts registered. Specify a host: freq docker <host>")
            return 1
        # Use first docker host
        host = docker_hosts[0]
    else:
        host = resolve.by_target(cfg.hosts, target)
        if not host:
            fmt.error(f"Host not found: {target}")
            return 1

    fmt.header(f"Docker: {host.label}")
    fmt.blank()

    # Get container list
    r = ssh_run(
        host=host.ip,
        command="docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
        cfg=cfg,
    )

    if r.returncode != 0:
        fmt.line(f"{fmt.C.RED}Docker not available or no permission.{fmt.C.RESET}")
        if r.stderr:
            fmt.line(f"{fmt.C.DIM}{r.stderr}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    if not r.stdout.strip():
        fmt.line(f"{fmt.C.YELLOW}No running containers.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    lines = r.stdout.strip().split("\n")
    fmt.line(f"{fmt.C.BOLD}{len(lines)} containers running{fmt.C.RESET}")
    fmt.blank()

    fmt.table_header(
        ("NAME", 20),
        ("IMAGE", 30),
        ("STATUS", 18),
    )

    for line in lines:
        parts = line.split("|")
        name = parts[0] if len(parts) > 0 else "?"
        image = parts[1] if len(parts) > 1 else "?"
        status = parts[2] if len(parts) > 2 else "?"

        # Truncate long image names
        if len(image) > 30:
            image = "..." + image[-27:]

        # Color status
        if "Up" in status:
            status_colored = f"{fmt.C.GREEN}{status}{fmt.C.RESET}"
        else:
            status_colored = f"{fmt.C.RED}{status}{fmt.C.RESET}"

        fmt.table_row(
            (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 20),
            (f"{fmt.C.DIM}{image}{fmt.C.RESET}", 30),
            (status_colored, 18),
        )

    fmt.blank()
    fmt.footer()
    return 0


def cmd_docker_fleet(cfg: FreqConfig, pack, args) -> int:
    """Fleet-wide Docker operations — ps/logs/stats across all docker hosts."""
    action = getattr(args, "docker_action", "ps")

    # Find all docker hosts
    docker_hosts = resolve.by_type(cfg.hosts, "docker")
    if not docker_hosts:
        fmt.error("No docker-type hosts registered in hosts.toml")
        return 1

    fmt.header(f"Docker Fleet: {action}")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Hosts:{fmt.C.RESET} {len(docker_hosts)} docker host(s)")
    fmt.blank()

    if action == "ps":
        cmd = "docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}' 2>/dev/null"
    elif action == "logs":
        service = getattr(args, "service", "") or ""
        lines = getattr(args, "lines", 20) or 20
        if service:
            cmd = f"docker logs --tail {lines} {service} 2>&1"
        else:
            cmd = f"docker ps --format '{{{{.Names}}}}' 2>/dev/null | head -5 | while read c; do echo \"=== $c ===\"; docker logs --tail 3 $c 2>&1; done"
    elif action == "stats":
        cmd = "docker stats --no-stream --format '{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}' 2>/dev/null"
    else:
        fmt.error(f"Unknown action: {action}")
        return 1

    results = ssh_run_many(
        hosts=docker_hosts,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=30,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    total_containers = 0

    for host in docker_hosts:
        r = result_for(results, host)
        if not r or r.returncode != 0:
            fmt.line(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {host.label}: unreachable")
            continue

        if not r.stdout.strip():
            fmt.line(f"  {fmt.C.DIM}{host.label}: no containers{fmt.C.RESET}")
            continue

        lines_out = r.stdout.strip().split("\n")

        if action == "ps":
            fmt.line(f"  {fmt.C.BOLD}{host.label}{fmt.C.RESET} ({len(lines_out)} containers)")
            for line in lines_out:
                parts = line.split("|")
                name = parts[0] if len(parts) > 0 else "?"
                image = parts[1] if len(parts) > 1 else ""
                status = parts[2] if len(parts) > 2 else ""
                if len(image) > 25:
                    image = "..." + image[-22:]
                status_c = (
                    f"{fmt.C.GREEN}{status}{fmt.C.RESET}" if "Up" in status else f"{fmt.C.RED}{status}{fmt.C.RESET}"
                )
                fmt.line(f"    {name:<20} {image:<25} {status_c}")
            total_containers += len(lines_out)

        elif action == "stats":
            fmt.line(f"  {fmt.C.BOLD}{host.label}{fmt.C.RESET}")
            for line in lines_out:
                parts = line.split("|")
                name = parts[0] if len(parts) > 0 else "?"
                cpu = parts[1] if len(parts) > 1 else "?"
                mem = parts[2] if len(parts) > 2 else "?"
                fmt.line(f"    {name:<20} CPU: {cpu:<8} MEM: {mem}")
            total_containers += len(lines_out)

        elif action == "logs":
            fmt.line(f"  {fmt.C.BOLD}{host.label}{fmt.C.RESET}")
            for line in lines_out:
                fmt.line(f"    {fmt.C.DIM}{line}{fmt.C.RESET}")

        fmt.blank()

    if action in ("ps", "stats"):
        fmt.line(
            f"  {fmt.C.BOLD}Total:{fmt.C.RESET} {total_containers} container(s) across {len(docker_hosts)} host(s)"
        )

    fmt.blank()
    fmt.footer()
    return 0


# ─────────────────────────────────────────────────────────────
# HELPERS — Target resolution and info formatting
# ─────────────────────────────────────────────────────────────


def _resolve_targets(cfg: FreqConfig, target: str) -> list:
    """Resolve a target string to a list of hosts."""
    if not target or target.lower() == "all":
        return cfg.hosts

    # Try as group first
    group_hosts = resolve.by_group(cfg.hosts, target)
    if group_hosts:
        return group_hosts

    # Try as type
    type_hosts = resolve.by_type(cfg.hosts, target)
    if type_hosts:
        return type_hosts

    # Try as single host
    host = resolve.by_target(cfg.hosts, target)
    if host:
        return [host]

    # Try as comma-separated labels
    if "," in target:
        return resolve.by_labels(cfg.hosts, target)

    return []


def cmd_diagnose(cfg: FreqConfig, pack, args) -> int:
    """Deep diagnostic for a single host — hardware, network, services, security."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq fleet diagnose <host>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    fmt.header(f"Diagnose: {host.label}")
    fmt.blank()

    # Sections — each is a dict of {check_name: command}
    sections = {
        "System": {
            "hostname": "hostname -f 2>/dev/null || hostname",
            "os": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'",
            "kernel": "uname -r",
            "arch": "uname -m",
            "uptime": "uptime -p 2>/dev/null || uptime",
            "last_boot": "who -b 2>/dev/null | awk '{print $3, $4}'",
        },
        "Hardware": {
            "cpu_model": "grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs",
            "cpu_cores": "nproc",
            "ram_total": "free -h | awk '/Mem:/ {print $2}'",
            "ram_used": "free -h | awk '/Mem:/ {print $3}'",
            "ram_pct": "free | awk '/Mem:/ {printf \"%.0f%%\", $3/$2*100}'",
            "swap": "free -h | awk '/Swap:/ {print $3\"/\"$2}'",
            "load": "cat /proc/loadavg | awk '{print $1, $2, $3}'",
        },
        "Storage": {
            "disks": "df -h --output=source,size,used,avail,pcent,target 2>/dev/null | grep -E '^/' | head -10",
        },
        "Network": {
            "interfaces": "ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $NF\": \"$2}'",
            "default_gw": "ip route show default 2>/dev/null | awk '{print $3}' | head -1",
            "dns": "grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | tr '\\n' ' '",
            "listening": "ss -tlnp 2>/dev/null | grep LISTEN | awk '{print $4}' | sed 's/.*://' | sort -un | tr '\\n' ' '",
        },
        "Services": {
            "docker": "docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null | head -15 || echo 'not installed'",
            "systemd_failed": "systemctl --failed --no-legend 2>/dev/null | head -5 || echo 'n/a'",
            "running_services": "systemctl list-units --type=service --state=running --no-legend 2>/dev/null | wc -l",
        },
        "Security": {
            "ssh_root": "grep -i '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'",
            "ssh_passwd": "grep -i '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null | awk '{print $2}'",
            "users_with_shell": "grep -c '/bin/bash\\|/bin/zsh\\|/bin/sh' /etc/passwd 2>/dev/null",
            "last_login": "last -1 --time-format iso 2>/dev/null | head -1",
            "failed_logins": "journalctl -u sshd --since '24 hours ago' --no-pager 2>/dev/null | grep -c 'Failed password' || echo '0'",
        },
    }

    for section_name, checks in sections.items():
        fmt.line(f"{fmt.C.PURPLE_BOLD}{section_name}{fmt.C.RESET}")

        for check_name, cmd in checks.items():
            r = ssh_run(
                host=host.ip,
                command=cmd,
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=FLEET_QUICK_TIMEOUT,
                htype=host.htype,
                use_sudo=False,
                cfg=cfg,
            )
            value = r.stdout.strip() if r.returncode == 0 else f"{fmt.C.RED}error{fmt.C.RESET}"
            label = check_name.replace("_", " ").title()

            # Multi-line output (disks, docker, etc)
            if "\n" in value:
                print(f"    {fmt.C.GRAY}{label}:{fmt.C.RESET}")
                for line in value.split("\n"):
                    print(f"      {fmt.C.DIM}{line}{fmt.C.RESET}")
            else:
                print(f"    {fmt.C.GRAY}{label:>18}:{fmt.C.RESET}  {value}")

        fmt.blank()

    fmt.footer()
    return 0


def cmd_log(cfg: FreqConfig, pack, args) -> int:
    """View recent logs from a host via journalctl."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq fleet log <host> [--lines N] [--unit <service>]")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    lines = getattr(args, "lines", None) or 30
    unit = getattr(args, "unit", None)

    fmt.header(f"Logs: {host.label}")
    fmt.blank()

    cmd = f"journalctl --no-pager -n {lines} --output=short-iso"
    if unit:
        cmd += f" -u {unit}"

    # Try without sudo first (works on most hosts), fall back to sudo
    r = ssh_run(
        host=host.ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
        cfg=cfg,
    )
    if r.returncode != 0 and "password" not in r.stderr:
        # Try with sudo
        r = ssh_run(
            host=host.ip,
            command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=FLEET_CMD_TIMEOUT,
            htype=host.htype,
            use_sudo=True,
            cfg=cfg,
        )

    if r.returncode != 0:
        fmt.line(f"{fmt.C.RED}Failed to retrieve logs.{fmt.C.RESET}")
        if r.stderr:
            fmt.line(f"{fmt.C.DIM}{r.stderr}{fmt.C.RESET}")
    elif r.stdout:
        for log_line in r.stdout.split("\n"):
            # Colorize severity
            if "error" in log_line.lower() or "fail" in log_line.lower():
                print(f"  {fmt.C.RED}{log_line}{fmt.C.RESET}")
            elif "warn" in log_line.lower():
                print(f"  {fmt.C.YELLOW}{log_line}{fmt.C.RESET}")
            else:
                print(f"  {fmt.C.DIM}{log_line}{fmt.C.RESET}")
    else:
        fmt.line(f"{fmt.C.YELLOW}No log entries found.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


# ─────────────────────────────────────────────────────────────
# SSH & KEYS — Interactive SSH, key deployment, key rotation
# ─────────────────────────────────────────────────────────────


def cmd_ssh_host(cfg: FreqConfig, pack, args) -> int:
    """SSH to a fleet host interactively."""
    import os

    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq fleet ssh <host>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    from freq.core.ssh import get_platform_ssh, result_for

    platform = get_platform_ssh(host.htype, cfg)
    user = platform["user"]

    ssh_cmd = ["ssh"]
    ssh_cmd.extend(["-o", "StrictHostKeyChecking=accept-new"])
    if cfg.ssh_key_path:
        ssh_cmd.extend(["-i", cfg.ssh_key_path])
    ssh_cmd.extend(platform.get("extra_opts", []))
    ssh_cmd.append(f"{user}@{host.ip}")

    fmt.dim(f"  Connecting to {host.label} ({host.ip}) as {user}...")
    print()

    # Replace current process with SSH
    os.execvp("ssh", ssh_cmd)
    return 0  # Never reached


def cmd_keys(cfg: FreqConfig, pack, args) -> int:
    """SSH key management — deploy, list, rotate."""
    action = getattr(args, "action", None) or "list"

    if action == "list":
        return _keys_list(cfg)
    elif action == "deploy":
        return _keys_deploy(cfg, args)
    elif action == "rotate":
        return _keys_rotate(cfg, args)
    else:
        fmt.error(f"Unknown keys action: {action}")
        return 1


def _keys_list(cfg: FreqConfig) -> int:
    """List SSH key status across fleet."""
    fmt.header("SSH Keys")
    fmt.blank()

    if not cfg.ssh_key_path:
        fmt.line(f"{fmt.C.RED}No SSH key found.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Show local key info
    r = subprocess.run(
        ["ssh-keygen", "-l", "-f", cfg.ssh_key_path],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0:
        fmt.line(f"{fmt.C.BOLD}Local key:{fmt.C.RESET}  {r.stdout.strip()}")
    else:
        fmt.line(f"{fmt.C.BOLD}Local key:{fmt.C.RESET}  {cfg.ssh_key_path}")

    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Fleet key status:{fmt.C.RESET}")
    fmt.blank()

    # Check each host
    fmt.table_header(
        ("HOST", 16),
        ("STATUS", 10),
        ("AUTH", 12),
    )

    pub_key_path = cfg.ssh_key_path + ".pub"
    try:
        with open(pub_key_path) as f:
            pub_key_data = f.read().strip().split()[1]  # Just the key material
    except (FileNotFoundError, IndexError):
        pub_key_data = None

    results = ssh_run_many(
        hosts=cfg.hosts,
        command="cat ~/.ssh/authorized_keys 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_QUICK_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    deployed = 0
    for h in cfg.hosts:
        r = result_for(results, h)
        if r and r.returncode == 0:
            if pub_key_data and pub_key_data in r.stdout:
                deployed += 1
                fmt.table_row(
                    (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                    (fmt.badge("ok"), 10),
                    ("key deployed", 12),
                )
            else:
                fmt.table_row(
                    (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                    (fmt.badge("warn"), 10),
                    ("key missing", 12),
                )
        else:
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (fmt.badge("down"), 10),
                ("unreachable", 12),
            )

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{deployed}{fmt.C.RESET} deployed  ({len(cfg.hosts)} total)")
    fmt.blank()
    fmt.footer()
    return 0


def _keys_deploy(cfg: FreqConfig, args) -> int:
    """Deploy SSH key to a host."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq keys deploy --target <host>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    if not cfg.ssh_key_path:
        fmt.error("No SSH key found.")
        return 1

    pub_key_path = cfg.ssh_key_path + ".pub"
    try:
        with open(pub_key_path) as f:
            pub_key = f.read().strip()
    except FileNotFoundError:
        fmt.error(f"Public key not found: {pub_key_path}")
        return 1

    fmt.header(f"Deploy Key: {host.label}")
    fmt.blank()
    fmt.step_start(f"Deploying key to {host.label}")

    from freq.core.ssh import get_platform_ssh, result_for

    platform = get_platform_ssh(host.htype, cfg)
    user = platform["user"]

    r = subprocess.run(
        ["ssh-copy-id", "-i", pub_key_path, f"{user}@{host.ip}"],
        capture_output=True,
        text=True,
        timeout=FLEET_SLOW_TIMEOUT,
    )

    if r.returncode == 0:
        fmt.step_ok(f"Key deployed to {host.label}")
    else:
        fmt.step_fail(f"Deploy failed: {r.stderr.strip()}")

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


def _keys_rotate(cfg: FreqConfig, args) -> int:
    """Rotate SSH keys: generate new key pair, deploy to all hosts, verify.

    Steps:
    1. Backup current key
    2. Generate new ed25519 key
    3. Deploy new key to all reachable hosts (while old key still works)
    4. Verify new key works on each host
    5. Report results
    """
    import shutil

    if not cfg.ssh_key_path:
        fmt.error("No SSH key configured.")
        return 1

    if not os.path.isfile(cfg.ssh_key_path):
        fmt.error(f"Current key not found: {cfg.ssh_key_path}")
        return 1

    key_dir = os.path.dirname(cfg.ssh_key_path)
    old_key = cfg.ssh_key_path
    old_pub = old_key + ".pub"

    fmt.header("SSH Key Rotation")
    fmt.blank()

    # Confirm
    if not getattr(args, "yes", False):
        fmt.line(f"  {fmt.C.YELLOW}This will rotate the SSH key across {len(cfg.hosts)} host(s).{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.YELLOW}Current key: {old_key}{fmt.C.RESET}")
        try:
            confirm = input(f"  {fmt.C.YELLOW}Proceed? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm != "y":
            fmt.info("Cancelled.")
            return 0

    # Step 1: Backup current key
    fmt.step_start("Backing up current key")
    backup_path = old_key + ".bak"
    shutil.copy2(old_key, backup_path)
    if os.path.isfile(old_pub):
        shutil.copy2(old_pub, old_pub + ".bak")
    fmt.step_ok(f"Backup saved: {backup_path}")

    # Step 2: Generate new key
    fmt.step_start("Generating new ed25519 key")
    hostname = os.uname().nodename
    r = subprocess.run(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-C",
            f"freq-rotated@{hostname}",
            "-f",
            old_key,
            "-N",
            "",
            "-q",
            "",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # ssh-keygen won't overwrite — remove old first, then generate
    os.remove(old_key)
    if os.path.isfile(old_pub):
        os.remove(old_pub)
    r = subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-C", f"freq-rotated@{hostname}", "-f", old_key, "-N", "", "-q"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        fmt.step_fail(f"Key generation failed: {r.stderr}")
        # Restore backup
        shutil.copy2(backup_path, old_key)
        fmt.info("Restored from backup.")
        fmt.blank()
        fmt.footer()
        return 1
    os.chmod(old_key, 0o600)
    os.chmod(old_pub, 0o644)
    fmt.step_ok("New key generated")

    # Step 3: Read new public key
    with open(old_pub) as f:
        new_pubkey = f.read().strip()

    # Step 4: Deploy new key to all hosts using the BACKUP (old) key
    successes = 0
    failures = 0
    for h in cfg.hosts:
        if h.htype in ("switch", "idrac"):
            continue  # Skip non-Linux hosts
        fmt.step_start(f"Deploying to {h.label} ({h.ip})")
        from freq.core.ssh import run as ssh_run, result_for

        # Use the backup key to add the new key
        escaped = new_pubkey.replace('"', '\\"')
        cmd = (
            f"mkdir -p ~/.ssh && "
            f'grep -qF "{escaped}" ~/.ssh/authorized_keys 2>/dev/null || '
            f'echo "{escaped}" >> ~/.ssh/authorized_keys'
        )
        result = ssh_run(
            host=h.ip,
            command=cmd,
            key_path=backup_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=15,
            htype=h.htype,
            use_sudo=False,
            cfg=cfg,
        )
        if result.returncode == 0:
            fmt.step_ok(f"Deployed to {h.label}")
            successes += 1
        else:
            fmt.step_fail(f"Failed: {h.label} — {result.stderr[:80]}")
            failures += 1

    # Step 5: Remove old key from authorized_keys on all hosts
    old_pub_bak = old_pub + ".bak"
    if successes > 0 and os.path.isfile(old_pub_bak):
        with open(old_pub_bak) as f:
            old_pubkey = f.read().strip()
        if old_pubkey:
            fmt.blank()
            fmt.divider("Removing old key")
            for h in cfg.hosts:
                if h.htype in ("switch", "idrac"):
                    continue
                from freq.core.ssh import run as ssh_run, result_for

                old_escaped = old_pubkey.replace("/", "\\/").replace(".", "\\.")
                rm_cmd = f"sed -i '/{old_escaped}/d' ~/.ssh/authorized_keys 2>/dev/null; echo OK"
                result = ssh_run(
                    host=h.ip,
                    command=rm_cmd,
                    key_path=old_key,
                    connect_timeout=cfg.ssh_connect_timeout,
                    command_timeout=15,
                    htype=h.htype,
                    use_sudo=False,
                    cfg=cfg,
                )
                if result.returncode == 0:
                    fmt.step_ok(f"Old key removed from {h.label}")
                else:
                    fmt.step_warn(f"Could not remove old key from {h.label}")

    fmt.blank()
    fmt.divider("Results")
    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{successes}{fmt.C.RESET} deployed  {fmt.C.RED}{failures}{fmt.C.RESET} failed")
    if failures > 0:
        fmt.line(f"  {fmt.C.YELLOW}Old key backup: {backup_path}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0 if failures == 0 else 1


# ─────────────────────────────────────────────────────────────
# FLEET MAINTENANCE — NTP sync, OS updates, logging
# ─────────────────────────────────────────────────────────────


def cmd_ntp(cfg: FreqConfig, pack, args) -> int:
    """NTP check/fix across fleet."""
    action = getattr(args, "action", None) or "check"

    hosts = cfg.hosts
    if not hosts:
        fmt.error("No hosts registered.")
        return 1

    fmt.header("Fleet NTP")
    fmt.blank()

    if action == "fix":
        return _ntp_fix(cfg, hosts)

    # Check mode
    fmt.table_header(("HOST", 16), ("SYNCED", 8), ("TIMESYNCD", 10), ("TIME", 20))

    issues = 0
    results = ssh_run_many(
        hosts=hosts,
        command="timedatectl show --property=NTPSynchronized --value 2>/dev/null; "
        "systemctl is-active systemd-timesyncd 2>/dev/null; "
        "date '+%Y-%m-%d %H:%M:%S %Z'",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_QUICK_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode == 0 and r.stdout:
            lines = r.stdout.strip().split("\n")
            synced = lines[0].strip() if lines else "?"
            service = lines[1].strip() if len(lines) > 1 else "?"
            current_time = lines[2].strip() if len(lines) > 2 else "?"

            synced_badge = fmt.badge("ok") if synced == "yes" else fmt.badge("warn")
            svc_badge = fmt.badge("ok") if service == "active" else fmt.badge("warn")

            if synced != "yes" or service != "active":
                issues += 1

            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (synced_badge, 8),
                (svc_badge, 10),
                (current_time, 20),
            )
        else:
            issues += 1
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (fmt.badge("down"), 8),
                (fmt.badge("down"), 10),
                ("unreachable", 20),
            )

    fmt.blank()
    if issues:
        fmt.line(f"  {fmt.C.YELLOW}{issues} host(s) with NTP issues.{fmt.C.RESET}")
        fmt.info("Run 'freq fleet ntp fix' to remediate.")
    else:
        fmt.line(f"  {fmt.C.GREEN}All hosts time-synced.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 1 if issues else 0


def _ntp_fix(cfg, hosts) -> int:
    """Fix NTP on hosts that aren't synced."""
    fmt.line(f"{fmt.C.BOLD}Fixing NTP across {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    results = ssh_run_many(
        hosts=hosts,
        command="sudo systemctl enable --now systemd-timesyncd 2>/dev/null && "
        "sudo timedatectl set-ntp true 2>/dev/null && "
        "echo NTP_FIXED",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    fixed = 0
    for h in hosts:
        r = result_for(results, h)
        if r and "NTP_FIXED" in r.stdout:
            fixed += 1
            fmt.step_ok(f"{h.label} NTP enabled")
        else:
            fmt.step_fail(f"{h.label} NTP fix failed")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{fixed}{fmt.C.RESET}/{len(hosts)} hosts fixed")
    fmt.blank()
    fmt.footer()
    return 0


def cmd_fleet_update(cfg: FreqConfig, pack, args) -> int:
    """Check/apply OS updates across fleet."""
    action = getattr(args, "action", None) or "check"

    hosts = cfg.hosts
    if not hosts:
        fmt.error("No hosts registered.")
        return 1

    fmt.header("Fleet Updates")
    fmt.blank()

    if action == "apply":
        return _fleet_update_apply(cfg, hosts)

    # Check mode — detect package manager and count available updates
    fmt.table_header(("HOST", 16), ("UPDATES", 10), ("PKG MGR", 8))

    results = ssh_run_many(
        hosts=hosts,
        command="if command -v apt >/dev/null 2>&1; then "
        "  apt list --upgradable 2>/dev/null | grep -c upgradable; echo apt; "
        "elif command -v dnf >/dev/null 2>&1; then "
        "  dnf check-update 2>/dev/null | grep -c '^[a-zA-Z]'; echo dnf; "
        "elif command -v zypper >/dev/null 2>&1; then "
        "  zypper list-updates 2>/dev/null | grep -c '|'; echo zypper; "
        "else echo 0; echo unknown; fi",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_SLOW_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    total_updates = 0
    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode in (0, 100) and r.stdout:
            lines = r.stdout.strip().split("\n")
            count = lines[0].strip() if lines else "?"
            pkg_mgr = lines[1].strip() if len(lines) > 1 else "?"
            try:
                num = int(count)
                total_updates += num
                color = fmt.C.YELLOW if num > 0 else fmt.C.GREEN
                count_str = f"{color}{num}{fmt.C.RESET}"
            except ValueError:
                count_str = count
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (count_str, 10),
                (pkg_mgr, 8),
            )
        else:
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (fmt.badge("down"), 10),
                ("?", 8),
            )

    fmt.blank()
    fmt.line(f"  {total_updates} update(s) available across fleet")
    if total_updates > 0:
        fmt.info("Run 'freq fleet update apply' to install.")
    fmt.blank()
    fmt.footer()
    return 0


def _fleet_update_apply(cfg, hosts) -> int:
    """Apply updates across fleet."""
    fmt.line(f"{fmt.C.BOLD}Applying updates to {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.line(f"{fmt.C.YELLOW}This may take several minutes.{fmt.C.RESET}")
    fmt.blank()

    results = ssh_run_many(
        hosts=hosts,
        command="if command -v apt >/dev/null 2>&1; then "
        "  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && "
        "  sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -qq && echo UPDATE_OK; "
        "elif command -v dnf >/dev/null 2>&1; then "
        "  sudo dnf upgrade -y --quiet && echo UPDATE_OK; "
        "elif command -v zypper >/dev/null 2>&1; then "
        "  sudo zypper update -y --no-confirm && echo UPDATE_OK; "
        "else echo UPDATE_UNKNOWN; fi",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_EXEC_TIMEOUT,
        max_parallel=3,  # Don't slam all hosts at once
        use_sudo=False,
        cfg=cfg,
    )

    ok = 0
    for h in hosts:
        r = result_for(results, h)
        if r and "UPDATE_OK" in r.stdout:
            ok += 1
            fmt.step_ok(f"{h.label} updated")
        else:
            err = r.stderr[:40] if r and r.stderr else "timeout or error"
            fmt.step_fail(f"{h.label}: {err}")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{ok}{fmt.C.RESET}/{len(hosts)} hosts updated")
    fmt.blank()
    fmt.footer()
    return 0


def _info_field(label: str, value: str) -> None:
    """Print a key-value info field."""
    fmt.line(f"  {fmt.C.GRAY}{label:>12}:{fmt.C.RESET}  {value}")


def cmd_test_connection(cfg: FreqConfig, pack, args) -> int:
    """Three-step connectivity test: TCP → SSH auth → sudo access."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq test-connection <host>")
        fmt.info("  host: IP address or hostname")
        return 1

    # Resolve label to IP if needed
    ip = target
    for h in cfg.hosts:
        if h.label == target:
            ip = h.ip
            break

    fmt.header("Test Connection: {}".format(ip))
    fmt.blank()

    # Step 1: TCP connect to port 22
    fmt.step_start("TCP connect to port 22")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((ip, 22))
        s.close()
        fmt.step_ok("Port 22 reachable")
    except (socket.timeout, socket.error, OSError) as e:
        fmt.step_fail("Port 22 unreachable: {}".format(e))
        fmt.info("Check: firewall rules, host is up, SSH service running")
        fmt.blank()
        fmt.footer()
        return 1

    # Step 2: SSH auth
    fmt.step_start("SSH authentication")
    r = ssh_run(
        host=ip,
        command="echo FREQ_AUTH_OK",
        key_path=cfg.ssh_key_path,
        command_timeout=10,
        htype="linux",
        use_sudo=False,
        cfg=cfg,
    )
    if r.returncode == 0 and "FREQ_AUTH_OK" in r.stdout:
        fmt.step_ok("SSH auth succeeded as {}".format(cfg.ssh_service_account))
    else:
        fmt.step_fail("SSH auth failed")
        fmt.info("Check: SSH key deployed, user exists, sshd allows key auth")
        if r.stderr:
            fmt.info("Error: {}".format(r.stderr.split("\\n")[0][:60]))
        fmt.blank()
        fmt.footer()
        return 1

    # Step 3: sudo access
    fmt.step_start("Sudo access")
    r = ssh_run(
        host=ip,
        command="echo FREQ_SUDO_OK",
        key_path=cfg.ssh_key_path,
        command_timeout=10,
        htype="linux",
        use_sudo=True,
        cfg=cfg,
    )
    if r.returncode == 0 and "FREQ_SUDO_OK" in r.stdout:
        fmt.step_ok("Sudo access confirmed (NOPASSWD)")
    else:
        fmt.step_fail("Sudo access denied")
        fmt.info("Check: sudoers entry for {} with NOPASSWD".format(cfg.ssh_service_account))
        fmt.blank()
        fmt.footer()
        return 1

    fmt.blank()
    fmt.line("  {g}All checks passed — host is FREQ-ready{r}".format(g=fmt.C.GREEN, r=fmt.C.RESET))
    fmt.blank()
    fmt.footer()
    return 0
