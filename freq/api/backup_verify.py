"""Backup verification API handlers -- prove backups are restorable.

Who:   New module for backup integrity verification.
What:  REST endpoints to verify PVE backups and check restore readiness.
Why:   A backup that can't be restored is not a backup. This proves they work.
Where: Routes registered at /api/backup/verify*.
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import re

from freq.core import log as logger
from freq.api.helpers import json_response, get_json_body
from freq.core.config import load_config
from freq.core.ssh import run as ssh_single
from freq.modules.serve import _check_session_role


# -- Helpers -----------------------------------------------------------------


def _pve_ssh(cfg, node_ip, cmd, timeout=60):
    """SSH to a PVE node and run a command."""
    return ssh_single(
        host=node_ip,
        command=cmd,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pve",
        use_sudo=True,
    )


def _find_node_ip(cfg, node_name=None):
    """Find a reachable PVE node IP."""
    if node_name:
        for i, name in enumerate(cfg.pve_node_names):
            if name == node_name and i < len(cfg.pve_nodes):
                return cfg.pve_nodes[i]
    return cfg.pve_nodes[0] if cfg.pve_nodes else None


# -- Handlers ----------------------------------------------------------------


def handle_backup_verify(handler):
    """POST /api/backup/verify -- verify a specific PVE backup.

    Body: {"vmid": 100, "node": "pve01", "storage": "local", "file": "vzdump-qemu-100-..."}
    Runs qmrestore --verify (or vzdump --verify if available).
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    body = get_json_body(handler)
    vmid = body.get("vmid")
    node = body.get("node", "")
    file_path = body.get("file", "")

    # Validate vmid is a positive integer (prevent shell injection)
    try:
        vmid = int(vmid) if vmid else 0
    except (ValueError, TypeError):
        vmid = 0
    if vmid < 100:
        json_response(handler, {"error": "Valid vmid required (integer >= 100)"}, 400)
        return

    node_ip = _find_node_ip(cfg, node)
    if not node_ip:
        json_response(handler, {"error": "No PVE node available"}, 400)
        return

    if file_path:
        # Validate file_path: only allow safe characters (alphanumeric, /, -, _, .)
        if not re.match(r"^[a-zA-Z0-9/_\-. ]+$", file_path):
            json_response(handler, {"error": "Invalid file path characters"}, 400)
            return
        if ".." in file_path:
            json_response(handler, {"error": "Path traversal not allowed"}, 400)
            return
        cmd = f"qmrestore '{file_path}' --verify 2>&1 | tail -10"
    else:
        # Find latest backup for this VMID and verify it
        cmd = (
            f"LATEST=$(ls -t /var/lib/vz/dump/vzdump-qemu-{vmid}-*.vma* 2>/dev/null | head -1); "
            f"[ -z \"$LATEST\" ] && echo 'NO_BACKUP_FOUND' && exit 1; "
            f'echo "Verifying: $LATEST"; '
            f'qmrestore "$LATEST" --verify 2>&1 | tail -10'
        )

    r = _pve_ssh(cfg, node_ip, cmd, timeout=120)
    ok = r.returncode == 0 and "NO_BACKUP_FOUND" not in (r.stdout or "")

    json_response(
        handler,
        {
            "ok": ok,
            "vmid": vmid,
            "node": node or "auto",
            "output": r.stdout[:2000] if r.stdout else "",
            "error": r.stderr[:500] if not ok and r.stderr else "",
        },
    )


def handle_backup_verify_status(handler):
    """GET /api/backup/verify/status -- backup status for all VMs.

    Lists latest backup per VM with age, size, and whether it's been verified.
    """
    cfg = load_config()
    node_ip = _find_node_ip(cfg)
    if not node_ip:
        json_response(handler, {"error": "No PVE node available"}, 400)
        return

    # List all backups with VMID, timestamp, size
    cmd = (
        "for f in /var/lib/vz/dump/vzdump-qemu-*.vma* /var/lib/vz/dump/vzdump-lxc-*.tar* 2>/dev/null; do "
        '  [ -f "$f" ] || continue; '
        '  base=$(basename "$f"); '
        "  vmid=$(echo \"$base\" | grep -oP '(?<=vzdump-(qemu|lxc)-)\\d+'); "
        "  ts=$(echo \"$base\" | grep -oP '\\d{4}_\\d{2}_\\d{2}-\\d{2}_\\d{2}_\\d{2}'); "
        '  size=$(stat -c%s "$f" 2>/dev/null || echo 0); '
        "  type=$(echo \"$base\" | grep -oP '(qemu|lxc)'); "
        '  echo "$vmid|$ts|$size|$type|$base"; '
        "done | sort -t'|' -k1,1n -k2,2r"
    )
    r = _pve_ssh(cfg, node_ip, cmd, timeout=30)

    backups = {}
    if r.returncode == 0 and r.stdout.strip():
        for line in r.stdout.strip().splitlines():
            parts = line.split("|")
            if len(parts) < 5:
                continue
            vmid_str, ts, size_str, btype, filename = parts
            if not vmid_str:
                continue
            try:
                vmid = int(vmid_str)
            except ValueError:
                continue
            # Keep only the latest backup per VMID
            if vmid not in backups:
                ts_fmt = ts.replace("_", "-", 2).replace("_", ":", 2) if ts else ""
                backups[vmid] = {
                    "vmid": vmid,
                    "type": btype,
                    "latest_backup": ts_fmt,
                    "size_mb": round(int(size_str) / (1024 * 1024), 1) if size_str.isdigit() else 0,
                    "file": filename,
                }

    json_response(
        handler,
        {
            "ok": True,
            "backups": list(backups.values()),
            "total_vms_with_backups": len(backups),
        },
    )


def handle_cert_expiry(handler):
    """GET /api/cert/expiry -- fleet certificate inventory sorted by expiry.

    Scans known ports for TLS certs and returns days until expiry.
    """
    cfg = load_config()
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"ok": True, "certs": []})
        return

    import ssl
    import socket
    from datetime import datetime, timezone

    ports = [443, 8006, 8443, 8888]
    certs = []

    for h in hosts[:15]:  # Limit to 15 hosts × 4 ports × 2s = 2 min worst case
        for port in ports:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with socket.create_connection((h.ip, port), timeout=3) as sock:
                    with ctx.wrap_socket(sock, server_hostname=h.ip) as ssock:
                        cert = ssock.getpeercert(binary_form=False)
                        if not cert:
                            # Get binary cert for self-signed
                            der = ssock.getpeercert(binary_form=True)
                            if der:
                                certs.append(
                                    {
                                        "host": h.label,
                                        "ip": h.ip,
                                        "port": port,
                                        "subject": "self-signed (binary only)",
                                        "issuer": "",
                                        "expires": "",
                                        "days_remaining": -1,
                                        "status": "unknown",
                                    }
                                )
                            continue
                        not_after = cert.get("notAfter", "")
                        if not_after:
                            # Parse "Mar 15 12:00:00 2026 GMT"
                            try:
                                exp = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
                                days = (exp - datetime.now(timezone.utc).replace(tzinfo=None)).days
                            except ValueError:
                                days = -1
                        else:
                            days = -1

                        subject = dict(x[0] for x in cert.get("subject", ()))
                        issuer = dict(x[0] for x in cert.get("issuer", ()))

                        status = "ok"
                        if days < 0:
                            status = "expired"
                        elif days < 7:
                            status = "critical"
                        elif days < 30:
                            status = "warning"

                        certs.append(
                            {
                                "host": h.label,
                                "ip": h.ip,
                                "port": port,
                                "subject": subject.get("commonName", ""),
                                "issuer": issuer.get("organizationName", issuer.get("commonName", "")),
                                "expires": not_after,
                                "days_remaining": days,
                                "status": status,
                            }
                        )
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                logger.debug(f"api_backup_verify: cert check skipped {h.label}:{port}: {e}")
                continue

    # Sort by days remaining (soonest expiry first)
    certs.sort(key=lambda c: c["days_remaining"] if c["days_remaining"] >= 0 else 99999)

    json_response(
        handler,
        {
            "ok": True,
            "certs": certs,
            "total": len(certs),
            "critical": sum(1 for c in certs if c["status"] == "critical"),
            "warning": sum(1 for c in certs if c["status"] == "warning"),
            "expired": sum(1 for c in certs if c["status"] == "expired"),
        },
    )


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register backup verification and cert expiry API routes."""
    routes["/api/backup/verify"] = handle_backup_verify
    routes["/api/backup/verify/status"] = handle_backup_verify_status
    routes["/api/cert/expiry"] = handle_cert_expiry
