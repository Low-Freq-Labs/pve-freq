<!-- INTERNAL — Not for public distribution -->

# ULTIMATE ATOMIC AUDIT — v3.0.0 Overhaul Execution Plan

**Date:** April 2, 2026
**Author:** Morty (20-agent audit synthesis)
**Rule:** This document is the plan. A FRESH WINDOW executes it. No guessing.

---

## HOW TO USE THIS DOCUMENT

Each fix specifies:
- **File** — exact path
- **Line** — exact line number(s) in the codebase as of commit `8648d7a`
- **Current** — what the code looks like now
- **Change** — exactly what to do
- **Why** — the problem being solved
- **Verify** — how to confirm the fix worked

Execute phases in order. Commit after each phase. Deploy after Phase 0.

---

## PHASE 0: SECURITY HARDENING

**Timeline:** 1-2 days. Non-negotiable. Do first.
**Commit message prefix:** `security:`

### 0.1 — Fix Auth Bypass (CRITICAL)

**File:** `freq/modules/serve.py`
**Lines:** 1282-1302
**Current:** `_check_session_role()` returns `"admin", None` when no token is provided (line 1292).
**Change:** Replace the no-token fallback:
```python
# REMOVE this block (lines 1290-1292):
if not token:
    return "admin", None

# REPLACE with:
if not token:
    return None, "Authentication required"
```
**Why:** Any unauthenticated request gets admin access. This is the #1 vulnerability.
**Verify:** `curl http://localhost:8888/api/admin/fleet-boundaries` should return `{"error": "Authentication required"}`, not data.

### 0.2 — Implement `_request_body()` Method

**File:** `freq/modules/serve.py`
**Where:** Add as a method on `FreqHandler` class (near line 7335, alongside `_json_response`)
**Current:** Line 3111 calls `self._request_body()` which doesn't exist. Login always falls back to GET params.
**Change:** Add this method to `FreqHandler`:
```python
def _request_body(self):
    """Read and parse JSON request body."""
    length = int(self.headers.get("Content-Length", 0))
    if length <= 0:
        return {}
    if length > 1_000_000:  # 1MB limit
        return {}
    raw = self.rfile.read(length)
    return json.loads(raw)
```
Then update `_serve_auth_login` (line 3106-3120) to properly use POST body and STOP falling back to query params for credentials:
```python
# Lines 3106-3120: Replace the entire credential extraction block
if self.command == "POST":
    try:
        body = self._request_body()
        username = body.get("username", "").strip().lower()
        password = body.get("password", "")
    except Exception:
        self._json_response({"error": "Invalid request body"}, 400)
        return
else:
    # GET login is no longer supported — credentials must be POST
    self._json_response({"error": "Use POST with JSON body for login"}, 405)
    return
```
**JS change:** Update `app.js` login fetch to send POST with JSON body instead of query params. Find the login fetch call (search for `API.AUTH_LOGIN`) and change to:
```javascript
fetch(API.AUTH_LOGIN, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({username: u, password: p})
})
```
**Why:** Credentials sent as GET params appear in logs, browser history, and referer headers.
**Verify:** Login via dashboard still works. `curl -X GET .../api/auth/login?username=x&password=y` returns 405.

### 0.3 — Fix Password Hashing

**File:** `freq/modules/serve.py`
**Lines:** 3150, 6562, 6623
**Current:** `hashlib.sha256(password.encode()).hexdigest()` — no salt, no iterations.
**Change:** Create a helper (near line 1280):
```python
import secrets

def _hash_password(password: str, salt: str = None) -> str:
    """Hash password with PBKDF2-SHA256 + per-user salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return f"{salt}${dk.hex()}"

def _verify_password(password: str, stored: str) -> bool:
    """Verify password against stored hash."""
    if '$' not in stored:
        # Legacy SHA256 hash — verify and signal migration needed
        return hashlib.sha256(password.encode()).hexdigest() == stored
    salt, _ = stored.split('$', 1)
    return _hash_password(password, salt) == stored
```
Replace all 3 occurrences:
- Line 3150: `pw_hash = _hash_password(password)`
- Line 6562: Use `_verify_password(password, stored_hash)` instead of `==` comparison
- Line 6623: `pw_hash = _hash_password(new_password)`

Handle migration: `_verify_password` accepts old SHA256 hashes. On successful login with old hash, re-hash with new scheme and save.
**Why:** SHA256 without salt is rainbow-table vulnerable.
**Verify:** Existing users can still log in. New passwords use salt. Check vault entry format has `$` separator.

### 0.4 — Add Auth to Vault Endpoints

**File:** `freq/api/secure.py`
**Lines:** 28, 39, 54
**Current:** `handle_vault`, `handle_vault_set`, `handle_vault_delete` have ZERO auth checks.
**Change:** Add to the top of each function (import `_check_session_role` from serve.py at top of file):
```python
from freq.modules.serve import _check_session_role

def handle_vault(handler):
    role, err = _check_session_role(handler, "operator")
    if err:
        json_response(handler, {"error": err}, 403); return
    # ... rest of function

def handle_vault_set(handler):
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return
    # ... rest of function

def handle_vault_delete(handler):
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403); return
    # ... rest of function
```
**Why:** Anyone on the network can read/write/delete secrets without authentication.
**Verify:** `curl http://localhost:8888/api/vault` without token returns 403.

### 0.5 — Fix CORS Headers

**File:** `freq/modules/serve.py`
**Lines:** 2952, 3485, 6647, 7340
**Current:** `self.send_header("Access-Control-Allow-Origin", "*")` on all JSON responses.
**Change:** In `_json_response` (line 7340), replace `"*"` with the request's Origin header if it matches the dashboard, otherwise omit:
```python
def _json_response(self, data, status=200):
    body = json.dumps(data).encode()
    self.send_response(status)
    self.send_header("Content-Type", "application/json")
    # Only allow same-origin requests
    origin = self.headers.get("Origin", "")
    if origin:
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("X-Frame-Options", "DENY")
    self.end_headers()
    self.wfile.write(body)
```
Remove the standalone CORS headers at lines 2952, 3485, 6647 (they're redundant if `_json_response` handles it).
**Why:** Wildcard CORS enables cross-site request forgery from any website.
**Verify:** Browser console shows no CORS errors on dashboard. Cross-origin requests from other domains are blocked.

### 0.6 — Add Rate Limiting on Login

**File:** `freq/modules/serve.py`
**Where:** Add before `_serve_auth_login` (line 6536)
**Change:** Add a rate limiter:
```python
_login_attempts = {}  # {ip: [(timestamp, success_bool), ...]}
_login_lock = threading.Lock()

def _check_rate_limit(ip: str) -> bool:
    """Return True if login allowed, False if rate-limited."""
    now = time.time()
    window = 300  # 5 minutes
    max_failures = 10
    with _login_lock:
        attempts = _login_attempts.get(ip, [])
        # Clean old entries
        attempts = [(t, s) for t, s in attempts if now - t < window]
        _login_attempts[ip] = attempts
        failures = sum(1 for t, s in attempts if not s)
        return failures < max_failures

def _record_login_attempt(ip: str, success: bool):
    with _login_lock:
        if ip not in _login_attempts:
            _login_attempts[ip] = []
        _login_attempts[ip].append((time.time(), success))
```
At the top of `_serve_auth_login` (line 6536), add:
```python
client_ip = self.client_address[0]
if not _check_rate_limit(client_ip):
    self._json_response({"error": "Too many login attempts. Try again in 5 minutes."}, 429)
    return
```
After successful/failed login, call `_record_login_attempt(client_ip, True/False)`.
**Why:** Zero rate limiting allows unlimited brute-force attempts.
**Verify:** After 10 failed logins from same IP, 11th attempt returns 429.

### 0.7 — Add Security Headers

**File:** `freq/modules/serve.py`
**Lines:** 7335-7342 (`_json_response`), 3791-3806 (`_serve_app`)
**Change:** Add to `_serve_app` (HTML responses):
```python
self.send_header("X-Content-Type-Options", "nosniff")
self.send_header("X-Frame-Options", "DENY")
self.send_header("X-XSS-Protection", "1; mode=block")
self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
```
The `_json_response` changes are covered in 0.5 above.
**Why:** Missing headers enable clickjacking, MIME sniffing, and XSS.
**Verify:** Response headers visible in browser devtools.

### 0.8 — Move Tokens to Authorization Header

**File:** `freq/modules/serve.py` — line 1288-1289
**File:** `freq/data/web/js/app.js` — all `fetch()` calls that include `token=`
**Change in serve.py:** Update `_check_session_role` to read from header first:
```python
# Replace line 1288-1289:
params = parse_qs(urlparse(handler.path).query)
token = params.get("token", [""])[0]

# With:
token = ""
auth_header = handler.headers.get("Authorization", "")
if auth_header.startswith("Bearer "):
    token = auth_header[7:]
if not token:
    # Fallback to query param (deprecation path)
    params = parse_qs(urlparse(handler.path).query)
    token = params.get("token", [""])[0]
```
**Change in app.js:** Create a helper function and update all fetch calls:
```javascript
function _authFetch(url, opts) {
    opts = opts || {};
    if (!opts.headers) opts.headers = {};
    if (_authToken) opts.headers['Authorization'] = 'Bearer ' + _authToken;
    return fetch(url, opts);
}
```
Then replace `fetch(API.SOMETHING + '?token=' + _authToken)` patterns with `_authFetch(API.SOMETHING)`.
**Count:** ~80+ fetch calls in app.js include `token=` in URL.
**Why:** Tokens in URLs are logged in server logs, browser history, and referer headers.
**Verify:** Network tab shows Authorization header, not token in URL.

### 0.9 — Thread-Safe Token Store

**File:** `freq/modules/serve.py`
**Line:** 6534
**Current:** `_auth_tokens = {}` with no lock. Mutations at lines 1293, 1297, 6578, 6593, 6599.
**Change:** Add a lock and use it everywhere:
```python
# Line 6534:
_auth_tokens = {}
_auth_lock = threading.Lock()
```
Wrap ALL mutations:
- Line 1293: `with _auth_lock: session = FreqHandler._auth_tokens.get(token)`
- Line 1297: `with _auth_lock: del FreqHandler._auth_tokens[token]`
- Line 6578: `with _auth_lock: FreqHandler._auth_tokens[token] = {...}`
- Line 6593: `with _auth_lock: session = FreqHandler._auth_tokens.get(token)`
- Line 6599: `with _auth_lock: del FreqHandler._auth_tokens[token]`

Also use `secrets.token_urlsafe(32)` instead of SHA256 for token generation (line 6577).
**Why:** Race conditions on concurrent requests. Weak token entropy.
**Verify:** No crashes under concurrent login/verify requests.

### 0.10 — Sanitize DC01 Data from Docs

**File:** `docs/CONFIGURATION.md` — lines 224-232
**Change:** Replace `10.25.255.0/24` and `10.25.25.0/24` with `192.168.10.0/24` and `192.168.30.0/24`.

**File:** `docs/E2E-EXECUTION-PLAN.md`
**Change:** Delete the file or move to `.internal/`.

**File:** `docs/freqconcourstheworld/*.md`
**Change:** Add header: `# INTERNAL — Not for public distribution`
**Why:** DC01 network topology leaks block public release.
**Verify:** `grep -r "10.25" docs/` returns only internal-marked files.

---

## PHASE 1: FOUNDATION HARDENING

**Timeline:** 1-2 weeks.
**Commit message prefix:** `foundation:`

### 1.1 — Config Validation

**File:** `freq/core/config.py`
**Where:** After line 359 (end of `load_config()`)
**Change:** Add validation function:
```python
def _validate_config(cfg: FreqConfig) -> list:
    """Validate config. Returns list of warning strings."""
    warnings = []
    from freq.core.validate import ip as valid_ip, port as valid_port
    from freq.deployers import HTYPE_COMPAT
    
    for host in cfg.hosts:
        if not valid_ip(host.ip):
            warnings.append(f"Host {host.label}: invalid IP '{host.ip}'")
        cat, vendor = resolve_htype(host.htype) if hasattr(host, 'htype') else ("unknown", "unknown")
        if cat == "unknown":
            warnings.append(f"Host {host.label}: unknown type '{host.htype}'")
    
    if cfg.dashboard_port and not valid_port(cfg.dashboard_port):
        warnings.append(f"Invalid dashboard port: {cfg.dashboard_port}")
    if cfg.ssh_connect_timeout <= 0:
        warnings.append(f"SSH connect timeout must be positive: {cfg.ssh_connect_timeout}")
    if cfg.ssh_max_parallel <= 0:
        warnings.append(f"SSH max parallel must be positive: {cfg.ssh_max_parallel}")
    
    return warnings
```
Call it at end of `load_config()`:
```python
warnings = _validate_config(cfg)
for w in warnings:
    logger.warn(f"config: {w}")
```
Also make `_safe_int` log warnings:
```python
def _safe_int(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warn(f"config: expected int, got {type(value).__name__}: {value!r}, using default {default}")
        return default
```
**Why:** Malformed config silently degrades. Users never know their settings are ignored.
**Verify:** Set `ssh.max_parallel = "five"` in freq.toml, run `freq doctor`, see warning in output.

### 1.2 — Config Caching

**File:** `freq/core/config.py`
**Where:** Above `load_config()` (line 316)
**Change:** Add module-level cache:
```python
_config_cache = None
_config_cache_ts = 0
_CONFIG_TTL = 5  # seconds

def load_config(install_dir=None, force=False):
    global _config_cache, _config_cache_ts
    now = time.time()
    if not force and _config_cache and (now - _config_cache_ts) < _CONFIG_TTL:
        return _config_cache
    # ... existing load logic ...
    _config_cache = cfg
    _config_cache_ts = now
    return cfg
```
**Why:** `load_config()` called 17+ times in background probes + 40+ times per-request in API handlers. All re-read files from disk.
**Verify:** Add timing: config loads once, subsequent calls within 5s return cached.

### 1.3 — Add pytest-cov and ruff to pyproject.toml

**File:** `pyproject.toml`
**Where:** Append after the existing content
**Change:** Add:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=freq --cov-report=term-missing --cov-fail-under=50"

[tool.coverage.run]
branch = true
source = ["freq"]
omit = ["freq/data/*", "freq/tui/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.",
    "raise NotImplementedError",
]

[tool.ruff]
line-length = 120
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "W"]
ignore = ["E501"]  # line length handled separately
```

**File:** `.github/workflows/test.yml`
**Where:** Line 122 (pytest command)
**Change:** Update test step:
```yaml
- name: Lint
  run: pip3 install ruff && ruff check freq/ --exit-zero

- name: Test with coverage
  run: |
    pip3 install pytest-cov
    python3 -m pytest tests/ -v --tb=short --cov=freq --cov-report=term-missing --cov-fail-under=50
```
**Why:** 0% measured coverage, no linting, no quality gates.
**Verify:** CI runs ruff and reports coverage percentage.

### 1.4 — Auth Decorator

**File:** `freq/api/helpers.py`
**Where:** After existing functions
**Change:** Add:
```python
def require_role(min_role="operator"):
    """Decorator for API handlers that require authentication."""
    def decorator(handler_func):
        def wrapper(handler):
            from freq.modules.serve import _check_session_role
            role, err = _check_session_role(handler, min_role)
            if err:
                json_response(handler, {"error": err}, 403)
                return
            handler_func(handler)
        wrapper.__name__ = handler_func.__name__
        wrapper.__doc__ = handler_func.__doc__
        return wrapper
    return decorator
```
Usage in domain modules (replace 36 copy-paste blocks):
```python
from freq.api.helpers import require_role

@require_role("admin")
def handle_vault_set(handler):
    # ... no more manual auth check ...
```
**Why:** Auth check copy-pasted 36 times. One missed = security hole.
**Verify:** Endpoints still require auth. Code is shorter.

### 1.5 — Consolidate Parameter Extraction

**File:** `freq/api/helpers.py`
**Where:** Update existing `get_param()` and add `get_param_int()`
**Change:** Add type-safe helpers:
```python
def get_param_int(handler, key, default=0, min_val=None, max_val=None):
    """Get integer query parameter with bounds checking."""
    raw = get_param(handler, key, str(default))
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return default
    if min_val is not None and val < min_val:
        return default
    if max_val is not None and val > max_val:
        return default
    return val
```
Replace the 33 unsafe `int()` casts across API modules with `get_param_int()`.
**Why:** 33 places do `int(params.get("cores", ["2"])[0])` with no bounds checking.
**Verify:** `?cores=-5` and `?cores=abc` return defaults, not errors.

### 1.6 — Thread-Safe _bg_lock Scope Audit

**File:** `freq/modules/serve.py`
**Issue:** `_bg_lock` held during SSE broadcast creates deadlock risk.
**Change:** In `_bg_probe_health()` (around line 485-492), release lock BEFORE broadcasting:
```python
# Current (lines ~485-492):
with _bg_lock:
    _bg_cache["health"] = result
    _bg_cache_ts["health"] = time.time()
_sse_broadcast(...)  # Move OUTSIDE the lock

# NOT inside the with block
```
Audit all `_bg_probe_*` functions to ensure SSE broadcasts happen AFTER lock release.
**Why:** Lock order violation: `_bg_lock` -> `_sse_lock` in probe, reverse possible in handler.
**Verify:** No deadlocks under load. Dashboard updates continue.

---

## PHASE 2: FRONTEND MODERNIZATION

**Timeline:** 2-3 weeks.
**Commit message prefix:** `frontend:`

### 2.1 — Create `_authFetch` Helper

**File:** `freq/data/web/js/app.js`
**Where:** Near top, after utility functions (after line 78)
**Change:** Add fetch wrapper with auth + timeout + error handling:
```javascript
function _authFetch(url, opts) {
    opts = opts || {};
    if (!opts.headers) opts.headers = {};
    if (_authToken) opts.headers['Authorization'] = 'Bearer ' + _authToken;
    var controller = new AbortController();
    var timeout = setTimeout(function() { controller.abort(); }, 10000);
    opts.signal = controller.signal;
    return fetch(url, opts).finally(function() { clearTimeout(timeout); });
}
```
Then systematically replace all `fetch(API.X + '?token=' + _authToken)` patterns (80+ occurrences).
**Why:** 92 fetch calls have no error handling. Zero have timeouts. 80+ send tokens in URLs.
**Verify:** Network tab shows Bearer header. Timeout after 10s if API hangs.

### 2.2 — URL Routing via History API

**File:** `freq/data/web/js/app.js`
**Where:** In `switchView()` function (line 831) and init section (line 6626+)
**Change:** Update `switchView` to push state:
```javascript
function switchView(view) {
    // ... existing view switching logic ...
    window.history.pushState({view: view}, '', '/dashboard/' + view);
}
```
Add popstate handler:
```javascript
window.addEventListener('popstate', function(e) {
    if (e.state && e.state.view) switchView(e.state.view);
});
```
Add initial route parsing in init:
```javascript
var initPath = window.location.pathname.replace('/dashboard/', '');
if (initPath && VIEW_LOADERS[initPath]) switchView(initPath);
```
Update serve.py `_serve_app` to serve app.html for all `/dashboard/*` paths (SPA catch-all).
**Why:** Can't bookmark views. Browser back/forward doesn't work.
**Verify:** Navigate to Fleet, copy URL, paste in new tab — lands on Fleet view.

### 2.3 — DOM Caching with data Attributes

**File:** `freq/data/web/js/app.js`
**Where:** VM card rendering (line 2436) and health refresh (line 920)
**Change:** Add `data-host-id` to cards when rendering:
```javascript
// In VM card rendering (line 2436):
var c = '<div class="host-card" data-host-id="' + v.name.toLowerCase() + '" ...>';

// In PVE node card rendering (line 2380):
nodeCard = '<div class="host-card" data-host-id="' + nodeName.toLowerCase() + '" ...>';
```
Update silent refresh to use data attributes instead of text matching:
```javascript
// Replace lines 920-935 (text-matching loop):
var card = document.querySelector('.host-card[data-host-id="' + v.name.toLowerCase() + '"]');
if (!card) return;
// ... update card directly
```
**Why:** `querySelectorAll('.host-card')` + text matching on every 5-10s refresh is O(n*m). Data attribute lookup is O(1).
**Verify:** Fleet view still updates live. No text-matching in refresh functions.

### 2.4 — Event Listener Cleanup

**File:** `freq/data/web/js/app.js`
**Where:** View-specific listeners (lines 3366, 3762, 5598, 5835-5920)
**Change:** Create cleanup registry:
```javascript
var _viewCleanup = [];
function _onViewCleanup(fn) { _viewCleanup.push(fn); }
```
In `switchView()`, before switching:
```javascript
_viewCleanup.forEach(function(fn) { try { fn(); } catch(e) {} });
_viewCleanup = [];
```
Wrap view-specific listeners:
```javascript
// Instead of: document.addEventListener('mousedown', handler)
// Use:
document.addEventListener('mousedown', handler);
_onViewCleanup(function() { document.removeEventListener('mousedown', handler); });
```
**Why:** Event listeners accumulate on every view switch. 50 switches = 50 zombie handlers.
**Verify:** Memory profiler shows stable listener count across view switches.

### 2.5 — Extract Inline Styles to CSS Classes

**File:** `freq/data/web/css/app.css`
**Change:** Add classes for the most common inline style patterns:
```css
.sparkline-row { display: flex; gap: 8px; margin-top: 8px; padding-top: 6px; border-top: 1px solid var(--border); }
.spark-label { font-size: 9px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }
.form-label { font-size: 12px; color: var(--text-dim); margin-bottom: 4px; }
.form-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.form-section { margin-top: 12px; padding: 12px; background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; }
.grid-auto-280 { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: var(--gap-md); }
.text-center { text-align: center; }
.w-full { width: 100%; }
```
Then replace the corresponding `style="..."` strings in app.js and app.html with class references.
**Count:** ~200 inline style strings in JS alone.
**Why:** Inline styles are unmaintainable and override CSS cascade unpredictably.
**Verify:** Visual regression check — dashboard looks identical.

---

## PHASE 3: ARCHITECTURE CLEANUP

**Timeline:** 2-4 weeks.
**Commit message prefix:** `refactor:`

### 3.1 — Extract Auth to `freq/api/auth.py`

**From:** `freq/modules/serve.py` lines 1282-1302, 6534-6631
**To:** New file `freq/api/auth.py`
**Move:**
- `_check_session_role()` (lines 1282-1302)
- `_auth_tokens` dict + `_auth_lock` (line 6534)
- `_hash_password()` / `_verify_password()` (from Phase 0.3)
- `_check_rate_limit()` / `_record_login_attempt()` (from Phase 0.6)
- `SESSION_TIMEOUT_SECONDS` constant
- Login/verify/change-password handlers

Update all 36+ callers to import from `freq.api.auth` instead of serve.py.
**Why:** Auth logic scattered across 7,800-line monolith. Should be one focused module.

### 3.2 — Extract Background Probes to `freq/api/probes.py`

**From:** `freq/modules/serve.py` lines 241-919
**To:** New file `freq/api/probes.py`
**Move 7 probe functions:**
1. `_bg_probe_infra()` — line 241 (~130 lines)
2. `_bg_probe_health()` — line 370 (~150 lines)
3. `_bg_probe_fleet_overview()` — line 517 (~155 lines)
4. `_bg_discover_pve_nodes()` — line 673 (~120 lines)
5. `_bg_fetch_vm_tags()` — line 795 (~90 lines)
6. `_bg_sync_hosts()` — line 886 (~30 lines)
7. `_bg_check_update()` — line 919 (~70 lines)

Keep in serve.py: `_bg_health_loop()` (line 990) and `_bg_slow_loop()` (line 1000) — these are the thread runners that call the probes.
**Why:** 745 lines of probe logic in the HTTP server module. Probes are domain logic, not HTTP logic.

### 3.3 — Move Remaining Helpers to `freq/api/helpers.py`

**From:** `freq/modules/serve.py`
**Move:**
- `_parse_query()` (line 1320) — 67 callers in serve.py
- `_parse_query_flat()` (line 1342) — 23 callers in serve.py
- `_parse_pct()` (line 1325) — percentage parsing
- `_resolve_container_vm_ip()` (line 1348) — IP resolution

Update all callers. The 67 `_parse_query` callers in serve.py become `from freq.api.helpers import _parse_query`.
**Why:** Helpers trapped in 7,800-line monolith prevent serve.py decomposition.

### 3.4 — Delete Dead Route Comments

**File:** `freq/modules/serve.py` lines 1551-1670
**Change:** Delete the 75+ lines of "moved to" comments documenting extracted routes.
**Why:** Documentation-in-code that serves no purpose. The routes are in `freq/api/` modules.
**Verify:** `wc -l freq/modules/serve.py` drops by ~120 lines.

---

## PHASE 4: TESTING & QUALITY

**Timeline:** Ongoing, parallel with other phases.
**Commit message prefix:** `test:`

### 4.1 — Security Tests

**File:** New `tests/test_security_api.py`
**Tests to write:**
```python
def test_no_token_returns_401():
    """Auth bypass: no token should NOT return data."""
    
def test_vault_requires_auth():
    """Vault endpoints require admin token."""

def test_login_rate_limiting():
    """10+ failed logins from same IP returns 429."""

def test_password_uses_salt():
    """New passwords include salt separator."""

def test_cors_not_wildcard():
    """CORS header is not * on responses."""

def test_post_login_only():
    """GET /api/auth/login returns 405."""
```
**Why:** Every security fix in Phase 0 needs a test to prevent regression.

### 4.2 — Config Validation Tests

**File:** New `tests/test_config_validation.py`
**Tests to write:**
```python
def test_invalid_ip_warns():
    """Config with bad IP produces warning."""

def test_unknown_host_type_warns():
    """Config with unknown host type produces warning."""

def test_safe_int_logs_warning():
    """Non-integer config value logs warning."""

def test_empty_toml_uses_defaults():
    """Empty freq.toml still produces valid config."""

def test_malformed_toml_warns():
    """Broken TOML syntax produces warning, doesn't crash."""
```

### 4.3 — Auth Decorator Tests

**File:** New `tests/test_auth_decorator.py`
**Tests to write:**
```python
def test_require_role_blocks_no_token():
    """@require_role handler returns 403 without token."""

def test_require_role_passes_valid_token():
    """@require_role handler proceeds with valid admin token."""

def test_require_role_blocks_insufficient_role():
    """@require_role('admin') blocks operator token."""
```

---

## PHASE 5: SHIP PREPARATION

**Timeline:** After Phases 0-2.
**Commit message prefix:** `ship:`

### 5.1 — `freq init` Wizard

This is the P0 blocker for public release. The wizard needs to:
1. Auto-detect PVE nodes (try common IPs, ask user to confirm)
2. Ask for gateway IP, cluster name, SSH account
3. Generate freq.toml with detected values
4. Generate hosts.toml from PVE cluster VM inventory
5. Create SSH keys if missing
6. Test connectivity to all discovered hosts
7. Run `freq doctor` to validate

**Implementation location:** `freq/modules/init_cmd.py` — the existing file needs the wizard logic added to its phase system.
**Design reference:** Archives have full spec at `/mnt/obsidian/WSL-JARVIS-MEMORIES/docs/freq-audit-s076/freq-generic-roadmap.md`

### 5.2 — Replace DC01-Specific Values

**Reference:** Archives cataloged 58 hardcoded values. Top 10:
1. `svc-admin` SSH username (40 occurrences) — make configurable via `ssh.service_account`
2. `DC01` brand strings (10 occurrences) — use `cfg.cluster_name`
3. `truenas_admin` group (8 occurrences) — make configurable
4. `/mnt/obsidian` paths (5 occurrences) — remove or make configurable
5. `jarvis-ai` probe user (4 occurrences) — remove
6. Gateway/DNS IPs (3 occurrences) — use `cfg.vm_gateway`/`cfg.vm_nameserver`

Most are already in config fields but some modules read hardcoded values instead of config.
**Verify:** `grep -r "svc-admin\|DC01\|truenas_admin\|/mnt/obsidian\|jarvis-ai" freq/` returns only config defaults and comments.

### 5.3 — TLS Support

**File:** `freq/modules/serve.py`
**Where:** `cmd_serve()` function (line 7758+)
**Change:** Add optional TLS wrapping:
```python
import ssl

if cfg.tls_cert and cfg.tls_key:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cfg.tls_cert, cfg.tls_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    logger.info(f"Dashboard: https://localhost:{port}")
else:
    logger.info(f"Dashboard: http://localhost:{port}")
    logger.warn("TLS not configured — credentials sent in plaintext")
```
Add config fields to FreqConfig: `tls_cert`, `tls_key` (default empty).
At minimum, document reverse proxy setup (nginx/caddy) in README.
**Why:** All credentials currently sent in plaintext HTTP.

---

## PHASE 6: FEATURE EXPANSION (Post-Ship)

These use the archive feature designs as starting points. Not detailed here — each gets its own design doc when the time comes.

1. **`freq audit`** — Security scanner. Archives say this is "the one thing worth millions." Automates the S076 audit that found 7 critical vulns.
2. **`freq backup`** — VM backup management. Zero vzdump schedules is existential risk.
3. **TrueNAS midclt migration** — REST API deprecated in 26.04. Must migrate before upgrade.
4. **`freq pf sweep`** — 1,046 lines of spec ready in archives.
5. **`freq idrac`** — 876 lines of spec ready in archives.
6. **Notification webhooks** — Discord, Slack, email, generic webhook.

---

## EXECUTION CHECKLIST

```
PHASE 0 — SECURITY (commit each fix separately)
[ ] 0.1  Fix auth bypass (serve.py:1292)
[ ] 0.2  Implement _request_body() + POST-only login
[ ] 0.3  Fix password hashing (3 locations)
[ ] 0.4  Add auth to vault endpoints (secure.py)
[ ] 0.5  Fix CORS headers (4 locations)
[ ] 0.6  Add rate limiting on login
[ ] 0.7  Add security headers
[ ] 0.8  Move tokens to Authorization header (serve.py + app.js)
[ ] 0.9  Thread-safe token store
[ ] 0.10 Sanitize DC01 data from docs
[ ] --- DEPLOY TO VM 5005, VERIFY DASHBOARD WORKS ---

PHASE 1 — FOUNDATION (commit in logical groups)
[ ] 1.1  Config validation
[ ] 1.2  Config caching
[ ] 1.3  Add pytest-cov + ruff to pyproject.toml + CI
[ ] 1.4  Auth decorator
[ ] 1.5  Consolidate parameter extraction
[ ] 1.6  Thread-safe _bg_lock scope audit

PHASE 2 — FRONTEND (commit per feature)
[ ] 2.1  Create _authFetch helper
[ ] 2.2  URL routing via History API
[ ] 2.3  DOM caching with data attributes
[ ] 2.4  Event listener cleanup
[ ] 2.5  Extract inline styles to CSS classes

PHASE 3 — ARCHITECTURE (commit per extraction)
[ ] 3.1  Extract auth to freq/api/auth.py
[ ] 3.2  Extract background probes to freq/api/probes.py
[ ] 3.3  Move remaining helpers to freq/api/helpers.py
[ ] 3.4  Delete dead route comments

PHASE 4 — TESTING (ongoing)
[ ] 4.1  Security tests
[ ] 4.2  Config validation tests
[ ] 4.3  Auth decorator tests

PHASE 5 — SHIP PREP (after 0-2)
[ ] 5.1  freq init wizard
[ ] 5.2  Replace DC01-specific values
[ ] 5.3  TLS support
```

---

## VERIFICATION PROTOCOL

After each phase, on VM 5005:
1. `git pull origin v3-rewrite` on VM 5005
2. `sudo pip install --break-system-packages -e /opt/pve-freq`
3. Restart: `sudo pkill -f "freq serve"; sudo nohup freq serve --port 8888 </dev/null >/tmp/freq-serve.log 2>&1 &`
4. Hard refresh dashboard (Ctrl+Shift+R)
5. Verify login works
6. Verify fleet data loads
7. Check browser console for errors
8. Run `freq doctor` on VM 5005

---

## POST-EXECUTION: E2E PLAN UPDATE

After all phases are complete, update **`docs/freqconcourstheworld/E2E-TEST-PLAN.md`** (the real E2E plan — 781 lines, 26 phases, all 7 device types) to reflect every change made here:
- New auth flow (POST-only login, Bearer tokens, rate limiting)
- Password hashing migration (PBKDF2 + salt)
- Vault auth requirements
- CORS changes
- Security headers
- Config validation warnings
- `_authFetch` in frontend
- Any new CLI flags, config fields, or API behaviors

`docs/E2E-EXECUTION-PLAN.md` is the old skeleton — ignore it.
The E2E plan must test what actually ships, not what existed before this audit.
**Added:** 2026-04-02 by Morty before Phase 0 execution.
