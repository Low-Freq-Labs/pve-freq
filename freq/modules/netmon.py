"""Network monitoring and interface tracking for FREQ.

Commands: netmon (poll/interfaces/bandwidth/discover/topology)

SNMP polling, interface monitoring, bandwidth trending.
Topology discovery via LLDP/CDP.

Kills: SolarWinds ($2K+/node, hacked), LibreNMS (complex)
"""
import json
import os
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many

NETMON_DIR = "netmon"
NETMON_DATA = "interface-data.json"
NETMON_CMD_TIMEOUT = 15
MAX_DATAPOINTS = 500


def _netmon_dir(cfg: FreqConfig) -> str:
    path = os.path.join(cfg.conf_dir, NETMON_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_data(cfg: FreqConfig) -> dict:
    filepath = os.path.join(_netmon_dir(cfg), NETMON_DATA)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"snapshots": [], "topology": {}}


def _save_data(cfg: FreqConfig, data: dict):
    data["snapshots"] = data.get("snapshots", [])[-MAX_DATAPOINTS:]
    filepath = os.path.join(_netmon_dir(cfg), NETMON_DATA)
    with open(filepath, "w") as f:
        json.dump(data, f)


def _format_bytes(b: int) -> str:
    """Format bytes into human-readable string."""
    if b >= 1073741824:
        return f"{b / 1073741824:.1f}G"
    if b >= 1048576:
        return f"{b / 1048576:.1f}M"
    if b >= 1024:
        return f"{b / 1024:.1f}K"
    return f"{b}B"


def cmd_netmon(cfg: FreqConfig, pack, args) -> int:
    """Network monitoring dispatch."""
    action = getattr(args, "action", None) or "interfaces"
    routes = {
        "interfaces": _cmd_interfaces,
        "poll": _cmd_poll,
        "bandwidth": _cmd_bandwidth,
        "topology": _cmd_topology,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown netmon action: {action}")
    fmt.info("Available: interfaces, poll, bandwidth, topology")
    return 1


def _cmd_interfaces(cfg: FreqConfig, args) -> int:
    """Show network interface status across fleet."""
    fmt.header("Fleet Network Interfaces")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    command = (
        "ip -j addr show 2>/dev/null || "
        "ip addr show | awk '/^[0-9]/ {iface=$2} /inet / {print iface\"|\"$2}'"
    )

    fmt.step_start(f"Scanning {len(hosts)} hosts")
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=NETMON_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )
    fmt.step_ok("Scan complete")
    fmt.blank()

    total_ifaces = 0
    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            continue

        # Try JSON first
        try:
            ifaces = json.loads(r.stdout)
            fmt.divider(h.label)
            fmt.blank()
            fmt.table_header(("INTERFACE", 14), ("STATE", 8), ("IP", 20), ("MAC", 18))

            for iface in ifaces:
                name = iface.get("ifname", "?")
                state = iface.get("operstate", "?").lower()
                state_color = fmt.C.GREEN if state == "up" else fmt.C.RED
                mac = iface.get("address", "-")

                addrs = []
                for addr in iface.get("addr_info", []):
                    if addr.get("family") == "inet":
                        addrs.append(f"{addr['local']}/{addr['prefixlen']}")

                ip_str = ", ".join(addrs) if addrs else "-"

                if name == "lo":
                    continue

                total_ifaces += 1
                fmt.table_row(
                    (f"{fmt.C.BOLD}{name}{fmt.C.RESET}", 14),
                    (f"{state_color}{state}{fmt.C.RESET}", 8),
                    (ip_str[:20], 20),
                    (mac, 18),
                )
            fmt.blank()
            continue
        except json.JSONDecodeError:
            pass

        # Fallback: parse text output
        fmt.divider(h.label)
        fmt.blank()
        for line in r.stdout.strip().split("\n"):
            if "|" in line:
                parts = line.split("|", 1)
                iface = parts[0].strip().rstrip(":")
                ip = parts[1].strip() if len(parts) > 1 else "-"
                if iface != "lo:":
                    total_ifaces += 1
                    fmt.line(f"  {fmt.C.BOLD}{iface}{fmt.C.RESET}  {ip}")
        fmt.blank()

    fmt.line(f"  {fmt.C.DIM}{total_ifaces} interfaces across fleet{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_poll(cfg: FreqConfig, args) -> int:
    """Poll interface counters (bandwidth snapshot)."""
    fmt.header("Network Poll")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Get interface byte counters
    command = (
        "for iface in $(ls /sys/class/net/ | grep -v lo); do "
        "  rx=$(cat /sys/class/net/$iface/statistics/rx_bytes 2>/dev/null || echo 0); "
        "  tx=$(cat /sys/class/net/$iface/statistics/tx_bytes 2>/dev/null || echo 0); "
        "  state=$(cat /sys/class/net/$iface/operstate 2>/dev/null || echo unknown); "
        "  echo \"${iface}|${rx}|${tx}|${state}\"; "
        "done"
    )

    fmt.step_start(f"Polling {len(hosts)} hosts")
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=NETMON_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )
    fmt.step_ok("Poll complete")
    fmt.blank()

    snapshot = {"epoch": int(time.time()), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "hosts": {}}

    fmt.table_header(("HOST", 14), ("IFACE", 10), ("RX", 10), ("TX", 10), ("STATE", 8))

    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            continue

        host_ifaces = {}
        for line in r.stdout.strip().split("\n"):
            parts = line.split("|")
            if len(parts) >= 4:
                iface = parts[0]
                try:
                    rx = int(parts[1])
                    tx = int(parts[2])
                except ValueError:
                    rx = tx = 0
                state = parts[3]

                host_ifaces[iface] = {"rx": rx, "tx": tx, "state": state}

                state_color = fmt.C.GREEN if state == "up" else fmt.C.DIM
                fmt.table_row(
                    (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
                    (iface, 10),
                    (_format_bytes(rx), 10),
                    (_format_bytes(tx), 10),
                    (f"{state_color}{state}{fmt.C.RESET}", 8),
                )

        snapshot["hosts"][h.label] = host_ifaces

    # Save snapshot for bandwidth trending
    data = _load_data(cfg)
    data["snapshots"].append(snapshot)
    _save_data(cfg, data)

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Snapshot #{len(data['snapshots'])} recorded{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}View bandwidth: freq netmon bandwidth{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_bandwidth(cfg: FreqConfig, args) -> int:
    """Show bandwidth usage from poll history."""
    fmt.header("Bandwidth Usage")
    fmt.blank()

    data = _load_data(cfg)
    snapshots = data.get("snapshots", [])

    if len(snapshots) < 2:
        fmt.line(f"  {fmt.C.YELLOW}Need at least 2 polls for bandwidth data.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Run: freq netmon poll (twice, with interval){fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Calculate delta between last two snapshots
    prev = snapshots[-2]
    curr = snapshots[-1]
    elapsed = max(curr["epoch"] - prev["epoch"], 1)

    fmt.line(f"  Period: {elapsed}s between polls")
    fmt.blank()

    fmt.table_header(("HOST", 14), ("IFACE", 10), ("RX/s", 10), ("TX/s", 10))

    for label in sorted(curr.get("hosts", {}).keys()):
        curr_ifaces = curr["hosts"][label]
        prev_ifaces = prev.get("hosts", {}).get(label, {})

        for iface, counters in curr_ifaces.items():
            prev_counters = prev_ifaces.get(iface, {})
            rx_delta = max(0, counters.get("rx", 0) - prev_counters.get("rx", 0))
            tx_delta = max(0, counters.get("tx", 0) - prev_counters.get("tx", 0))

            rx_rate = rx_delta / elapsed
            tx_rate = tx_delta / elapsed

            if rx_rate > 0 or tx_rate > 0:
                fmt.table_row(
                    (f"{fmt.C.BOLD}{label}{fmt.C.RESET}", 14),
                    (iface, 10),
                    (_format_bytes(int(rx_rate)) + "/s", 10),
                    (_format_bytes(int(tx_rate)) + "/s", 10),
                )

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_topology(cfg: FreqConfig, args) -> int:
    """Discover network topology via LLDP/CDP."""
    fmt.header("Network Topology")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    command = (
        "lldpctl -f keyvalue 2>/dev/null | grep -E 'name|descr|port' | head -20 || "
        "lldpcli show neighbors 2>/dev/null | head -20 || "
        "echo 'no-lldp'"
    )

    fmt.step_start("Querying LLDP neighbors")
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=NETMON_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )
    fmt.step_ok("Discovery complete")
    fmt.blank()

    has_data = False
    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0 or "no-lldp" in r.stdout:
            continue

        if r.stdout.strip():
            has_data = True
            fmt.divider(h.label)
            fmt.blank()
            for line in r.stdout.strip().split("\n")[:10]:
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
            fmt.blank()

    if not has_data:
        fmt.line(f"  {fmt.C.DIM}No LLDP data found. Install lldpd on hosts for topology discovery.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}  apt install lldpd && systemctl enable --now lldpd{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0
