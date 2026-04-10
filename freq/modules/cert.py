"""Fleet-wide TLS certificate inventory and lifecycle for FREQ.

Domain: freq cert <scan|list|check>

Scans every fleet host for TLS certificates on common ports (443, 8006,
8443, 9090, etc.). Tracks expiry, issuer, subject, and self-signed status.
One command to know every cert in your infrastructure and when it dies.

Replaces: Manual cert tracking in spreadsheets, certbot cron scripts,
          Let's Encrypt GUIs ($0 but no fleet awareness)

Architecture:
    - Scanning uses ssl + socket (stdlib) to connect and read certs
    - Parallel SSH probes via ssh_run_many for fleet-wide port checks
    - Inventory persisted in conf/certs/cert-inventory.json
    - Expiry thresholds: 7d critical, 30d warning

Design decisions:
    - Scans real TLS handshakes, not config files. What the network sees
      is what matters, not what you think is deployed.
"""

import json
import os
import ssl
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many, result_for

# Storage
CERT_DIR = "certs"
CERT_FILE = "cert-inventory.json"
CERT_CMD_TIMEOUT = 15
CERT_CONNECT_TIMEOUT = 5

# Default ports to check
DEFAULT_PORTS = [443, 8443, 8006, 8888, 9090, 3000, 8080]

# Expiry thresholds (days)
EXPIRY_CRITICAL = 7
EXPIRY_WARNING = 30


def _cert_dir(cfg: FreqConfig) -> str:
    """Get or create cert directory."""
    path = os.path.join(cfg.conf_dir, CERT_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_cert_data(cfg: FreqConfig) -> dict:
    """Load cert inventory from disk."""
    filepath = os.path.join(_cert_dir(cfg), CERT_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"certs": [], "scan_time": ""}


def _save_cert_data(cfg: FreqConfig, data: dict):
    """Save cert inventory to disk."""
    filepath = os.path.join(_cert_dir(cfg), CERT_FILE)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _check_tls_cert(host: str, port: int, timeout: int = CERT_CONNECT_TIMEOUT) -> dict:
    """Check a TLS certificate on host:port."""
    result = {
        "host": host,
        "port": port,
        "status": "error",
        "subject": "",
        "issuer": "",
        "not_after": "",
        "days_remaining": -1,
        "self_signed": False,
        "error": "",
    }

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert(binary_form=False)
                cert_der = ssock.getpeercert(binary_form=True)

                if not cert and cert_der:
                    # Decode DER cert manually for basic info
                    import ssl as ssl_mod

                    cert = (
                        ssl_mod._ssl._test_decode_cert(cert_der) if hasattr(ssl_mod._ssl, "_test_decode_cert") else {}
                    )

                if cert:
                    # Extract subject
                    subject_parts = []
                    for field in cert.get("subject", ()):
                        for key, value in field:
                            if key == "commonName":
                                subject_parts.append(value)
                    result["subject"] = ", ".join(subject_parts) if subject_parts else "unknown"

                    # Extract issuer
                    issuer_parts = []
                    for field in cert.get("issuer", ()):
                        for key, value in field:
                            if key in ("commonName", "organizationName"):
                                issuer_parts.append(value)
                    result["issuer"] = ", ".join(issuer_parts) if issuer_parts else "unknown"

                    # Check expiry
                    not_after = cert.get("notAfter", "")
                    result["not_after"] = not_after
                    if not_after:
                        try:
                            expiry = ssl.cert_time_to_seconds(not_after)
                            days = (expiry - time.time()) / 86400
                            result["days_remaining"] = int(days)
                        except (ValueError, OverflowError):
                            pass

                    # Check self-signed
                    result["self_signed"] = cert.get("subject") == cert.get("issuer")

                    result["status"] = "ok"
                else:
                    # Got a connection but couldn't parse cert
                    result["status"] = "ok"
                    result["subject"] = "(binary cert)"

    except ssl.SSLError as e:
        result["error"] = str(e)[:60]
        result["status"] = "ssl_error"
    except ValueError as e:
        result["error"] = str(e)[:60]
        result["status"] = "error"
    except (ConnectionRefusedError, ConnectionResetError):
        result["error"] = "connection refused"
        result["status"] = "refused"
    except socket.timeout:
        result["error"] = "timeout"
        result["status"] = "timeout"
    except OSError as e:
        result["error"] = str(e)[:60]
        result["status"] = "error"

    return result


def _scan_host_certs(cfg: FreqConfig, host) -> list:
    """Scan a single host for TLS certs on common ports."""
    certs = []
    for port in DEFAULT_PORTS:
        result = _check_tls_cert(host.ip, port)
        if result["status"] == "ok":
            result["label"] = host.label
            certs.append(result)
    return certs


def _scan_fleet_certs_via_ssh(cfg: FreqConfig) -> list:
    """Use SSH to find certs on fleet hosts."""
    hosts = cfg.hosts
    if not hosts:
        return []

    # Find cert files on each host
    command = (
        "find /etc/ssl/certs /etc/pve/nodes /etc/letsencrypt/live "
        "/etc/nginx/ssl /etc/apache2/ssl /opt -maxdepth 3 "
        "-name '*.pem' -o -name '*.crt' -o -name '*.cert' 2>/dev/null | head -20 | "
        "while read f; do "
        "  exp=$(openssl x509 -enddate -noout -in \"$f\" 2>/dev/null | sed 's/notAfter=//'); "
        "  sub=$(openssl x509 -subject -noout -in \"$f\" 2>/dev/null | sed 's/subject=//'); "
        "  iss=$(openssl x509 -issuer -noout -in \"$f\" 2>/dev/null | sed 's/issuer=//'); "
        '  if [ -n "$exp" ]; then echo "$f|$sub|$iss|$exp"; fi; '
        "done"
    )

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=CERT_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    certs = []
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0 or not r.stdout.strip():
            continue

        for line in r.stdout.strip().split("\n"):
            parts = line.split("|", 3)
            if len(parts) >= 4:
                filepath, subject, issuer, expiry = parts[0], parts[1], parts[2], parts[3]

                days_remaining = -1
                try:
                    # Parse date like "Mar 31 12:00:00 2027 GMT"
                    exp_time = ssl.cert_time_to_seconds(expiry.strip())
                    days_remaining = int((exp_time - time.time()) / 86400)
                except (ValueError, OverflowError):
                    pass

                self_signed = subject.strip() == issuer.strip()

                certs.append(
                    {
                        "label": h.label,
                        "host": h.ip,
                        "port": 0,
                        "path": filepath.strip(),
                        "subject": subject.strip()[:60],
                        "issuer": issuer.strip()[:60],
                        "not_after": expiry.strip(),
                        "days_remaining": days_remaining,
                        "self_signed": self_signed,
                        "status": "ok",
                    }
                )

    return certs


def cmd_cert(cfg: FreqConfig, pack, args) -> int:
    """TLS certificate management."""
    action = getattr(args, "action", None) or "scan"

    if action == "scan":
        return _cmd_scan(cfg, args)
    elif action == "list":
        return _cmd_list(cfg, args)
    elif action == "check":
        return _cmd_check_single(cfg, args)

    fmt.error(f"Unknown cert action: {action}")
    fmt.info("Available: scan, list, check")
    return 1


def _cmd_scan(cfg: FreqConfig, args) -> int:
    """Scan fleet for TLS certificates."""
    fmt.header("TLS Certificate Scan")
    fmt.blank()

    all_certs = []

    # SSH-based cert file scan
    fmt.step_start("Scanning fleet for certificate files")
    file_certs = _scan_fleet_certs_via_ssh(cfg)
    fmt.step_ok(f"Found {len(file_certs)} certificate files")
    all_certs.extend(file_certs)

    # Network TLS scan on common ports (parallel with timeout)
    fmt.step_start("Probing TLS endpoints")
    with ThreadPoolExecutor(max_workers=cfg.ssh_max_parallel or 5) as pool:
        futures = {pool.submit(_scan_host_certs, cfg, h): h for h in cfg.hosts}
        for future in as_completed(futures, timeout=60):
            try:
                all_certs.extend(future.result(timeout=CERT_CONNECT_TIMEOUT + 2))
            except Exception:
                pass
    net_count = len(all_certs) - len(file_certs)
    fmt.step_ok(f"Found {net_count} TLS endpoints")

    # Save results
    cert_data = {
        "certs": all_certs,
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "total": len(all_certs),
    }
    _save_cert_data(cfg, cert_data)

    fmt.blank()

    # Display results
    if not all_certs:
        fmt.line(f"  {fmt.C.DIM}No certificates found.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Sort: expired first, then by days remaining
    all_certs.sort(key=lambda c: c.get("days_remaining", 9999))

    fmt.table_header(
        ("HOST", 14),
        ("PORT/PATH", 20),
        ("SUBJECT", 20),
        ("EXPIRES", 12),
        ("STATUS", 12),
    )

    expiring = 0
    expired = 0
    self_signed = 0

    for cert in all_certs:
        days = cert.get("days_remaining", -1)
        label = cert.get("label", cert.get("host", ""))
        port_or_path = str(cert.get("port", "")) if cert.get("port") else cert.get("path", "")[-20:]
        subject = cert.get("subject", "")[:20]

        # Status
        if days < 0:
            status = f"{fmt.C.RED}EXPIRED{fmt.C.RESET}"
            expired += 1
        elif days <= EXPIRY_CRITICAL:
            status = f"{fmt.C.RED}{days}d LEFT{fmt.C.RESET}"
            expiring += 1
        elif days <= EXPIRY_WARNING:
            status = f"{fmt.C.YELLOW}{days}d left{fmt.C.RESET}"
            expiring += 1
        else:
            status = f"{fmt.C.GREEN}{days}d{fmt.C.RESET}"

        if cert.get("self_signed"):
            self_signed += 1
            status += f" {fmt.C.DIM}SS{fmt.C.RESET}"

        fmt.table_row(
            (f"{fmt.C.BOLD}{label}{fmt.C.RESET}", 14),
            (port_or_path, 20),
            (subject, 20),
            (cert.get("not_after", "")[:12], 12),
            (status, 12),
        )

    fmt.blank()
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(f"  Total: {len(all_certs)} certificates")
    if expired:
        fmt.line(f"  {fmt.C.RED}{fmt.S.CROSS} {expired} EXPIRED{fmt.C.RESET}")
    if expiring:
        fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} {expiring} expiring within {EXPIRY_WARNING} days{fmt.C.RESET}")
    if self_signed:
        fmt.line(f"  {fmt.C.DIM}{self_signed} self-signed{fmt.C.RESET}")
    if not expired and not expiring:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} All certificates healthy.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 1 if expired or expiring else 0


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List last scan results."""
    data = _load_cert_data(cfg)
    if not data.get("certs"):
        fmt.error("No cert data. Run: freq cert scan")
        return 1

    fmt.header(f"Certificate Inventory (from {data.get('scan_time', '?')[:19]})")
    fmt.blank()

    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return 0

    fmt.line(f"  {len(data['certs'])} certificates on file")
    fmt.line(f"  {fmt.C.DIM}Run freq cert scan to refresh.{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_check_single(cfg: FreqConfig, args) -> int:
    """Check a single host:port for TLS."""
    target = getattr(args, "target", None)
    if not target:
        fmt.error("Usage: freq cert check <host:port>")
        return 1

    # Parse host:port
    if ":" in target:
        host, port_str = target.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            fmt.error(f"Invalid port: {port_str}")
            return 1
    else:
        host = target
        port = 443

    fmt.header(f"TLS Check: {host}:{port}")
    fmt.blank()

    result = _check_tls_cert(host, port)

    if result["status"] == "ok":
        fmt.step_ok(f"Connected to {host}:{port}")
        fmt.blank()
        fmt.line(f"  Subject:    {result['subject']}")
        fmt.line(f"  Issuer:     {result['issuer']}")
        fmt.line(f"  Expires:    {result['not_after']}")
        fmt.line(f"  Days left:  {result['days_remaining']}")
        fmt.line(f"  Self-signed: {'Yes' if result['self_signed'] else 'No'}")
    else:
        fmt.step_fail(f"{result['status']}: {result['error']}")

    fmt.blank()
    fmt.footer()
    return 0 if result["status"] == "ok" else 1
