"""Multi-site federation for FREQ.

Domain: freq fleet federation

Connects independent FREQ instances across sites for cross-site visibility.
Each site registers with a name, URL, and HMAC shared secret, then polls
peers periodically for health and fleet status.

Replaces: Zabbix distributed monitoring + VPN mesh dashboards ($20k+/yr)

Architecture:
    - Sites stored in data/federation.json with HMAC auth headers
    - poll_site() checks /healthz then /api/health on each remote
    - Federation summary aggregates host counts across all reachable sites

Design decisions:
    - HMAC-SHA256 auth with 5-minute timestamp window prevents replay attacks
    - Secrets never serialized to API responses (sites_to_dicts strips them)
"""
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from freq.core import log as logger


FEDERATION_FILE = "federation.json"
POLL_INTERVAL = 120  # seconds between polling remote sites
REQUEST_TIMEOUT = 10  # seconds


@dataclass
class Site:
    """A registered remote FREQ site."""
    name: str
    url: str          # base URL, e.g. "https://freq.dc02.example.com:8888"
    secret: str = ""  # shared secret for HMAC auth
    enabled: bool = True
    last_seen: float = 0.0
    last_status: str = "unknown"  # ok, unreachable, error, unknown
    last_version: str = ""
    last_hosts: int = 0
    last_healthy: int = 0


def _federation_path(data_dir: str) -> str:
    """Return the federation state file path."""
    return os.path.join(data_dir, FEDERATION_FILE)


def load_sites(data_dir: str) -> list:
    """Load registered sites from disk."""
    path = _federation_path(data_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        sites = []
        for s in data.get("sites", []):
            sites.append(Site(
                name=s.get("name", ""),
                url=s.get("url", "").rstrip("/"),
                secret=s.get("secret", ""),
                enabled=s.get("enabled", True),
                last_seen=s.get("last_seen", 0.0),
                last_status=s.get("last_status", "unknown"),
                last_version=s.get("last_version", ""),
                last_hosts=s.get("last_hosts", 0),
                last_healthy=s.get("last_healthy", 0),
            ))
        return sites
    except (json.JSONDecodeError, OSError):
        return []


def save_sites(data_dir: str, sites: list):
    """Save registered sites to disk."""
    path = _federation_path(data_dir)
    data = {"sites": [
        {
            "name": s.name,
            "url": s.url,
            "secret": s.secret,
            "enabled": s.enabled,
            "last_seen": s.last_seen,
            "last_status": s.last_status,
            "last_version": s.last_version,
            "last_hosts": s.last_hosts,
            "last_healthy": s.last_healthy,
        }
        for s in sites
    ]}
    try:
        with open(path, "w") as f:
            json.dump(data, f)
    except OSError as e:
        logger.warn(f"Failed to save federation state: {e}")


def register_site(data_dir: str, name: str, url: str, secret: str = "") -> tuple:
    """Register a new remote site. Returns (success, message)."""
    if not name or not url:
        return False, "Name and URL are required"

    url = url.rstrip("/")
    sites = load_sites(data_dir)

    # Check for duplicates
    for s in sites:
        if s.name == name:
            return False, f"Site '{name}' already registered"
        if s.url == url:
            return False, f"URL '{url}' already registered as '{s.name}'"

    sites.append(Site(name=name, url=url, secret=secret))
    save_sites(data_dir, sites)
    return True, f"Site '{name}' registered"


def unregister_site(data_dir: str, name: str) -> tuple:
    """Remove a registered site. Returns (success, message)."""
    sites = load_sites(data_dir)
    original = len(sites)
    sites = [s for s in sites if s.name != name]
    if len(sites) == original:
        return False, f"Site '{name}' not found"
    save_sites(data_dir, sites)
    return True, f"Site '{name}' removed"


def _make_auth_header(secret: str, body: str = "") -> dict:
    """Create HMAC auth header for cross-site requests."""
    if not secret:
        return {}
    ts = str(int(time.time()))
    sig_input = f"{ts}:{body}"
    sig = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
    return {"X-Freq-Timestamp": ts, "X-Freq-Signature": sig}


def verify_auth(secret: str, timestamp: str, signature: str, body: str = "") -> bool:
    """Verify an incoming HMAC-authenticated request."""
    if not secret:
        return True  # No secret = open federation
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > 300:  # 5 minute window
            return False
    except (ValueError, TypeError):
        return False
    sig_input = f"{timestamp}:{body}"
    expected = hmac.new(secret.encode(), sig_input.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def poll_site(site: Site) -> Site:
    """Poll a remote site for status. Updates and returns the site."""
    if not site.enabled:
        return site

    # Check /healthz first (lightweight)
    try:
        headers = _make_auth_header(site.secret)
        req = urllib.request.Request(f"{site.url}/healthz", headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            site.last_version = data.get("version", "")
            site.last_status = "ok"
            site.last_seen = time.time()
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        site.last_status = "unreachable"
        return site

    # If healthz succeeded, try /api/health for fleet details
    try:
        headers = _make_auth_header(site.secret)
        req = urllib.request.Request(f"{site.url}/api/health", headers=headers)
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode())
            hosts = data.get("hosts", [])
            site.last_hosts = len(hosts)
            site.last_healthy = sum(1 for h in hosts if h.get("status") == "ok")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        pass  # healthz passed, so site is up — fleet data just unavailable

    return site


def poll_all_sites(data_dir: str) -> list:
    """Poll all registered sites and update state. Returns updated sites."""
    sites = load_sites(data_dir)
    updated = []
    for site in sites:
        updated.append(poll_site(site))
    save_sites(data_dir, updated)
    return updated


def should_poll(data_dir: str, interval: int = POLL_INTERVAL) -> bool:
    """Check if enough time has passed since any site was last polled."""
    sites = load_sites(data_dir)
    if not sites:
        return False
    oldest = min(s.last_seen for s in sites) if sites else 0
    return (time.time() - oldest) > interval


def sites_to_dicts(sites: list) -> list:
    """Convert sites to JSON-serializable dicts (hide secrets)."""
    return [
        {
            "name": s.name,
            "url": s.url,
            "has_secret": bool(s.secret),
            "enabled": s.enabled,
            "last_seen": round(s.last_seen),
            "last_status": s.last_status,
            "last_version": s.last_version,
            "last_hosts": s.last_hosts,
            "last_healthy": s.last_healthy,
            "age": round(time.time() - s.last_seen) if s.last_seen > 0 else -1,
        }
        for s in sites
    ]


def federation_summary(sites: list) -> dict:
    """Compute federation-wide summary."""
    active = [s for s in sites if s.enabled]
    reachable = [s for s in active if s.last_status == "ok"]
    total_hosts = sum(s.last_hosts for s in reachable)
    total_healthy = sum(s.last_healthy for s in reachable)

    return {
        "total_sites": len(sites),
        "active_sites": len(active),
        "reachable_sites": len(reachable),
        "unreachable_sites": len(active) - len(reachable),
        "total_hosts": total_hosts,
        "total_healthy": total_healthy,
    }


# ── CLI Command ────────────────────────────────────────────────────────

def cmd_federation(cfg, pack, args) -> int:
    """Manage multi-site federation."""
    from freq.core import fmt

    action = getattr(args, "action", "list")

    if action == "list":
        sites = load_sites(cfg.data_dir)
        fmt.header("Federation")
        fmt.blank()
        if not sites:
            fmt.line(f"  {fmt.C.DIM}No remote sites registered.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Register with: freq federation register --name <name> --url <url>{fmt.C.RESET}")
        else:
            fmt.line(f"  {'SITE':<20} {'URL':<35} {'STATUS':<10} {'HOSTS':>6} {'AGE':>8}")
            fmt.line(f"  {'─' * 82}")
            for s in sites_to_dicts(sites):
                status_color = fmt.C.GREEN if s["last_status"] == "ok" else fmt.C.RED
                age = f"{s['age']}s" if s["age"] >= 0 else "never"
                enabled = "" if s.get("enabled", True) else f" {fmt.C.DIM}(disabled){fmt.C.RESET}"
                fmt.line(f"  {s['name']:<20} {s['url']:<35} {status_color}{s['last_status']:<10}{fmt.C.RESET} {s['last_hosts']:>6} {age:>8}{enabled}")
            fmt.blank()
            summary = federation_summary(sites)
            fmt.line(f"  {fmt.C.BOLD}{summary['reachable_sites']}/{summary['total_sites']} sites reachable{fmt.C.RESET}  |  {summary['total_hosts']} hosts  |  {summary['total_healthy']} healthy")
        fmt.blank()
        fmt.footer()
        return 0

    elif action == "register":
        name = getattr(args, "name", None)
        url = getattr(args, "url", None)
        secret = getattr(args, "secret", "")
        if not name or not url:
            fmt.error("Usage: freq federation register --name <name> --url <url> [--secret <secret>]")
            return 1
        ok, msg = register_site(cfg.data_dir, name, url, secret or "")
        fmt.header("Federation")
        if ok:
            fmt.step_ok(msg)
        else:
            fmt.error(msg)
        fmt.footer()
        return 0 if ok else 1

    elif action == "remove":
        name = getattr(args, "name", None)
        if not name:
            fmt.error("Usage: freq federation remove --name <name>")
            return 1
        ok, msg = unregister_site(cfg.data_dir, name)
        fmt.header("Federation")
        if ok:
            fmt.step_ok(msg)
        else:
            fmt.error(msg)
        fmt.footer()
        return 0 if ok else 1

    elif action == "poll":
        fmt.header("Federation Poll")
        fmt.blank()
        sites = poll_all_sites(cfg.data_dir)
        for s in sites:
            status_color = fmt.C.GREEN if s.last_status == "ok" else fmt.C.RED
            fmt.line(f"  {s.name:<20} {status_color}{s.last_status}{fmt.C.RESET}  v{s.last_version}  {s.last_hosts} hosts")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.error(f"Unknown action: {action}")
    return 1
