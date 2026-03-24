"""Fleet operations for FREQ.

Commands: status, exec, info, diagnose, docker, keys, dashboard
The core of fleet management — every command talks to real hosts via SSH.
"""
import asyncio
import subprocess
import time

from freq.core import fmt
from freq.core import resolve
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many
from freq.core.types import Host

# Fleet operation timeouts
FLEET_QUICK_TIMEOUT = 10
FLEET_CMD_TIMEOUT = 15
FLEET_SLOW_TIMEOUT = 30
FLEET_EXEC_TIMEOUT = 600


def cmd_status(cfg: FreqConfig, pack, args) -> int:
    """Fleet health summary — ping every host and report status."""
    fmt.header("Fleet Status")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"{fmt.C.YELLOW}No hosts registered. Run: freq hosts add{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.line(f"{fmt.C.BOLD}Checking {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    # Parallel ping all hosts (no sudo needed for uptime)
    start = time.monotonic()
    results = ssh_run_many(
        hosts=hosts,
        command="uptime -p 2>/dev/null || uptime",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_QUICK_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )
    total_duration = time.monotonic() - start

    # Display results
    fmt.table_header(
        ("HOST", 16),
        ("STATUS", 10),
        ("UPTIME", 30),
        ("TIME", 6),
    )

    up = 0
    down = 0
    for h in hosts:
        r = results.get(h.label)
        if r and r.returncode == 0:
            up += 1
            uptime = r.stdout.strip().replace("up ", "")
            if len(uptime) > 30:
                uptime = uptime[:27] + "..."
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (fmt.badge("up"), 10),
                (uptime, 30),
                (f"{r.duration:.1f}s", 6),
            )
        else:
            down += 1
            err = r.stderr[:30] if r else "no response"
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 16),
                (fmt.badge("down"), 10),
                (f"{fmt.C.RED}{err}{fmt.C.RESET}", 30),
                (f"{r.duration:.1f}s" if r else "—", 6),
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


def cmd_exec(cfg: FreqConfig, pack, args) -> int:
    """Run a command across fleet hosts."""
    target = getattr(args, "target", None)
    cmd_parts = getattr(args, "cmd", [])

    if not cmd_parts:
        fmt.error("Usage: freq exec <target> <command>")
        fmt.info("  target: host label, group name, or 'all'")
        fmt.info("  Example: freq exec all uptime")
        fmt.info("  Example: freq exec distro 'cat /etc/os-release | head -1'")
        return 1

    command = " ".join(cmd_parts)

    # Resolve targets
    hosts = _resolve_targets(cfg, target)
    if not hosts:
        fmt.error(f"No hosts matched: {target}")
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
    )
    total_duration = time.monotonic() - start

    # Color rotation for host prefixes
    host_colors = [
        fmt.C.CYAN, fmt.C.GREEN, fmt.C.YELLOW, fmt.C.MAGENTA,
        fmt.C.BLUE, fmt.C.ORANGE, fmt.C.PURPLE, fmt.C.WHITE, fmt.C.RED,
    ]

    # Display results with colored host prefixes
    ok_count = 0
    fail_count = 0
    for i, h in enumerate(hosts):
        r = results.get(h.label)
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

    return 0


def cmd_info(cfg: FreqConfig, pack, args) -> int:
    """System info for a single host."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq info <host>")
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
        "disk": "df -h / | awk 'NR==2 {print $3\"/\"$2\" (\"$5\" used)\"}'",
        "ip_addrs": "ip -4 addr show | grep 'inet ' | grep -v '127.0.0.1' | awk '{print $2}' | tr '\\n' ' '",
        "load": "cat /proc/loadavg | awk '{print $1, $2, $3}'",
        "docker": "docker ps --format '{{.Names}}' 2>/dev/null | wc -l",
    }

    info = {}
    for key, cmd in commands.items():
        r = ssh_run(
            host=host.ip, command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            htype=host.htype,
            use_sudo=False,
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
        "echo \"$(hostname)|"
        "$(cat /etc/os-release 2>/dev/null | grep -oP '(?<=PRETTY_NAME=\\\").*(?=\\\")' || echo unknown)|"
        "$(nproc)|"
        "$(free -m | awk '/Mem:/ {printf \\\"%d/%dMB\\\", $3, $2}')|"
        "$(df -h / | awk 'NR==2 {print $5}')|"
        "$(uptime -p 2>/dev/null | sed 's/up //' || echo unknown)|"
        "$(docker ps -q 2>/dev/null | wc -l)\""
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
        r = results.get(h.label)
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


# --- Helpers ---

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
        fmt.error("Usage: freq diagnose <host>")
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
                host=host.ip, command=cmd,
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=FLEET_QUICK_TIMEOUT,
                htype=host.htype,
                use_sudo=False,
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
        fmt.error("Usage: freq log <host> [--lines N] [--unit <service>]")
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
        host=host.ip, command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=FLEET_CMD_TIMEOUT,
        htype=host.htype,
        use_sudo=False,
    )
    if r.returncode != 0 and "password" not in r.stderr:
        # Try with sudo
        r = ssh_run(
            host=host.ip, command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=FLEET_CMD_TIMEOUT,
            htype=host.htype,
            use_sudo=True,
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


def cmd_ssh_host(cfg: FreqConfig, pack, args) -> int:
    """SSH to a fleet host interactively."""
    import os

    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq ssh <host>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    from freq.core.ssh import PLATFORM_SSH
    platform = PLATFORM_SSH.get(host.htype, PLATFORM_SSH["linux"])
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
        fmt.error("Key rotation not yet implemented.")
        return 1
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
        capture_output=True, text=True,
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
    )

    deployed = 0
    for h in cfg.hosts:
        r = results.get(h.label)
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

    from freq.core.ssh import PLATFORM_SSH
    platform = PLATFORM_SSH.get(host.htype, PLATFORM_SSH["linux"])
    user = platform["user"]

    r = subprocess.run(
        ["ssh-copy-id", "-i", pub_key_path, f"{user}@{host.ip}"],
        capture_output=True, text=True, timeout=FLEET_SLOW_TIMEOUT,
    )

    if r.returncode == 0:
        fmt.step_ok(f"Key deployed to {host.label}")
    else:
        fmt.step_fail(f"Deploy failed: {r.stderr.strip()}")

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


# --- Helpers ---

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
    )

    for h in hosts:
        r = results.get(h.label)
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
    )

    fixed = 0
    for h in hosts:
        r = results.get(h.label)
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
    )

    total_updates = 0
    for h in hosts:
        r = results.get(h.label)
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
    )

    ok = 0
    for h in hosts:
        r = results.get(h.label)
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
