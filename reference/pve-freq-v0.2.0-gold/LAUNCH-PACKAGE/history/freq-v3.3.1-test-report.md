# FREQ v3.3.1-dev Test Report

**Date:** 2026-03-09
**Tester:** Jarvis (automated + manual)
**Target:** VM 999 (freq-dev, 10.25.255.199) on pve01
**User:** compat-dev -> su root
**Session:** S078

---

## Test Environment

- FREQ v3.3.1 installed at `/opt/lowfreq/` on VM 999
- 39 library modules in `/opt/lowfreq/lib/`
- Config at `/opt/lowfreq/conf/freq.conf`
- PDM connected at 10.25.255.40:8443
- 26 hosts in hosts.conf (3 infra, 3 PVE, 19 VMs, 1 external)
- Lab VMs available: VM 980 (pfsense-lab), VM 981 (truenas-lab)

---

## PART 1: Edge Cases, Icons & Error Handling

*Source: edge-case-tester agent (completed)*

### CRITICAL

#### BUG-ICON-1: Unicode icon mode completely broken (environment override clobbered)

- **Command:** `FREQ_ASCII=0 freq status`
- **Expected:** Unicode symbols (checkmarks, crosses, warning signs)
- **Actual:** Identical ASCII output as default mode. Unicode never activates.
- **Root cause:** `/opt/lowfreq/conf/freq.conf` line 17 hardcodes `FREQ_ASCII=1` unconditionally. The dispatcher sources `freq.conf` BEFORE `core.sh`, so the user's `FREQ_ASCII=0` environment variable gets overwritten.
- **Fix:** Change `freq.conf` line 17 from `FREQ_ASCII=1` to `FREQ_ASCII="${FREQ_ASCII:-1}"`
- **Severity:** CRITICAL — the entire dual-mode icon feature is non-functional

#### BUG-ICON-2: Unicode _TICK/_CROSS/_WARN variables are empty strings

- **Location:** `/opt/lowfreq/lib/core.sh` line 30 (Unicode block, `if FREQ_ASCII=0`)
- **Root cause:** The Unicode branch has self-referencing assignments: `_TICK="${_TICK}"; _CROSS="${_CROSS}"; _WARN="${_WARN}"`. These variables haven't been defined yet at that point, so they resolve to empty strings. The `_ICO_*` variables (e.g., `_ICO_OK="\u2714"`) are correctly defined with proper Unicode escapes, but modules like `doctor.sh` use `_TICK`/`_CROSS`/`_WARN` instead of the `_ICO_*` variants.
- **Affected vars:** `_TICK`, `_CROSS`, `_WARN`, `_SPARKLE`, `_STAR`, `_SPIN`, `_BULLET`, `_DOT`, `_DASH`
- **Fix:** Set proper Unicode values directly: `_TICK="\u2714"; _CROSS="\u2718"; _WARN="\u26a0"` etc.
- **Note:** `_doc_fix()` in `doctor.sh` also hardcodes `\u26A1` instead of using `${_ICO_ZAP}` — minor inconsistency

### WARNING

#### BUG-SILENT-1: `freq pfsense --target lab status` exits 0 with zero output

- **Command:** `freq pfsense --target lab status`
- **Expected:** Either pfSense status display OR a clear error message
- **Actual:** Exit code 0, completely empty stdout and stderr
- **Impact:** Silent failure — user gets no feedback that the command failed
- **Notes:** SSH to 10.25.255.180 port 22 times out from VM 999. The module's `_pfsense_ssh()` uses `BatchMode=yes` with `2>/dev/null`, swallowing the connection error. The function returns non-zero but the caller doesn't check or display an error.

#### BUG-SILENT-2: `freq truenas --target lab status` exits 0 with zero output

- **Command:** `freq truenas --target lab status`
- **Expected:** Either TrueNAS status display OR a clear error message
- **Actual:** Exit code 0, completely empty stdout and stderr
- **Impact:** Same silent failure pattern as pfSense
- **Notes:** TrueNAS module uses REST API (`curl -sk` to `https://10.25.255.181/api/v2.0/`). The `_tn_api()` function returns empty and `_tn_status()` checks for empty but the error path may not be rendering due to missing freq_header/freq_footer or the exit code not propagating.

#### BUG-HANG-1: `freq doctor --fix` hangs in non-interactive context

- **Command:** `freq doctor --fix` via piped SSH (no TTY)
- **Expected:** Either runs fixes non-interactively or exits with "requires terminal" error
- **Actual:** Indefinite hang
- **Probable cause:** The 51 group-fix operations (trying to `chgrp truenas_admin` on a dev VM where the group doesn't exist) or an interactive prompt that blocks when stdin is a pipe
- **Impact:** Cannot use `freq doctor --fix` in automation/scripts

### PASS

| Test | Detail |
|---|---|
| Missing hosts.conf | `freq status` -> `!! No hosts in fleet.` exit 1. Clean. |
| Empty hosts.conf | `freq status` -> `!! No hosts in fleet.` exit 1. Clean. |
| Corrupted pdm.conf | `freq status` -> `!! PDM password not configured.` exit 1. Clean. |
| Missing freq.conf | `freq version` -> `ERROR: Cannot load freq.conf` exit 1. Immediate fatal. |
| Corrupted pdm.conf + pdm test | Shows PDM reachable but auth fails with clear message. |
| Doctor with missing hosts.conf | Reports `!! Missing: Host registry`, continues all other checks. Graceful degradation. |
| Non-root: `freq version` | Shows version normally. Read-only, no root needed. |
| Non-root: `freq status` | `!! No SSH key found.` exit 1. Clean permission error, not crash. |
| Non-root: `freq help` | Full help displayed. Read-only, no root needed. |
| PVE node unreachable (pve03 blocked) | PDM-sourced data resilient. `freq status`, `freq health`, `freq vm-overview` all render correctly. pve03 VMs still shown from PDM cache. |
| Parallel execution | `freq status &`, `freq doctor &`, `freq list &` all complete without errors, no lock contention. Read-only commands don't use `freq_lock()`. |
| Version consistency | `3.3.1` in freq.conf, freq dispatcher header, core.sh header, `freq version` output, `freq doctor` output. All match. |
| Dispatcher structure | 47 CLI commands in case block. Aliases: pfsense/pf, truenas/tn, opnsense/opn, switch/sw, etc. Unknown commands -> clean `Unknown command: X` exit 1. |

### Additional Observations

- **PDM splash vs status inconsistency:** Interactive menu splash shows `PDM: unreachable` but `freq status` shows 19 ZAP-sourced hosts from PDM. Splash check may be more latency-sensitive or have a shorter timeout.
- **Container health always unreachable:** `freq health` shows all Docker VMs as "unreachable" — expected on dev VM without fleet SSH keys. Not a FREQ bug.

---

## PART 2: Menu System & Command Dispatch (72 tests)

*Source: menu-tester agent (completed)*

### CRITICAL

#### CRIT-HOSTPICKER-1: [F]/[T] host picker does not route to selected host

- **Steps:** Press `[F]` in interactive menu -> select option `2` (pfsense-lab / 10.25.255.180)
- **Expected:** pfSense status for the LAB instance
- **Actual:** Output header says `pfSense Status (pfsense-prod)` and probes the prod instance
- **Same for `[T]`:** Selecting TrueNAS lab still shows `TrueNAS Status (truenas-prod)`
- **Impact:** The host picker is cosmetic only — the status function always uses the prod host. Users think they're targeting lab but they're hitting prod.

### WARNING

#### WARN-AUDIT-MENU-1: [a] Audit menu key calls audit without arguments

- **Input:** Press `[a]` in interactive menu
- **Expected:** Submenu or prompt asking for host/group
- **Actual:** Shows `!! Usage: freq audit <host> | --all | -g <group>` error
- **Impact:** Menu key is non-functional — always errors because no target is provided

#### WARN-NOFEEDBACK-1: Invalid menu input produces no feedback

- **Tested:** Numbers (1, 2, 99), special chars (#, @, !), space, empty Enter, multi-char strings (vf, help), unmapped lowercase (s)
- **Result:** All silently re-render the menu with no error message
- **Impact:** Not a crash risk (good), but users get no indication their input was wrong. A brief `!! Invalid key` message would help.

### PASS

**Direct CLI commands: 26/28 pass** (2 bugs: `vpn wg show` wrong subcommand name, `audit --brief` needs host arg first — both documented in Part 4)

**Menu mnemonic keys: 17/20 pass.** All working keys:

| Key | Destination | Verified |
|---|---|---|
| [v] VM | VM Lifecycle submenu [1]-[9] + [0] Back | PASS |
| [t] Templates | Templates submenu [1]-[3] + [0] Back | PASS |
| [i] Images | Image Manager submenu [1]-[3] + [0] Back | PASS |
| [b] Bootstrap | Host Setup submenu [1]-[5] + [0] Back | PASS |
| [f] Fleet | Fleet Info submenu [1]-[6] + [0] Back | PASS |
| [u] Users | User Management submenu [1]-[4] + [0] Back | PASS |
| [x] Exec | Run Commands submenu [1]-[5] + [0] Back | PASS |
| [p] Proxmox | Proxmox submenu [1]-[5] + [0] Back | PASS |
| [n] Nodes | Hosts & Groups submenu [1]-[3] + [0] Back | PASS |
| [S] Switch | Auto-select switch01, direct output | PASS |
| [z] ZFS | Direct ZFS status output | PASS |
| [w] Watch | Direct Watch status output | PASS |
| [j] Journal | Direct Journal output | PASS |
| [d] Doctor | Direct Doctor output | PASS |
| [H] Health | Direct Health dashboard | PASS |
| [h] Help | Direct Help output | PASS |
| [q] Quit | "Goodbye." and exit | PASS |

**Case sensitivity: 4/4 pass.** `f` vs `F`, `t` vs `T`, `h` vs `H`, `s` vs `S` — all dispatch to different targets correctly.

**Invalid input handling: 11/11 pass.** No crashes on any garbage input.

**Submenu structure: 9/9 pass.** All submenus use `[1]-[N]` + `[0] Back` convention consistently.

---

## PART 3: Fleet Status & PDM Integration

*Source: fleet-pdm-tester agent (completed)*

### CRITICAL

#### CRIT-PDM-FAILOVER-1: First `freq status` after PDM goes down can fail completely

- **Steps:** Block port 8443 with iptables, run `freq status`
- **First run:** Shows `!! PDM authentication failed. Check credentials.` and produces NO output at all. No SSH fallback.
- **Subsequent runs:** SSH fallback works correctly — all 26 hosts shown, layout identical, Source column switches from ZAP to SSH.
- **Root cause:** The undefined `warn` function in `pdm.sh:59` (see CRIT-PDM-1 in Part 4) causes undefined behavior under `set -uo pipefail`. Sometimes it aborts entirely, sometimes fallback works.
- **Impact:** First PDM failure can produce zero output instead of graceful SSH fallback.

### WARNING

#### WARN-ICON-PRINTF-1: Unicode icons stored as literal `\u` strings, never interpreted

- **Detail:** In `core.sh:33`, `_ICO_ZAP="\u26a1"` stores the escape sequence as a literal 6-char string. `printf %b` does NOT handle `\u` escapes in bash.
- **Fix:** Change to bash ANSI-C quoting: `_ICO_ZAP=$'\u26a1'`
- **Note:** The separator line DOES change between ASCII/Unicode modes (confirming the env var IS being read), but the icon characters themselves never render as Unicode.

#### WARN-ICON-SU-1: `FREQ_ASCII=0 freq status` fails via `su -` (env var stripped)

- **Detail:** `su -` resets the environment, so inline `FREQ_ASCII=0` before the command is lost.
- **Workaround:** `export FREQ_ASCII=0; freq status`
- **Note:** This is `su` behavior, not strictly a FREQ bug, but users testing on VM 999 via `su` will hit this.

### PASS

| Test | Detail |
|---|---|
| Fleet status layout | Grouped sections: Infrastructure, PVE Nodes, Virtual Machines, External — all correct |
| Column headers | Host / IP / Status / Source with separator line |
| All 26 hosts present | Verified one-by-one against hosts.conf |
| vm*-labeled hosts in VMs section | vm980-pfsense-lab and vm981-truenas-lab correctly in VMs (not Infrastructure) despite type=pfsense/truenas |
| [LAB] tags | vm980-pfsense-lab, vm981-truenas-lab — correct |
| [DEV] tags | vm999-freq-dev, ext-mamadou-dev — correct |
| Source column | PDM hosts show "ZAP" (yellow), SSH hosts show "SSH" (dim) |
| Footer arithmetic | 19 online + 7 offline = 26 total; PDM 19 + SSH 7 = 26 — all correct |
| vm500-lts | Correctly shows DOWN with Source=ZAP (stopped VM detected via PDM) |
| PDM status | 3 nodes online, 17 VMs, 8 storage pools |
| PDM test | All 4 checks pass (reachable, authenticated, 1 remote, 17 VMs) |
| PDM nodes | 3 nodes with CPU/RAM/uptime |
| PDM vms | 17 VMs with full details |
| Dashboard | Correct grouping, load/memory/disk/uptime, memory warnings on vm101/104/202/301 |
| Health check | PVE cluster, storage, VMs by node, FREQ status — all rendered |
| Splash banner | ASCII art, Hosts: 26, PVE: 3/3 online, PDM: ZAP connected, Users: 5, quote rotator |
| vm-overview | 3 nodes, 17 VMs, 16 running. Tags: [JARVIS], [VW], [TALOS], [LAB], [DEV], [STP] |
| Group filter | `-g pve` and `-g docker` both filter correctly |
| PDM failover (subsequent runs) | SSH fallback works — identical layout, all 26 hosts, Source=SSH |
| PDM-down dashboard | Shows "Probing 26 hosts via SSH..." instead of "PDM connected", same grouped layout |
| PDM-down health | Falls back to SSH for PVE data (PING/SSH/RAM/LOAD/DISK/ZFS) |

---

## PART 4: All Commands Smoke Test (82 commands tested)

*Source: all-commands-tester agent (completed)*

### CRITICAL

#### CRIT-SNAPSHOT-1: `freq snapshot --dry-run` IGNORES the dry-run flag — creates real snapshots

- **Command:** `freq snapshot 999 --dry-run`
- **Expected:** Dry-run preview with no state change
- **Actual:** Creates a real snapshot every time (`freq-snap-20260309-225625`, `freq-snap-20260309-231551`)
- **Impact:** Data-modifying operation ignoring safety flag. Contrast with `freq destroy 999 --dry-run` which correctly shows `[DRY-RUN]` and aborts.
- **Priority:** Highest — if snapshot ignores `--dry-run`, other commands might too

#### CRIT-PDM-1: `pdm.sh` line 59 — `warn: command not found`

- **Commands:** `freq pdm status`, `freq pdm nodes`, `freq pdm vms` — all three hit this
- **Error:** `/opt/lowfreq/lib/pdm.sh: line 59: warn: command not found`
- **Root cause:** `warn` function is undefined in pdm.sh's scope. Likely needs the function name to be `_warn` or `log_warn` or the function isn't being sourced.
- **Note:** `freq pdm test` works fine — different code path that doesn't call `warn()`

#### CRIT-DESTROY-1: `freq destroy 100 --dry-run` — safety message missing context

- **Command:** `freq destroy 100 --dry-run`
- **Expected:** Clear message explaining WHY it refused (e.g., "VM 100 is a production VM")
- **Actual:** Only shows `Use 'freq destroy 100 --force' to override this safety check` — no header, no VM name, no explanation of what safety check failed
- **Impact:** User has no idea why destruction was blocked. The `--force` hint without context is confusing.

#### CRIT-PFSENSE-1: `freq pfsense services` — silent exit 255, zero output

- **Command:** `freq pfsense services` (when prod pfSense unreachable)
- **Expected:** Error message like "UNREACHABLE" (as `status` subcommand does)
- **Actual:** Exit code 255, completely empty output
- **Impact:** Unhandled SSH failure. Other pfSense subcommands (`status`, `rules`, `check`) handle unreachability gracefully.

#### CRIT-HEALTHSH-1: `health.sh` has no write-locking — concurrent modification broke entire tool

- **Observation:** During testing, another `code-dev` session modified `/opt/lowfreq/lib/health.sh` and introduced a syntax error on line 77. This broke ALL commands that load health.sh (`health`, `distros quirks`, `distros supported`, `version`, `snapshot`).
- **Impact:** A bad write to any shared .sh file can break the entire tool for all concurrent users
- **Note:** Bug was fixed by the same session ~3 minutes later. Transient but high-risk.

### WARNING

#### WARN-ARGORDER-1: `freq pfsense --target lab status` — wrong argument order silently fails

- **Command:** `freq pfsense --target lab status`
- **Expected:** pfSense lab status (or clear error about arg order)
- **Actual:** Silently shows usage text and exits 0
- **Correct syntax:** `freq pfsense status --target lab` (subcommand before flags)
- **Impact:** User puts flags before subcommand (natural pattern) and gets no error

#### WARN-VPN-1: `freq vpn wg show` — wrong subcommand name

- **Command:** `freq vpn wg show` — prints usage and exits
- **Correct:** `freq vpn wg status` — valid subcommands are: `status|peers|add|remove|genkey|stale`
- **Note:** Documentation/help may reference `show` but the actual subcommand is `status`

#### WARN-DISTROS-1: `freq distros info/quirks/supported` — bash error in usage message

- **Commands:** `freq distros info`, `freq distros quirks`, `freq distros supported` (all without args)
- **Actual output:** `/opt/lowfreq/lib/distros.sh: line 217: 1: Usage: ...`
- **Issue:** Error includes shell file path and line number. Should use `echo` or `die` for clean usage text.

#### WARN-BACKUP-1: `freq backup` — exits 0 with no action

- **Command:** `freq backup` (no subcommand)
- **Actual:** Shows "Usage: freq backup <host|status|config>" and exits 0
- **Expected:** Exit code 1 (no action taken)

#### WARN-MIGRATE-1: `freq migrate` — shows host picker instead of usage

- **Command:** `freq migrate` (no VMID)
- **Actual:** Shows host picker with 26 hosts
- **Expected:** "Usage: freq migrate <vmid>" (like `freq clone` and `freq destroy` do)

#### WARN-BOOTSTRAP-1: `freq bootstrap` — checks prerequisites before args

- **Command:** `freq bootstrap` (no IP)
- **Actual:** "sshpass required for bootstrap. Install: apt install sshpass"
- **Expected:** "Usage: freq bootstrap <ip>" first, then prerequisite checks

#### WARN-EXEC-1: `freq exec uptime` — no `--yes` flag for non-interactive use

- **Command:** `freq exec uptime`
- **Actual:** Shows target list (24 hosts) then "Aborted." (can't confirm non-interactively)
- **Expected:** Should support `--yes` flag like other commands

#### WARN-PFSENSE-2: Inconsistent unreachability handling across pfSense subcommands

- `freq pfsense status` -> shows "UNREACHABLE" (good)
- `freq pfsense states` -> shows "Active states: unknown" (vague)
- `freq pfsense rules` -> shows empty box (misleading — looks like no rules)
- `freq pfsense logs` -> shows empty box (misleading — looks like no logs)
- `freq pfsense services` -> exit 255, zero output (broken, CRIT above)

#### WARN-SERIAL-1: `freq serial` help lists duplicate subcommand entries

- `devices`, `attach`, and `probe-hw` are each listed twice in the help output

#### WARN-VAULT-1: `freq vault list` exit code ambiguity

- Shows "No vault found. Run: freq vault init" with exit 1
- Exit 1 for "not initialized" vs "error" could confuse scripts

### PASS (65 commands)

All tested without crashes. Key highlights:

| Command | Result |
|---|---|
| `freq list` | 18 VMs across 3 nodes |
| `freq vm-status 999` | 3 pass, 1 fail (SSH), 1 warn (cloud-init) |
| `freq vm-status 99999` | "VM '99999' not found" — correct rejection |
| `freq destroy 999 --dry-run` | Shows DRY-RUN box, asks name confirm, aborts — correct |
| `freq status` | 19 online, 7 offline, 26 total |
| `freq dashboard` | Full dashboard with load/memory/disk/uptime |
| `freq discover` | Found 3 unregistered VMs |
| `freq groups` | 11 groups listed |
| `freq vm-overview` | 3 nodes, 17 VMs, 16 running |
| `freq vmconfig 99999` | "VM 99999 not found in cluster" — correct |
| `freq images list` | 4 found, 7 missing |
| `freq truenas status` | Version 25.10.1, mega-pool ONLINE 63% |
| `freq truenas pools` | mega-pool ONLINE HEALTHY |
| `freq truenas shares` | 1 SMB, 3 NFS |
| `freq zfs status` | All pools ONLINE across 3 nodes |
| `freq zfs health` | "All pools healthy" (5 scrub warnings) |
| `freq audit --all --brief` | 24C, 3H, 7M, 19L, 3P |
| `freq harden check` | Fleet hardening matrix |
| `freq health` | Full infrastructure dashboard |
| `freq doctor` | 76 pass, 53 issues (permission warnings on dev VM) |
| `freq --json list` | Valid JSON output (18 VMs) |
| `freq nonexistent-command` | "Run 'freq help' for usage" exit 1 — correct |
| All missing-arg commands | Clean usage messages (passwd, new-user, clone, destroy, resize, ssh, exec) |

---

## PART 5: Lab Infrastructure (pfSense/TrueNAS/OPNsense)

*Tested manually during session*

### Lab pfSense (VM 980, 10.25.255.180)

- **Status:** pfSense 2.7.2-RELEASE running on pve03
- **Interfaces:** WAN (vtnet0) = 10.25.255.180/24, LAN (vtnet1) = 192.168.50.1/24
- **NICs:** 4 total (vtnet0-3: VLAN 2550/5/25/66) — mirrors prod pfSense NIC layout
- **SSH:** Enabled (sshd running), root password set to `changeme1234`
- **Problem:** Port 22 not reachable from VM 999 despite `easyrule pass wan tcp any any 22`. pfSense WAN firewall may need additional configuration or the rule didn't take effect. Needs console investigation of `sockstat -4l | grep :22` and `pfctl -sr | grep 22`.
- **Serial probe:** `freq serial capture 980` returns empty (0 bytes). Serial socket exists at `/var/run/qemu-server/980.serial0` on pve03 but socat reads EOF immediately. May need pfSense serial console output enabled in `/boot/loader.conf`.

### Lab TrueNAS (VM 981, 10.25.255.181)

- **Status:** Running on pve01, pingable from VM 999
- **API:** `freq truenas --target lab status` returns empty (BUG-SILENT-2 above)
- **Needs:** Verify TrueNAS web API is accessible on HTTPS, check if root password is set

### OPNsense Module

- **Location:** `/opt/lowfreq/lib/opnsense.sh` (206 lines)
- **Architecture:** REST API-based (not SSH like pfSense module)
- **Subcommands:** status, rules, wg, backup
- **Default target:** `--target lab` (safe — points at 10.25.255.180)
- **Current state:** No API credentials in vault. Fails with clear error: `!! No OPNsense API credentials in vault` + instructions to add them.
- **Note:** VM 980 runs pfSense, not OPNsense. The OPNsense module targets the same lab IP but uses OPNsense-specific API endpoints (`/api/core/firmware/status` etc.) that pfSense doesn't have. This module is currently untestable without an actual OPNsense instance.

---

## FINAL SUMMARY — All 4 Agents Complete

**Total tests executed: 160+**

| Severity | Count | Bug IDs |
|---|---|---|
| CRITICAL | 9 | CRIT-SNAPSHOT-1, CRIT-HOSTPICKER-1, CRIT-PDM-1, CRIT-PDM-FAILOVER-1, CRIT-DESTROY-1, CRIT-PFSENSE-1, CRIT-HEALTHSH-1, BUG-ICON-1, BUG-ICON-2 |
| WARNING | 18 | BUG-SILENT-1/2, BUG-HANG-1, WARN-ARGORDER-1, WARN-VPN-1, WARN-DISTROS-1, WARN-BACKUP-1, WARN-MIGRATE-1, WARN-BOOTSTRAP-1, WARN-EXEC-1, WARN-PFSENSE-2, WARN-SERIAL-1, WARN-VAULT-1, WARN-AUDIT-MENU-1, WARN-NOFEEDBACK-1, WARN-ICON-PRINTF-1, WARN-ICON-SU-1 |
| PASS | 145+ | 65 commands, 22 fleet/PDM scenarios, 67 menu/dispatch tests, 13 edge cases |
| BLOCKED | 2 | Lab pfSense SSH unreachable, OPNsense needs instance |

### Priority Fix Order

1. **CRIT-SNAPSHOT-1: `freq snapshot --dry-run` creates real snapshots** — data-modifying op ignoring safety flag. Highest priority.
2. **CRIT-HOSTPICKER-1: [F]/[T] host picker routes to prod not lab** — users select lab in picker but always hit prod. Safety issue.
3. **CRIT-PDM-1 + CRIT-PDM-FAILOVER-1: `pdm.sh:59 warn: command not found`** — undefined function breaks all PDM status commands AND causes intermittent total failure of SSH fallback on first PDM outage.
4. **BUG-ICON-1 + BUG-ICON-2 + WARN-ICON-PRINTF-1: Unicode icon mode completely non-functional** — three bugs combine to make the entire v3.3.1 dual-mode feature dead. (a) freq.conf clobbers env var, (b) core.sh self-references empty vars, (c) `\u` escapes stored as literal strings not interpreted.
5. **CRIT-DESTROY-1: Destroy safety message has no context** — tells user to `--force` but never says WHY it was blocked.
6. **CRIT-PFSENSE-1: `freq pfsense services` exit 255 zero output** — unhandled SSH failure while other subcommands handle it.
7. **CRIT-HEALTHSH-1: No write-lock on lib/ files** — concurrent session broke entire tool mid-test.
8. **BUG-SILENT-1/2: Silent exit 0 on lab targets** — pfSense and TrueNAS lab commands fail with no output, no error.
9. **WARN-ARGORDER-1: `--target lab` before subcommand silently fails** — natural argument order produces no error.

### What Works Well

- **Fleet status B2 layout** — grouping, categorization, [LAB]/[DEV] tags, source tracking all correct
- **PDM integration** — when it works, it's fast and accurate. 19 hosts via PDM in one call.
- **PDM-to-SSH failover** — subsequent runs after PDM failure produce identical layout via SSH
- **Menu system** — 17/20 mnemonic keys work, case sensitivity correct, all 9 submenus properly structured, zero crashes on any garbage input
- **Config file resilience** — missing/empty/corrupted configs produce clean error messages
- **Non-root handling** — clean permission errors, no crashes
- **PVE node resilience** — PDM-sourced data survives individual node outages
- **Parallel execution** — no race conditions on read-only commands
- **Version consistency** — 3.3.1 across all files
- **VM protection** — `freq destroy 100` correctly refuses (even if the message needs work)
- **`--json` output** — `freq --json list` produces valid JSON
- **65/82 commands** produce expected output with no crashes
