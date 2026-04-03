"""Hardware management for FREQ — iDRAC, IPMI, SMART, UPS.

Domain: freq hw <action>
What: Server hardware monitoring and management. iDRAC via Redfish/racadm,
      IPMI via ipmitool, SMART via smartctl, UPS via NUT. Graduated
      from infrastructure.py.
Replaces: iDRAC web UI, manual ipmitool, individual smartctl runs
Architecture:
    - iDRAC: SSH with racadm commands (existing), future Redfish REST API
    - IPMI: shells to ipmitool for non-Dell servers
    - SMART: ssh_run_many with smartctl across fleet
    - UPS: SSH to NUT server, run upsc commands
Design decisions:
    - racadm SSH first. Redfish is better but not all iDRACs support it.
    - SMART scanning is fleet-wide — every host with drives gets checked.
    - UPS management via NUT — the standard Linux UPS daemon.
"""

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many
from freq.core import log as logger


# ---------------------------------------------------------------------------
# SMART Monitoring
# ---------------------------------------------------------------------------


def cmd_hw_smart(cfg: FreqConfig, pack, args) -> int:
    """Check SMART health across fleet."""
    fmt.header("SMART Health", breadcrumb="FREQ > Hardware")
    fmt.blank()

    # Run smartctl on PVE nodes and NAS
    targets = [h for h in cfg.hosts if h.htype in ("pve", "truenas", "linux")]
    if not targets:
        fmt.warn("No hosts to check")
        fmt.footer()
        return 1

    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in targets]
    cmd = 'smartctl --scan 2>/dev/null | while read dev rest; do echo "$dev|$(smartctl -H $dev 2>/dev/null | grep overall)"; done'
    results = run_many(
        hosts=hosts_data,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
    )

    issues = 0
    for h in targets:
        r = results.get(h.ip)
        if r and r.returncode == 0 and r.stdout.strip():
            fmt.line(f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}")
            for line in r.stdout.strip().splitlines():
                parts = line.split("|")
                dev = parts[0] if parts else "?"
                health = parts[1].strip() if len(parts) > 1 else "unknown"
                if "PASSED" in health:
                    fmt.line(f"  {fmt.C.GREEN}{dev:<16} PASSED{fmt.C.RESET}")
                elif health:
                    fmt.line(f"  {fmt.C.RED}{dev:<16} {health}{fmt.C.RESET}")
                    issues += 1
            fmt.blank()
        else:
            fmt.line(f"  {fmt.C.DIM}{h.label}: smartctl not available{fmt.C.RESET}")

    if issues:
        fmt.warn(f"{issues} drive(s) with health issues")
    else:
        fmt.success("All drives healthy")

    logger.info("hw_smart", hosts=len(targets), issues=issues)
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# UPS Monitoring
# ---------------------------------------------------------------------------


def cmd_hw_ups(cfg: FreqConfig, pack, args) -> int:
    """Show UPS status via NUT."""
    fmt.header("UPS Status", breadcrumb="FREQ > Hardware")
    fmt.blank()

    # Try to find a host running NUT
    targets = [h for h in cfg.hosts if h.htype in ("linux", "pve")]
    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in targets]
    results = run_many(
        hosts=hosts_data,
        command="upsc -l 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=5,
    )

    found = False
    for h in targets:
        r = results.get(h.ip)
        if r and r.returncode == 0 and r.stdout.strip():
            ups_names = r.stdout.strip().splitlines()
            for ups in ups_names:
                ups = ups.strip()
                if not ups:
                    continue
                found = True
                # Get UPS details
                detail_r = ssh_run(
                    host=h.ip,
                    command=f"upsc {ups} 2>/dev/null",
                    key_path=cfg.ssh_key_path,
                    connect_timeout=cfg.ssh_connect_timeout,
                    command_timeout=5,
                    htype=h.htype,
                )
                if detail_r.returncode == 0:
                    fmt.line(f"{fmt.C.BOLD}UPS: {ups} (on {h.label}){fmt.C.RESET}")
                    important = [
                        "battery.charge",
                        "battery.runtime",
                        "ups.load",
                        "ups.status",
                        "input.voltage",
                        "output.voltage",
                    ]
                    for line in detail_r.stdout.splitlines():
                        key, _, val = line.partition(":")
                        if key.strip() in important:
                            fmt.line(f"  {fmt.C.CYAN}{key.strip():<22}{fmt.C.RESET} {val.strip()}")
                    fmt.blank()

    if not found:
        fmt.warn("No UPS found (NUT not running or upsc not available)")
        fmt.info("Install NUT using your package manager (apt, dnf, pacman, etc.)")

    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Power Management
# ---------------------------------------------------------------------------


def cmd_hw_power(cfg: FreqConfig, pack, args) -> int:
    """Show fleet power consumption estimates."""
    fmt.header("Power Consumption", breadcrumb="FREQ > Hardware")
    fmt.blank()

    targets = [h for h in cfg.hosts if h.htype in ("pve", "linux")]
    if not targets:
        fmt.warn("No hosts to check")
        fmt.footer()
        return 1

    # Estimate from /proc — CPU count * TDP estimate
    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in targets]
    cmd = "nproc && cat /proc/cpuinfo | grep 'model name' | head -1"
    results = run_many(
        hosts=hosts_data,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=5,
    )

    total_watts = 0
    for h in targets:
        r = results.get(h.ip)
        if r and r.returncode == 0:
            lines = r.stdout.strip().splitlines()
            cores = int(lines[0]) if lines and lines[0].isdigit() else 0
            model = lines[1].split(":", 1)[1].strip() if len(lines) > 1 and ":" in lines[1] else "?"
            # Rough estimate: 10W per core for desktop, 5W for low-power
            est_watts = cores * 8
            total_watts += est_watts
            fmt.line(f"  {h.label:<14} {cores} cores  ~{est_watts}W  {fmt.C.DIM}{model[:40]}{fmt.C.RESET}")

    fmt.blank()
    fmt.info(f"Estimated total: ~{total_watts}W ({total_watts * 24 * 30 / 1000:.0f} kWh/month)")
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def cmd_hw_inventory(cfg: FreqConfig, pack, args) -> int:
    """Show hardware inventory across fleet."""
    fmt.header("Hardware Inventory", breadcrumb="FREQ > Hardware")
    fmt.blank()

    targets = [h for h in cfg.hosts if h.htype in ("pve", "linux", "docker")]
    hosts_data = [{"ip": h.ip, "label": h.label, "htype": h.htype} for h in targets]
    cmd = (
        "echo CPU:$(nproc);"
        "echo RAM:$(free -g | awk '/Mem:/{print $2}')G;"
        "echo DISK:$(lsblk -d -o SIZE --noheadings 2>/dev/null | head -1);"
        "echo KERNEL:$(uname -r)"
    )
    results = run_many(
        hosts=hosts_data,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=10,
    )

    fmt.table_header(("Host", 14), ("Type", 8), ("CPU", 4), ("RAM", 6), ("Disk", 8), ("Kernel", 20))
    for h in targets:
        r = results.get(h.ip)
        if r and r.returncode == 0:
            info = {}
            for line in r.stdout.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    info[k] = v
            fmt.table_row(
                (h.label, 14),
                (h.htype, 8),
                (info.get("CPU", "?"), 4),
                (info.get("RAM", "?"), 6),
                (info.get("DISK", "?"), 8),
                (info.get("KERNEL", "?")[:20], 20),
            )
        else:
            fmt.table_row((h.label, 14), (h.htype, 8), ("?", 4), ("?", 6), ("?", 8), ("unreachable", 20))

    fmt.blank()
    fmt.info(f"{len(targets)} host(s)")
    fmt.footer()
    return 0
