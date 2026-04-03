"""Firewall management for FREQ — pfSense/OPNsense orchestration.

Domain: freq fw <action>
What: Manage firewall rules, NAT, DHCP leases, gateways, states, and
      system status. Graduated from infrastructure.py _device_cmd() to
      full deployer-backed vendor-agnostic commands.
Replaces: pfSense WebGUI, manual SSH sessions, OPNsense web interface
Architecture:
    - SSH-based commands via freq/core/ssh.py (htype=pfsense)
    - Future: REST API via urllib.request for pfrest/OPNsense API
    - Rule/config backups stored in conf/firewall/
    - Vendor detection from host type in hosts.conf
Design decisions:
    - SSH first, REST later. SSH works on every pfSense/OPNsense box.
    - Rule export/import as XML fragments for backup/restore.
    - DHCP lease parsing from dhcpd.leases file via SSH.
    - Gateway status via pfctl and netstat — no API needed.
"""
import os
import re
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run
from freq.core import log as logger


# ---------------------------------------------------------------------------
# SSH Helper
# ---------------------------------------------------------------------------

def _fw_ssh(ip, cmd, cfg, timeout=15):
    """Run a command on pfSense/OPNsense via SSH."""
    r = ssh_run(
        host=ip, command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pfsense", use_sudo=False,
    )
    return r.stdout or "", r.returncode == 0


def _get_fw_ip(cfg):
    """Get firewall IP from config or hosts.conf."""
    if cfg.pfsense_ip:
        return cfg.pfsense_ip
    for h in cfg.hosts:
        if h.htype in ("pfsense", "opnsense"):
            return h.ip
    return None


def _fw_data_dir(cfg):
    """Return firewall data directory."""
    path = os.path.join(cfg.conf_dir, "firewall")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Commands — System Status
# ---------------------------------------------------------------------------

def cmd_fw_status(cfg: FreqConfig, pack, args) -> int:
    """Show firewall system status."""
    ip = _get_fw_ip(cfg)
    if not ip:
        fmt.error("No firewall configured. Set pfsense_ip in freq.toml")
        return 1

    fmt.header("Firewall Status", breadcrumb="FREQ > Firewall")
    fmt.blank()

    # System info
    out, ok = _fw_ssh(ip, "uname -a", cfg)
    if ok:
        fmt.line(f"{fmt.C.BOLD}System:{fmt.C.RESET} {out.strip()}")
    else:
        fmt.warn(f"Cannot reach firewall at {ip}")
        fmt.footer()
        return 1

    # Uptime
    out, ok = _fw_ssh(ip, "uptime", cfg)
    if ok:
        fmt.line(f"{fmt.C.BOLD}Uptime:{fmt.C.RESET} {out.strip()}")

    # pfctl info
    out, ok = _fw_ssh(ip, "pfctl -s info 2>/dev/null | head -8", cfg)
    if ok and out.strip():
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Packet Filter:{fmt.C.RESET}")
        for line in out.strip().splitlines():
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")

    # State table count
    out, ok = _fw_ssh(ip, "pfctl -ss 2>/dev/null | wc -l", cfg)
    if ok:
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Active States:{fmt.C.RESET} {out.strip()}")

    fmt.blank()
    logger.info("fw_status", ip=ip)
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — Rules
# ---------------------------------------------------------------------------

def cmd_fw_rules(cfg: FreqConfig, pack, args) -> int:
    """List, export, or audit firewall rules."""
    action = getattr(args, "action", "list")
    ip = _get_fw_ip(cfg)
    if not ip:
        fmt.error("No firewall configured")
        return 1

    if action == "export":
        return _fw_rules_export(cfg, ip)
    elif action == "audit":
        return _fw_rules_audit(cfg, ip)

    # Default: list
    fmt.header("Firewall Rules", breadcrumb="FREQ > Firewall")
    fmt.blank()

    out, ok = _fw_ssh(ip, "pfctl -sr 2>/dev/null", cfg, timeout=20)
    if not ok:
        fmt.warn(f"Could not retrieve rules from {ip}")
        fmt.footer()
        return 1

    rules = out.strip().splitlines()
    for i, rule in enumerate(rules, 1):
        # Color by action
        if rule.strip().startswith("pass"):
            color = fmt.C.GREEN
        elif rule.strip().startswith("block"):
            color = fmt.C.RED
        else:
            color = fmt.C.DIM
        fmt.line(f"  {fmt.C.DIM}{i:>3}{fmt.C.RESET}  {color}{rule}{fmt.C.RESET}")

    fmt.blank()
    fmt.info(f"{len(rules)} active rules")
    logger.info("fw_rules_list", ip=ip, count=len(rules))
    fmt.footer()
    return 0


def _fw_rules_export(cfg, ip):
    """Export firewall rules to a backup file."""
    fmt.header("Export Firewall Rules", breadcrumb="FREQ > Firewall")
    fmt.blank()

    out, ok = _fw_ssh(ip, "pfctl -sr 2>/dev/null", cfg, timeout=20)
    if not ok:
        fmt.warn("Could not retrieve rules")
        fmt.footer()
        return 1

    ts = time.strftime("%Y%m%d-%H%M%S")
    filepath = os.path.join(_fw_data_dir(cfg), f"rules-{ts}.txt")
    with open(filepath, "w") as f:
        f.write(out)
    fmt.success(f"Rules exported to {filepath}")
    fmt.info(f"{len(out.splitlines())} rules saved")
    fmt.footer()
    return 0


def _fw_rules_audit(cfg, ip):
    """Audit firewall rules for common issues."""
    fmt.header("Firewall Rules Audit", breadcrumb="FREQ > Firewall")
    fmt.blank()

    out, ok = _fw_ssh(ip, "pfctl -sr 2>/dev/null", cfg, timeout=20)
    if not ok:
        fmt.warn("Could not retrieve rules")
        fmt.footer()
        return 1

    rules = out.strip().splitlines()
    issues = []

    for i, rule in enumerate(rules, 1):
        # Check for overly broad rules
        if "any" in rule and "pass" in rule and "quick" in rule:
            issues.append((i, "Broad pass rule with 'any' and 'quick'", rule.strip()))
        # Check for rules without logging
        if "pass" in rule and "log" not in rule and "quick" in rule:
            issues.append((i, "Pass rule without logging", rule.strip()))

    if issues:
        fmt.table_header(("Rule #", 8), ("Issue", 40), ("Rule", 50))
        for num, issue, rule_text in issues[:20]:
            fmt.table_row(
                (str(num), 8),
                (f"{fmt.C.YELLOW}{issue}{fmt.C.RESET}", 40),
                (f"{fmt.C.DIM}{rule_text[:50]}{fmt.C.RESET}", 50),
            )
        fmt.blank()
        fmt.warn(f"{len(issues)} potential issue(s) found")
    else:
        fmt.success("No obvious rule issues found")

    fmt.blank()
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — NAT
# ---------------------------------------------------------------------------

def cmd_fw_nat(cfg: FreqConfig, pack, args) -> int:
    """List NAT/port forward rules."""
    ip = _get_fw_ip(cfg)
    if not ip:
        fmt.error("No firewall configured")
        return 1

    fmt.header("NAT Rules", breadcrumb="FREQ > Firewall")
    fmt.blank()

    out, ok = _fw_ssh(ip, "pfctl -sn 2>/dev/null", cfg)
    if not ok:
        fmt.warn(f"Could not retrieve NAT rules from {ip}")
        fmt.footer()
        return 1

    rules = out.strip().splitlines()
    for i, rule in enumerate(rules, 1):
        fmt.line(f"  {fmt.C.DIM}{i:>3}{fmt.C.RESET}  {rule}")

    fmt.blank()
    fmt.info(f"{len(rules)} NAT rules")
    logger.info("fw_nat", ip=ip, count=len(rules))
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — States
# ---------------------------------------------------------------------------

def cmd_fw_states(cfg: FreqConfig, pack, args) -> int:
    """Show active connection states."""
    ip = _get_fw_ip(cfg)
    if not ip:
        fmt.error("No firewall configured")
        return 1

    limit = getattr(args, "limit", 20)

    fmt.header("Active States", breadcrumb="FREQ > Firewall")
    fmt.blank()

    # Get count
    count_out, ok = _fw_ssh(ip, "pfctl -ss 2>/dev/null | wc -l", cfg)
    total = int(count_out.strip()) if ok and count_out.strip().isdigit() else 0

    # Get top states
    out, ok = _fw_ssh(ip, f"pfctl -ss 2>/dev/null | head -{limit}", cfg)
    if ok and out.strip():
        for line in out.strip().splitlines():
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    else:
        fmt.warn("No states or pfctl unavailable")

    fmt.blank()
    fmt.info(f"Showing {min(limit, total)}/{total} active states")
    logger.info("fw_states", ip=ip, total=total)
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — Interfaces & Gateways
# ---------------------------------------------------------------------------

def cmd_fw_interfaces(cfg: FreqConfig, pack, args) -> int:
    """Show firewall network interfaces."""
    ip = _get_fw_ip(cfg)
    if not ip:
        fmt.error("No firewall configured")
        return 1

    fmt.header("Firewall Interfaces", breadcrumb="FREQ > Firewall")
    fmt.blank()

    out, ok = _fw_ssh(ip, "ifconfig -a | grep -E '^[a-z]|inet '", cfg)
    if ok and out.strip():
        for line in out.strip().splitlines():
            if not line.startswith("\t") and not line.startswith(" "):
                fmt.line(f"  {fmt.C.BOLD}{line}{fmt.C.RESET}")
            else:
                fmt.line(f"    {fmt.C.DIM}{line.strip()}{fmt.C.RESET}")
    else:
        fmt.warn("Could not retrieve interfaces")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_fw_gateways(cfg: FreqConfig, pack, args) -> int:
    """Show gateway status and routing table."""
    ip = _get_fw_ip(cfg)
    if not ip:
        fmt.error("No firewall configured")
        return 1

    fmt.header("Gateways", breadcrumb="FREQ > Firewall")
    fmt.blank()

    out, ok = _fw_ssh(ip, "netstat -rn | head -20", cfg)
    if ok and out.strip():
        for line in out.strip().splitlines():
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    else:
        fmt.warn("Could not retrieve routing table")

    fmt.blank()
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — DHCP
# ---------------------------------------------------------------------------

def cmd_fw_dhcp(cfg: FreqConfig, pack, args) -> int:
    """Show DHCP leases from pfSense."""
    ip = _get_fw_ip(cfg)
    if not ip:
        fmt.error("No firewall configured")
        return 1

    action = getattr(args, "action", "leases")

    fmt.header("DHCP Leases", breadcrumb="FREQ > Firewall")
    fmt.blank()

    out, ok = _fw_ssh(ip, "cat /var/dhcpd/var/db/dhcpd.leases 2>/dev/null", cfg, timeout=10)
    if not ok or not out.strip():
        fmt.warn("Could not read DHCP leases (file may not exist or dhcpd not running)")
        fmt.footer()
        return 1

    leases = _parse_dhcp_leases(out)

    if not leases:
        fmt.info("No active DHCP leases")
        fmt.footer()
        return 0

    fmt.table_header(("IP Address", 16), ("MAC Address", 18), ("Hostname", 20), ("Expires", 20))
    for lease in leases:
        fmt.table_row(
            (lease.get("ip", ""), 16),
            (lease.get("mac", ""), 18),
            (lease.get("hostname", ""), 20),
            (lease.get("ends", ""), 20),
        )

    fmt.blank()
    fmt.info(f"{len(leases)} active lease(s)")
    logger.info("fw_dhcp", ip=ip, leases=len(leases))
    fmt.footer()
    return 0


def _parse_dhcp_leases(text):
    """Parse ISC dhcpd.leases format into list of dicts."""
    leases = []
    current = {}

    for line in text.splitlines():
        line = line.strip()

        if line.startswith("lease ") and "{" in line:
            m = re.match(r"lease\s+([\d.]+)\s*\{", line)
            if m:
                current = {"ip": m.group(1)}

        elif line.startswith("hardware ethernet") and current:
            m = re.match(r"hardware ethernet\s+([\da-fA-F:]+)", line)
            if m:
                current["mac"] = m.group(1)

        elif line.startswith("client-hostname") and current:
            m = re.match(r'client-hostname\s+"([^"]+)"', line)
            if m:
                current["hostname"] = m.group(1)

        elif line.startswith("ends ") and current:
            m = re.match(r"ends\s+\d+\s+(.+);", line)
            if m:
                current["ends"] = m.group(1)

        elif line == "}" and current:
            if current.get("ip"):
                leases.append(current)
            current = {}

    return leases
