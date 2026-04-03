# Security Audit Tracker — S017
**Started:** 2026-04-03
**Method:** Read every line, fix CRITICAL/HIGH immediately, commit per tier

## Legend
- [ ] = pending
- [A] = audited, no issues
- [F] = audited, issues found and FIXED
- [S] = spot-check only (audited in S016)

---

## Tier 1: Security Foundation (~18K lines)
| Status | File | Lines | Findings |
|--------|------|-------|----------|
| [A] | freq/core/ssh.py | 388 | CLEAN — no shell=True, proper escaping, sshpass -f |
| [F] | freq/modules/serve.py | 7761 | 11 fixed: dispatch error leak, 8 missing auth (agent create/destroy, media restart/update, lab tool proxy/config/save, container action) |
| [A] | freq/modules/init_cmd.py | 4172 | CLEAN — CLI-only, interactive root, all SSH via ssh.py |
| [F] | freq/api/auth.py | 238 | 2 fixed: GET password-change blocked, error detail leak plugged |
| [A] | freq/modules/vault.py | 354 | CLEAN — AES-256-CBC, machine-bound key, no user input in commands |
| [A] | freq/core/config.py | 818 | CLEAN — TOML parsing, safe defaults, input validation |
| [A] | freq/modules/pve.py | 600 | CLEAN — SSH via ssh.py, API via urllib with token header, input validated |
| [A] | freq/modules/vm.py | 1714 | CLEAN — validated inputs (valid_label, int vmid), SSH via ssh.py |
| [A] | freq/modules/fleet.py | 1552 | CLEAN — subprocess list args, no shell=True, SSH via ssh.py |
| [A] | freq/modules/firewall.py | 412 | CLEAN — all commands hardcoded, SSH via ssh.py |

## Tier 2: API Layer (~11K lines)
| Status | File | Lines | Findings |
|--------|------|-------|----------|
| [F] | freq/api/fleet.py | 1161 | 1 fixed: handle_exec missing admin auth — arbitrary command execution |
| [F] | freq/api/vm.py | 1080 | 16 fixed: ALL write handlers missing auth (create/destroy/migrate=admin, power/resize/snapshot/rename/tag=operator) |
| [F] | freq/api/ct.py | 597 | 1 fixed: handle_ct_power missing operator auth |
| [ ] | freq/api/docker_api.py | 395 | |
| [ ] | freq/api/observe.py | 439 | |
| [ ] | freq/api/secure.py | 328 | |
| [ ] | freq/api/state.py | 233 | |
| [ ] | freq/api/auto.py | 409 | |
| [F] | freq/api/dr.py | 290 | 2 fixed: handle_backup and handle_zfs missing operator auth |
| [F] | freq/api/user.py | 86 | 3 fixed: create/promote/demote missing admin auth — privilege escalation |
| [ ] | freq/api/plugin.py | 80 | |
| [ ] | freq/api/ops.py | 71 | |
| [ ] | freq/api/host.py | 49 | |
| [ ] | freq/api/helpers.py | 86 | |
| [ ] | freq/api/v1_stubs.py | 169 | |
| [ ] | freq/api/__init__.py | 68 | |
| [S] | freq/api/opnsense.py | 772 | audited S016 |
| [S] | freq/api/fw.py | 660 | audited S016 |
| [S] | freq/api/store.py | 562 | audited S016 |
| [S] | freq/api/net.py | 477 | audited S016 |
| [S] | freq/api/ipmi.py | 354 | audited S016 |
| [S] | freq/api/redfish.py | 484 | audited S016 |
| [S] | freq/api/synology.py | 316 | audited S016 |
| [S] | freq/api/bench.py | 382 | audited S016 |
| [S] | freq/api/logs.py | 193 | audited S016 |
| [S] | freq/api/backup_verify.py | 257 | audited S016 |
| [S] | freq/api/terminal.py | 479 | audited S016 |
| [S] | freq/api/hw.py | 279 | audited S016 |

## Tier 3: Modules + Core + Deployers + Engine + Jarvis (~40K lines)
| Status | File | Lines | Findings |
|--------|------|-------|----------|
| [ ] | freq/cli.py | 3275 | |
| [ ] | freq/modules/media.py | 2390 | |
| [ ] | freq/modules/switch_orchestration.py | 1164 | |
| [ ] | freq/modules/alert.py | 739 | |
| [ ] | freq/modules/hosts.py | 725 | |
| [ ] | freq/modules/event_network.py | 687 | |
| [ ] | freq/modules/plugin_manager.py | 663 | |
| [ ] | freq/modules/snmp.py | 512 | |
| [ ] | freq/modules/config_management.py | 506 | |
| [ ] | freq/modules/lab.py | 452 | |
| [ ] | freq/modules/patch.py | 451 | |
| [ ] | freq/modules/schedule.py | 444 | |
| [ ] | freq/modules/stack.py | 439 | |
| [ ] | freq/modules/specialist.py | 412 | |
| [ ] | freq/modules/users.py | 426 | |
| [ ] | freq/modules/plan.py | 565 | |
| [ ] | freq/modules/net_intelligence.py | 408 | |
| [ ] | freq/modules/migrate_vmware.py | 402 | |
| [ ] | freq/modules/cert.py | 397 | |
| [ ] | freq/modules/comply.py | 396 | |
| [ ] | freq/modules/dr.py | 395 | |
| [ ] | freq/modules/oncall.py | 392 | |
| [ ] | freq/modules/inventory.py | 392 | |
| [ ] | freq/modules/ipam.py | 390 | |
| [ ] | freq/modules/baseline.py | 389 | |
| [ ] | freq/modules/docs.py | 386 | |
| [ ] | freq/modules/backup_policy.py | 385 | |
| [ ] | freq/modules/report.py | 384 | |
| [ ] | freq/modules/benchmark.py | 381 | |
| [ ] | freq/modules/topology.py | 371 | |
| [ ] | freq/modules/cost_analysis.py | 369 | |
| [ ] | freq/modules/secrets.py | 367 | |
| [ ] | freq/modules/depmap.py | 367 | |
| [ ] | freq/modules/netmon.py | 360 | |
| [ ] | freq/modules/webhook.py | 353 | |
| [ ] | freq/modules/demo.py | 346 | |
| [ ] | freq/modules/storage.py | 343 | |
| [ ] | freq/modules/trend.py | 338 | |
| [ ] | freq/modules/audit.py | 334 | |
| [ ] | freq/modules/dns.py | 313 | |
| [ ] | freq/modules/vpn.py | 303 | |
| [ ] | freq/modules/infrastructure.py | 302 | |
| [ ] | freq/modules/logs.py | 291 | |
| [ ] | freq/modules/discover.py | 289 | |
| [ ] | freq/modules/engine_cmds.py | 286 | |
| [ ] | freq/modules/proxy.py | 279 | |
| [ ] | freq/modules/migrate_plan.py | 279 | |
| [ ] | freq/modules/synthetic_monitors.py | 277 | |
| [ ] | freq/modules/sla.py | 273 | |
| [ ] | freq/modules/compare.py | 270 | |
| [ ] | freq/modules/backup.py | 265 | |
| [ ] | freq/modules/proxy_management.py | 249 | |
| [ ] | freq/modules/gwipe.py | 246 | |
| [ ] | freq/modules/cert_management.py | 237 | |
| [ ] | freq/modules/automation.py | 237 | |
| [ ] | freq/modules/health.py | 230 | |
| [ ] | freq/modules/dns_management.py | 217 | |
| [ ] | freq/modules/incident.py | 215 | |
| [ ] | freq/modules/deploy_agent.py | 211 | |
| [ ] | freq/modules/rollback.py | 209 | |
| [ ] | freq/modules/hardware.py | 208 | |
| [ ] | freq/modules/bootstrap.py | 203 | |
| [ ] | freq/modules/metrics.py | 199 | |
| [ ] | freq/modules/comms.py | 197 | |
| [ ] | freq/modules/db.py | 187 | |
| [ ] | freq/modules/fim.py | 184 | |
| [ ] | freq/modules/iac.py | 165 | |
| [ ] | freq/modules/docker_mgmt.py | 163 | |
| [ ] | freq/modules/wol.py | 160 | |
| [ ] | freq/modules/selfupdate.py | 159 | |
| [ ] | freq/modules/harden.py | 158 | |
| [ ] | freq/modules/vuln.py | 117 | |
| [ ] | freq/modules/journal.py | 112 | |
| [ ] | freq/modules/why.py | 104 | |
| [ ] | freq/modules/distros.py | 88 | |
| [ ] | freq/modules/web_ui.py | 70 | |
| [ ] | freq/modules/__init__.py | 1 | |
| [ ] | freq/core/doctor.py | 391 | |
| [ ] | freq/core/fmt.py | 372 | |
| [ ] | freq/core/types.py | 306 | |
| [ ] | freq/core/platform.py | 209 | |
| [ ] | freq/core/packages.py | 199 | |
| [ ] | freq/core/personality.py | 181 | |
| [ ] | freq/core/validate.py | 177 | |
| [ ] | freq/core/services.py | 173 | |
| [ ] | freq/core/preflight.py | 165 | |
| [ ] | freq/core/remote_platform.py | 153 | |
| [ ] | freq/core/resolve.py | 142 | |
| [ ] | freq/core/log.py | 120 | |
| [ ] | freq/core/plugins.py | 77 | |
| [ ] | freq/core/compat.py | 47 | |
| [ ] | freq/core/__init__.py | 1 | |
| [ ] | freq/deployers/switch/cisco.py | 740 | |
| [ ] | freq/deployers/nas/truenas.py | 149 | |
| [ ] | freq/deployers/__init__.py | 83 | |
| [ ] | freq/deployers/firewall/opnsense.py | 27 | |
| [ ] | freq/deployers/switch/ubiquiti.py | 26 | |
| [ ] | freq/deployers/server/linux.py | 26 | |
| [ ] | freq/deployers/bmc/ilo.py | 26 | |
| [ ] | freq/deployers/firewall/pfsense.py | 21 | |
| [ ] | freq/deployers/bmc/idrac.py | 21 | |
| [ ] | freq/jarvis/agent.py | 736 | |
| [ ] | freq/jarvis/rules.py | 472 | |
| [ ] | freq/jarvis/capacity.py | 469 | |
| [ ] | freq/jarvis/chaos.py | 438 | |
| [ ] | freq/jarvis/gitops.py | 385 | |
| [ ] | freq/jarvis/notify.py | 362 | |
| [ ] | freq/jarvis/federation.py | 322 | |
| [ ] | freq/jarvis/provision.py | 307 | |
| [ ] | freq/jarvis/cost.py | 287 | |
| [ ] | freq/jarvis/learn.py | 286 | |
| [ ] | freq/jarvis/playbook.py | 260 | |
| [ ] | freq/jarvis/patrol.py | 175 | |
| [ ] | freq/jarvis/risk.py | 168 | |
| [ ] | freq/jarvis/sweep.py | 123 | |
| [ ] | freq/jarvis/__init__.py | 5 | |
| [ ] | freq/engine/runner.py | 245 | |
| [ ] | freq/engine/policy.py | 163 | |
| [ ] | freq/engine/policies/ssh_hardening.py | 52 | |
| [ ] | freq/engine/policies/ntp_sync.py | 37 | |
| [ ] | freq/engine/policies/rpcbind.py | 35 | |
| [ ] | freq/engine/policies/__init__.py | 10 | |
| [ ] | freq/engine/__init__.py | 1 | |
| [ ] | freq/tui/menu.py | 1524 | |
| [ ] | freq/tui/__init__.py | 1 | |
| [ ] | freq/agent_collector.py | 322 | |
| [ ] | freq/__main__.py | 12 | |
| [ ] | freq/__init__.py | 5 | |
| [ ] | freq/data/__init__.py | 8 | |
| [ ] | freq/data/web/__init__.py | 1 | |
| [ ] | freq/data/conf-templates/plugins/example_ping.py | 47 | |

## Tier 4: Frontend + Docker (~10.7K lines)
| Status | File | Lines | Findings |
|--------|------|-------|----------|
| [ ] | freq/data/web/js/app.js | 8628 | |
| [ ] | freq/data/web/app.html | 1658 | |
| [ ] | pve-freq-docker/Dockerfile | 82 | |
| [ ] | pve-freq-docker/compose.yml | 77 | |
| [ ] | pve-freq-docker/build.sh | 60 | |
| [ ] | pve-freq-docker/docker-entrypoint.sh | 49 | |
| [ ] | pve-freq-docker/.github/workflows/docker.yml | 114 | |

---

## Findings Log
Format: `[SEVERITY] file:line — description → FIX applied`

### Tier 1+2 Findings (34 issues fixed)

**CRITICAL — Auth Bypass (24 handlers had no authentication):**
- `[CRITICAL] freq/api/fleet.py:297 — handle_exec: arbitrary command execution across fleet, NO AUTH → admin auth added`
- `[CRITICAL] freq/api/vm.py:50,84,335,639,729,787 — create/destroy/change-id/add-disk/clone/migrate: NO AUTH → admin auth added`
- `[CRITICAL] freq/api/user.py:26,42,60 — create/promote/demote: privilege escalation, NO AUTH → admin auth added`
- `[HIGH] freq/api/vm.py:107,129,165,245,307,408,481,528,691 — snapshot/resize/power/rename/delete-snap/add-nic/clear-nics/change-ip/tag: NO AUTH → operator auth added`
- `[HIGH] freq/api/ct.py:174 — handle_ct_power: container power control, NO AUTH → operator auth added`
- `[HIGH] freq/api/dr.py:28,256 — handle_backup/handle_zfs: write ops, NO AUTH → operator auth added`
- `[HIGH] freq/modules/serve.py:4766,4801 — agent create/destroy: VM lifecycle, NO AUTH → admin auth added`
- `[HIGH] freq/modules/serve.py:5174,5231 — media restart/update: container ops, NO AUTH → operator/admin auth added`
- `[HIGH] freq/modules/serve.py:6821 — container action: restart/stop/start, NO AUTH → operator auth added`
- `[HIGH] freq/modules/serve.py:6343,6362,6380 — lab tool proxy/config/save: vault access, NO AUTH → operator/admin auth added`

**CRITICAL — Input Validation:**
- `[CRITICAL] freq/api/auth.py:210-218 — password change accepted GET with password in URL → POST-only enforced`

**HIGH — Information Disclosure:**
- `[HIGH] freq/modules/serve.py:1581 — dispatch error handler leaked str(e) to client → generic error message`
- `[HIGH] freq/api/auth.py:238 — password change error leaked internal details → generic error message`

### Tier 2 Findings

### Tier 3 Findings

### Tier 4 Findings
