"""Reverse proxy backend management for FREQ — NPM, Caddy, Traefik, HAProxy.

Domain: freq proxy <backend> <action>
What: Manage reverse proxy hosts, SSL, routes via backend-specific APIs.
      Extends existing proxy.py with API integration for popular backends.
Replaces: NPM admin panel, Caddy API manual curl, Traefik dashboard
Architecture:
    - Auto-detect backend via proxy.py existing detection
    - NPM: REST API with token auth (urllib.request)
    - Caddy: Admin API at localhost:2019 (urllib.request)
    - Traefik: API at /api (urllib.request)
    - HAProxy: stats socket or stats page parsing
Design decisions:
    - urllib.request only — zero dependencies.
    - Backend detection before commands — no guessing.
    - Each backend gets its own set of commands mapped to its API.
"""

import json
import urllib.request
import urllib.error

from freq.core import fmt
from freq.core.config import FreqConfig


# ---------------------------------------------------------------------------
# Backend Detection
# ---------------------------------------------------------------------------


def _detect_backend(cfg):
    """Detect which reverse proxy is running. Returns (type, host_ip) or (None, None)."""
    # Check fleet hosts for known proxy types
    for h in cfg.hosts:
        if h.htype == "docker" or h.htype == "linux":
            # Try NPM (port 81)
            if _check_http(h.ip, 81, "/api"):
                return "npm", h.ip
            # Try Caddy admin (port 2019)
            if _check_http(h.ip, 2019, "/config/"):
                return "caddy", h.ip
            # Try Traefik (port 8080)
            if _check_http(h.ip, 8080, "/api/overview"):
                return "traefik", h.ip
    return None, None


def _check_http(ip, port, path, timeout=2):
    """Quick HTTP check — returns True if endpoint responds."""
    try:
        url = f"http://{ip}:{port}{path}"
        req = urllib.request.Request(url, method="GET")
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Commands — Status
# ---------------------------------------------------------------------------


def cmd_proxy_status(cfg: FreqConfig, pack, args) -> int:
    """Detect reverse proxy backend and show status."""
    fmt.header("Reverse Proxy Status", breadcrumb="FREQ > Proxy")
    fmt.blank()

    backend, host_ip = _detect_backend(cfg)

    if not backend:
        fmt.warn("No reverse proxy detected on fleet hosts")
        fmt.info("Checked: NPM (port 81), Caddy (2019), Traefik (8080)")
        fmt.footer()
        return 1

    fmt.line(f"{fmt.C.BOLD}Backend:{fmt.C.RESET}  {backend.upper()}")
    fmt.line(f"{fmt.C.BOLD}Host:{fmt.C.RESET}     {host_ip}")
    fmt.blank()

    if backend == "npm":
        return _npm_status(host_ip)
    elif backend == "caddy":
        return _caddy_status(host_ip)
    elif backend == "traefik":
        return _traefik_status(host_ip)

    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# NPM Backend
# ---------------------------------------------------------------------------


def _npm_api(ip, path, token=None, method="GET"):
    """Call NPM API endpoint."""
    url = f"http://{ip}:81/api{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()), resp.status
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        return {"error": str(e)}, 0


def _npm_status(ip):
    """Show NPM proxy hosts summary."""
    # NPM needs auth — try without first
    data, status = _npm_api(ip, "/nginx/proxy-hosts")
    if status == 0:
        fmt.warn("NPM API not responding or auth required")
        fmt.info("NPM REST API requires authentication token")
        fmt.footer()
        return 1

    if isinstance(data, list):
        fmt.line(f"{fmt.C.BOLD}Proxy Hosts:{fmt.C.RESET}")
        fmt.table_header(("Domain", 30), ("Forward", 24), ("SSL", 6), ("Enabled", 8))
        for host in data:
            domains = ", ".join(host.get("domain_names", []))
            forward = f"{host.get('forward_scheme', 'http')}://{host.get('forward_host', '?')}:{host.get('forward_port', '?')}"
            ssl_on = "Yes" if host.get("ssl_forced") else "No"
            enabled = "Yes" if host.get("enabled") else "No"
            fmt.table_row(
                (domains[:30], 30),
                (forward[:24], 24),
                (ssl_on, 6),
                (enabled, 8),
            )
        fmt.blank()
        fmt.info(f"{len(data)} proxy host(s)")

    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Caddy Backend
# ---------------------------------------------------------------------------


def _caddy_status(ip):
    """Show Caddy server status."""
    try:
        url = f"http://{ip}:2019/config/"
        with urllib.request.urlopen(url, timeout=5) as resp:
            config = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        fmt.warn("Caddy admin API not responding")
        fmt.footer()
        return 1

    # Count routes
    apps = config.get("apps", {})
    http_app = apps.get("http", {})
    servers = http_app.get("servers", {})
    total_routes = 0
    for name, server in servers.items():
        routes = server.get("routes", [])
        total_routes += len(routes)
        fmt.line(f"  Server '{name}': {len(routes)} route(s)")
        listen = server.get("listen", [])
        if listen:
            fmt.line(f"    Listen: {', '.join(listen)}")

    fmt.blank()
    fmt.info(f"{len(servers)} server(s), {total_routes} route(s)")
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Traefik Backend
# ---------------------------------------------------------------------------


def _traefik_status(ip):
    """Show Traefik dashboard summary."""
    try:
        url = f"http://{ip}:8080/api/overview"
        with urllib.request.urlopen(url, timeout=5) as resp:
            overview = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        fmt.warn("Traefik API not responding")
        fmt.footer()
        return 1

    http = overview.get("http", {})
    routers = http.get("routers", {})
    services = http.get("services", {})

    fmt.line(f"  Routers:  {routers.get('total', 0)} ({routers.get('warnings', 0)} warnings)")
    fmt.line(f"  Services: {services.get('total', 0)} ({services.get('warnings', 0)} warnings)")

    fmt.blank()
    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Commands — Proxy Hosts List (backend-agnostic)
# ---------------------------------------------------------------------------


def cmd_proxy_hosts(cfg: FreqConfig, pack, args) -> int:
    """List proxy hosts from detected backend."""
    backend, host_ip = _detect_backend(cfg)
    if not backend:
        fmt.error("No reverse proxy detected")
        return 1

    fmt.header(f"Proxy Hosts ({backend.upper()})", breadcrumb="FREQ > Proxy")
    fmt.blank()

    if backend == "npm":
        return _npm_status(host_ip)
    elif backend == "caddy":
        return _caddy_status(host_ip)
    elif backend == "traefik":
        return _traefik_status(host_ip)

    fmt.footer()
    return 0


def cmd_proxy_health(cfg: FreqConfig, pack, args) -> int:
    """Check health of all proxy backends."""
    fmt.header("Proxy Health Check", breadcrumb="FREQ > Proxy")
    fmt.blank()

    backends = [
        ("NPM", 81, "/api"),
        ("Caddy", 2019, "/config/"),
        ("Traefik", 8080, "/api/overview"),
    ]

    for h in cfg.hosts:
        if h.htype not in ("docker", "linux"):
            continue
        for name, port, path in backends:
            if _check_http(h.ip, port, path):
                fmt.step_ok(f"{h.label}: {name} on port {port}")
            # Only report if we find something

    fmt.blank()
    fmt.footer()
    return 0
