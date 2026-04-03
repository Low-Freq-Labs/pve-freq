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
| [F] | freq/api/docker_api.py | 395 | 1 fixed: compose-view missing operator auth |
| [F] | freq/api/observe.py | 439 | 3 fixed: trend_snapshot, sla_check, monitors_check missing auth |
| [F] | freq/api/secure.py | 328 | 1 fixed: harden missing operator auth |
| [A] | freq/api/state.py | 233 | CLEAN — write ops have admin auth |
| [A] | freq/api/auto.py | 409 | CLEAN — write ops have admin auth |
| [F] | freq/api/dr.py | 290 | 2 fixed: handle_backup and handle_zfs missing operator auth |
| [F] | freq/api/user.py | 86 | 3 fixed: create/promote/demote missing admin auth — privilege escalation |
| [A] | freq/api/plugin.py | 80 | CLEAN — read-only |
| [A] | freq/api/ops.py | 71 | CLEAN — read-only |
| [A] | freq/api/host.py | 49 | CLEAN — read-only |
| [A] | freq/api/helpers.py | 86 | CLEAN — utility functions |
| [A] | freq/api/v1_stubs.py | 169 | CLEAN — stubs only |
| [A] | freq/api/__init__.py | 68 | CLEAN — route registration |
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
| [A] | freq/cli.py | 3275 | CLEAN — CLI argument parsing, no direct shell injection |
| [A] | freq/modules/media.py | 2390 | CLEAN — SSH via ssh.py, docker commands validated |
| [A] | freq/modules/switch_orchestration.py | 1164 | CLEAN — SSH via ssh.py |
| [A] | freq/modules/alert.py | 739 | CLEAN — config-driven, no user input in commands |
| [A] | freq/modules/hosts.py | 725 | CLEAN — TOML parsing, no shell injection |
| [A] | freq/modules/event_network.py | 687 | CLEAN |
| [A] | freq/modules/plugin_manager.py | 663 | CLEAN — tarball path traversal checked |
| [A] | freq/modules/snmp.py | 512 | CLEAN — subprocess list args, no shell=True |
| [A] | freq/modules/config_management.py | 506 | CLEAN |
| [A] | freq/modules/lab.py | 452 | CLEAN |
| [A] | freq/modules/patch.py | 451 | CLEAN |
| [A] | freq/modules/schedule.py | 444 | NOTE — shell=True by design (admin cron jobs) |
| [A] | freq/modules/stack.py | 439 | CLEAN |
| [A] | freq/modules/specialist.py | 412 | CLEAN |
| [A] | freq/modules/users.py | 426 | CLEAN — shlex.quote used for passwords |
| [A] | freq/modules/plan.py | 565 | CLEAN |
| [A] | freq/modules/net_intelligence.py | 408 | CLEAN |
| [A] | freq/modules/migrate_vmware.py | 402 | CLEAN |
| [A] | freq/modules/cert.py | 397 | CLEAN |
| [A] | freq/modules/comply.py | 396 | CLEAN |
| [A] | freq/modules/dr.py | 395 | CLEAN |
| [A] | freq/modules/oncall.py | 392 | CLEAN |
| [A] | freq/modules/inventory.py | 392 | CLEAN |
| [A] | freq/modules/ipam.py | 390 | CLEAN |
| [A] | freq/modules/baseline.py | 389 | CLEAN |
| [A] | freq/modules/docs.py | 386 | CLEAN |
| [A] | freq/modules/backup_policy.py | 385 | CLEAN |
| [A] | freq/modules/report.py | 384 | CLEAN |
| [A] | freq/modules/benchmark.py | 381 | CLEAN |
| [A] | freq/modules/topology.py | 371 | CLEAN |
| [A] | freq/modules/cost_analysis.py | 369 | CLEAN |
| [A] | freq/modules/secrets.py | 367 | CLEAN |
| [A] | freq/modules/depmap.py | 367 | CLEAN |
| [A] | freq/modules/netmon.py | 360 | CLEAN |
| [A] | freq/modules/webhook.py | 353 | NOTE — shell=True by design (admin webhooks) |
| [A] | freq/modules/demo.py | 346 | CLEAN |
| [A] | freq/modules/storage.py | 343 | CLEAN |
| [A] | freq/modules/trend.py | 338 | CLEAN |
| [A] | freq/modules/audit.py | 334 | CLEAN |
| [A] | freq/modules/dns.py | 313 | CLEAN |
| [A] | freq/modules/vpn.py | 303 | CLEAN |
| [A] | freq/modules/infrastructure.py | 302 | CLEAN |
| [A] | freq/modules/logs.py | 291 | CLEAN |
| [A] | freq/modules/discover.py | 289 | CLEAN |
| [A] | freq/modules/engine_cmds.py | 286 | CLEAN |
| [A] | freq/modules/proxy.py | 279 | CLEAN |
| [A] | freq/modules/migrate_plan.py | 279 | CLEAN |
| [A] | freq/modules/synthetic_monitors.py | 277 | CLEAN |
| [A] | freq/modules/sla.py | 273 | CLEAN |
| [A] | freq/modules/compare.py | 270 | CLEAN |
| [A] | freq/modules/backup.py | 265 | CLEAN |
| [A] | freq/modules/proxy_management.py | 249 | CLEAN |
| [A] | freq/modules/gwipe.py | 246 | CLEAN |
| [A] | freq/modules/cert_management.py | 237 | CLEAN |
| [A] | freq/modules/automation.py | 237 | CLEAN |
| [A] | freq/modules/health.py | 230 | CLEAN |
| [A] | freq/modules/dns_management.py | 217 | CLEAN |
| [A] | freq/modules/incident.py | 215 | CLEAN |
| [A] | freq/modules/deploy_agent.py | 211 | CLEAN |
| [A] | freq/modules/rollback.py | 209 | CLEAN |
| [A] | freq/modules/hardware.py | 208 | CLEAN |
| [A] | freq/modules/bootstrap.py | 203 | CLEAN |
| [A] | freq/modules/metrics.py | 199 | CLEAN |
| [A] | freq/modules/comms.py | 197 | CLEAN |
| [A] | freq/modules/db.py | 187 | CLEAN |
| [A] | freq/modules/fim.py | 184 | CLEAN |
| [A] | freq/modules/iac.py | 165 | CLEAN |
| [A] | freq/modules/docker_mgmt.py | 163 | CLEAN |
| [A] | freq/modules/wol.py | 160 | CLEAN |
| [A] | freq/modules/selfupdate.py | 159 | CLEAN |
| [A] | freq/modules/harden.py | 158 | CLEAN |
| [A] | freq/modules/vuln.py | 117 | CLEAN |
| [A] | freq/modules/journal.py | 112 | CLEAN |
| [A] | freq/modules/why.py | 104 | CLEAN |
| [A] | freq/modules/distros.py | 88 | CLEAN |
| [A] | freq/modules/web_ui.py | 70 | CLEAN |
| [A] | freq/modules/__init__.py | 1 | CLEAN |
| [A] | freq/core/doctor.py | 391 | CLEAN |
| [A] | freq/core/fmt.py | 372 | CLEAN |
| [A] | freq/core/types.py | 306 | CLEAN |
| [A] | freq/core/platform.py | 209 | CLEAN |
| [A] | freq/core/packages.py | 199 | CLEAN |
| [A] | freq/core/personality.py | 181 | CLEAN |
| [A] | freq/core/validate.py | 177 | CLEAN |
| [A] | freq/core/services.py | 173 | CLEAN |
| [A] | freq/core/preflight.py | 165 | CLEAN |
| [A] | freq/core/remote_platform.py | 153 | CLEAN |
| [A] | freq/core/resolve.py | 142 | CLEAN |
| [A] | freq/core/log.py | 120 | CLEAN |
| [A] | freq/core/plugins.py | 77 | CLEAN |
| [A] | freq/core/compat.py | 47 | CLEAN |
| [A] | freq/core/__init__.py | 1 | CLEAN |
| [A] | freq/deployers/switch/cisco.py | 740 | NOTE — VLAN/port params from config, not user API input |
| [A] | freq/deployers/nas/truenas.py | 149 | NOTE — password in stdin pipe, brief ps visibility |
| [A] | freq/deployers/__init__.py | 83 | CLEAN |
| [A] | freq/deployers/firewall/opnsense.py | 27 | CLEAN |
| [A] | freq/deployers/switch/ubiquiti.py | 26 | CLEAN |
| [A] | freq/deployers/server/linux.py | 26 | CLEAN |
| [A] | freq/deployers/bmc/ilo.py | 26 | CLEAN |
| [A] | freq/deployers/firewall/pfsense.py | 21 | CLEAN |
| [A] | freq/deployers/bmc/idrac.py | 21 | CLEAN |
| [A] | freq/jarvis/agent.py | 736 | CLEAN |
| [A] | freq/jarvis/rules.py | 472 | CLEAN |
| [A] | freq/jarvis/capacity.py | 469 | CLEAN |
| [F] | freq/jarvis/chaos.py | 438 | FIXED — service name injection validated |
| [A] | freq/jarvis/gitops.py | 385 | CLEAN |
| [A] | freq/jarvis/notify.py | 362 | CLEAN |
| [A] | freq/jarvis/federation.py | 322 | CLEAN |
| [A] | freq/jarvis/provision.py | 307 | CLEAN |
| [A] | freq/jarvis/cost.py | 287 | CLEAN |
| [A] | freq/jarvis/learn.py | 286 | CLEAN |
| [A] | freq/jarvis/playbook.py | 260 | CLEAN |
| [A] | freq/jarvis/patrol.py | 175 | CLEAN |
| [A] | freq/jarvis/risk.py | 168 | CLEAN |
| [A] | freq/jarvis/sweep.py | 123 | CLEAN |
| [A] | freq/jarvis/__init__.py | 5 | CLEAN |
| [A] | freq/engine/runner.py | 245 | NOTE — policy paths from config files |
| [A] | freq/engine/policy.py | 163 | CLEAN |
| [A] | freq/engine/policies/ssh_hardening.py | 52 | CLEAN |
| [A] | freq/engine/policies/ntp_sync.py | 37 | CLEAN |
| [A] | freq/engine/policies/rpcbind.py | 35 | CLEAN |
| [A] | freq/engine/policies/__init__.py | 10 | CLEAN |
| [A] | freq/engine/__init__.py | 1 | CLEAN |
| [A] | freq/tui/menu.py | 1524 | CLEAN — CLI only |
| [A] | freq/tui/__init__.py | 1 | CLEAN |
| [A] | freq/agent_collector.py | 322 | CLEAN |
| [A] | freq/__main__.py | 12 | CLEAN |
| [A] | freq/__init__.py | 5 | CLEAN |
| [A] | freq/data/__init__.py | 8 | CLEAN |
| [A] | freq/data/web/__init__.py | 1 | CLEAN |
| [A] | freq/data/conf-templates/plugins/example_ping.py | 47 | CLEAN |

## Tier 4: Frontend + Docker (~10.7K lines)
| Status | File | Lines | Findings |
|--------|------|-------|----------|
| [A] | freq/data/web/js/app.js | 8628 | NOTE — 833 innerHTML uses, low-risk (internal tool, data from trusted PVE/SSH) |
| [A] | freq/data/web/app.html | 1658 | CLEAN — CSP headers set by serve.py, no inline scripts |
| [A] | pve-freq-docker/Dockerfile | 82 | CLEAN — non-root user, tini, no secrets |
| [A] | pve-freq-docker/compose.yml | 77 | CLEAN — read_only root, no-new-privileges, resource limits |
| [A] | pve-freq-docker/build.sh | 60 | CLEAN |
| [A] | pve-freq-docker/docker-entrypoint.sh | 49 | CLEAN — drops to non-root, proper permissions |
| [A] | pve-freq-docker/.github/workflows/docker.yml | 114 | CLEAN |

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
