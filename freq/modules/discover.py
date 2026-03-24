"""Network discovery for FREQ.

Commands: discover

Scans a subnet for SSH-reachable hosts and identifies their platform type.
Uses parallel ping + SSH fingerprinting to find and classify hosts.
"""
import asyncio
import time

from freq.core import fmt
from freq.core import validate
from freq.core.config import FreqConfig
from freq.core.ssh import async_run

# Discovery settings
PING_TIMEOUT = 1.0
SCAN_MAX_PARALLEL = 50
SCAN_HOST_START = 1
SCAN_HOST_END = 254
IDENTIFY_CONNECT_TIMEOUT = 3
IDENTIFY_CMD_TIMEOUT = 5


async def _ping_host(ip: str, timeout: float = PING_TIMEOUT) -> bool:
    """Check if a host responds to ping."""
    proc = await asyncio.create_subprocess_exec(
        "ping", "-c", "1", "-W", str(int(timeout)), ip,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def _scan_subnet(prefix: str, start: int = SCAN_HOST_START, end: int = SCAN_HOST_END, max_parallel: int = SCAN_MAX_PARALLEL) -> list:
    """Ping sweep a subnet, return list of responding IPs."""
    semaphore = asyncio.Semaphore(max_parallel)
    alive = []

    async def _check(ip: str):
        async with semaphore:
            if await _ping_host(ip, timeout=PING_TIMEOUT):
                alive.append(ip)

    tasks = []
    for i in range(start, end + 1):
        ip = f"{prefix}.{i}"
        tasks.append(asyncio.create_task(_check(ip)))

    await asyncio.gather(*tasks)
    return sorted(alive, key=lambda x: int(x.split(".")[-1]))


async def _identify_host(ip: str, key_path: str) -> dict:
    """Try to SSH into a host and identify its platform."""
    info = {"ip": ip, "reachable": False, "hostname": "", "os": "", "type": "unknown"}

    # Try SSH as service account
    r = await async_run(
        host=ip,
        command="hostname; cat /etc/os-release 2>/dev/null | grep -oP '(?<=^ID=).*' | head -1",
        key_path=key_path,
        connect_timeout=IDENTIFY_CONNECT_TIMEOUT,
        command_timeout=IDENTIFY_CMD_TIMEOUT,
        htype="linux",
        use_sudo=False,
    )

    if r.returncode != 0:
        return info

    info["reachable"] = True
    lines = r.stdout.strip().split("\n")
    info["hostname"] = lines[0] if lines else ""

    os_id = lines[1].strip('"') if len(lines) > 1 else ""
    info["os"] = os_id

    # Detect platform type
    if os_id in ("debian", "ubuntu"):
        # Check if it's a PVE node
        r2 = await async_run(
            host=ip, command="which pvesh 2>/dev/null",
            key_path=key_path, connect_timeout=IDENTIFY_CONNECT_TIMEOUT, command_timeout=IDENTIFY_CMD_TIMEOUT,
            htype="linux", use_sudo=False,
        )
        if r2.returncode == 0 and r2.stdout.strip():
            info["type"] = "pve"
        else:
            # Check if Docker is running
            r3 = await async_run(
                host=ip, command="docker --version 2>/dev/null",
                key_path=key_path, connect_timeout=IDENTIFY_CONNECT_TIMEOUT, command_timeout=IDENTIFY_CMD_TIMEOUT,
                htype="linux", use_sudo=False,
            )
            if r3.returncode == 0 and "Docker" in r3.stdout:
                info["type"] = "docker"
            else:
                info["type"] = "linux"
    elif os_id in ("rocky", "almalinux", "centos", "fedora", "opensuse-leap"):
        info["type"] = "linux"
    elif "freenas" in os_id or "truenas" in os_id:
        info["type"] = "truenas"
    else:
        info["type"] = "linux"

    return info


def scan_and_identify(prefix: str, key_path: str, start: int = 1, end: int = 254) -> tuple:
    """Scan a subnet and identify hosts. Returns (alive_ips, hosts_info).

    Reusable core — called by both `freq discover` and `freq init` Phase 5.
    """
    fmt.step_start("Ping sweep")
    scan_start = time.monotonic()
    alive = asyncio.run(_scan_subnet(prefix, start, end))
    scan_time = time.monotonic() - scan_start
    fmt.step_ok(f"{len(alive)} hosts responding ({scan_time:.1f}s)")

    if not alive:
        return alive, []

    fmt.step_start("Identifying hosts via SSH")

    async def _identify_all():
        tasks = [_identify_host(ip, key_path) for ip in alive]
        return await asyncio.gather(*tasks)

    hosts_info = asyncio.run(_identify_all())
    ssh_reachable = sum(1 for h in hosts_info if h["reachable"])
    fmt.step_ok(f"{ssh_reachable} hosts identified")

    return alive, hosts_info


def _display_discovery_results(alive, hosts_info, known_ips):
    """Display a discovery results table. Returns count of new (unregistered) hosts."""
    fmt.blank()
    fmt.table_header(
        ("IP", 17),
        ("HOSTNAME", 20),
        ("TYPE", 10),
        ("STATUS", 10),
        ("REGISTERED", 10),
    )

    new_count = 0
    for h in hosts_info:
        ip = h["ip"]
        is_known = ip in known_ips

        if h["reachable"]:
            type_color = {
                "pve": fmt.C.PURPLE,
                "linux": fmt.C.GREEN,
                "docker": fmt.C.CYAN,
                "truenas": fmt.C.BLUE,
            }.get(h["type"], fmt.C.GRAY)

            registered = f"{fmt.C.GREEN}yes{fmt.C.RESET}" if is_known else f"{fmt.C.YELLOW}no{fmt.C.RESET}"
            if not is_known:
                new_count += 1

            fmt.table_row(
                (ip, 17),
                (h["hostname"][:20], 20),
                (f"{type_color}{h['type']}{fmt.C.RESET}", 10),
                (fmt.badge("up"), 10),
                (registered, 10),
            )
        else:
            fmt.table_row(
                (ip, 17),
                (f"{fmt.C.DIM}—{fmt.C.RESET}", 20),
                (f"{fmt.C.DIM}—{fmt.C.RESET}", 10),
                (f"{fmt.C.DIM}ping only{fmt.C.RESET}", 10),
                (f"{fmt.C.GREEN}yes{fmt.C.RESET}" if is_known else f"{fmt.C.DIM}—{fmt.C.RESET}", 10),
            )

    return new_count


def _parse_subnet_input(subnet_str: str) -> tuple:
    """Parse user subnet input. Accepts '192.168.1' or '192.168.1.0/24'.

    Returns (prefix, start, end) or (None, 0, 0) on bad input.
    """
    subnet_str = subnet_str.strip()

    # Handle CIDR notation (only /24 supported for now)
    if "/" in subnet_str:
        parts = subnet_str.split("/")
        subnet_str = parts[0]
        # Strip trailing .0 from CIDR base
        if subnet_str.endswith(".0"):
            subnet_str = subnet_str[:-2]

    # Handle 3-octet prefix: 192.168.1
    octets = subnet_str.split(".")
    if len(octets) == 3:
        try:
            for o in octets:
                v = int(o)
                if v < 0 or v > 255:
                    return None, 0, 0
            return subnet_str, 1, 254
        except ValueError:
            return None, 0, 0

    # Handle 4-octet: treat as /24 prefix
    if len(octets) == 4:
        try:
            for o in octets:
                v = int(o)
                if v < 0 or v > 255:
                    return None, 0, 0
            prefix = ".".join(octets[:3])
            return prefix, 1, 254
        except ValueError:
            return None, 0, 0

    return None, 0, 0


def cmd_discover(cfg: FreqConfig, pack, args) -> int:
    """Discover hosts on the local subnet."""
    fmt.header("Network Discovery")
    fmt.blank()

    # Get subnet from args or ask the user
    subnet = getattr(args, "subnet", None)
    if not subnet:
        try:
            subnet = input(f"  {fmt.C.CYAN}Subnet to scan (e.g. 192.168.1 or 192.168.1.0/24):{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1

    prefix, start, end = _parse_subnet_input(subnet)
    if prefix is None:
        fmt.error(f"Invalid subnet: {subnet}")
        fmt.line(f"  {fmt.C.DIM}Examples: 192.168.1  or  192.168.1.0/24{fmt.C.RESET}")
        return 1

    fmt.line(f"{fmt.C.BOLD}Scanning {prefix}.{start}-{end}...{fmt.C.RESET}")
    fmt.blank()

    alive, hosts_info = scan_and_identify(prefix, cfg.ssh_key_path, start, end)

    if not alive:
        fmt.blank()
        fmt.line(f"{fmt.C.YELLOW}No hosts found on {prefix}.0/24{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    known_ips = {h.ip for h in cfg.hosts}
    new_count = _display_discovery_results(alive, hosts_info, known_ips)

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        f"  {len(alive)} alive  "
        f"{sum(1 for h in hosts_info if h['reachable'])} SSH-reachable  "
        f"{new_count} new (not in fleet)"
    )
    if new_count > 0:
        fmt.line(f"  {fmt.C.GRAY}Add new hosts with: freq hosts add{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()

    return 0
