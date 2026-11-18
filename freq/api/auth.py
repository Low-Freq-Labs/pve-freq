"""Auth module — session management, password hashing, rate limiting.

Extracted from freq/modules/serve.py during Phase 3.1 refactor.
Centralizes all authentication logic in one focused module.

Used by: serve.py (route handlers), secure.py (vault auth), helpers.py (decorator)
"""

import hashlib
import json
import os
import secrets
import shutil
import sys
import threading
import time
from urllib.parse import urlparse

from freq.core import log as logger
from freq.core.config import load_config
from freq.core.setup_contract import (
    SetupContractError,
    clear_setup_contract,
    contract_credential_keys,
    credential_runtime_value,
    credential_vault_key,
    load_setup_contract,
)
from freq.core.setup_state import SCHEMA as ZERO_STATE_WEB_SCHEMA
from freq.core.setup_state import load_setup_state, setup_state_path
from freq.core.vault import vault_get, vault_init, vault_list, vault_set, vault_update
from freq.core.vault_key_input import _VaultKeyReadDuty
from freq.core.vault_decrypt_input import _VaultDecryptReadDuty
from freq.services.setup_health import setup_marker_exists as _setup_marker_exists
from freq.services.setup_inputs import (
    _SetupInitDirectoryDuty,
    _SetupInitSecretFileDuty,
    _SetupInitVMContractDuty,
    _SetupDeviceMaterializationDuty,
    _SetupBootstrapLookupDuty,
    resolved_bootstrap_username,
    setup_secret_dir,
    toml_scalar,
    write_setup_secret,
    write_vm_contract,
)

_SETUP_DIRECTORY_DUTY_OMITTED = object()

# ── Constants ──────────────────────────────────────────────────────────────

SESSION_TIMEOUT_HOURS = 1
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_HOURS * 3600


def _load_users(cfg):
    """Resolve the user loader lazily to preserve auth/users import isolation."""
    from freq.modules.users import _load_users as load_users

    return load_users(cfg)


# ── Token Store (in-memory, cleared on restart) ───────────────────────────

_auth_tokens = {}  # token -> {user, role, ts, last_activity_ts}
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


def _trusted_proxy_cidrs() -> list:
    try:
        cfg = load_config()
        return getattr(cfg, "trusted_proxy_cidrs", None) or []
    except Exception:
        return []


def _peer_is_trusted_proxy(handler) -> bool:
    try:
        peer_ip = handler.client_address[0]
    except Exception:
        return False
    trusted = _trusted_proxy_cidrs()
    return bool(trusted) and any(_ip_in_cidr(peer_ip, c) for c in trusted)


def request_is_https(handler) -> bool:
    """Return True for direct TLS or trusted-proxy HTTPS requests."""
    import ssl as _ssl
    if isinstance(getattr(handler, "request", None), _ssl.SSLSocket):
        return True
    if not _peer_is_trusted_proxy(handler):
        return False
    proto = str(handler.headers.get("X-Forwarded-Proto", "") or "").split(",", 1)[0].strip().lower()
    return proto == "https"


def same_origin_or_absent(handler, *, require_present=False, is_https=None) -> bool:
    """Validate an Origin against the request scheme and Host authority."""
    origin = str(handler.headers.get("Origin", "") or "").strip()
    if not origin:
        return not require_present
    host = str(handler.headers.get("Host", "") or "").strip().lower()
    if not host:
        return False
    try:
        parsed = urlparse(origin)
    except Exception:
        return False
    expected_scheme = "https" if (request_is_https(handler) if is_https is None else is_https) else "http"
    return bool(
        parsed.scheme.lower() == expected_scheme
        and parsed.netloc.lower() == host
        and not parsed.username
        and not parsed.password
        and parsed.path == ""
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def send_security_headers(handler):
    """Send the shared application security-header policy.

    The dashboard is self-contained, so CSP never needs an off-box asset host.
    Runtime style writes still require ``unsafe-inline`` for styles; script
    execution remains restricted to same-origin assets.
    """
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("X-XSS-Protection", "1; mode=block")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    handler.send_header(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), usb=(), payment=(), "
        "accelerometer=(), gyroscope=(), magnetometer=(), interest-cohort=()",
    )
    handler.send_header(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'",
    )
    # HSTS is valid only for direct TLS or HTTPS asserted by a trusted proxy.
    # Plain-HTTP and spoofed forwarded-proto requests must never receive it.
    try:
        if request_is_https(handler):
            handler.send_header(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
    except Exception:
        pass


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


def _extract_session_token_and_source(handler) -> tuple[str, str]:
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
        return auth_header[7:], "bearer"
    cookie_header = handler.headers.get("Cookie", "")
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("freq_session="):
            return part[len("freq_session="):], "cookie"
    return "", ""


def _extract_session_token(handler) -> str:
    token, _source = _extract_session_token_and_source(handler)
    return token


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


def _session_touch_requested(handler) -> bool:
    try:
        return str(handler.headers.get("X-Freq-User-Activity", "")).lower() in {"1", "true", "yes"}
    except Exception:
        return False


def _set_session_refresh_cookie(handler, token: str):
    try:
        handler._refresh_session_cookie = token
    except Exception:
        pass


def establish_session(handler, username: str, role: str) -> str:
    """Create a browser session and queue the response cookie on handler."""
    from freq.core.read_source_epoch import source_write

    with source_write():
        token = secrets.token_urlsafe(32)
        now = time.time()
        with _auth_lock:
            _auth_tokens[token] = {
                "user": username,
                "role": role,
                "ts": now,
                "last_activity_ts": now,
                "csrf_token": secrets.token_urlsafe(32),
            }
        _set_session_refresh_cookie(handler, token)
        return token


def setup_session_payload(handler, username, role="admin", **extra):
    """Create setup session and include the CSRF token setup.js needs."""
    token = establish_session(handler, username, role)
    csrf_token = ""
    with _auth_lock:
        csrf_token = (_auth_tokens.get(token) or {}).get("csrf_token", "")
    payload = {
        "ok": True,
        "user": username,
        "role": role,
        "session_started": True,
        "csrf_token": csrf_token,
        "auth_mode": "cookie",
    }
    payload.update(extra)
    return payload


def is_first_run():
    """Detect if this is the first run or if setup is incomplete.

    Returns True if no users exist — even if init markers are present.
    An init without dashboard users is incomplete: the operator cannot
    log in and would be stranded between "setup complete" and
    "invalid credentials". The setup wizard must remain available
    until at least one user exists.

    F9 of R-SECURITY-TRUST-AUDIT-20260413P: this function now fails
    CLOSED on exception. Pre-fix it returned True if _load_users
    raised, on the reasoning "safer to show setup wizard". That was
    wrong — fail-open meant a transient users.conf permission/IO
    error reopened the entire setup wizard surface to unauth callers,
    which combined with F2 (test-ssh SSRF) gave a real attack window.
    Fail-closed on read error is the safer posture: the setup wizard
    stays gated, the operator sees the failure via /api/setup/status
    or freq.log, and unsticks the wizard explicitly via
    /api/setup/reset (admin auth) once the underlying read is fixed.
    """
    cfg = load_config()

    # Users are the ultimate gate — no users means setup is incomplete
    # regardless of markers. This prevents the post-init dead-end where
    # .initialized exists but users.conf is empty.
    try:
        users = _load_users(cfg)
        if not users:
            return True
    except Exception as e:
        logger.error(
            f"_is_first_run: failed to check users — failing CLOSED to keep "
            f"setup endpoints gated: {e}"
        )
        return False  # Fail closed (F9): never re-open the wizard on a read error

    # If users exist, check markers to determine if setup completed
    if os.path.isfile(os.path.join(cfg.data_dir, "setup-complete")):
        return False
    if os.path.isfile(os.path.join(cfg.conf_dir, ".initialized")):
        return False
    if os.path.isfile(os.path.join(cfg.conf_dir, ".web-setup-complete")):
        return False

    # Users exist but no markers — treat as configured (user added manually)
    return False


def allow_setup_admin_window(handler):
    """Allow setup continuation after first admin creation, before markers.

    The first setup call creates users.conf, which intentionally makes
    is_first_run() false. Continuing setup after that point must be
    authenticated as the freshly-created admin, and only while no setup/init
    marker exists.
    """
    cfg = load_config()
    if _setup_marker_exists(cfg):
        handler._json_response({"error": "Setup wizard already used — run freq init to complete fleet deployment"}, 403)
        return False
    role, err = check_session_role(handler, "admin")
    if err:
        handler._json_response({"error": err}, 403)
        return False
    return True


def _setup_store_admin_password(cfg, username, password):
    """Store and verify setup admin password before users.conf changes."""
    pw_hash = hash_password(password)
    try:
        if not os.path.exists(cfg.vault_file):
            if not vault_init(cfg):
                return "Failed to initialize password vault"
        if not vault_set(cfg, "auth", f"password_{username}", pw_hash):
            return "Failed to store password in vault"
        if not vault_get(cfg, "auth", f"password_{username}"):
            return "Password storage verification failed"
    except MemoryError:
        raise
    except Exception as e:
        return str(e)
    return ""


def _setup_vault_host(setup_id):
    return f"setup:{setup_id}"


def _setup_contract_getter(cfg, setup_id):
    host = _setup_vault_host(setup_id)
    values = {key: value for entry_host, key, value in vault_list(cfg) if entry_host == host}
    return lambda key: values.get(key, "")


_SETUP_DEVICE_DUTY_OMITTED = object()


def write_setup_contract_credentials(cfg, secret_dir, contract, *, _duty=_SETUP_DEVICE_DUTY_OMITTED):
    if _duty is _SETUP_DEVICE_DUTY_OMITTED:
        from freq.core.read_source_epoch import source_write

        with source_write():
            if not (contract.get("owned_devices") or []):
                return ""
            getter = _setup_contract_getter(cfg, contract["setup_id"])
            requirements = {
                row["resource_id"]: row for row in contract.get("credential_requirements") or []
            }
            lines = []
            for device in contract.get("owned_devices") or []:
                resource_id = device.get("resource_id", "")
                requirement = requirements.get(resource_id) or {}
                kind = str(device.get("kind") or "").strip().lower()
                section = f"{kind}-{credential_vault_key(resource_id, 'section').split('_')[1]}"
                values = {}
                for field in requirement.get("allowed_fields") or []:
                    raw = getter(credential_vault_key(resource_id, field))
                    if raw:
                        values[field] = credential_runtime_value(field, raw)
                lines.extend(
                    [
                        f"[{section}]",
                        f"type = {toml_scalar(kind)}",
                        f"host = {toml_scalar(device.get('host', ''))}",
                        f"label = {toml_scalar(device.get('label', resource_id))}",
                        f"scope = {toml_scalar('lab' if device.get('placement') == 'lab' else 'core')}",
                    ]
                )
                if values.get("username"):
                    lines.append(f"user = {toml_scalar(values['username'])}")
                for field in ("bootstrap_mode", "tls_sha256", "trust_on_first_use"):
                    if values.get(field) not in (None, ""):
                        lines.append(f"{field} = {toml_scalar(values[field])}")
                if kind == "truenas" and values.get("api_key") and not any(
                    values.get(field) for field in ("password", "ssh_private_key")
                ):
                    lines.append("browser_probe_only = true")
                for field, suffix, toml_key in (
                    ("password", "password", "password_file"),
                    ("api_key", "api-key", "api_key_file"),
                    ("api_secret", "api-secret", "api_secret_file"),
                    ("ssh_private_key", "ssh-key", "ssh_key_file"),
                    ("sudo_password", "sudo-password", "sudo_password_file"),
                ):
                    if values.get(field):
                        value_path = write_setup_secret(secret_dir, f"{section}-{suffix}", values[field])
                        lines.append(f"{toml_key} = {toml_scalar(value_path)}")
                lines.append("")
            if not lines:
                return ""
            path = os.path.join(secret_dir, "device-credentials.toml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines).rstrip() + "\n")
            os.chmod(path, 0o600)
            return path
    if type(_duty) is not _SetupDeviceMaterializationDuty:
        raise SetupContractError('init_prepare_failed',
            'Setup device materialization is unavailable.', status=500)
    try:
        _duty.enter(cfg, secret_dir, contract)
        from freq.core.read_source_epoch import source_write
        _duty.gate_stage = 'construct-pending'
        _duty.gate = source_write()
    except BaseException as failure:
        _duty.remember(0, failure)
        raise _duty.failure from None

    def materialize():
        if not (contract.get("owned_devices") or []):
            return ""
        getter = _setup_contract_getter(cfg, contract["setup_id"])
        requirements = {
            row["resource_id"]: row for row in contract.get("credential_requirements") or []
        }
        lines = []
        for device in contract.get("owned_devices") or []:
            resource_id = device.get("resource_id", "")
            requirement = requirements.get(resource_id) or {}
            kind = str(device.get("kind") or "").strip().lower()
            section = f"{kind}-{credential_vault_key(resource_id, 'section').split('_')[1]}"
            values = {}
            for field in requirement.get("allowed_fields") or []:
                raw = getter(credential_vault_key(resource_id, field))
                if raw:
                    values[field] = credential_runtime_value(field, raw)
            lines.extend(
                [
                    f"[{section}]",
                    f"type = {toml_scalar(kind)}",
                    f"host = {toml_scalar(device.get('host', ''))}",
                    f"label = {toml_scalar(device.get('label', resource_id))}",
                    f"scope = {toml_scalar('lab' if device.get('placement') == 'lab' else 'core')}",
                ]
            )
            if values.get("username"):
                lines.append(f"user = {toml_scalar(values['username'])}")
            for field in ("bootstrap_mode", "tls_sha256", "trust_on_first_use"):
                if values.get(field) not in (None, ""):
                    lines.append(f"{field} = {toml_scalar(values[field])}")
            if kind == "truenas" and values.get("api_key") and not any(
                values.get(field) for field in ("password", "ssh_private_key")
            ):
                lines.append("browser_probe_only = true")
            for field, suffix, toml_key in (
                ("password", "password", "password_file"),
                ("api_key", "api-key", "api_key_file"),
                ("api_secret", "api-secret", "api_secret_file"),
                ("ssh_private_key", "ssh-key", "ssh_key_file"),
                ("sudo_password", "sudo-password", "sudo_password_file"),
            ):
                if values.get(field):
                    value_path = write_setup_secret(secret_dir, f"{section}-{suffix}", values[field])
                    lines.append(f"{toml_key} = {toml_scalar(value_path)}")
            lines.append("")
        if not lines:
            return ""
        path = os.path.join(secret_dir, "device-credentials.toml")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
        os.chmod(path, 0o600)
        return path

    _duty.gate_stage = _duty.entry_stage = 'pending'
    try:
        with _duty.gate:
            _duty.entry_stage = 'returned'
            _duty.body_stage = 'pending'
            try:
                _duty.result_path = materialize()
                _duty.result_stage = 'stored'
                _duty.body_stage = 'returned'
            except BaseException as failure:
                # Preserve original source context's body-error delivery.
                _duty.remember(1, failure)
                raise
    except BaseException as failure:
        _duty.remember(2, failure)
    else:
        _duty.gate_stage = 'returned'
    if _duty.failure is not None:
        raise _duty.failure from None
    _duty.stage = 'returned'
    return _duty.result_path


def setup_init_command_from_contract(cfg, request, contract, discovery, job_id, *, _directory_duty=_SETUP_DIRECTORY_DUTY_OMITTED):
    """Materialize internal-only adapters for the existing headless CLI."""
    if _directory_duty is _SETUP_DIRECTORY_DUTY_OMITTED:
        secret_dir = setup_secret_dir(cfg, job_id)
    else:
        if (type(_directory_duty) is not _SetupInitDirectoryDuty
                or _directory_duty.cfg is not cfg or _directory_duty.job_id != job_id):
            raise SetupContractError('init_prepare_failed',
                'Setup adapter acquisition is unavailable.', status=500)
        secret_dir = setup_secret_dir(cfg, job_id, _duty=_directory_duty)
        if (type(_directory_duty) is not _SetupInitDirectoryDuty
                or _directory_duty.cfg is not cfg or _directory_duty.job_id != job_id
                or _directory_duty.result_stage != 'stored'
                or _directory_duty.failure is not None
                or secret_dir is not _directory_duty.result_path):
            raise SetupContractError('init_prepare_failed',
                'Setup adapter acquisition is unavailable.', status=500)
        _directory_duty.caller_returned = True
    try:
        if _directory_duty is _SETUP_DIRECTORY_DUTY_OMITTED:
            service_file = write_setup_secret(
                secret_dir, "service-account-password", request["service_account"]["password"]
            )
        else:
            file_duty = _directory_duty.service_file
            if (type(file_duty) is not _SetupInitSecretFileDuty
                    or file_duty.directory is not _directory_duty
                    or file_duty.launch is not _directory_duty.launch
                    or file_duty.job is not _directory_duty.job
                    or file_duty.cfg is not cfg or file_duty.used is not False):
                raise SetupContractError('init_prepare_failed',
                    'Setup secret acquisition is unavailable.', status=500)
            service_file = write_setup_secret(
                secret_dir, "service-account-password", request["service_account"]["password"],
                _duty=file_duty)
            if (file_duty.result_stage != 'stored' or file_duty.failure is not None
                    or file_duty.result_path is not service_file
                    or file_duty.open_stage != 'returned' or file_duty.enter_stage != 'returned'
                    or file_duty.entered_handle is not file_duty.handle
                    or file_duty.body_stage != 'returned' or file_duty.exit_stage != 'returned'
                    or file_duty.mode_stage != 'returned'):
                raise SetupContractError('init_prepare_failed',
                    'Setup secret acquisition is unavailable.', status=500)
            file_duty.caller_returned = True
        if _directory_duty is _SETUP_DIRECTORY_DUTY_OMITTED:
            bootstrap_password = vault_get(
                cfg, _setup_vault_host(contract["setup_id"]), "bootstrap_password"
            )
            if not bootstrap_password:
                raise SetupContractError(
                    "bootstrap_secret_missing", "Bootstrap credentials expired; run discovery again.", status=409
                )
        else:
            lookup_duty = _directory_duty.bootstrap_lookup
            if (type(lookup_duty) is not _SetupBootstrapLookupDuty
                    or lookup_duty.directory is not _directory_duty
                    or lookup_duty.launch is not _directory_duty.launch
                    or lookup_duty.job is not _directory_duty.job
                    or lookup_duty.cfg is not cfg):
                raise SetupContractError('init_prepare_failed',
                    'Setup bootstrap acquisition is unavailable.', status=500)
            try:
                key_read = lookup_duty.key_read
                if (type(key_read) is not _VaultKeyReadDuty
                        or key_read.lookup is not lookup_duty
                        or key_read.directory is not _directory_duty
                        or key_read.launch is not lookup_duty.launch
                        or key_read.job is not lookup_duty.job
                        or key_read.cfg is not cfg or key_read.used is not False):
                    raise SetupContractError('init_prepare_failed',
                        'Setup bootstrap acquisition is unavailable.', status=500)
                decrypt_read = lookup_duty.decrypt_read
                if (type(decrypt_read) is not _VaultDecryptReadDuty
                        or decrypt_read.lookup is not lookup_duty
                        or decrypt_read.key_read is not key_read
                        or decrypt_read.directory is not _directory_duty
                        or decrypt_read.launch is not lookup_duty.launch
                        or decrypt_read.job is not lookup_duty.job
                        or decrypt_read.cfg is not cfg or decrypt_read.used is not False):
                    raise SetupContractError('init_prepare_failed',
                        'Setup bootstrap acquisition is unavailable.', status=500)
                lookup_duty.enter(cfg, contract)
                lookup_duty.requested_host = _setup_vault_host(contract["setup_id"])
                lookup_duty.stage = 'pending'
                bootstrap_password = vault_get(
                    cfg, lookup_duty.requested_host, "bootstrap_password", _key_read=key_read)
                lookup_duty.stage = 'returned'
                if not key_read.known():
                    key_read.refuse()
                if lookup_duty.failure is not None:
                    raise lookup_duty.failure from None
                if not bootstrap_password:
                    raise SetupContractError(
                        "bootstrap_secret_missing", "Bootstrap credentials expired; run discovery again.", status=409
                    )
                if not decrypt_read.known():
                    decrypt_read.refuse()
                lookup_duty.passed_empty_check = True
            except BaseException as failure:
                lookup_duty.remember(failure)
                raise lookup_duty.failure from None
        if _directory_duty is _SETUP_DIRECTORY_DUTY_OMITTED:
            bootstrap_file = write_setup_secret(secret_dir, "bootstrap-password", bootstrap_password)
        else:
            bootstrap_duty = _directory_duty.bootstrap_file
            if (type(bootstrap_duty) is not _SetupInitSecretFileDuty
                    or bootstrap_duty.directory is not _directory_duty
                    or bootstrap_duty.launch is not _directory_duty.launch
                    or bootstrap_duty.job is not _directory_duty.job
                    or bootstrap_duty.cfg is not cfg or bootstrap_duty.used is not False
                    or bootstrap_duty.name != 'bootstrap-password'):
                raise SetupContractError('init_prepare_failed',
                    'Setup bootstrap file acquisition is unavailable.', status=500)
            bootstrap_file = write_setup_secret(
                secret_dir, "bootstrap-password", bootstrap_password, _duty=bootstrap_duty)
            if (bootstrap_duty.result_stage != 'stored' or bootstrap_duty.failure is not None
                    or bootstrap_duty.result_path is not bootstrap_file
                    or bootstrap_duty.open_stage != 'returned' or bootstrap_duty.handle is None
                    or bootstrap_duty.enter_stage != 'returned'
                    or bootstrap_duty.entered_handle is not bootstrap_duty.handle
                    or bootstrap_duty.body_stage != 'returned' or bootstrap_duty.exit_stage != 'returned'
                    or bootstrap_duty.mode_stage != 'returned'):
                raise SetupContractError('init_prepare_failed',
                    'Setup bootstrap file acquisition is unavailable.', status=500)
            bootstrap_duty.caller_returned = True
        bootstrap_password = ""
        if _directory_duty is _SETUP_DIRECTORY_DUTY_OMITTED:
            vm_contract_file = write_vm_contract(secret_dir, contract)
        else:
            contract_duty = _directory_duty.vm_contract
            if (type(contract_duty) is not _SetupInitVMContractDuty
                    or contract_duty.directory is not _directory_duty
                    or contract_duty.launch is not _directory_duty.launch
                    or contract_duty.job is not _directory_duty.job
                    or contract_duty.cfg is not cfg or contract_duty.used is not False):
                raise SetupContractError('init_prepare_failed',
                    'Setup contract acquisition is unavailable.', status=500)
            vm_contract_file = write_vm_contract(secret_dir, contract, _duty=contract_duty)
            if (contract_duty.contract is not contract or contract_duty.format_stage != 'returned'
                    or contract_duty.result_stage != 'stored' or contract_duty.failure is not None
                    or contract_duty.result_path is not vm_contract_file
                    or contract_duty.open_stage != 'returned' or contract_duty.handle is None
                    or contract_duty.enter_stage != 'returned'
                    or contract_duty.entered_handle is not contract_duty.handle
                    or contract_duty.body_stage != 'returned' or contract_duty.exit_stage != 'returned'
                    or contract_duty.mode_stage != 'returned'):
                raise SetupContractError('init_prepare_failed',
                    'Setup contract acquisition is unavailable.', status=500)
            contract_duty.caller_returned = True
        if _directory_duty is _SETUP_DIRECTORY_DUTY_OMITTED:
            device_file = write_setup_contract_credentials(cfg, secret_dir, contract)
        else:
            device_duty = _directory_duty.device_credentials
            if (type(device_duty) is not _SetupDeviceMaterializationDuty
                    or device_duty.directory is not _directory_duty
                    or device_duty.launch is not _directory_duty.launch
                    or device_duty.job is not _directory_duty.job
                    or device_duty.cfg is not cfg or device_duty.used is not False):
                raise SetupContractError('init_prepare_failed',
                    'Setup device materialization is unavailable.', status=500)
            device_file = write_setup_contract_credentials(
                cfg, secret_dir, contract, _duty=device_duty)
            if (device_duty.contract is not contract or device_duty.stage != 'returned'
                    or device_duty.entry_stage != 'returned' or device_duty.gate_stage != 'returned'
                    or device_duty.body_stage != 'returned' or device_duty.result_stage != 'stored'
                    or device_duty.result_path is not device_file or device_duty.failure is not None):
                raise SetupContractError('init_prepare_failed',
                    'Setup device materialization is unavailable.', status=500)
            device_duty.caller_returned = True
        if _directory_duty is _SETUP_DIRECTORY_DUTY_OMITTED:
            pdm_file = write_setup_secret(secret_dir, "pdm-password", request.get("pdm_password", ""))
        else:
            pdm_duty = _directory_duty.pdm_file
            if (type(pdm_duty) is not _SetupInitSecretFileDuty
                    or pdm_duty.directory is not _directory_duty
                    or pdm_duty.launch is not _directory_duty.launch
                    or pdm_duty.job is not _directory_duty.job
                    or pdm_duty.cfg is not cfg or pdm_duty.used is not False
                    or pdm_duty.name != 'pdm-password'
                    or pdm_duty.launch.preparation.request is not request):
                raise SetupContractError('init_prepare_failed',
                    'Setup PDM acquisition is unavailable.', status=500)
            pdm_file = write_setup_secret(
                secret_dir, "pdm-password", request.get("pdm_password", ""), _duty=pdm_duty)
            known_empty = (pdm_duty.pdm_mode == 'skip' and pdm_duty.result_stage == 'empty'
                and pdm_duty.result_path == '' and pdm_duty.open_stage == 'unused'
                and pdm_duty.handle is None and pdm_duty.enter_stage == 'unused'
                and pdm_duty.body_stage == 'unused' and pdm_duty.exit_stage == 'unused'
                and pdm_duty.mode_stage == 'unused')
            known_file = (pdm_duty.pdm_mode == 'install' and pdm_duty.result_stage == 'stored'
                and pdm_duty.open_stage == 'returned' and pdm_duty.handle is not None
                and pdm_duty.enter_stage == 'returned' and pdm_duty.entered_handle is pdm_duty.handle
                and pdm_duty.body_stage == 'returned' and pdm_duty.exit_stage == 'returned'
                and pdm_duty.mode_stage == 'returned'
                and pdm_duty.result_path is pdm_duty.candidate_path)
            if (not (known_empty or known_file) or pdm_duty.failure is not None
                    or pdm_duty.result_path is not pdm_file
                    or pdm_duty.pdm_mode != request.get('pdm_mode')):
                raise SetupContractError('init_prepare_failed',
                    'Setup PDM acquisition is unavailable.', status=500)
            pdm_duty.caller_returned = True
        cluster = discovery.get("cluster") or {}
        nodes = cluster.get("nodes") or []
        node_hosts = [str(row.get("host") or "") for row in nodes if row.get("host")]
        node_names = [str(row.get("name") or row.get("host") or "") for row in nodes if row.get("host")]
        if not node_hosts:
            raise SetupContractError("stale_discovery", "Discovery has no PVE nodes.", "discovery_id", 409)
        code = "import sys; from freq.cli import main; raise SystemExit(main(sys.argv[1:]))"
        cmd = [
            sys.executable, "-c", code, "--yes", "init", "--headless",
            "--password-file", service_file,
            "--bootstrap-user", resolved_bootstrap_username(discovery),
            "--bootstrap-password-file", bootstrap_file,
            "--service-account", request["service_account"]["username"],
            "--pve-nodes", ",".join(node_hosts),
            "--pve-node-names", ",".join(node_names),
            "--cluster-name", str(cluster.get("name") or "pve"),
            "--ssh-mode", request["ssh_mode"],
            "--vm-contract", vm_contract_file,
        ]
        if device_file:
            cmd.extend(["--device-credentials", device_file])
        if request["pdm_mode"] == "install":
            cmd.append("--install-pdm")
            cmd.extend(["--pdm-pass", pdm_file])
        else:
            cmd.append("--skip-pdm")
        env = os.environ.copy()
        env.update({"FREQ_DIR": cfg.install_dir, "FREQ_WEB_INIT": "1", "PYTHONUNBUFFERED": "1"})
        if os.geteuid() != 0:
            cmd = [
                "sudo", "-n", "env", f"FREQ_DIR={cfg.install_dir}",
                "FREQ_WEB_INIT=1", "PYTHONUNBUFFERED=1",
            ] + cmd
        return cmd, env, secret_dir
    except Exception as body_failure:
        if _directory_duty is not _SETUP_DIRECTORY_DUTY_OMITTED:
            # Required preparation retains uncertain acquisitions on its original
            # job. A failed body supplies no directory-removal authority.
            _directory_duty.remember(body_failure)
            raise _directory_duty.failure from None
        cleanup_failure = None
        try:
            shutil.rmtree(secret_dir, ignore_errors=True)
        except BaseException as failure:
            cleanup_failure = failure
        first = body_failure
        if cleanup_failure is not None and (
                not issubclass(type(cleanup_failure), Exception)
                or not issubclass(type(first), MemoryError)
                and issubclass(type(cleanup_failure), MemoryError)):
            first = cleanup_failure
        raise first from None


def _clear_setup_contract_credentials(cfg, contract):
    """Remove every setup-device value named by a durable contract."""
    if not contract:
        return
    host = _setup_vault_host(contract.get("setup_id", ""))
    existing = {key for entry_host, key, _value in vault_list(cfg) if entry_host == host}
    updates = {key: None for key in contract_credential_keys(contract) if key in existing}
    if updates and not vault_update(cfg, host, updates):
        raise OSError("setup credential cleanup failed")
    remaining = {key for entry_host, key, _value in vault_list(cfg) if entry_host == host}
    if remaining.intersection(updates):
        raise OSError("setup credential cleanup failed")


def _retire_setup_contract(cfg, contract):
    """Remove contract-owned credentials before clearing durable selection state."""
    _clear_setup_contract_credentials(cfg, contract)
    clear_setup_contract(cfg)


def _delete_setup_vault_namespace(cfg, setup_id):
    host = _setup_vault_host(setup_id)
    keys = {key for entry_host, key, _value in vault_list(cfg) if entry_host == host}
    if keys and not vault_update(cfg, host, {key: None for key in keys}):
        raise OSError("setup secret cleanup failed")
    remaining = {key for entry_host, key, _value in vault_list(cfg) if entry_host == host}
    if remaining:
        raise OSError("setup secret cleanup failed")


def _cleanup_expired_setup(cfg):
    """Remove orphaned setup secrets when TTL expiry is observed."""
    raw_state = {}
    try:
        with open(setup_state_path(cfg), encoding="utf-8") as handle:
            raw_state = json.load(handle)
    except (OSError, ValueError, TypeError):
        pass
    if load_setup_state(cfg):
        return False
    contract = load_setup_contract(cfg)
    setup_id = ""
    if isinstance(raw_state, dict) and raw_state.get("schema") == ZERO_STATE_WEB_SCHEMA:
        setup_id = str(raw_state.get("setup_id") or "")
    if not setup_id and contract:
        setup_id = str(contract.get("setup_id") or "")
    if setup_id and len(setup_id) <= 256:
        _delete_setup_vault_namespace(cfg, setup_id)
    if contract:
        clear_setup_contract(cfg)
    return bool(setup_id or contract)


def _bg_cleanup_expired_setup():
    try:
        _cleanup_expired_setup(load_config())
    except Exception as exc:
        logger.warn(f"setup_expiry_cleanup_failed: {exc}")


def _observe_setup_state(cfg):
    """Load setup state while making expiry cleanup part of observation."""
    _cleanup_expired_setup(cfg)
    return load_setup_state(cfg)


def maybe_send_session_refresh_cookie(handler):
    token = getattr(handler, "_refresh_session_cookie", "")
    if not token:
        return
    secure_flag = "; Secure" if request_is_https(handler) else ""
    handler.send_header(
        "Set-Cookie",
        f"freq_session={token}; HttpOnly; SameSite=Strict; Path=/; "
        f"Max-Age={SESSION_TIMEOUT_SECONDS}{secure_flag}",
    )


def _lookup_session(token: str, touch: bool = False, handler=None):
    """Return the session dict for a token, or None on miss/expiry.
    Side-effect: removes expired entries from the in-memory store."""
    if not token:
        return None
    now = time.time()
    with _auth_lock:
        session = _auth_tokens.get(token)
        if not session:
            return None
        last_activity = session.get("last_activity_ts", session.get("ts", now))
        if now - last_activity > SESSION_TIMEOUT_SECONDS:
            del _auth_tokens[token]
            return None
        if touch:
            session["last_activity_ts"] = now
            if handler is not None:
                _set_session_refresh_cookie(handler, token)
        return session



def capture_cluster_session(handler):
    """Retain the original session identity for the dedicated cluster read.

    The token stays private and must never be logged or serialized. This grant
    does not authorize a provider operation; routes separately resolve targets.
    """
    token = _extract_session_token(handler)
    with _auth_lock:
        session = _auth_tokens.get(token)
        if type(session) is not dict:
            return None
        role, user = session.get("role"), session.get("user")
        if role not in ("viewer", "operator", "admin", "protected"):
            return None
        last = session.get("last_activity_ts", session.get("ts"))
        if type(last) not in (int, float) or not 0 <= time.time() - last < SESSION_TIMEOUT_SECONDS:
            return None
        return (token, session, role, user)


def admit_cluster_publication(handler, grant, deadline, *, service, revision):
    """Linearize disclosure before socket I/O, without holding auth during I/O.

    Logout after this point cannot retract admitted bytes. Original frontend
    lifetime retirement must reject those bytes if they arrive after logout.
    """
    if type(grant) is not tuple or len(grant) != 4:
        return False
    from freq.services.cluster_service import SuppliedClusterService
    if type(service) is not SuppliedClusterService or type(revision) is not str:
        return False
    token, original, role, user = grant
    with _auth_lock:
        if getattr(handler, "_cluster_publication_admitted", False):
            return False
        current = _auth_tokens.get(token)
        if current is not original or type(current) is not dict:
            return False
        last = current.get("last_activity_ts", current.get("ts"))
        if (current.get("role") != role or current.get("user") != user
                or role not in ("viewer", "operator", "admin", "protected")
                or type(last) not in (int, float)
                or not 0 <= time.time() - last < SESSION_TIMEOUT_SECONDS
                or not time.monotonic() < deadline):
            return False
        with service.lock:
            if service._revision != revision:
                return False
            handler._cluster_publication_admitted = True
            return True

def current_user(handler) -> str:
    """Return the username for the request's session, or "" if none.

    Used by handlers that need to bind ownership to a created resource
    (e.g. terminal session creator pinning, F8 of
    R-SECURITY-TRUST-AUDIT-20260413P) WITHOUT also enforcing a
    role minimum — the role check is the caller's job.
    """
    token = _extract_session_token(handler)
    session = _lookup_session(token, touch=_session_touch_requested(handler), handler=handler)
    return session["user"] if session else ""


def current_csrf_token(handler) -> str:
    token = _extract_session_token(handler)
    session = _lookup_session(token, touch=False, handler=handler)
    return session.get("csrf_token", "") if session else ""


def check_csrf(handler) -> tuple[bool, str]:
    """Require CSRF token for unsafe cookie-authenticated API requests."""
    token, source = _extract_session_token_and_source(handler)
    if source != "cookie":
        return True, ""
    session = _lookup_session(token, touch=False, handler=handler)
    if not session:
        return False, "Session expired or invalid"
    expected = session.get("csrf_token", "")
    supplied = str(handler.headers.get("X-Freq-CSRF", "") or "")
    if not expected or not secrets.compare_digest(expected, supplied):
        return False, "CSRF token required"
    return True, ""


def check_session_role(handler, min_role="operator"):
    """Check if the request has a valid session with sufficient role.

    Role hierarchy: viewer < operator < admin.
    Returns (role_str, None) if ok, or (None, error_str) if blocked.
    """
    token, source = _extract_session_token_and_source(handler)
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
    session = _lookup_session(token, touch=_session_touch_requested(handler), handler=handler)
    if not session:
        return None, "Session expired or invalid"
    role_order = {"viewer": 0, "operator": 1, "admin": 2, "protected": 3}
    if role_order.get(session["role"], 0) < role_order.get(min_role, 1):
        return None, f"Requires {min_role} role (you are {session['role']})"
    try:
        handler._session_user = session["user"]
        handler._session_role = session["role"]
        handler._session_auth_source = source
        handler._session_csrf_token = session.get("csrf_token", "")
    except Exception:
        pass
    return session["role"], None


# ── Handler Functions (called from serve.py route dispatch) ───────────────


def handle_auth_login(handler):
    """POST /api/auth/login — authenticate user."""
    # T-7 of R-SECURITY-ARCH-DEBT-20260413U: resolve the real client IP
    # via trusted-proxy X-Forwarded-For handling. Default-deny: if
    # trusted_proxy_cidrs is empty the resolver returns the peer IP
    # unchanged (legacy direct-serve behavior).
    client_ip = resolve_client_ip(handler)

    if handler.command != "POST":
        handler._json_response({"error": "Use POST with JSON body for login"}, 405)
        return
    if not request_is_https(handler) or not same_origin_or_absent(
        handler, require_present=True, is_https=True
    ):
        handler._json_response({"error": "Matching HTTPS Origin header required"}, 403)
        return
    try:
        body = handler._request_body()
        username = body.get("username", "").strip().lower()
        password = body.get("password", "")
    except MemoryError:
        raise
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
    except MemoryError:
        raise
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
        except MemoryError:
            raise
        except Exception as e:
            logger.warn(f"vault write failed for auth: {e}")

    record_login_attempt(client_ip, True, username)

    token = establish_session(handler, username, user["role"])
    # Set auth cookie for SSE and cookie-based auth (HttpOnly, SameSite=Strict)
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    # Add Secure flag only when THIS request arrived over TLS. Setting Secure
    # based on tls_cert config is wrong: if the dashboard has tls_cert set but
    # the client talked to it over HTTP (e.g. TLS wrap failed, or reverse proxy),
    # the Secure cookie is dropped by the client and session persistence breaks.
    secure_flag = "; Secure" if request_is_https(handler) else ""
    handler.send_header("Set-Cookie",
                        f"freq_session={token}; HttpOnly; SameSite=Strict; Path=/; "
                        f"Max-Age={SESSION_TIMEOUT_SECONDS}{secure_flag}")
    # M-BLUETEAM-SECURITY-HARDENING-20260413AJ: reflected-origin ACAO
    # dropped on the auth surface too. The login endpoint is the most
    # sensitive cross-origin target in the app and must stay strictly
    # same-origin. The shared response policy therefore sends no ACAO.
    send_security_headers(handler)
    import json as _json
    csrf_token = ""
    with _auth_lock:
        csrf_token = (_auth_tokens.get(token) or {}).get("csrf_token", "")
    body = _json.dumps(
        {
            "ok": True,
            "token": token,
            "csrf_token": csrf_token,
            "auth_mode": "cookie",
            "user": username,
            "role": user["role"],
        }
    ).encode()
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def handle_auth_logout(handler):
    """POST /api/auth/logout — invalidate session and clear cookie."""
    handler.close_connection = True
    if handler.command != "POST":
        handler._json_response({"error": "Use POST for logout"}, 405)
        return
    if not request_is_https(handler) or not same_origin_or_absent(
        handler, require_present=True, is_https=True
    ):
        handler._json_response({"error": "Matching HTTPS Origin header required"}, 403)
        return
    token = _extract_session_token(handler)

    if token:
        from freq.services.cluster_service import SuppliedClusterService
        from freq.core.read_source_epoch import source_write
        with source_write(), _auth_lock:
            retired = _auth_tokens.pop(token, None)
            service = getattr(getattr(handler, "server", None), "cluster_report_service", None)
            if retired is not None and type(service) is SuppliedClusterService:
                service.references.retire_session(retired)

    # Clear cookie by setting Max-Age=0. Mirror the same Secure flag the
    # login path applies (auth.py:212-214) so strict cookie auditors and
    # any clients enforcing Secure-flag symmetry get the matching directive.
    # Browsers honor Max-Age=0 regardless of Secure, so this is correctness
    # rather than functional — F10 in R-SECURITY-TRUST-AUDIT-20260413P.
    secure_flag = "; Secure" if request_is_https(handler) else ""
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Connection", "close")
    send_security_headers(handler)
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
    session = _lookup_session(token, touch=_session_touch_requested(handler), handler=handler)
    if not session:
        handler._json_response({"valid": False})
        return
    now = time.time()
    issued = session.get("ts", now)
    age = max(0, int(now - issued))
    idle = max(0, int(now - session.get("last_activity_ts", issued)))
    ttl = max(0, SESSION_TIMEOUT_SECONDS - idle)
    handler._json_response(
        {
            "valid": True,
            "user": session["user"],
            "role": session["role"],
            "session_age_s": age,
            "session_idle_s": idle,
            "session_ttl_s": ttl,
            "session_timeout_s": SESSION_TIMEOUT_SECONDS,
            "csrf_token": session.get("csrf_token", ""),
            "auth_mode": "cookie",
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
    except MemoryError:
        raise
    except Exception as e:
        logger.warn(f"api_auth: failed to parse password change body: {e}")
        current_password = ""
        new_password = ""

    session = _lookup_session(token, touch=_session_touch_requested(handler), handler=handler)
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
    except MemoryError:
        raise
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
    except MemoryError:
        raise
    except Exception as e:
        logger.error(f"password change failed for {username}: {e}")
        handler._json_response({"error": "Failed to update password"}, 500)
        return

    # T-2: purge every OTHER session for this user. The caller's
    # current token stays so their in-flight browser tab keeps working.
    purged = 0
    from freq.core.read_source_epoch import source_write
    with source_write(), _auth_lock:
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


# Original read-only Cluster pilot auth integration.
# This source is not installed or an enabled route. Legacy auth above is frozen.
# Actual startup/currentness/admission/HTTP joins remain Rick-owned.
class _ClusterPilotAuthRefused(Exception):
    """Fixed original auth error schema; never carries a password/hash/cfg."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.payload = {"error": message}


def _cluster_pilot_direct_tls(handler):
    """Selected pilot accepts only its actual TLS socket, never forwarded headers."""
    import ssl

    return isinstance(getattr(handler, "request", None), ssl.SSLSocket)


def _cluster_pilot_installation(handler):
    """Resolve only the original constructor-retained installation.

    An exact type check is a refusal filter, not native resource authority. The
    real owner's begin_auth/auth_current must validate its retained installation
    and lease. A request dictionary, cfg flag or callback cannot issue either.
    Missing implementation refuses without falling through to legacy auth.
    """
    try:
        from freq.services.cluster_pilot_startup import OriginalPilotInstallation
    except ImportError:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable") from None
    installation = getattr(getattr(handler, "server", None),
                           "_cluster_pilot_installation", None)
    if type(installation) is not OriginalPilotInstallation:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")
    return installation


def _cluster_pilot_login_rate(handler, installation):
    """Fixed retained component only; missing actual broker/owner refuses."""
    try:
        from freq.services.pilot_login_rate import OriginalPilotLoginRate
        rate = installation._login_rate
        if (type(rate) is not OriginalPilotLoginRate or
                rate._installation is not installation or
                _cluster_pilot_installation(handler) is not installation):
            raise ValueError("unavailable")
        return rate
    except Exception:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable") from None


def _cluster_pilot_rate_call(rate, operation, handler, username):
    """Fixed calls only; ordinary refusal becomes 503, controls propagate."""
    try:
        if operation == "check":
            return rate.check(handler, username)
        if operation == "record_failure":
            return rate.record_failure(handler, username)
        raise ValueError("unavailable")
    except Exception:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable") from None


def _cluster_pilot_readonly_password(handler, installation):
    """Prepare a verified original lease; does not mint/publish a session.

    Only the original server may call this as part of its fixed login dispatch.
    On successful return that SAME retained lease remains outstanding: the
    original caller must final-admit it and retire_auth in its own finally.
    Returned fields/identity alone cannot authorize session insertion or bytes.
    Every failure retires an acquired lease once. An uncertain retire remains
    an original owner duty; timeout is never confirmation of settlement.

    begin_auth derives its end from the original native request record, never
    from a public caller value. This helper does not extend or renew that end.

    This selected graph performs no load_config/_load_users/vault write/setup,
    service fallback or password migration. Native configured-user/service-user
    exclusion/Vault READ semantics belong to begin_auth in the actual owner.
    """
    if handler.command != "POST":
        raise _ClusterPilotAuthRefused(405, "Use POST with JSON body for login")
    if not _cluster_pilot_direct_tls(handler) or not same_origin_or_absent(
            handler, require_present=True, is_https=True):
        raise _ClusterPilotAuthRefused(403, "Matching HTTPS Origin header required")
    if _cluster_pilot_installation(handler) is not installation:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")

    try:
        body = handler._request_body()
        username = body.get("username", "").strip().lower()
        password = body.get("password", "")
        if type(username) is not str or type(password) is not str:
            raise ValueError("invalid body field types")
    except Exception:
        raise _ClusterPilotAuthRefused(400, "Invalid request body") from None
    if not username or not password:
        raise _ClusterPilotAuthRefused(400, "Username and password required")
    # Same original stores, original request end and preallocated once duty.
    rate = _cluster_pilot_login_rate(handler, installation)
    if _cluster_pilot_rate_call(rate, "check", handler, username) is not True:
        raise _ClusterPilotAuthRefused(
            429, "Too many login attempts. Try again in 5 minutes.")

    lease = None
    transferred = False
    original_error = None
    try:
        try:
            lease = installation.begin_auth(handler, username)
        except Exception:
            raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable") from None
        if lease is None:
            _cluster_pilot_rate_call(rate, "record_failure", handler, username)
            raise _ClusterPilotAuthRefused(401, "Invalid credentials")
        if installation.auth_current(lease) is not True:
            raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")
        # These are read from the SAME owner-retained lease only after its
        # native configured-users/hash read and owner-current admission.
        if (type(lease.original_user) is not str or lease.original_user != username
                or lease.role not in ("viewer", "operator", "admin", "protected")):
            _cluster_pilot_rate_call(rate, "record_failure", handler, username)
            raise _ClusterPilotAuthRefused(401, "Invalid credentials")
        # The fixed original lease invokes original verify_password internally
        # outside admission gates, stores its outcome privately, and checks its
        # own retained shortened request end/currentness. No copied hash or
        # caller-supplied verification predicate can mint that private outcome.
        verified = lease.verify_password(password)
        if installation.auth_current(lease) is not True:
            raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")
        if verified is not True:
            _cluster_pilot_rate_call(rate, "record_failure", handler, username)
            raise _ClusterPilotAuthRefused(401, "Invalid credentials")
        # No legacy-SHA migration: original verification remains, all write
        # repair/init/update paths stay outside this read-only pilot graph.
        # Success bucket clearing, session creation and HTTP disclosure must
        # occur only through the original final admission, still unfinished.
        transferred = True
        return lease
    except BaseException as original_failure:
        original_error = original_failure
        raise
    finally:
        # Drop local references; Python assignment does not erase string memory.
        password = ""
        if lease is not None and not transferred:
            try:
                installation.retire_auth(lease)
            except BaseException as cleanup:
                # Preserve the first genuine control. A cleanup control must
                # not disappear behind an earlier ordinary auth refusal.
                # Actual unsettled duties remain retained by the owner.
                if original_error is None or (isinstance(original_error, Exception)
                                             and not isinstance(cleanup, Exception)):
                    raise


def handle_cluster_pilot_auth_login(handler):
    """Selected original POST login preparation and final owner admission.

    The original owner consumes admission/response duty and retains the exact
    response. Its fixed writer validates original request/response identity and
    once-write state before socket IO outside the gates. This wrapper never
    accepts a response/commit callback. Missing real operations refuse.
    """
    installation = _cluster_pilot_installation(handler)
    lease = _cluster_pilot_readonly_password(handler, installation)
    original_error = None
    try:
        response = installation.admit_login(handler, lease)
        if response is None:
            raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")
        return _cluster_pilot_write_admitted(handler, installation, response)
    except BaseException as original_failure:
        original_error = original_failure
        raise
    finally:
        try:
            installation.retire_auth(lease)
        except BaseException as cleanup:
            # Keep an original control; propagate a cleanup control over an
            # ordinary admission failure. Duties stay with the same owner;
            # this wrapper never appends a second HTTP response.
            if original_error is None or (isinstance(original_error, Exception)
                                         and not isinstance(cleanup, Exception)):
                raise


def handle_cluster_pilot_auth_verify(handler):
    """Selected GET verify; original owner final-admits original session only.

    The owner retains original token/cookie extraction, explicit activity touch,
    idle timeout and exact session/CSRF payload, under its fixed ordered final
    admission. Do not use a caller-provided session dict or legacy auth success
    as a substitute for that native original owner transaction.
    """
    if handler.command != "GET":
        raise _ClusterPilotAuthRefused(405, "Use GET for session verification")
    if not _cluster_pilot_direct_tls(handler) or not same_origin_or_absent(
            handler, require_present=False, is_https=True):
        raise _ClusterPilotAuthRefused(403, "Matching HTTPS Origin header required")
    installation = _cluster_pilot_installation(handler)
    response = installation.admit_verify(handler)
    if response is None:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")
    return _cluster_pilot_write_admitted(handler, installation, response)


def handle_cluster_pilot_auth_logout(handler):
    """Selected POST logout; retire actual session AND observed references.

    Exact original cookie/Bearer/CSRF checks, session removal, original installed
    service reference retirement and response-duty consumption belong to the
    original owner's INSTALLATION -> AUTH -> REFERENCES transaction. Never
    remove the session first then look up a supplied service or emit success
    while reference retirement is uncertain. Socket writes happen afterward.
    """
    if handler.command != "POST":
        raise _ClusterPilotAuthRefused(405, "Use POST for logout")
    if not _cluster_pilot_direct_tls(handler) or not same_origin_or_absent(
            handler, require_present=True, is_https=True):
        raise _ClusterPilotAuthRefused(403, "Matching HTTPS Origin header required")
    installation = _cluster_pilot_installation(handler)
    response = installation.admit_logout(handler)
    if response is None:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")
    return _cluster_pilot_write_admitted(handler, installation, response)


def _cluster_pilot_write_admitted(handler, installation, response):
    """Emit ONLY through the same original owner and its fixed native writer.

    Type checks filter mistakes, never mint original response authority. The
    writer must additionally validate retained handler/request/response identity
    and spent write duty; a copied immutable frame is not an alternate writer.
    Any partial write closes the connection. The original dispatcher must not
    append an error/status after admission or a failed attempted write.
    """
    try:
        from freq.services.cluster_pilot_http import OriginalPilotResponse
    except ImportError:
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable") from None
    if (type(response) is not OriginalPilotResponse
            or _cluster_pilot_installation(handler) is not installation):
        raise _ClusterPilotAuthRefused(503, "Cluster authentication unavailable")
    return installation.write_admitted_response(handler, response)
