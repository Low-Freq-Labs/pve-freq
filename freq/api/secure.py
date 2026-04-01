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

import os
import time

from freq.api.helpers import json_response, get_params, get_cfg
from freq.core.config import load_config
from freq.core import resolve as res
from freq.core.ssh import run_many as ssh_run_many
from freq.modules.vault import vault_get, vault_set, vault_init, vault_list, vault_delete
from freq.modules.serve import _check_session_role


# ── Handlers ────────────────────────────────────────────────────────────


def handle_vault(handler):
    """GET /api/vault — list vault entries (values masked)."""
    cfg = load_config()
    if not os.path.exists(cfg.vault_file):
        json_response(handler, {"entries": [], "initialized": False}); return
    entries = vault_list(cfg)
    safe = [{"host": h, "key": k, "masked": "********" if any(w in k.lower() for w in ["pass", "secret", "token", "key"]) else v[:20]}
            for h, k, v in entries]
    json_response(handler, {"entries": safe, "initialized": True, "count": len(entries)})


def handle_vault_set(handler):
    """GET /api/vault/set — set a vault entry."""
    cfg = load_config()
    params = get_params(handler)
    key = params.get("key", [""])[0]
    value = params.get("value", [""])[0]
    host = params.get("host", ["DEFAULT"])[0]
    if not key or not value:
        json_response(handler, {"error": "Key and value required"}); return
    if not os.path.exists(cfg.vault_file):
        vault_init(cfg)
    ok = vault_set(cfg, host, key, value)
    json_response(handler, {"ok": ok, "key": key, "host": host})


def handle_vault_delete(handler):
    """GET /api/vault/delete — delete a vault entry."""
    cfg = load_config()
    params = get_params(handler)
    key = params.get("key", [""])[0]
    host = params.get("host", ["DEFAULT"])[0]
    ok = vault_delete(cfg, host, key)
    json_response(handler, {"ok": ok, "key": key, "host": host})


def handle_harden(handler):
    """GET /api/harden — run SSH hardening checks across fleet."""
    cfg = load_config()
    params = get_params(handler)
    target = params.get("target", ["all"])[0]
    if target == "all":
        hosts = cfg.hosts
    else:
        h = res.by_target(cfg.hosts, target)
        hosts = [h] if h else []
    checks = [
        ("PasswordAuth", "grep -c '^PasswordAuthentication no' /etc/ssh/sshd_config 2>/dev/null || echo 0",
         "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config"),
        ("RootLogin", "grep -c '^PermitRootLogin prohibit-password' /etc/ssh/sshd_config 2>/dev/null || echo 0",
         "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config"),
        ("EmptyPasswd", "grep -c '^PermitEmptyPasswords no' /etc/ssh/sshd_config 2>/dev/null || echo 0",
         "sed -i 's/^#*PermitEmptyPasswords.*/PermitEmptyPasswords no/' /etc/ssh/sshd_config"),
    ]
    results = []
    for name, check_cmd, _ in checks:
        r = ssh_run_many(hosts=hosts, command=check_cmd, key_path=cfg.ssh_key_path,
                         connect_timeout=3, command_timeout=10, max_parallel=10, use_sudo=True)
        for h in hosts:
            host_res = r.get(h.label)
            ok = host_res and host_res.returncode == 0 and host_res.stdout.strip() != "0"
            results.append({"host": h.label, "check": name, "ok": ok})
    json_response(handler, {"results": results, "hosts": len(hosts)})


def handle_sweep(handler):
    """GET /api/sweep — run full audit + policy sweep pipeline."""
    cfg = load_config()
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}); return
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
        json_response(handler, {"error": f"Sweep failed: {e}"}, 500)


def handle_cert_inventory(handler):
    """GET /api/cert/inventory — get cert inventory."""
    from freq.modules.cert import _load_cert_data
    cfg = load_config()
    data = _load_cert_data(cfg)
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
    """GET /api/patch/compliance — patch compliance info."""
    json_response(handler, {"info": "Run freq patch compliance for live data", "usage": "freq patch compliance"})


def handle_secrets_audit(handler):
    """GET /api/secrets/audit — secret audit summary."""
    from freq.modules.secrets import _load_leases, _load_scan_results
    cfg = load_config()
    leases = _load_leases(cfg)
    scan = _load_scan_results(cfg)
    now = time.time()
    expired = sum(1 for l in leases if 0 < l.get("expires_epoch", 0) < now)
    json_response(handler, {
        "leases": len(leases), "expired": expired,
        "scan_findings": len(scan.get("findings", [])),
        "last_scan": scan.get("scan_time", "never"),
    })


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
    """GET /api/proxy/status — proxy status."""
    json_response(handler, {"info": "Run freq proxy status for live data", "usage": "freq proxy status"})


def handle_comply_status(handler):
    """GET /api/comply/status — compliance status."""
    from freq.modules.comply import _load_results, CIS_CHECKS
    cfg = load_config()
    results = _load_results(cfg)
    json_response(handler, {
        "last_scan": results.get("last_scan", "never"),
        "total_checks": len(CIS_CHECKS),
        "scan_count": len(results.get("scans", [])),
    })


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
    routes["/api/vault"] = handle_vault
    routes["/api/vault/set"] = handle_vault_set
    routes["/api/vault/delete"] = handle_vault_delete
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
