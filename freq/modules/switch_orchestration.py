"""Switch orchestration for FREQ — vendor-agnostic switch management.

Domain: freq net switch <action> [target]
What: Query and manage network switches across vendors (Cisco, Juniper,
      Aruba, Ubiquiti, Arista) through a unified CLI interface.
Replaces: Manual SSH sessions to each switch, vendor-specific GUIs,
          the old infrastructure.py _device_cmd() pattern for switches
Architecture:
    - Resolves target to Host from hosts.conf (type=switch)
    - Picks vendor deployer via deployers/__init__.py resolve_htype()
    - Calls deployer getter (get_facts, get_interfaces, etc.)
    - Formats output via freq/core/fmt.py
    - If no target specified, uses cfg.switch_ip (single-switch compat)
Design decisions:
    - Vendor-agnostic: CLI commands are the same regardless of switch vendor.
      The deployer handles vendor-specific SSH commands and output parsing.
    - Target resolution: --all flag hits every switch in hosts.conf in parallel.
    - Graduated from infrastructure.py: the 6 old switch actions are replaced
      by richer, deployer-backed commands.
"""
from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Target Resolution
# ---------------------------------------------------------------------------

def _get_switch_hosts(cfg):
    """Return all hosts with htype=switch from hosts.conf."""
    return [h for h in cfg.hosts if h.htype == "switch"]


def _resolve_target(target, cfg):
    """Resolve a target string to (ip, label, htype) tuple.

    Target can be: IP address, host label, or None (uses cfg.switch_ip).
    Returns (ip, label, vendor) or (None, None, None) on failure.
    """
    if not target:
        # Default to cfg.switch_ip for single-switch setups
        if cfg.switch_ip:
            # Find the host entry to get the label
            for h in cfg.hosts:
                if h.ip == cfg.switch_ip:
                    return h.ip, h.label, _vendor_for_host(h)
            return cfg.switch_ip, "switch", "cisco"
        return None, None, None

    # Try by label first, then by IP
    for h in cfg.hosts:
        if h.label == target or h.ip == target:
            if h.htype == "switch":
                return h.ip, h.label, _vendor_for_host(h)
            # Allow targeting by label even if not type=switch
            return h.ip, h.label, _vendor_for_host(h)

    # Bare IP — assume cisco
    if "." in target:
        return target, target, "cisco"

    return None, None, None


def _vendor_for_host(host):
    """Determine vendor from host type string.

    Supports 'switch' (default cisco), 'switch:juniper', 'switch:aruba', etc.
    """
    from freq.deployers import resolve_htype
    _, vendor = resolve_htype(host.htype)
    return vendor


def _get_deployer(vendor):
    """Load the deployer module for a switch vendor."""
    from freq.deployers import get_deployer
    return get_deployer("switch", vendor)


# ---------------------------------------------------------------------------
# Commands — Core Switch Getters
# ---------------------------------------------------------------------------

def cmd_switch_show(cfg: FreqConfig, pack, args) -> int:
    """Show switch overview: facts + interface summary."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target specified and no switch_ip in freq.toml")
        fmt.info("Usage: freq net switch show <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Switch: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    # Facts
    facts = deployer.get_facts(ip, cfg)
    if facts:
        fmt.line(f"{fmt.C.BOLD}Device Facts{fmt.C.RESET}")
        for key in ("hostname", "model", "serial", "os_version", "uptime", "image"):
            val = facts.get(key, "")
            if val:
                fmt.line(f"  {fmt.C.CYAN}{key:<14}{fmt.C.RESET} {val}")
        fmt.blank()
    else:
        fmt.warn(f"Could not retrieve facts from {ip}")
        fmt.blank()
        fmt.footer()
        return 1

    # Interface summary
    interfaces = deployer.get_interfaces(ip, cfg)
    if interfaces:
        up = sum(1 for i in interfaces if i.get("status") == "connected")
        down = sum(1 for i in interfaces if i.get("status") == "notconnect")
        other = len(interfaces) - up - down
        fmt.line(f"{fmt.C.BOLD}Interfaces{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.GREEN}{up} up{fmt.C.RESET}  "
                 f"{fmt.C.RED}{down} down{fmt.C.RESET}  "
                 f"{fmt.C.DIM}{other} other{fmt.C.RESET}  "
                 f"({len(interfaces)} total)")
        fmt.blank()

    # VLAN count
    vlans = deployer.get_vlans(ip, cfg)
    if vlans:
        active = sum(1 for v in vlans if v.get("status") == "active")
        fmt.line(f"{fmt.C.BOLD}VLANs{fmt.C.RESET}  {active} active / {len(vlans)} total")
        fmt.blank()

    logger.info("switch_show", target=label, ip=ip, vendor=vendor)
    fmt.footer()
    return 0


def cmd_switch_facts(cfg: FreqConfig, pack, args) -> int:
    """Display device facts: hostname, model, serial, OS, uptime."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch facts <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Switch Facts: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    facts = deployer.get_facts(ip, cfg)
    if not facts:
        fmt.warn(f"Could not retrieve facts from {ip}")
        fmt.footer()
        return 1

    for key, val in facts.items():
        if val:
            fmt.line(f"  {fmt.C.CYAN}{key:<14}{fmt.C.RESET} {val}")

    fmt.blank()
    logger.info("switch_facts", target=label, ip=ip)
    fmt.footer()
    return 0


def cmd_switch_interfaces(cfg: FreqConfig, pack, args) -> int:
    """Display interface table with status, speed, VLAN."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch interfaces <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Interfaces: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    interfaces = deployer.get_interfaces(ip, cfg)
    if not interfaces:
        fmt.warn(f"Could not retrieve interfaces from {ip}")
        fmt.footer()
        return 1

    fmt.table_header(
        ("Port", 18), ("Description", 20), ("Status", 12),
        ("VLAN", 6), ("Duplex", 8), ("Speed", 8),
    )
    for iface in interfaces:
        status = iface.get("status", "")
        color = fmt.C.GREEN if status == "connected" else fmt.C.RED if status in ("notconnect", "err-disabled") else fmt.C.DIM
        fmt.table_row(
            (iface.get("name", ""), 18),
            (iface.get("description", ""), 20),
            (f"{color}{status}{fmt.C.RESET}", 12),
            (iface.get("vlan", ""), 6),
            (iface.get("duplex", ""), 8),
            (iface.get("speed", ""), 8),
        )

    fmt.blank()
    up = sum(1 for i in interfaces if i.get("status") == "connected")
    fmt.info(f"{up}/{len(interfaces)} ports connected")
    logger.info("switch_interfaces", target=label, ip=ip, count=len(interfaces))
    fmt.footer()
    return 0


def cmd_switch_vlans(cfg: FreqConfig, pack, args) -> int:
    """Display VLAN table with port membership."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch vlans <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"VLANs: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    vlans = deployer.get_vlans(ip, cfg)
    if not vlans:
        fmt.warn(f"Could not retrieve VLANs from {ip}")
        fmt.footer()
        return 1

    fmt.table_header(("ID", 6), ("Name", 20), ("Status", 10), ("Ports", 40))
    for v in vlans:
        ports = ", ".join(v.get("ports", []))
        if len(ports) > 40:
            ports = ports[:37] + "..."
        fmt.table_row(
            (str(v.get("id", "")), 6),
            (v.get("name", ""), 20),
            (v.get("status", ""), 10),
            (ports, 40),
        )

    fmt.blank()
    logger.info("switch_vlans", target=label, ip=ip, count=len(vlans))
    fmt.footer()
    return 0


def cmd_switch_mac(cfg: FreqConfig, pack, args) -> int:
    """Display MAC address table."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch mac <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"MAC Table: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    entries = deployer.get_mac_table(ip, cfg)
    if not entries:
        fmt.warn(f"Could not retrieve MAC table from {ip}")
        fmt.footer()
        return 1

    # Optional --vlan filter
    vlan_filter = getattr(args, "vlan", None)
    if vlan_filter:
        entries = [e for e in entries if e.get("vlan") == int(vlan_filter)]

    fmt.table_header(("VLAN", 6), ("MAC Address", 16), ("Type", 10), ("Port", 16))
    for e in entries:
        fmt.table_row(
            (str(e.get("vlan", "")), 6),
            (e.get("mac", ""), 16),
            (e.get("type", ""), 10),
            (e.get("port", ""), 16),
        )

    fmt.blank()
    fmt.info(f"{len(entries)} entries")
    logger.info("switch_mac", target=label, ip=ip, count=len(entries))
    fmt.footer()
    return 0


def cmd_switch_arp(cfg: FreqConfig, pack, args) -> int:
    """Display ARP table."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch arp <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"ARP Table: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    entries = deployer.get_arp_table(ip, cfg)
    if not entries:
        fmt.warn(f"Could not retrieve ARP table from {ip}")
        fmt.footer()
        return 1

    fmt.table_header(("IP Address", 16), ("MAC Address", 16), ("Interface", 14), ("Age", 8))
    for e in entries:
        fmt.table_row(
            (e.get("ip", ""), 16),
            (e.get("mac", ""), 16),
            (e.get("interface", ""), 14),
            (e.get("age", ""), 8),
        )

    fmt.blank()
    fmt.info(f"{len(entries)} entries")
    logger.info("switch_arp", target=label, ip=ip, count=len(entries))
    fmt.footer()
    return 0


def cmd_switch_neighbors(cfg: FreqConfig, pack, args) -> int:
    """Display LLDP/CDP neighbors."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch neighbors <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Neighbors: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    neighbors = deployer.get_neighbors(ip, cfg)
    if not neighbors:
        fmt.warn(f"No neighbors found on {ip}")
        fmt.footer()
        return 1

    fmt.table_header(
        ("Device", 20), ("Local Port", 16), ("Remote Port", 16),
        ("Platform", 20), ("IP", 16),
    )
    for n in neighbors:
        fmt.table_row(
            (n.get("device", ""), 20),
            (n.get("local_port", ""), 16),
            (n.get("remote_port", ""), 16),
            (n.get("platform", ""), 20),
            (n.get("ip", ""), 16),
        )

    fmt.blank()
    fmt.info(f"{len(neighbors)} neighbors")
    logger.info("switch_neighbors", target=label, ip=ip, count=len(neighbors))
    fmt.footer()
    return 0


def cmd_switch_config(cfg: FreqConfig, pack, args) -> int:
    """Display or backup running configuration."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch config <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Config: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    config_text = deployer.get_config(ip, cfg)
    if not config_text:
        fmt.warn(f"Could not retrieve config from {ip}")
        fmt.footer()
        return 1

    # --backup flag: save to conf/switch-configs/
    if getattr(args, "backup", False):
        import os
        import time as _time
        config_dir = os.path.join(cfg.conf_dir, "switch-configs")
        os.makedirs(config_dir, exist_ok=True)
        ts = _time.strftime("%Y%m%d-%H%M%S")
        filename = f"{label}-{ts}.conf"
        filepath = os.path.join(config_dir, filename)
        with open(filepath, "w") as f:
            f.write(config_text)
        fmt.success(f"Config saved to {filepath}")
        fmt.info(f"{len(config_text.splitlines())} lines")
    else:
        for line in config_text.splitlines():
            print(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")

    fmt.blank()
    logger.info("switch_config", target=label, ip=ip, backup=getattr(args, "backup", False))
    fmt.footer()
    return 0


def cmd_switch_environment(cfg: FreqConfig, pack, args) -> int:
    """Display environment: temperature, fans, PSU, CPU, memory."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch environment <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Environment: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    env = deployer.get_environment(ip, cfg)
    if not env:
        fmt.warn(f"Could not retrieve environment from {ip}")
        fmt.footer()
        return 1

    # Temperature
    temps = env.get("temperature", [])
    if temps:
        fmt.line(f"{fmt.C.BOLD}Temperature{fmt.C.RESET}")
        for t in temps:
            celsius = t.get("celsius", 0)
            color = fmt.C.GREEN if celsius < 45 else fmt.C.YELLOW if celsius < 65 else fmt.C.RED
            fmt.line(f"  {t.get('sensor', '?'):<16} {color}{celsius}°C{fmt.C.RESET}")
        fmt.blank()

    # Fans
    fans = env.get("fans", [])
    if fans:
        fmt.line(f"{fmt.C.BOLD}Fans{fmt.C.RESET}")
        for f_ in fans:
            status = f_.get("status", "unknown")
            color = fmt.C.GREEN if status.lower() in ("ok", "good", "normal") else fmt.C.RED
            fmt.line(f"  {f_.get('name', '?'):<16} {color}{status}{fmt.C.RESET}")
        fmt.blank()

    # Power
    power = env.get("power", [])
    if power:
        fmt.line(f"{fmt.C.BOLD}Power Supplies{fmt.C.RESET}")
        for p in power:
            status = p.get("status", "unknown")
            color = fmt.C.GREEN if status.lower() in ("ok", "good", "normal") else fmt.C.RED
            fmt.line(f"  {p.get('name', '?'):<16} {color}{status}{fmt.C.RESET}")
        fmt.blank()

    # CPU / Memory
    cpu = env.get("cpu")
    mem = env.get("memory")
    if cpu is not None or mem is not None:
        fmt.line(f"{fmt.C.BOLD}Utilization{fmt.C.RESET}")
        if cpu is not None:
            color = fmt.C.GREEN if cpu < 60 else fmt.C.YELLOW if cpu < 85 else fmt.C.RED
            fmt.line(f"  {'CPU':<16} {color}{cpu}%{fmt.C.RESET}")
        if mem is not None:
            color = fmt.C.GREEN if mem < 70 else fmt.C.YELLOW if mem < 90 else fmt.C.RED
            fmt.line(f"  {'Memory':<16} {color}{mem}%{fmt.C.RESET}")
        fmt.blank()

    logger.info("switch_environment", target=label, ip=ip)
    fmt.footer()
    return 0


def cmd_switch_exec(cfg: FreqConfig, pack, args) -> int:
    """Execute an arbitrary show command on a switch."""
    target = getattr(args, "target", None)
    command = getattr(args, "command", None)

    if not command:
        fmt.error("No command specified. Usage: freq net switch exec <target> \"<command>\"")
        return 1

    run_all = getattr(args, "all", False)

    if run_all:
        # Run across all switches in parallel
        return _exec_all(cfg, command)

    ip, label, vendor = _resolve_target(target, cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net switch exec <target> \"<command>\"")
        return 1

    fmt.header(f"Exec: {label}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}> {command}{fmt.C.RESET}")
    fmt.blank()

    from freq.core.ssh import run as ssh_run
    key = cfg.ssh_rsa_key_path or cfg.ssh_key_path
    r = ssh_run(
        host=ip, command=f"terminal length 0 ; {command}",
        key_path=key,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=30,
        htype="switch", use_sudo=False,
    )

    if r.returncode == 0 and r.stdout:
        for line in r.stdout.splitlines():
            print(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    else:
        fmt.warn(f"Command failed or no output from {ip}")
        if r.stderr:
            fmt.line(f"  {fmt.C.RED}{r.stderr[:200]}{fmt.C.RESET}")

    fmt.blank()
    logger.info("switch_exec", target=label, ip=ip, command=command)
    fmt.footer()
    return 0 if r.returncode == 0 else 1


def _exec_all(cfg, command):
    """Run a command across all switches in parallel."""
    from freq.core.ssh import run_many

    switches = _get_switch_hosts(cfg)
    if not switches:
        fmt.error("No switches found in hosts.conf (type=switch)")
        return 1

    fmt.header("Exec All Switches", breadcrumb="FREQ > Net > Switch")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}> {command}{fmt.C.RESET}")
    fmt.line(f"{fmt.C.DIM}Targets: {', '.join(h.label for h in switches)}{fmt.C.RESET}")
    fmt.blank()

    hosts = [{"ip": h.ip, "label": h.label, "htype": "switch"} for h in switches]
    results = run_many(
        hosts=hosts,
        command=f"terminal length 0 ; {command}",
        key_path=cfg.ssh_rsa_key_path or cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=30,
        use_sudo=False,
    )

    ok_count = 0
    for h in switches:
        r = results.get(h.ip)
        if r and r.returncode == 0:
            fmt.line(f"{fmt.C.GREEN}{h.label}{fmt.C.RESET} ({h.ip})")
            for line in (r.stdout or "").splitlines()[:20]:
                print(f"    {fmt.C.DIM}{line}{fmt.C.RESET}")
            ok_count += 1
        else:
            fmt.line(f"{fmt.C.RED}{h.label}{fmt.C.RESET} ({h.ip}) — unreachable")
        fmt.blank()

    fmt.info(f"{ok_count}/{len(switches)} switches responded")
    logger.info("switch_exec_all", command=command, targets=len(switches), ok=ok_count)
    fmt.footer()
    return 0 if ok_count > 0 else 1


# ---------------------------------------------------------------------------
# Commands — Port Management
# ---------------------------------------------------------------------------

def cmd_port_status(cfg: FreqConfig, pack, args) -> int:
    """Display per-port status: link, speed, VLAN, PoE, connected device."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net port status <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Port Status: {label}", breadcrumb="FREQ > Net > Port")
    fmt.blank()

    interfaces = deployer.get_interfaces(ip, cfg)
    if not interfaces:
        fmt.warn(f"Could not retrieve port status from {ip}")
        fmt.footer()
        return 1

    # Merge PoE data if available
    poe_map = {}
    if hasattr(deployer, "get_poe_status"):
        poe_entries = deployer.get_poe_status(ip, cfg)
        poe_map = {e["port"]: e for e in poe_entries}

    fmt.table_header(
        ("Port", 14), ("Description", 18), ("Status", 12),
        ("VLAN", 6), ("Speed", 8), ("PoE", 8),
    )
    for iface in interfaces:
        name = iface.get("name", "")
        status = iface.get("status", "")
        color = fmt.C.GREEN if status == "connected" else fmt.C.RED if status in ("notconnect", "err-disabled") else fmt.C.DIM

        poe_info = poe_map.get(name, {})
        poe_str = ""
        if poe_info:
            watts = poe_info.get("watts", "")
            if watts and watts != "n/a":
                poe_str = f"{watts}W"
            else:
                poe_str = poe_info.get("oper", "")

        fmt.table_row(
            (name, 14),
            (iface.get("description", ""), 18),
            (f"{color}{status}{fmt.C.RESET}", 12),
            (iface.get("vlan", ""), 6),
            (iface.get("speed", ""), 8),
            (poe_str, 8),
        )

    fmt.blank()
    up = sum(1 for i in interfaces if i.get("status") == "connected")
    fmt.info(f"{up}/{len(interfaces)} ports connected")
    logger.info("port_status", target=label, ip=ip, count=len(interfaces))
    fmt.footer()
    return 0


def cmd_port_configure(cfg: FreqConfig, pack, args) -> int:
    """Configure a single port: VLAN, mode, shutdown state."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    port = getattr(args, "port", None)
    if not ip or not port:
        fmt.error("Usage: freq net port configure <target> <port> [--vlan N] [--mode access|trunk] [--shutdown|--no-shutdown]")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Configure Port: {label} {port}", breadcrumb="FREQ > Net > Port")
    fmt.blank()

    vlan = getattr(args, "vlan", None)
    mode = getattr(args, "mode", None)
    shutdown = getattr(args, "shutdown", None)
    no_shutdown = getattr(args, "no_shutdown", None)

    changes = 0

    if vlan is not None:
        fmt.step_start(f"Setting VLAN {vlan} on {port}")
        if deployer.set_port_vlan(ip, cfg, port, vlan, mode or "access"):
            fmt.step_ok(f"VLAN {vlan} set")
            changes += 1
        else:
            fmt.step_fail(f"Failed to set VLAN {vlan}")

    elif mode is not None and vlan is None:
        fmt.step_start(f"Setting mode {mode} on {port}")
        if deployer.set_port_vlan(ip, cfg, port, None, mode):
            fmt.step_ok(f"Mode {mode} set")
            changes += 1
        else:
            fmt.step_fail(f"Failed to set mode {mode}")

    if shutdown:
        fmt.step_start(f"Shutting down {port}")
        if deployer.set_port_shutdown(ip, cfg, port, shutdown=True):
            fmt.step_ok("Port shut down")
            changes += 1
        else:
            fmt.step_fail("Failed to shutdown port")

    elif no_shutdown:
        fmt.step_start(f"Enabling {port}")
        if deployer.set_port_shutdown(ip, cfg, port, shutdown=False):
            fmt.step_ok("Port enabled")
            changes += 1
        else:
            fmt.step_fail("Failed to enable port")

    if changes > 0:
        fmt.step_start("Saving config")
        if deployer.save_config(ip, cfg):
            fmt.step_ok("Config saved")
        else:
            fmt.step_warn("Save failed — changes may not persist across reboot")

    if changes == 0 and not vlan and not mode and not shutdown and not no_shutdown:
        fmt.warn("No changes specified. Use --vlan, --mode, --shutdown, or --no-shutdown")

    fmt.blank()
    logger.info("port_configure", target=label, ip=ip, port=port, changes=changes)
    fmt.footer()
    return 0


def cmd_port_desc(cfg: FreqConfig, pack, args) -> int:
    """Set port description."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    port = getattr(args, "port", None)
    description = getattr(args, "description", None)
    if not ip or not port or not description:
        fmt.error("Usage: freq net port desc <target> <port> --description \"text\"")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Set Description: {label} {port}", breadcrumb="FREQ > Net > Port")
    fmt.blank()

    fmt.step_start(f"Setting description on {port}")
    if deployer.set_port_description(ip, cfg, port, description):
        fmt.step_ok(f"Description: {description}")
        deployer.save_config(ip, cfg)
    else:
        fmt.step_fail("Failed to set description")

    fmt.blank()
    logger.info("port_desc", target=label, ip=ip, port=port, description=description)
    fmt.footer()
    return 0


def cmd_port_poe(cfg: FreqConfig, pack, args) -> int:
    """Display PoE status or toggle PoE on a port."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    if not ip:
        fmt.error("No switch target. Usage: freq net port poe <target>")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    port = getattr(args, "port", None)
    poe_on = getattr(args, "on", False)
    poe_off = getattr(args, "off", False)

    # Toggle mode
    if port and (poe_on or poe_off):
        fmt.header(f"PoE Toggle: {label} {port}", breadcrumb="FREQ > Net > Port")
        fmt.blank()
        action = "Enabling" if poe_on else "Disabling"
        fmt.step_start(f"{action} PoE on {port}")
        if deployer.set_port_poe(ip, cfg, port, enabled=poe_on):
            fmt.step_ok(f"PoE {'enabled' if poe_on else 'disabled'}")
            deployer.save_config(ip, cfg)
        else:
            fmt.step_fail(f"Failed to {'enable' if poe_on else 'disable'} PoE")
        fmt.blank()
        fmt.footer()
        return 0

    # Status mode
    fmt.header(f"PoE Status: {label}", breadcrumb="FREQ > Net > Port")
    fmt.blank()

    if not hasattr(deployer, "get_poe_status"):
        fmt.warn("PoE status not supported for this vendor")
        fmt.footer()
        return 1

    entries = deployer.get_poe_status(ip, cfg)
    if not entries:
        fmt.warn(f"Could not retrieve PoE status from {ip}")
        fmt.footer()
        return 1

    fmt.table_header(("Port", 14), ("Admin", 8), ("Oper", 8), ("Watts", 8), ("Device", 20))
    total_watts = 0
    for e in entries:
        watts = e.get("watts", "")
        if isinstance(watts, (int, float)):
            total_watts += watts
        fmt.table_row(
            (e.get("port", ""), 14),
            (e.get("admin", ""), 8),
            (e.get("oper", ""), 8),
            (str(watts), 8),
            (e.get("device", ""), 20),
        )

    fmt.blank()
    fmt.info(f"Total power draw: {total_watts:.1f}W")
    logger.info("port_poe", target=label, ip=ip, entries=len(entries))
    fmt.footer()
    return 0


def cmd_port_find(cfg: FreqConfig, pack, args) -> int:
    """Find which port a MAC address is on."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    mac_query = getattr(args, "mac", None)
    if not ip or not mac_query:
        fmt.error("Usage: freq net port find <target> --mac XX:XX:XX:XX:XX:XX")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Find MAC: {label}", breadcrumb="FREQ > Net > Port")
    fmt.blank()

    # Normalize query — support colon, dash, and dot formats
    mac_clean = mac_query.lower().replace(":", "").replace("-", "").replace(".", "")

    entries = deployer.get_mac_table(ip, cfg)
    if not entries:
        fmt.warn(f"Could not retrieve MAC table from {ip}")
        fmt.footer()
        return 1

    matches = []
    for e in entries:
        entry_clean = e.get("mac", "").replace(".", "")
        if mac_clean in entry_clean:
            matches.append(e)

    if matches:
        fmt.table_header(("VLAN", 6), ("MAC Address", 16), ("Port", 16), ("Type", 10))
        for m in matches:
            fmt.table_row(
                (str(m.get("vlan", "")), 6),
                (m.get("mac", ""), 16),
                (m.get("port", ""), 16),
                (m.get("type", ""), 10),
            )
        fmt.blank()
        fmt.success(f"Found {len(matches)} match(es) for {mac_query}")
    else:
        fmt.warn(f"MAC {mac_query} not found in {len(entries)} table entries")

    logger.info("port_find", target=label, ip=ip, mac=mac_query, found=len(matches))
    fmt.footer()
    return 0


def cmd_port_flap(cfg: FreqConfig, pack, args) -> int:
    """Bounce a port (shut/no shut)."""
    ip, label, vendor = _resolve_target(getattr(args, "target", None), cfg)
    port = getattr(args, "port", None)
    if not ip or not port:
        fmt.error("Usage: freq net port flap <target> --port Gi1/0/5")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    fmt.header(f"Port Flap: {label} {port}", breadcrumb="FREQ > Net > Port")
    fmt.blank()

    fmt.step_start(f"Bouncing {port} (shut/no shut)")
    if deployer.flap_port(ip, cfg, port):
        fmt.step_ok(f"{port} bounced")
    else:
        fmt.step_fail(f"Failed to flap {port}")

    fmt.blank()
    logger.info("port_flap", target=label, ip=ip, port=port)
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — Port Profiles
# ---------------------------------------------------------------------------

PROFILES_FILE = "switch-profiles.toml"


def _load_profiles(cfg):
    """Load switch profiles from conf/switch-profiles.toml."""
    import os
    filepath = os.path.join(cfg.conf_dir, PROFILES_FILE)
    if not os.path.exists(filepath):
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(filepath, "rb") as f:
        data = tomllib.load(f)
    return data.get("profile", {})


def _save_profiles(cfg, profiles):
    """Save switch profiles to conf/switch-profiles.toml."""
    import os
    filepath = os.path.join(cfg.conf_dir, PROFILES_FILE)
    lines = ["# FREQ Switch Port Profiles", "# Apply with: freq net switch profile apply <name> <target> <port-range>", ""]
    for name, profile in sorted(profiles.items()):
        lines.append(f"[profile.{name}]")
        for key, val in profile.items():
            if isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            elif isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            elif isinstance(val, list):
                items = ", ".join(str(v) for v in val)
                lines.append(f"{key} = [{items}]")
            elif isinstance(val, dict):
                inner = ", ".join(f'{k} = {_toml_val(v)}' for k, v in val.items())
                lines.append(f"{key} = {{ {inner} }}")
            else:
                lines.append(f"{key} = {val}")
        lines.append("")
    with open(filepath, "w") as f:
        f.write("\n".join(lines))


def _toml_val(v):
    """Format a value for inline TOML."""
    if isinstance(v, str):
        return f'"{v}"'
    elif isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _expand_port_range(port_range):
    """Expand a port range like Gi1/0/1-24 into individual port names.

    Supports: Gi1/0/1-24, Gi1/0/1,Gi1/0/5, Gi1/0/1-4,Gi1/0/10
    """
    import re as _re
    ports = []
    for segment in port_range.split(","):
        segment = segment.strip()
        m = _re.match(r"^(.+/)(\d+)-(\d+)$", segment)
        if m:
            prefix = m.group(1)
            start = int(m.group(2))
            end = int(m.group(3))
            for i in range(start, end + 1):
                ports.append(f"{prefix}{i}")
        else:
            ports.append(segment)
    return ports


def cmd_profile_list(cfg: FreqConfig, pack, args) -> int:
    """List available port profiles."""
    profiles = _load_profiles(cfg)

    fmt.header("Switch Port Profiles", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    if not profiles:
        fmt.warn("No profiles defined")
        fmt.info(f"Create one: freq net switch profile create <name>")
        fmt.footer()
        return 0

    fmt.table_header(("Name", 20), ("Mode", 8), ("VLAN", 8), ("Description", 40))
    for name, p in sorted(profiles.items()):
        fmt.table_row(
            (name, 20),
            (p.get("mode", "—"), 8),
            (str(p.get("vlan", p.get("native_vlan", "—"))), 8),
            (p.get("description", ""), 40),
        )

    fmt.blank()
    fmt.info(f"{len(profiles)} profile(s)")
    fmt.footer()
    return 0


def cmd_profile_show(cfg: FreqConfig, pack, args) -> int:
    """Show details of a specific profile."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq net switch profile show <name>")
        return 1

    profiles = _load_profiles(cfg)
    profile = profiles.get(name)
    if not profile:
        fmt.error(f"Profile '{name}' not found")
        return 1

    fmt.header(f"Profile: {name}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()

    for key, val in profile.items():
        fmt.line(f"  {fmt.C.CYAN}{key:<20}{fmt.C.RESET} {val}")

    # Show what config lines this would generate (Cisco)
    from freq.deployers.switch.cisco import profile_to_config_lines
    lines = profile_to_config_lines(profile)
    if lines:
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Generated IOS Config:{fmt.C.RESET}")
        for line in lines:
            fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_profile_apply(cfg: FreqConfig, pack, args) -> int:
    """Apply a profile to a port or port range on a switch."""
    profile_name = getattr(args, "name", None)
    target = getattr(args, "target", None)
    port_range = getattr(args, "ports", None)

    if not profile_name or not port_range:
        fmt.error("Usage: freq net switch profile apply <name> <target> --ports Gi1/0/1-24")
        return 1

    profiles = _load_profiles(cfg)
    profile = profiles.get(profile_name)
    if not profile:
        fmt.error(f"Profile '{profile_name}' not found")
        return 1

    ip, label, vendor = _resolve_target(target, cfg)
    if not ip:
        fmt.error("No switch target specified")
        return 1

    deployer = _get_deployer(vendor)
    if not deployer:
        fmt.error(f"No deployer for switch vendor: {vendor}")
        return 1

    # Generate vendor-specific config lines
    if hasattr(deployer, "profile_to_config_lines"):
        config_lines = deployer.profile_to_config_lines(profile)
    else:
        from freq.deployers.switch.cisco import profile_to_config_lines
        config_lines = profile_to_config_lines(profile)

    ports = _expand_port_range(port_range)

    fmt.header(f"Apply Profile: {profile_name}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Profile:{fmt.C.RESET} {profile_name}")
    fmt.line(f"{fmt.C.BOLD}Target:{fmt.C.RESET}  {label} ({ip})")
    fmt.line(f"{fmt.C.BOLD}Ports:{fmt.C.RESET}   {', '.join(ports)} ({len(ports)} port(s))")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Config per port:{fmt.C.RESET}")
    for line in config_lines:
        fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
    fmt.blank()

    ok_count = 0
    for port in ports:
        fmt.step_start(f"Configuring {port}")
        if deployer.apply_profile_lines(ip, cfg, port, config_lines):
            fmt.step_ok(port)
            ok_count += 1
        else:
            fmt.step_fail(port)

    fmt.blank()
    if ok_count > 0:
        fmt.step_start("Saving config")
        if deployer.save_config(ip, cfg):
            fmt.step_ok("Config saved")
        else:
            fmt.step_warn("Save failed — changes may not persist")

    fmt.blank()
    fmt.info(f"{ok_count}/{len(ports)} ports configured")
    logger.info("profile_apply", profile=profile_name, target=label, ports=len(ports), ok=ok_count)
    fmt.footer()
    return 0


def cmd_profile_create(cfg: FreqConfig, pack, args) -> int:
    """Create a new port profile interactively or with flags."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq net switch profile create <name> [--mode access|trunk] [--vlan N] [--description text]")
        return 1

    profiles = _load_profiles(cfg)
    if name in profiles:
        fmt.error(f"Profile '{name}' already exists. Delete it first or use a different name.")
        return 1

    profile = {}
    desc = getattr(args, "description", None)
    mode = getattr(args, "mode", None)
    vlan = getattr(args, "vlan", None)
    shutdown = getattr(args, "shutdown", False)

    if desc:
        profile["description"] = desc
    if mode:
        profile["mode"] = mode
    if vlan:
        profile["vlan"] = int(vlan)
    if shutdown:
        profile["shutdown"] = True

    if not profile:
        fmt.error("Specify at least one option: --mode, --vlan, --description, --shutdown")
        return 1

    profiles[name] = profile
    _save_profiles(cfg, profiles)

    fmt.header(f"Profile Created: {name}", breadcrumb="FREQ > Net > Switch")
    fmt.blank()
    for key, val in profile.items():
        fmt.line(f"  {fmt.C.CYAN}{key:<20}{fmt.C.RESET} {val}")
    fmt.blank()
    fmt.success(f"Profile '{name}' saved to {PROFILES_FILE}")
    logger.info("profile_create", name=name)
    fmt.footer()
    return 0


def cmd_profile_delete(cfg: FreqConfig, pack, args) -> int:
    """Delete a port profile."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq net switch profile delete <name>")
        return 1

    profiles = _load_profiles(cfg)
    if name not in profiles:
        fmt.error(f"Profile '{name}' not found")
        return 1

    del profiles[name]
    _save_profiles(cfg, profiles)

    fmt.success(f"Profile '{name}' deleted")
    logger.info("profile_delete", name=name)
    return 0
