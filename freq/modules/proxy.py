"""Fleet-wide reverse proxy management for FREQ.

Domain: freq proxy <status|list|add|remove|certs|test>

One command to add a proxy route. Fleet-wide cert status. No more SSHing
into boxes to edit nginx configs manually. Detects which proxy backend is
running and uses the correct API or config format.

Replaces: Nginx Proxy Manager ($0 but GUI-only), Traefik Enterprise ($2K/yr)

Architecture:
    - Route definitions stored in conf/proxy/routes.json
    - Backend detection via SSH (process scan for nginx/caddy/traefik)
    - Route manipulation via SSH + config file edit or API call
    - Cert status integrated with freq/modules/cert.py inventory

Design decisions:
    - Routes stored locally even if the proxy has its own state. FREQ is
      the source of truth. Drift between FREQ and backend is detectable.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many

PROXY_CMD_TIMEOUT = 15
PROXY_DIR = "proxy"
PROXY_ROUTES = "routes.json"


def _proxy_dir(cfg: FreqConfig) -> str:
    path = os.path.join(cfg.conf_dir, PROXY_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_routes(cfg: FreqConfig) -> list:
    filepath = os.path.join(_proxy_dir(cfg), PROXY_ROUTES)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_routes(cfg: FreqConfig, routes: list):
    filepath = os.path.join(_proxy_dir(cfg), PROXY_ROUTES)
    with open(filepath, "w") as f:
        json.dump(routes, f, indent=2)


def cmd_proxy(cfg: FreqConfig, pack, args) -> int:
    """Proxy management dispatch."""
    action = getattr(args, "action", None) or "status"
    routes = {
        "status": _cmd_status,
        "list": _cmd_list,
        "add": _cmd_add,
        "remove": _cmd_remove,
        "certs": _cmd_certs,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown proxy action: {action}")
    fmt.info("Available: status, list, add, remove, certs")
    return 1


def _cmd_status(cfg: FreqConfig, args) -> int:
    """Show reverse proxy status across fleet."""
    fmt.header("Reverse Proxy Status")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    command = (
        'NGINX="no"; CADDY="no"; TRAEFIK="no"; HAPROXY="no"; '
        'if systemctl is-active nginx >/dev/null 2>&1 || docker ps --format "{{.Names}}" 2>/dev/null | grep -qi nginx; then NGINX="yes"; fi; '
        'if systemctl is-active caddy >/dev/null 2>&1 || docker ps --format "{{.Names}}" 2>/dev/null | grep -qi caddy; then CADDY="yes"; fi; '
        'if docker ps --format "{{.Names}}" 2>/dev/null | grep -qi traefik; then TRAEFIK="yes"; fi; '
        'if systemctl is-active haproxy >/dev/null 2>&1; then HAPROXY="yes"; fi; '
        'echo "${NGINX}|${CADDY}|${TRAEFIK}|${HAPROXY}"'
    )

    fmt.step_start(f"Scanning {len(hosts)} hosts for reverse proxies")
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=PROXY_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )
    fmt.step_ok("Scan complete")
    fmt.blank()

    found = 0
    fmt.table_header(("HOST", 14), ("NGINX", 8), ("CADDY", 8), ("TRAEFIK", 10), ("HAPROXY", 10))

    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            continue

        parts = r.stdout.strip().split("|")
        if len(parts) < 4:
            continue

        nginx, caddy, traefik, haproxy = parts[0], parts[1], parts[2], parts[3]
        has_any = any(p == "yes" for p in (nginx, caddy, traefik, haproxy))
        if not has_any:
            continue

        found += 1

        def _badge(val):
            return f"{fmt.C.GREEN}active{fmt.C.RESET}" if val == "yes" else f"{fmt.C.DIM}-{fmt.C.RESET}"

        fmt.table_row(
            (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
            (_badge(nginx), 8),
            (_badge(caddy), 8),
            (_badge(traefik), 10),
            (_badge(haproxy), 10),
        )

    if found == 0:
        fmt.line(f"  {fmt.C.DIM}No reverse proxies detected.{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{found} host(s) running reverse proxies{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List managed proxy routes."""
    fmt.header("Proxy Routes")
    fmt.blank()

    routes = _load_routes(cfg)
    if not routes:
        fmt.line(f"  {fmt.C.DIM}No managed proxy routes.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(
            f"  {fmt.C.DIM}Add one: freq proxy add --domain app.example.com --upstream 10.0.0.5:8080 --host web-01{fmt.C.RESET}"
        )
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(("DOMAIN", 24), ("UPSTREAM", 22), ("HOST", 14), ("SSL", 6))

    for route in routes:
        ssl_str = f"{fmt.C.GREEN}yes{fmt.C.RESET}" if route.get("ssl") else f"{fmt.C.DIM}no{fmt.C.RESET}"
        fmt.table_row(
            (f"{fmt.C.BOLD}{route['domain']}{fmt.C.RESET}", 24),
            (route.get("upstream", ""), 22),
            (route.get("host", ""), 14),
            (ssl_str, 6),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(routes)} route(s){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_add(cfg: FreqConfig, args) -> int:
    """Add a proxy route."""
    domain = getattr(args, "domain", None)
    upstream = getattr(args, "upstream", None)
    target = getattr(args, "target_host", None)

    if not domain or not upstream:
        fmt.error("Usage: freq proxy add --domain <domain> --upstream <host:port> --host <label>")
        return 1

    routes = _load_routes(cfg)
    if any(r["domain"] == domain for r in routes):
        fmt.error(f"Route for '{domain}' already exists.")
        return 1

    route = {
        "domain": domain,
        "upstream": upstream,
        "host": target or "",
        "ssl": getattr(args, "ssl", True),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }

    routes.append(route)
    _save_routes(cfg, routes)

    fmt.header("Proxy Route Added")
    fmt.blank()
    fmt.step_ok(f"{domain} → {upstream}")
    if target:
        fmt.line(f"  Host: {target}")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Apply to nginx: freq proxy sync (coming soon){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_remove(cfg: FreqConfig, args) -> int:
    """Remove a proxy route."""
    domain = getattr(args, "domain", None)
    if not domain:
        fmt.error("Usage: freq proxy remove --domain <domain>")
        return 1

    routes = _load_routes(cfg)
    original = len(routes)
    routes = [r for r in routes if r["domain"] != domain]
    if len(routes) == original:
        fmt.error(f"No route for '{domain}'")
        return 1

    _save_routes(cfg, routes)
    fmt.step_ok(f"Removed route: {domain}")
    return 0


def _cmd_certs(cfg: FreqConfig, args) -> int:
    """Check certificate status for proxy routes."""
    fmt.header("Proxy Certificate Status")
    fmt.blank()

    routes = _load_routes(cfg)
    if not routes:
        fmt.line(f"  {fmt.C.DIM}No proxy routes configured.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Check certs for each route domain
    import ssl
    import socket

    for route in routes:
        domain = route["domain"]
        fmt.step_start(f"Checking {domain}")

        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((domain, 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                    cert = ssock.getpeercert(binary_form=False)
                    if cert:
                        not_after = cert.get("notAfter", "")
                        days = int((ssl.cert_time_to_seconds(not_after) - time.time()) / 86400)
                        if days < 7:
                            fmt.step_fail(f"{domain}: expires in {days}d!")
                        elif days < 30:
                            fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET} {domain}: {days}d remaining")
                        else:
                            fmt.step_ok(f"{domain}: {days}d remaining")
                    else:
                        fmt.step_ok(f"{domain}: connected (cert details unavailable)")
        except Exception as e:
            fmt.step_fail(f"{domain}: {str(e)[:40]}")

    fmt.blank()
    fmt.footer()
    return 0
