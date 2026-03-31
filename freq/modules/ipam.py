"""IPAM — IP Address Management for FREQ.

Scans hosts, VMs, and VLAN configs to track used IPs and find available ones.
Pure arithmetic on existing data — no external IPAM service needed.
"""
import ipaddress
import os

from freq.core.config import FreqConfig
from freq.core import fmt
from freq.core import log as logger


def _parse_subnet(subnet_str: str):
    """Parse a CIDR subnet string into an IPv4Network."""
    try:
        return ipaddress.IPv4Network(subnet_str, strict=False)
    except (ValueError, TypeError):
        return None


def _collect_used_ips(cfg: FreqConfig, vlan_name: str = "") -> set:
    """Collect all used IPs from hosts.toml and PVE VM configs.

    Returns a set of IPv4Address objects.
    """
    used = set()

    # 1. From hosts.toml
    for host in cfg.hosts:
        try:
            addr = ipaddress.IPv4Address(host.ip)
            used.add(addr)
        except (ValueError, TypeError):
            pass
        # Also check all_ips
        for extra_ip in getattr(host, "all_ips", []):
            try:
                # Strip CIDR if present
                ip_str = extra_ip.split("/")[0]
                used.add(ipaddress.IPv4Address(ip_str))
            except (ValueError, TypeError):
                pass

    # 2. From PVE VM configs (network interfaces)
    from freq.core.ssh import run as ssh_run
    for node_ip in cfg.pve_nodes:
        r = ssh_run(
            host=node_ip,
            command="sudo qm list 2>/dev/null | tail -n +2 | awk '{print $1}'",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode != 0:
            continue

        vmids = [v.strip() for v in r.stdout.strip().split("\n") if v.strip()]
        if not vmids:
            continue

        # Batch query configs for IPs
        vmid_list = " ".join(vmids[:200])  # Cap for safety
        r = ssh_run(
            host=node_ip,
            command=f"for v in {vmid_list}; do sudo qm config $v 2>/dev/null | grep -oP 'ip=\\K[0-9./]+'; done",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=60,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().split("\n"):
                line = line.strip()
                if not line:
                    continue
                ip_str = line.split("/")[0]
                try:
                    used.add(ipaddress.IPv4Address(ip_str))
                except (ValueError, TypeError):
                    pass

    # 3. Infrastructure IPs from config
    for attr in ("vm_gateway", "vm_nameserver", "truenas_ip", "pfsense_ip",
                 "switch_ip", "docker_dev_ip"):
        val = getattr(cfg, attr, "")
        if val:
            try:
                used.add(ipaddress.IPv4Address(val))
            except (ValueError, TypeError):
                pass

    # 4. VLAN gateways
    for vlan in cfg.vlans:
        if vlan.gateway:
            try:
                used.add(ipaddress.IPv4Address(vlan.gateway))
            except (ValueError, TypeError):
                pass

    return used


def _find_vlan(cfg: FreqConfig, vlan_name: str):
    """Find a VLAN by name (case-insensitive)."""
    for vlan in cfg.vlans:
        if vlan.name.lower() == vlan_name.lower():
            return vlan
    return None


def _next_available(subnet, used_ips: set, count: int = 1, start_offset: int = 10) -> list:
    """Find the next N available IPs in a subnet.

    Skips:
      - Network address (.0)
      - Broadcast address (.255 for /24)
      - First start_offset addresses (reserved for gateways/infra)
      - Any IP in used_ips set
    """
    available = []
    for addr in subnet.hosts():
        # Skip first N addresses (reserved range)
        host_num = int(addr) - int(subnet.network_address)
        if host_num < start_offset:
            continue

        if addr not in used_ips:
            available.append(addr)
            if len(available) >= count:
                break

    return available


def _list_ips(cfg: FreqConfig, vlan_name: str = "") -> list:
    """List all used IPs, optionally filtered by VLAN subnet."""
    used = _collect_used_ips(cfg)
    result = []

    if vlan_name:
        vlan = _find_vlan(cfg, vlan_name)
        if not vlan or not vlan.subnet:
            return []
        subnet = _parse_subnet(vlan.subnet)
        if not subnet:
            return []
        # Filter to IPs in this subnet
        for ip in sorted(used):
            if ip in subnet:
                result.append(str(ip))
    else:
        result = [str(ip) for ip in sorted(used)]

    return result


def _check_ip(cfg: FreqConfig, ip_str: str) -> dict:
    """Check if a specific IP is in use.

    Returns: {"ip": str, "in_use": bool, "owner": str}
    """
    try:
        target = ipaddress.IPv4Address(ip_str.split("/")[0])
    except (ValueError, TypeError):
        return {"ip": ip_str, "in_use": False, "owner": "", "error": "Invalid IP"}

    # Check hosts
    for host in cfg.hosts:
        try:
            if ipaddress.IPv4Address(host.ip) == target:
                return {"ip": str(target), "in_use": True, "owner": host.label}
        except (ValueError, TypeError):
            pass

    # Check infrastructure
    for attr, label in [("vm_gateway", "gateway"), ("truenas_ip", "truenas"),
                        ("pfsense_ip", "pfsense"), ("switch_ip", "switch")]:
        val = getattr(cfg, attr, "")
        if val:
            try:
                if ipaddress.IPv4Address(val) == target:
                    return {"ip": str(target), "in_use": True, "owner": label}
            except (ValueError, TypeError):
                pass

    return {"ip": str(target), "in_use": False, "owner": ""}


def cmd_ip(cfg: FreqConfig, pack, args) -> int:
    """IPAM command handler — next, list, check."""
    action = getattr(args, "action", "next")
    vlan_name = getattr(args, "vlan", "")
    json_mode = getattr(args, "json", False)

    if action == "next":
        return _cmd_ip_next(cfg, vlan_name, json_mode, args)
    elif action == "list":
        return _cmd_ip_list(cfg, vlan_name, json_mode)
    elif action == "check":
        return _cmd_ip_check(cfg, args, json_mode)
    else:
        fmt.error(f"Unknown action: {action}")
        return 1


def _cmd_ip_next(cfg: FreqConfig, vlan_name: str, json_mode: bool, args) -> int:
    """Find next available IP in a VLAN."""
    fmt.header("Next Available IP")
    fmt.blank()

    if not vlan_name:
        fmt.error("Specify a VLAN: freq ip next --vlan <name>")
        fmt.blank()
        if cfg.vlans:
            fmt.line(f"  Available VLANs:")
            for v in cfg.vlans:
                fmt.line(f"    {fmt.C.CYAN}{v.name}{fmt.C.RESET} ({v.subnet})")
        fmt.blank()
        fmt.footer()
        return 1

    vlan = _find_vlan(cfg, vlan_name)
    if not vlan:
        fmt.error(f"VLAN '{vlan_name}' not found")
        fmt.blank()
        if cfg.vlans:
            fmt.line(f"  Available VLANs:")
            for v in cfg.vlans:
                fmt.line(f"    {fmt.C.CYAN}{v.name}{fmt.C.RESET} ({v.subnet})")
        fmt.footer()
        return 1

    subnet = _parse_subnet(vlan.subnet)
    if not subnet:
        fmt.error(f"Invalid subnet: {vlan.subnet}")
        fmt.footer()
        return 1

    count = getattr(args, "count", 1) or 1

    fmt.step_start(f"Scanning {vlan.name} ({vlan.subnet})")
    used = _collect_used_ips(cfg)
    used_in_subnet = {ip for ip in used if ip in subnet}
    fmt.step_ok(f"Found {len(used_in_subnet)} used IP(s) in subnet")

    available = _next_available(subnet, used, count=count)

    if not available:
        fmt.blank()
        fmt.error(f"No available IPs in {vlan.subnet}")
        fmt.footer()
        return 1

    fmt.blank()
    total_hosts = subnet.num_addresses - 2  # Exclude network + broadcast
    free_count = total_hosts - len(used_in_subnet)

    if json_mode:
        import json
        print(json.dumps({
            "vlan": vlan.name,
            "subnet": vlan.subnet,
            "next": [str(ip) for ip in available],
            "used": len(used_in_subnet),
            "free": free_count,
            "total": total_hosts,
        }))
    else:
        for ip in available:
            prefix_len = subnet.prefixlen
            fmt.line(f"  {fmt.C.GREEN}{fmt.C.BOLD}{ip}/{prefix_len}{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  VLAN:  {vlan.name} (ID {vlan.id})")
        fmt.line(f"  Used:  {len(used_in_subnet)}/{total_hosts}")
        fmt.line(f"  Free:  {free_count}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_ip_list(cfg: FreqConfig, vlan_name: str, json_mode: bool) -> int:
    """List used IPs, optionally filtered by VLAN."""
    fmt.header("IP Address List")
    fmt.blank()

    fmt.step_start("Collecting used IPs")
    used = _collect_used_ips(cfg)
    fmt.step_ok(f"Found {len(used)} used IP(s)")

    fmt.blank()

    if vlan_name:
        vlan = _find_vlan(cfg, vlan_name)
        if not vlan:
            fmt.error(f"VLAN '{vlan_name}' not found")
            fmt.footer()
            return 1

        subnet = _parse_subnet(vlan.subnet)
        if not subnet:
            fmt.error(f"Invalid subnet: {vlan.subnet}")
            fmt.footer()
            return 1

        fmt.line(f"  {fmt.C.BOLD}{vlan.name}{fmt.C.RESET} ({vlan.subnet})")
        fmt.blank()

        # Show IPs in this subnet with owner info
        for ip in sorted(used):
            if ip in subnet:
                owner = ""
                for host in cfg.hosts:
                    try:
                        if ipaddress.IPv4Address(host.ip) == ip:
                            owner = host.label
                            break
                    except (ValueError, TypeError):
                        pass
                if owner:
                    fmt.line(f"  {str(ip):<18} {fmt.C.DIM}{owner}{fmt.C.RESET}")
                else:
                    fmt.line(f"  {str(ip):<18} {fmt.C.DIM}(VM/infra){fmt.C.RESET}")
    else:
        # Show all VLANs
        if cfg.vlans:
            for vlan in cfg.vlans:
                subnet = _parse_subnet(vlan.subnet)
                if not subnet:
                    continue
                count = sum(1 for ip in used if ip in subnet)
                fmt.line(f"  {fmt.C.BOLD}{vlan.name:<12}{fmt.C.RESET} "
                         f"{vlan.subnet:<20} {count} used")
        fmt.blank()
        fmt.line(f"  Total: {len(used)} IP(s) tracked")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_ip_check(cfg: FreqConfig, args, json_mode: bool) -> int:
    """Check if a specific IP is in use."""
    fmt.header("IP Check")
    fmt.blank()

    target = getattr(args, "target", "")
    if not target:
        fmt.error("Specify an IP: freq ip check <ip>")
        fmt.footer()
        return 1

    result = _check_ip(cfg, target)

    if json_mode:
        import json
        print(json.dumps(result))
    else:
        if result.get("error"):
            fmt.error(result["error"])
        elif result["in_use"]:
            fmt.line(f"  {fmt.C.RED}{result['ip']}{fmt.C.RESET} — "
                     f"{fmt.C.BOLD}IN USE{fmt.C.RESET} by {result['owner']}")
        else:
            fmt.line(f"  {fmt.C.GREEN}{result['ip']}{fmt.C.RESET} — "
                     f"{fmt.C.GREEN}AVAILABLE{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0
