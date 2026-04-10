"""Firewall domain API handlers -- pfSense write operations.

Who:   New module for pfSense management write operations.
What:  REST endpoints for pfSense service control, DHCP reservations,
       config backup/restore, firewall rules, WireGuard peers, reboot.
Why:   pfSense was read-only. Now we can manage it from the dashboard.
Where: Routes registered at /api/pfsense/*.
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import re

from freq.core import log as logger
from freq.api.helpers import require_post,  json_response, get_json_body
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.modules.serve import _check_session_role


# -- Helper ------------------------------------------------------------------


def _pf_ssh(cfg, cmd, timeout=15):
    """SSH to pfSense and return result."""
    return ssh_single(
        host=cfg.pfsense_ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pfsense",
        use_sudo=False,
        cfg=cfg,
    )


def _pf_ok(r, action=""):
    """Standard pfSense response dict."""
    return {
        "ok": r.returncode == 0,
        "action": action,
        "output": r.stdout[:4000] if r.returncode == 0 else "",
        "error": r.stderr[:200] if r.returncode != 0 else "",
    }


def _require_pfsense(handler):
    """Check admin role and pfSense config. Returns (cfg, ok)."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return None, False
    cfg = load_config()
    if not cfg.pfsense_ip:
        json_response(handler, {"error": "pfSense not configured"}, 400)
        return None, False
    return cfg, True


# -- pfSense Service Control ------------------------------------------------

_PF_SERVICES = {
    "dhcpd",
    "unbound",
    "openvpn",
    "ipsec",
    "dpinger",
    "ntpd",
    "sshd",
    "syslogd",
    "filterdns",
}


def handle_pfsense_service(handler):
    """POST /api/pfsense/service -- restart a pfSense service.

    Body: {"service": "dhcpd", "action": "restart"}
    """
    if require_post(handler, "pfSense service"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    service = body.get("service", "").strip().lower()
    action = body.get("action", "restart")

    if action not in ("restart", "start", "stop"):
        json_response(handler, {"error": "action must be restart, start, or stop"}, 400)
        return
    if service not in _PF_SERVICES:
        json_response(
            handler, {"error": f"Unknown service: {service}. Allowed: {', '.join(sorted(_PF_SERVICES))}"}, 400
        )
        return

    # pfSense uses FreeBSD service command or pfSsh.php for some services
    if service == "unbound":
        cmd = f"pfSsh.php playback svc {action} unbound 2>/dev/null || service unbound {action}"
    elif service == "openvpn":
        cmd = f"pfSsh.php playback svc {action} openvpn 2>/dev/null || service openvpn {action}"
    else:
        cmd = f"service {service} {action} 2>&1"

    r = _pf_ssh(cfg, cmd, timeout=20)
    json_response(handler, _pf_ok(r, f"{action} {service}"))


# -- pfSense DHCP Reservations ---------------------------------------------

_SAFE_MAC = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_SAFE_IP = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
_SAFE_HOSTNAME = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_SAFE_IFACE = re.compile(r"^[a-zA-Z0-9_]{1,16}$")
_SAFE_CIDR = re.compile(r"^[0-9a-fA-F.:/ ]+$")
_SAFE_TEXT = re.compile(r"^[a-zA-Z0-9 _\-.:,/()]{0,128}$")
_SAFE_WG_KEY = re.compile(r"^[A-Za-z0-9+/=]{43,44}$")


def handle_pfsense_dhcp_reservation(handler):
    """POST /api/pfsense/dhcp/reservation -- manage static DHCP mappings.

    Body: {"action": "list|add|delete", "mac": "...", "ip": "...",
           "hostname": "...", "description": "...", "interface": "lan"}
    """
    if require_post(handler, "pfSense DHCP"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    action = body.get("action", "list")
    iface = body.get("interface", "lan").strip().lower()

    if not _SAFE_IFACE.match(iface):
        json_response(handler, {"error": "Invalid interface name"}, 400)
        return

    if action == "list":
        # Parse config.xml for static mappings
        cmd = (
            "cat /cf/conf/config.xml 2>/dev/null | "
            "sed -n '/<dhcpd>/,/<\\/dhcpd>/p' | "
            "sed -n '/<staticmap>/,/<\\/staticmap>/p'"
        )
        r = _pf_ssh(cfg, cmd)
        if r.returncode == 0 and r.stdout.strip():
            # Parse XML-ish output into JSON
            entries = _parse_dhcp_static_maps(r.stdout)
            json_response(handler, {"ok": True, "reservations": entries})
        else:
            json_response(handler, {"ok": True, "reservations": []})
        return

    if action == "add":
        mac = body.get("mac", "").strip()
        ip = body.get("ip", "").strip()
        hostname = body.get("hostname", "").strip()
        description = body.get("description", hostname)

        if not mac or not _SAFE_MAC.match(mac):
            json_response(handler, {"error": "Invalid MAC address"}, 400)
            return
        if not ip or not _SAFE_IP.match(ip):
            json_response(handler, {"error": "Invalid IP address"}, 400)
            return
        if hostname and not _SAFE_HOSTNAME.match(hostname):
            json_response(handler, {"error": "Invalid hostname"}, 400)
            return
        if description and not _SAFE_TEXT.match(description):
            json_response(handler, {"error": "Invalid description (alphanumeric + basic punctuation only)"}, 400)
            return

        # Use PHP helper to add static mapping via pfSense's config system
        php_cmd = (
            f'php -r "'
            f"require_once('config.inc');"
            f"require_once('util.inc');"
            f"require_once('services.inc');"
            f"\\$config = parse_config(true);"
            f"if(!isset(\\$config['dhcpd']['{iface}']['staticmap'])) "
            f"  \\$config['dhcpd']['{iface}']['staticmap'] = array();"
            f"\\$new = array("
            f"  'mac' => '{mac}',"
            f"  'ipaddr' => '{ip}',"
            f"  'hostname' => '{hostname}',"
            f"  'descr' => '{description}'"
            f");"
            f"\\$config['dhcpd']['{iface}']['staticmap'][] = \\$new;"
            f"write_config('Added DHCP reservation via FREQ');"
            f"services_dhcpd_configure();"
            f"echo 'OK';\""
        )
        r = _pf_ssh(cfg, php_cmd, timeout=30)
        json_response(
            handler,
            {
                "ok": r.returncode == 0 and "OK" in (r.stdout or ""),
                "action": "add",
                "mac": mac,
                "ip": ip,
                "hostname": hostname,
                "output": r.stdout[:500] if r.returncode == 0 else "",
                "error": r.stderr[:200] if r.returncode != 0 else "",
            },
        )
        return

    if action == "delete":
        mac = body.get("mac", "").strip()
        if not mac or not _SAFE_MAC.match(mac):
            json_response(handler, {"error": "MAC address required for delete"}, 400)
            return

        php_cmd = (
            f'php -r "'
            f"require_once('config.inc');"
            f"require_once('util.inc');"
            f"require_once('services.inc');"
            f"\\$config = parse_config(true);"
            f"\\$maps = &\\$config['dhcpd']['{iface}']['staticmap'];"
            f"if(is_array(\\$maps)) {{"
            f"  foreach(\\$maps as \\$k => \\$v) {{"
            f"    if(strtolower(\\$v['mac']) === strtolower('{mac}')) {{"
            f"      unset(\\$maps[\\$k]);"
            f"      \\$maps = array_values(\\$maps);"
            f"      write_config('Removed DHCP reservation via FREQ');"
            f"      services_dhcpd_configure();"
            f"      echo 'DELETED';"
            f"      exit(0);"
            f"    }}"
            f"  }}"
            f"}}"
            f"echo 'NOT_FOUND';\""
        )
        r = _pf_ssh(cfg, php_cmd, timeout=30)
        found = "DELETED" in (r.stdout or "")
        json_response(
            handler,
            {
                "ok": found,
                "action": "delete",
                "mac": mac,
                "output": r.stdout[:500] if r.returncode == 0 else "",
                "error": "Reservation not found"
                if not found and r.returncode == 0
                else (r.stderr[:200] if r.returncode != 0 else ""),
            },
        )
        return

    json_response(handler, {"error": f"Unknown action: {action}"}, 400)


def _parse_dhcp_static_maps(xml_text):
    """Parse staticmap XML fragments into list of dicts."""
    entries = []
    for block in re.findall(r"<staticmap>(.*?)</staticmap>", xml_text, re.DOTALL):
        entry = {}
        for field in ("mac", "ipaddr", "hostname", "descr"):
            m = re.search(rf"<{field}>(.*?)</{field}>", block)
            if m:
                entry[field] = m.group(1)
        if entry.get("mac"):
            entries.append(entry)
    return entries


# -- pfSense Config Backup --------------------------------------------------


def handle_pfsense_config_backup(handler):
    """POST /api/pfsense/config/backup -- download or create config backup.

    Body: {"action": "download|create|list"}
    """
    if require_post(handler, "pfSense config backup"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    action = body.get("action", "download")

    if action == "download":
        r = _pf_ssh(cfg, "cat /cf/conf/config.xml", timeout=20)
        if r.returncode == 0:
            json_response(
                handler,
                {
                    "ok": True,
                    "action": "download",
                    "config": r.stdout,
                    "size": len(r.stdout),
                },
            )
        else:
            json_response(handler, {"ok": False, "error": r.stderr[:200]}, 500)

    elif action == "create":
        cmd = (
            "cp /cf/conf/config.xml /cf/conf/backup/config-$(date +%Y%m%d_%H%M%S).xml 2>&1 && "
            "echo 'BACKUP_OK' || echo 'BACKUP_FAIL'"
        )
        r = _pf_ssh(cfg, cmd)
        json_response(
            handler,
            {
                "ok": r.returncode == 0 and "BACKUP_OK" in (r.stdout or ""),
                "action": "create",
                "output": r.stdout[:500],
            },
        )

    elif action == "list":
        cmd = "ls -la /cf/conf/backup/ 2>/dev/null | tail -20"
        r = _pf_ssh(cfg, cmd)
        json_response(handler, _pf_ok(r, "list"))

    else:
        json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- pfSense Reboot ---------------------------------------------------------


def handle_pfsense_reboot(handler):
    """POST /api/pfsense/reboot -- reboot pfSense.

    Body: {"confirm": true}
    """
    if require_post(handler, "pfSense reboot"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    if not body.get("confirm"):
        json_response(handler, {"error": "Must set confirm: true"}, 400)
        return

    _pf_ssh(cfg, "shutdown -r now", timeout=5)
    json_response(handler, {"ok": True, "message": "Reboot command sent"})


# -- pfSense Firewall Rules -------------------------------------------------


def handle_pfsense_rules(handler):
    """POST /api/pfsense/rules -- list, add, or delete firewall rules.

    Body: {"action": "list|add|delete", ...}
    List returns parsed pfctl output.
    Add/delete modify config.xml via PHP.
    """
    if require_post(handler, "pfSense rules"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    action = body.get("action", "list")

    if action == "list":
        cmd = (
            "pfctl -sr 2>/dev/null | grep -v '^scrub' | grep -v '^anchor' | "
            'sed \'s/ label "[^"]*"//g; s/ ridentifier [0-9]*//g\' | head -60'
        )
        r = _pf_ssh(cfg, cmd)
        json_response(handler, _pf_ok(r, "list"))
        return

    if action == "add":
        rule_type = body.get("type", "pass")  # pass or block
        direction = body.get("direction", "in")  # in or out
        interface = body.get("interface", "lan")
        proto = body.get("proto", "any")  # tcp, udp, icmp, any
        src = body.get("src", "any")
        dst = body.get("dst", "any")
        dst_port = body.get("dst_port", "")
        description = body.get("description", "Added by FREQ")

        # Validate
        if rule_type not in ("pass", "block"):
            json_response(handler, {"error": "type must be pass or block"}, 400)
            return
        if direction not in ("in", "out"):
            json_response(handler, {"error": "direction must be in or out"}, 400)
            return
        if proto not in ("tcp", "udp", "icmp", "any"):
            json_response(handler, {"error": "proto must be tcp, udp, icmp, or any"}, 400)
            return

        # Validate all inputs against safe patterns (prevent shell/PHP injection)
        if not _SAFE_IFACE.match(interface):
            json_response(handler, {"error": "Invalid interface name"}, 400)
            return
        if src != "any" and not _SAFE_CIDR.match(src):
            json_response(handler, {"error": "Invalid source (use 'any' or CIDR)"}, 400)
            return
        if dst != "any" and not _SAFE_CIDR.match(dst):
            json_response(handler, {"error": "Invalid destination (use 'any' or CIDR)"}, 400)
            return
        if dst_port and not re.match(r"^\d{1,5}$", dst_port):
            json_response(handler, {"error": "Invalid port number"}, 400)
            return
        if not _SAFE_TEXT.match(description):
            json_response(handler, {"error": "Invalid description"}, 400)
            return

        port_part = ""
        if dst_port and proto in ("tcp", "udp"):
            port_part = f"'dstport' => '{dst_port}',"

        proto_part = f"'protocol' => '{proto}'," if proto != "any" else ""

        php_cmd = (
            f'php -r "'
            f"require_once('config.inc');"
            f"require_once('util.inc');"
            f"require_once('filter.inc');"
            f"\\$config = parse_config(true);"
            f"if(!isset(\\$config['filter']['rule'])) \\$config['filter']['rule'] = array();"
            f"\\$rule = array("
            f"  'type' => '{rule_type}',"
            f"  'interface' => '{interface}',"
            f"  'direction' => '{direction}',"
            f"  {proto_part}"
            f"  'source' => array('address' => '{src}'),"
            f"  'destination' => array('address' => '{dst}', {port_part}),"
            f"  'descr' => '{description}'"
            f");"
            f"\\$config['filter']['rule'][] = \\$rule;"
            f"write_config('Added firewall rule via FREQ');"
            f"filter_configure();"
            f"echo 'OK';\""
        )
        r = _pf_ssh(cfg, php_cmd, timeout=30)
        json_response(
            handler,
            {
                "ok": r.returncode == 0 and "OK" in (r.stdout or ""),
                "action": "add",
                "output": r.stdout[:500] if r.returncode == 0 else "",
                "error": r.stderr[:200] if r.returncode != 0 else "",
            },
        )
        return

    if action == "delete":
        index = body.get("index")
        if index is None:
            json_response(handler, {"error": "index required for delete"}, 400)
            return
        try:
            idx = int(index)
        except (ValueError, TypeError):
            json_response(handler, {"error": "index must be integer"}, 400)
            return

        php_cmd = (
            f'php -r "'
            f"require_once('config.inc');"
            f"require_once('util.inc');"
            f"require_once('filter.inc');"
            f"\\$config = parse_config(true);"
            f"if(isset(\\$config['filter']['rule'][{idx}])) {{"
            f"  unset(\\$config['filter']['rule'][{idx}]);"
            f"  \\$config['filter']['rule'] = array_values(\\$config['filter']['rule']);"
            f"  write_config('Deleted firewall rule via FREQ');"
            f"  filter_configure();"
            f"  echo 'DELETED';"
            f"}} else {{ echo 'NOT_FOUND'; }}\""
        )
        r = _pf_ssh(cfg, php_cmd, timeout=30)
        found = "DELETED" in (r.stdout or "")
        json_response(
            handler,
            {
                "ok": found,
                "action": "delete",
                "index": idx,
                "output": r.stdout[:500] if r.returncode == 0 else "",
                "error": "Rule not found"
                if not found and r.returncode == 0
                else (r.stderr[:200] if r.returncode != 0 else ""),
            },
        )
        return

    json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- pfSense NAT Rules ------------------------------------------------------


def handle_pfsense_nat(handler):
    """POST /api/pfsense/nat -- manage NAT/port forward rules.

    Body: {"action": "list|add|delete", ...}
    """
    if require_post(handler, "pfSense NAT"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    action = body.get("action", "list")

    if action == "list":
        cmd = "pfctl -sn 2>/dev/null | head -40"
        r = _pf_ssh(cfg, cmd)
        json_response(handler, _pf_ok(r, "list"))
        return

    if action == "add":
        interface = body.get("interface", "wan")
        proto = body.get("proto", "tcp")
        src_port = body.get("src_port", "")
        dst_ip = body.get("dst_ip", "")
        dst_port = body.get("dst_port", "")
        description = body.get("description", "Port forward via FREQ")

        if proto not in ("tcp", "udp", "tcp/udp"):
            json_response(handler, {"error": "proto must be tcp, udp, or tcp/udp"}, 400)
            return
        if not src_port or not dst_ip or not dst_port:
            json_response(handler, {"error": "src_port, dst_ip, dst_port required"}, 400)
            return
        if not _SAFE_IP.match(dst_ip):
            json_response(handler, {"error": "Invalid dst_ip"}, 400)
            return
        if not _SAFE_IFACE.match(interface):
            json_response(handler, {"error": "Invalid interface name"}, 400)
            return
        if not re.match(r"^\d{1,5}$", src_port):
            json_response(handler, {"error": "Invalid source port"}, 400)
            return
        if not re.match(r"^\d{1,5}$", dst_port):
            json_response(handler, {"error": "Invalid destination port"}, 400)
            return
        if not _SAFE_TEXT.match(description):
            json_response(handler, {"error": "Invalid description"}, 400)
            return

        php_cmd = (
            f'php -r "'
            f"require_once('config.inc');"
            f"require_once('util.inc');"
            f"require_once('filter.inc');"
            f"\\$config = parse_config(true);"
            f"if(!isset(\\$config['nat']['rule'])) \\$config['nat']['rule'] = array();"
            f"\\$rule = array("
            f"  'interface' => '{interface}',"
            f"  'protocol' => '{proto}',"
            f"  'source' => array('any' => ''),"
            f"  'destination' => array('any' => '', 'port' => '{src_port}'),"
            f"  'target' => '{dst_ip}',"
            f"  'local-port' => '{dst_port}',"
            f"  'descr' => '{description}'"
            f");"
            f"\\$config['nat']['rule'][] = \\$rule;"
            f"write_config('Added NAT rule via FREQ');"
            f"filter_configure();"
            f"echo 'OK';\""
        )
        r = _pf_ssh(cfg, php_cmd, timeout=30)
        json_response(
            handler,
            {
                "ok": r.returncode == 0 and "OK" in (r.stdout or ""),
                "action": "add",
                "output": r.stdout[:500] if r.returncode == 0 else "",
                "error": r.stderr[:200] if r.returncode != 0 else "",
            },
        )
        return

    if action == "delete":
        index = body.get("index")
        if index is None:
            json_response(handler, {"error": "index required"}, 400)
            return
        try:
            idx = int(index)
        except (ValueError, TypeError):
            json_response(handler, {"error": "index must be integer"}, 400)
            return

        php_cmd = (
            f'php -r "'
            f"require_once('config.inc');"
            f"require_once('util.inc');"
            f"require_once('filter.inc');"
            f"\\$config = parse_config(true);"
            f"if(isset(\\$config['nat']['rule'][{idx}])) {{"
            f"  unset(\\$config['nat']['rule'][{idx}]);"
            f"  \\$config['nat']['rule'] = array_values(\\$config['nat']['rule']);"
            f"  write_config('Deleted NAT rule via FREQ');"
            f"  filter_configure();"
            f"  echo 'DELETED';"
            f"}} else {{ echo 'NOT_FOUND'; }}\""
        )
        r = _pf_ssh(cfg, php_cmd, timeout=30)
        found = "DELETED" in (r.stdout or "")
        json_response(
            handler,
            {
                "ok": found,
                "action": "delete",
                "index": idx,
                "output": r.stdout[:500],
                "error": "" if found else "Rule not found",
            },
        )
        return

    json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- pfSense WireGuard Peer Management --------------------------------------


def handle_pfsense_wg_peer(handler):
    """POST /api/pfsense/wg/peer -- manage WireGuard peers.

    Body: {"action": "list|add|remove", "interface": "wg0",
           "public_key": "...", "allowed_ips": "10.25.100.x/32",
           "endpoint": "1.2.3.4:51820", "description": "..."}
    """
    if require_post(handler, "WireGuard peer"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    action = body.get("action", "list")
    iface = body.get("interface", "wg0").strip()

    if not _SAFE_IFACE.match(iface):
        json_response(handler, {"error": "Invalid interface name"}, 400)
        return

    if action == "list":
        cmd = f"wg show {iface} 2>/dev/null || wg show 2>/dev/null || echo 'No WireGuard tunnels'"
        r = _pf_ssh(cfg, cmd)
        json_response(handler, _pf_ok(r, "list"))
        return

    if action == "add":
        pubkey = body.get("public_key", "").strip()
        allowed_ips = body.get("allowed_ips", "").strip()
        endpoint = body.get("endpoint", "").strip()
        psk = body.get("preshared_key", "").strip()

        if not pubkey:
            json_response(handler, {"error": "public_key required"}, 400)
            return
        if not allowed_ips or not _SAFE_CIDR.match(allowed_ips):
            json_response(handler, {"error": "allowed_ips required (e.g. 10.25.100.5/32)"}, 400)
            return
        if not _SAFE_WG_KEY.match(pubkey):
            json_response(handler, {"error": "Invalid public key format"}, 400)
            return
        if endpoint and not re.match(r"^[0-9a-fA-F.:]+:\d{1,5}$", endpoint):
            json_response(handler, {"error": "Invalid endpoint (format: ip:port)"}, 400)
            return
        if psk and not _SAFE_WG_KEY.match(psk):
            json_response(handler, {"error": "Invalid preshared key format"}, 400)
            return

        cmd = f"wg set {iface} peer {pubkey} allowed-ips {allowed_ips}"
        if endpoint:
            cmd += f" endpoint {endpoint}"
        if psk:
            cmd += f" preshared-key <(echo '{psk}')"

        r = _pf_ssh(cfg, cmd, timeout=10)
        json_response(
            handler,
            {
                "ok": r.returncode == 0,
                "action": "add",
                "public_key": pubkey,
                "allowed_ips": allowed_ips,
                "output": r.stdout[:500] if r.returncode == 0 else "",
                "error": r.stderr[:200] if r.returncode != 0 else "",
            },
        )
        return

    if action == "remove":
        pubkey = body.get("public_key", "").strip()
        if not pubkey or not _SAFE_WG_KEY.match(pubkey):
            json_response(handler, {"error": "Valid public_key required"}, 400)
            return

        cmd = f"wg set {iface} peer {pubkey} remove"
        r = _pf_ssh(cfg, cmd, timeout=10)
        json_response(
            handler,
            {
                "ok": r.returncode == 0,
                "action": "remove",
                "public_key": pubkey,
                "output": r.stdout[:500] if r.returncode == 0 else "",
                "error": r.stderr[:200] if r.returncode != 0 else "",
            },
        )
        return

    json_response(handler, {"error": f"Unknown action: {action}"}, 400)


# -- pfSense System Updates --------------------------------------------------


def handle_pfsense_updates(handler):
    """POST /api/pfsense/updates -- check for or apply system updates.

    Body: {"action": "check"}
    """
    if require_post(handler, "pfSense update"):
        return
    cfg, ok = _require_pfsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    action = body.get("action", "check")

    if action == "check":
        cmd = "pkg update -f 2>/dev/null; pkg version -vIL= 2>/dev/null | head -30"
        r = _pf_ssh(cfg, cmd, timeout=30)
        json_response(handler, _pf_ok(r, "check"))
    else:
        json_response(handler, {"error": "Only 'check' is supported (apply via pfSense WebGUI)"}, 400)


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register pfSense API routes."""
    routes["/api/pfsense/service"] = handle_pfsense_service
    routes["/api/pfsense/dhcp/reservation"] = handle_pfsense_dhcp_reservation
    routes["/api/pfsense/config/backup"] = handle_pfsense_config_backup
    routes["/api/pfsense/reboot"] = handle_pfsense_reboot
    routes["/api/pfsense/rules"] = handle_pfsense_rules
    routes["/api/pfsense/nat"] = handle_pfsense_nat
    routes["/api/pfsense/wg/peer"] = handle_pfsense_wg_peer
    routes["/api/pfsense/updates"] = handle_pfsense_updates
