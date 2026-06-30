"""User domain API handlers -- /api/users, /api/users/create, etc.

Who:   Extracted from freq/modules/serve.py during Phase 0.5 refactor.
What:  REST endpoints for user management (CRUD, promote, demote).
Why:   Decouples user management from monolithic serve.py into a domain module.
Where: Routes registered at /api/* (same paths as legacy serve.py).
When:  Called by serve.py dispatcher via _V1_ROUTES fallback.
"""

import os

from freq.core import log as logger
from freq.api.helpers import require_post, json_response, get_json_body
from freq.api.auth import (
    _auth_lock,
    _auth_tokens,
    check_session_role as _check_session_role,
    current_user,
    hash_password,
)
from freq.core.config import load_config
from freq.modules.users import (
    _load_users,
    _save_users,
    _role_level,
    _valid_username,
    ROLE_HIERARCHY,
)
from freq.modules.serve import _parse_query
from freq.modules.vault import vault_delete, vault_init, vault_set


def _target_username(handler) -> str:
    params = _parse_query(handler)
    username = params.get("username", [""])[0]
    if username:
        return username.strip().lower()
    body = get_json_body(handler)
    return str(body.get("username", "") or "").strip().lower()


def _purge_user_sessions(username: str) -> int:
    purged = 0
    with _auth_lock:
        stale = [
            token
            for token, sess in _auth_tokens.items()
            if sess.get("user") == username
        ]
        for token in stale:
            del _auth_tokens[token]
            purged += 1
    return purged


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


def handle_user_reset_password(handler):
    """POST /api/users/reset-password -- reset another dashboard user's password."""
    if require_post(handler, "User password reset"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    body = get_json_body(handler)
    username = str(body.get("username", "") or "").strip().lower()
    password = str(body.get("password", "") or "")
    if not username:
        json_response(handler, {"error": "Username required"}, 400)
        return
    if not _valid_username(username):
        json_response(handler, {"error": "Invalid username"}, 400)
        return
    if username == current_user(handler):
        json_response(handler, {"error": "Use Change Password for your own account"}, 409)
        return
    if username == getattr(cfg, "ssh_service_account", ""):
        json_response(handler, {"error": "Service account password is not web-managed"}, 400)
        return
    if not password or len(password) < 8:
        json_response(handler, {"error": "Password must be at least 8 characters"}, 400)
        return
    users = _load_users(cfg)
    if not any(u["username"] == username for u in users):
        json_response(handler, {"error": f"User not found: {username}"}, 404)
        return
    try:
        if not os.path.exists(cfg.vault_file):
            vault_init(cfg)
    except Exception as e:
        try:
            vault_init(cfg)
        except Exception:
            logger.error(f"user password reset vault init failed for {username}: {e}")
            json_response(handler, {"error": "Vault unavailable"}, 500)
            return
    try:
        pw_hash = hash_password(password)
        vault_set(cfg, "auth", f"password_{username}", pw_hash)
    except Exception as e:
        logger.error(f"user password reset failed for {username}: {e}")
        json_response(handler, {"error": "Failed to update password"}, 500)
        return
    purged = _purge_user_sessions(username)
    json_response(handler, {"ok": True, "username": username, "sessions_purged": purged})


def handle_user_delete(handler):
    """POST /api/users/delete -- delete a dashboard user and stored password."""
    if require_post(handler, "User delete"):
        return
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return
    cfg = load_config()
    username = _target_username(handler)
    if not username:
        json_response(handler, {"error": "Username required"}, 400)
        return
    if not _valid_username(username):
        json_response(handler, {"error": "Invalid username"}, 400)
        return
    if username == current_user(handler):
        json_response(handler, {"error": "Cannot delete the signed-in user"}, 409)
        return
    if username == getattr(cfg, "ssh_service_account", ""):
        json_response(handler, {"error": "Service account cannot be deleted from Web UI"}, 400)
        return
    users = _load_users(cfg)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        json_response(handler, {"error": f"User not found: {username}"}, 404)
        return
    if user.get("role") == "protected":
        json_response(handler, {"error": "Protected user cannot be deleted"}, 409)
        return
    if user.get("role") == "admin":
        admins = [u for u in users if u.get("role") == "admin"]
        if len(admins) <= 1:
            json_response(handler, {"error": "Cannot delete the last admin"}, 409)
            return
    kept = [u for u in users if u["username"] != username]
    if not _save_users(cfg, kept):
        json_response(handler, {"error": "Failed to save users"}, 500)
        return
    try:
        vault_delete(cfg, "auth", f"password_{username}")
    except Exception as e:
        logger.warn(f"user delete could not remove password for {username}: {e}")
    purged = _purge_user_sessions(username)
    json_response(handler, {"ok": True, "username": username, "sessions_purged": purged})


def handle_user_promote(handler):
    """POST /api/users/promote -- promote a user."""
    if require_post(handler, "User promote"):
        return
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
    if require_post(handler, "User demote"):
        return
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
    routes["/api/users/reset-password"] = handle_user_reset_password
    routes["/api/users/delete"] = handle_user_delete
    routes["/api/users/promote"] = handle_user_promote
    routes["/api/users/demote"] = handle_user_demote
