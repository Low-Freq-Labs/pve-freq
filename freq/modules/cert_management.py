"""Certificate lifecycle management for FREQ — ACME, CA, fleet deployment.

Domain: freq cert <acme|ca|inspect|deploy> <action>
What: Issue certificates via ACME (Let's Encrypt), manage private CA,
      inspect certs on endpoints, deploy certs to fleet hosts.
      Extends existing cert.py scan/list/check with write operations.
Replaces: Manual certbot runs, step-ca CLI, SCP cert files, cert tracking
Architecture:
    - ACME: shells to certbot for issuance, parses output
    - CA: shells to step-ca for private CA operations
    - Deploy: SCP via ssh.py to push certs to target hosts
    - Inventory: extends conf/certs/ with issued cert tracking
Design decisions:
    - Shell to certbot/step-ca, not implement ACME protocol. Zero deps.
    - Track issued certs in JSON for renewal/expiry monitoring.
    - Deploy is SCP + service reload via SSH — works everywhere.
"""
import json
import os
import re
import ssl
import socket
import subprocess
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Data Storage
# ---------------------------------------------------------------------------

CERT_DIR = "certs"


def _cert_dir(cfg):
    """Return cert data directory."""
    path = os.path.join(cfg.conf_dir, CERT_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_issued(cfg):
    """Load issued certificate inventory."""
    filepath = os.path.join(_cert_dir(cfg), "issued.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return {"certs": []}


def _save_issued(cfg, data):
    """Save issued certificate inventory."""
    filepath = os.path.join(_cert_dir(cfg), "issued.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Commands — Certificate Inspection
# ---------------------------------------------------------------------------

def cmd_cert_inspect(cfg: FreqConfig, pack, args) -> int:
    """Inspect TLS certificate on a host:port."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq cert inspect <host:port>")
        return 1

    # Parse host:port
    if ":" in target:
        host, port_str = target.rsplit(":", 1)
        port = int(port_str)
    else:
        host = target
        port = 443

    fmt.header(f"Certificate: {host}:{port}", breadcrumb="FREQ > Cert")
    fmt.blank()

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert(binary_form=False)
                der = ssock.getpeercert(binary_form=True)
    except Exception as e:
        fmt.error(f"Could not connect to {host}:{port}: {e}")
        return 1

    if not cert:
        # Binary cert only — parse what we can
        fmt.warn("Certificate retrieved but no parsed data (self-signed or invalid chain)")
        fmt.footer()
        return 1

    # Display cert details
    subject = dict(x[0] for x in cert.get("subject", []))
    issuer = dict(x[0] for x in cert.get("issuer", []))
    not_before = cert.get("notBefore", "")
    not_after = cert.get("notAfter", "")
    sans = [entry[1] for entry in cert.get("subjectAltName", [])]

    fmt.line(f"{fmt.C.BOLD}Subject:{fmt.C.RESET}     {subject.get('commonName', '?')}")
    fmt.line(f"{fmt.C.BOLD}Issuer:{fmt.C.RESET}      {issuer.get('organizationName', issuer.get('commonName', '?'))}")
    fmt.line(f"{fmt.C.BOLD}Valid From:{fmt.C.RESET}   {not_before}")
    fmt.line(f"{fmt.C.BOLD}Valid Until:{fmt.C.RESET}  {not_after}")
    if sans:
        fmt.line(f"{fmt.C.BOLD}SANs:{fmt.C.RESET}        {', '.join(sans[:5])}")
        if len(sans) > 5:
            fmt.line(f"              ... and {len(sans) - 5} more")
    fmt.line(f"{fmt.C.BOLD}Serial:{fmt.C.RESET}      {cert.get('serialNumber', '?')}")

    # Check expiry
    try:
        from datetime import datetime
        expiry = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z")
        days_left = (expiry - datetime.utcnow()).days
        if days_left < 0:
            fmt.blank()
            fmt.error(f"EXPIRED {abs(days_left)} days ago!")
        elif days_left < 30:
            fmt.blank()
            fmt.warn(f"Expires in {days_left} days")
        else:
            fmt.blank()
            fmt.success(f"{days_left} days until expiry")
    except (ValueError, ImportError):
        pass

    fmt.blank()
    logger.info("cert_inspect", target=f"{host}:{port}")
    fmt.footer()
    return 0


def cmd_cert_fleet_check(cfg: FreqConfig, pack, args) -> int:
    """Check TLS certificates across all fleet hosts."""
    fmt.header("Fleet Certificate Check", breadcrumb="FREQ > Cert")
    fmt.blank()

    # Check common ports on all hosts
    ports = [443, 8443, 8006, 9090]
    results = []

    for h in cfg.hosts:
        for port in ports:
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                with socket.create_connection((h.ip, port), timeout=2) as sock:
                    with ctx.wrap_socket(sock, server_hostname=h.ip) as ssock:
                        cert = ssock.getpeercert(binary_form=False)
                        if cert:
                            not_after = cert.get("notAfter", "")
                            subject = dict(x[0] for x in cert.get("subject", []))
                            cn = subject.get("commonName", "?")
                            results.append({
                                "host": h.label, "port": port,
                                "cn": cn, "expires": not_after,
                            })
            except (ConnectionRefusedError, socket.timeout, OSError):
                continue

    if results:
        fmt.table_header(("Host", 14), ("Port", 6), ("CN", 24), ("Expires", 24))
        for r in results:
            fmt.table_row(
                (r["host"], 14),
                (str(r["port"]), 6),
                (r["cn"], 24),
                (r["expires"], 24),
            )
        fmt.blank()
        fmt.info(f"{len(results)} TLS endpoint(s) found")
    else:
        fmt.warn("No TLS endpoints found on standard ports")

    fmt.footer()
    return 0


def cmd_cert_acme_status(cfg: FreqConfig, pack, args) -> int:
    """Show ACME (Let's Encrypt) certificate status."""
    fmt.header("ACME Certificates", breadcrumb="FREQ > Cert > ACME")
    fmt.blank()

    # Check if certbot is available
    try:
        r = subprocess.run(["certbot", "certificates"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                fmt.line(f"  {fmt.C.DIM}{line}{fmt.C.RESET}")
        else:
            fmt.warn("certbot returned an error (may need sudo)")
            if r.stderr:
                fmt.line(f"  {fmt.C.DIM}{r.stderr[:200]}{fmt.C.RESET}")
    except FileNotFoundError:
        fmt.warn("certbot not installed")
        fmt.info("Install certbot using your package manager (apt, dnf, pacman, etc.)")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_cert_issued_list(cfg: FreqConfig, pack, args) -> int:
    """List tracked issued certificates."""
    data = _load_issued(cfg)
    certs = data.get("certs", [])

    fmt.header("Issued Certificates", breadcrumb="FREQ > Cert")
    fmt.blank()

    if not certs:
        fmt.info("No tracked certificates")
        fmt.footer()
        return 0

    fmt.table_header(("Domain", 24), ("Type", 8), ("Issued", 12), ("Expires", 12))
    for c in certs:
        fmt.table_row(
            (c.get("domain", ""), 24),
            (c.get("type", ""), 8),
            (c.get("issued", ""), 12),
            (c.get("expires", ""), 12),
        )

    fmt.blank()
    fmt.info(f"{len(certs)} certificate(s)")
    fmt.footer()
    return 0
