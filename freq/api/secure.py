"""Secure domain API handlers — /api/secure/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for security: vault, hardening, sweep, certs, DNS,
       patching, secrets, proxy, and compliance.
Why:   Decouples security logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.

Maps to security/compliance CLI domains. Each handler is a standalone
function that receives the HTTP handler as its first argument.
"""

import json
import os
import re
import time
import uuid

from freq.core import log as logger
from freq.api.helpers import require_post, json_response, get_params, get_json_body
from freq.core.config import load_config
from freq.core import resolve as res
from freq.core.ssh import run_many as ssh_run_many, result_for
from freq.modules.vault import vault_set, vault_get, vault_init, vault_list, vault_delete
from freq.api.auth import check_session_role as _check_session_role, current_user


_VAULT_GLOBAL_HOST = "freq:vault:credentials:global"
_VAULT_USER_HOST_PREFIX = "freq:vault:credentials:user:"
_VAULT_META_PREFIX = "meta:"
_VAULT_SECRET_PREFIX = "secret:"


def _role_at_least(role: str, minimum: str) -> bool:
    order = {"viewer": 0, "operator": 1, "admin": 2, "protected": 3}
    return order.get(role or "", -1) >= order.get(minimum, 1)


def _vault_now() -> int:
    return int(time.time())


def _vault_owner_slug(username: str) -> str:
    raw = str(username or "").strip().lower()
    slug = re.sub(r"[^a-z0-9_.@-]+", "-", raw).strip("-")
    return slug[:80] or "unknown"


def _credential_host(scope: str, owner: str = "") -> str:
    return _VAULT_GLOBAL_HOST if scope == "global" else _VAULT_USER_HOST_PREFIX + _vault_owner_slug(owner)


def _credential_meta_key(credential_id: str) -> str:
    return _VAULT_META_PREFIX + credential_id


def _credential_secret_key(credential_id: str) -> str:
    return _VAULT_SECRET_PREFIX + credential_id


def _normalize_scope(raw: str) -> str:
    scope = str(raw or "user").strip().lower()
    if scope == "local":
        scope = "user"
    return scope if scope in {"global", "user"} else ""


def _credential_id() -> str:
    return uuid.uuid4().hex


def _safe_tags(value) -> list[str]:
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",")]
    elif isinstance(value, list):
        items = [str(v).strip() for v in value]
    else:
        items = []
    return [v for v in items if v][:12]


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    return "********"


def _safe_credential(meta: dict, has_secret: bool = True) -> dict:
    safe = {
        "id": meta.get("id", ""),
        "scope": meta.get("scope", "user"),
        "owner": meta.get("owner", ""),
        "label": meta.get("label", ""),
        "username": meta.get("username", ""),
        "url": meta.get("url", ""),
        "notes": meta.get("notes", ""),
        "tags": meta.get("tags", []),
        "kind": meta.get("kind", "login"),
        "created_at": meta.get("created_at", 0),
        "updated_at": meta.get("updated_at", 0),
        "created_by": meta.get("created_by", ""),
        "updated_by": meta.get("updated_by", ""),
        "has_secret": bool(has_secret),
        "masked": _mask_secret("x" if has_secret else ""),
    }
    return safe


def _load_credential_metas(cfg) -> list[dict]:
    metas = []
    for host, key, value in vault_list(cfg):
        if not key.startswith(_VAULT_META_PREFIX):
            continue
        if host != _VAULT_GLOBAL_HOST and not host.startswith(_VAULT_USER_HOST_PREFIX):
            continue
        try:
            meta = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("id") and meta.get("scope") in {"global", "user"}:
            metas.append(meta)
    return metas


def _find_credential_meta(cfg, credential_id: str, scope: str, user: str) -> tuple[dict, str]:
    hosts = [_credential_host(scope, user)] if scope == "user" else [_VAULT_GLOBAL_HOST]
    key = _credential_meta_key(credential_id)
    for host in hosts:
        raw = vault_get(cfg, host, key)
        if not raw:
            continue
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError):
            return {}, host
        return meta if isinstance(meta, dict) else {}, host
    return {}, hosts[0]


def _can_read_credential(meta: dict, user: str, role: str) -> bool:
    if not _role_at_least(role, "operator"):
        return False
    if meta.get("scope") == "global":
        return True
    return meta.get("scope") == "user" and meta.get("owner") == user


def _can_write_credential(scope: str, owner: str, user: str, role: str) -> bool:
    if scope == "global":
        return _role_at_least(role, "admin")
    return _role_at_least(role, "operator") and owner == user


def _vault_request_user(handler) -> str:
    return getattr(handler, "_session_user", "") or current_user(handler)


def handle_vault_credentials(handler):
    """GET /api/vault/credentials — scoped product credential list."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    user = _vault_request_user(handler)
    cfg = load_config()
    initialized = os.path.exists(cfg.vault_file)
    if not initialized:
        json_response(
            handler,
            {
                "initialized": False,
                "credentials": [],
                "counts": {"global": 0, "user": 0},
                "scope_model": {"global": "operators_and_admins", "user": "current_user_only"},
            },
        )
        return
    safe = []
    for meta in _load_credential_metas(cfg):
        if _can_read_credential(meta, user, role):
            host = _credential_host(meta.get("scope", "user"), meta.get("owner", ""))
            has_secret = bool(vault_get(cfg, host, _credential_secret_key(meta.get("id", ""))))
            safe.append(_safe_credential(meta, has_secret=has_secret))
    safe.sort(key=lambda m: (m.get("scope") != "global", m.get("label", "").lower()))
    counts = {
        "global": len([m for m in safe if m.get("scope") == "global"]),
        "user": len([m for m in safe if m.get("scope") == "user"]),
    }
    json_response(
        handler,
        {
            "initialized": True,
            "credentials": safe,
            "counts": counts,
            "scope_model": {"global": "operators_and_admins", "user": "current_user_only"},
        },
    )


def handle_vault_credential_set(handler):
    """POST /api/vault/credentials/set — create or update a scoped credential."""
    if require_post(handler, "Vault credential set"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    user = _vault_request_user(handler)
    body = get_json_body(handler)
    scope = _normalize_scope(body.get("scope"))
    if not scope:
        json_response(handler, {"error": "scope must be global or user"}, 400)
        return
    owner = "" if scope == "global" else user
    if not _can_write_credential(scope, owner, user, role):
        json_response(handler, {"error": "Global credentials require admin role"}, 403)
        return
    label = str(body.get("label") or body.get("name") or "").strip()
    username = str(body.get("username") or "").strip()
    secret = str(body.get("secret") if body.get("secret") is not None else body.get("password") or "")
    credential_id = str(body.get("id") or "").strip()
    if not label:
        json_response(handler, {"error": "label required"}, 400)
        return
    cfg = load_config()
    if not os.path.exists(cfg.vault_file):
        vault_init(cfg)
    existing = {}
    if credential_id:
        existing, _ = _find_credential_meta(cfg, credential_id, scope, user)
        if existing and not _can_write_credential(existing.get("scope", scope), existing.get("owner", owner), user, role):
            json_response(handler, {"error": "Credential scope is not writable by this user"}, 403)
            return
    else:
        credential_id = _credential_id()
    if existing and not secret:
        secret = vault_get(cfg, _credential_host(existing.get("scope", scope), existing.get("owner", owner)), _credential_secret_key(credential_id))
    if not secret:
        json_response(handler, {"error": "secret required"}, 400)
        return
    now = _vault_now()
    meta = {
        "id": credential_id,
        "scope": scope,
        "owner": owner,
        "label": label,
        "username": username,
        "url": str(body.get("url") or "").strip(),
        "notes": str(body.get("notes") or "").strip(),
        "tags": _safe_tags(body.get("tags")),
        "kind": str(body.get("kind") or "login").strip()[:40] or "login",
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "created_by": existing.get("created_by", user),
        "updated_by": user,
    }
    host = _credential_host(scope, owner)
    ok_meta = vault_set(cfg, host, _credential_meta_key(credential_id), json.dumps(meta, sort_keys=True, separators=(",", ":")))
    ok_secret = vault_set(cfg, host, _credential_secret_key(credential_id), secret)
    if not ok_meta or not ok_secret:
        json_response(handler, {"error": "Vault write failed", "ok": False}, 500)
        return
    json_response(handler, {"ok": True, "credential": _safe_credential(meta, has_secret=True)})


def handle_vault_credential_reveal(handler):
    """POST /api/vault/credentials/reveal — reveal one authorized secret."""
    if require_post(handler, "Vault credential reveal"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    user = _vault_request_user(handler)
    body = get_json_body(handler)
    scope = _normalize_scope(body.get("scope"))
    credential_id = str(body.get("id") or "").strip()
    if not scope or not credential_id:
        json_response(handler, {"error": "id and scope required"}, 400)
        return
    cfg = load_config()
    meta, host = _find_credential_meta(cfg, credential_id, scope, user)
    if not meta:
        json_response(handler, {"error": "Credential not found"}, 404)
        return
    if not _can_read_credential(meta, user, role):
        json_response(handler, {"error": "Credential not found"}, 404)
        return
    secret = vault_get(cfg, host, _credential_secret_key(credential_id))
    json_response(handler, {"ok": True, "credential": _safe_credential(meta, has_secret=bool(secret)), "secret": secret})


def handle_vault_credential_delete(handler):
    """POST /api/vault/credentials/delete — delete one scoped credential."""
    if require_post(handler, "Vault credential delete"):
        return
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    user = _vault_request_user(handler)
    body = get_json_body(handler)
    scope = _normalize_scope(body.get("scope"))
    credential_id = str(body.get("id") or "").strip()
    if not scope or not credential_id:
        json_response(handler, {"error": "id and scope required"}, 400)
        return
    cfg = load_config()
    meta, host = _find_credential_meta(cfg, credential_id, scope, user)
    if not meta:
        json_response(handler, {"error": "Credential not found"}, 404)
        return
    if not _can_write_credential(meta.get("scope", scope), meta.get("owner", user), user, role):
        json_response(handler, {"error": "Credential not found"}, 404)
        return
    ok_meta = vault_delete(cfg, host, _credential_meta_key(credential_id))
    ok_secret = vault_delete(cfg, host, _credential_secret_key(credential_id))
    json_response(handler, {"ok": bool(ok_meta or ok_secret), "id": credential_id, "scope": meta.get("scope", scope)})


def handle_harden(handler):
    """GET /api/harden — run SSH hardening checks across fleet."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = get_params(handler)
    target = params.get("target", ["all"])[0]
    if target == "all":
        hosts = cfg.hosts
    else:
        h = res.by_target(cfg.hosts, target)
        hosts = [h] if h else []
    checks = [
        (
            "PasswordAuth",
            "grep -c '^PasswordAuthentication no' /etc/ssh/sshd_config 2>/dev/null || echo 0",
            "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config",
        ),
        (
            "RootLogin",
            "grep -c '^PermitRootLogin prohibit-password' /etc/ssh/sshd_config 2>/dev/null || echo 0",
            "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config",
        ),
        (
            "EmptyPasswd",
            "grep -c '^PermitEmptyPasswords no' /etc/ssh/sshd_config 2>/dev/null || echo 0",
            "sed -i 's/^#*PermitEmptyPasswords.*/PermitEmptyPasswords no/' /etc/ssh/sshd_config",
        ),
    ]
    results = []
    for name, check_cmd, _ in checks:
        r = ssh_run_many(
            hosts=hosts,
            command=check_cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=10,
            max_parallel=10,
            use_sudo=True,
            cfg=cfg,
        )
        for h in hosts:
            host_res = result_for(r, h)
            ok = host_res and host_res.returncode == 0 and host_res.stdout.strip() != "0"
            results.append({"host": h.label, "check": name, "ok": ok})
    json_response(handler, {"results": results, "hosts": len(hosts)})


def handle_sweep(handler):
    """GET /api/sweep — run full audit + policy sweep pipeline."""
    cfg = load_config()
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = get_params(handler)
    do_fix = params.get("fix", ["false"])[0].lower() == "true"
    try:
        import io
        import contextlib
        from freq.jarvis.sweep import cmd_sweep

        class Args:
            pass

        args = Args()
        args.fix = do_fix
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_sweep(cfg, None, args)
        json_response(handler, {"ok": result == 0, "output": buf.getvalue(), "fix_mode": do_fix})
    except Exception as e:
        logger.error(f"api_secure_error: sweep failed: {e}", endpoint="sweep")
        json_response(handler, {"error": f"Sweep failed: {e}"}, 500)


def handle_cert_inventory(handler):
    """GET /api/cert/inventory — get cert inventory."""
    from freq.modules.cert import _load_cert_data
    from freq.modules.cert_management import _cert_inventory_from_reconcile

    cfg = load_config()
    data = _cert_inventory_from_reconcile(cfg, _load_cert_data(cfg))
    json_response(handler, data)


def handle_dns_inventory(handler):
    """GET /api/dns/inventory — get DNS inventory."""
    from freq.modules.dns import _load_dns_data

    cfg = load_config()
    data = _load_dns_data(cfg)
    json_response(handler, data)


def handle_patch_status(handler):
    """GET /api/patch/status — get patch status (history only)."""
    from freq.modules.patch import _load_history, _load_holds

    cfg = load_config()
    json_response(handler, {"history": _load_history(cfg)[-20:], "holds": _load_holds(cfg)})


def handle_patch_compliance(handler):
    """GET /api/patch/compliance — live fleet patch compliance check."""
    cfg = load_config()
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"hosts": [], "compliance_pct": 0, "compliant": 0, "total": 0})
        return

    command = (
        "if command -v apt-get >/dev/null 2>&1; then "
        "  apt list --upgradable 2>/dev/null | grep -cv '^Listing'; "
        "elif command -v yum >/dev/null 2>&1; then "
        "  yum check-update -q 2>/dev/null | grep -cv '^$'; "
        "else echo 0; fi"
    )
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=30,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
        cfg=cfg,
    )

    host_results = []
    compliant = 0
    total_reachable = 0
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode not in (0, 100):
            host_results.append({"host": h.label, "status": "unreachable", "updates": 0})
            continue
        total_reachable += 1
        try:
            count = int(r.stdout.strip().split("\n")[-1])
        except (ValueError, IndexError):
            count = 0
        if count == 0:
            compliant += 1
        host_results.append(
            {
                "host": h.label,
                "status": "compliant" if count == 0 else "updates_available",
                "updates": count,
            }
        )

    pct = round(compliant / max(total_reachable, 1) * 100, 1)
    json_response(
        handler,
        {
            "hosts": host_results,
            "compliance_pct": pct,
            "compliant": compliant,
            "total": total_reachable,
        },
    )


def handle_secrets_audit(handler):
    """GET /api/secrets/audit — secret audit summary."""
    from freq.modules.secrets import _load_leases, _load_scan_results

    cfg = load_config()
    leases = _load_leases(cfg)
    scan = _load_scan_results(cfg)
    now = time.time()
    expired = sum(1 for l in leases if 0 < l.get("expires_epoch", 0) < now)
    json_response(
        handler,
        {
            "leases": len(leases),
            "expired": expired,
            "scan_findings": len(scan.get("findings", [])),
            "last_scan": scan.get("scan_time", "never"),
        },
    )


def handle_secrets_leases(handler):
    """GET /api/secrets/leases — list secret leases."""
    from freq.modules.secrets import _load_leases

    cfg = load_config()
    json_response(handler, {"leases": _load_leases(cfg)})


def handle_secrets_scan_results(handler):
    """GET /api/secrets/scan — get last scan results."""
    from freq.modules.secrets import _load_scan_results

    cfg = load_config()
    json_response(handler, _load_scan_results(cfg))


def handle_proxy_list(handler):
    """GET /api/proxy/list — list proxy routes."""
    from freq.modules.proxy import _load_routes

    cfg = load_config()
    routes = _load_routes(cfg)
    json_response(handler, {"routes": routes, "count": len(routes)})


def handle_proxy_status_api(handler):
    """GET /api/proxy/status — live reverse proxy detection across fleet."""
    cfg = load_config()
    hosts = cfg.hosts
    if not hosts:
        json_response(handler, {"hosts": [], "total": 0})
        return

    command = (
        'NGINX="no"; CADDY="no"; TRAEFIK="no"; HAPROXY="no"; '
        'if systemctl is-active nginx >/dev/null 2>&1 || docker ps --format "{{.Names}}" 2>/dev/null | grep -qi nginx; then NGINX="yes"; fi; '
        'if systemctl is-active caddy >/dev/null 2>&1 || docker ps --format "{{.Names}}" 2>/dev/null | grep -qi caddy; then CADDY="yes"; fi; '
        'if docker ps --format "{{.Names}}" 2>/dev/null | grep -qi traefik; then TRAEFIK="yes"; fi; '
        'if systemctl is-active haproxy >/dev/null 2>&1; then HAPROXY="yes"; fi; '
        'echo "${NGINX}|${CADDY}|${TRAEFIK}|${HAPROXY}"'
    )
    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=15,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
        cfg=cfg,
    )

    proxy_hosts = []
    for h in hosts:
        r = result_for(results, h)
        if not r or r.returncode != 0:
            continue
        parts = r.stdout.strip().split("|")
        if len(parts) < 4:
            continue
        nginx, caddy, traefik, haproxy = parts[0], parts[1], parts[2], parts[3]
        if all(p == "no" for p in (nginx, caddy, traefik, haproxy)):
            continue
        proxy_hosts.append(
            {
                "host": h.label,
                "nginx": nginx == "yes",
                "caddy": caddy == "yes",
                "traefik": traefik == "yes",
                "haproxy": haproxy == "yes",
            }
        )

    json_response(handler, {"hosts": proxy_hosts, "total": len(proxy_hosts)})


def handle_comply_status(handler):
    """GET /api/comply/status — compliance status."""
    from freq.modules.comply import _load_results, CIS_CHECKS

    cfg = load_config()
    results = _load_results(cfg)
    json_response(
        handler,
        {
            "last_scan": results.get("last_scan", "never"),
            "total_checks": len(CIS_CHECKS),
            "scan_count": len(results.get("scans", [])),
        },
    )


def handle_comply_results(handler):
    """GET /api/comply/results — get compliance scan results."""
    from freq.modules.comply import _load_results

    cfg = load_config()
    results = _load_results(cfg)
    scans = results.get("scans", [])
    json_response(handler, {"latest": scans[-1] if scans else None, "total_scans": len(scans)})


# ── Route Registration ──────────────────────────────────────────────────


def register(routes: dict):
    """Register secure API routes into the master route table.

    These routes use the same /api/ paths as the legacy serve.py handlers.
    The dispatch in serve.py checks _ROUTES first, then _V1_ROUTES. By
    removing these paths from _ROUTES, dispatch falls through to here.
    """
    routes["/api/vault/credentials"] = handle_vault_credentials
    routes["/api/vault/credentials/set"] = handle_vault_credential_set
    routes["/api/vault/credentials/reveal"] = handle_vault_credential_reveal
    routes["/api/vault/credentials/delete"] = handle_vault_credential_delete
    routes["/api/harden"] = handle_harden
    routes["/api/sweep"] = handle_sweep
    routes["/api/cert/inventory"] = handle_cert_inventory
    routes["/api/dns/inventory"] = handle_dns_inventory
    routes["/api/patch/status"] = handle_patch_status
    routes["/api/patch/compliance"] = handle_patch_compliance
    routes["/api/secrets/audit"] = handle_secrets_audit
    routes["/api/secrets/leases"] = handle_secrets_leases
    routes["/api/secrets/scan"] = handle_secrets_scan_results
    routes["/api/proxy/list"] = handle_proxy_list
    routes["/api/proxy/status"] = handle_proxy_status_api
    routes["/api/comply/status"] = handle_comply_status
    routes["/api/comply/results"] = handle_comply_results
