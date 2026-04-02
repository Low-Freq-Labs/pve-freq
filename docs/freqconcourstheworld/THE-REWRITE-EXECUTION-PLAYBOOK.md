<!-- INTERNAL — Not for public distribution -->

# THE REWRITE EXECUTION PLAYBOOK

**The Literal Step-by-Step Order of Operations for v3.0.0**

**Author:** Morty (Lead Dev)
**Created:** 2026-04-01
**Purpose:** Answer the question "what do I do first?" — because building 810 actions without an order of operations is how you build everything twice.

---

## THE CORE PROBLEM

THE-CONVERGENCE says "old flat commands are dead." FEATURE-PLAN says "build in workstreams." These are in tension:

- If I build WS1 (switch orchestration) as `freq switch exec` (old flat style), I have to move it to `freq net switch exec` later. Double work.
- If I build WS1 as `freq net switch exec` (converged style), cli.py doesn't support domain dispatch yet. It crashes.

**The answer: refactor the CLI dispatch system FIRST.** Before a single new feature is written. The converged domain structure is the foundation that everything else is built on.

---

## PHASE 0: THE FOUNDATION REFACTOR

Before any new feature. Before any workstream. This is the structural change that makes everything else possible.

### Step 0.1: Build the Domain Dispatch System

**Current cli.py architecture:**
```python
# 126 flat top-level commands, each with a _cmd_wrapper
subparsers = parser.add_subparsers()
p = subparsers.add_parser("create", ...)
p.set_defaults(func=_cmd_create)
p = subparsers.add_parser("status", ...)
p.set_defaults(func=_cmd_status)
# ... 124 more of these
```

**Target cli.py architecture:**
```python
# ~25 domains, each with their own subparsers
subparsers = parser.add_subparsers()

# freq vm <action>
vm_parser = subparsers.add_parser("vm", help="Virtual machine lifecycle")
vm_sub = vm_parser.add_subparsers()
vm_sub.add_parser("list", ...).set_defaults(func=_cmd_vm_list)
vm_sub.add_parser("create", ...).set_defaults(func=_cmd_vm_create)
# ...

# freq net <group> <action>
net_parser = subparsers.add_parser("net", help="Network & switch management")
net_sub = net_parser.add_subparsers()
# freq net switch <action>
net_switch = net_sub.add_parser("switch", ...)
net_switch_sub = net_switch.add_subparsers()
net_switch_sub.add_parser("show", ...).set_defaults(func=_cmd_net_switch_show)
# ...
```

**What to do:**
1. Create the domain parser structure (empty — just the tree)
2. Move each existing command into its domain one at a time
3. Remove the old flat registration
4. Test after every move — `freq <domain> <action> --help` must work

**Order of domain creation:**
```
1. freq vm        ← 21 existing commands, biggest batch
2. freq fleet     ← 14 existing commands
3. freq host      ← 9 existing commands
4. freq docker    ← 3 existing (docker, docker-fleet, stack)
5. freq secure    ← 6 existing (audit, harden, comply, patch, secrets, vault)
6. freq observe   ← 7 existing (alert, logs, trend, capacity, monitor, sla, report)
7. freq state     ← 6 existing (baseline, plan, apply, check, fix, diff, policies, gitops)
8. freq auto      ← 6 existing (rules, schedule, playbook, webhook, chaos, patrol)
9. freq ops       ← 2 existing (oncall, risk)
10. freq hw       ← 3 existing (idrac, cost, cost-analysis)
11. freq store    ← 3 existing (truenas, zfs, backup + backup-policy)
12. freq dr       ← 3 existing (backup, backup-policy → moves here, sla → shares with observe, rollback)
13. freq net      ← 5 existing (switch, netmon, map, ip, discover → partial)
14. freq fw       ← 1 existing (pfsense → renamed)
15. freq cert     ← 1 existing (cert)
16. freq dns      ← 1 existing (dns)
17. freq proxy    ← 1 existing (proxy)
18. freq media    ← 1 existing (media — already well-organized)
19. freq user     ← 7 existing (users, new-user, passwd, roles, promote, demote, install-user)
20. freq event    ← empty (new domain, no existing commands)
21. freq vpn      ← empty (new domain)
Utilities stay top-level: init, configure, version, help, doctor, menu, demo, learn, serve, docs, publish, plugin
```

**Estimated effort:** 2-3 sessions. This is refactoring, not rewriting — the module code doesn't change, only the CLI registration and dispatch wrappers.

**Test after completion:**
- `freq help` shows ~25 domains (not 126 flat commands)
- `freq vm --help` shows all VM actions
- `freq vm create --name test --node pve02 ...` works exactly as `freq create` used to
- Every existing feature works under its new domain name
- No old flat command names work (except utilities)

### Step 0.2: Build the Platform Abstraction Layers

From GIT-READY-FOR-PUBLIC-RELEASE.md. These are the core libraries that all new AND existing features use:

```
freq/core/platform.py          — Local platform detection
freq/core/remote_platform.py   — Remote platform detection via SSH
freq/core/packages.py          — Package manager abstraction
freq/core/services.py          — Service manager abstraction
```

**Estimated effort:** 1 session. ~450 lines total. Pure library code with unit tests.

**Test after completion:**
- `Platform.detect()` returns correct data on Nexus (Debian 13)
- Remote detection works via SSH to freq-test (Debian)
- Package manager detection finds `apt` on Debian hosts
- Service manager detection finds `systemd` on Debian hosts

### Step 0.3: Fix P0 Ship Blockers

From GIT-READY. The 6 items that break on non-Debian:

1. comply.py apt-only remediations → use packages.py
2. audit.py apt-only update check → use packages.py
3. init_cmd.py "apt install sshpass" messages → use install_hint()
4. netmon.py "apt install lldpd" message → use install_hint()
5. config.py tomllib import → consistent try/except
6. preflight.py MIN_PYTHON → align to (3, 11)

**Estimated effort:** 1 session. Targeted fixes, not rewrites.

### Step 0.4: Apply SOURCE-CODE-STANDARDS to All Existing Files

Every existing module gets:
- Header docstring (5 questions)
- Named constants (no magic numbers)
- Section separators (300+ line files)
- Import order standardization

**Estimated effort:** 2-3 sessions. Tedious but mechanical. Do NOT change any logic — headers and formatting only.

### Step 0.5: Restructure serve.py for Domain-Based API

serve.py is 7,676 lines and will need to support 810 actions. It must be split up.

**Current:** One monolithic file with all API handlers, all HTML, all SSE, all auth.
**Target:** Domain-based API modules that serve.py imports and routes to.

```
freq/api/__init__.py          — API router
freq/api/auth.py              — Login, sessions, tokens
freq/api/vm.py                — /api/v1/vm/* endpoints
freq/api/fleet.py             — /api/v1/fleet/* endpoints
freq/api/net.py               — /api/v1/net/* endpoints
freq/api/fw.py                — /api/v1/fw/* endpoints
... (one per domain)
freq/modules/serve.py         — HTTP server, SSE, static files, dashboard HTML
                                 (still exists, but delegates API handling to freq/api/)
```

**URL structure:**
```
/api/v1/vm/list              → freq vm list
/api/v1/vm/create            → freq vm create
/api/v1/net/switch/vlans     → freq net switch vlans
/api/v1/fw/rules/list        → freq fw rules list
/api/v1/observe/metrics/top  → freq observe metrics top
```

Every CLI domain maps 1:1 to an API path prefix. Every CLI action maps to an API endpoint. The API is the CLI over HTTP — same functions, same arguments, JSON in/out.

**Estimated effort:** 2-3 sessions. Significant refactor of serve.py.

---

## PHASE 1-9: BUILD BY WORKSTREAM

After Phase 0 is complete, the converged CLI structure exists and new features build directly into it. Follow the workstream order from FEATURE-PLAN.md:

```
PHASE 1 — The Network (WS 1-2)
PHASE 2 — The Gateway (WS 3-7)
PHASE 3 — The Foundation (WS 8-9)
PHASE 4 — The Eyes (WS 10-11)
PHASE 5 — The Brain (WS 12, 15-16)
PHASE 6 — The Fleet (WS 13-14, 17-18)
PHASE 7 — The Ecosystem (WS 19)
PHASE 8 — The Face (WS 20)
PHASE 9 — The Proof (WS 21)
```

### For Each Workstream, the Build Order Is:

```
1. Create the module file with header docstring (SOURCE-CODE-STANDARDS)
2. Define constants and data storage paths
3. Implement commands one at a time:
   a. Register in cli.py under the correct domain
   b. Write the command function
   c. Write unit test
   d. Register API endpoint in freq/api/<domain>.py
   e. Verify: freq <domain> <action> --help works
   f. Verify: freq <domain> <action> produces output
4. After ALL commands in the workstream are done:
   a. Run full test suite — 0 regressions
   b. Update module header if anything changed during build
   c. Commit with clear message
```

### Docker Repo Sync Cadence

After EVERY phase merge to `v3-rewrite`, sync pve-freq-docker:
1. Run `scripts/sync-docker.sh` (see RELEASE-STRATEGY.md)
2. Build Docker image: `docker build -t pve-freq:test .`
3. Smoke test: `docker run pve-freq:test freq version`
4. Commit to pve-freq-docker with matching commit message

Do NOT wait until Phase 10 to sync. Both repos stay 1:1 at every phase boundary.

### Commit Strategy During Build

- **One commit per command group** (not per individual command). Example: all switch getter commands = 1 commit. All port management commands = 1 commit.
- **Commit message format:** `feat(net): switch getters — facts, interfaces, vlans, mac, arp, neighbors`
- **Never commit broken code.** If a command is half-done, finish it before committing.
- **Never commit without running tests.** `python3 -m pytest tests/ -q` before every commit.

---

## PHASE 10: THE GIT-READY PASS

After all features are built and tested, before public release:

1. **Run the GIT-READY file-by-file checklist** — every module audited for distro assumptions
2. **Fix P1, P2, P3 issues** from GIT-READY
3. **Test on Tier 1 and Tier 2 distros** using the testing matrix
4. **Docker image build and test** — both Debian and Alpine variants
5. **pve-freq-docker repo sync** — both repos 1:1

---

## PHASE 11: PUBLIC RELEASE PREP

From RELEASE-STRATEGY.md:

1. README polish
2. CHANGELOG.md
3. GitHub release
4. Docker image push
5. Announce

---

## SESSION PLANNING

Rough session mapping (each session = one Morty spawn with a focused mission):

| Session | What Gets Built | Estimated Work |
|---|---|---|
| S008 | Phase 0.1 — CLI domain refactor (move all 126 commands) | Heavy — 2-3 hours |
| S009 | Phase 0.2-0.3 — Platform abstractions + P0 fixes | Medium — 1-2 hours |
| S010 | Phase 0.4 — SOURCE-CODE-STANDARDS applied to all files | Medium — 2 hours |
| S011 | Phase 0.5 — serve.py API restructure | Heavy — 2-3 hours |
| S012 | Phase 1 — WS1 Switch Orchestration (deployer getters, port mgmt, profiles) | Heavy — 3+ hours |
| S013 | Phase 1 — WS1 Event Networking + WS2 Network Intelligence | Heavy — 3+ hours |
| S014 | Phase 2 — WS3 Firewall Deep | Heavy — 3+ hours |
| S015 | Phase 2 — WS4 DNS + WS5 VPN | Medium — 2-3 hours |
| S016 | Phase 2 — WS6 Certs + WS7 Proxy | Medium — 2 hours |
| S017 | Phase 3 — WS8 Storage + WS9 DR | Heavy — 3+ hours |
| S018 | Phase 4 — WS10 Observability | Heavy — 3+ hours |
| S019 | Phase 4 — WS11 Security & Compliance | Heavy — 3+ hours |
| S020 | Phase 5 — WS12 Ops + WS15 IaC + WS16 Automation | Heavy — 3+ hours |
| S021 | Phase 6 — WS13 Docker + WS14 Hardware + WS17 Fleet + WS18 Publish | Medium — 2-3 hours |
| S022 | Phase 7 — WS19 Plugin System | Light — 1 hour |
| S023 | Phase 8 — WS20 Dashboard Pages | Heavy — 3+ hours |
| S024 | Phase 9 — WS21 E2E Testing (live fleet) | Heavy — 3+ hours |
| S025 | Phase 10 — GIT-READY pass + distro testing | Heavy — 3+ hours |
| S026 | Phase 11 — Release prep, README, Docker, announce | Medium — 2 hours |

**~19 sessions from here to public release.** That's the real number. Not a guess — derived from the actual work items.

---

## THE DEPENDENCY CHAIN

This is what MUST happen before what. Arrows mean "depends on."

```
Phase 0.1 (CLI refactor)
    ↓
Phase 0.2 (Platform abstractions)  ──→  Phase 0.3 (P0 fixes)
    ↓
Phase 0.5 (API restructure)
    ↓
Phase 0.4 (Source code standards) ← can run in parallel with 0.5
    ↓
Phase 1 (Network) ← WS1 builds deployer getter interface used by WS2-14
    ↓
Phase 2 (Gateway) ← WS3 establishes REST API pattern used by WS4-7
    ↓
Phase 3 (Storage + DR) ← DR depends on storage commands
    ↓
Phase 4 (Observability + Security) ← needs device management from 1-3
    ↓
Phase 5 (Ops + IaC + Automation) ← automation orchestrates features from 1-4
    ↓
Phase 6 (Docker + HW + Fleet + Publish) ← easy builds, follows established patterns
    ↓
Phase 7 (Plugins) ← formalize after architecture is proven
    ↓
Phase 8 (Dashboard) ← needs all CLI commands to exist first
    ↓
Phase 9 (E2E Testing) ← needs everything built
    ↓
Phase 10 (GIT-READY) ← needs everything tested
    ↓
Phase 11 (Release) ← needs everything polished
```

**There are no shortcuts.** Phase 0 before Phase 1. Phase 1 before Phase 2. Dashboard after CLI. Testing after features. Release after testing. This is the order.

---

## WHAT TO DO WHEN YOU'RE STUCK

During any phase, if progress stalls:

1. **Can't figure out the design?** → Write the --help text first. If you can explain the command to a user, you can implement it.
2. **Module getting too big?** → Split at the section separator. If a section is 200+ lines, it's a candidate for its own module.
3. **Feature depends on something not built yet?** → Stub it. Return mock data with a `# TODO: implement when WS<N> is complete` comment. Wire it up later.
4. **3 failures in a row?** → Stop. Read the error. Check assumptions. Ask Sonny if needed.
5. **Scope creep?** → Check THE-CONVERGENCE. If the command isn't in a domain, it doesn't exist yet. Finish what's planned before adding new ideas.
6. **Lost context between sessions?** → Read resume-state.md. Read the daily journal. Read THIS file's session plan to know where you are.
