> Historical snapshot: this audit captures the repo state and command surface as of April 2, 2026. Old command names, counts, and gaps are preserved here as audit evidence, not current operator guidance. Use current docs and `freq help` for the shipped interface.

# Deep Audit Findings — S017

**Date:** 2026-04-03
**Method:** 10 parallel agents, every line read, cross-file analysis
**Scope:** 174 Python files (70K lines), 8.6K JS, 1.6K HTML, 382 Docker
**Status:** ALL ISSUES FIXED — S017/S018 (2026-04-03)

---

## WILL CRASH AT RUNTIME (fix immediately)

| # | File:Line | Issue |
|---|-----------|-------|
| 1 | `api/vm.py:963` | `is_protected_vmid(vmid)` called with 1 arg, needs 3. TypeError on rollback endpoint. |
| 2 | `api/terminal.py:140` | `cfg.service_account` doesn't exist on FreqConfig. Should be `cfg.ssh_service_account`. Every web terminal session hits this. |
| 3 | `modules/media.py:2110` | `_cmd_gpu()` passes ContainerVM as first arg to `_docker_cmd()` instead of cfg. AttributeError guaranteed. |
| 4 | `jarvis/chaos.py:415` | Status check compares `result.status == "pass"` but run_experiment sets `"completed"`. ALL chaos experiments report wrong status. |

## SECURITY (exploitable)

| # | File:Line | Issue |
|---|-----------|-------|
| 5 | `app.js:5057-5103` | **Shell injection in fleet user management.** Password interpolated directly into shell command: `echo "'+user+':'+pass+'" | chpasswd`. Backticks, `$()`, double quotes in password = RCE on all fleet hosts. |
| 6 | `app.js:4884` | **Vault unlock doesn't verify password.** Password field is cosmetic — any value works if username matches admin. False sense of security. |
| 7 | `app.js:78 vs 3232` | **Two different `_esc()` functions.** Second overwrites first, missing single-quote escaping. Everything after line 3232 has weaker XSS protection. |
| 8 | `init_cmd.py:3093` | **`--fix` mode deploys EMPTY passwords.** `ctx["svc_pass"]` is always `""`. Every host fixed by `freq init --fix` gets freq-admin with NO password. |
| 9 | `init_cmd.py:2107` | **SSH pubkey not sanitized in inline shell.** Pubkey comment with single quote breaks shell quoting = RCE on fleet hosts during init. |

## SILENTLY DOES NOTHING (looks like it works, doesn't)

| # | File:Line | Issue |
|---|-----------|-------|
| 10 | `init_cmd.py:2600` | **Switch uninstall sends config via SSH exec, not stdin.** IOS requires stdin for `configure terminal`. Uninstall silently fails — FREQ account stays on switch. |
| 11 | `init_cmd.py:3946` | **Headless init writes success marker on failure.** `freq init --check` says "initialized" even when deployment failed. Next run skips deployment. |
| 12 | `fleet.py:1138-1254` | **Key rotation never removes old keys.** Deploys new key but old key stays in authorized_keys forever. Not rotating — just adding. |
| 13 | `modules/media.py:1198` | **_cmd_scan sends no API key.** Makes raw curl without auth header. Sonarr/Radarr returns 401. Scan "succeeds" but nothing happens. |
| 14 | `modules/media.py:1366` | **_indexers_sync sends empty POST body.** Prowlarr command API requires JSON body. Does nothing. |
| 15 | `deployers/nas/truenas.py:146` | **TrueNAS remove() uses userdel.** Deploy uses midclt (persists), remove uses userdel (doesn't persist). Account comes back after TrueNAS update. |
| 16 | `jarvis/gitops.py:342` | **GitOps sync/apply ignores configured branch.** Always uses "main" regardless of freq.toml `[gitops] branch`. |
| 17 | `api/vm.py:1024` | **Stale snapshots endpoint never filters by age.** Returns ALL snapshots but reports `threshold_days`. Lies. |
| 18 | `jarvis/provision.py:186` | **ZFS format detection keyed wrong.** `cfg.pve_storage` keyed by node name, code looks up by pool name. Never matches. Double copy-on-write on ZFS. |

## LOGIC BUGS (wrong behavior)

| # | File:Line | Issue |
|---|-----------|-------|
| 19 | `init_cmd.py:792` | **Return value mismatch.** Returns `1` (truthy) on failure. Caller checks `if not result` — `not 1` is False, so init continues with invalid username. |
| 20 | `init_cmd.py:1980` | **Wrong password stored for devices.** Writes `svc_pass` (freq-admin password) as "device password" for iDRAC/switch. Switch SSH will use the wrong password. |
| 21 | `fleet.py:227` | **cmd_exec always returns 0.** Partial fleet failures masked. CI/scripts can't detect failure. |
| 22 | `vm.py:584` | **cmd_resize has no safety check and runs on wrong node.** Uses `_find_node()` (any node) instead of `_find_vm_node()`. Also no protected-VM check. |
| 23 | `vm.py:136-162` | **_apply_cloudinit never checks return values.** 5-6 PVE commands, none checked. Partially configured cloud-init worse than total failure. |
| 24 | `api/vm.py:106` | **API destroy uses --skiplock.** Bypasses PVE locks. CLI destroy does NOT. API is more destructive than CLI. |
| 25 | `vm.py:644` | **Disk resize hardcodes "scsi0".** If boot disk is virtio0 or scsi1, resize hits wrong disk. |
| 26 | `jarvis/chaos.py:121` | **VMID 800-899 "hard block" not implemented.** Docstring claims it, code doesn't enforce it. |
| 27 | `jarvis/gitops.py:278` | **Rollback leaves dirty working tree.** `git checkout <hash> -- .` doesn't move HEAD. Next pull creates merge conflicts. |
| 28 | `api/vm.py:317` | **Operator precedence bug in snapshot filter.** `not line or "current" in line.lower() and "->" in line` — `and` binds tighter than `or`. Masked by secondary check but fragile. |
| 29 | `init_cmd.py:820` | **Sudo check runs from root, always passes.** `sudo -u X sudo -n true` from root doesn't test X's sudo config. |
| 30 | `modules/media.py:1028` | **Gluetun port hardcoded to 8000.** Ignores container.port from registry. |

## DEAD CODE (remove in cleanup)

| Category | Lines | Details |
|----------|-------|---------|
| serve.py orphan methods | ~4,000-5,000 | 162 `_serve_*` methods replaced by v1 API handlers, never deleted |
| Duplicate functions | ~200 | `_find_node()` vs `_find_reachable_node()` vs `_find_reachable_pve_node()` (3 versions) |
| Dead FreqConfig fields | 3 | `vm_bios`, `vm_domain`, `nic_mtu` — loaded, never read |
| Dead type definitions | 2 | `VMCategory` enum, `PermissionTier` enum — never imported |
| Dead frontend constants | 28 | API.XXX constants defined but never used in any fetch call |
| Phantom config keys | 3 | `[pve] ssh_user`, `[vm.defaults] ci_user`, `[pfsense]` section — documented, never parsed |
| vm.py cmd_sandbox | ~100 | Nearly identical to cmd_clone, will diverge |
| Old DASHBOARD_HTML | 240 | Entire legacy dashboard at /old route |

## UI BUGS (Sonny sees these)

| # | File:Line | Issue |
|---|-----------|-------|
| 31 | `app.js:176` | **DEBUG message on login screen.** `DEBUG: user=[sonny] pass_len=8` shows every login. |
| 32 | `app.js:4483` | **Rollback tab broken.** References `vm-tools-form` instead of `vm-form`. Nothing appears. |
| 33 | `app.js:1256` | **SSE has no auth token.** EventSource can't send headers. Either security hole or silent failure. |
| 34 | `app.js:1366` | **4-second delay before fleet render.** setTimeout(4000) even if data is already available. |
| 35 | `app.js:1013` | **Summary stat counts go stale.** querySelectorAll result never used. Counts don't update between page loads. |
| 36 | `app.js:4757` | **Literal `\n` in snapshot text.** Double-escaped newline shows `\n\nLive migration: BLOCKED` as text. |
| 37 | `app.js:1174` | **Sparkline CSS variable in canvas.** `var(--purple-light)` not resolved by canvas. Invisible fallback lines. |
| 38 | 11 fetch calls | **Empty .catch(function(){}).** API failures silently swallowed — no toast, no error, loading never clears. |

## CONFIG SYSTEM ISSUES

| # | Issue |
|---|-------|
| 39 | `is_prod()` relies on magic category name strings ("personal", "infrastructure", "prod_media", "prod_other"). VMCategory enum exists to enforce these but is never used. Category named "production" silently treated as non-production. |
| 40 | "restart" and "clone" tier actions defined in fleet-boundaries.toml but never checked by `_check_vm_permission()`. Dead permission entries. |
| 41 | operator and admin tiers have identical action lists. Three-tier system collapses to two tiers. |
| 42 | `cfg.snmp_community` not on FreqConfig, not in TOML loader. Always falls back to hardcoded default. Unconfigurable. |
| 43 | `opnsense_ip`, `synology_ip`, `[[monitor]]` section — loaded by code but not in freq.toml.example. Users can't discover them. |

## ARCHITECTURE ISSUES

| # | Issue |
|---|-------|
| 44 | **Circular imports:** deployers import from init_cmd, init_cmd imports from deployers. Deploy logic is in the wrong file. |
| 45 | **3 versions of "find PVE node":** vm.py, pve.py, serve.py — different behavior, used inconsistently. api/vm.py uses BOTH within the same file. |
| 46 | **Stub deployers with inconsistent return types:** ubiquiti, ilo, opnsense return (False, str) tuples while others return bool. |
| 47 | **api/vm.py imports serve.py privates:** `_bg_cache`, `_bg_lock`, `_find_reachable_pve_node`. Circular dependency, can't function without server running. |

---

## TOTAL COUNTS

| Severity | Count |
|----------|-------|
| Will crash at runtime | 4 |
| Security (exploitable) | 5 |
| Silently does nothing | 9 |
| Logic bugs (wrong behavior) | 12 |
| Dead code (lines) | ~5,000+ |
| UI bugs (user-visible) | 8+ |
| Config system issues | 5 |
| Architecture issues | 4 |
| **TOTAL ISSUES** | **80+** |

---

## FROM E2E DATA FLOW TRACES (5 flows traced end-to-end)

| # | Flow | Issue |
|---|------|-------|
| 48 | Health | **SSE endpoint /api/events has NO auth.** Anyone on the network gets live fleet telemetry — host IPs, health changes, alerts, VM state. EventSource can't send Bearer tokens. |
| 49 | Health | **/api/health has no auth.** Full fleet health data (IPs, CPU, RAM, disk, docker counts) exposed without login. |
| 50 | All VMs | **All VM operations use GET instead of POST.** Create, destroy, power, migrate — all via query params. Browser prefetch, crawlers, or cached proxies could trigger destructive ops. |
| 51 | Setup | **Race condition: two simultaneous setup wizards.** Both can create admin accounts. Last write wins, no conflict detection. |
| 52 | Setup | **Post-setup dashboard empty for ~60s.** Background sync hasn't run yet. User sees "0 VMs across 0 nodes." |
| 53 | Container | **Container name matching uses config key, not Docker name.** If Docker container is `sonarr-v4` but config key is `sonarr`, restart fails silently. |
| 54 | VM Create | **VMID floor override doesn't check existence.** Sets vmid=5000 but 5000 might already exist. No retry. |
| 55 | VM Create | **No partial failure cleanup.** Half-created VM stays in PVE on failure. |

## FROM CLI + CONFIG AUDIT

| # | File:Line | Issue |
|---|-----------|-------|
| 56 | `config.py:365` | **`fmt` not imported — hosts.conf migration crashes.** NameError when legacy hosts.conf auto-migration runs. |
| 57 | `config.py:235` | **PermissionError not caught in load_toml.** Root-owned config file crashes instead of returning {}. |
| 58 | `config.py:462` | **protected_ranges format not validated.** Flat list `[900, 999]` crashes the `for start, end` unpack. |
| 59 | `cli.py:133` | **Global --json flag never read.** Registered on root parser, zero uses anywhere. |
| 60 | `cli.py:552` | **`host edit` silently does `list`.** Action "edit" not handled, falls through to list. |
| 61 | `cli.py:1788-1955` | **Help command missing 10+ domains.** event, vpn, specialist, lab, many sub-domains not listed. |
| 62 | `cli.py:1914` | **`store zfs` in help but no parser.** Users told to run a command that doesn't exist. |

## FROM CROSS-FILE DEAD CODE ANALYSIS

| Category | Count | Lines |
|----------|-------|-------|
| Dead serve.py methods (replaced by api/) | 161 methods | ~3,679 |
| Dead standalone functions | 8 functions | ~80 |
| Dead imports (unused across 60+ files) | 110 imports | ~110 |
| **serve.py is 47% dead code** | | **~3,679 of 7,779 lines** |

## FULL ISSUE COUNTS (UPDATED)

| Severity | Count |
|----------|-------|
| Will crash at runtime | 7 |
| Security (exploitable) | 7 |
| Silently does nothing | 9 |
| Logic bugs (wrong behavior) | 16 |
| Dead code | ~3,900 lines across 282 items |
| UI bugs (user-visible) | 10 |
| Config system issues | 8 |
| Architecture issues | 4 |
| E2E flow issues | 8 |
| CLI help/UX issues | 4 |
| **TOTAL DISTINCT ISSUES** | **80+** |
