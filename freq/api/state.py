"""State/policy domain API handlers -- /api/policies, /api/policy/*, /api/baseline/*, /api/gitops/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for policy compliance, baselines, and GitOps config sync.
Why:   Decouples state/policy logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

from freq.core import log as logger
from freq.api.helpers import json_response
from freq.core.config import load_config
from freq.modules.serve import (
    _parse_query,
    _parse_query_flat,
    _check_session_role,
)


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
        import io, contextlib
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
    cfg = load_config()
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err})
        return
    query = _parse_query(handler)
    policy = query.get("policy", [""])[0]
    hosts_param = query.get("hosts", [""])[0]
    try:
        import io, contextlib
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
        import io, contextlib
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


def handle_gitops_status(handler):
    """GET /api/gitops/status -- return GitOps sync status and configuration."""
    from freq.jarvis.gitops import load_gitops_config, load_state, state_to_dict

    cfg = load_config()
    go_cfg = load_gitops_config(cfg.conf_dir)
    state = load_state(cfg.data_dir)
    json_response(
        handler,
        {
            "enabled": go_cfg.enabled,
            "repo_url": go_cfg.repo_url,
            "branch": go_cfg.branch,
            "sync_interval": go_cfg.sync_interval,
            "auto_apply": go_cfg.auto_apply,
            "state": state_to_dict(state),
        },
    )


def handle_gitops_sync(handler):
    """POST /api/gitops/sync -- trigger a sync (fetch) from remote."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err})
        return
    from freq.jarvis.gitops import load_gitops_config, sync, state_to_dict

    cfg = load_config()
    go_cfg = load_gitops_config(cfg.conf_dir)
    if not go_cfg.enabled:
        json_response(handler, {"error": "GitOps not configured -- set repo_url in freq.toml [gitops]"})
        return
    state = sync(cfg.data_dir, go_cfg.branch)
    json_response(handler, {"ok": True, "state": state_to_dict(state)})


def handle_gitops_apply(handler):
    """POST /api/gitops/apply -- apply pending changes (pull)."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err})
        return
    from freq.jarvis.gitops import load_gitops_config, apply_changes, load_state, state_to_dict

    cfg = load_config()
    go_cfg = load_gitops_config(cfg.conf_dir)
    if not go_cfg.enabled:
        json_response(handler, {"error": "GitOps not configured"})
        return
    ok, msg = apply_changes(cfg.data_dir, go_cfg.branch)
    state = load_state(cfg.data_dir)
    json_response(handler, {"ok": ok, "message": msg, "state": state_to_dict(state)})


def handle_gitops_diff(handler):
    """GET /api/gitops/diff -- show diff between local and remote."""
    from freq.jarvis.gitops import load_gitops_config, get_diff, get_diff_full

    cfg = load_config()
    go_cfg = load_gitops_config(cfg.conf_dir)
    params = _parse_query_flat(handler.path)
    full = params.get("full", "") == "1"
    if full:
        diff = get_diff_full(cfg.data_dir, go_cfg.branch)
    else:
        diff = get_diff(cfg.data_dir, go_cfg.branch)
    json_response(handler, {"diff": diff})


def handle_gitops_log(handler):
    """GET /api/gitops/log -- return recent commit history."""
    from freq.jarvis.gitops import get_log

    cfg = load_config()
    params = _parse_query_flat(handler.path)
    try:
        count = min(int(params.get("count", "20")), 50)
    except (ValueError, TypeError):
        count = 20
    commits = get_log(cfg.data_dir, count)
    json_response(handler, {"commits": commits})


def handle_gitops_rollback(handler):
    """POST /api/gitops/rollback -- rollback config to a specific commit."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err})
        return
    from freq.jarvis.gitops import rollback

    cfg = load_config()
    params = _parse_query_flat(handler.path)
    commit = params.get("commit", "").strip()
    if not commit:
        json_response(handler, {"error": "Missing commit parameter"})
        return
    ok, msg = rollback(cfg.data_dir, commit)
    json_response(handler, {"ok": ok, "message": msg})


def handle_gitops_init(handler):
    """POST /api/gitops/init -- initialize the gitops repo clone."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err})
        return
    from freq.jarvis.gitops import load_gitops_config, init_repo

    cfg = load_config()
    go_cfg = load_gitops_config(cfg.conf_dir)
    if not go_cfg.repo_url:
        json_response(handler, {"error": "No repo_url configured in freq.toml [gitops]"})
        return
    ok, msg = init_repo(cfg.data_dir, go_cfg.repo_url, go_cfg.branch)
    json_response(handler, {"ok": ok, "message": msg})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register state/policy API routes into the master route table."""
    routes["/api/policies"] = handle_policies
    routes["/api/policy/check"] = handle_policy_check
    routes["/api/policy/fix"] = handle_policy_fix
    routes["/api/policy/diff"] = handle_policy_diff
    routes["/api/baseline/list"] = handle_baseline_list
    routes["/api/gitops/status"] = handle_gitops_status
    routes["/api/gitops/sync"] = handle_gitops_sync
    routes["/api/gitops/apply"] = handle_gitops_apply
    routes["/api/gitops/diff"] = handle_gitops_diff
    routes["/api/gitops/log"] = handle_gitops_log
    routes["/api/gitops/rollback"] = handle_gitops_rollback
    routes["/api/gitops/init"] = handle_gitops_init
