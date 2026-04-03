"""Network intelligence for FREQ — cross-switch search and diagnostics.

Domain: freq net find/trace/health
What: Find MACs/IPs across all switches, automated troubleshooting,
      subnet utilization, IP conflict detection.
Replaces: Manual SSH to each switch, spreadsheet IP tracking, guesswork
Architecture:
    - find-mac/find-ip search all switches in parallel using deployer getters
    - troubleshoot chains: ping -> DNS -> MAC lookup -> ARP -> switch port
    - IPAM extensions: utilization calculates % used per subnet, conflict
      detects duplicate IPs via ARP scan
Design decisions:
    - Search across ALL switches, not just one. The whole point is fleet-wide.
    - Troubleshoot is a diagnostic chain, not a fix. Show the path, not the patch.
    - IP conflict uses ARP tables from switches — no active scanning needed.
"""

import re
import socket

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Commands — Find
# ---------------------------------------------------------------------------


def cmd_find_mac(cfg: FreqConfig, pack, args) -> int:
    """Search all switches for a MAC address."""
    mac_query = getattr(args, "mac", None)
    if not mac_query:
        fmt.error("Usage: freq net find-mac <mac-address>")
        return 1

    from freq.modules.switch_orchestration import _get_switch_hosts, _get_deployer, _vendor_for_host

    fmt.header(f"Find MAC: {mac_query}", breadcrumb="FREQ > Net")
    fmt.blank()

    mac_clean = mac_query.lower().replace(":", "").replace("-", "").replace(".", "")
    switches = _get_switch_hosts(cfg)
    if not switches:
        fmt.error("No switches in hosts.conf")
        return 1

    all_matches = []
    for h in switches:
        vendor = _vendor_for_host(h)
        deployer = _get_deployer(vendor)
        if not deployer:
            continue

        entries = deployer.get_mac_table(h.ip, cfg)
        for e in entries:
            entry_clean = e.get("mac", "").replace(".", "").replace(":", "").replace("-", "")
            if mac_clean in entry_clean:
                all_matches.append(
                    {
                        "switch": h.label,
                        "switch_ip": h.ip,
                        "port": e.get("port", ""),
                        "vlan": e.get("vlan", ""),
                        "mac": e.get("mac", ""),
                        "type": e.get("type", ""),
                    }
                )

    if all_matches:
        fmt.table_header(("Switch", 14), ("Port", 16), ("VLAN", 6), ("MAC", 16), ("Type", 10))
        for m in all_matches:
            fmt.table_row(
                (m["switch"], 14),
                (m["port"], 16),
                (str(m["vlan"]), 6),
                (m["mac"], 16),
                (m["type"], 10),
            )
        fmt.blank()
        fmt.success(
            f"Found on {len(set(m['switch'] for m in all_matches))} switch(es), {len(all_matches)} entry/entries"
        )
    else:
        fmt.warn(f"MAC {mac_query} not found on any of {len(switches)} switches")

    logger.info("find_mac", mac=mac_query, found=len(all_matches))
    fmt.footer()
    return 0


def cmd_find_ip(cfg: FreqConfig, pack, args) -> int:
    """Search all switches' ARP tables for an IP address."""
    ip_query = getattr(args, "ip", None)
    if not ip_query:
        fmt.error("Usage: freq net find-ip <ip-address>")
        return 1

    from freq.modules.switch_orchestration import _get_switch_hosts, _get_deployer, _vendor_for_host

    fmt.header(f"Find IP: {ip_query}", breadcrumb="FREQ > Net")
    fmt.blank()

    switches = _get_switch_hosts(cfg)
    all_matches = []

    for h in switches:
        vendor = _vendor_for_host(h)
        deployer = _get_deployer(vendor)
        if not deployer:
            continue

        entries = deployer.get_arp_table(h.ip, cfg)
        for e in entries:
            if e.get("ip") == ip_query:
                all_matches.append(
                    {
                        "switch": h.label,
                        "interface": e.get("interface", ""),
                        "mac": e.get("mac", ""),
                        "age": e.get("age", ""),
                    }
                )

    if all_matches:
        fmt.table_header(("Switch", 14), ("Interface", 14), ("MAC", 16), ("Age", 8))
        for m in all_matches:
            fmt.table_row(
                (m["switch"], 14),
                (m["interface"], 14),
                (m["mac"], 16),
                (m["age"], 8),
            )
        fmt.blank()

        # Now find which port the MAC is on
        if all_matches[0]["mac"]:
            mac = all_matches[0]["mac"]
            fmt.line(f"{fmt.C.BOLD}MAC:{fmt.C.RESET} {mac}")
            fmt.step_start(f"Finding port for {mac}")
            for h in switches:
                vendor = _vendor_for_host(h)
                deployer = _get_deployer(vendor)
                if not deployer:
                    continue
                mac_entries = deployer.get_mac_table(h.ip, cfg)
                mac_clean = mac.replace(".", "").replace(":", "").replace("-", "")
                for e in mac_entries:
                    e_clean = e.get("mac", "").replace(".", "").replace(":", "").replace("-", "")
                    if mac_clean == e_clean:
                        fmt.step_ok(f"Port: {e.get('port', '?')} on {h.label} (VLAN {e.get('vlan', '?')})")
                        break

        fmt.blank()
        fmt.success(f"IP {ip_query} found")
    else:
        fmt.warn(f"IP {ip_query} not found in ARP tables of {len(switches)} switches")

    logger.info("find_ip", ip=ip_query, found=len(all_matches))
    fmt.footer()
    return 0


def cmd_troubleshoot(cfg: FreqConfig, pack, args) -> int:
    """Automated troubleshooting — trace an IP or MAC through the network."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq net troubleshoot <ip-or-mac-or-hostname>")
        return 1

    fmt.header(f"Troubleshoot: {target}", breadcrumb="FREQ > Net")
    fmt.blank()

    # Step 1: Determine if IP, MAC, or hostname
    is_ip = bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", target))
    is_mac = bool(re.match(r"^[0-9a-fA-F:.\\-]{8,17}$", target))

    ip = None
    mac = None
    hostname = None

    if is_ip:
        ip = target
        fmt.step_ok(f"Target is IP: {ip}")
    elif is_mac:
        mac = target
        fmt.step_ok(f"Target is MAC: {mac}")
    else:
        hostname = target
        fmt.step_start(f"Resolving hostname: {hostname}")
        try:
            ip = socket.gethostbyname(hostname)
            fmt.step_ok(f"Resolved to {ip}")
        except socket.gaierror:
            fmt.step_fail(f"DNS resolution failed for {hostname}")
            fmt.footer()
            return 1

    # Step 2: Ping check (if we have IP)
    if ip:
        import subprocess

        fmt.step_start(f"Ping {ip}")
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "2", ip], capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                # Extract RTT
                m = re.search(r"time[=<](\S+)", r.stdout)
                rtt = m.group(1) if m else "?"
                fmt.step_ok(f"Reachable (RTT: {rtt}ms)")
            else:
                fmt.step_fail(f"Unreachable")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            fmt.step_fail("Ping failed")

    # Step 3: Reverse DNS (if we have IP)
    if ip and not hostname:
        fmt.step_start(f"Reverse DNS for {ip}")
        try:
            hostname = socket.gethostbyaddr(ip)[0]
            fmt.step_ok(f"Hostname: {hostname}")
        except socket.herror:
            fmt.step_warn("No reverse DNS record")

    # Step 4: Find in ARP/MAC tables
    from freq.modules.switch_orchestration import _get_switch_hosts, _get_deployer, _vendor_for_host

    switches = _get_switch_hosts(cfg)

    if ip and not mac:
        fmt.step_start(f"Searching ARP tables for {ip}")
        for h in switches:
            vendor = _vendor_for_host(h)
            deployer = _get_deployer(vendor)
            if not deployer:
                continue
            arp = deployer.get_arp_table(h.ip, cfg)
            for e in arp:
                if e.get("ip") == ip:
                    mac = e.get("mac", "")
                    fmt.step_ok(f"MAC: {mac} (via {h.label}, {e.get('interface', '?')})")
                    break
            if mac:
                break
        if not mac:
            fmt.step_warn("Not found in any ARP table")

    # Step 5: Find switch port
    if mac:
        mac_clean = mac.lower().replace(":", "").replace("-", "").replace(".", "")
        fmt.step_start(f"Finding switch port for {mac}")
        found_port = False
        for h in switches:
            vendor = _vendor_for_host(h)
            deployer = _get_deployer(vendor)
            if not deployer:
                continue
            mac_table = deployer.get_mac_table(h.ip, cfg)
            for e in mac_table:
                e_clean = e.get("mac", "").replace(".", "").replace(":", "").replace("-", "")
                if mac_clean == e_clean:
                    fmt.step_ok(f"Switch: {h.label}, Port: {e.get('port', '?')}, VLAN: {e.get('vlan', '?')}")
                    found_port = True
                    break
            if found_port:
                break
        if not found_port:
            fmt.step_warn("Not found in any MAC table")

    # Summary
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Summary{fmt.C.RESET}")
    if hostname:
        fmt.line(f"  Hostname:  {hostname}")
    if ip:
        fmt.line(f"  IP:        {ip}")
    if mac:
        fmt.line(f"  MAC:       {mac}")

    fmt.blank()
    logger.info("troubleshoot", target=target, ip=ip, mac=mac, hostname=hostname)
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — IPAM Extensions
# ---------------------------------------------------------------------------


def cmd_ip_utilization(cfg: FreqConfig, pack, args) -> int:
    """Show subnet utilization per VLAN."""
    fmt.header("IP Utilization", breadcrumb="FREQ > Net > IP")
    fmt.blank()

    # Load VLANs
    vlans = _load_vlans(cfg)
    if not vlans:
        fmt.warn("No VLANs defined in vlans.toml")
        fmt.footer()
        return 1

    # Collect used IPs
    from freq.modules.ipam import _collect_used_ips

    fmt.table_header(("VLAN", 6), ("Name", 16), ("Subnet", 20), ("Used", 6), ("Total", 6), ("Util %", 8), ("Bar", 20))
    for vname, vinfo in sorted(vlans.items(), key=lambda x: x[1].get("id", 0)):
        subnet = vinfo.get("subnet", "")
        if not subnet or "/" not in subnet:
            continue

        prefix = int(subnet.split("/")[1])
        total = 2 ** (32 - prefix) - 2 if prefix <= 30 else 1

        used_ips = _collect_used_ips(cfg, vname)
        used = len(used_ips)
        pct = int(used * 100 / total) if total > 0 else 0

        # Color by utilization
        if pct > 90:
            color = fmt.C.RED
        elif pct > 70:
            color = fmt.C.YELLOW
        else:
            color = fmt.C.GREEN

        bar_width = 18
        filled = int(bar_width * pct / 100)
        bar = f"{color}{'█' * filled}{'░' * (bar_width - filled)}{fmt.C.RESET}"

        fmt.table_row(
            (str(vinfo.get("id", "?")), 6),
            (vname, 16),
            (subnet, 20),
            (str(used), 6),
            (str(total), 6),
            (f"{color}{pct}%{fmt.C.RESET}", 8),
            (bar, 20),
        )

    fmt.blank()
    logger.info("ip_utilization")
    fmt.footer()
    return 0


def cmd_ip_conflict(cfg: FreqConfig, pack, args) -> int:
    """Detect IP conflicts by checking ARP tables for duplicate IPs."""
    fmt.header("IP Conflict Detection", breadcrumb="FREQ > Net > IP")
    fmt.blank()

    from freq.modules.switch_orchestration import _get_switch_hosts, _get_deployer, _vendor_for_host

    switches = _get_switch_hosts(cfg)
    if not switches:
        fmt.error("No switches in hosts.conf")
        return 1

    fmt.step_start("Scanning ARP tables across all switches")

    # Collect all ARP entries
    ip_to_macs = {}
    for h in switches:
        vendor = _vendor_for_host(h)
        deployer = _get_deployer(vendor)
        if not deployer:
            continue
        arp = deployer.get_arp_table(h.ip, cfg)
        for e in arp:
            ip_addr = e.get("ip", "")
            mac_addr = e.get("mac", "")
            if ip_addr and mac_addr:
                ip_to_macs.setdefault(ip_addr, set()).add(mac_addr)

    # Find IPs with multiple MACs
    conflicts = {ip: macs for ip, macs in ip_to_macs.items() if len(macs) > 1}

    if conflicts:
        fmt.step_warn(f"{len(conflicts)} conflict(s) detected")
        fmt.blank()

        fmt.table_header(("IP Address", 16), ("MAC Addresses", 40))
        for ip_addr, macs in sorted(conflicts.items()):
            fmt.table_row(
                (ip_addr, 16),
                (", ".join(sorted(macs)), 40),
            )

        fmt.blank()
        fmt.warn(f"{len(conflicts)} IP(s) have multiple MAC addresses — possible conflicts")
    else:
        fmt.step_ok(f"No conflicts — {len(ip_to_macs)} unique IPs checked")

    fmt.blank()
    logger.info("ip_conflict", ips_checked=len(ip_to_macs), conflicts=len(conflicts))
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_vlans(cfg):
    """Load VLAN definitions from vlans.toml."""
    import os

    vlans_path = os.path.join(cfg.conf_dir, "vlans.toml")
    if not os.path.exists(vlans_path):
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(vlans_path, "rb") as f:
        data = tomllib.load(f)
    return data.get("vlan", {})
