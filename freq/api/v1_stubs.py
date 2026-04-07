"""Stub handlers for v1 dashboard endpoints not yet fully implemented.

Returns valid empty responses so the frontend renders graceful empty states
instead of 404 errors in the console. As real implementations are built,
move routes from here to their proper domain modules.
"""

from freq.core import log as logger
from freq.api.helpers import json_response, get_param


# -- Firewall (pfSense integration) ------------------------------------------


def handle_fw_status(handler):
    """GET /api/v1/fw/status — firewall overview."""
    json_response(
        handler,
        {
            "stats": {"rules": 0, "nat": 0, "states": 0, "interfaces": 0},
            "interfaces": [],
            "message": "Firewall integration not yet configured",
        },
    )


def handle_fw_rules(handler):
    """GET /api/v1/fw/rules — firewall rule table."""
    json_response(handler, {"rules": []})


def handle_fw_nat(handler):
    """GET /api/v1/fw/nat — NAT rules."""
    json_response(handler, {"rules": []})


def handle_fw_states(handler):
    """GET /api/v1/fw/states — connection states."""
    json_response(handler, {"states": []})


# -- DNS ---------------------------------------------------------------------


def handle_dns_status(handler):
    """GET /api/v1/dns/status — DNS zone overview."""
    json_response(
        handler,
        {
            "stats": {"zones": 0, "records": 0, "healthy": 0, "errors": 0},
            "records": [],
            "message": "DNS management not yet configured",
        },
    )


def handle_dns_check(handler):
    """GET /api/v1/dns/check — DNS lookup check."""
    domain = get_param(handler, "domain")
    if not domain:
        json_response(handler, {"error": "domain parameter required"}, 400)
        return
    json_response(
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
    json_response(
        handler,
        {
            "stats": {"wg_tunnels": 0, "wg_peers": 0, "ovpn_tunnels": 0, "connected": 0},
            "wireguard": None,
            "openvpn": None,
            "message": "VPN status not yet configured",
        },
    )


# -- Certs -------------------------------------------------------------------


def handle_cert_list(handler):
    """GET /api/v1/cert/list — certificate inventory."""
    json_response(
        handler,
        {
            "stats": {"total": 0, "valid": 0, "expiring": 0, "expired": 0},
            "certs": [],
            "message": "Certificate monitoring not yet configured",
        },
    )


# -- DR (Disaster Recovery) --------------------------------------------------


def handle_dr_status(handler):
    """GET /api/v1/dr/status — backup & DR overview."""
    json_response(
        handler,
        {
            "stats": {"hosts": 0, "protected": 0, "stale": 0, "policies": 0},
            "backups": [],
            "policies": [],
            "runbooks": [],
            "message": "Backup policies not yet configured",
        },
    )


# -- Incidents / Ops ---------------------------------------------------------


def handle_ops_incidents(handler):
    """GET /api/v1/ops/incidents — incident log."""
    json_response(
        handler,
        {
            "stats": {"open": 0, "resolved": 0, "total": 0, "mttr_min": 0},
            "incidents": [],
            "message": "No incidents recorded",
        },
    )


# -- Observe / Metrics -------------------------------------------------------


def handle_observe_metrics(handler):
    """GET /api/v1/observe/metrics — top-level metrics dashboard."""
    json_response(
        handler,
        {
            "stats": {"hosts": 0, "series": 0, "alerts": 0, "uptime_pct": 0},
            "hosts": [],
            "message": "Metrics collection not yet configured",
        },
    )


# -- Automation --------------------------------------------------------------


def handle_auto_status(handler):
    """GET /api/v1/auto/status — automation overview."""
    json_response(
        handler,
        {
            "stats": {"reactors": 0, "workflows": 0, "jobs": 0, "runs_today": 0},
            "reactors": [],
            "workflows": [],
            "jobs": [],
            "message": "Automation engine not yet configured",
        },
    )


# -- Network scan ------------------------------------------------------------


def handle_net_switches(handler):
    """GET /api/v1/net/switches — switch inventory for dashboard."""
    json_response(
        handler,
        {
            "stats": {"total": 0, "online": 0, "offline": 0},
            "switches": [],
            "message": "No switches configured",
        },
    )


def handle_net_scan(handler):
    """GET /api/v1/net/scan — network discovery scan."""
    scan_type = get_param(handler, "type", "arp")
    json_response(
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
    routes["/api/v1/net/switches"] = handle_net_switches
    routes["/api/v1/net/scan"] = handle_net_scan
