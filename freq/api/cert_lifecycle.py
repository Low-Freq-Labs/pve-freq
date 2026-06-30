"""Certificate lifecycle API handlers.

Provides the dashboard JSON contract for the cert manager without exposing
inline secrets. Operators pass credential paths; the backend reads files.
"""

import contextlib
import io
import ipaddress
import json
import os
import tempfile
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
    _cert_settings,
    _cert_targets,
    _cert_targets_from_catalog,
    _cert_inventory_from_reconcile,
    _discover_cloudflare_zone_id,
    _infer_cert_targets,
    _issued_from_reconcile,
    _load_issued,
    _render_cert_config_block,
    _reconcile_lifecycle_targets,
    _cloudflare_token_status,
    _ssl_onboarding_contract,
    _stage_cloudflare_token,
    _stage_cloudflare_token_value,
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


def _normalize_cidrs(values):
    cidrs = []
    for raw in values or []:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            network = ipaddress.ip_network(text, strict=False)
        except ValueError as exc:
            raise ValueError(f"invalid trusted proxy CIDR: {text}") from exc
        normalized = str(network)
        if normalized not in cidrs:
            cidrs.append(normalized)
    return cidrs


def _toml_array(values):
    return "[" + ", ".join(json.dumps(str(v)) for v in values) + "]"


def _write_dashboard_trusted_proxy_cidrs(cfg, cidrs):
    """Persist trusted proxy CIDRs through the product config writer."""
    toml_path = os.path.join(cfg.conf_dir, "freq.toml")
    text = ""
    if os.path.isfile(toml_path):
        with open(toml_path) as f:
            text = f.read()
    lines = text.splitlines()
    setting = f"trusted_proxy_cidrs = {_toml_array(cidrs)}"

    dash_start = None
    dash_end = len(lines)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[dashboard]":
            dash_start = idx
            dash_end = len(lines)
            for end_idx in range(idx + 1, len(lines)):
                candidate = lines[end_idx].strip()
                if candidate.startswith("[") and candidate.endswith("]"):
                    dash_end = end_idx
                    break
            break

    if dash_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[dashboard]", setting])
    else:
        replaced = False
        new_section = []
        for line in lines[dash_start + 1:dash_end]:
            if line.strip().startswith("trusted_proxy_cidrs"):
                if not replaced:
                    new_section.append(setting)
                    replaced = True
                continue
            new_section.append(line)
        if not replaced:
            new_section.append(setting)
        lines = lines[:dash_start + 1] + new_section + lines[dash_end:]

    os.makedirs(cfg.conf_dir, exist_ok=True)
    with open(toml_path, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")
    load_config(force=True)
    return toml_path


def _discover_cloudflare_zone_id_for_token(token, base_domain):
    """Discover Cloudflare zone from a pasted token without persisting it."""
    fd, path = tempfile.mkstemp(prefix="freq-cf-token-", suffix=".secret")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(str(token or "").strip() + "\n")
        os.chmod(path, 0o600)
        return _discover_cloudflare_zone_id(path, base_domain)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def handle_cert_lifecycle(handler):
    """GET /api/cert/lifecycle — read-only cert lifecycle state."""
    role, err = _check_session_role(handler, "viewer")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    try:
        plan = _build_lifecycle_plan(cfg)
        reconcile = _reconcile_lifecycle_targets(cfg)
        inventory = _cert_inventory_from_reconcile(cfg, _load_cert_data(cfg), reconcile=reconcile)
        issued = _issued_from_reconcile(cfg, _load_issued(cfg), reconcile=reconcile, inventory=inventory)
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


def handle_cert_trusted_proxy(handler):
    """POST /api/cert/lifecycle/trusted-proxy — configure proxy trust."""
    if require_post(handler, "Certificate trusted proxy"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    raw = body.get("trusted_proxy_cidrs", body.get("cidrs", []))
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, list):
        json_response(handler, {"error": "trusted_proxy_cidrs must be a list or comma-separated string"}, 400)
        return
    dry_run = _truthy(body.get("dry_run"), True)
    confirm = _truthy(body.get("confirm"), False)
    if not dry_run and not confirm:
        json_response(handler, {"error": "applying trusted proxy CIDRs requires confirm=true"}, 400)
        return

    cfg = load_config()
    try:
        cidrs = _normalize_cidrs(raw)
    except ValueError as exc:
        json_response(handler, {"error": str(exc)}, 400)
        return
    if not cidrs:
        json_response(handler, {"error": "at least one trusted proxy CIDR is required"}, 400)
        return

    result = {
        "ok": True,
        "dry_run": dry_run,
        "current": list(getattr(cfg, "trusted_proxy_cidrs", []) or []),
        "trusted_proxy_cidrs": cidrs,
        "restart_required": False,
    }
    if not dry_run:
        _write_dashboard_trusted_proxy_cidrs(cfg, cidrs)
        updated = load_config(force=True)
        result["current"] = list(getattr(updated, "trusted_proxy_cidrs", []) or [])
        result["applied"] = True
    json_response(handler, result)


def handle_cert_cloudflare_token(handler):
    """POST /api/cert/lifecycle/cloudflare-token — store Cloudflare token secret."""
    if require_post(handler, "Certificate Cloudflare token store"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    token = str(body.get("cloudflare_token") or body.get("token") or body.get("api_token") or "").strip()
    if not token:
        json_response(handler, {"error": "cloudflare_token is required"}, 400)
        return
    if len(token) < 8:
        json_response(handler, {"error": "Cloudflare token is too short"}, 400)
        return
    dry_run = _truthy(body.get("dry_run"), True)
    confirm = _truthy(body.get("confirm"), False)
    if not dry_run and not confirm:
        json_response(handler, {"error": "storing Cloudflare token requires confirm=true"}, 400)
        return

    cfg = load_config()
    current = _cert_settings(cfg)
    base_domain = str(body.get("base_domain") or current.get("base_domain") or "").strip().lower()
    token_dest = str(body.get("token_dest") or "").strip()
    replace = _truthy(body.get("replace"), False)
    reverse_proxy_host = str(body.get("reverse_proxy_host") or current.get("reverse_proxy_host") or "").strip()

    try:
        zone = {"zone_id": "", "zone_name": "", "errors": []}
        if base_domain:
            zone = _discover_cloudflare_zone_id_for_token(token, base_domain)
            if not zone.get("zone_id"):
                json_response(handler, {"ok": False, "error": "could not discover Cloudflare zone", "zone": zone}, 400)
                return
        token_path = token_dest or _cloudflare_token_status(cfg, current).get("path", "")
        if not token_path:
            token_path = "/etc/freq/credentials/cloudflare_dns_token"
        if not dry_run:
            token_path = _stage_cloudflare_token_value(cfg, token, token_dest)

        settings = dict(DEFAULT_CERT_SETTINGS)
        settings.update(current)
        settings.update(
            {
                "dns_provider": "cloudflare",
                "dns_token_path": token_path,
                "reverse_proxy_host": reverse_proxy_host,
            }
        )
        if base_domain:
            settings["base_domain"] = base_domain
        if zone.get("zone_id"):
            settings["cloudflare_zone_id"] = zone["zone_id"]

        targets = _cert_targets_from_catalog(
            body.get("service_catalog") or body.get("web_ui_catalog") or body.get("cert_targets") or [],
            settings.get("base_domain", ""),
            settings.get("reverse_proxy_host", ""),
        ) or _cert_targets(cfg)

        result = {
            "ok": True,
            "dry_run": dry_run,
            "stored": not dry_run,
            "provider": "cloudflare",
            "base_domain": settings.get("base_domain", ""),
            "zone": zone,
            "token_status": _cloudflare_token_status(cfg, settings),
            "config_path": os.path.join(cfg.conf_dir, "freq.toml"),
            "value_exposed": False,
        }
        if dry_run:
            result["planned_token_status"] = dict(result["token_status"], stored=False, ready=False)
        else:
            result["config_path"] = _write_cert_config_block(cfg, settings, targets, replace=replace)
            updated = load_config(force=True)
            result["token_status"] = _cloudflare_token_status(updated, _cert_settings(updated))
            result["config_updated"] = True
        json_response(handler, result)
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
    routes["/api/cert/lifecycle/trusted-proxy"] = handle_cert_trusted_proxy
    routes["/api/cert/lifecycle/cloudflare-token"] = handle_cert_cloudflare_token
    routes["/api/cert/lifecycle/bootstrap"] = handle_cert_bootstrap
    routes["/api/cert/lifecycle/action"] = handle_cert_action
