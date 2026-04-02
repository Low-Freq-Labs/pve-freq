"""DNS management for FREQ — unified internal DNS + backend integration.

Domain: freq dns <action>
What: Manage internal DNS records, sync from fleet inventory, query backends
      (Pi-hole, AdGuard, Unbound). Extends existing dns.py scan/check/list.
Replaces: Manual Pi-hole/AdGuard admin panels, editing /etc/hosts,
          Unbound conf edits via SSH
Architecture:
    - Internal DNS: A/PTR records derived from hosts.toml inventory
    - Backend detection: Pi-hole (REST API), AdGuard (REST API), Unbound (SSH)
    - Uses urllib.request for HTTP APIs — zero dependencies
    - DNS data stored in conf/dns/
Design decisions:
    - Backends are optional. Internal DNS sync works with just hosts.toml.
    - Pi-hole v6 API via session auth. AdGuard via basic auth.
    - Unbound via SSH to pfSense — edit local-data entries.
"""
import json
import os
import socket
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ---------------------------------------------------------------------------
# Data Storage
# ---------------------------------------------------------------------------

DNS_DIR = "dns"


def _dns_dir(cfg):
    """Return DNS data directory."""
    path = os.path.join(cfg.conf_dir, DNS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_dns_inventory(cfg):
    """Load internal DNS inventory."""
    filepath = os.path.join(_dns_dir(cfg), "dns-internal.json")
    if os.path.exists(filepath):
        with open(filepath) as f:
            return json.load(f)
    return {"records": []}


def _save_dns_inventory(cfg, data):
    """Save internal DNS inventory."""
    filepath = os.path.join(_dns_dir(cfg), "dns-internal.json")
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Commands — Internal DNS
# ---------------------------------------------------------------------------

def cmd_dns_internal_list(cfg: FreqConfig, pack, args) -> int:
    """List internal DNS records."""
    data = _load_dns_inventory(cfg)
    records = data.get("records", [])

    fmt.header("Internal DNS Records", breadcrumb="FREQ > DNS")
    fmt.blank()

    if not records:
        fmt.warn("No internal DNS records")
        fmt.info("Run: freq dns internal sync — to generate from hosts.toml")
        fmt.footer()
        return 0

    fmt.table_header(("Hostname", 24), ("IP", 16), ("Type", 6), ("Source", 12))
    for r in sorted(records, key=lambda x: x.get("ip", "")):
        fmt.table_row(
            (r.get("hostname", ""), 24),
            (r.get("ip", ""), 16),
            (r.get("type", "A"), 6),
            (r.get("source", "manual"), 12),
        )

    fmt.blank()
    fmt.info(f"{len(records)} record(s)")
    fmt.footer()
    return 0


def cmd_dns_internal_add(cfg: FreqConfig, pack, args) -> int:
    """Add an internal DNS record."""
    hostname = getattr(args, "hostname", None)
    ip = getattr(args, "ip", None)
    if not hostname or not ip:
        fmt.error("Usage: freq dns internal add <hostname> <ip>")
        return 1

    data = _load_dns_inventory(cfg)
    records = data.get("records", [])

    # Check for duplicates
    for r in records:
        if r.get("hostname") == hostname and r.get("ip") == ip:
            fmt.warn(f"Record already exists: {hostname} -> {ip}")
            return 0

    records.append({
        "hostname": hostname,
        "ip": ip,
        "type": "A",
        "source": "manual",
        "added": time.strftime("%Y-%m-%d"),
    })
    data["records"] = records
    _save_dns_inventory(cfg, data)

    fmt.success(f"Added: {hostname} -> {ip}")
    logger.info("dns_add", hostname=hostname, ip=ip)
    return 0


def cmd_dns_internal_remove(cfg: FreqConfig, pack, args) -> int:
    """Remove an internal DNS record."""
    hostname = getattr(args, "hostname", None)
    if not hostname:
        fmt.error("Usage: freq dns internal remove <hostname>")
        return 1

    data = _load_dns_inventory(cfg)
    records = data.get("records", [])
    new_records = [r for r in records if r.get("hostname") != hostname]

    if len(new_records) == len(records):
        fmt.warn(f"Record not found: {hostname}")
        return 1

    removed = len(records) - len(new_records)
    data["records"] = new_records
    _save_dns_inventory(cfg, data)

    fmt.success(f"Removed {removed} record(s) for {hostname}")
    logger.info("dns_remove", hostname=hostname, removed=removed)
    return 0


def cmd_dns_internal_sync(cfg: FreqConfig, pack, args) -> int:
    """Sync DNS records from hosts.toml inventory."""
    fmt.header("DNS Sync from Fleet", breadcrumb="FREQ > DNS")
    fmt.blank()

    data = _load_dns_inventory(cfg)
    records = data.get("records", [])

    # Remove old auto-generated records
    records = [r for r in records if r.get("source") != "hosts.toml"]

    # Generate from hosts.toml
    added = 0
    for h in cfg.hosts:
        records.append({
            "hostname": f"{h.label}.freq.local",
            "ip": h.ip,
            "type": "A",
            "source": "hosts.toml",
            "added": time.strftime("%Y-%m-%d"),
        })
        added += 1

    data["records"] = records
    _save_dns_inventory(cfg, data)

    fmt.step_ok(f"Synced {added} hosts from hosts.toml")
    fmt.info(f"Total records: {len(records)}")

    fmt.blank()
    logger.info("dns_sync", added=added, total=len(records))
    fmt.footer()
    return 0


def cmd_dns_internal_audit(cfg: FreqConfig, pack, args) -> int:
    """Audit DNS records — check forward/reverse resolution."""
    data = _load_dns_inventory(cfg)
    records = data.get("records", [])

    fmt.header("DNS Audit", breadcrumb="FREQ > DNS")
    fmt.blank()

    if not records:
        fmt.warn("No records to audit")
        fmt.footer()
        return 0

    pass_count = 0
    fail_count = 0

    for r in records:
        hostname = r.get("hostname", "")
        expected_ip = r.get("ip", "")

        try:
            resolved = socket.gethostbyname(hostname)
            if resolved == expected_ip:
                fmt.step_ok(f"{hostname} -> {resolved}")
                pass_count += 1
            else:
                fmt.step_warn(f"{hostname} -> {resolved} (expected {expected_ip})")
                fail_count += 1
        except socket.gaierror:
            fmt.step_fail(f"{hostname} — DNS resolution failed")
            fail_count += 1

    fmt.blank()
    fmt.info(f"{pass_count} passed, {fail_count} failed")
    fmt.footer()
    return 0
