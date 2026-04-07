"""OPNsense REST API integration for FREQ.

Who:   OPNsense firewall management via its native REST API.
What:  Read/write endpoints for system status, services, firewall rules,
       DHCP reservations, DNS overrides, WireGuard peers, firmware, reboot.
Why:   Direct API integration — no SSH required. OPNsense exposes a full
       REST API with key+secret auth, unlike pfSense which needs SSH+PHP.
Where: Routes registered at /api/opnsense/*.
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import base64
import json
import re
import ssl

from freq.core import log as logger

# OPNsense uses UUID-v4 format for resource identifiers
_SAFE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
import urllib.request
import urllib.error

from freq.api.helpers import json_response, get_json_body
from freq.core.config import load_config
from freq.modules.serve import _check_session_role
from freq.modules.vault import vault_get


# -- Helpers -----------------------------------------------------------------


def _opn_request(cfg, path, method="GET", body=None):
    """Make a request to the OPNsense REST API.

    Builds the URL from cfg.opnsense_ip, authenticates with API key+secret
    from the FREQ vault, and returns parsed JSON.

    Args:
        cfg:    FreqConfig instance with opnsense_ip set.
        path:   API path (e.g. "core/system/status"). No leading slash.
        method: HTTP method — GET or POST.
        body:   Optional dict to send as JSON body (POST only).

    Returns:
        (data_dict, None) on success.
        (None, error_string) on failure.
    """
    api_key = vault_get(cfg, "opnsense", "api_key")
    api_secret = vault_get(cfg, "opnsense", "api_secret")
    if not api_key or not api_secret:
        return None, "OPNsense API credentials not configured in vault"

    url = f"https://{cfg.opnsense_ip}/api/{path}"

    # Build auth header
    credentials = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()

    headers = {
        "Authorization": f"Basic {credentials}",
        "Accept": "application/json",
    }

    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    # Self-signed certs are standard on homelab firewalls
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read()
            if not raw:
                return {}, None
            return json.loads(raw), None
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            err_body = e.read().decode()[:500]
        except Exception:
            pass
        logger.warn(f"api_opnsense: HTTP {e.code} on {path}", endpoint=path)
        return None, f"OPNsense HTTP {e.code}: {err_body or e.reason}"
    except urllib.error.URLError as e:
        logger.warn(f"api_opnsense: connection failed: {e.reason}", endpoint=path)
        return None, f"OPNsense connection failed: {e.reason}"
    except json.JSONDecodeError:
        logger.warn(f"api_opnsense: invalid JSON from {path}", endpoint=path)
        return None, "OPNsense returned invalid JSON"
    except Exception as e:
        logger.error(f"api_opnsense_error: {e}", endpoint=path)
        return None, f"OPNsense request error: {e}"


def _require_opnsense(handler):
    """Check admin role and OPNsense config. Returns (cfg, ok).

    Sends an error response and returns (None, False) if the caller
    lacks admin privileges or OPNsense is not configured.
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return None, False
    cfg = load_config()
    if not cfg.opnsense_ip:
        json_response(handler, {"error": "OPNsense not configured"}, 400)
        return None, False
    return cfg, True


def _require_opnsense_read(handler):
    """Load config and verify OPNsense is configured. No role check.

    Read endpoints are available to any authenticated session.

    Returns (cfg, ok).
    """
    cfg = load_config()
    if not cfg.opnsense_ip:
        json_response(handler, {"error": "OPNsense not configured"}, 400)
        return None, False
    return cfg, True


def _firewall_safe_apply(cfg, mutation_path, mutation_body=None):
    """Apply a firewall mutation using the OPNsense savepoint pattern.

    OPNsense firewall changes use a transactional model:
      1. Create a savepoint (gets a revision UUID)
      2. Apply the mutation (add/delete rule)
      3. Apply the revision (activates the change)
      4. Cancel the rollback timer (commits permanently)

    If any step fails, OPNsense auto-rolls back after the timeout.

    Args:
        cfg:             FreqConfig instance.
        mutation_path:   API path for the mutation (e.g. "firewall/filter/addRule").
        mutation_body:   Optional dict body for the mutation POST.

    Returns:
        (result_dict, None) on success.
        (None, error_string) on failure.
    """
    # Step 1: Create savepoint
    sp_data, sp_err = _opn_request(cfg, "firewall/filter/savepoint", method="POST")
    if sp_err:
        return None, f"Savepoint failed: {sp_err}"

    revision = sp_data.get("revision")
    if not revision:
        return None, "Savepoint returned no revision"

    # Step 2: Execute the mutation
    mut_data, mut_err = _opn_request(cfg, mutation_path, method="POST", body=mutation_body)
    if mut_err:
        return None, f"Mutation failed: {mut_err}"

    # Step 3: Apply the revision
    apply_data, apply_err = _opn_request(
        cfg,
        f"firewall/filter/apply/{revision}",
        method="POST",
    )
    if apply_err:
        return None, f"Apply failed (auto-rollback pending): {apply_err}"

    # Step 4: Cancel the rollback timer — commit permanently
    cancel_data, cancel_err = _opn_request(
        cfg,
        f"firewall/filter/cancelRollback/{revision}",
        method="POST",
    )
    if cancel_err:
        # Non-fatal: the change is applied, rollback timer just stays active
        return mut_data, f"Warning: cancelRollback failed ({cancel_err}), change applied"

    return mut_data, None


# -- Read Operations (no role check) -----------------------------------------


def handle_opnsense_status(handler):
    """GET /api/opnsense/status -- OPNsense system status.

    Returns system information from the OPNsense API including
    uptime, CPU, memory, and version details.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "core/system/status")
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "status": data})


def handle_opnsense_services(handler):
    """GET /api/opnsense/services -- list OPNsense services and status.

    Returns the full service list with running/stopped state.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "core/service/search")
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "services": data})


def handle_opnsense_rules(handler):
    """GET /api/opnsense/rules -- list OPNsense firewall filter rules.

    Uses POST with empty body to the searchRule endpoint, which is
    OPNsense's standard pattern for paginated search results.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    # OPNsense searchRule is a POST endpoint (search with empty filter)
    data, err = _opn_request(cfg, "firewall/filter/searchRule", method="POST", body={})
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "rules": data})


def handle_opnsense_dhcp(handler):
    """GET /api/opnsense/dhcp -- list Kea DHCP reservations.

    Returns static DHCP reservations from the Kea DHCPv4 service.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "kea/dhcpv4/searchReservation", method="POST", body={})
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "reservations": data})


def handle_opnsense_dns(handler):
    """GET /api/opnsense/dns -- list Unbound DNS host overrides.

    Returns DNS override entries from the Unbound resolver.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "unbound/settings/searchHostOverride", method="POST", body={})
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "overrides": data})


def handle_opnsense_wireguard(handler):
    """GET /api/opnsense/wireguard -- list WireGuard peers.

    Returns all configured WireGuard client peers.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "wireguard/client/searchClient", method="POST", body={})
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "peers": data})


def handle_opnsense_firmware(handler):
    """GET /api/opnsense/firmware -- check OPNsense firmware/update status.

    Returns current firmware version and available updates.
    """
    cfg, ok = _require_opnsense_read(handler)
    if not ok:
        return

    data, err = _opn_request(cfg, "core/firmware/status", method="POST")
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "firmware": data})


# -- Write Operations (admin only) -------------------------------------------


def handle_opnsense_service_action(handler):
    """POST /api/opnsense/service/action -- start/stop/restart a service.

    Body: {"service": "unbound", "action": "restart"}

    Supported actions: start, stop, restart.
    Calls the OPNsense core service control API.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    service = body.get("service", "").strip()
    action = body.get("action", "").strip()

    if not service:
        json_response(handler, {"error": "service is required"}, 400)
        return
    if action not in ("start", "stop", "restart"):
        json_response(handler, {"error": "action must be start, stop, or restart"}, 400)
        return

    data, err = _opn_request(cfg, f"core/service/{action}/{service}", method="POST")
    if err:
        json_response(handler, {"ok": False, "error": err, "action": action, "service": service}, 502)
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": action,
            "service": service,
            "result": data,
        },
    )


def handle_opnsense_rule_add(handler):
    """POST /api/opnsense/rules/add -- add a firewall filter rule.

    Body: {
        "action": "pass",
        "direction": "in",
        "interface": "lan",
        "protocol": "TCP",
        "source": "any",
        "destination": "10.0.0.0/24",
        "port": "443",
        "description": "Allow HTTPS"
    }

    Uses the savepoint safety pattern: savepoint -> addRule -> apply -> cancelRollback.
    If apply fails, OPNsense automatically rolls back to the savepoint.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)

    # Validate required fields
    rule_action = body.get("action", "").strip()
    if rule_action not in ("pass", "block", "reject"):
        json_response(handler, {"error": "action must be pass, block, or reject"}, 400)
        return

    direction = body.get("direction", "in").strip()
    if direction not in ("in", "out"):
        json_response(handler, {"error": "direction must be in or out"}, 400)
        return

    interface = body.get("interface", "").strip()
    if not interface:
        json_response(handler, {"error": "interface is required"}, 400)
        return

    protocol = body.get("protocol", "").strip()
    source = body.get("source", "any").strip()
    destination = body.get("destination", "any").strip()
    port = body.get("port", "").strip()
    description = body.get("description", "Added by FREQ").strip()

    # Build rule payload per OPNsense API schema
    rule_body = {
        "rule": {
            "action": rule_action,
            "direction": direction,
            "interface": interface,
            "source_net": source,
            "destination_net": destination,
            "description": description,
            "enabled": "1",
        }
    }

    if protocol:
        rule_body["rule"]["protocol"] = protocol

    if port:
        rule_body["rule"]["destination_port"] = port

    data, err = _firewall_safe_apply(cfg, "firewall/filter/addRule", rule_body)
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "result": data,
        },
    )


def handle_opnsense_rule_delete(handler):
    """POST /api/opnsense/rules/delete -- delete a firewall filter rule.

    Body: {"uuid": "abc-123-def"}

    Uses the savepoint safety pattern: savepoint -> delRule -> apply -> cancelRollback.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    uuid = body.get("uuid", "").strip()

    if not uuid or not _SAFE_UUID.match(uuid):
        json_response(handler, {"error": "Valid UUID required (format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)"}, 400)
        return

    data, err = _firewall_safe_apply(cfg, f"firewall/filter/delRule/{uuid}")
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "delete",
            "uuid": uuid,
            "result": data,
        },
    )


def handle_opnsense_dhcp_add(handler):
    """POST /api/opnsense/dhcp/add -- add a Kea DHCP reservation.

    Body: {"mac": "AA:BB:CC:DD:EE:FF", "ip": "10.0.0.50", "hostname": "myhost"}

    Adds the reservation then reconfigures the Kea service to apply.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    mac = body.get("mac", "").strip()
    ip = body.get("ip", "").strip()
    hostname = body.get("hostname", "").strip()

    if not mac:
        json_response(handler, {"error": "mac is required"}, 400)
        return
    if not ip:
        json_response(handler, {"error": "ip is required"}, 400)
        return

    reservation_body = {
        "reservation": {
            "hw_address": mac,
            "ip_address": ip,
        }
    }
    if hostname:
        reservation_body["reservation"]["hostname"] = hostname

    # Add the reservation
    data, err = _opn_request(cfg, "kea/dhcpv4/addReservation", method="POST", body=reservation_body)
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    # Reconfigure Kea to apply
    _, reconf_err = _opn_request(cfg, "kea/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "add",
                "warning": f"Reservation added but reconfigure failed: {reconf_err}",
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "mac": mac,
            "ip": ip,
            "hostname": hostname,
            "result": data,
        },
    )


def handle_opnsense_dhcp_delete(handler):
    """POST /api/opnsense/dhcp/delete -- delete a Kea DHCP reservation.

    Body: {"uuid": "abc-123"}

    Deletes the reservation then reconfigures the Kea service to apply.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    uuid = body.get("uuid", "").strip()

    if not uuid or not _SAFE_UUID.match(uuid):
        json_response(handler, {"error": "Valid UUID required"}, 400)
        return

    # Delete the reservation
    data, err = _opn_request(cfg, f"kea/dhcpv4/delReservation/{uuid}", method="POST")
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    # Reconfigure Kea to apply
    _, reconf_err = _opn_request(cfg, "kea/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "delete",
                "uuid": uuid,
                "warning": f"Reservation deleted but reconfigure failed: {reconf_err}",
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "delete",
            "uuid": uuid,
            "result": data,
        },
    )


def handle_opnsense_dns_add(handler):
    """POST /api/opnsense/dns/add -- add an Unbound DNS host override.

    Body: {"host": "myapp", "domain": "lab.local", "ip": "10.0.0.50"}

    Adds the override then reconfigures Unbound to apply.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    host = body.get("host", "").strip()
    domain = body.get("domain", "").strip()
    ip = body.get("ip", "").strip()

    if not host:
        json_response(handler, {"error": "host is required"}, 400)
        return
    if not domain:
        json_response(handler, {"error": "domain is required"}, 400)
        return
    if not ip:
        json_response(handler, {"error": "ip is required"}, 400)
        return

    override_body = {
        "host": {
            "hostname": host,
            "domain": domain,
            "server": ip,
            "enabled": "1",
        }
    }

    # Add the host override
    data, err = _opn_request(cfg, "unbound/settings/addHostOverride", method="POST", body=override_body)
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    # Reconfigure Unbound to apply
    _, reconf_err = _opn_request(cfg, "unbound/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "add",
                "warning": f"Override added but reconfigure failed: {reconf_err}",
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "host": host,
            "domain": domain,
            "ip": ip,
            "result": data,
        },
    )


def handle_opnsense_dns_delete(handler):
    """POST /api/opnsense/dns/delete -- delete an Unbound DNS host override.

    Body: {"uuid": "abc-123"}

    Deletes the override then reconfigures Unbound to apply.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    uuid = body.get("uuid", "").strip()

    if not uuid or not _SAFE_UUID.match(uuid):
        json_response(handler, {"error": "Valid UUID required"}, 400)
        return

    # Delete the host override
    data, err = _opn_request(cfg, f"unbound/settings/delHostOverride/{uuid}", method="POST")
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    # Reconfigure Unbound to apply
    _, reconf_err = _opn_request(cfg, "unbound/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "delete",
                "uuid": uuid,
                "warning": f"Override deleted but reconfigure failed: {reconf_err}",
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "delete",
            "uuid": uuid,
            "result": data,
        },
    )


def handle_opnsense_wg_add(handler):
    """POST /api/opnsense/wireguard/add -- add a WireGuard peer.

    Body: {
        "name": "peer1",
        "pubkey": "...",
        "tunneladdress": "10.25.100.5/32",
        "serveruuid": "..."
    }

    Adds the peer then reconfigures WireGuard to apply.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    name = body.get("name", "").strip()
    pubkey = body.get("pubkey", "").strip()
    tunneladdress = body.get("tunneladdress", "").strip()
    serveruuid = body.get("serveruuid", "").strip()

    if not name:
        json_response(handler, {"error": "name is required"}, 400)
        return
    if not pubkey:
        json_response(handler, {"error": "pubkey is required"}, 400)
        return
    if not tunneladdress:
        json_response(handler, {"error": "tunneladdress is required"}, 400)
        return

    client_body = {
        "client": {
            "name": name,
            "pubkey": pubkey,
            "tunneladdress": tunneladdress,
            "enabled": "1",
        }
    }
    if serveruuid:
        client_body["client"]["servers"] = serveruuid

    # Add the WireGuard peer
    data, err = _opn_request(cfg, "wireguard/client/addClient", method="POST", body=client_body)
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    # Reconfigure WireGuard to apply
    _, reconf_err = _opn_request(cfg, "wireguard/service/reconfigure", method="POST")
    if reconf_err:
        json_response(
            handler,
            {
                "ok": True,
                "action": "add",
                "warning": f"Peer added but reconfigure failed: {reconf_err}",
                "result": data,
            },
        )
        return

    json_response(
        handler,
        {
            "ok": True,
            "action": "add",
            "name": name,
            "pubkey": pubkey,
            "tunneladdress": tunneladdress,
            "result": data,
        },
    )


def handle_opnsense_reboot(handler):
    """POST /api/opnsense/reboot -- reboot OPNsense.

    Body: {"confirm": true}

    Requires explicit confirmation to prevent accidental reboots.
    This will take down the firewall and all network services.
    """
    cfg, ok = _require_opnsense(handler)
    if not ok:
        return

    body = get_json_body(handler)
    if not body.get("confirm"):
        json_response(handler, {"error": "Must set confirm: true"}, 400)
        return

    data, err = _opn_request(cfg, "core/system/reboot", method="POST")
    if err:
        json_response(handler, {"ok": False, "error": err}, 502)
        return

    json_response(handler, {"ok": True, "message": "Reboot command sent", "result": data})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register OPNsense API routes."""
    # Read operations (no role check)
    routes["/api/opnsense/status"] = handle_opnsense_status
    routes["/api/opnsense/services"] = handle_opnsense_services
    routes["/api/opnsense/rules"] = handle_opnsense_rules
    routes["/api/opnsense/dhcp"] = handle_opnsense_dhcp
    routes["/api/opnsense/dns"] = handle_opnsense_dns
    routes["/api/opnsense/wireguard"] = handle_opnsense_wireguard
    routes["/api/opnsense/firmware"] = handle_opnsense_firmware

    # Write operations (admin only)
    routes["/api/opnsense/rules/add"] = handle_opnsense_rule_add
    routes["/api/opnsense/rules/delete"] = handle_opnsense_rule_delete
    routes["/api/opnsense/dhcp/add"] = handle_opnsense_dhcp_add
    routes["/api/opnsense/dhcp/delete"] = handle_opnsense_dhcp_delete
    routes["/api/opnsense/dns/add"] = handle_opnsense_dns_add
    routes["/api/opnsense/dns/delete"] = handle_opnsense_dns_delete
    routes["/api/opnsense/wireguard/add"] = handle_opnsense_wg_add
    routes["/api/opnsense/service/action"] = handle_opnsense_service_action
    routes["/api/opnsense/reboot"] = handle_opnsense_reboot
