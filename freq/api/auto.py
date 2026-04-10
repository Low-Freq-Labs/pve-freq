"""Auto domain API handlers — /api/auto/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for automation: alert rules, scheduling, webhooks,
       playbooks, chaos engineering, and patrol status.
Why:   Decouples automation logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.

Maps to automation/orchestration CLI domains. Each handler is a standalone
function that receives the HTTP handler as its first argument.
"""

import os
import re

from freq.core import log as logger
from freq.api.helpers import require_post,  json_response, get_params
from freq.core.config import load_config
from freq.modules.serve import (
    _check_session_role,
    CACHE_DIR,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_params_flat(handler):
    """Parse query params into a flat {key: str} dict."""
    from urllib.parse import urlparse, parse_qs

    raw = parse_qs(urlparse(handler.path).query)
    return {k: v[0] if v else "" for k, v in raw.items()}


# ── Handlers ────────────────────────────────────────────────────────────


def handle_rules(handler):
    """GET /api/rules — list all alert rules and their current state."""
    from freq.jarvis.rules import load_rules, rules_to_dicts, load_rule_state

    cfg = load_config()
    rules = load_rules(cfg.conf_dir)
    state = load_rule_state(CACHE_DIR)
    rule_list = rules_to_dicts(rules)
    # Annotate with state info
    for rd in rule_list:
        active_hosts = [k.split(":", 1)[1] for k in state if k.startswith(f"{rd['name']}:")]
        rd["active_hosts"] = active_hosts
    json_response(handler, {"rules": rule_list, "count": len(rule_list)})


def handle_rules_create(handler):
    """GET /api/rules/create — create a new alert rule."""
    if require_post(handler, "Rule create"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.rules import Rule, load_rules, save_rules

    cfg = load_config()
    params = get_params(handler)
    name = params.get("name", [""])[0].strip()
    condition = params.get("condition", [""])[0].strip()
    if not name or not condition:
        json_response(handler, {"error": "name and condition required"}, 400)
        return
    valid_conditions = ("host_unreachable", "cpu_above", "ram_above", "disk_above", "docker_down")
    if condition not in valid_conditions:
        json_response(handler, {"error": f"Invalid condition. Valid: {', '.join(valid_conditions)}"}, 400)
        return
    rules = load_rules(cfg.conf_dir)
    if any(r.name == name for r in rules):
        json_response(handler, {"error": f"Rule '{name}' already exists"}, 409)
        return
    rules.append(
        Rule(
            name=name,
            condition=condition,
            target=params.get("target", ["*"])[0].strip(),
            threshold=float(params.get("threshold", ["0"])[0]),
            duration=int(params.get("duration", ["0"])[0]),
            severity=params.get("severity", ["warning"])[0].strip(),
            cooldown=int(params.get("cooldown", ["300"])[0]),
            enabled=params.get("enabled", ["true"])[0].lower() == "true",
        )
    )
    if save_rules(cfg.conf_dir, rules):
        json_response(handler, {"ok": True, "name": name})
    else:
        json_response(handler, {"error": "Failed to save rules"}, 500)


def handle_rules_update(handler):
    """GET /api/rules/update — update an existing alert rule (enable/disable/modify)."""
    if require_post(handler, "Rule update"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.rules import load_rules, save_rules

    cfg = load_config()
    params = get_params(handler)
    name = params.get("name", [""])[0].strip()
    if not name:
        json_response(handler, {"error": "name required"}, 400)
        return
    rules = load_rules(cfg.conf_dir)
    rule = next((r for r in rules if r.name == name), None)
    if not rule:
        json_response(handler, {"error": f"Rule '{name}' not found"}, 404)
        return
    # Update fields if provided
    if "enabled" in params:
        rule.enabled = params["enabled"][0].lower() == "true"
    if "threshold" in params:
        rule.threshold = float(params["threshold"][0])
    if "duration" in params:
        rule.duration = int(params["duration"][0])
    if "cooldown" in params:
        rule.cooldown = int(params["cooldown"][0])
    if "severity" in params:
        rule.severity = params["severity"][0].strip()
    if "target" in params:
        rule.target = params["target"][0].strip()
    if save_rules(cfg.conf_dir, rules):
        json_response(handler, {"ok": True, "name": name})
    else:
        json_response(handler, {"error": "Failed to save rules"}, 500)


def handle_rules_delete(handler):
    """GET /api/rules/delete — delete an alert rule."""
    if require_post(handler, "Rule delete"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.rules import load_rules, save_rules

    cfg = load_config()
    params = get_params(handler)
    name = params.get("name", [""])[0].strip()
    if not name:
        json_response(handler, {"error": "name required"}, 400)
        return
    rules = load_rules(cfg.conf_dir)
    before = len(rules)
    rules = [r for r in rules if r.name != name]
    if len(rules) == before:
        json_response(handler, {"error": f"Rule '{name}' not found"}, 404)
        return
    if save_rules(cfg.conf_dir, rules):
        json_response(handler, {"ok": True, "deleted": name})
    else:
        json_response(handler, {"error": "Failed to save rules"}, 500)


def handle_rules_history(handler):
    """GET /api/rules/history — return recent alert history."""
    from freq.jarvis.rules import load_alert_history

    history = load_alert_history(CACHE_DIR)
    json_response(handler, {"alerts": history, "count": len(history)})


def handle_schedule_jobs(handler):
    """GET /api/schedule/jobs — list scheduled jobs."""
    from freq.modules.schedule import _load_jobs

    cfg = load_config()
    jobs = _load_jobs(cfg)
    json_response(handler, {"jobs": jobs, "count": len(jobs)})


def handle_schedule_log(handler):
    """GET /api/schedule/log — get schedule execution log."""
    from freq.modules.schedule import _load_log

    cfg = load_config()
    log = _load_log(cfg)
    json_response(handler, {"log": log[-50:], "total": len(log)})


def handle_schedule_templates(handler):
    """GET /api/schedule/templates — list job templates."""
    from freq.modules.schedule import JOB_TEMPLATES

    json_response(handler, {"templates": JOB_TEMPLATES})


def handle_webhook_list(handler):
    """GET /api/webhook/list — list webhooks (tokens redacted)."""
    from freq.modules.webhook import _load_hooks

    cfg = load_config()
    hooks = _load_hooks(cfg)
    safe = []
    for h in hooks:
        safe.append({k: v for k, v in h.items() if k not in ("token", "secret")})
    json_response(handler, {"webhooks": safe, "count": len(safe)})


def handle_webhook_log(handler):
    """GET /api/webhook/log — get webhook execution log."""
    from freq.modules.webhook import _load_log

    cfg = load_config()
    log = _load_log(cfg)
    json_response(handler, {"log": log[-50:], "total": len(log)})


def handle_playbooks(handler):
    """GET /api/playbooks — list all available playbooks."""
    from freq.jarvis.playbook import load_playbooks, playbooks_to_dicts

    cfg = load_config()
    playbooks = load_playbooks(cfg.conf_dir)
    json_response(handler, {"playbooks": playbooks_to_dicts(playbooks)})


def handle_playbooks_run(handler):
    """GET /api/playbooks/run — run all steps of a playbook (non-confirm steps only)."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = _get_params_flat(handler)
    filename = params.get("filename", "")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        json_response(handler, {"error": "Invalid or missing filename"}, 400)
        return

    from freq.jarvis.playbook import load_playbooks, run_step, result_to_dict
    from freq.core.ssh import run as ssh_run

    cfg = load_config()
    playbooks = load_playbooks(cfg.conf_dir)
    pb = next((p for p in playbooks if p.filename == filename), None)
    if not pb:
        json_response(handler, {"error": f"Playbook '{filename}' not found"}, 404)
        return

    results = []
    for step in pb.steps:
        if step.confirm:
            results.append(
                {
                    "step_name": step.name,
                    "step_type": step.step_type,
                    "status": "pending_confirm",
                    "output": "",
                    "error": "Requires confirmation",
                    "duration": 0,
                }
            )
            break
        r = run_step(step, ssh_run, cfg)
        results.append(result_to_dict(r))
        if r.status == "fail":
            break

    json_response(
        handler,
        {
            "playbook": pb.name,
            "filename": pb.filename,
            "results": results,
            "completed": len(results) == len(pb.steps) and all(r["status"] == "pass" for r in results),
        },
    )


def handle_playbooks_step(handler):
    """GET /api/playbooks/step — run a single step of a playbook by index."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = _get_params_flat(handler)
    filename = params.get("filename", "")
    step_idx = params.get("step", "")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        json_response(handler, {"error": "Invalid or missing filename"}, 400)
        return
    if step_idx == "":
        json_response(handler, {"error": "Missing step parameter"}, 400)
        return

    try:
        step_idx = int(step_idx)
    except ValueError:
        json_response(handler, {"error": "step must be an integer"}, 400)
        return

    from freq.jarvis.playbook import load_playbooks, run_step, result_to_dict
    from freq.core.ssh import run as ssh_run

    cfg = load_config()
    playbooks = load_playbooks(cfg.conf_dir)
    pb = next((p for p in playbooks if p.filename == filename), None)
    if not pb:
        json_response(handler, {"error": f"Playbook '{filename}' not found"}, 404)
        return
    if step_idx < 0 or step_idx >= len(pb.steps):
        json_response(handler, {"error": f"Step index {step_idx} out of range"}, 400)
        return

    r = run_step(pb.steps[step_idx], ssh_run, cfg)
    json_response(
        handler,
        {
            "playbook": pb.name,
            "step_index": step_idx,
            "total_steps": len(pb.steps),
            "result": result_to_dict(r),
        },
    )


def handle_playbooks_create(handler):
    """GET /api/playbooks/create — create a new playbook from parameters."""
    if require_post(handler, "Playbook create"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    params = _get_params_flat(handler)
    name = params.get("name", "").strip()
    if not name:
        json_response(handler, {"error": "Missing playbook name"}, 400)
        return

    filename = re.sub(r"[^a-z0-9_-]", "-", name.lower()) + ".toml"
    cfg = load_config()
    pb_dir = os.path.join(cfg.conf_dir, "playbooks")
    os.makedirs(pb_dir, exist_ok=True)
    path = os.path.join(pb_dir, filename)
    if os.path.exists(path):
        json_response(handler, {"error": f"Playbook '{filename}' already exists"}, 409)
        return

    description = params.get("description", "")
    trigger = params.get("trigger", "")
    _te = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    content = f'[playbook]\nname = "{_te(name)}"\ndescription = "{_te(description)}"\ntrigger = "{_te(trigger)}"\n'
    try:
        with open(path, "w") as f:
            f.write(content)
        json_response(handler, {"ok": True, "filename": filename})
    except OSError as e:
        logger.error(f"api_auto_error: {e}", endpoint="playbooks/create")
        json_response(handler, {"error": str(e)}, 500)


def handle_chaos_types(handler):
    """GET /api/chaos/types — list available chaos experiment types."""
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.chaos import list_experiment_types

    json_response(handler, {"types": list_experiment_types()})


def handle_chaos_run(handler):
    """GET /api/chaos/run — run a chaos experiment (admin only)."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    from freq.jarvis.chaos import Experiment, run_experiment, result_to_dict
    from freq.core.ssh import run as ssh_run

    cfg = load_config()
    params = _get_params_flat(handler)
    name = params.get("name", "").strip()
    exp_type = params.get("type", "").strip()
    target = params.get("target", "").strip()
    service = params.get("service", "")
    try:
        duration = int(params.get("duration", "60"))
    except (ValueError, TypeError):
        json_response(handler, {"error": "duration must be an integer"}, 400)
        return

    if not name or not exp_type or not target:
        json_response(handler, {"error": "Missing name, type, or target parameter"}, 400)
        return

    exp = Experiment(
        name=name,
        experiment_type=exp_type,
        target_host=target,
        target_service=service,
        duration=duration,
    )
    result = run_experiment(exp, ssh_run, cfg)
    json_response(handler, {"result": result_to_dict(result)})


def handle_chaos_log(handler):
    """GET /api/chaos/log — return recent chaos experiment log."""
    from freq.jarvis.chaos import load_experiment_log

    cfg = load_config()
    params = _get_params_flat(handler)
    try:
        count = min(int(params.get("count", "20")), 50)
    except (ValueError, TypeError):
        count = 20
    log = load_experiment_log(cfg.data_dir, count)
    json_response(handler, {"experiments": log})


def handle_patrol_status(handler):
    """GET /api/patrol/status — get patrol (continuous monitoring) status."""
    cfg = load_config()
    try:
        import io
        import contextlib

        # Patrol is a long-running process — we return a one-shot status check
        from freq.modules.engine_cmds import cmd_check

        class Args:
            pass

        args = Args()
        args.policy = None
        args.hosts = None
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = cmd_check(cfg, None, args)
        json_response(
            handler,
            {
                "ok": result == 0,
                "output": buf.getvalue(),
                "note": "One-shot compliance check (patrol is a long-running CLI process)",
            },
        )
    except Exception as e:
        logger.error(f"api_auto_error: {e}", endpoint="patrol/status")
        json_response(handler, {"error": f"Patrol status failed: {e}"}, 500)


# ── Route Registration ──────────────────────────────────────────────────


def register(routes: dict):
    """Register auto API routes into the master route table.

    These routes use the same /api/ paths as the legacy serve.py handlers.
    The dispatch in serve.py checks _ROUTES first, then _V1_ROUTES. By
    removing these paths from _ROUTES, dispatch falls through to here.
    """
    routes["/api/rules"] = handle_rules
    routes["/api/rules/create"] = handle_rules_create
    routes["/api/rules/update"] = handle_rules_update
    routes["/api/rules/delete"] = handle_rules_delete
    routes["/api/rules/history"] = handle_rules_history
    routes["/api/schedule/jobs"] = handle_schedule_jobs
    routes["/api/schedule/log"] = handle_schedule_log
    routes["/api/schedule/templates"] = handle_schedule_templates
    routes["/api/webhook/list"] = handle_webhook_list
    routes["/api/webhook/log"] = handle_webhook_log
    routes["/api/playbooks"] = handle_playbooks
    routes["/api/playbooks/run"] = handle_playbooks_run
    routes["/api/playbooks/step"] = handle_playbooks_step
    routes["/api/playbooks/create"] = handle_playbooks_create
    routes["/api/chaos/types"] = handle_chaos_types
    routes["/api/chaos/run"] = handle_chaos_run
    routes["/api/chaos/log"] = handle_chaos_log
    routes["/api/patrol/status"] = handle_patrol_status
