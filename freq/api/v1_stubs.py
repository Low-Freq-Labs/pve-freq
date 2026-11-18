"""Stub handlers for v1 dashboard endpoints not yet fully implemented.

Returns valid empty responses so the frontend renders graceful empty states
instead of 404 errors in the console. As real implementations are built,
move routes from here to their proper domain modules.
"""

from freq.api.helpers import get_param, json_response


def _stub_response(handler, payload, status=200):
    """Return a truthful capability envelope for an unimplemented v1 route."""
    body = dict(payload) if isinstance(payload, dict) else {"data": payload}
    body.setdefault("implemented", False)
    body.setdefault("available", False)
    body.setdefault("capability_status", "unimplemented")
    json_response(handler, body, status)

# -- Firewall (pfSense integration) ------------------------------------------


def handle_fw_status(handler):
    """GET /api/v1/fw/status — firewall overview."""
    _stub_response(
        handler,
        {
            "stats": {"rules": 0, "nat": 0, "states": 0, "interfaces": 0},
            "interfaces": [],
            "message": "This capability is not implemented",
        },
    )


def handle_fw_rules(handler):
    """GET /api/v1/fw/rules — firewall rule table."""
    _stub_response(handler, {"rules": []})


def handle_fw_nat(handler):
    """GET /api/v1/fw/nat — NAT rules."""
    _stub_response(handler, {"rules": []})


def handle_fw_states(handler):
    """GET /api/v1/fw/states — connection states."""
    _stub_response(handler, {"states": []})


# -- DNS ---------------------------------------------------------------------


def handle_dns_status(handler):
    """GET /api/v1/dns/status — DNS zone overview."""
    _stub_response(
        handler,
        {
            "stats": {"zones": 0, "records": 0, "healthy": 0, "errors": 0},
            "records": [],
            "message": "This capability is not implemented",
        },
    )


def handle_dns_check(handler):
    """GET /api/v1/dns/check — DNS lookup check."""
    domain = get_param(handler, "domain")
    if not domain:
        _stub_response(handler, {"error": "domain parameter required"}, 400)
        return
    _stub_response(
        handler,
        {
            "domain": domain,
            "message": "DNS check not yet implemented",
            "records": [],
        },
    )


# -- VPN ---------------------------------------------------------------------


def handle_vpn_status(handler):
    """GET /api/v1/vpn/status — VPN tunnel overview."""
    _stub_response(
        handler,
        {
            "stats": {"wg_tunnels": 0, "wg_peers": 0, "ovpn_tunnels": 0, "connected": 0},
            "wireguard": None,
            "openvpn": None,
            "message": "This capability is not implemented",
        },
    )


# -- Certs -------------------------------------------------------------------


def handle_cert_list(handler):
    """GET /api/v1/cert/list — certificate inventory."""
    _stub_response(
        handler,
        {
            "stats": {"total": 0, "valid": 0, "expiring": 0, "expired": 0},
            "certs": [],
            "message": "This capability is not implemented",
        },
    )


# -- DR (Disaster Recovery) --------------------------------------------------


def handle_dr_status(handler):
    """GET /api/v1/dr/status — backup & DR overview."""
    _stub_response(
        handler,
        {
            "stats": {"hosts": 0, "protected": 0, "stale": 0, "policies": 0},
            "backups": [],
            "policies": [],
            "runbooks": [],
            "message": "This capability is not implemented",
        },
    )


# -- Incidents / Ops ---------------------------------------------------------


def handle_ops_incidents(handler):
    """GET /api/v1/ops/incidents — incident log."""
    _stub_response(
        handler,
        {
            "stats": {"open": 0, "resolved": 0, "total": 0, "mttr_min": 0},
            "incidents": [],
            "message": "Incident collection is not implemented",
        },
    )


# -- Observe / Metrics -------------------------------------------------------


def handle_observe_metrics(handler):
    """GET /api/v1/observe/metrics — top-level metrics dashboard."""
    _stub_response(
        handler,
        {
            "stats": {"hosts": 0, "series": 0, "alerts": 0, "uptime_pct": 0},
            "hosts": [],
            "message": "This capability is not implemented",
        },
    )


# -- Automation --------------------------------------------------------------


def handle_auto_status(handler):
    """GET /api/v1/auto/status — automation overview."""
    _stub_response(
        handler,
        {
            "stats": {"reactors": 0, "workflows": 0, "jobs": 0, "runs_today": 0},
            "reactors": [],
            "workflows": [],
            "jobs": [],
            "message": "This capability is not implemented",
        },
    )


# -- Network scan ------------------------------------------------------------


def handle_net_scan(handler):
    """GET /api/v1/net/scan — network discovery scan."""
    scan_type = get_param(handler, "type", "arp")
    _stub_response(
        handler,
        {
            "type": scan_type,
            "devices": [],
            "message": f"Network scan ({scan_type}) not yet implemented",
        },
    )


# -- Registration ------------------------------------------------------------


def register(routes):
    """Register v1 stub routes."""
    routes["/api/v1/fw/status"] = handle_fw_status
    routes["/api/v1/fw/rules"] = handle_fw_rules
    routes["/api/v1/fw/nat"] = handle_fw_nat
    routes["/api/v1/fw/states"] = handle_fw_states
    routes["/api/v1/dns/status"] = handle_dns_status
    routes["/api/v1/dns/check"] = handle_dns_check
    routes["/api/v1/vpn/status"] = handle_vpn_status
    routes["/api/v1/cert/list"] = handle_cert_list
    routes["/api/v1/dr/status"] = handle_dr_status
    routes["/api/v1/ops/incidents"] = handle_ops_incidents
    routes["/api/v1/observe/metrics"] = handle_observe_metrics
    routes["/api/v1/auto/status"] = handle_auto_status
    routes["/api/v1/net/scan"] = handle_net_scan
