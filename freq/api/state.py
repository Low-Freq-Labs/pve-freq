"""State/policy domain API handlers -- /api/policies, /api/policy/*, /api/baseline/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for policy compliance and baselines.
Why:   Decouples state/policy logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Registered in the unified fail-closed route registry.
"""

from freq.api.auth import check_session_role as _check_session_role
from freq.api.helpers import json_response, require_post
from freq.core import log as logger
from freq.core.config import load_config
from freq.core.http_query import parse_query as _parse_query

# -- Handlers ----------------------------------------------------------------


def handle_policies(handler):
    """GET /api/policies -- available policies."""
    from freq.engine.policies import ALL_POLICIES

    policy_list = [
        {
            "name": p["name"],
            "description": p.get("description", ""),
            "scope": p.get("scope", []),
        }
        for p in ALL_POLICIES
    ]
    json_response(handler, {"policies": policy_list, "count": len(policy_list)})


def handle_policy_check(handler):
    """GET /api/policy/check -- run policy compliance check (dry run)."""
    cfg = load_config()
    query = _parse_query(handler)
    policy = query.get("policy", [""])[0]
    hosts_param = query.get("hosts", [""])[0]
    try:
        import contextlib
        import io

        from freq.modules.engine_cmds import cmd_check

        class Args:
            pass

        args = Args()
        args.policy = policy or None
        args.hosts = hosts_param or None
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_check(cfg, None, args)
        json_response(handler, {"ok": result == 0, "output": buf.getvalue(), "policy": policy})
    except Exception as e:
        logger.error(f"api_state_error: policy check failed: {e}", endpoint="policy/check")
        json_response(handler, {"error": f"Policy check failed: {e}"}, 500)


def handle_policy_fix(handler):
    """POST /api/policy/fix -- apply policy remediation."""
    if require_post(handler, "Policy fix"):
        return
    cfg = load_config()
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    query = _parse_query(handler)
    policy = query.get("policy", [""])[0]
    hosts_param = query.get("hosts", [""])[0]
    try:
        import contextlib
        import io

        from freq.modules.engine_cmds import cmd_fix

        class Args:
            pass

        args = Args()
        args.policy = policy or None
        args.hosts = hosts_param or None
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_fix(cfg, None, args)
        json_response(handler, {"ok": result == 0, "output": buf.getvalue(), "policy": policy})
    except Exception as e:
        logger.error(f"api_state_error: policy fix failed: {e}", endpoint="policy/fix")
        json_response(handler, {"error": f"Policy fix failed: {e}"}, 500)


def handle_policy_diff(handler):
    """GET /api/policy/diff -- show policy drift as git-style diff."""
    cfg = load_config()
    query = _parse_query(handler)
    policy = query.get("policy", [""])[0]
    hosts_param = query.get("hosts", [""])[0]
    try:
        import contextlib
        import io

        from freq.modules.engine_cmds import cmd_diff

        class Args:
            pass

        args = Args()
        args.policy = policy or None
        args.hosts = hosts_param or None
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_diff(cfg, None, args)
        json_response(handler, {"ok": result == 0, "output": buf.getvalue(), "policy": policy})
    except Exception as e:
        logger.error(f"api_state_error: policy diff failed: {e}", endpoint="policy/diff")
        json_response(handler, {"error": f"Policy diff failed: {e}"}, 500)


def handle_baseline_list(handler):
    """GET /api/baseline/list -- list saved baselines."""
    from freq.modules.baseline import _list_baselines

    cfg = load_config()
    baselines = _list_baselines(cfg)
    json_response(handler, {"baselines": baselines, "count": len(baselines)})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register state/policy API routes into the master route table."""
    routes["/api/policies"] = handle_policies
    routes["/api/policy/check"] = handle_policy_check
    routes["/api/policy/fix"] = handle_policy_fix
    routes["/api/policy/diff"] = handle_policy_diff
    routes["/api/baseline/list"] = handle_baseline_list
