"""Host domain API handlers -- /api/keys, /api/groups.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for SSH key inventory and host group management.
Why:   Decouples host management from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

from freq.api.helpers import json_response
from freq.core.config import load_config
from freq.core import resolve as res
from freq.core.ssh import run_many as ssh_run_many


# -- Handlers ----------------------------------------------------------------


def handle_keys(handler):
    """GET /api/keys -- SSH key inventory across fleet."""
    cfg = load_config()
    results = ssh_run_many(
        hosts=cfg.hosts,
        command="cat ~/.ssh/authorized_keys 2>/dev/null | wc -l",
        key_path=cfg.ssh_key_path,
        connect_timeout=3,
        command_timeout=5,
        max_parallel=10,
        use_sudo=False,
        cfg=cfg,
    )
    keys = []
    for h in cfg.hosts:
        r = results.get(h.label)
        err = r.stderr or "" if r else ""
        down = (
            r is None
            or r.returncode == 124
            or "Connection timed out" in err
            or "Connection refused" in err
            or "No route to host" in err
        )
        reachable = not down
        keys.append(
            {
                "host": h.label,
                "ip": h.ip,
                "reachable": reachable,
                "key_count": int(r.stdout.strip()) if r and r.returncode == 0 and r.stdout.strip().isdigit() else 0,
            }
        )
    json_response(handler, {"hosts": keys, "ssh_key": cfg.ssh_key_path})


def handle_groups(handler):
    """GET /api/groups -- host groups."""
    cfg = load_config()
    groups = {g: [h.label for h in hosts] for g, hosts in res.all_groups(cfg.hosts).items()}
    json_response(handler, {"groups": groups})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register host API routes into the master route table."""
    routes["/api/keys"] = handle_keys
    routes["/api/groups"] = handle_groups
