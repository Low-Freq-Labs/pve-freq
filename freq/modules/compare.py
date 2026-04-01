"""Side-by-side host and VM comparison for FREQ.

Domain: freq fleet <compare>

Diffs two hosts or two VMs across every dimension: CPU, RAM, disk,
packages, services, uptime, kernel, networking, Docker, swap. Find why
one host is broken and the other is not. Color-coded delta output.

Replaces: Manual SSH-and-eyeball comparison, spreadsheet diffs

Architecture:
    - Single compound SSH command gathers 17 metrics per host in one call
    - PVE API queries for VM-level comparison (cores, RAM, disk, status)
    - Side-by-side table rendering with delta highlighting via freq/core/fmt

Design decisions:
    - Everything in one SSH round-trip per host. Two hosts = two calls,
      not thirty-four. Fast enough to run ad-hoc during incidents.
"""
import json
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core import resolve
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Timeouts
CMP_CMD_TIMEOUT = 15
CMP_PVE_TIMEOUT = 30
CMP_QUICK_TIMEOUT = 10


def _gather_host_info(cfg: FreqConfig, host) -> dict:
    """Gather detailed info from a single host."""
    command = (
        'echo "HOSTNAME=$(hostname -f 2>/dev/null || hostname)"; '
        'echo "OS=$(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d \'\\"\')"; '
        'echo "KERNEL=$(uname -r)"; '
        'echo "ARCH=$(uname -m)"; '
        'echo "CORES=$(nproc)"; '
        "echo \"RAM_MB=$(free -m | awk '/Mem:/ {print $2}')\"; "
        "echo \"RAM_USED=$(free -m | awk '/Mem:/ {print $3}')\"; "
        "echo \"DISK_TOTAL=$(df -BG / | awk 'NR==2 {print $2}' | tr -d 'G')\"; "
        "echo \"DISK_USED=$(df -BG / | awk 'NR==2 {print $3}' | tr -d 'G')\"; "
        "echo \"DISK_PCT=$(df -h / | awk 'NR==2 {print $5}' | tr -d '%')\"; "
        "echo \"LOAD=$(cat /proc/loadavg | awk '{print $1, $2, $3}')\"; "
        "echo \"UPTIME=$(cat /proc/uptime | awk '{d=int($1/86400); h=int(($1%86400)/3600); printf \"%dd %dh\", d, h}')\"; "
        "echo \"DOCKER=$(systemctl is-active docker 2>/dev/null || echo inactive)\"; "
        "echo \"DOCKER_COUNT=$(docker ps -q 2>/dev/null | wc -l || echo 0)\"; "
        "echo \"IPS=$(ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $2}' | tr '\\n' ',' | sed 's/,$//')\"; "
        "echo \"SWAP_TOTAL=$(free -m | awk '/Swap:/ {print $2}')\"; "
        "echo \"SWAP_USED=$(free -m | awk '/Swap:/ {print $3}')\"; "
        "echo \"PKG_COUNT=$(dpkg --list 2>/dev/null | grep '^ii' | wc -l || rpm -qa 2>/dev/null | wc -l || echo 0)\"; "
        "echo \"SERVICES=$(systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | wc -l || echo 0)\"; "
        "echo \"USERS=$(who 2>/dev/null | wc -l || echo 0)\"; "
    )

    r = ssh_run(
        host=host.ip,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=CMP_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )

    info = {"label": host.label, "ip": host.ip, "type": host.htype, "reachable": False}

    if r.returncode != 0:
        return info

    info["reachable"] = True

    # Parse key=value output
    for line in r.stdout.strip().split("\n"):
        if "=" in line:
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip()
            info[key] = value

    return info


def _compare_field(label: str, val_a, val_b, higher_is_better: bool = True) -> tuple:
    """Compare two values and return (label, val_a_str, val_b_str, diff_indicator)."""
    str_a = str(val_a) if val_a else "-"
    str_b = str(val_b) if val_b else "-"

    # Try numeric comparison
    try:
        num_a = float(str_a.replace(",", ""))
        num_b = float(str_b.replace(",", ""))
        if num_a == num_b:
            indicator = f"{fmt.C.GREEN}={fmt.C.RESET}"
        elif (num_a > num_b) == higher_is_better:
            indicator = f"{fmt.C.GREEN}◀{fmt.C.RESET}"
        else:
            indicator = f"{fmt.C.GREEN}▶{fmt.C.RESET}"
    except (ValueError, TypeError):
        if str_a == str_b:
            indicator = f"{fmt.C.GREEN}={fmt.C.RESET}"
        else:
            indicator = f"{fmt.C.YELLOW}≠{fmt.C.RESET}"

    return label, str_a, str_b, indicator


def cmd_compare(cfg: FreqConfig, pack, args) -> int:
    """Compare two hosts or VMs side-by-side."""
    target_a = getattr(args, "target_a", None)
    target_b = getattr(args, "target_b", None)

    if not target_a or not target_b:
        fmt.error("Usage: freq compare <host-a> <host-b>")
        fmt.info("Accepts host labels or IPs")
        return 1

    fmt.header(f"Compare: {target_a} vs {target_b}")
    fmt.blank()

    # Resolve hosts
    host_a = resolve.host(cfg.hosts, target_a)
    host_b = resolve.host(cfg.hosts, target_b)

    if not host_a:
        fmt.error(f"Host not found: {target_a}")
        return 1
    if not host_b:
        fmt.error(f"Host not found: {target_b}")
        return 1

    # Gather info from both hosts
    fmt.step_start(f"Scanning {host_a.label}")
    info_a = _gather_host_info(cfg, host_a)
    if info_a["reachable"]:
        fmt.step_ok(f"{host_a.label} — reachable")
    else:
        fmt.step_fail(f"{host_a.label} — unreachable")

    fmt.step_start(f"Scanning {host_b.label}")
    info_b = _gather_host_info(cfg, host_b)
    if info_b["reachable"]:
        fmt.step_ok(f"{host_b.label} — reachable")
    else:
        fmt.step_fail(f"{host_b.label} — unreachable")

    if not info_a["reachable"] and not info_b["reachable"]:
        fmt.blank()
        fmt.error("Both hosts unreachable — nothing to compare")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.blank()

    # Build comparison table
    header_a = f"{fmt.C.CYAN}{host_a.label}{fmt.C.RESET}"
    header_b = f"{fmt.C.CYAN}{host_b.label}{fmt.C.RESET}"

    fmt.table_header(
        ("FIELD", 16),
        (host_a.label, 24),
        ("", 3),
        (host_b.label, 24),
    )

    comparisons = [
        ("Hostname", info_a.get("hostname", "-"), info_b.get("hostname", "-"), False),
        ("OS", info_a.get("os", "-"), info_b.get("os", "-"), False),
        ("Kernel", info_a.get("kernel", "-"), info_b.get("kernel", "-"), False),
        ("Arch", info_a.get("arch", "-"), info_b.get("arch", "-"), False),
    ]

    # Print identity section
    for label, va, vb, _ in comparisons:
        _, sa, sb, ind = _compare_field(label, va, vb)
        fmt.table_row(
            (f"{fmt.C.BOLD}{label}{fmt.C.RESET}", 16),
            (sa[:24], 24),
            (ind, 3),
            (sb[:24], 24),
        )

    # Divider
    print()

    # Resources
    resources = [
        _compare_field("CPU Cores", info_a.get("cores", "-"), info_b.get("cores", "-"), True),
        _compare_field("RAM (MB)", info_a.get("ram_mb", "-"), info_b.get("ram_mb", "-"), True),
        _compare_field("RAM Used", info_a.get("ram_used", "-"), info_b.get("ram_used", "-"), False),
        _compare_field("Disk Total", info_a.get("disk_total", "-"), info_b.get("disk_total", "-"), True),
        _compare_field("Disk Used", info_a.get("disk_used", "-"), info_b.get("disk_used", "-"), False),
        _compare_field("Disk %", info_a.get("disk_pct", "-"), info_b.get("disk_pct", "-"), False),
        _compare_field("Swap Total", info_a.get("swap_total", "-"), info_b.get("swap_total", "-"), True),
        _compare_field("Swap Used", info_a.get("swap_used", "-"), info_b.get("swap_used", "-"), False),
    ]

    for label, sa, sb, ind in resources:
        fmt.table_row(
            (f"{fmt.C.BOLD}{label}{fmt.C.RESET}", 16),
            (sa[:24], 24),
            (ind, 3),
            (sb[:24], 24),
        )

    print()

    # Status
    status_fields = [
        _compare_field("Load", info_a.get("load", "-"), info_b.get("load", "-"), False),
        _compare_field("Uptime", info_a.get("uptime", "-"), info_b.get("uptime", "-"), True),
        _compare_field("Docker", info_a.get("docker", "-"), info_b.get("docker", "-"), False),
        _compare_field("Containers", info_a.get("docker_count", "-"), info_b.get("docker_count", "-"), False),
        _compare_field("Packages", info_a.get("pkg_count", "-"), info_b.get("pkg_count", "-"), False),
        _compare_field("Services", info_a.get("services", "-"), info_b.get("services", "-"), False),
        _compare_field("Logged In", info_a.get("users", "-"), info_b.get("users", "-"), False),
    ]

    for label, sa, sb, ind in status_fields:
        fmt.table_row(
            (f"{fmt.C.BOLD}{label}{fmt.C.RESET}", 16),
            (sa[:24], 24),
            (ind, 3),
            (sb[:24], 24),
        )

    print()

    # Network
    ips_a = info_a.get("ips", "-")
    ips_b = info_b.get("ips", "-")
    _, sa, sb, ind = _compare_field("IPs", ips_a, ips_b, False)
    fmt.table_row(
        (f"{fmt.C.BOLD}IPs{fmt.C.RESET}", 16),
        (sa[:24], 24),
        (ind, 3),
        (sb[:24], 24),
    )

    fmt.blank()

    # Differences summary
    diff_count = 0
    all_fields = [
        ("os", "OS"), ("kernel", "Kernel"), ("cores", "CPU Cores"),
        ("ram_mb", "RAM"), ("disk_total", "Disk"), ("docker", "Docker"),
    ]
    diffs = []
    for key, label in all_fields:
        va = info_a.get(key, "")
        vb = info_b.get(key, "")
        if str(va) != str(vb) and va and vb:
            diffs.append(label)
            diff_count += 1

    fmt.divider("Summary")
    fmt.blank()
    if diff_count == 0:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} Hosts are identical across all checked fields.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} {diff_count} difference(s): {', '.join(diffs)}{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0
