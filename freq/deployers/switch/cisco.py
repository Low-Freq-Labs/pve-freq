"""Cisco IOS/IOS-XE switch deployer for FREQ.

Vendor: Cisco
Platforms: Catalyst 9200/9300/9500, ISR, ASR, legacy 2960/3750
OS: IOS 15.x, IOS-XE 16.x/17.x
Auth: SSH with RSA key (ed25519 not supported). Password auth for initial deploy.
Transport: SSH with legacy ciphers (see freq/core/ssh.py LEGACY_HTYPES)

Getter interface:
    get_facts()        -> hostname, model, serial, uptime, ios version
    get_interfaces()   -> name, status, speed, duplex, vlan
    get_vlans()        -> id, name, ports
    get_mac_table()    -> mac, vlan, port, type
    get_arp_table()    -> ip, mac, interface, age
    get_neighbors()    -> device, port, ip, platform
    get_config()       -> running-config as string
    get_environment()  -> temperature, fans, PSU status

Setter interface:
    push_config(lines) -> configure terminal, apply lines, end, write memory
    save_config()      -> write memory

Known quirks:
    - IOS returns garbage exit codes. Parse output for '% Invalid' patterns.
    - 'terminal length 0' before show commands to disable paging.
    - 'write memory' not 'copy run start' on older IOS.
"""
import re

from freq.core.ssh import run as ssh_run

CATEGORY = "switch"
VENDOR = "cisco"
NEEDS_PASSWORD = True
NEEDS_RSA = True


# ---------------------------------------------------------------------------
# SSH helper — wraps ssh_run with switch defaults
# ---------------------------------------------------------------------------

def _ssh(ip, cmd, cfg, timeout=15):
    """Run a command on a Cisco switch via SSH.

    Prepends 'terminal length 0' to disable paging.
    Returns (stdout, ok) tuple.
    """
    full_cmd = f"terminal length 0 ; {cmd}"
    key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
    r = ssh_run(
        host=ip, command=full_cmd,
        key_path=key,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="switch", use_sudo=False,
    )
    ok = r.returncode == 0 and "% Invalid" not in (r.stdout or "")
    return r.stdout or "", ok


# ---------------------------------------------------------------------------
# Deploy / Remove (existing — delegates to init_cmd)
# ---------------------------------------------------------------------------

def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to Cisco IOS switch."""
    from freq.modules.init_cmd import _deploy_switch
    return _deploy_switch(ip, ctx, auth_pass, auth_key, auth_user)


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from Cisco IOS switch."""
    from freq.modules.init_cmd import _remove_switch
    return _remove_switch(ip, svc_name, rsa_key_path or key_path)


# ---------------------------------------------------------------------------
# Getter Interface
# ---------------------------------------------------------------------------

def get_facts(ip, cfg):
    """Return device identity: hostname, model, serial, uptime, OS version."""
    out, ok = _ssh(ip, "show version", cfg)
    if not ok:
        return {}
    return _parse_show_version(out)


def get_interfaces(ip, cfg):
    """Return interface table: name, status, speed, duplex, vlan."""
    out, ok = _ssh(ip, "show interfaces status", cfg)
    if not ok:
        return []
    return _parse_interfaces_status(out)


def get_vlans(ip, cfg):
    """Return VLAN table: id, name, ports."""
    out, ok = _ssh(ip, "show vlan brief", cfg)
    if not ok:
        return []
    return _parse_vlan_brief(out)


def get_mac_table(ip, cfg):
    """Return MAC table: mac, vlan, port, type."""
    out, ok = _ssh(ip, "show mac address-table", cfg)
    if not ok:
        return []
    return _parse_mac_table(out)


def get_arp_table(ip, cfg):
    """Return ARP table: ip, mac, interface, age."""
    out, ok = _ssh(ip, "show arp", cfg)
    if not ok:
        return []
    return _parse_arp_table(out)


def get_neighbors(ip, cfg):
    """Return LLDP/CDP neighbors: device, local_port, remote_port, platform."""
    out, ok = _ssh(ip, "show cdp neighbors detail", cfg)
    if not ok:
        return []
    return _parse_cdp_detail(out)


def get_config(ip, cfg):
    """Return running configuration as string."""
    out, ok = _ssh(ip, "show running-config", cfg, timeout=30)
    if not ok:
        return ""
    return out


def get_environment(ip, cfg):
    """Return environment: temperature, fans, PSU status, CPU, memory."""
    result = {"temperature": [], "fans": [], "power": [], "cpu": None, "memory": None}

    # Environment (temp/fans/power) — not all platforms support this
    env_out, env_ok = _ssh(ip, "show environment all", cfg)
    if env_ok:
        result.update(_parse_environment(env_out))

    # CPU
    cpu_out, cpu_ok = _ssh(ip, "show processes cpu | include CPU utilization", cfg)
    if cpu_ok:
        m = re.search(r"five minutes:\s*(\d+)%", cpu_out)
        result["cpu"] = int(m.group(1)) if m else None

    # Memory
    mem_out, mem_ok = _ssh(ip, "show platform software status control-processor brief", cfg)
    if mem_ok and "RP0" in mem_out:
        m = re.search(r"RP0\s+\S+\s+\S+\s+\S+\s+(\d+)", mem_out)
        result["memory"] = int(m.group(1)) if m else None
    else:
        # Fallback for older IOS
        mem_out2, mem_ok2 = _ssh(ip, "show memory statistics | include Processor", cfg)
        if mem_ok2:
            m = re.search(r"Processor\s+\S+\s+(\d+)\s+(\d+)", mem_out2)
            if m:
                total = int(m.group(1)) + int(m.group(2))
                used = int(m.group(1))
                result["memory"] = int(used * 100 / total) if total else None

    return result


# ---------------------------------------------------------------------------
# Setter Interface
# ---------------------------------------------------------------------------

def push_config(ip, cfg, lines):
    """Push config lines to device. Returns True on success."""
    config_block = "\n".join(["configure terminal"] + list(lines) + ["end"])
    out, ok = _ssh(ip, config_block, cfg, timeout=30)
    if not ok or "% Invalid" in out:
        return False
    return True


def save_config(ip, cfg):
    """Persist running config to startup. Returns True on success."""
    out, ok = _ssh(ip, "write memory", cfg)
    return ok and "% Invalid" not in out


# ---------------------------------------------------------------------------
# Port Getters
# ---------------------------------------------------------------------------

def get_port_status(ip, cfg):
    """Return per-port status: name, status, vlan, speed, duplex, description."""
    return get_interfaces(ip, cfg)


def get_poe_status(ip, cfg):
    """Return PoE status per port: port, admin, oper, watts, device."""
    out, ok = _ssh(ip, "show power inline", cfg)
    if not ok:
        return []
    return _parse_power_inline(out)


# ---------------------------------------------------------------------------
# Port Setters
# ---------------------------------------------------------------------------

def set_port_vlan(ip, cfg, port, vlan, mode="access"):
    """Set port VLAN and mode. Returns True on success."""
    lines = [f"interface {port}"]
    if mode == "access":
        lines += [f"switchport mode access", f"switchport access vlan {vlan}"]
    elif mode == "trunk":
        lines += ["switchport mode trunk"]
        if vlan:
            lines.append(f"switchport trunk allowed vlan {vlan}")
    return push_config(ip, cfg, lines)


def set_port_shutdown(ip, cfg, port, shutdown=True):
    """Shutdown or no-shutdown a port. Returns True on success."""
    cmd = "shutdown" if shutdown else "no shutdown"
    return push_config(ip, cfg, [f"interface {port}", cmd])


def set_port_description(ip, cfg, port, description):
    """Set port description. Returns True on success."""
    return push_config(ip, cfg, [f"interface {port}", f"description {description}"])


def set_port_poe(ip, cfg, port, enabled=True):
    """Enable or disable PoE on a port. Returns True on success."""
    cmd = "power inline auto" if enabled else "power inline never"
    return push_config(ip, cfg, [f"interface {port}", cmd])


def flap_port(ip, cfg, port):
    """Bounce a port: shutdown then no-shutdown. Returns True on success."""
    return push_config(ip, cfg, [f"interface {port}", "shutdown", "no shutdown"])


def apply_profile_lines(ip, cfg, port, config_lines):
    """Apply a list of config lines to a port. Returns True on success."""
    return push_config(ip, cfg, [f"interface {port}"] + config_lines)


# ---------------------------------------------------------------------------
# Parsers — IOS show command output to structured data
# ---------------------------------------------------------------------------

def _parse_show_version(text):
    """Parse 'show version' into facts dict."""
    facts = {
        "hostname": "",
        "model": "",
        "serial": "",
        "os_version": "",
        "uptime": "",
        "image": "",
    }

    for line in text.splitlines():
        line = line.strip()

        # Hostname — "hostname uptime is ..."
        m = re.match(r"^(\S+)\s+uptime\s+is\s+(.*)", line)
        if m:
            facts["hostname"] = m.group(1)
            facts["uptime"] = m.group(2).strip()
            continue

        # IOS version
        m = re.search(r"(?:Cisco IOS.*?Version|IOS-XE.*?Version)\s+(\S+)", line, re.IGNORECASE)
        if m and not facts["os_version"]:
            facts["os_version"] = m.group(1).rstrip(",")
            continue

        # Model — "cisco WS-C3750-24TS" or "Cisco Catalyst 9300"
        m = re.match(r"^[Cc]isco\s+(\S+)", line)
        if m and not facts["model"] and "IOS" not in line:
            facts["model"] = m.group(1)
            continue

        # Model from "Model Number" line (IOS-XE)
        m = re.match(r"^Model [Nn]umber\s*:\s*(\S+)", line)
        if m:
            facts["model"] = m.group(1)
            continue

        # Serial
        m = re.match(r"^(?:Processor board ID|System [Ss]erial [Nn]umber)\s*:?\s*(\S+)", line)
        if m and not facts["serial"]:
            facts["serial"] = m.group(1)
            continue

        # Image file
        m = re.search(r'System image file is "(\S+)"', line)
        if m:
            facts["image"] = m.group(1)
            continue

    return facts


def _parse_interfaces_status(text):
    """Parse 'show interfaces status' into list of interface dicts."""
    interfaces = []
    header_found = False

    for line in text.splitlines():
        # Skip until we find the header line
        if "Port" in line and "Status" in line:
            header_found = True
            continue

        if not header_found or not line.strip():
            continue

        # show interfaces status format (fixed-width columns):
        # Port      Name               Status       Vlan       Duplex  Speed Type
        # Gi1/0/1   Camera-Lobby       connected    50         a-full  a-1000 10/100/1000BaseTX
        parts = line.split()
        if len(parts) < 4:
            continue

        port = parts[0]
        status = ""
        vlan = ""
        duplex = ""
        speed = ""
        name = ""

        # Status keywords to find the status column
        status_words = {"connected", "notconnect", "disabled", "err-disabled",
                        "monitoring", "faulty", "inactive"}

        # Find which token is the status
        status_idx = -1
        for i, p in enumerate(parts):
            if p in status_words:
                status_idx = i
                break

        if status_idx > 0:
            name = " ".join(parts[1:status_idx])
            status = parts[status_idx]
            remaining = parts[status_idx + 1:]
            if len(remaining) >= 1:
                vlan = remaining[0]
            if len(remaining) >= 2:
                duplex = remaining[1]
            if len(remaining) >= 3:
                speed = remaining[2]

        interfaces.append({
            "name": port,
            "description": name,
            "status": status,
            "vlan": vlan,
            "duplex": duplex,
            "speed": speed,
        })

    return interfaces


def _parse_vlan_brief(text):
    """Parse 'show vlan brief' into list of VLAN dicts."""
    vlans = []
    header_found = False

    for line in text.splitlines():
        if "VLAN" in line and "Name" in line and "Status" in line:
            header_found = True
            continue
        if line.startswith("----"):
            continue
        if not header_found or not line.strip():
            continue

        # VLAN lines: "10   DEVLAB   active   Gi1/0/1, Gi1/0/2"
        # Continuation lines start with spaces and have only port lists
        m = re.match(r"^(\d+)\s+(\S+)\s+(\S+)\s*(.*)", line)
        if m:
            vlan_id = int(m.group(1))
            name = m.group(2)
            status = m.group(3)
            ports_str = m.group(4).strip()
            ports = [p.strip() for p in ports_str.split(",") if p.strip()] if ports_str else []
            vlans.append({
                "id": vlan_id,
                "name": name,
                "status": status,
                "ports": ports,
            })
        elif vlans and line.startswith(" "):
            # Continuation line — more ports for the previous VLAN
            extra = [p.strip() for p in line.strip().split(",") if p.strip()]
            vlans[-1]["ports"].extend(extra)

    return vlans


def _parse_mac_table(text):
    """Parse 'show mac address-table' into list of MAC dicts."""
    entries = []

    for line in text.splitlines():
        # Format: "  10    aabb.ccdd.eeff    DYNAMIC     Gi1/0/5"
        # Skip header/footer lines
        m = re.match(r"^\s*(\d+)\s+([\da-fA-F]{4}\.[\da-fA-F]{4}\.[\da-fA-F]{4})\s+(\S+)\s+(\S+)", line)
        if m:
            entries.append({
                "vlan": int(m.group(1)),
                "mac": m.group(2).lower(),
                "type": m.group(3).lower(),
                "port": m.group(4),
            })

    return entries


def _parse_arp_table(text):
    """Parse 'show arp' into list of ARP dicts."""
    entries = []

    for line in text.splitlines():
        # Format: "Internet  10.25.255.5     10   aabb.ccdd.eeff  ARPA   Vlan2550"
        m = re.match(
            r"^\s*Internet\s+([\d.]+)\s+(\S+)\s+([\da-fA-F]{4}\.[\da-fA-F]{4}\.[\da-fA-F]{4})\s+\S+\s+(\S+)",
            line,
        )
        if m:
            entries.append({
                "ip": m.group(1),
                "age": m.group(2),
                "mac": m.group(3).lower(),
                "interface": m.group(4),
            })

    return entries


def _parse_cdp_detail(text):
    """Parse 'show cdp neighbors detail' into list of neighbor dicts."""
    neighbors = []
    current = {}

    for line in text.splitlines():
        line = line.strip()

        if line.startswith("Device ID:"):
            if current:
                neighbors.append(current)
            current = {
                "device": line.split(":", 1)[1].strip(),
                "local_port": "",
                "remote_port": "",
                "platform": "",
                "ip": "",
            }

        elif "IP address:" in line and current:
            m = re.search(r"IP address:\s*([\d.]+)", line)
            if m:
                current["ip"] = m.group(1)

        elif "Platform:" in line and current:
            m = re.search(r"Platform:\s*(.+?)(?:,|$)", line)
            if m:
                current["platform"] = m.group(1).strip()

        elif "Interface:" in line and current:
            # "Interface: GigabitEthernet1/0/1,  Port ID (outgoing port): GigabitEthernet0/1"
            m = re.match(r"Interface:\s*(\S+),\s*Port ID.*?:\s*(\S+)", line)
            if m:
                current["local_port"] = m.group(1)
                current["remote_port"] = m.group(2)

    if current:
        neighbors.append(current)

    return neighbors


def _parse_environment(text):
    """Parse 'show environment all' into temp/fan/power dicts."""
    result = {"temperature": [], "fans": [], "power": []}

    section = None
    for line in text.splitlines():
        lower = line.lower().strip()

        if "temperature" in lower and ("sensor" in lower or "value" in lower or "---" not in lower):
            section = "temperature"
            continue
        elif "fan" in lower and ("status" in lower or "speed" in lower):
            section = "fans"
            continue
        elif "power" in lower and ("supply" in lower or "status" in lower or "watts" in lower):
            section = "power"
            continue

        if not line.strip() or line.strip().startswith("---"):
            continue

        if section == "temperature":
            # Various formats: "1   Inlet     28 C    (0 C  - 45 C)"
            m = re.match(r"^\s*\d+\s+(\S+)\s+(\d+)\s*C", line)
            if m:
                result["temperature"].append({
                    "sensor": m.group(1),
                    "celsius": int(m.group(2)),
                })

        elif section == "fans":
            parts = line.split()
            if len(parts) >= 2:
                result["fans"].append({
                    "name": parts[0],
                    "status": parts[-1],
                })

        elif section == "power":
            parts = line.split()
            if len(parts) >= 2:
                result["power"].append({
                    "name": parts[0],
                    "status": parts[-1],
                })

    return result


def _parse_power_inline(text):
    """Parse 'show power inline' into list of PoE port dicts."""
    entries = []
    header_found = False

    for line in text.splitlines():
        # Header: "Interface Admin  Oper       Power   Device  Class Max"
        if "Interface" in line and "Admin" in line:
            header_found = True
            continue
        if line.startswith("---"):
            continue
        if not header_found or not line.strip():
            continue
        # Summary lines at the bottom
        if "Available" in line or "Used" in line or "Remaining" in line or "Total" in line:
            continue

        # Format: "Gi1/0/1   auto   on         7.0     Ieee PD   3     30.0"
        parts = line.split()
        if len(parts) < 3:
            continue

        port = parts[0]
        if not (port.startswith("Gi") or port.startswith("Fa") or port.startswith("Te")):
            continue

        admin = parts[1] if len(parts) > 1 else ""
        oper = parts[2] if len(parts) > 2 else ""
        watts = ""
        device = ""

        if len(parts) > 3:
            try:
                watts = float(parts[3])
            except ValueError:
                watts = parts[3]

        if len(parts) > 4:
            device = parts[4]
            if len(parts) > 5 and not parts[5].replace(".", "").isdigit():
                device += " " + parts[5]

        entries.append({
            "port": port,
            "admin": admin,
            "oper": oper,
            "watts": watts,
            "device": device,
        })

    return entries


def profile_to_config_lines(profile):
    """Convert a switch profile dict to IOS config lines for an interface.

    Takes a profile dict (from switch-profiles.toml) and returns a list
    of IOS commands to apply to an interface (without 'interface X' prefix).
    """
    lines = []

    if profile.get("description"):
        lines.append(f"description {profile['description']}")

    if profile.get("shutdown"):
        lines.append("shutdown")
        return lines

    lines.append("no shutdown")

    mode = profile.get("mode", "access")
    lines.append(f"switchport mode {mode}")

    if mode == "access":
        if profile.get("vlan"):
            lines.append(f"switchport access vlan {profile['vlan']}")
    elif mode == "trunk":
        if profile.get("allowed_vlans"):
            vlan_str = ",".join(str(v) for v in profile["allowed_vlans"])
            lines.append(f"switchport trunk allowed vlan {vlan_str}")
        if profile.get("native_vlan"):
            lines.append(f"switchport trunk native vlan {profile['native_vlan']}")

    if profile.get("speed") and profile["speed"] != "auto":
        lines.append(f"speed {profile['speed']}")

    if profile.get("spanning_tree") == "portfast":
        lines.append("spanning-tree portfast")

    if profile.get("poe") is True:
        lines.append("power inline auto")
    elif profile.get("poe") is False:
        lines.append("power inline never")

    ps = profile.get("port_security")
    if ps:
        lines.append("switchport port-security")
        if ps.get("max_mac"):
            lines.append(f"switchport port-security maximum {ps['max_mac']}")
        if ps.get("violation"):
            lines.append(f"switchport port-security violation {ps['violation']}")

    return lines
