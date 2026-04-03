"""VPN management for FREQ — WireGuard, OpenVPN, IPsec.

Domain: freq vpn <action>
What: Manage VPN peers, tunnels, and status. WireGuard peer lifecycle,
      OpenVPN cert management, IPsec tunnel monitoring.
Replaces: pfSense VPN GUI, manual wg commands, manual cert generation
Architecture:
    - WireGuard: SSH to pfSense/host running wg, parse wg show output
    - OpenVPN: SSH to parse status file, cert management via easy-rsa
    - IPsec: SSH to parse strongswan/racoon status
    - Data stored in conf/vpn/
Design decisions:
    - SSH-first. REST API integration is future work when pfrest is common.
    - Peer configs stored locally in conf/vpn/peers/ for export/provisioning.
    - QR code generation for WireGuard uses qrencode CLI if available.
"""

import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VPN_DIR = "vpn"


def _vpn_dir(cfg):
    """Return VPN data directory."""
    path = os.path.join(cfg.conf_dir, VPN_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _vpn_ssh(ip, cmd, cfg, timeout=10):
    """Run command on VPN host via SSH."""
    r = ssh_run(
        host=ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pfsense",
        use_sudo=True,
    )
    return r.stdout or "", r.returncode == 0


def _get_vpn_host(cfg):
    """Get VPN host IP (typically the firewall)."""
    if cfg.pfsense_ip:
        return cfg.pfsense_ip
    for h in cfg.hosts:
        if h.htype in ("pfsense", "opnsense"):
            return h.ip
    return None


# ---------------------------------------------------------------------------
# Commands — WireGuard
# ---------------------------------------------------------------------------


def cmd_vpn_wg_status(cfg: FreqConfig, pack, args) -> int:
    """Show WireGuard tunnel status."""
    ip = _get_vpn_host(cfg)
    if not ip:
        fmt.error("No VPN host configured (need pfsense_ip or a pfsense host in hosts.conf)")
        return 1

    fmt.header("WireGuard Status", breadcrumb="FREQ > VPN > WireGuard")
    fmt.blank()

    out, ok = _vpn_ssh(ip, "wg show all 2>/dev/null", cfg)
    if not ok or not out.strip():
        fmt.warn("WireGuard not running or wg command not available")
        fmt.footer()
        return 1

    peers = _parse_wg_show(out)
    if not peers:
        fmt.info("No WireGuard peers configured")
        fmt.footer()
        return 0

    fmt.table_header(("Interface", 12), ("Peer", 20), ("Endpoint", 22), ("Latest Handshake", 18), ("Transfer", 16))
    for p in peers:
        # Truncate public key for display
        key_short = p.get("public_key", "")[:16] + "..."
        handshake = p.get("latest_handshake", "never")
        transfer = p.get("transfer", "")
        endpoint = p.get("endpoint", "none")

        fmt.table_row(
            (p.get("interface", ""), 12),
            (key_short, 20),
            (endpoint, 22),
            (handshake, 18),
            (transfer, 16),
        )

    fmt.blank()
    active = sum(1 for p in peers if p.get("latest_handshake", "never") != "never")
    fmt.info(f"{active}/{len(peers)} peers active")
    logger.info("vpn_wg_status", peers=len(peers), active=active)
    fmt.footer()
    return 0


def cmd_vpn_wg_peers(cfg: FreqConfig, pack, args) -> int:
    """List WireGuard peers with details."""
    ip = _get_vpn_host(cfg)
    if not ip:
        fmt.error("No VPN host configured")
        return 1

    fmt.header("WireGuard Peers", breadcrumb="FREQ > VPN > WireGuard")
    fmt.blank()

    out, ok = _vpn_ssh(ip, "wg show all dump 2>/dev/null", cfg)
    if not ok or not out.strip():
        fmt.warn("WireGuard not running or no peers")
        fmt.footer()
        return 1

    peers = _parse_wg_dump(out)
    for p in peers:
        fmt.line(f"{fmt.C.BOLD}{p.get('interface', '?')}{fmt.C.RESET}")
        fmt.line(f"  Public Key:       {p.get('public_key', '?')}")
        fmt.line(f"  Endpoint:         {p.get('endpoint', 'none')}")
        fmt.line(f"  Allowed IPs:      {p.get('allowed_ips', 'none')}")
        fmt.line(f"  Latest Handshake: {p.get('latest_handshake', 'never')}")
        fmt.line(f"  Transfer:         RX {p.get('rx', '0')} / TX {p.get('tx', '0')}")
        fmt.blank()

    fmt.info(f"{len(peers)} peer(s)")
    fmt.footer()
    return 0


def cmd_vpn_wg_audit(cfg: FreqConfig, pack, args) -> int:
    """Audit WireGuard peers — find stale/inactive peers."""
    ip = _get_vpn_host(cfg)
    if not ip:
        fmt.error("No VPN host configured")
        return 1

    fmt.header("WireGuard Audit", breadcrumb="FREQ > VPN > WireGuard")
    fmt.blank()

    out, ok = _vpn_ssh(ip, "wg show all dump 2>/dev/null", cfg)
    if not ok:
        fmt.warn("WireGuard not available")
        fmt.footer()
        return 1

    peers = _parse_wg_dump(out)
    stale = []
    for p in peers:
        handshake = p.get("latest_handshake_epoch", 0)
        if handshake == 0:
            stale.append((p, "never connected"))
        elif time.time() - handshake > 86400 * 30:  # 30 days
            days = int((time.time() - handshake) / 86400)
            stale.append((p, f"inactive {days} days"))

    if stale:
        fmt.warn(f"{len(stale)} stale peer(s):")
        for p, reason in stale:
            key_short = p.get("public_key", "")[:20] + "..."
            fmt.line(f"  {fmt.C.YELLOW}{key_short}{fmt.C.RESET} — {reason}")
    else:
        fmt.success(f"All {len(peers)} peers are active")

    fmt.blank()
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — OpenVPN
# ---------------------------------------------------------------------------


def cmd_vpn_ovpn_status(cfg: FreqConfig, pack, args) -> int:
    """Show OpenVPN server status."""
    ip = _get_vpn_host(cfg)
    if not ip:
        fmt.error("No VPN host configured")
        return 1

    fmt.header("OpenVPN Status", breadcrumb="FREQ > VPN > OpenVPN")
    fmt.blank()

    out, ok = _vpn_ssh(
        ip, "cat /var/log/openvpn-status.log 2>/dev/null || cat /tmp/openvpn-status.log 2>/dev/null", cfg
    )
    if not ok or not out.strip():
        fmt.warn("OpenVPN status log not found — server may not be running")
        fmt.footer()
        return 1

    clients = _parse_ovpn_status(out)
    if clients:
        fmt.table_header(("Client", 20), ("Real Address", 22), ("Virtual IP", 16), ("Connected Since", 20))
        for c in clients:
            fmt.table_row(
                (c.get("name", ""), 20),
                (c.get("real_address", ""), 22),
                (c.get("virtual_ip", ""), 16),
                (c.get("connected_since", ""), 20),
            )
        fmt.blank()
        fmt.info(f"{len(clients)} connected client(s)")
    else:
        fmt.info("No connected clients")

    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _parse_wg_show(text):
    """Parse 'wg show all' output into list of peer dicts."""
    peers = []
    current_iface = ""

    for line in text.splitlines():
        line = line.strip()
        if line.startswith("interface:"):
            current_iface = line.split(":", 1)[1].strip()
        elif line.startswith("peer:"):
            peers.append(
                {
                    "interface": current_iface,
                    "public_key": line.split(":", 1)[1].strip(),
                }
            )
        elif line.startswith("endpoint:") and peers:
            peers[-1]["endpoint"] = line.split(":", 1)[1].strip()
        elif line.startswith("latest handshake:") and peers:
            peers[-1]["latest_handshake"] = line.split(":", 1)[1].strip()
        elif line.startswith("transfer:") and peers:
            peers[-1]["transfer"] = line.split(":", 1)[1].strip()
        elif line.startswith("allowed ips:") and peers:
            peers[-1]["allowed_ips"] = line.split(":", 1)[1].strip()

    return peers


def _parse_wg_dump(text):
    """Parse 'wg show all dump' output into list of peer dicts."""
    peers = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        # Skip interface lines (4 fields)
        if len(parts) >= 8:
            peers.append(
                {
                    "interface": parts[0],
                    "public_key": parts[1],
                    "endpoint": parts[3] if parts[3] != "(none)" else "none",
                    "allowed_ips": parts[4],
                    "latest_handshake_epoch": int(parts[5]) if parts[5] != "0" else 0,
                    "latest_handshake": time.strftime("%Y-%m-%d %H:%M", time.localtime(int(parts[5])))
                    if parts[5] != "0"
                    else "never",
                    "rx": parts[6],
                    "tx": parts[7] if len(parts) > 7 else "0",
                }
            )
    return peers


def _parse_ovpn_status(text):
    """Parse OpenVPN status log into list of client dicts."""
    clients = []
    in_clients = False

    for line in text.splitlines():
        if "CONNECTED" in line and "CLIENT_LIST" not in line:
            continue
        if line.startswith("CLIENT_LIST,") or line.startswith("HEADER,CLIENT_LIST"):
            in_clients = True
            continue
        if line.startswith("ROUTING_TABLE") or line.startswith("HEADER,ROUTING"):
            in_clients = False
            continue

        if in_clients and "," in line:
            parts = line.split(",")
            if len(parts) >= 5:
                clients.append(
                    {
                        "name": parts[0] if not parts[0].startswith("HEADER") else parts[1],
                        "real_address": parts[1] if len(parts) > 1 else "",
                        "virtual_ip": parts[2] if len(parts) > 2 else "",
                        "connected_since": parts[4] if len(parts) > 4 else "",
                    }
                )

    return clients
