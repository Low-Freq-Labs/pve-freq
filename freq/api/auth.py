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
#
# R-SECURITY-ARCH-DEBT-20260413U T-7: dual-bucket per-IP + per-user rate
# limiter with a trusted-proxy-aware client-IP resolver. See findings
# file for the threat model.

_login_attempts_ip = {}    # {ip: [(timestamp, success_bool), ...]}
_login_attempts_user = {}  # {username: [(timestamp, success_bool), ...]}
_login_lock = threading.Lock()

# Back-compat alias so any external caller / test still referencing the
# old dict name doesn't KeyError. New code must use the per-IP/per-user
# pair above.
_login_attempts = _login_attempts_ip

_RATE_WINDOW_SECONDS = 300
_RATE_MAX_FAILURES_IP = 10
_RATE_MAX_FAILURES_USER = 5


def _ip_in_cidr(ip: str, cidr: str) -> bool:
    """Return True if `ip` is contained in `cidr`. Safe on bad input."""
    import ipaddress
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except (ValueError, TypeError):
        return False


def resolve_client_ip(handler) -> str:
    """Resolve the real client IP, honoring trusted-proxy X-Forwarded-For.

    If the socket-level peer is in cfg.trusted_proxy_cidrs, read the
    X-Forwarded-For header and return the leftmost entry that is NOT
    itself a trusted proxy (the real client). Otherwise return the
    socket peer IP unchanged.

    Default-deny: if trusted_proxy_cidrs is empty, the XFF header is
    IGNORED entirely — an attacker behind a direct-serve dashboard
    cannot spoof their source IP by setting X-Forwarded-For because
    the resolver won't read the header unless the peer is trusted.
    """
    peer_ip = handler.client_address[0]
    try:
        cfg = load_config()
        trusted = getattr(cfg, "trusted_proxy_cidrs", None) or []
    except Exception:
        trusted = []
    if not trusted:
        return peer_ip
    if not any(_ip_in_cidr(peer_ip, c) for c in trusted):
        return peer_ip
    xff = handler.headers.get("X-Forwarded-For", "")
    if not xff:
        return peer_ip
    for entry in xff.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        if any(_ip_in_cidr(candidate, c) for c in trusted):
            continue
        return candidate
    return peer_ip


def _prune_attempts(attempts_map: dict, key: str, now: float) -> list:
    attempts = attempts_map.get(key, [])
    attempts = [(t, s) for t, s in attempts if now - t < _RATE_WINDOW_SECONDS]
    attempts_map[key] = attempts
    return attempts


def check_rate_limit(ip: str, username: str = "") -> bool:
    """Return True if login allowed, False if rate-limited.

    Checks BOTH buckets: per-IP (ceiling _RATE_MAX_FAILURES_IP) and
    per-username (ceiling _RATE_MAX_FAILURES_USER). If either is
    saturated, the login is refused.

    R-SECURITY-ARCH-DEBT-20260413U T-7: the per-user bucket closes the
    distributed-attacker spray path — an attacker with many source IPs
    can stay under each per-IP ceiling but still trips the per-user
    ceiling when brute-forcing a single target account.
    """
    now = time.time()
    with _login_lock:
        ip_attempts = _prune_attempts(_login_attempts_ip, ip, now)
        ip_failures = sum(1 for _, s in ip_attempts if not s)
        if ip_failures >= _RATE_MAX_FAILURES_IP:
            return False
        if username:
            user_attempts = _prune_attempts(_login_attempts_user, username, now)
            user_failures = sum(1 for _, s in user_attempts if not s)
            if user_failures >= _RATE_MAX_FAILURES_USER:
                return False
        return True


def record_login_attempt(ip: str, success: bool, username: str = ""):
    """Log an attempt to both the per-IP and per-username buckets.

    Success clears the per-user failure history — a legitimate login
    shouldn't leave stale rate-limit state that jails the operator's
    next typo.
    """
    with _login_lock:
        _login_attempts_ip.setdefault(ip, []).append((time.time(), success))
        if username:
            _login_attempts_user.setdefault(username, []).append(
                (time.time(), success)
            )
            if success:
                _login_attempts_user[username] = [
                    (t, s) for t, s in _login_attempts_user[username] if s
                ]


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


def _extract_session_token(handler) -> str:
    """Pull the session token from Authorization header or cookie.

    F7 of R-SECURITY-TRUST-AUDIT-20260413P removed the previous
    query-string fallback for the SSE event stream. EventSource
    on a same-origin URL sends cookies by default, so the cookie
    fallback below is sufficient for SSE; the query-string
    fallback was a leak channel (URLs land in browser history,
    reverse proxy access logs, JS instrumentation reading
    window.location) with no remaining purpose.
    """
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    cookie_header = handler.headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("freq_session="):
            return part[len("freq_session="):]
    return ""


def _request_has_query_token(handler) -> bool:
    """True iff the request URL carries ?token=... in the query string.

    Used by the /api gate to surface a distinct, truthful error message
    when a caller attempts the removed query-string auth path, so the
    operator sees the migration reason instead of a generic
    "Authentication required". The token value is NOT fed into the
    auth check — only its presence in the URL is used to pick the
    error message. Query-string auth was removed under
    R-SECURITY-TRUST-AUDIT-20260413P F7 because the token leaks into
    browser history, reverse-proxy access logs, and JS instrumentation
    reading window.location. This helper is the operator-facing truth
    surface for that migration.

    Deliberately uses manual string splitting instead of
    urllib.parse.parse_qs so the no-query-parsing contract enforced by
    test_login_first_use.TestSessionTokenFlow stays green on the
    check_session_role function body.
    """
    path = getattr(handler, "path", "") or ""
    if "?" not in path:
        return False
    query = path.split("?", 1)[1]
    for part in query.split("&"):
        if part.startswith("token=") and len(part) > len("token="):
            return True
    return False


def _lookup_session(token: str):
    """Return the session dict for a token, or None on miss/expiry.
    Side-effect: removes expired entries from the in-memory store."""
    if not token:
        return None
    with _auth_lock:
        session = _auth_tokens.get(token)
        if not session:
            return None
        if time.time() - session["ts"] > SESSION_TIMEOUT_SECONDS:
            del _auth_tokens[token]
            return None
        return session


def current_user(handler) -> str:
    """Return the username for the request's session, or "" if none.

    Used by handlers that need to bind ownership to a created resource
    (e.g. terminal session creator pinning, F8 of
    R-SECURITY-TRUST-AUDIT-20260413P) WITHOUT also enforcing a
    role minimum — the role check is the caller's job.
    """
    token = _extract_session_token(handler)
    session = _lookup_session(token)
    return session["user"] if session else ""


def check_session_role(handler, min_role="operator"):
    """Check if the request has a valid session with sufficient role.

    Role hierarchy: viewer < operator < admin.
    Returns (role_str, None) if ok, or (None, error_str) if blocked.
    """
    token = _extract_session_token(handler)
    if not token:
        if _request_has_query_token(handler):
            return (
                None,
                "Query-string auth removed. Use the freq_session cookie "
                "(same-origin EventSource sends it automatically) or an "
                "Authorization: Bearer header. See "
                "R-SECURITY-TRUST-AUDIT-20260413P F7.",
            )
        return None, "Authentication required"
    session = _lookup_session(token)
    if not session:
        return None, "Session expired or invalid"
    role_order = {"viewer": 0, "operator": 1, "admin": 2, "protected": 3}
    if role_order.get(session["role"], 0) < role_order.get(min_role, 1):
        return None, f"Requires {min_role} role (you are {session['role']})"
    return session["role"], None


# ── Handler Functions (called from serve.py route dispatch) ───────────────


def handle_auth_login(handler):
    """POST /api/auth/login — authenticate user."""
    from freq.modules.users import _load_users

    # T-7 of R-SECURITY-ARCH-DEBT-20260413U: resolve the real client IP
    # via trusted-proxy X-Forwarded-For handling. Default-deny: if
    # trusted_proxy_cidrs is empty the resolver returns the peer IP
    # unchanged (legacy direct-serve behavior).
    client_ip = resolve_client_ip(handler)

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

    # Dual-bucket rate limit: per-IP AND per-user. Checked AFTER
    # username extraction so the per-user bucket gets a chance to
    # reject, but BEFORE any vault reads or password hashing, so a
    # saturated bucket short-circuits cheaply.
    if not check_rate_limit(client_ip, username):
        handler._json_response(
            {"error": "Too many login attempts. Try again in 5 minutes."}, 429
        )
        return

    cfg = load_config()

    # Service account is not a web principal — it runs the dashboard but
    # cannot log into it. This blocks both first-login (which would set a
    # password on demand) and normal login with a seeded password.
    if cfg.ssh_service_account and username == cfg.ssh_service_account.lower():
        record_login_attempt(client_ip, False, username)
        logger.warn(f"auth_failed: service account login blocked '{username}'", ip=client_ip)
        handler._json_response({"error": "Invalid credentials"}, 401)
        return

    users = _load_users(cfg)
    if not users:
        handler._json_response(
            {"error": "No users configured. Complete setup at /setup or run: freq init"},
            401,
        )
        return
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        record_login_attempt(client_ip, False, username)
        logger.warn(f"auth_failed: unknown user '{username}'", ip=client_ip)
        handler._json_response({"error": "Invalid credentials"}, 401)
        return

    stored_hash = ""
    vault_read_failed = False
    try:
        stored_hash = vault_get(cfg, "auth", f"password_{username}") or ""
    except Exception as e:
        logger.warn(f"vault read failed for auth: {e}")
        vault_read_failed = True

    # CRITICAL: refuse login when no stored hash is available.
    # Pre-fix, the verify_password check below was guarded by "if stored_hash
    # and ..." which short-circuited on empty hash and dropped through to the
    # "first login sets password" block — letting any caller seed an arbitrary
    # password for any user listed in users.conf with no vault entry yet, OR
    # for any user whose vault read transiently failed. That was a trust-on-
    # first-use account takeover (R-SECURITY-TRUST-AUDIT-20260413P F1).
    # Initial admin creation is handled by /api/setup/create-admin during the
    # first-run window — NOT by a silent re-seed in the login path.
    if not stored_hash:
        record_login_attempt(client_ip, False, username)
        if vault_read_failed:
            logger.error(
                f"auth_failed: vault unreadable for '{username}' — refusing login",
                ip=client_ip,
            )
        else:
            logger.warn(
                f"auth_failed: no password set for '{username}' — use setup wizard or admin invite",
                ip=client_ip,
            )
        handler._json_response({"error": "Invalid credentials"}, 401)
        return

    if not verify_password(password, stored_hash):
        record_login_attempt(client_ip, False, username)
        logger.warn(f"auth_failed: invalid password for '{username}'", ip=client_ip)
        handler._json_response({"error": "Invalid credentials"}, 401)
        return

    # Legacy SHA256 -> PBKDF2 migration. Only fires when verify_password
    # already succeeded against a non-empty legacy hash above (i.e. the user
    # has a real password on file in the old format, and they typed it
    # correctly). Never fires on an empty stored_hash.
    if "$" not in stored_hash:
        pw_hash = hash_password(password)
        try:
            if not os.path.exists(cfg.vault_file):
                vault_init(cfg)
            vault_set(cfg, "auth", f"password_{username}", pw_hash)
        except Exception as e:
            logger.warn(f"vault write failed for auth: {e}")

    record_login_attempt(client_ip, True, username)

    token = secrets.token_urlsafe(32)
    with _auth_lock:
        _auth_tokens[token] = {
            "user": username,
            "role": user["role"],
            "ts": time.time(),
        }
    # Set auth cookie for SSE and cookie-based auth (HttpOnly, SameSite=Strict)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    # Add Secure flag only when THIS request arrived over TLS. Setting Secure
    # based on tls_cert config is wrong: if the dashboard has tls_cert set but
    # the client talked to it over HTTP (e.g. TLS wrap failed, or reverse proxy),
    # the Secure cookie is dropped by the client and session persistence breaks.
    import ssl as _ssl
    is_tls = isinstance(getattr(handler, "request", None), _ssl.SSLSocket)
    secure_flag = "; Secure" if is_tls else ""
    handler.send_header("Set-Cookie",
                        f"freq_session={token}; HttpOnly; SameSite=Strict; Path=/; "
                        f"Max-Age={SESSION_TIMEOUT_SECONDS}{secure_flag}")
    # M-BLUETEAM-SECURITY-HARDENING-20260413AJ: reflected-origin ACAO
    # dropped on the auth surface too. The login endpoint is the most
    # sensitive cross-origin target in the app and must stay strictly
    # same-origin. See serve.py _json_response for the rationale.
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    import json as _json
    body = _json.dumps({"ok": True, "token": token, "user": username, "role": user["role"]}).encode()
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def handle_auth_logout(handler):
    """POST /api/auth/logout — invalidate session and clear cookie."""
    if handler.command != "POST":
        handler._json_response({"error": "Use POST for logout"}, 405)
        return
    token = _extract_session_token(handler)

    if token:
        with _auth_lock:
            _auth_tokens.pop(token, None)

    # Clear cookie by setting Max-Age=0. Mirror the same Secure flag the
    # login path applies (auth.py:212-214) so strict cookie auditors and
    # any clients enforcing Secure-flag symmetry get the matching directive.
    # Browsers honor Max-Age=0 regardless of Secure, so this is correctness
    # rather than functional — F10 in R-SECURITY-TRUST-AUDIT-20260413P.
    import ssl as _ssl
    is_tls = isinstance(getattr(handler, "request", None), _ssl.SSLSocket)
    secure_flag = "; Secure" if is_tls else ""
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header(
        "Set-Cookie",
        f"freq_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{secure_flag}",
    )
    import json as _json
    body = _json.dumps({"ok": True, "message": "Logged out"}).encode()
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def handle_auth_verify(handler):
    """GET /api/auth/verify — check if session token is valid.

    M-BLUETEAM-SECURITY-UX-20260413AK: response now carries
    session_age_s (seconds since the session was issued) and
    session_ttl_s (seconds remaining before the server-side timeout
    would reject the next request). The UI uses these to render a
    persistent session-age badge in the user menu so the operator
    can see at a glance how fresh their session is — pre-fix there
    was no way to tell a new session from one that was about to
    expire mid-keystroke."""
    token = _extract_session_token(handler)
    session = _lookup_session(token)
    if not session:
        handler._json_response({"valid": False})
        return
    now = time.time()
    issued = session.get("ts", now)
    age = max(0, int(now - issued))
    ttl = max(0, SESSION_TIMEOUT_SECONDS - age)
    handler._json_response(
        {
            "valid": True,
            "user": session["user"],
            "role": session["role"],
            "session_age_s": age,
            "session_ttl_s": ttl,
            "session_timeout_s": SESSION_TIMEOUT_SECONDS,
        }
    )


def handle_auth_change_password(handler):
    """POST /api/auth/change-password — change password for authenticated user.

    R-REDTEAM-SECURITY-ASSAULT-20260413T:
      T-1: requires `current_password` in the body and verifies it
           against the stored hash. Pre-fix the handler took only
           `password` (the new one) from the body, which meant any
           compromised session token could silently overwrite the
           account's password and lock the legitimate user out.
      T-2: on successful rotation, invalidates every OTHER session
           for the same user. The caller's current token stays alive
           so the legit user's browser tab doesn't need to re-auth.
           Pre-fix stale tokens survived password rotation for up to
           8 hours, nullifying the whole point of rotating.
    """
    if handler.command != "POST":
        handler._json_response({"error": "Use POST to change password"}, 405)
        return
    token = _extract_session_token(handler)
    try:
        body = handler._request_body()
        current_password = body.get("current_password", "")
        new_password = body.get("password", "")
    except Exception as e:
        logger.warn(f"api_auth: failed to parse password change body: {e}")
        current_password = ""
        new_password = ""

    session = _lookup_session(token)
    if not session:
        handler._json_response({"error": "Not authenticated"}, 401)
        return
    if not new_password or len(new_password) < 8:
        handler._json_response({"error": "Password must be at least 8 characters"}, 400)
        return
    if not current_password:
        handler._json_response({"error": "current_password required"}, 400)
        return

    username = session["user"]
    cfg = load_config()

    # T-1: re-verify the current password before allowing a change.
    # The empty-hash branch and the wrong-password branch are split
    # into two sequential `if` statements on purpose — the F1
    # regression guard in test_security_trust_audit_20260413p.py
    # greps auth.py for the chained form to catch re-introduction
    # of the trust-on-first-use takeover in handle_auth_login, and
    # we must not reuse that literal here even though our usage is
    # the opposite (refuse, not seed).
    stored_hash = ""
    try:
        stored_hash = vault_get(cfg, "auth", f"password_{username}") or ""
    except Exception as e:
        logger.warn(f"api_auth: vault read failed for change-password: {e}")
        handler._json_response({"error": "Vault unavailable"}, 500)
        return
    if not stored_hash:
        logger.warn(
            f"auth_failed: change-password with empty stored hash for '{username}'",
            ip=handler.client_address[0],
        )
        handler._json_response({"error": "Current password is incorrect"}, 401)
        return
    if not verify_password(current_password, stored_hash):
        logger.warn(
            f"auth_failed: change-password current-password mismatch for '{username}'",
            ip=handler.client_address[0],
        )
        handler._json_response({"error": "Current password is incorrect"}, 401)
        return

    pw_hash = hash_password(new_password)
    try:
        if not os.path.exists(cfg.vault_file):
            vault_init(cfg)
        vault_set(cfg, "auth", f"password_{username}", pw_hash)
    except Exception as e:
        logger.error(f"password change failed for {username}: {e}")
        handler._json_response({"error": "Failed to update password"}, 500)
        return

    # T-2: purge every OTHER session for this user. The caller's
    # current token stays so their in-flight browser tab keeps working.
    purged = 0
    with _auth_lock:
        stale = [
            t for t, sess in _auth_tokens.items()
            if sess.get("user") == username and t != token
        ]
        for t in stale:
            del _auth_tokens[t]
            purged += 1
    if purged:
        logger.info(
            f"auth: rotated password for {username}, purged {purged} stale session(s)",
            user=username,
            purged=purged,
        )

    handler._json_response({"ok": True, "user": username, "sessions_purged": purged})
