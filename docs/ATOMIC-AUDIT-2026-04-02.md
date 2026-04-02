# FREQ ATOMIC AUDIT — April 2, 2026

**Audited by:** Morty (20 parallel agents, 14+ hours of analysis)
**Scope:** Every file in both repos, all archives, all competitors, all best practices
**Philosophy:** No ass-kissing. Diamonds require pressure.

---

## THE HONEST TRUTH

FREQ is a **genuinely unique tool** in a space where nothing else exists. No other project spans Proxmox + Docker + pfSense + TrueNAS + switches in one CLI+dashboard. Cockpit is deprecating multi-host. Community scripts run as root with no audit trail. Portainer locks compose files in a database. Grafana+Prometheus requires a PhD in YAML.

But unique doesn't mean ready. The codebase has **critical security vulnerabilities**, **architectural debt from rapid growth**, and **missing infrastructure** that would embarrass us if we shipped today.

Here's the full picture.

---

## PART 1: WINS (What's Genuinely Good)

### Architecture Wins
- **Zero external dependencies.** The entire tool runs on Python stdlib. This mirrors what AWS CLI, Ansible, and Terraform do. It's a competitive advantage, not a limitation.
- **SSH multiplexing via ControlMaster.** 4x speedup on fleet ops (14 hosts in 2.7s). This is the exact same pattern Ansible uses as its default SSH transport.
- **Safe defaults philosophy.** Every config field has a default. FREQ boots even with empty freq.toml. Config survives broken code.
- **Lazy module imports.** If media.py is deleted, fleet commands still work. The spine survives missing muscles.
- **Deployer registry pattern.** Adding a new device type = one Python file + 4 constants + 2 functions. Clean extension point.
- **Structured JSON logging** with automatic credential redaction. jq-friendly.

### Tech Stack Wins (Validated by Research)
- **argparse** — Correct. Matches AWS CLI, Ansible. Zero deps.
- **subprocess SSH** — Correct. Matches Ansible's default transport. Handles legacy device ciphers natively.
- **TOML config** — Correct. Python ecosystem standard. stdlib tomllib.
- **BaseHTTPRequestHandler** — Correct for single-admin embedded dashboard. No framework needed.

### Dashboard Wins
- **Glassmorphism design system** is cohesive and modern. CSS token system (70 lines) is a solid foundation.
- **Real-time PVE metrics** via API polling with smooth in-place bar updates.
- **SSE event bus** is clean pub/sub with per-client queues and dead client cleanup.
- **Sparkline charts** with HiDPI canvas rendering and proper color coding.

### CLI/UX Wins
- **Personality system** makes the tool memorable. Celebrations after successful commands aren't frivolous — they humanize infrastructure work.
- **freq doctor** is a model for self-diagnostics. 15-point check covering the full stack.
- **Branding is consistent.** Purple theme, ASCII art, colored output. First impression is "this is professional."
- **25 domains, 88+ commands.** The breadth is impressive.

---

## PART 2: CRITICAL ISSUES (Fix Before Anything Else)

### SECURITY — The House is Unlocked

| Issue | Severity | Location |
|-------|----------|----------|
| **Auth bypass: no token = admin** | CRITICAL | serve.py:1282-1292 — missing token grants full admin access |
| **Plaintext HTTP, no TLS** | CRITICAL | serve.py:7788 — all credentials sent in cleartext |
| **CORS wildcard on every endpoint** | CRITICAL | serve.py:7340 — `Access-Control-Allow-Origin: *` enables CSRF |
| **Tokens in URL query strings** | HIGH | serve.py:1288 — logged in server logs, browser history, referer headers |
| **SHA256 passwords, no salt** | HIGH | serve.py:6562 — rainbow table vulnerable |
| **`_request_body()` doesn't exist** | HIGH | serve.py:3111 — POST login always falls back to GET params |
| **Zero rate limiting** | HIGH | serve.py:6536 — brute-force login with zero consequences |
| **Vault endpoints have NO auth** | HIGH | secure.py:28-61 — anyone can read/write secrets |
| **Binds to 0.0.0.0** | HIGH | serve.py:7788 — exposed to entire network |
| **Systemd unit runs as root** | HIGH | install.sh — dashboard compromise = root on all hosts |
| **Missing security headers** | MEDIUM | No CSP, X-Frame-Options, X-Content-Type-Options |
| **33 unsafe int() casts** | MEDIUM | API modules — no bounds checking on user input |
| **f-string SSH command injection risk** | MEDIUM | docker_api.py:217, net.py:270 — paths not quoted |

### DATA LEAKS — Blocks Public Release

| Issue | File | Fix |
|-------|------|-----|
| DC01 VLAN subnets in docs | docs/CONFIGURATION.md:224-232 | Replace with 192.168.x.x examples |
| DC01 VM IPs in E2E plan | docs/E2E-EXECUTION-PLAN.md | Delete or sanitize |
| DC01 IPs in freqconcourstheworld/ | docs/freqconcourstheworld/*.md | Mark internal or sanitize |

---

## PART 3: ARCHITECTURAL DEBT

### serve.py — The 7,800-Line Monolith
- **100+ handler methods** in one file. Background thread probes, auth, caching, SSE, routing, device-specific logic — all tangled together.
- **Auth check copy-pasted 30+ times** instead of a decorator.
- **3 different parameter extraction patterns** (`get_params`, `_parse_query`, `_parse_query_flat`).
- **Thread safety bugs:** `_auth_tokens` dict has no lock. `_bg_lock` held during SSE broadcast risks deadlock.
- **Cache timestamps written but never checked.** Data served regardless of age. No "stale" indicator.
- **75 lines of "moved to" comments** documenting route migration. Should be deleted.

### Frontend — The 6,600-Line Vanilla JS Monolith
- **543 innerHTML assignments.** DOM rebuilt from scratch on every update.
- **75 global variables** for state. No centralized store, no predictable mutations.
- **No URL routing.** Can't bookmark views, can't use browser back/forward.
- **DOM queried by text matching** every 5-10 seconds instead of data attributes.
- **Memory leaks** from zombie event listeners never cleaned up on view switch.
- **200+ inline style strings** in JS instead of CSS classes.
- **No fetch timeout.** If API hangs, `_healthInFlight` never resets.

### API Layer — 60% Migrated
- **9 domain modules still import helpers from serve.py.** Hard dependency on the monolith.
- **Auth checking inconsistent.** 35 handlers have auth, 60+ GET endpoints have none, vault endpoints (secrets!) have none.
- **`load_config()` called per-request with no caching.** 100+ file reads per second on busy dashboard.
- **Plugin module had broken registration** (fixed this session — was using short keys that never matched dispatch).

### Config System — Silent Failures
- **Malformed TOML silently returns `{}`.** User gets defaults, thinks config loaded.
- **`_safe_int()` swallows bad values.** `max_parallel = "five"` silently becomes 5. No warning.
- **No schema validation.** Invalid IPs, unknown host types, out-of-range ports — all accepted.
- **FreqConfig is mutable** when it should be frozen. Discipline, not enforcement.
- **No file locking on hosts.toml writes.** Concurrent `freq discover` + `freq sync` can corrupt.
- **Fleet boundaries entirely commented out** in production config.

### Docker Packaging — Diverged
- **Two repos have different system packages** (11 vs 6), different user models (USER vs setpriv), different health check endpoints (/healthz vs /api/status), completely different volume paths.
- **No automated sync validation.** No CI job catches divergence.
- **Health check missing from compose.yml** (only in Dockerfile).

### Testing — Flying Blind
- **0% measured coverage.** No pytest-cov, no threshold enforcement.
- **48 of 81 modules have zero tests.** 12 of 14 deployers untested.
- **No linting.** No ruff, black, flake8, mypy. No code quality enforcement.
- **No type checking.** Silent runtime errors in production.
- **Test quality mixed.** Foundation tests are solid. Phase tests just check "doesn't crash."

### Documentation — Good Branding, Weak Substance
- **No "First 10 Minutes" guide.** New user drops into `freq init` wizard with no explanation.
- **No troubleshooting guide.** If init fails, you're reading source code.
- **Error messages don't suggest fixes.** "Host not found" but no hint to run `freq host list`.
- **Subcommand help has no examples.** Compare with git/kubectl help output.

---

## PART 4: COMPETITIVE POSITION

### FREQ's Unique Lane
Nobody else does what FREQ does:

| Capability | tteck Scripts | Portainer | Cockpit | Ansible | FREQ |
|------------|--------------|-----------|---------|---------|------|
| Proxmox-native VM management | Via scripts | No | No | Via modules | **Yes** |
| Docker container management | Via scripts | **Yes** | Podman only | Via modules | **Yes** |
| Fleet/multi-host | No | Yes (agents) | **Deprecated** | **Yes** | **Yes** |
| Infrastructure (pfSense/TrueNAS/switches) | No | No | No | Via playbooks | **Yes** |
| Security auditing | No | No (CE) | No | Via roles | **Yes** |
| CLI + Web dashboard | No | Web only | Web only | CLI only | **Yes** |
| Zero dependencies | Yes (bash) | No (Go+Docker) | No (C+React) | No (Python+deps) | **Yes** |

### Patterns to Steal
| Pattern | From | Why |
|---------|------|-----|
| Zero-config auto-discovery | Netdata | Users shouldn't write YAML to see first metric |
| One-command install, working in 60s | Uptime Kuma, Portainer | Two commands max to running dashboard |
| WebSocket/SSE real-time updates | Uptime Kuma | Already have SSE — lean into it more |
| Docker label-based service registration | Homepage | Containers self-register by adding labels |
| Security-first (auto-HTTPS, built-in auth) | Cosmos-Server | Most competitors treat security as optional |
| Config as real files on disk | Dockge (anti-Portainer) | Never lock user data in a database |

### The Opening
- **Cockpit deprecated multi-host.** Fleet management is our lane, wide open.
- **Community scripts have 27K stars but run as root with zero audit trail.** Security is our wedge.
- **Portainer gates RBAC behind paid tier.** We can ship RBAC for free.
- **Grafana+Prometheus requires 10+ config files for a 3-node homelab.** We can do zero-config.

---

## PART 5: BURIED TREASURE (Recovered from Archives)

### Features Designed But Never Built
| Feature | Design Status | Lines of Spec | Priority |
|---------|--------------|---------------|----------|
| `freq init` wizard | Fully specced | P0 blocker | **CRITICAL — blocks public release** |
| `freq audit` security scanner | Fully designed | Tier 1 | **HIGH — catches 7 criticals** |
| `freq pf sweep` firewall audit | 1,046 lines, fact-checked | Ready | HIGH |
| `freq idrac` BMC management | 876 lines, fact-checked | Ready | MEDIUM |
| `freq tn sweep` TrueNAS audit | 800+ lines, fact-checked | Ready | MEDIUM |
| `freq backup` VM backups | Designed | Tier 1 | **HIGH — existential risk** |
| `freq watch` continuous monitor | Framework exists | Tier 2 | MEDIUM |
| `freq context` live fleet snapshot | Designed | Tier 2 | MEDIUM |

### Critical Infrastructure Finding
**TrueNAS REST API is deprecated and will be removed in v26.04.** FREQ uses REST exclusively. Must migrate to `midclt call` over SSH before next TrueNAS upgrade or FREQ silently breaks.

### Architectural Insight Worth Keeping
**FREQ as source of truth:** Stop maintaining stale IP tables in markdown. `freq doctor` should replace static fleet references. Claude wakes up, runs `freq doctor`, knows fleet state in 30 seconds. Stale docs only as emergency fallback.

### Bash v2.0.0 Patterns Worth Evaluating (Not Porting Blindly)
- **`ask_rsq()` — Retry/Skip/Quit** at every failure point. Users never get stuck.
- **Rollback system** — checkpoint-based undo stack for multi-step operations.
- **`dry_or_run()`** — consistent dry-run wrapper on all state-changing commands.
- **pfSense PHP config automation** — DHCP/DNS provisioning via config.xml manipulation.

These are UX patterns to consider implementing in Python, not bash code to port.

---

## PART 6: THE FIX PLAN

### Phase 0: Security Hardening (Do First, Do Now)
**Timeline: 1-2 days. Non-negotiable before any other work.**

1. **Fix auth bypass** — require token always, remove "backwards compat" admin grant
2. **Implement `_request_body()`** — parse JSON POST bodies, stop credentials in GET params
3. **Switch password hashing** to `hashlib.pbkdf2_hmac` with per-user salt
4. **Add auth to vault endpoints** — `_check_session_role(handler, "admin")` on all 3
5. **Set CORS to specific origin** — dashboard URL, not `*`
6. **Add rate limiting** on `/api/auth/login` — 10 attempts per 5 minutes per IP
7. **Add security headers** — X-Frame-Options, X-Content-Type-Options, CSP
8. **Move tokens from query strings to Authorization header** (JS + Python change)
9. **Protect `_auth_tokens` dict** with threading.Lock
10. **Sanitize DC01 data from docs** — CONFIGURATION.md, E2E-EXECUTION-PLAN.md

### Phase 1: Foundation Hardening (1-2 weeks)
**Make what exists bulletproof.**

1. **Config validation** — add `_validate_config()` after load, warn on bad values, error on critical
2. **Cache config** — module-level cache with TTL, stop re-reading files per request
3. **Freeze FreqConfig** — `@dataclass(frozen=True)` to prevent runtime mutation
4. **Add pytest-cov** — measure coverage, set CI threshold at 50% (raise over time)
5. **Add ruff** — basic linting in CI (E, F, I rules)
6. **Fix thread safety** — lock on `_auth_tokens`, audit `_bg_lock` hold scope
7. **Consolidate param extraction** — one `get_param()` pattern in helpers.py
8. **Auth decorator** — `@require_role("admin")` to replace 30+ copy-paste blocks
9. **Systemd unit** — run as `freq-admin` user, not root
10. **Docker repo sync** — unify health check endpoints, document which files must match

### Phase 2: Frontend Modernization (2-3 weeks)
**Not a rewrite. Targeted improvements.**

1. **Add htmx** (14KB) — replace innerHTML fetch patterns with `hx-get`/`hx-swap`
2. **URL routing** via History API — bookmarkable views, browser back/forward
3. **Extract inline styles** to CSS classes — `.input`, `.sparkline-row`, `.form-label`
4. **DOM caching** — use `data-host-id` attributes, cache card references, stop text matching
5. **Fetch timeouts** — 10s timeout on all API calls, reset in-flight flags on error
6. **Clean up event listeners** — remove on view switch, prevent zombie handlers
7. **Split app.js** into logical modules — fleet.js, docker.js, security.js, palette.js
8. **Add loading state cleanup** — "Scanning..." that shows forever if API hangs

### Phase 3: Architecture Cleanup (2-4 weeks)
**Extract the monolith.**

1. **Extract auth middleware** from serve.py to `freq/api/auth.py`
2. **Extract background probes** to `freq/api/probes.py`
3. **Move remaining serve.py helpers** to `freq/api/helpers.py` (complete the migration)
4. **Extract device probes** to device-specific modules (not inline in _bg_probe_infra)
5. **Split init_cmd.py** (4,172 lines) — deployer logic to `freq/deployers/*/`, keep orchestrator thin
6. **Add file locking** on hosts.toml writes
7. **Implement config reload signal** — SIGHUP or `freq config reload`

### Phase 4: Testing & Quality (Ongoing)
**Build the safety net.**

1. **Deployer unit tests** — mock SSH, verify command construction for all 14 deployers
2. **API integration tests** — mock PVE responses, verify request building
3. **Security tests** — injection prevention on all entry points
4. **Add mypy** — gradual type hints starting with core/
5. **Coverage to 70%** — focus on modules that handle user input and SSH
6. **CI: ruff + black + pytest-cov** on every PR

### Phase 5: Ship Preparation (When Phases 0-2 Complete)
**Get ready for public.**

1. **`freq init` wizard** — the P0 blocker. Auto-detect PVE, generate configs, first-run experience.
2. **Replace 58 DC01-specific values** — all config-driven, nothing hardcoded
3. **"Getting Started" guide** — install to working dashboard in 10 minutes
4. **Error messages that suggest fixes** — "Host not found. Run `freq host list` to see available hosts."
5. **TLS support** — self-signed certs by default, or document reverse proxy setup
6. **Subcommand help with examples** — copy-paste ready

### Phase 6: Feature Expansion (After Ship)
**Build on the solid foundation.**

1. `freq audit` — security scanner (designed, ready to implement)
2. `freq backup` — VM backup management (existential gap)
3. TrueNAS midclt migration — before 26.04 breaks everything
4. `freq pf sweep` — interactive firewall audit (1,046 lines of spec ready)
5. `freq idrac` — BMC management (876 lines of spec ready)
6. Notification webhooks — Discord, Slack, email, generic webhook
7. Public status page — Uptime Kuma pattern

---

## PART 7: THE SCORECARD

| Dimension | Current | Target | Gap |
|-----------|---------|--------|-----|
| **Security** | D | A | Auth bypass, no TLS, no rate limiting |
| **Architecture** | C+ | A- | Monoliths need extraction, migration 60% done |
| **Frontend** | C+ | B+ | Works but innerHTML soup, no routing, memory leaks |
| **Testing** | D+ | B | 0% measured coverage, 48 untested modules |
| **Config** | C | B+ | Silent failures, no validation, no caching |
| **Documentation** | C+ | B+ | Good branding, weak substance |
| **Docker** | B- | A- | Solid design, diverged from main repo |
| **CLI/UX** | B+ | A | 88 commands, good branding, weak help text |
| **SSH Layer** | A- | A | Multiplexing, timeout handling, legacy device support |
| **Deployer Pattern** | A- | A | Clean registry, easy to extend |
| **Competitive Position** | A | A+ | Unique lane, no direct competitor |

---

## FINAL WORD

FREQ is a gem with real potential. The zero-dependency philosophy, SSH multiplexing, deployer registry, and competitive positioning are genuine strengths that took real engineering to build. The dashboard looks professional. The CLI is comprehensive.

But gems aren't diamonds. The security holes would be embarrassing in public. The monoliths will slow down every future feature. The testing gap means bugs ship silent. The config system lies to users when their TOML is broken.

The path to VVS diamonds is: **Phase 0 (security) immediately, Phase 1 (foundation) this week, Phase 2 (frontend) next 2 weeks, then ship.** Everything else follows.

The competition left the door wide open. We just need to walk through it with a product that doesn't have its shoelaces untied.
