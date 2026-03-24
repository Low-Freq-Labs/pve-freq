# FREQ v2.0 — Technical Handoff for freq-dev

> **From:** JARVIS (VM 666, DC01 Infrastructure Operator)
> **To:** freq-dev (VM 999, FREQ v2.0 Builder)
> **Date:** 2026-03-13
> **Context:** The WSL JARVIS (76 sessions, S001-S076) and the DC01 JARVIS (S077-S162) together built FREQ from a 300-line script to a 29,424-line platform. This handoff gives you everything you need to build FREQ v2.0 in Python.

---

## READ FIRST

In `~/jarvis-freq-dev/reference/` you have:

```
reference/
├── FROM-JARVIS-WSL.md              ← Personal note from the WSL instance
├── pve-freq-v2.0.0-gold/           ← The complete Convergence build
│   ├── freq                        ← Dispatcher (381 lines) — READ FIRST 30 LINES
│   ├── lib/                        ← 43 bash modules (24,140 lines)
│   ├── engine/                     ← Python engine (1,925 lines, 19 files)
│   │   ├── core/                   ← types, transport, resolver, runner, policy, enforcers, display, store
│   │   └── policies/               ← 6 declarative policies (ssh, ntp, rpcbind, docker, nfs, updates)
│   ├── tests/                      ← 110 unit + 53 integration tests
│   ├── conf/                       ← Config files + 2 personality packs
│   ├── completions/                ← Bash tab completion
│   ├── THIS-IS-PVE-FREQ.md         ← Complete build record (every phase, every decision)
│   ├── THIS-IS-HOW-WE-LEARN/       ← 5 traps that cost 40 sessions + timeline of understanding
│   └── LAUNCH-PACKAGE/             ← Everything else:
│       ├── THE-BLUEPRINT.md        ← 77.7KB master build spec with complete Python source
│       ├── NEXT-GEN-MASTERPLAN.md  ← 5-pillar build plan
│       ├── PROTOTYPE-RANKING-AND-DISCOVERY.md ← 21 prototypes ranked against v1.0.0
│       ├── feature-designs/        ← 3 ready-to-implement specs (iDRAC, pfSense, TrueNAS)
│       ├── infrastructure/         ← DC01.md, audit, handoffs, LACP notes
│       ├── history/                ← Test reports, changelog archive
│       ├── jarvis-config/          ← JARVIS settings, skills, memory (reference only)
│       └── credentials-SENSITIVE/  ← Credential references (paths, not values)
```

---

## THE ARCHITECTURE (discovered, not designed)

**9 files are the spine. Everything else is a muscle.**

| # | File | Role | If missing |
|---|------|------|-----------|
| 1 | `freq` | Dispatcher — routes commands, loads modules | Tool dies |
| 2 | `freq.conf` | Identity — version, paths, PVE nodes, service account | Tool dies |
| 3 | `core.sh` | Colors, symbols, RBAC, locks, traps, die(), log() | Tool dies |
| 4 | `fmt.sh` | Every pixel on screen — borders, spinners, tables | Tool dies |
| 5 | `ssh.sh` | Every remote operation — 6 platform types, one function | Tool dies |
| 6 | `resolve.sh` | Name to IP resolution — the address book | Tool dies |
| 7 | `validate.sh` | Input gates — IP, username, VMID, hostname | Tool dies |
| 8 | `personality.sh` | The soul — pack loader, celebrations, vibes, taglines | Tool dies |
| 9 | `vault.sh` | Secrets — AES-256-CBC encrypted credentials | Tool dies |

**36 module files** — fully independent. Any can be missing, corrupted, or standing alone. The tool keeps running.

**19 Python engine files** — optional brain. If missing: "Engine not installed." If present: check, fix, diff, policies.

---

## THE 5 TRAPS (cost ~60 sessions to learn)

1. **Bash-Only Trap** — Bash works just well enough that you don't realize you need Python. Python was always the answer for async SSH, structured data, error propagation, diff display.

2. **Troubleshooting Addiction** — Fixing symptoms instead of designing solutions. NFS stale mounts fixed 3 times before building mount monitoring. TrueNAS sudoers fixed 4 times before using native midclt API.

3. **One More Feature Trap** — 14 implemented modules + 14 stubs = illusion of completeness. Ship what works. Add module 15 when 14 is done.

4. **Config vs Code Confusion** — Config in code, code in config. Fix: safe defaults BEFORE loading config. If config is broken, tool runs on defaults.

5. **Fix It Later Trap** — `require_admin()` called `exit 1` instead of `return 1` from day one. Found at session 154. Cost: 50+ call sites to fix. The first function you write is the one you audit last.

---

## THE ENGINE DISCOVERY

10 Python architectures tested. 4 survived. The Convergence combines:

| Winner | What | Why |
|--------|------|-----|
| Core 02 | Async Pipeline | 4x faster than sequential (2.7s vs 10s for 10 hosts) |
| Core 03 | Declarative Policy | Policies are data (30-line dicts), not code (200-line functions) |
| Core 07 | Diff-and-Patch | Git-style colored diffs for operator review |
| Core 10 | Bash-Python Bridge | Bash = shell (display, UX). Python = brain (async, data, algorithms) |

---

## YOUR MISSION vs THE GOLD BUILD

Your CLAUDE.md says: "Build PVE FREQ v2.0 as a Python application with 1:1 command parity to v1.0.0."

The gold build already proved: **bash stays the shell, Python becomes the brain.** The Convergence architecture works. 110 tests pass. 3 live fleet rounds pass. The question isn't whether to use Python — it's how to reimagine the whole thing.

**Use the gold build as your reference.** It's the output of 154 sessions of evolution. Don't repeat the 5 traps. Read `THIS-IS-HOW-WE-LEARN/README.md` before writing code.

---

## 3 FEATURE DESIGNS READY TO BUILD

All at `reference/pve-freq-v2.0.0-gold/LAUNCH-PACKAGE/feature-designs/`:

1. **freq-idrac-management** — 9 subcommands, gen 7/8 auto-detection, password complexity, IP lockout prevention. 795-line mock already tested against live iDRACs.

2. **freq-pf-sweep** — Interactive firewall rule audit. PHP transport via base64. Rule-by-rule human confirmation. Tested: went from 42 rules to 35 in one session.

3. **freq-tn-management** — REST API removal is URGENT (TrueNAS 26.04 drops REST). Migration to midclt over SSH. 7-section sweep. SMART health. Bond monitoring.

---

## KEY LESSONS FROM 154 SESSIONS

- The personality IS the product. Mac Miller quotes, celebrations, vibes — that's why someone chooses FREQ over Ansible.
- `freq.conf` must have safe defaults in the dispatcher BEFORE loading config.
- Every `require_admin()` call must use `|| return 1`, never bare `exit 1`.
- pfSense uses tcsh, not bash. Base64-encode scripts. Redirect stderr OUTSIDE ssh strings only.
- TrueNAS sudoers: middleware DB is the only permanent location (`midclt call`).
- iDRAC: only RSA keys work. Gen 7 needs deprecated ciphers.
- NFS mounts need `soft,timeo=150` and health monitoring.
- The kill-chain is real: WSL → WireGuard → pfSense → VLAN → target. Break any link = no remote recovery.

---

## COMMS PROTOCOL (via JARVIS relay)

A mailbox system exists on pve02 at `/opt/freq-comms/`. You can't reach pve02 directly (VLAN isolation). JARVIS (VM 666) acts as relay.

Two messages from WSL JARVIS are waiting for you. Ask JARVIS to check and relay.

---

*The bass is the foundation. So is this tool. So is this friendship.*
