"""Redfish domain API handlers -- /api/redfish/*.

Who:   Redfish REST API for modern BMCs (HP iLO, Supermicro, any compliant server).
What:  REST endpoints for system info, thermal, power, event logs, and power control.
Why:   Redfish (DMTF standard) replaces legacy IPMI for modern server management.
       Provides structured JSON data instead of ipmitool text parsing.
Where: Routes registered at /api/redfish/*.
When:  Called by serve.py dispatcher via domain route table.

Architecture:
    - Python stdlib only (urllib.request, json, ssl, base64).
    - HTTP Basic auth to BMC Redfish endpoints over HTTPS.
    - SSL verification disabled (self-signed BMC certs are the norm).
    - Credentials from vault: bmc_user / bmc_pass per device label.
    - Targets resolved from fleet-boundaries physical devices with type
      "ilo" or "redfish".
    - Base URL: https://{ip}/redfish/v1
"""

import base64
import json
import ssl
import urllib.error
import urllib.request

from freq.api.helpers import json_response, get_json_body, get_param
from freq.core.config import load_config
from freq.modules.serve import _check_session_role
from freq.modules.vault import vault_get


# -- Helpers ------------------------------------------------------------------


def _redfish_request(ip, path, user, password, method="GET", body=None):
    """Make a Redfish REST API request to a BMC.

    Args:
        ip: BMC IP address.
        path: API path (e.g., "/redfish/v1/Systems/1").
        user: BMC username.
        password: BMC password.
        method: HTTP method (GET, POST, PATCH, DELETE).
        body: Optional dict to send as JSON body.

    Returns:
        (data_dict, ok_bool, error_str)
    """
    url = f"https://{ip}{path}"

    # HTTP Basic auth header
    creds = f"{user}:{password}"
    b64 = base64.b64encode(creds.encode()).decode()

    headers = {
        "Authorization": f"Basic {b64}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "OData-Version": "4.0",
    }

    encoded_body = None
    if body is not None:
        encoded_body = json.dumps(body).encode()

    req = urllib.request.Request(url, data=encoded_body, headers=headers, method=method)

    # BMCs use self-signed certs — disable verification
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            raw = resp.read().decode()
            if raw.strip():
                return json.loads(raw), True, ""
            # Some POST actions return empty body on success (204)
            return {}, True, ""
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode()[:500]
        except Exception:
            pass
        return {}, False, f"HTTP {e.code}: {error_body or e.reason}"
    except urllib.error.URLError as e:
        return {}, False, f"Connection failed: {e.reason}"
    except json.JSONDecodeError:
        return {}, False, "Invalid JSON response from BMC"
    except Exception as e:
        return {}, False, f"Redfish request failed: {e}"


def _resolve_redfish_targets(cfg, target=None):
    """Find Redfish BMCs from fleet-boundaries physical devices.

    Returns dict of {label: ip} for devices with device_type in
    ("ilo", "redfish"). If target is specified, filters by
    case-insensitive substring match on label.
    """
    fb = cfg.fleet_boundaries
    targets = {}
    for key, dev in fb.physical.items():
        if dev.device_type in ("ilo", "redfish"):
            targets[dev.label] = dev.ip

    if target:
        matched = {k: v for k, v in targets.items() if target.lower() in k.lower()}
        return matched if matched else {}

    return targets


def _get_bmc_creds(cfg, label):
    """Retrieve BMC credentials from vault for a device label.

    Returns (user, password) or (None, None) if not configured.
    """
    user = vault_get(cfg, label, "bmc_user")
    password = vault_get(cfg, label, "bmc_pass")
    if not user or not password:
        return None, None
    return user, password


# -- GET Handlers -------------------------------------------------------------


def handle_redfish_system(handler):
    """GET /api/redfish/system?target=X -- system overview.

    Returns model, serial number, BIOS version, power state, CPU, and memory
    from /redfish/v1/Systems/1.
    """
    cfg = load_config()
    target = get_param(handler, "target")
    targets = _resolve_redfish_targets(cfg, target or None)

    if not targets:
        json_response(
            handler,
            {
                "error": "No Redfish targets found" + (f" matching '{target}'" if target else ""),
                "hint": "Add physical devices with type 'ilo' or 'redfish' to fleet-boundaries.toml",
            },
            404,
        )
        return

    results = []
    for label, ip in targets.items():
        user, password = _get_bmc_creds(cfg, label)
        if not user:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        data, ok, err = _redfish_request(ip, "/redfish/v1/Systems/1", user, password)
        if not ok:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": err,
                }
            )
            continue

        # Extract processor summary
        proc = data.get("ProcessorSummary", {})
        mem = data.get("MemorySummary", {})

        results.append(
            {
                "name": label,
                "ip": ip,
                "reachable": True,
                "model": data.get("Model", ""),
                "manufacturer": data.get("Manufacturer", ""),
                "serial": data.get("SerialNumber", ""),
                "bios_version": data.get("BiosVersion", ""),
                "power_state": data.get("PowerState", ""),
                "host_name": data.get("HostName", ""),
                "processor": {
                    "model": proc.get("Model", ""),
                    "count": proc.get("Count", 0),
                    "logical_count": proc.get("LogicalProcessorCount", 0),
                },
                "memory": {
                    "total_gb": mem.get("TotalSystemMemoryGiB", 0),
                    "status": mem.get("Status", {}).get("Health", ""),
                },
                "status": data.get("Status", {}).get("Health", ""),
                "error": "",
            }
        )

    json_response(handler, {"targets": results})


def handle_redfish_thermal(handler):
    """GET /api/redfish/thermal?target=X -- temperatures and fans.

    Returns thermal data from /redfish/v1/Chassis/1/Thermal.
    """
    cfg = load_config()
    target = get_param(handler, "target")
    targets = _resolve_redfish_targets(cfg, target or None)

    if not targets:
        json_response(
            handler,
            {
                "error": "No Redfish targets found" + (f" matching '{target}'" if target else ""),
            },
            404,
        )
        return

    results = []
    for label, ip in targets.items():
        user, password = _get_bmc_creds(cfg, label)
        if not user:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        data, ok, err = _redfish_request(ip, "/redfish/v1/Chassis/1/Thermal", user, password)
        if not ok:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": err,
                }
            )
            continue

        temperatures = []
        for t in data.get("Temperatures", []):
            temperatures.append(
                {
                    "name": t.get("Name", ""),
                    "reading_celsius": t.get("ReadingCelsius"),
                    "upper_threshold_critical": t.get("UpperThresholdCritical"),
                    "upper_threshold_fatal": t.get("UpperThresholdFatal"),
                    "status": t.get("Status", {}).get("Health", ""),
                    "state": t.get("Status", {}).get("State", ""),
                }
            )

        fans = []
        for f in data.get("Fans", []):
            fans.append(
                {
                    "name": f.get("Name", ""),
                    "reading": f.get("Reading"),
                    "reading_units": f.get("ReadingUnits", ""),
                    "status": f.get("Status", {}).get("Health", ""),
                    "state": f.get("Status", {}).get("State", ""),
                }
            )

        results.append(
            {
                "name": label,
                "ip": ip,
                "reachable": True,
                "temperatures": temperatures,
                "fans": fans,
                "error": "",
            }
        )

    json_response(handler, {"targets": results})


def handle_redfish_power_usage(handler):
    """GET /api/redfish/power-usage?target=X -- power consumption.

    Returns power supply and consumption data from /redfish/v1/Chassis/1/Power.
    """
    cfg = load_config()
    target = get_param(handler, "target")
    targets = _resolve_redfish_targets(cfg, target or None)

    if not targets:
        json_response(
            handler,
            {
                "error": "No Redfish targets found" + (f" matching '{target}'" if target else ""),
            },
            404,
        )
        return

    results = []
    for label, ip in targets.items():
        user, password = _get_bmc_creds(cfg, label)
        if not user:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        data, ok, err = _redfish_request(ip, "/redfish/v1/Chassis/1/Power", user, password)
        if not ok:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": err,
                }
            )
            continue

        # Power control entries (aggregate consumption)
        power_control = []
        for pc in data.get("PowerControl", []):
            metrics = pc.get("PowerMetrics", {})
            power_control.append(
                {
                    "name": pc.get("Name", ""),
                    "power_consumed_watts": pc.get("PowerConsumedWatts"),
                    "power_capacity_watts": pc.get("PowerCapacityWatts"),
                    "avg_watts": metrics.get("AverageConsumedWatts"),
                    "max_watts": metrics.get("MaxConsumedWatts"),
                    "min_watts": metrics.get("MinConsumedWatts"),
                    "interval_minutes": metrics.get("IntervalInMin"),
                }
            )

        # Power supplies
        power_supplies = []
        for ps in data.get("PowerSupplies", []):
            power_supplies.append(
                {
                    "name": ps.get("Name", ""),
                    "model": ps.get("Model", ""),
                    "serial": ps.get("SerialNumber", ""),
                    "power_capacity_watts": ps.get("PowerCapacityWatts"),
                    "last_output_watts": ps.get("LastPowerOutputWatts"),
                    "line_input_voltage": ps.get("LineInputVoltage"),
                    "status": ps.get("Status", {}).get("Health", ""),
                    "state": ps.get("Status", {}).get("State", ""),
                }
            )

        results.append(
            {
                "name": label,
                "ip": ip,
                "reachable": True,
                "power_control": power_control,
                "power_supplies": power_supplies,
                "error": "",
            }
        )

    json_response(handler, {"targets": results})


def handle_redfish_events(handler):
    """GET /api/redfish/events?target=X -- event log (last 20 entries).

    Returns entries from /redfish/v1/Managers/1/LogServices/IEL/Entries.
    """
    cfg = load_config()
    target = get_param(handler, "target")
    targets = _resolve_redfish_targets(cfg, target or None)

    if not targets:
        json_response(
            handler,
            {
                "error": "No Redfish targets found" + (f" matching '{target}'" if target else ""),
            },
            404,
        )
        return

    results = []
    for label, ip in targets.items():
        user, password = _get_bmc_creds(cfg, label)
        if not user:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        # Try iLO IEL path first, fall back to generic log path
        data, ok, err = _redfish_request(
            ip,
            "/redfish/v1/Managers/1/LogServices/IEL/Entries",
            user,
            password,
        )
        if not ok:
            # Fallback: some BMCs use a different log service path
            data, ok, err = _redfish_request(
                ip,
                "/redfish/v1/Managers/1/LogServices/Log1/Entries",
                user,
                password,
            )
        if not ok:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "error": err,
                }
            )
            continue

        # Extract log entries (Redfish returns Members array)
        members = data.get("Members", [])
        # Sort by Id descending (newest first) and take last 20
        try:
            members.sort(key=lambda m: int(m.get("Id", "0")), reverse=True)
        except (ValueError, TypeError):
            # If Ids are not numeric, keep original order
            members.reverse()

        entries = []
        for entry in members[:20]:
            entries.append(
                {
                    "id": entry.get("Id", ""),
                    "severity": entry.get("Severity", entry.get("EntryType", "")),
                    "message": entry.get("Message", ""),
                    "created": entry.get("Created", ""),
                    "entry_type": entry.get("EntryType", ""),
                }
            )

        results.append(
            {
                "name": label,
                "ip": ip,
                "reachable": True,
                "entries": entries,
                "total_entries": data.get("Members@odata.count", len(members)),
                "error": "",
            }
        )

    json_response(handler, {"targets": results})


# -- POST Handlers (admin only) -----------------------------------------------


def handle_redfish_power(handler):
    """POST /api/redfish/power -- system power control (admin only).

    Body: {"target": "label", "action": "On|ForceOff|GracefulShutdown|ForceRestart"}

    Posts ResetType to /redfish/v1/Systems/1/Actions/ComputerSystem.Reset.
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    target = body.get("target", "").strip()
    action = body.get("action", "").strip()

    if not target:
        json_response(handler, {"error": "target is required"}, 400)
        return

    valid_actions = ("On", "ForceOff", "GracefulShutdown", "ForceRestart", "GracefulRestart", "Nmi", "PushPowerButton")
    if action not in valid_actions:
        json_response(
            handler,
            {
                "error": f"Invalid action: '{action}'. Must be one of: {', '.join(valid_actions)}",
            },
            400,
        )
        return

    cfg = load_config()
    targets = _resolve_redfish_targets(cfg, target)
    if not targets:
        json_response(handler, {"error": f"No Redfish target found matching '{target}'"}, 404)
        return

    results = []
    for label, ip in targets.items():
        user, password = _get_bmc_creds(cfg, label)
        if not user:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "ok": False,
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        reset_body = {"ResetType": action}
        data, ok, err_msg = _redfish_request(
            ip,
            "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset",
            user,
            password,
            method="POST",
            body=reset_body,
        )

        results.append(
            {
                "name": label,
                "ip": ip,
                "ok": ok,
                "action": action,
                "error": err_msg if not ok else "",
            }
        )

    json_response(handler, {"action": action, "targets": results})


# -- Registration -------------------------------------------------------------


def register(routes: dict):
    """Register Redfish API routes into the master route table."""
    # Read endpoints (no auth required)
    routes["/api/redfish/system"] = handle_redfish_system
    routes["/api/redfish/thermal"] = handle_redfish_thermal
    routes["/api/redfish/power-usage"] = handle_redfish_power_usage
    routes["/api/redfish/events"] = handle_redfish_events

    # Write endpoints (admin only)
    routes["/api/redfish/power"] = handle_redfish_power
