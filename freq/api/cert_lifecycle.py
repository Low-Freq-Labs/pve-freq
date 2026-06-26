"""Certificate lifecycle API handlers.

Provides the dashboard JSON contract for the cert manager without exposing
inline secrets. Operators pass credential paths; the backend reads files.
"""

import contextlib
import io
import json
import os
from types import SimpleNamespace

from freq.api.auth import check_session_role as _check_session_role
from freq.api.helpers import get_json_body, json_response, require_post
from freq.core import log as logger
from freq.core.config import load_config
from freq.modules.cert import _load_cert_data
from freq.modules.cert_management import (
    DEFAULT_CERT_SETTINGS,
    _acme_available,
    _build_lifecycle_plan,
    _cert_targets_from_catalog,
    _discover_cloudflare_zone_id,
    _infer_cert_targets,
    _load_issued,
    _render_cert_config_block,
    _reconcile_lifecycle_targets,
    _ssl_onboarding_contract,
    _stage_cloudflare_token,
    _write_cert_config_block,
    cmd_cert_deploy,
    cmd_cert_dns_sync,
    cmd_cert_issue,
    cmd_cert_renew,
    cmd_cert_verify,
)


def _truthy(value, default=False):
    if value is None:
        return default
    return str(value).lower() not in ("0", "false", "no", "off", "")


def _parse_stdout(payload):
    text = (payload or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _run_cert_command(func, cfg, args):
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = func(cfg, None, args)
    except Exception as exc:
        logger.error("cert_lifecycle_action_failed", action=getattr(args, "action", ""), error=str(exc))
        return {"ok": False, "returncode": 1, "error": str(exc), "output": buf.getvalue()}
    output = buf.getvalue()
    parsed = _parse_stdout(output)
    return {
        "ok": code == 0,
        "returncode": code,
        "data": parsed,
        "output": output,
    }


def _targets_from_request(cfg, base_domain, body, settings):
    catalog = body.get("service_catalog") or body.get("web_ui_catalog") or body.get("catalog")
    if catalog:
        return _cert_targets_from_catalog(catalog, base_domain, settings.get("reverse_proxy_host", "")), "service_catalog"
    targets = body.get("cert_targets") or body.get("targets")
    if targets:
        return _cert_targets_from_catalog(targets, base_domain, settings.get("reverse_proxy_host", "")), "service_catalog"
    infer_targets = _truthy(body.get("infer_targets"), True)
    return (_infer_cert_targets(cfg, base_domain) if infer_targets else []), "inferred" if infer_targets else "none"


def handle_cert_lifecycle(handler):
    """GET /api/cert/lifecycle — read-only cert lifecycle state."""
    role, err = _check_session_role(handler, "viewer")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    try:
        plan = _build_lifecycle_plan(cfg)
        issued = _load_issued(cfg)
        inventory = _load_cert_data(cfg)
        settings = plan.get("settings", {})
        onboarding = _ssl_onboarding_contract(cfg)
        adopted_existing = settings.get("management_mode") == "adopted_existing"
        json_response(
            handler,
            {
                "ok": True,
                "plan": plan,
                "issued": issued,
                "inventory": inventory,
                "onboarding": onboarding,
                "status": {
                    "configured": bool(
                        settings.get("base_domain")
                        and (
                            adopted_existing
                            or (settings.get("dns_provider") and settings.get("dns_token_path"))
                        )
                    ),
                    "management_mode": settings.get("management_mode") or "managed",
                    "acme_available": _acme_available(settings),
                    "targets": len(plan.get("targets", [])),
                    "dns_records": len(plan.get("dns_records", [])),
                    "warnings": len(plan.get("warnings", [])),
                },
            },
        )
    except Exception as exc:
        json_response(handler, {"ok": False, "error": str(exc)}, 500)


def handle_cert_onboarding(handler):
    """GET /api/cert/lifecycle/onboarding — product SSL setup contract."""
    role, err = _check_session_role(handler, "viewer")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    try:
        json_response(handler, {"ok": True, "onboarding": _ssl_onboarding_contract(cfg)})
    except Exception as exc:
        json_response(handler, {"ok": False, "error": str(exc)}, 500)


def handle_cert_adopt_existing(handler):
    """POST /api/cert/lifecycle/adopt-existing — record already-working SSL."""
    if require_post(handler, "Certificate adopt existing"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    base_domain = str(body.get("base_domain", "") or "").strip().lower()
    fullchain = os.path.expanduser(str(body.get("cert_fullchain_path", "") or "").strip())
    key_path = os.path.expanduser(str(body.get("cert_key_path", "") or "").strip())
    reverse_proxy_host = str(body.get("reverse_proxy_host", "") or "").strip()
    renewal_owner = str(body.get("renewal_owner", "") or "").strip() or "external"
    replace = _truthy(body.get("replace"), False)
    dry_run = _truthy(body.get("dry_run"), True)
    infer_targets = _truthy(body.get("infer_targets"), True)

    if body.get("cloudflare_token") or body.get("token"):
        json_response(handler, {"error": "Cloudflare tokens are not needed to adopt existing SSL"}, 400)
        return
    if not base_domain:
        json_response(handler, {"error": "base_domain is required"}, 400)
        return
    if bool(fullchain) != bool(key_path):
        json_response(handler, {"error": "cert_fullchain_path and cert_key_path must be provided together"}, 400)
        return
    if fullchain and not os.path.isfile(fullchain):
        json_response(handler, {"error": f"certificate fullchain not found: {fullchain}"}, 400)
        return
    if key_path and not os.path.isfile(key_path):
        json_response(handler, {"error": f"certificate key not found: {key_path}"}, 400)
        return

    cfg = load_config()
    try:
        settings = dict(DEFAULT_CERT_SETTINGS)
        settings.update(
            {
                "base_domain": base_domain,
                "wildcard": True,
                "management_mode": "adopted_existing",
                "issuer": "existing",
                "record_strategy": "existing-dns",
                "reverse_proxy_host": reverse_proxy_host,
                "renewal_owner": renewal_owner,
            }
        )
        if fullchain and key_path:
            settings["cert_fullchain_path"] = fullchain
            settings["cert_key_path"] = key_path
        targets, target_source = _targets_from_request(cfg, base_domain, body, settings)
        if not infer_targets and target_source == "inferred":
            targets = []
            target_source = "none"
        result = {
            "ok": True,
            "dry_run": dry_run,
            "settings": settings,
            "targets": targets,
            "target_source": target_source,
            "config_path": os.path.join(cfg.conf_dir, "freq.toml"),
        }
        if dry_run:
            result["config_block"] = _render_cert_config_block(settings, targets)
        else:
            result["config_path"] = _write_cert_config_block(cfg, settings, targets, replace=replace)
        json_response(handler, result)
    except Exception as exc:
        json_response(handler, {"ok": False, "error": str(exc)}, 500)


def handle_cert_reconcile(handler):
    """GET /api/cert/lifecycle/reconcile — authoritative served-cert probe."""
    role, err = _check_session_role(handler, "viewer")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    try:
        json_response(handler, _reconcile_lifecycle_targets(cfg))
    except Exception as exc:
        json_response(handler, {"ok": False, "error": str(exc)}, 500)


def handle_cert_bootstrap(handler):
    """POST /api/cert/lifecycle/bootstrap — bootstrap config from token path."""
    if require_post(handler, "Certificate bootstrap"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    if body.get("cloudflare_token") or body.get("token"):
        json_response(handler, {"error": "inline Cloudflare tokens are not accepted; provide cloudflare_token_path"}, 400)
        return
    base_domain = str(body.get("base_domain", "") or "").strip().lower()
    source_path = os.path.expanduser(str(body.get("cloudflare_token_path", "") or "").strip())
    dry_run = _truthy(body.get("dry_run"), True)
    replace = _truthy(body.get("replace"), False)
    token_dest = str(body.get("token_dest", "") or "").strip()
    reverse_proxy_host = str(body.get("reverse_proxy_host", "") or "").strip()
    if not base_domain:
        json_response(handler, {"error": "base_domain is required"}, 400)
        return
    if not source_path:
        json_response(handler, {"error": "cloudflare_token_path is required"}, 400)
        return
    if not os.path.isfile(source_path):
        json_response(handler, {"error": f"Cloudflare token file not found: {source_path}"}, 400)
        return

    cfg = load_config()
    try:
        zone = _discover_cloudflare_zone_id(source_path, base_domain)
        if not zone.get("zone_id"):
            json_response(handler, {"ok": False, "error": "could not discover Cloudflare zone", "zone": zone}, 400)
            return
        token_path = source_path if dry_run else _stage_cloudflare_token(cfg, source_path, token_dest)
        settings = dict(DEFAULT_CERT_SETTINGS)
        settings.update(
            {
                "base_domain": base_domain,
                "wildcard": True,
                "issuer": "acme.sh",
                "dns_provider": "cloudflare",
                "dns_token_path": token_path,
                "cloudflare_zone_id": zone["zone_id"],
                "record_strategy": "public-private-a",
                "reverse_proxy_host": reverse_proxy_host,
            }
        )
        targets, target_source = _targets_from_request(cfg, base_domain, body, settings)
        result = {
            "ok": True,
            "dry_run": dry_run,
            "zone": zone,
            "settings": settings,
            "targets": targets,
            "target_source": target_source,
            "config_path": os.path.join(cfg.conf_dir, "freq.toml"),
        }
        if dry_run:
            result["config_block"] = _render_cert_config_block(settings, targets)
        else:
            result["config_path"] = _write_cert_config_block(cfg, settings, targets, replace=replace)
        json_response(handler, result)
    except Exception as exc:
        json_response(handler, {"ok": False, "error": str(exc)}, 500)


def handle_cert_action(handler):
    """POST /api/cert/lifecycle/action — dry-run or execute cert actions."""
    if require_post(handler, "Certificate lifecycle action"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    body = get_json_body(handler)
    action = str(body.get("action", "") or "").strip()
    target = str(body.get("target", "") or "").strip()
    dry_run = _truthy(body.get("dry_run"), action != "verify")
    confirm = _truthy(body.get("confirm"), False)
    destructive = action in ("issue", "renew", "deploy", "dns-sync")
    if action not in ("issue", "renew", "deploy", "dns-sync", "verify"):
        json_response(handler, {"error": "action must be issue, renew, deploy, dns-sync, or verify"}, 400)
        return
    if destructive and not dry_run and not confirm:
        json_response(handler, {"error": "non-dry-run certificate actions require confirm=true"}, 400)
        return

    cfg = load_config()
    if action == "issue":
        args = SimpleNamespace(action=action, json=dry_run, dry_run=dry_run, yes=confirm)
        result = _run_cert_command(cmd_cert_issue, cfg, args)
    elif action == "renew":
        args = SimpleNamespace(action=action, json=dry_run, dry_run=dry_run, yes=confirm, deploy=False)
        result = _run_cert_command(cmd_cert_renew, cfg, args)
    elif action == "deploy":
        args = SimpleNamespace(action=action, json=True, dry_run=dry_run, yes=confirm, target=target)
        result = _run_cert_command(cmd_cert_deploy, cfg, args)
    elif action == "dns-sync":
        args = SimpleNamespace(action=action, json=True, dry_run=dry_run, yes=confirm)
        result = _run_cert_command(cmd_cert_dns_sync, cfg, args)
    else:
        args = SimpleNamespace(action=action, json=True, target=target)
        result = _run_cert_command(cmd_cert_verify, cfg, args)
    result.update({"action": action, "dry_run": dry_run, "target": target})
    json_response(handler, result, 200 if result.get("ok") else 400)


def register(routes: dict):
    routes["/api/cert/lifecycle"] = handle_cert_lifecycle
    routes["/api/cert/lifecycle/onboarding"] = handle_cert_onboarding
    routes["/api/cert/lifecycle/adopt-existing"] = handle_cert_adopt_existing
    routes["/api/cert/lifecycle/reconcile"] = handle_cert_reconcile
    routes["/api/cert/lifecycle/bootstrap"] = handle_cert_bootstrap
    routes["/api/cert/lifecycle/action"] = handle_cert_action
