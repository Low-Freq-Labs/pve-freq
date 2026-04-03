"""Synology DSM API handlers -- REST integration for Synology NAS devices.

Who:   New module for Synology DSM management.
What:  REST endpoints proxying to Synology's SYNO.* API.
Why:   Synology is the second most popular NAS platform in homelabs.
Where: Routes registered at /api/synology/*.
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.

Synology DSM API uses session-based auth:
  1. POST SYNO.API.Auth login → get session ID (sid)
  2. Pass _sid=<sid> on all subsequent requests
  3. Sessions expire after inactivity (default 15 min)
"""

import json
import ssl
import urllib.request
import urllib.error
import urllib.parse

from freq.api.helpers import json_response, get_json_body, get_param
from freq.core.config import load_config
from freq.modules.serve import _check_session_role
from freq.modules.vault import vault_get


# -- Session cache -----------------------------------------------------------

_synology_session = {"sid": "", "ip": ""}


# -- Helper ------------------------------------------------------------------

def _syn_url(ip, api, version, method, extra_params=None):
    """Build a Synology DSM API URL."""
    params = {
        "api": api,
        "version": str(version),
        "method": method,
    }
    if extra_params:
        params.update(extra_params)
    if _synology_session["sid"] and _synology_session["ip"] == ip:
        params["_sid"] = _synology_session["sid"]
    qs = urllib.parse.urlencode(params)
    return f"http://{ip}:5000/webapi/entry.cgi?{qs}"


def _syn_request(ip, api, version, method, extra_params=None, timeout=15):
    """Make a request to the Synology DSM API. Returns (data, error)."""
    url = _syn_url(ip, api, version, method, extra_params)
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        if data.get("success"):
            return data.get("data", {}), None
        code = data.get("error", {}).get("code", 0)
        # Session expired — clear cache
        if code in (105, 106, 107):
            _synology_session["sid"] = ""
            return None, "Session expired — re-login required"
        return None, f"API error code {code}"
    except urllib.error.URLError as e:
        return None, f"Connection failed: {e}"
    except Exception as e:
        return None, str(e)


def _syn_login(cfg):
    """Login to Synology DSM and cache session ID. Returns (sid, error)."""
    ip = cfg.synology_ip
    if not ip:
        return None, "Synology not configured"

    user = vault_get(cfg, "synology", "dsm_user") or "admin"
    passwd = vault_get(cfg, "synology", "dsm_pass") or ""
    if not passwd:
        return None, "Synology credentials not in vault (synology|dsm_user, synology|dsm_pass)"

    data, err = _syn_request(ip, "SYNO.API.Auth", 6, "login", {
        "account": user,
        "passwd": passwd,
        "format": "sid",
    })
    if err:
        return None, f"Login failed: {err}"
    sid = data.get("sid", "")
    if not sid:
        return None, "No session ID returned"
    _synology_session["sid"] = sid
    _synology_session["ip"] = ip
    return sid, None


def _ensure_session(cfg):
    """Ensure we have a valid Synology session. Returns (ip, error)."""
    ip = cfg.synology_ip
    if not ip:
        return None, "Synology IP not configured"
    if _synology_session["sid"] and _synology_session["ip"] == ip:
        return ip, None
    _, err = _syn_login(cfg)
    if err:
        return None, err
    return ip, None


def _require_synology(handler, admin=False):
    """Check role (optionally admin) and Synology session. Returns (cfg, ip, ok)."""
    if admin:
        role, err = _check_session_role(handler, "admin")
        if err:
            json_response(handler, {"error": err}, 403)
            return None, None, False
    cfg = load_config()
    ip, err = _ensure_session(cfg)
    if err:
        json_response(handler, {"error": err}, 400)
        return None, None, False
    return cfg, ip, True


# -- Read Handlers -----------------------------------------------------------


def handle_synology_status(handler):
    """GET /api/synology/status -- system info via SYNO.DSM.Info."""
    cfg, ip, ok = _require_synology(handler)
    if not ok:
        return

    data, err = _syn_request(ip, "SYNO.DSM.Info", 2, "getinfo")
    if err:
        json_response(handler, {"ok": False, "error": err})
        return

    json_response(handler, {
        "ok": True,
        "model": data.get("model", ""),
        "ram": data.get("ram", 0),
        "serial": data.get("serial", ""),
        "version": data.get("version_string", ""),
        "uptime": data.get("uptime", 0),
        "temperature": data.get("temperature", 0),
        "raw": data,
    })


def handle_synology_storage(handler):
    """GET /api/synology/storage -- volume and disk status."""
    cfg, ip, ok = _require_synology(handler)
    if not ok:
        return

    data, err = _syn_request(ip, "SYNO.Storage.CGI.Storage", 1, "load_info")
    if err:
        json_response(handler, {"ok": False, "error": err})
        return

    volumes = []
    for vol in data.get("volumes", []):
        volumes.append({
            "id": vol.get("id", ""),
            "status": vol.get("status", ""),
            "total_size": vol.get("size", {}).get("total", ""),
            "used_size": vol.get("size", {}).get("used", ""),
            "fs_type": vol.get("fs_type", ""),
        })

    disks = []
    for disk in data.get("disks", []):
        disks.append({
            "name": disk.get("name", ""),
            "model": disk.get("model", ""),
            "vendor": disk.get("vendor", ""),
            "size": disk.get("size_total", 0),
            "temp": disk.get("temp", 0),
            "status": disk.get("status", ""),
            "smart_status": disk.get("smart_status", ""),
        })

    json_response(handler, {"ok": True, "volumes": volumes, "disks": disks})


def handle_synology_shares(handler):
    """GET /api/synology/shares -- shared folder list."""
    cfg, ip, ok = _require_synology(handler)
    if not ok:
        return

    data, err = _syn_request(ip, "SYNO.FileStation.List", 2, "list_share")
    if err:
        json_response(handler, {"ok": False, "error": err})
        return

    shares = []
    for s in data.get("shares", []):
        shares.append({
            "name": s.get("name", ""),
            "path": s.get("path", ""),
            "is_dir": s.get("isdir", False),
        })

    json_response(handler, {"ok": True, "shares": shares, "total": data.get("total", 0)})


def handle_synology_docker(handler):
    """GET /api/synology/docker -- Docker container list (DSM 7+)."""
    cfg, ip, ok = _require_synology(handler)
    if not ok:
        return

    # Docker Manager API — may not be available on all models
    data, err = _syn_request(ip, "SYNO.Docker.Container", 1, "list", {"limit": 50, "offset": 0})
    if err:
        json_response(handler, {"ok": False, "error": f"Docker API unavailable: {err}"})
        return

    containers = []
    for c in data.get("containers", []):
        containers.append({
            "name": c.get("name", ""),
            "image": c.get("image", ""),
            "status": c.get("status", ""),
            "state": c.get("state", ""),
        })

    json_response(handler, {"ok": True, "containers": containers, "total": len(containers)})


def handle_synology_packages(handler):
    """GET /api/synology/packages -- installed package list."""
    cfg, ip, ok = _require_synology(handler)
    if not ok:
        return

    data, err = _syn_request(ip, "SYNO.Core.Package", 1, "list", {"additional": '["description"]'})
    if err:
        json_response(handler, {"ok": False, "error": err})
        return

    packages = []
    for pkg in data.get("packages", []):
        packages.append({
            "id": pkg.get("id", ""),
            "name": pkg.get("name", ""),
            "version": pkg.get("version", ""),
            "status": "running" if pkg.get("additional", {}).get("status") == "running" else "stopped",
        })

    json_response(handler, {"ok": True, "packages": packages})


# -- Write Handlers ----------------------------------------------------------


def handle_synology_service(handler):
    """POST /api/synology/service -- start or stop a package/service.

    Body: {"package": "ContainerManager", "action": "start|stop"}
    """
    cfg, ip, ok = _require_synology(handler, admin=True)
    if not ok:
        return

    body = get_json_body(handler)
    package = body.get("package", "").strip()
    action = body.get("action", "")

    if not package:
        json_response(handler, {"error": "package required"}, 400)
        return
    if action not in ("start", "stop"):
        json_response(handler, {"error": "action must be start or stop"}, 400)
        return

    data, err = _syn_request(ip, "SYNO.Core.Package.Control", 1, action, {"id": package})
    if err:
        json_response(handler, {"ok": False, "error": err})
    else:
        json_response(handler, {"ok": True, "action": action, "package": package})


def handle_synology_reboot(handler):
    """POST /api/synology/reboot -- reboot Synology NAS.

    Body: {"confirm": true}
    """
    cfg, ip, ok = _require_synology(handler, admin=True)
    if not ok:
        return

    body = get_json_body(handler)
    if not body.get("confirm"):
        json_response(handler, {"error": "Must set confirm: true"}, 400)
        return

    data, err = _syn_request(ip, "SYNO.DSM.System", 1, "reboot")
    if err:
        json_response(handler, {"ok": False, "error": err})
    else:
        json_response(handler, {"ok": True, "message": "Reboot command sent"})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register Synology API routes."""
    routes["/api/synology/status"] = handle_synology_status
    routes["/api/synology/storage"] = handle_synology_storage
    routes["/api/synology/shares"] = handle_synology_shares
    routes["/api/synology/docker"] = handle_synology_docker
    routes["/api/synology/packages"] = handle_synology_packages
    routes["/api/synology/service"] = handle_synology_service
    routes["/api/synology/reboot"] = handle_synology_reboot
