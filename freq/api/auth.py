"""Auth module — session management, password hashing, rate limiting.

Extracted from freq/modules/serve.py during Phase 3.1 refactor.
Centralizes all authentication logic in one focused module.

Used by: serve.py (route handlers), secure.py (vault auth), helpers.py (decorator)
"""

import hashlib
import os
import secrets
import threading
import time
from urllib.parse import urlparse, parse_qs

from freq.core import log as logger
from freq.core.config import load_config
from freq.modules.vault import vault_get, vault_set, vault_init


# ── Constants ──────────────────────────────────────────────────────────────

SESSION_TIMEOUT_HOURS = 8
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_HOURS * 3600


# ── Token Store (in-memory, cleared on restart) ───────────────────────────

_auth_tokens = {}  # token -> {user, role, ts}
_auth_lock = threading.Lock()


# ── Rate Limiting ─────────────────────────────────────────────────────────

_login_attempts = {}  # {ip: [(timestamp, success_bool), ...]}
_login_lock = threading.Lock()


def check_rate_limit(ip: str) -> bool:
    """Return True if login allowed, False if rate-limited."""
    now = time.time()
    window = 300  # 5 minutes
    max_failures = 10
    with _login_lock:
        attempts = _login_attempts.get(ip, [])
        attempts = [(t, s) for t, s in attempts if now - t < window]
        _login_attempts[ip] = attempts
        failures = sum(1 for t, s in attempts if not s)
        return failures < max_failures


def record_login_attempt(ip: str, success: bool):
    with _login_lock:
        if ip not in _login_attempts:
            _login_attempts[ip] = []
        _login_attempts[ip].append((time.time(), success))


# ── Password Hashing ─────────────────────────────────────────────────────


def hash_password(password: str, salt: str = None) -> str:
    """Hash password with PBKDF2-SHA256 + per-user salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify password against stored hash. Supports legacy SHA256 for migration."""
    if "$" not in stored:
        return hashlib.sha256(password.encode()).hexdigest() == stored
    salt, _ = stored.split("$", 1)
    return hash_password(password, salt) == stored


# ── Session Check ─────────────────────────────────────────────────────────


def check_session_role(handler, min_role="operator"):
    """Check if the request has a valid session with sufficient role.

    Role hierarchy: viewer < operator < admin.
    Returns (role_str, None) if ok, or (None, error_str) if blocked.
    """
    token = ""
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        params = parse_qs(urlparse(handler.path).query)
        token = params.get("token", [""])[0]
    if not token:
        return None, "Authentication required"
    with _auth_lock:
        session = _auth_tokens.get(token)
        if not session:
            return None, "Session expired or invalid"
        if time.time() - session["ts"] > SESSION_TIMEOUT_SECONDS:
            del _auth_tokens[token]
            return None, "Session expired"
    role_order = {"viewer": 0, "operator": 1, "admin": 2, "protected": 3}
    if role_order.get(session["role"], 0) < role_order.get(min_role, 1):
        return None, f"Requires {min_role} role (you are {session['role']})"
    return session["role"], None


# ── Handler Functions (called from serve.py route dispatch) ───────────────


def handle_auth_login(handler):
    """POST /api/auth/login — authenticate user."""
    from freq.modules.users import _load_users

    client_ip = handler.client_address[0]
    if not check_rate_limit(client_ip):
        handler._json_response({"error": "Too many login attempts. Try again in 5 minutes."}, 429)
        return

    if handler.command != "POST":
        handler._json_response({"error": "Use POST with JSON body for login"}, 405)
        return
    try:
        body = handler._request_body()
        username = body.get("username", "").strip().lower()
        password = body.get("password", "")
    except Exception as e:
        logger.warn(f"auth_failed: invalid request body: {e}", endpoint="auth/login")
        handler._json_response({"error": "Invalid request body"}, 400)
        return

    if not username or not password:
        handler._json_response({"error": "Username and password required"}, 400)
        return

    cfg = load_config()
    users = _load_users(cfg)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        record_login_attempt(client_ip, False)
        logger.warn(f"auth_failed: unknown user '{username}'", ip=client_ip)
        handler._json_response({"error": "Invalid credentials"}, 401)
        return

    stored_hash = ""
    try:
        stored_hash = vault_get(cfg, "auth", f"password_{username}") or ""
    except Exception as e:
        logger.warn(f"vault read failed for auth: {e}")

    if stored_hash and not verify_password(password, stored_hash):
        record_login_attempt(client_ip, False)
        logger.warn(f"auth_failed: invalid password for '{username}'", ip=client_ip)
        handler._json_response({"error": "Invalid credentials"}, 401)
        return

    # First login sets password / migrate legacy SHA256 to PBKDF2
    if not stored_hash or ("$" not in stored_hash):
        pw_hash = hash_password(password)
        try:
            if not os.path.exists(cfg.vault_file):
                vault_init(cfg)
            vault_set(cfg, "auth", f"password_{username}", pw_hash)
        except Exception as e:
            logger.warn(f"vault write failed for auth: {e}")

    record_login_attempt(client_ip, True)

    token = secrets.token_urlsafe(32)
    with _auth_lock:
        _auth_tokens[token] = {
            "user": username,
            "role": user["role"],
            "ts": time.time(),
        }
    handler._json_response(
        {
            "ok": True,
            "token": token,
            "user": username,
            "role": user["role"],
        }
    )


def handle_auth_verify(handler):
    """GET /api/auth/verify — check if session token is valid."""
    token = ""
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        params = parse_qs(urlparse(handler.path).query)
        token = params.get("token", [""])[0]
    with _auth_lock:
        session = _auth_tokens.get(token)
        if not session:
            handler._json_response({"valid": False})
            return
        if time.time() - session["ts"] > SESSION_TIMEOUT_SECONDS:
            del _auth_tokens[token]
            handler._json_response({"valid": False})
            return
    handler._json_response(
        {
            "valid": True,
            "user": session["user"],
            "role": session["role"],
        }
    )


def handle_auth_change_password(handler):
    """POST /api/auth/change-password — change password for authenticated user."""
    token = ""
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    if not token:
        params = parse_qs(urlparse(handler.path).query)
        token = params.get("token", [""])[0]
    if handler.command != "POST":
        handler._json_response({"error": "Use POST to change password"}, 405)
        return
    try:
        body = handler._request_body()
        new_password = body.get("password", "")
    except Exception as e:
        logger.warn(f"api_auth: failed to parse password change body: {e}")
        new_password = ""

    with _auth_lock:
        session = _auth_tokens.get(token)
    if not session:
        handler._json_response({"error": "Not authenticated"}, 401)
        return
    if not new_password or len(new_password) < 6:
        handler._json_response({"error": "Password must be at least 6 characters"}, 400)
        return

    username = session["user"]
    cfg = load_config()
    pw_hash = hash_password(new_password)
    try:
        if not os.path.exists(cfg.vault_file):
            vault_init(cfg)
        vault_set(cfg, "auth", f"password_{username}", pw_hash)
        handler._json_response({"ok": True, "user": username})
    except Exception as e:
        logger.error(f"password change failed for {username}: {e}")
        handler._json_response({"error": "Failed to update password"}, 500)
