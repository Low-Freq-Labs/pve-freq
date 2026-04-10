"""User domain API handlers -- /api/users, /api/users/create, etc.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for user management (CRUD, promote, demote).
Why:   Decouples user management from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

from freq.core import log as logger
from freq.api.helpers import require_post,  json_response
from freq.api.auth import check_session_role as _check_session_role
from freq.core.config import load_config
from freq.modules.users import _load_users, _save_users, _role_level, ROLE_HIERARCHY
from freq.modules.serve import _parse_query


# -- Handlers ----------------------------------------------------------------


def handle_users(handler):
    """GET /api/users -- list all users."""
    cfg = load_config()
    users = _load_users(cfg)
    json_response(handler, {"users": users, "count": len(users), "roles": ROLE_HIERARCHY})


def handle_user_create(handler):
    """POST /api/users/create -- create a new user."""
    if require_post(handler, "User create"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = _parse_query(handler)
    username = params.get("username", [""])[0]
    role = params.get("role", ["operator"])[0]
    if not username:
        json_response(handler, {"error": "Username required"}, 400)
        return
    users = _load_users(cfg)
    if any(u["username"] == username for u in users):
        json_response(handler, {"error": f"User '{username}' already exists"}, 409)
        return
    users.append({"username": username, "role": role, "groups": ""})
    ok = _save_users(cfg, users)
    json_response(handler, {"ok": ok, "username": username, "role": role})


def handle_user_promote(handler):
    """POST /api/users/promote -- promote a user."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = _parse_query(handler)
    username = params.get("username", [""])[0]
    users = _load_users(cfg)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        json_response(handler, {"error": f"User not found: {username}"}, 404)
        return
    lvl = _role_level(user["role"])
    if lvl >= _role_level("admin"):
        json_response(handler, {"error": "Already at max role"}, 409)
        return
    old = user["role"]
    user["role"] = ROLE_HIERARCHY[lvl + 1]
    _save_users(cfg, users)
    json_response(handler, {"ok": True, "username": username, "old": old, "new": user["role"]})


def handle_user_demote(handler):
    """POST /api/users/demote -- demote a user."""
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    params = _parse_query(handler)
    username = params.get("username", [""])[0]
    users = _load_users(cfg)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        json_response(handler, {"error": f"User not found: {username}"}, 404)
        return
    lvl = _role_level(user["role"])
    if lvl <= 0:
        json_response(handler, {"error": "Already at min role"}, 409)
        return
    old = user["role"]
    user["role"] = ROLE_HIERARCHY[lvl - 1]
    _save_users(cfg, users)
    json_response(handler, {"ok": True, "username": username, "old": old, "new": user["role"]})


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register user API routes into the master route table."""
    routes["/api/users"] = handle_users
    routes["/api/users/create"] = handle_user_create
    routes["/api/users/promote"] = handle_user_promote
    routes["/api/users/demote"] = handle_user_demote
