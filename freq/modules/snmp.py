"""SNMP polling for FREQ — device monitoring without agents.

Domain: freq net snmp <action> [target]
What: Poll network devices via SNMP for interface stats, CPU, memory,
      uptime, and errors. Shells out to snmpget/snmpwalk from net-snmp
      package — zero Python dependencies.
Replaces: PRTG, LibreNMS, Zabbix SNMP monitoring, SolarWinds NPM
Architecture:
    - Shells to snmpget/snmpwalk via subprocess (same pattern as ssh.py)
    - Parses SNMP output into structured dicts
    - Poll results stored as JSON in conf/snmp/
    - Supports SNMPv2c (community string) and SNMPv3 (user/auth/priv)
    - Community string from freq.toml [snmp] section or --community flag
Design decisions:
    - Shell out to net-snmp tools, not PySNMP. Zero dependencies.
    - Store poll snapshots for trending — same pattern as netmon.py.
    - OID constants defined here, not in config. Standard MIBs only.
"""

import json
import os
import re
import subprocess
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Standard OIDs (IF-MIB, HOST-RESOURCES-MIB, SNMPv2-MIB)
# ---------------------------------------------------------------------------

OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
OID_SYS_LOCATION = "1.3.6.1.2.1.1.6.0"

# IF-MIB interface table
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"  # ifDescr
OID_IF_TYPE = "1.3.6.1.2.1.2.2.1.3"  # ifType
OID_IF_SPEED = "1.3.6.1.2.1.2.2.1.5"  # ifSpeed
OID_IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"  # ifAdminStatus
OID_IF_OPER = "1.3.6.1.2.1.2.2.1.8"  # ifOperStatus
OID_IF_IN_OCTETS = "1.3.6.1.2.1.2.2.1.10"  # ifInOctets
OID_IF_OUT_OCTETS = "1.3.6.1.2.1.2.2.1.16"  # ifOutOctets
OID_IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"  # ifInErrors
OID_IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"  # ifOutErrors

# HOST-RESOURCES-MIB (for Linux/network device CPU/memory)
OID_HR_PROC_LOAD = "1.3.6.1.2.1.25.3.3.1.2"  # hrProcessorLoad
OID_HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"  # hrStorageDescr
OID_HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"  # hrStorageSize
OID_HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"  # hrStorageUsed
OID_HR_STORAGE_UNITS = "1.3.6.1.2.1.25.2.3.1.4"  # hrStorageAllocationUnits

# ENTITY-MIB hardware identity.
OID_ENT_PHYSICAL_NAME = "1.3.6.1.2.1.47.1.1.1.1.7"
OID_ENT_PHYSICAL_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
OID_ENT_PHYSICAL_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13"

SNMP_DATA_DIR = "snmp"
DEFAULT_COMMUNITY = "public"


# ---------------------------------------------------------------------------
# SNMP Transport — shell to snmpget/snmpwalk
# ---------------------------------------------------------------------------


def _snmp_auth_args(community=DEFAULT_COMMUNITY, version="2c", auth=None):
    auth = auth or {}
    version = str(auth.get("version") or version or "2c").lower()
    if version in ("3", "v3", "snmpv3"):
        user = auth.get("user") or auth.get("username") or ""
        auth_password = auth.get("auth_password") or auth.get("password") or ""
        priv_password = auth.get("priv_password") or auth_password
        if not user or not auth_password or not priv_password:
            return []
        return [
            "-v", "3",
            "-l", auth.get("security_level") or "authPriv",
            "-u", user,
            "-a", auth.get("auth_protocol") or "SHA",
            "-A", auth_password,
            "-x", auth.get("priv_protocol") or "AES",
            "-X", priv_password,
        ]
    return ["-v", version, "-c", community]


def _snmp_get(ip, oid, community=DEFAULT_COMMUNITY, version="2c", timeout=5, auth=None):
    """Run snmpget and return the value string, or None on failure."""
    auth_args = _snmp_auth_args(community, version, auth)
    if not auth_args:
        return None
    cmd = ["snmpget", *auth_args, "-Ovq", "-t", str(timeout), ip, oid]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        if r.returncode == 0 and r.stdout.strip():
            return _clean_snmp_value(r.stdout.strip())
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _snmp_walk(ip, oid, community=DEFAULT_COMMUNITY, version="2c", timeout=10, auth=None):
    """Run snmpwalk and return list of (index, value) tuples."""
    auth_args = _snmp_auth_args(community, version, auth)
    if not auth_args:
        return []
    cmd = ["snmpwalk", *auth_args, "-Ovq", "-t", str(timeout), ip, oid]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        if r.returncode != 0:
            return []
        entries = []
        for line in r.stdout.strip().splitlines():
            val = _clean_snmp_value(line.strip())
            if val:
                entries.append(val)
        return entries
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def _snmp_walk_indexed(ip, oid, community=DEFAULT_COMMUNITY, version="2c", timeout=10, auth=None):
    """Run snmpwalk with OID output to get (oid_suffix, value) pairs."""
    auth_args = _snmp_auth_args(community, version, auth)
    if not auth_args:
        return {}
    cmd = ["snmpwalk", *auth_args, "-OQn", "-t", str(timeout), ip, oid]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        if r.returncode != 0:
            return {}
        result = {}
        for line in r.stdout.strip().splitlines():
            if "=" not in line:
                continue
            oid_part, _, val = line.partition("=")
            oid_part = oid_part.strip()
            val = _clean_snmp_value(val.strip())
            # Extract index from OID suffix
            suffix = oid_part.replace(oid, "").lstrip(".")
            if suffix:
                result[suffix] = val
        return result
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}


def _clean_snmp_value(val):
    """Clean SNMP output value — strip quotes, type prefixes."""
    if not val or val == "No Such" or "No Such Object" in val or "No Such Instance" in val:
        return None
    # Strip type prefixes like STRING:, INTEGER:, Gauge32:, Counter32:
    val = re.sub(r"^(STRING|INTEGER|Gauge32|Counter32|Counter64|Timeticks|OID|IpAddress):\s*", "", val)
    val = val.strip().strip('"')
    return val


def _get_community(cfg, args=None):
    """Get SNMP community string from config or args."""
    if args and getattr(args, "community", None):
        return args.community
    return getattr(cfg, "snmp_community", DEFAULT_COMMUNITY)


def _get_snmp_auth(cfg, args=None, include_secret=True):
    """Return path-backed SNMP auth, preferring v3 when configured."""
    if args and getattr(args, "community", None):
        return {}
    try:
        from freq.core.device_credentials import resolve_device_api_auth

        auth = resolve_device_api_auth(cfg, "snmp", include_secret=include_secret)
    except Exception:
        auth = {}
    if auth.get("version") in ("3", "v3", "snmpv3") and auth.get("user"):
        return auth
    return {}


# ---------------------------------------------------------------------------
# Data Storage
# ---------------------------------------------------------------------------


def _data_dir(cfg):
    """Return the SNMP data directory, creating if needed."""
    path = os.path.join(cfg.conf_dir, SNMP_DATA_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _save_poll(cfg, target, data):
    """Save a poll snapshot."""
    filepath = os.path.join(_data_dir(cfg), f"{target}-polls.json")
    existing = []
    if os.path.exists(filepath):
        with open(filepath) as f:
            try:
                existing = json.load(f)
            except json.JSONDecodeError:
                existing = []
    existing.append(data)
    # Keep last 100 polls
    existing = existing[-100:]
    with open(filepath, "w") as f:
        json.dump(existing, f, indent=2)


# ---------------------------------------------------------------------------
# High-Level Getters (combine multiple SNMP walks)
# ---------------------------------------------------------------------------


def get_system_info(ip, community=DEFAULT_COMMUNITY, auth=None, timeout=5):
    """Get system info via SNMP: sysDescr, sysUptime, sysName."""
    return {
        "description": _snmp_get(ip, OID_SYS_DESCR, community, auth=auth, timeout=timeout) or "",
        "object_id": _snmp_get(ip, OID_SYS_OBJECT_ID, community, auth=auth, timeout=timeout) or "",
        "uptime": _snmp_get(ip, OID_SYS_UPTIME, community, auth=auth, timeout=timeout) or "",
        "hostname": _snmp_get(ip, OID_SYS_NAME, community, auth=auth, timeout=timeout) or "",
        "contact": _snmp_get(ip, OID_SYS_CONTACT, community, auth=auth, timeout=timeout) or "",
        "location": _snmp_get(ip, OID_SYS_LOCATION, community, auth=auth, timeout=timeout) or "",
    }


def get_snmp_identity(ip, community=DEFAULT_COMMUNITY, auth=None, timeout=5):
    """Probe universal SNMP identity OIDs without making naming claims."""
    system = get_system_info(ip, community, auth=auth, timeout=timeout)
    serials = [v for v in _snmp_walk(ip, OID_ENT_PHYSICAL_SERIAL, community, auth=auth, timeout=timeout) if v]
    models = [v for v in _snmp_walk(ip, OID_ENT_PHYSICAL_MODEL, community, auth=auth, timeout=timeout) if v]
    names = [v for v in _snmp_walk(ip, OID_ENT_PHYSICAL_NAME, community, auth=auth, timeout=timeout) if v]
    serial = next((v for v in serials if v and v not in ("0", "None", "Unknown")), "")
    model = next((v for v in models if v and v not in ("0", "None", "Unknown")), "")
    physical_name = next((v for v in names if v and v not in ("0", "None", "Unknown")), "")
    return {
        "ip": ip,
        "source": "snmp",
        "sys_name": system.get("hostname", ""),
        "sys_descr": system.get("description", ""),
        "sys_object_id": system.get("object_id", ""),
        "serial": serial,
        "model": model,
        "physical_name": physical_name,
        "reachable": bool(system.get("hostname") or system.get("description")),
    }


def get_interfaces(ip, community=DEFAULT_COMMUNITY, auth=None):
    """Get interface table via SNMP: name, status, speed, counters."""
    names = _snmp_walk_indexed(ip, OID_IF_DESCR, community, auth=auth)
    admin = _snmp_walk_indexed(ip, OID_IF_ADMIN, community, auth=auth)
    oper = _snmp_walk_indexed(ip, OID_IF_OPER, community, auth=auth)
    speeds = _snmp_walk_indexed(ip, OID_IF_SPEED, community, auth=auth)
    in_oct = _snmp_walk_indexed(ip, OID_IF_IN_OCTETS, community, auth=auth)
    out_oct = _snmp_walk_indexed(ip, OID_IF_OUT_OCTETS, community, auth=auth)
    in_err = _snmp_walk_indexed(ip, OID_IF_IN_ERRORS, community, auth=auth)
    out_err = _snmp_walk_indexed(ip, OID_IF_OUT_ERRORS, community, auth=auth)

    interfaces = []
    for idx, name in names.items():
        admin_val = admin.get(idx, "")
        oper_val = oper.get(idx, "")
        # Map SNMP status codes
        admin_str = {"1": "up", "2": "down", "3": "testing"}.get(str(admin_val), str(admin_val))
        oper_str = {"1": "up", "2": "down", "3": "testing", "4": "unknown", "5": "dormant", "6": "notPresent"}.get(
            str(oper_val), str(oper_val)
        )

        speed_raw = speeds.get(idx, "0")
        try:
            speed_bps = int(speed_raw)
            speed_str = _format_speed(speed_bps)
        except (ValueError, TypeError):
            speed_str = str(speed_raw)

        interfaces.append(
            {
                "index": idx,
                "name": name,
                "admin": admin_str,
                "oper": oper_str,
                "speed": speed_str,
                "in_octets": _safe_int(in_oct.get(idx)),
                "out_octets": _safe_int(out_oct.get(idx)),
                "in_errors": _safe_int(in_err.get(idx)),
                "out_errors": _safe_int(out_err.get(idx)),
            }
        )

    return interfaces


def get_cpu_load(ip, community=DEFAULT_COMMUNITY, auth=None):
    """Get CPU load via SNMP (hrProcessorLoad)."""
    loads = _snmp_walk(ip, OID_HR_PROC_LOAD, community, auth=auth)
    values = [_safe_int(v) for v in loads if v is not None]
    if not values:
        return None
    return sum(values) // len(values)


def _format_speed(bps):
    """Format speed in bps to human-readable."""
    if bps >= 1_000_000_000:
        return f"{bps // 1_000_000_000}G"
    elif bps >= 1_000_000:
        return f"{bps // 1_000_000}M"
    elif bps >= 1_000:
        return f"{bps // 1_000}K"
    return str(bps)


def _safe_int(val):
    """Convert to int safely, return 0 on failure."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_snmp_poll(cfg: FreqConfig, pack, args) -> int:
    """Poll a device via SNMP — system info, interfaces, CPU."""
    target = getattr(args, "target", None)
    run_all = getattr(args, "all", False)
    community = _get_community(cfg, args)
    auth = _get_snmp_auth(cfg, args)

    if run_all:
        return _poll_all(cfg, community, auth)

    if not target:
        fmt.error("Usage: freq net snmp poll <target> or --all")
        return 1

    # Resolve target IP
    ip = _resolve_ip(target, cfg)
    if not ip:
        fmt.error(f"Cannot resolve target: {target}")
        return 1

    fmt.header(f"SNMP Poll: {target}", breadcrumb="FREQ > Net > SNMP")
    fmt.blank()

    # System info
    sys_info = get_system_info(ip, community, auth=auth)
    if not sys_info.get("hostname") and not sys_info.get("description"):
        fmt.warn(f"No SNMP response from {ip}")
        fmt.info("Check: is snmpd running? Is the community string correct?")
        fmt.info(f"  Try: snmpget -v 2c -c {community} {ip} {OID_SYS_DESCR}")
        fmt.footer()
        return 1

    fmt.line(f"{fmt.C.BOLD}System{fmt.C.RESET}")
    for key in ("hostname", "description", "uptime", "location", "contact"):
        val = sys_info.get(key, "")
        if val:
            fmt.line(f"  {fmt.C.CYAN}{key:<14}{fmt.C.RESET} {val}")
    fmt.blank()

    # Interfaces
    interfaces = get_interfaces(ip, community, auth=auth)
    if interfaces:
        # Filter to physical/interesting interfaces
        shown = [i for i in interfaces if i["oper"] == "up" or i["in_errors"] > 0]
        fmt.line(f"{fmt.C.BOLD}Interfaces ({len(shown)} up / {len(interfaces)} total){fmt.C.RESET}")
        fmt.table_header(("Name", 18), ("Status", 8), ("Speed", 8), ("In", 12), ("Out", 12), ("Errors", 8))
        for iface in shown[:30]:
            oper = iface["oper"]
            color = fmt.C.GREEN if oper == "up" else fmt.C.RED
            err_total = iface["in_errors"] + iface["out_errors"]
            err_color = fmt.C.RED if err_total > 0 else fmt.C.DIM
            fmt.table_row(
                (iface["name"], 18),
                (f"{color}{oper}{fmt.C.RESET}", 8),
                (iface["speed"], 8),
                (_format_bytes(iface["in_octets"]), 12),
                (_format_bytes(iface["out_octets"]), 12),
                (f"{err_color}{err_total}{fmt.C.RESET}", 8),
            )
        fmt.blank()

    # CPU
    cpu = get_cpu_load(ip, community, auth=auth)
    if cpu is not None:
        color = fmt.C.GREEN if cpu < 60 else fmt.C.YELLOW if cpu < 85 else fmt.C.RED
        fmt.line(f"{fmt.C.BOLD}CPU:{fmt.C.RESET} {color}{cpu}%{fmt.C.RESET}")
        fmt.blank()

    # Save poll
    poll_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "target": target,
        "ip": ip,
        "system": sys_info,
        "interface_count": len(interfaces),
        "interfaces_up": sum(1 for i in interfaces if i["oper"] == "up"),
        "cpu": cpu,
    }
    _save_poll(cfg, target, poll_data)

    logger.info("snmp_poll", target=target, ip=ip, interfaces=len(interfaces))
    fmt.footer()
    return 0


def _poll_all(cfg, community, auth=None):
    """Poll all switch-type hosts via SNMP."""
    from freq.modules.switch_orchestration import _get_switch_hosts

    switches = _get_switch_hosts(cfg)
    if not switches:
        fmt.error("No switches in hosts.toml")
        return 1

    fmt.header("SNMP Poll: All Switches", breadcrumb="FREQ > Net > SNMP")
    fmt.blank()

    ok_count = 0
    for h in switches:
        sys_info = get_system_info(h.ip, community, auth=auth)
        if sys_info.get("hostname") or sys_info.get("description"):
            cpu = get_cpu_load(h.ip, community, auth=auth)
            cpu_str = f"{cpu}%" if cpu is not None else "—"
            fmt.step_ok(f"{h.label} ({h.ip}) — {sys_info.get('hostname', '?')} — CPU: {cpu_str}")
            ok_count += 1
        else:
            fmt.step_fail(f"{h.label} ({h.ip}) — no SNMP response")

    fmt.blank()
    fmt.info(f"{ok_count}/{len(switches)} responded")
    logger.info("snmp_poll_all", targets=len(switches), ok=ok_count)
    fmt.footer()
    return 0 if ok_count > 0 else 1


def cmd_snmp_interfaces(cfg: FreqConfig, pack, args) -> int:
    """Show SNMP interface table with counters."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq net snmp interfaces <target>")
        return 1

    ip = _resolve_ip(target, cfg)
    community = _get_community(cfg, args)
    auth = _get_snmp_auth(cfg, args)

    fmt.header(f"SNMP Interfaces: {target}", breadcrumb="FREQ > Net > SNMP")
    fmt.blank()

    interfaces = get_interfaces(ip, community, auth=auth)
    if not interfaces:
        fmt.warn(f"No SNMP interface data from {ip}")
        fmt.footer()
        return 1

    fmt.table_header(
        ("Idx", 4),
        ("Name", 20),
        ("Admin", 6),
        ("Oper", 6),
        ("Speed", 8),
        ("In Octets", 14),
        ("Out Octets", 14),
        ("In Err", 8),
        ("Out Err", 8),
    )
    for iface in interfaces:
        oper_color = fmt.C.GREEN if iface["oper"] == "up" else fmt.C.RED
        fmt.table_row(
            (iface["index"], 4),
            (iface["name"], 20),
            (iface["admin"], 6),
            (f"{oper_color}{iface['oper']}{fmt.C.RESET}", 6),
            (iface["speed"], 8),
            (_format_bytes(iface["in_octets"]), 14),
            (_format_bytes(iface["out_octets"]), 14),
            (str(iface["in_errors"]), 8),
            (str(iface["out_errors"]), 8),
        )

    fmt.blank()
    up = sum(1 for i in interfaces if i["oper"] == "up")
    fmt.info(f"{up}/{len(interfaces)} interfaces up")
    logger.info("snmp_interfaces", target=target, ip=ip, count=len(interfaces))
    fmt.footer()
    return 0


def cmd_snmp_errors(cfg: FreqConfig, pack, args) -> int:
    """Show interfaces with errors."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq net snmp errors <target>")
        return 1

    ip = _resolve_ip(target, cfg)
    community = _get_community(cfg, args)
    auth = _get_snmp_auth(cfg, args)

    fmt.header(f"SNMP Errors: {target}", breadcrumb="FREQ > Net > SNMP")
    fmt.blank()

    interfaces = get_interfaces(ip, community, auth=auth)
    errors = [i for i in interfaces if i["in_errors"] > 0 or i["out_errors"] > 0]

    if not errors:
        fmt.success("No interface errors detected")
        fmt.footer()
        return 0

    fmt.table_header(("Name", 20), ("In Errors", 12), ("Out Errors", 12), ("Status", 8))
    for iface in errors:
        fmt.table_row(
            (iface["name"], 20),
            (f"{fmt.C.RED}{iface['in_errors']}{fmt.C.RESET}", 12),
            (f"{fmt.C.RED}{iface['out_errors']}{fmt.C.RESET}", 12),
            (iface["oper"], 8),
        )

    fmt.blank()
    fmt.warn(f"{len(errors)} interface(s) with errors")
    logger.info("snmp_errors", target=target, errors=len(errors))
    fmt.footer()
    return 0


def cmd_snmp_cpu(cfg: FreqConfig, pack, args) -> int:
    """Show CPU utilization via SNMP."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq net snmp cpu <target>")
        return 1

    ip = _resolve_ip(target, cfg)
    community = _get_community(cfg, args)
    auth = _get_snmp_auth(cfg, args)

    fmt.header(f"SNMP CPU: {target}", breadcrumb="FREQ > Net > SNMP")
    fmt.blank()

    cpu = get_cpu_load(ip, community, auth=auth)
    if cpu is None:
        fmt.warn(f"Could not retrieve CPU load from {ip}")
        fmt.footer()
        return 1

    color = fmt.C.GREEN if cpu < 60 else fmt.C.YELLOW if cpu < 85 else fmt.C.RED
    fmt.line(f"  {fmt.C.BOLD}CPU Load:{fmt.C.RESET} {color}{cpu}%{fmt.C.RESET}")

    # Also show per-core if available
    loads = _snmp_walk(ip, OID_HR_PROC_LOAD, community, auth=auth)
    if loads and len(loads) > 1:
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Per-Core:{fmt.C.RESET}")
        for i, load_val in enumerate(loads):
            v = _safe_int(load_val)
            c = fmt.C.GREEN if v < 60 else fmt.C.YELLOW if v < 85 else fmt.C.RED
            fmt.line(f"  Core {i}: {c}{v}%{fmt.C.RESET}")

    fmt.blank()
    logger.info("snmp_cpu", target=target, cpu=cpu)
    fmt.footer()
    return 0


def _snmp_setup_class(htype):
    htype = str(htype or "").strip().lower()
    if htype in {"pve", "proxmox", "linux", "ubuntu", "debian"}:
        return "linux_snmpd"
    if htype in {"truenas", "nas"}:
        return "truenas_midclt"
    if htype in {"switch", "cisco"}:
        return "cisco_ios_snmpv3"
    if htype in {"idrac", "bmc", "ilo", "ipmi", "redfish"}:
        return "redfish_bmc_snmp"
    if htype in {"pfsense", "opnsense", "firewall"}:
        return "pfsense_net_snmp_package"
    return "unsupported"


def build_snmp_setup_plan(cfg):
    """Build an enterprise SNMP setup/probe plan without mutating devices."""
    auth = _get_snmp_auth(cfg, include_secret=False)
    targets = []
    for host in getattr(cfg, "hosts", []) or []:
        htype = getattr(host, "htype", "")
        plan_class = _snmp_setup_class(htype)
        if plan_class == "unsupported":
            continue
        caveats = []
        if plan_class == "pfsense_net_snmp_package":
            caveats.append("pfSense built-in bsnmpd is v1/v2c only; SNMPv3 requires net-snmp package")
        if plan_class == "redfish_bmc_snmp":
            caveats.append("detect existing agent first; Dell iDRAC may already answer v2c and should be hardened deliberately")
        targets.append(
            {
                "label": getattr(host, "label", ""),
                "ip": getattr(host, "ip", ""),
                "type": htype,
                "setup_class": plan_class,
                "target_version": "v3",
                "security_level": "authPriv",
                "auth_protocol": auth.get("auth_protocol") or "SHA",
                "priv_protocol": auth.get("priv_protocol") or "AES",
                "credential_ref": "device-credentials:snmp" if auth.get("user") else "",
                "mutation": "plan_only",
                "caveats": caveats,
            }
        )
    return {
        "version": 1,
        "mode": "plan_only",
        "credential_ready": bool(auth.get("user")),
        "credential_ref": "device-credentials:snmp" if auth.get("user") else "",
        "targets": targets,
    }


def cmd_snmp_identity(cfg: FreqConfig, pack, args) -> int:
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq net snmp identity <target>")
        return 1
    ip = _resolve_ip(target, cfg)
    community = _get_community(cfg, args)
    auth = _get_snmp_auth(cfg, args)
    identity = get_snmp_identity(ip, community, auth=auth)
    fmt.header(f"SNMP Identity: {target}", breadcrumb="FREQ > Net > SNMP")
    fmt.blank()
    if not identity.get("reachable"):
        fmt.warn(f"No SNMP identity response from {ip}")
        fmt.footer()
        return 1
    for key in ("sys_name", "sys_descr", "sys_object_id", "serial", "model", "physical_name"):
        if identity.get(key):
            fmt.line(f"  {fmt.C.CYAN}{key:<14}{fmt.C.RESET} {identity[key]}")
    fmt.footer()
    return 0


def cmd_snmp_setup_plan(cfg: FreqConfig, pack, args) -> int:
    plan = build_snmp_setup_plan(cfg)
    fmt.header("SNMP Setup Plan", breadcrumb="FREQ > Net > SNMP")
    fmt.blank()
    fmt.info("Mode: plan-only. No devices are changed by this command.")
    if not plan["credential_ready"]:
        fmt.warn("SNMPv3 credential ref is not configured in device-credentials.")
    fmt.table_header(("Device", 18), ("IP", 15), ("Class", 24), ("Auth", 10))
    for target in plan["targets"]:
        auth_state = "ready" if target.get("credential_ref") else "missing"
        fmt.table_row(
            (target["label"], 18),
            (target["ip"], 15),
            (target["setup_class"], 24),
            (auth_state, 10),
        )
    fmt.blank()
    fmt.info(f"{len(plan['targets'])} SNMP-capable target(s) in plan")
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_ip(target, cfg):
    """Resolve target to IP address."""
    if re.match(r"^\d+\.\d+\.\d+\.\d+$", target):
        return target
    for h in cfg.hosts:
        if h.label == target:
            return h.ip
    return target


def _format_bytes(octets):
    """Format byte count to human-readable."""
    if octets >= 1_000_000_000:
        return f"{octets / 1_000_000_000:.1f} GB"
    elif octets >= 1_000_000:
        return f"{octets / 1_000_000:.1f} MB"
    elif octets >= 1_000:
        return f"{octets / 1_000:.1f} KB"
    return f"{octets} B"
