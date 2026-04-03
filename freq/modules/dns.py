"""DNS record tracking and validation for FREQ.

Domain: freq dns <scan|check|list>

Forward and reverse DNS validation across the fleet. Finds mismatches,
missing PTR records, and stale entries. Catches DNS problems before they
cause mysterious authentication failures or broken services.

Replaces: NetBox DNS tracking ($7.5K/yr), manual dig commands, spreadsheets

Architecture:
    - Forward lookups via socket.getaddrinfo (stdlib, no dig dependency)
    - Reverse lookups via socket.gethostbyaddr for PTR validation
    - Fleet host IPs cross-referenced against DNS for completeness
    - Inventory persisted in conf/dns/dns-inventory.json

Design decisions:
    - Uses stdlib socket, not dig/nslookup. Works on any platform without
      bind-utils installed. DNS resolution uses the host's resolver config.
"""
import json
import os
import socket
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many

# Storage
DNS_DIR = "dns"
DNS_FILE = "dns-inventory.json"
DNS_CMD_TIMEOUT = 10


def _dns_dir(cfg: FreqConfig) -> str:
    """Get or create DNS directory."""
    path = os.path.join(cfg.conf_dir, DNS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_dns_data(cfg: FreqConfig) -> dict:
    """Load DNS inventory from disk."""
    filepath = os.path.join(_dns_dir(cfg), DNS_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"records": [], "scan_time": ""}


def _save_dns_data(cfg: FreqConfig, data: dict):
    """Save DNS inventory to disk."""
    filepath = os.path.join(_dns_dir(cfg), DNS_FILE)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _forward_lookup(hostname: str) -> list:
    """Forward DNS lookup — hostname to IPs."""
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_INET)
        return list(set(r[4][0] for r in results))
    except (socket.gaierror, OSError):
        return []


def _reverse_lookup(ip: str) -> str:
    """Reverse DNS lookup — IP to hostname."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        return hostname
    except (socket.herror, socket.gaierror, OSError):
        return ""


def _gather_dns_info(cfg: FreqConfig) -> list:
    """Gather DNS info from all fleet hosts."""
    hosts = cfg.hosts
    if not hosts:
        return []

    # Get hostname and configured DNS from each host
    command = (
        'echo "HOSTNAME=$(hostname -f 2>/dev/null || hostname)"; '
        'echo "SHORT=$(hostname -s 2>/dev/null || hostname)"; '
        "echo \"DNS=$(cat /etc/resolv.conf 2>/dev/null | grep '^nameserver' | awk '{print $2}' | tr '\\n' ',' | sed 's/,$//')\"; "
        "echo \"SEARCH=$(cat /etc/resolv.conf 2>/dev/null | grep '^search\\|^domain' | awk '{$1=\"\"; print}' | sed 's/^ *//')\"; "
    )

    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=DNS_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    records = []
    for h in hosts:
        r = results.get(h.label)
        entry = {
            "label": h.label,
            "ip": h.ip,
            "hostname": "",
            "short": "",
            "dns_servers": "",
            "search_domain": "",
            "forward_ips": [],
            "reverse_hostname": "",
            "forward_match": False,
            "reverse_match": False,
            "issues": [],
        }

        if r and r.returncode == 0:
            # Parse key=value output
            for line in r.stdout.strip().split("\n"):
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip().lower()
                    value = value.strip()
                    if key == "hostname":
                        entry["hostname"] = value
                    elif key == "short":
                        entry["short"] = value
                    elif key == "dns":
                        entry["dns_servers"] = value
                    elif key == "search":
                        entry["search_domain"] = value

        # Forward lookup
        if entry["hostname"]:
            entry["forward_ips"] = _forward_lookup(entry["hostname"])
            if h.ip in entry["forward_ips"]:
                entry["forward_match"] = True
            elif entry["forward_ips"]:
                entry["issues"].append(f"Forward DNS resolves to {entry['forward_ips']} not {h.ip}")
            else:
                entry["issues"].append("Forward DNS lookup failed")

        # Reverse lookup
        entry["reverse_hostname"] = _reverse_lookup(h.ip)
        if entry["reverse_hostname"]:
            if (entry["reverse_hostname"] == entry["hostname"] or
                    entry["reverse_hostname"] == entry["short"]):
                entry["reverse_match"] = True
            else:
                entry["issues"].append(
                    f"Reverse DNS returns '{entry['reverse_hostname']}' not '{entry['hostname']}'")
        else:
            entry["issues"].append("No PTR record (reverse DNS failed)")

        records.append(entry)

    return records


def cmd_dns(cfg: FreqConfig, pack, args) -> int:
    """DNS record management."""
    action = getattr(args, "action", None) or "scan"

    if action == "scan":
        return _cmd_scan(cfg, args)
    elif action == "check":
        return _cmd_check(cfg, args)
    elif action == "list":
        return _cmd_list(cfg, args)

    fmt.error(f"Unknown dns action: {action}")
    fmt.info("Available: scan, check, list")
    return 1


def _cmd_scan(cfg: FreqConfig, args) -> int:
    """Scan fleet DNS records."""
    fmt.header("DNS Scan")
    fmt.blank()

    fmt.step_start("Gathering DNS info from fleet")
    records = _gather_dns_info(cfg)
    fmt.step_ok(f"Scanned {len(records)} hosts")
    fmt.blank()

    # Save
    dns_data = {
        "records": records,
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total": len(records),
    }
    _save_dns_data(cfg, dns_data)

    if not records:
        fmt.line(f"  {fmt.C.DIM}No hosts to scan.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Display
    fmt.table_header(
        ("HOST", 14), ("IP", 16), ("HOSTNAME", 22),
        ("FWD", 5), ("REV", 5), ("ISSUES", 24),
    )

    issues_total = 0
    for rec in records:
        fwd = f"{fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET}" if rec["forward_match"] else f"{fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET}"
        rev = f"{fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET}" if rec["reverse_match"] else f"{fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET}"
        issues = "; ".join(rec["issues"])[:24] if rec["issues"] else ""
        issues_total += len(rec["issues"])

        fmt.table_row(
            (f"{fmt.C.BOLD}{rec['label']}{fmt.C.RESET}", 14),
            (rec["ip"], 16),
            (rec["hostname"][:22], 22),
            (fwd, 5),
            (rev, 5),
            (f"{fmt.C.YELLOW}{issues}{fmt.C.RESET}" if issues else "", 24),
        )

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()

    fwd_ok = sum(1 for r in records if r["forward_match"])
    rev_ok = sum(1 for r in records if r["reverse_match"])

    fmt.line(f"  Forward DNS: {fwd_ok}/{len(records)} match")
    fmt.line(f"  Reverse DNS: {rev_ok}/{len(records)} match")

    if issues_total == 0:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} All DNS records clean.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} {issues_total} issue(s) found.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 1 if issues_total > 0 else 0


def _cmd_check(cfg: FreqConfig, args) -> int:
    """Check DNS for a single host/IP."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq dns check <hostname-or-ip>")
        return 1

    fmt.header(f"DNS Check: {target}")
    fmt.blank()

    # Determine if it's an IP or hostname
    is_ip = all(c.isdigit() or c == '.' for c in target)

    if is_ip:
        fmt.step_start(f"Reverse lookup: {target}")
        hostname = _reverse_lookup(target)
        if hostname:
            fmt.step_ok(f"{target} → {hostname}")
            fmt.step_start(f"Forward lookup: {hostname}")
            ips = _forward_lookup(hostname)
            if ips:
                fmt.step_ok(f"{hostname} → {', '.join(ips)}")
                if target in ips:
                    fmt.blank()
                    fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} Round-trip DNS matches.{fmt.C.RESET}")
                else:
                    fmt.blank()
                    fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} Forward lookup doesn't include {target}{fmt.C.RESET}")
            else:
                fmt.step_fail(f"Forward lookup failed for {hostname}")
        else:
            fmt.step_fail(f"No PTR record for {target}")
    else:
        fmt.step_start(f"Forward lookup: {target}")
        ips = _forward_lookup(target)
        if ips:
            fmt.step_ok(f"{target} → {', '.join(ips)}")
            for ip in ips:
                fmt.step_start(f"Reverse lookup: {ip}")
                hostname = _reverse_lookup(ip)
                if hostname:
                    fmt.step_ok(f"{ip} → {hostname}")
                else:
                    fmt.step_fail(f"No PTR record for {ip}")
        else:
            fmt.step_fail(f"Forward lookup failed for {target}")

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List last scan results."""
    data = _load_dns_data(cfg)
    if not data.get("records"):
        fmt.error("No DNS data. Run: freq dns scan")
        return 1

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return 0

    fmt.header(f"DNS Inventory (from {data.get('scan_time', '?')[:19]})")
    fmt.blank()
    fmt.line(f"  {len(data['records'])} records on file")
    fmt.line(f"  {fmt.C.DIM}Run freq dns scan to refresh.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
