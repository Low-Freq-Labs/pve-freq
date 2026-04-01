"""Operations domain API handlers -- /api/risk, /api/oncall/*.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for risk analysis and on-call management.
Why:   Decouples ops logic from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

from freq.api.helpers import json_response, get_cfg
from freq.core.config import load_config
from freq.jarvis.risk import _load_risk_map, _load_kill_chain


# -- Handlers ----------------------------------------------------------------


def handle_risk(handler):
    """GET /api/risk -- risk analysis data via API."""
    cfg = load_config()
    dependencies = _load_risk_map(cfg)
    chain = _load_kill_chain(cfg)
    targets = []
    for key, info in dependencies.items():
        targets.append({
            "name": key,
            "label": info["label"],
            "risk": info["risk"],
            "impact": info["impact"][0] if info["impact"] else "",
            "recovery": info["recovery"],
            "depends_on": info.get("depends_on", []),
            "depended_by": info.get("depended_by", []),
        })
    json_response(handler, {"targets": targets, "chain": chain})


def handle_oncall_whoami(handler):
    """GET /api/oncall/whoami -- who is on call."""
    from freq.modules.oncall import _load_schedule, _get_current_oncall
    cfg = load_config()
    schedule = _load_schedule(cfg)
    current = _get_current_oncall(schedule)
    json_response(handler, {"oncall": current, "rotation": schedule.get("rotation", "weekly"),
                            "users": schedule.get("users", [])})


def handle_oncall_schedule(handler):
    """GET /api/oncall/schedule -- get on-call schedule."""
    from freq.modules.oncall import _load_schedule
    cfg = load_config()
    json_response(handler, _load_schedule(cfg))


def handle_oncall_incidents(handler):
    """GET /api/oncall/incidents -- list incidents."""
    from freq.modules.oncall import _load_incidents
    cfg = load_config()
    incidents = _load_incidents(cfg)
    open_count = sum(1 for i in incidents if i.get("status") in ("open", "acknowledged"))
    json_response(handler, {"incidents": incidents[-50:], "total": len(incidents), "open": open_count})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register operations API routes into the master route table."""
    routes["/api/risk"] = handle_risk
    routes["/api/oncall/whoami"] = handle_oncall_whoami
    routes["/api/oncall/schedule"] = handle_oncall_schedule
    routes["/api/oncall/incidents"] = handle_oncall_incidents
