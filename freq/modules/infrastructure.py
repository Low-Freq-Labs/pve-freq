"""Infrastructure appliance management for FREQ.

Domain: freq fw <status|rules|aliases|...>, freq store <truenas-status|...>,
        freq net <switch-status|...>, freq hw <idrac-status|...>

Shared handler for SSH-based infrastructure appliances: pfSense firewalls,
TrueNAS storage, managed switches, and iDRAC/BMC controllers. Each device
type defines its own action map; the shared _device_cmd handles dispatch.

Replaces: Vendor-specific GUIs (pfSense WebGUI, TrueNAS WebUI, iDRAC web),
          manual SSH sessions to each appliance

Architecture:
    - Shared _device_cmd() handles action lookup, SSH exec, output formatting
    - Device IPs read from freq.toml [infrastructure] section
    - SSH via freq/core/ssh.py with device-specific htype (pfsense, truenas)
    - Per-device action dicts map action names to (description, command) tuples

Design decisions:
    - One shared handler, not four separate files. Appliance commands follow
      the same pattern (SSH + action dict), so the code is shared.
"""
import json
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

# Infrastructure timeouts
INFRA_CMD_TIMEOUT = 15
INFRA_TRUENAS_TIMEOUT = 30
INFRA_RESCUE_TIMEOUT = 60


def _device_cmd(cfg, args, title, ip, htype, actions, timeout=INFRA_CMD_TIMEOUT,
                use_sudo=False, help_note=""):
    """Shared handler for SSH-based infrastructure devices.

    Handles: action lookup, help display, SSH execution, output formatting.
    Used by pfSense, TrueNAS, and switch commands.
    """
    action = getattr(args, "action", None) or "status"

    fmt.header(title)
    fmt.blank()

    if not ip:
        fmt.line("{y}{title} IP not configured.{r}".format(
            y=fmt.C.YELLOW, title=title, r=fmt.C.RESET))
        fmt.line("{g}Set the IP in freq.toml [infrastructure]{r}".format(
            g=fmt.C.GRAY, r=fmt.C.RESET))
        fmt.blank()
        fmt.footer()
        return 1

    if action == "help" or action not in actions:
        fmt.line("{b}Available actions:{r}".format(b=fmt.C.BOLD, r=fmt.C.RESET))
        for name, (desc, _) in actions.items():
            fmt.line("  {c}{n:<12}{r} {d}".format(
                c=fmt.C.CYAN, n=name, r=fmt.C.RESET, d=desc))
        if help_note:
            fmt.blank()
            fmt.line("{g}{note}{r}".format(
                g=fmt.C.GRAY, note=help_note, r=fmt.C.RESET))
        fmt.blank()
        fmt.footer()
        return 0

    desc, cmd = actions[action]
    fmt.line("{b}{d}{r}".format(b=fmt.C.BOLD, d=desc, r=fmt.C.RESET))
    fmt.blank()

    r = ssh_run(
        host=ip, command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype=htype, use_sudo=use_sudo,
    )

    if r.returncode == 0 and r.stdout:
        for line in r.stdout.split("\n"):
            print("  {d}{l}{r}".format(d=fmt.C.DIM, l=line, r=fmt.C.RESET))
    else:
        fmt.line("{red}Cannot reach {title} at {ip}{r}".format(
            red=fmt.C.RED, title=title, ip=ip, r=fmt.C.RESET))
        if r.stderr:
            fmt.line("{d}{err}{r}".format(
                d=fmt.C.DIM, err=r.stderr[:60], r=fmt.C.RESET))

    fmt.blank()
    fmt.footer()
    return 0 if r.returncode == 0 else 1


# --- pfSense ---

def cmd_pfsense(cfg: FreqConfig, pack, args) -> int:
    """pfSense management — firewall rules, NAT, status."""
    return _device_cmd(cfg, args, "pfSense", cfg.pfsense_ip, "pfsense", {
        "status": ("System status", "uname -a; pfctl -s info 2>/dev/null | head -5"),
        "rules": ("Firewall rules", "pfctl -sr 2>/dev/null | head -30"),
        "nat": ("NAT rules", "pfctl -sn 2>/dev/null | head -20"),
        "states": ("Active states", "pfctl -ss 2>/dev/null | wc -l"),
        "interfaces": ("Interfaces", "ifconfig -a | grep '^[a-z]' | awk '{print $1}'"),
        "gateways": ("Gateway status", "netstat -rn | head -10"),
    })


# --- TrueNAS ---

def cmd_truenas(cfg: FreqConfig, pack, args) -> int:
    """TrueNAS management via midclt SSH."""
    return _device_cmd(cfg, args, "TrueNAS", cfg.truenas_ip, "truenas", {
        "status": ("System status", "midclt call system.info 2>/dev/null || echo 'midclt not available'"),
        "pools": ("ZFS pools", "zpool list 2>/dev/null"),
        "health": ("Pool health", "zpool status -x 2>/dev/null"),
        "datasets": ("Datasets", "zfs list -o name,used,avail,refer,mountpoint 2>/dev/null | head -20"),
        "shares": ("Shares", "midclt call sharing.smb.query '[]' 2>/dev/null | python3 -m json.tool 2>/dev/null || echo 'query failed'"),
        "alerts": ("Active alerts", "midclt call alert.list 2>/dev/null | python3 -c \"import json,sys; [print(a.get('formatted','?')) for a in json.load(sys.stdin)]\" 2>/dev/null || echo 'no alerts or midclt unavailable'"),
        "smart": ("SMART health", "midclt call disk.query '[]' 2>/dev/null | python3 -c \"import json,sys; [print(f\\\"{d['name']:>6} {d.get('serial','?'):>20} {'PASS' if not d.get('hddstandby_force') else 'CHECK'}\\\") for d in json.load(sys.stdin)]\" 2>/dev/null || echo 'unavailable'"),
    }, timeout=INFRA_TRUENAS_TIMEOUT, use_sudo=True,
       help_note="Uses midclt over SSH (no REST API dependency).")


# --- Switch ---

def cmd_switch(cfg: FreqConfig, pack, args) -> int:
    """Network switch management — VLANs and ports."""
    return _device_cmd(cfg, args, "Switch", cfg.switch_ip, "switch", {
        "status": ("Switch status", "show version | include uptime"),
        "vlans": ("VLAN database", "show vlan brief"),
        "interfaces": ("Interface status", "show ip interface brief"),
        "mac": ("MAC address table", "show mac address-table | head -30"),
        "arp": ("ARP table", "show arp | head -20"),
        "trunk": ("Trunk ports", "show interfaces trunk"),
    }, help_note="Connects to Cisco switch via SSH.")


# --- iDRAC ---

def cmd_idrac(cfg: FreqConfig, pack, args) -> int:
    """Dell iDRAC management — sensors, power, SEL."""
    action = getattr(args, "action", None) or "status"

    fmt.header("iDRAC")
    fmt.blank()

    # iDRAC targets from hosts.conf (type=idrac)
    targets = {}
    for h in cfg.hosts:
        if getattr(h, 'htype', '') == 'idrac':
            targets[h.label] = h.ip
    if not targets:
        fmt.line(f"  {fmt.C.YELLOW}No iDRAC hosts in hosts.conf (type: idrac){fmt.C.RESET}")
        fmt.info("Add hosts with type 'idrac' to conf/hosts.conf")
        fmt.blank()
        return 1

    actions = {
        "status": ("System status", "racadm getconfig -g cfgServerInfo"),
        "sensors": ("Temperature & fans", "racadm getsensorinfo"),
        "power": ("Power consumption", "racadm getconfig -g cfgServerPower"),
        "sel": ("System Event Log", "racadm getsel -i 1-10"),
        "info": ("Hardware inventory", "racadm getsysinfo"),
    }

    if action == "help" or action not in actions:
        fmt.line(f"{fmt.C.BOLD}Available actions:{fmt.C.RESET}")
        for name, (desc, _) in actions.items():
            fmt.line(f"  {fmt.C.CYAN}{name:<12}{fmt.C.RESET} {desc}")
        fmt.blank()
        fmt.line(f"{fmt.C.BOLD}Known iDRACs:{fmt.C.RESET}")
        for name, ip in targets.items():
            fmt.line(f"  {name}: {ip}")
        fmt.blank()
        fmt.footer()
        return 0

    desc, cmd = actions[action]
    fmt.line(f"{fmt.C.BOLD}{desc}{fmt.C.RESET}")
    fmt.blank()

    # Try all iDRAC targets
    for name, ip in targets.items():
        r = ssh_run(
            host=ip, command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=INFRA_CMD_TIMEOUT,
            htype="idrac", use_sudo=False,
        )

        if r.returncode == 0 and r.stdout:
            fmt.line(f"{fmt.C.PURPLE_BOLD}{name}{fmt.C.RESET} ({ip})")
            for line in r.stdout.split("\n")[:15]:
                print(f"    {fmt.C.DIM}{line}{fmt.C.RESET}")
            print()
        else:
            fmt.line(f"{fmt.C.DIM}{name}: unreachable{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


# --- Watch ---

def cmd_watch(cfg: FreqConfig, pack, args) -> int:
    """Monitoring daemon — periodic fleet health checks."""
    fmt.header("Watch")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Fleet monitoring — Ctrl+C to stop{fmt.C.RESET}")
    fmt.blank()

    from freq.modules.fleet import cmd_status

    interval = 30  # seconds
    try:
        while True:
            cmd_status(cfg, pack, args)
            print(f"\n  {fmt.C.DIM}Next check in {interval}s... (Ctrl+C to stop){fmt.C.RESET}")
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n  {fmt.C.YELLOW}Watch stopped.{fmt.C.RESET}")
        return 0


# --- Rescue ---

def cmd_rescue(cfg: FreqConfig, pack, args) -> int:
    """Rescue a stuck VM — force stop and console access."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq rescue <vmid>")
        return 1

    try:
        vmid = int(target)
    except ValueError:
        fmt.error(f"Invalid VMID: {target}")
        return 1

    fmt.header(f"Rescue VM {vmid}")
    fmt.blank()

    from freq.modules.pve import _find_reachable_node, _pve_cmd

    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1

    # Get current status
    fmt.step_start(f"Checking VM {vmid} status")
    stdout, ok = _pve_cmd(cfg, node_ip, f"qm status {vmid}")
    if ok:
        fmt.step_ok(f"Status: {stdout.strip()}")
    else:
        fmt.step_fail(f"VM {vmid} not found")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Rescue options:{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.CYAN}1{fmt.C.RESET}  Force stop (qm stop --force)")
    fmt.line(f"  {fmt.C.CYAN}2{fmt.C.RESET}  Reset (qm reset)")
    fmt.line(f"  {fmt.C.CYAN}3{fmt.C.RESET}  Unlock (qm unlock)")
    fmt.line(f"  {fmt.C.CYAN}0{fmt.C.RESET}  Cancel")
    fmt.blank()

    try:
        choice = input(f"  {fmt.C.YELLOW}Action:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    rescue_cmds = {
        "1": f"qm stop {vmid} --skiplock --timeout 30",
        "2": f"qm reset {vmid}",
        "3": f"qm unlock {vmid}",
    }

    cmd = rescue_cmds.get(choice)
    if not cmd:
        fmt.info("Cancelled.")
        return 0

    fmt.step_start(f"Executing rescue action")
    stdout, ok = _pve_cmd(cfg, node_ip, cmd, timeout=INFRA_RESCUE_TIMEOUT)
    if ok:
        fmt.step_ok("Rescue action completed")
    else:
        fmt.step_fail(f"Failed: {stdout}")

    fmt.blank()
    fmt.footer()
    return 0 if ok else 1
