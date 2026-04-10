"""IPMI domain API handlers -- /api/ipmi/*.

Who:   Generic IPMI management via ipmitool (LAN-based, no SSH to BMC).
What:  REST endpoints for IPMI status, sensors, SEL, power control, boot device.
Why:   Provides vendor-agnostic out-of-band hardware management for any
       IPMI-compliant BMC (Dell iDRAC, Supermicro, HP iLO in IPMI mode, etc.).
Where: Routes registered at /api/ipmi/*.
When:  Called by serve.py dispatcher via domain route table.

Architecture:
    - Runs ipmitool from the FREQ controller host over LAN (IPMI-over-LAN).
    - No SSH to BMCs — all communication via IPMI protocol (UDP 623).
    - Credentials from vault: bmc_user / bmc_pass per device label.
    - Targets resolved from fleet-boundaries physical devices with type
      "ipmi", "ilo", or "bmc".
    - Python stdlib only (subprocess, json).
"""

import os
import subprocess

from freq.core import log as logger
from freq.api.helpers import require_post, json_response, get_json_body, get_param
from freq.core.config import load_config
from freq.modules.serve import _check_session_role
from freq.modules.vault import vault_get


# -- Helpers ------------------------------------------------------------------


def _ipmitool(ip, user, password, *args):
    """Run an ipmitool command over LAN. Returns (stdout, ok).

    Uses lanplus interface for IPMI v2.0 encrypted sessions.
    Password passed via environment variable (IPMI_PASSWORD) to avoid
    exposing it in ps aux output. Timeout of 15 seconds.
    """
    cmd = [
        "ipmitool",
        "-I",
        "lanplus",
        "-H",
        ip,
        "-U",
        user,
        "-E",
    ] + list(args)
    env = os.environ.copy()
    env["IPMI_PASSWORD"] = password
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        return result.stdout.strip(), result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warn("api_ipmi: ipmitool timed out", host=ip)
        return "ipmitool command timed out (15s)", False
    except FileNotFoundError:
        logger.error("api_ipmi_error: ipmitool binary not found")
        return "ipmitool not found — install it: apt install ipmitool", False
    except Exception as e:
        logger.error(f"api_ipmi_error: {e}", host=ip)
        return f"ipmitool error: {e}", False


def _resolve_ipmi_targets(cfg, target=None):
    """Find IPMI BMCs from fleet-boundaries physical devices.

    Returns dict of {label: ip} for devices with device_type in
    ("ipmi", "ilo", "bmc"). If target is specified, filters by
    case-insensitive substring match on label.
    """
    fb = cfg.fleet_boundaries
    targets = {}
    for key, dev in fb.physical.items():
        if dev.device_type in ("ipmi", "ilo", "bmc"):
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


def _run_ipmi_for_targets(cfg, targets, *ipmi_args):
    """Run an ipmitool command against one or more targets.

    Returns a list of result dicts with name, ip, reachable, output, error.
    """
    results = []
    for label, ip in targets.items():
        user, password = _get_bmc_creds(cfg, label)
        if not user:
            results.append(
                {
                    "name": label,
                    "ip": ip,
                    "reachable": False,
                    "output": "",
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        stdout, ok = _ipmitool(ip, user, password, *ipmi_args)
        results.append(
            {
                "name": label,
                "ip": ip,
                "reachable": ok,
                "output": stdout[:4000] if ok else "",
                "error": stdout[:200] if not ok else "",
            }
        )
    return results


# -- GET Handlers -------------------------------------------------------------


def handle_ipmi_status(handler):
    """GET /api/ipmi/status?target=X -- BMC info and chassis power status.

    Runs `ipmitool mc info` and `chassis power status` against each target.
    If target is omitted, queries all known IPMI devices.
    """
    cfg = load_config()
    target = get_param(handler, "target")
    targets = _resolve_ipmi_targets(cfg, target or None)

    if not targets:
        json_response(
            handler,
            {
                "error": "No IPMI targets found" + (f" matching '{target}'" if target else ""),
                "hint": "Add physical devices with type 'ipmi' to fleet-boundaries.toml",
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
                    "mc_info": "",
                    "power_status": "",
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        mc_out, mc_ok = _ipmitool(ip, user, password, "mc", "info")
        pwr_out, pwr_ok = _ipmitool(ip, user, password, "chassis", "power", "status")

        results.append(
            {
                "name": label,
                "ip": ip,
                "reachable": mc_ok or pwr_ok,
                "mc_info": mc_out[:2000] if mc_ok else "",
                "power_status": pwr_out.strip() if pwr_ok else "",
                "error": (mc_out[:200] if not mc_ok else "") or (pwr_out[:200] if not pwr_ok else ""),
            }
        )

    json_response(handler, {"targets": results})


def handle_ipmi_sensors(handler):
    """GET /api/ipmi/sensors?target=X -- sensor data via `ipmitool sdr list`.

    Returns raw SDR (Sensor Data Record) output for each target.
    """
    cfg = load_config()
    target = get_param(handler, "target")
    targets = _resolve_ipmi_targets(cfg, target or None)

    if not targets:
        json_response(
            handler,
            {
                "error": "No IPMI targets found" + (f" matching '{target}'" if target else ""),
            },
            404,
        )
        return

    results = _run_ipmi_for_targets(cfg, targets, "sdr", "list")
    json_response(handler, {"targets": results})


def handle_ipmi_sel(handler):
    """GET /api/ipmi/sel?target=X -- System Event Log (last 20 entries).

    Returns recent SEL entries for hardware event auditing.
    """
    cfg = load_config()
    target = get_param(handler, "target")
    targets = _resolve_ipmi_targets(cfg, target or None)

    if not targets:
        json_response(
            handler,
            {
                "error": "No IPMI targets found" + (f" matching '{target}'" if target else ""),
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
                    "output": "",
                    "error": "BMC credentials not found in vault",
                }
            )
            continue

        stdout, ok = _ipmitool(ip, user, password, "sel", "list")
        # Limit to last 20 entries
        if ok and stdout:
            lines = stdout.strip().split("\n")
            trimmed = lines[-20:] if len(lines) > 20 else lines
            stdout = "\n".join(trimmed)

        results.append(
            {
                "name": label,
                "ip": ip,
                "reachable": ok,
                "output": stdout[:4000] if ok else "",
                "entries": len(stdout.strip().split("\n")) if ok and stdout.strip() else 0,
                "error": stdout[:200] if not ok else "",
            }
        )

    json_response(handler, {"targets": results})


# -- POST Handlers (admin only) -----------------------------------------------


def handle_ipmi_power(handler):
    """POST /api/ipmi/power -- chassis power control (admin only).

    Body: {"target": "label", "action": "on|off|cycle|reset|status"}

    Maps to: ipmitool chassis power {action}
    """
    if require_post(handler, "IPMI power"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    target = body.get("target", "").strip()
    action = body.get("action", "").strip().lower()

    if not target:
        json_response(handler, {"error": "target is required"}, 400)
        return

    valid_actions = ("on", "off", "cycle", "reset", "status")
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
    targets = _resolve_ipmi_targets(cfg, target)
    if not targets:
        json_response(handler, {"error": f"No IPMI target found matching '{target}'"}, 404)
        return

    results = _run_ipmi_for_targets(cfg, targets, "chassis", "power", action)
    json_response(handler, {"action": action, "targets": results})


def handle_ipmi_boot(handler):
    """POST /api/ipmi/boot -- set next boot device (admin only).

    Body: {"target": "label", "device": "pxe|bios|disk|cdrom"}

    Maps to: ipmitool chassis bootdev {device}
    """
    if require_post(handler, "IPMI boot device"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    target = body.get("target", "").strip()
    device = body.get("device", "").strip().lower()

    if not target:
        json_response(handler, {"error": "target is required"}, 400)
        return

    valid_devices = ("pxe", "bios", "disk", "cdrom")
    if device not in valid_devices:
        json_response(
            handler,
            {
                "error": f"Invalid device: '{device}'. Must be one of: {', '.join(valid_devices)}",
            },
            400,
        )
        return

    cfg = load_config()
    targets = _resolve_ipmi_targets(cfg, target)
    if not targets:
        json_response(handler, {"error": f"No IPMI target found matching '{target}'"}, 404)
        return

    results = _run_ipmi_for_targets(cfg, targets, "chassis", "bootdev", device)
    json_response(handler, {"action": "bootdev", "device": device, "targets": results})


def handle_ipmi_sel_clear(handler):
    """POST /api/ipmi/sel/clear -- clear the System Event Log (admin only).

    Body: {"target": "label"}

    Maps to: ipmitool sel clear
    """
    if require_post(handler, "IPMI SEL clear"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    target = body.get("target", "").strip()

    if not target:
        json_response(handler, {"error": "target is required"}, 400)
        return

    cfg = load_config()
    targets = _resolve_ipmi_targets(cfg, target)
    if not targets:
        json_response(handler, {"error": f"No IPMI target found matching '{target}'"}, 404)
        return

    results = _run_ipmi_for_targets(cfg, targets, "sel", "clear")
    json_response(handler, {"action": "sel_clear", "targets": results})


# -- Registration -------------------------------------------------------------


def register(routes: dict):
    """Register IPMI API routes into the master route table."""
    # Read endpoints (no auth required)
    routes["/api/ipmi/status"] = handle_ipmi_status
    routes["/api/ipmi/sensors"] = handle_ipmi_sensors
    routes["/api/ipmi/sel"] = handle_ipmi_sel

    # Write endpoints (admin only)
    routes["/api/ipmi/power"] = handle_ipmi_power
    routes["/api/ipmi/boot"] = handle_ipmi_boot
    routes["/api/ipmi/sel/clear"] = handle_ipmi_sel_clear
