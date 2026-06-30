"""SNMP setup API handlers.

Provides browser-safe product endpoints for planning and applying SNMP
enablement without asking operators to edit TOML or run ad hoc scripts.
"""

from freq.api.auth import check_session_role
from freq.api.helpers import get_json_body, get_param, json_response, require_post
from freq.core.config import load_config
from freq.modules.snmp import (
    build_snmp_setup_plan,
    read_last_snmp_setup_status,
    run_snmp_setup,
    store_snmp_credentials,
)


def _split_targets(raw):
    if isinstance(raw, list):
        return [str(v).strip() for v in raw if str(v).strip()]
    if isinstance(raw, str):
        return [v.strip() for v in raw.split(",") if v.strip()]
    return []


def _require_admin(handler):
    role, err = check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return False
    handler._request_role = role or getattr(handler, "_request_role", "")
    return True


def handle_snmp_setup_plan(handler):
    """GET /api/v1/net/snmp/setup/plan -- non-mutating SNMP setup plan."""
    cfg = load_config()
    targets = _split_targets(get_param(handler, "targets", ""))
    include_probe = get_param(handler, "probe", "").lower() in {"1", "true", "yes"}
    json_response(handler, build_snmp_setup_plan(cfg, targets=targets, include_probe=include_probe))


def handle_snmp_setup_status(handler):
    """GET /api/v1/net/snmp/setup/status -- last SNMP setup result."""
    cfg = load_config()
    json_response(handler, read_last_snmp_setup_status(cfg))


def handle_snmp_setup_apply(handler):
    """POST /api/v1/net/snmp/setup/apply -- dry-run or confirmed SNMP setup."""
    if require_post(handler, "SNMP setup"):
        return
    if not _require_admin(handler):
        return
    body = get_json_body(handler)
    dry_run = bool(body.get("dry_run", True))
    confirm = bool(body.get("confirm", False))
    if not dry_run and not confirm:
        json_response(handler, {"error": "SNMP setup apply requires confirm=true when dry_run=false"}, 400)
        return
    targets = _split_targets(body.get("targets", []))
    include_probe = bool(body.get("probe", False))
    cfg = load_config()
    result = run_snmp_setup(cfg, targets=targets, dry_run=dry_run, include_probe=include_probe)
    json_response(handler, result)


def handle_snmp_setup_credentials(handler):
    """POST /api/v1/net/snmp/setup/credentials -- store SNMPv3 credential files."""
    if require_post(handler, "SNMP setup credentials"):
        return
    if not _require_admin(handler):
        return
    body = get_json_body(handler)
    dry_run = bool(body.get("dry_run", True))
    confirm = bool(body.get("confirm", False))
    if not dry_run and not confirm:
        json_response(handler, {"error": "storing SNMP credentials requires confirm=true when dry_run=false"}, 400)
        return
    try:
        cfg = load_config()
        result = store_snmp_credentials(
            cfg,
            body.get("user") or body.get("username") or body.get("snmp_user"),
            body.get("auth_password") or body.get("auth_passphrase"),
            body.get("priv_password") or body.get("privacy_password") or body.get("priv_passphrase"),
            auth_protocol=body.get("auth_protocol") or "SHA",
            priv_protocol=body.get("priv_protocol") or body.get("privacy_protocol") or "AES",
            dry_run=dry_run,
        )
        json_response(handler, result)
    except ValueError as exc:
        json_response(handler, {"error": str(exc)}, 400)
    except Exception as exc:
        json_response(handler, {"ok": False, "error": str(exc)}, 500)


def register(routes: dict):
    """Register SNMP setup routes."""
    routes["/api/v1/net/snmp/setup/plan"] = handle_snmp_setup_plan
    routes["/api/v1/net/snmp/setup/status"] = handle_snmp_setup_status
    routes["/api/v1/net/snmp/setup/apply"] = handle_snmp_setup_apply
    routes["/api/v1/net/snmp/setup/credentials"] = handle_snmp_setup_credentials

    # Short aliases for dashboard code that is not version-aware yet.
    routes["/api/snmp/setup/plan"] = handle_snmp_setup_plan
    routes["/api/snmp/setup/status"] = handle_snmp_setup_status
    routes["/api/snmp/setup/apply"] = handle_snmp_setup_apply
    routes["/api/snmp/setup/credentials"] = handle_snmp_setup_credentials
