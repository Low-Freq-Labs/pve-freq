# TASKBOARD — DC01 4-Worker Audit Session

> Last updated: 2026-02-24 S043 — Fixed pvestatd hang on both pve01/pve03 (NFS storage timeout killed all VM status display for 4 days). Cluster health verified (2-node quorate, pve02 dropped from membership). pve02 homework updated with current state and TICKET-0008 removal recommendation. Lesson #39 added. 16/16 containers running.
> Maintained by: Master Orchestrator

---

## COMPLETED PROJECT: Docker Infrastructure Overhaul — Local + NFS Restructure

**Status:** COMPLETE — Executed S032-20260220
**Plan File:** `~/Jarvis & Sonny's Memory/DC01-Docker-Infrastructure-Overhaul-Plan.md`
**WIP File:** `~/dc01-overhaul/infra/WIP-DOCKER-OVERHAUL.md`
**Result:** All 13 containers running from local `/opt/dc01/` on all 5 VMs. NFS `plex/` → `media/` (lowercase). Mount hardened (`soft,timeo=150,retrans=3,bg`). Daily backup cron installed. VM 101 (Plex) RESTORED.

**Cleanup — DONE S034:**
- ~~Remove NFS symlinks~~ — DONE
- ~~Remove .pre-overhaul dirs~~ — DONE
- ~~Delete arr-data-archived/~~ — DONE
- ~~Delete .backup-nfs-migration-S029/~~ — DONE
- Backup cron verified working on all 5 VMs — **S040: `mountpoint -q` replaced with `/proc/mounts` grep on all 5 VMs**

---

## COMPLETED PROJECT: pfSense LAGG → LACP Conversion

**Status:** COMPLETE — Executed S032-20260220
**Result:** lagg0 LACP mode, MTU 9000, igc2+igc3 both ACTIVE/COLLECTING/DISTRIBUTING. Switch Po2(SU) LACP Gi1/47(P)+Gi1/48(P). Config saved. All connectivity verified.
**Handoff File:** ~/LACP-LAGG-SESSION-NOTES.md (updated to reflect completion)

---

## Worker #1 — Infrastructure Engineer

### TODO
| Priority | Task | Notes |
|----------|------|-------|
| ~~P1~~ | ~~NFS mount migration: /mnt/nfs-mega-share → /mnt/truenas/nfs-mega-share~~ | **DONE S029.** All 6 phases complete. 5 VMs migrated, 30 compose refs, 114 doc refs, 57 backup refs updated. |
| ~~P1~~ | ~~Execute LACP cutover (Phase 6)~~ | **DONE S032.** LACP formed, both ports COLLECTING+DISTRIBUTING. Delayed-script approach (auto-revert safety net). |
| ~~P1~~ | ~~Fix lagg0 MTU 1500→9000~~ | **DONE S032.** `ifconfig lagg0 mtu 9000` + config.xml `<mtu>9000</mtu>` persisted. |
| ~~P1~~ | ~~Apply TICKET-0001 fix to ARCHITECTURE.md~~ | **DONE S028.** Fixed in both ARCHITECTURE.md + DC01.md. |
| ~~P2~~ | ~~Update pve01 to PVE 9.1.6~~ | **DEFERRED S031.** apt says "all packages up to date" at 9.1.5. 9.1.6 not yet available in pve01's repo. Mirror lag — will resolve on its own. |
| ~~P2~~ | ~~Verify LACP forms after cutover~~ | **DONE S032.** Po2(SU) Gi1/47(P)+Gi1/48(P). Both ports ACTIVE/COLLECTING/DISTRIBUTING. |
| ~~P2~~ | ~~Run connectivity tests post-LACP~~ | **DONE S032.** Switch 1ms, TrueNAS 0.3ms, pve01 0.3ms. 13/13 containers running. pfSense webGUI 200. |
| ~~P2~~ | ~~Save final switch config post-LACP~~ | **DONE S032.** `write memory` executed. |
| ~~P2~~ | ~~Update DC01.md with final LACP state~~ | **DONE S032.** CLAUDE.md LAGG section fully rewritten. |
| ~~P2~~ | ~~Address TICKET-0002 through TICKET-0005~~ | **DONE S033.** All 4 tickets resolved in ARCHITECTURE.md + DC01.md. |
| ~~P3~~ | ~~Establish performance baselines~~ | **DONE S035.** NFS write/read, ZFS IOPS, latency baselines. CRITICAL: VLAN 5 NFS writes failing (pfSense MTU 1500). Report at `infra/PERFORMANCE-BASELINES.md`. |
| ~~P3~~ | ~~Review and optimize NFS mount options~~ | **DONE S035.** Already optimal — rsize/wsize at 1MB kernel max, sysctl tuned, nconnect N/A on NFSv3. Report at `infra/NFS-OPTIMIZATION-ASSESSMENT.md`. |
| ~~P3~~ | ~~Document VM CPU/RAM allocations~~ | **DONE S035.** pve01: 24 CPU/252GB RAM, pve03: 16 CPU/32GB RAM. Report at `infra/VM-ALLOCATIONS.md`. |

### DONE (Carried Forward)
- [DONE] Phases 0-5 of DC01 v1.1 Overhaul
- [DONE] FAILOVER established and tested both directions
- [DONE] VPN→MGMT routing fix on all 5 VMs + switch
- [DONE] pfSense webGUI root cause [CONFIRMED] — port 4443
- [DONE] DC01_v1.1_base_config (92 files, 1.1MB on NFS)
- [DONE] Pre-change LACP baseline captured Session 25
- [DONE] S26: svc-admin standardized across all 10 systems
- [DONE] S32: Docker Infrastructure Overhaul — all 9 phases, 13/13 containers on local `/opt/dc01/`
- [DONE] S32: LACP cutover — lagg0 LACP MTU 9000, Po2(SU), all connectivity verified
- [DONE] S34: Full infrastructure overhaul — 20+ fix categories across all 10 systems
- [DONE] S34: NFS sysctl tuning (7 systems), VM network hardening (4 VMs), backup infrastructure (5 VMs)
- [DONE] S34: Security hardening — X11 disabled, plex sudo removed, .env permissions, staging redacted
- [DONE] S34: Switch NTP configured, kernel updates on VM 102/103, pve03 swap + ZFS upgrade
- [DONE] S35: ARCHITECTURE.md drift review — 47 corrections (37 stale + 10 missing)
- [DONE] S35: Performance baselines — CRITICAL finding VLAN 5 NFS writes failing
- [DONE] S35: NFS optimization assessment — already optimal
- [DONE] S35: VM CPU/RAM allocations documented
- [DONE] S35: pve03 pve-test.sources repo removed
- [DONE] S35: VM 104 GPU vendor-reset assessed — DKMS build needed (Sonny action)
- [DONE] S35: Switch VLANs 113/715 removed (confirmed orphaned), config saved
- [DONE] S35: Switch config-register already 0x2102 pending reload
- [DONE] S27: Audit Phase A — pulled live configs from 10/10 systems
- [DONE] S40: NFS write failure root-caused (pfSense TCP forwarding) and fixed (static route via switch on VMs 101/102)
- [DONE] S40: Backup cron fixed — `mountpoint -q` replaced with `/proc/mounts` grep on all 5 VMs
- [DONE] S40: NFS share cleaned — 1.1GB stale backup + artifacts removed, backward compat symlinks removed
- [DONE] S40: Lessons #35 (pfSense NFS TCP forwarding) and #36 (mountpoint -q unreliable) added
- [DONE] S40: Dead pfSense rules removed (trackers 1771903089/1771903090 — unreachable inter-VLAN rules on opt5/opt6)
- [DONE] S40: Downloads cleaned — 8 movies + 1 TV special imported to library, ~280GB duplicates deleted, stuck processing cleared (~530GB reclaimed)
- [DONE] S40: Full media verification — 58 files, 459GB, all NFS-readable, zero corruption
- [DONE] S40: Plex library scan — 17 movies + 2 TV shows detected. Solo corrupt MKV (F-S040-SOLO-MKV)
- [DONE] S40: Radarr path fixes — 3 Star Wars movies corrected via API. 17/19 tracked with files
- [DONE] S40: Sonarr refresh — Ted Lasso special (S00E07) picked up, now 36/43 eps
- [DONE] S40: VM 103 qBit namespace fix — restarted stack, VPN connected, all 3 containers healthy
- [OPEN] S40: qBit credential mismatch — username `admin` vs `sonny-aif` (Sonny to fix via WebUI)
- [DONE] S41: VM 103 static IP (10.25.66.25), Docker ports bound to dirty VLAN, pfSense svc-admin config.xml cleanup
- [DONE] S42: Reboot verification — pfSense STORAGE rule verified, VMs 101/102 static routes verified
- [DONE] S42: TrueNAS post-init script fixed — deleted duplicate IDs 1+2, created clean ID 3 with `;` separators
- [DONE] S42: Service IP & Port Map — comprehensive table added to DC01.md (20 infra services, 16 containers)
- [DONE] S42: qBit VPN access fix — 3-layer problem solved (pfSense if-bound rule + VM policy routing + Docker table 200 bridge routes)
- [DONE] S42: Docker table 200 persistence — systemd service `docker-table200-routes.service` on VM 103, adds bridge routes after docker.service starts
- [DONE] S42: VM 103 reboot verification — 2 reboots. Docker 29 fwmark regression found and fixed (prio 201 rule). All persistence confirmed clean.

---

## Worker #2 — Quality & Compliance Engineer

### TODO
| Priority | Task | Notes |
|----------|------|-------|
| P1 | TICKET-0006: Temp password on all systems | `<REDACTED>` everywhere = single compromise = full access |
| ~~P1~~ | ~~Escalate TICKET-0001 resolution~~ | **RESOLVED S028.** TICKET-0001 closed. |
| ~~P2~~ | ~~TICKET-0007: TrueNAS svc-admin GID mismatch~~ | **CLOSED S031.** Primary GID 3000→950 via midclt. Home dir chgrp'd. SSH verified. |
| ~~P2~~ | ~~TICKET-0008: pve02 HA LRM dead 15 days~~ | **ASSESSED S035.** Recommendation: REMOVE from cluster. Full procedure at `infra/TICKET-0008-PVE02-ASSESSMENT.md`. Sonny decision pending. |
| ~~P2~~ | ~~Review ARCHITECTURE.md for drift~~ | **DONE S035.** 47 corrections applied (37 stale + 10 missing). Full alignment with DC01.md. |
| ~~P2~~ | ~~Compliance gate for LACP cutover~~ | **DONE S032.** LACP cutover executed with Sonny approval. Checkpoint file used. Verification complete. |
| ~~P3~~ | ~~TICKET-0009: Proxmox version drift~~ | **DEFERRED S031.** pve01 fully up to date at 9.1.5 — 9.1.6 not available in repo yet. Will self-resolve. |
| ~~P3~~ | ~~TICKET-0010: Tdarr API key plaintext~~ | **CLOSED S034.** Moved to .env file with 600 root:root permissions. |
| P3 | iDRAC default password remediation plan | AC-03 finding. |
| ~~P3~~ | ~~Backup strategy recommendation~~ | **DONE S035.** PBS on pve03 as VM 106, NFS-backed, 04:00 daily. Report at `infra/RECOMMENDATION-BACKUP-STRATEGY.md`. |
| ~~P3~~ | ~~Monitoring deployment recommendation~~ | **DONE S035.** Uptime Kuma on VM 102, 28 monitors, Discord alerts. Report at `infra/RECOMMENDATION-MONITORING.md`. |
| ~~P4~~ | ~~TICKET-0011: TrueNAS REST API deprecation~~ | **ASSESSED S035.** Current API works until 26.04 upgrade. No action needed now. |
| ~~P4~~ | ~~TICKET-0012: Switch password encryption~~ | **UPGRADED S30 → F-018 (CRITICAL).** Plaintext passwords found on console/VTY lines. |
| **P1** | **F-018: Switch plaintext passwords** | `m4st3rp4$$` visible in running-config on console + VTY. `service password-encryption` + change password. IMMEDIATE. |
| ~~P2~~ | ~~F-019: pfSense svc-admin UID/GID mismatch~~ | **CLOSED S031.** UID 2002→3003, GID 0→950. Group truenas_admin(950) created. config.xml updated. SSH verified. Backup at config.xml.backup-session31. |
| ~~P2~~ | ~~F-020: pfSense webGUI all interfaces~~ | **CLOSED S031.** Anti-lockout disabled. Block rules on LAN (dest="This Firewall" :4443/:80) + WireGuard (dest=10.25.0.1 :4443/:80). Verified: LAN blocked, VPN→.0.1 blocked, VPN→.255.1 HTTP 200. |
| P4 | F-021: TrueNAS IPv6 web listeners bypass | **CANNOT FIX S033.** Middleware requires ≥1 IPv6 entry, only option is `::`. No IPv6 routing in environment — risk is link-local L2 only. Downgraded LOW. Accept or disable IPv6 at OS level. |
| ~~P3~~ | ~~F-022: TrueNAS SSH on 0.0.0.0:22~~ | **CLOSED S033.** `ssh.update bindiface: ["eno4"]`. SSH now on 10.25.255.25:22 + localhost only. |
| ~~P3~~ | ~~F-023: pve03 nic0.10 MTU 1500~~ | **CLOSED S031.** Config file created (`vlan10-compute.conf`), MTU 9000 applied, IP 10.25.10.28/24 added. Deeper finding: VLAN 10 had NO persistent config — would vanish on reboot. Now persisted. |
| ~~P4~~ | ~~F-024: TrueNAS timezone mismatch~~ | **CLOSED S035.** Already America/Chicago — original finding was incorrect. |
| ~~P4~~ | ~~F-025: Stale VLANs 113/715 on switch~~ | **CLOSED S035.** Both VLANs confirmed orphaned (zero ports, zero SVIs, zero trunk carriage). Removed and config saved. |
| ~~P0~~ | ~~INCIDENT-S035: LACP OUTAGE~~ | **FULLY RECOVERED S036.** LACP reformed, MTU 9000, Po2(SU) Gi1/47(P)+Gi1/48(P). Errdisable recovery enabled. |
| **P3** | **DR Architecture — Phase 5b + 6** | Phases 1-4 COMPLETE S036. Phase 5 PARTIAL: WANDR interface/IP/gateway/VPN done, gateway group (automatic failover) PENDING. Phase 6 DEFERRED (failover script handles VLANs on-demand). Plan: `infra/DR-ARCHITECTURE-PLAN.md`. |

### DONE (Carried Forward)
- [DONE] TICKET-0001 through TICKET-0005 filed
- [DONE] S27: TICKET-0006 through TICKET-0012 filed (audit findings)
- [DONE] S27: Audit Phase C — validated all diffs, classified findings
- [DONE] compliance/WORKER1-NOTES.md + WORKER2-NOTES.md written
- [DONE] Phase 5 credential scan — 1 finding (Tdarr API key redacted)

---

## Worker #3 — Workflow & Process Engineer

### TODO
| Priority | Task | Notes |
|----------|------|-------|
| P2 | Monitor 4-worker audit effectiveness | First audit with Worker #4. Track process quality. |
| P2 | Track IMP-001/002 enforcement | Both exercised once. Need sustained enforcement. |
| ~~P3~~ | ~~TICKET-0001 aging recommendation~~ | **RESOLVED S028.** Fixed after 9 sessions. |
| P3 | Update IMPROVEMENT-BACKLOG.md | Add audit process observations. |
| P4 | Review IMP-003 for 3-worker system | Dependency-ordered scheduling. |

### DONE (Carried Forward)
- [DONE] workflow/WORKFLOW-NOTES.md written (Sessions 19-26)
- [DONE] workflow/IMPROVEMENT-BACKLOG.md maintained (IMP-001 through IMP-021)
- [DONE] S27: Observed first audit session. Worker #4 activated successfully.

---

## Worker #4 — Documentation & Backup Engineer

### TODO
| Priority | Task | Notes |
|----------|------|-------|
| ~~P2~~ | ~~Update base_config TrueNAS users.txt~~ | **DONE S042.** Refreshed — 5 non-builtin users, all GID 950. |
| ~~P2~~ | ~~Update base_config switch running-config~~ | **DONE S042.** Refreshed — 515 lines, passwords redacted. |
| ~~P3~~ | ~~Add VM sudoers to backup templates~~ | **DONE S042.** NEW: `vms/vm-{101-105}/sudoers.d/svc-admin` (5 files). |
| ~~P3~~ | ~~Document pfSense svc-admin in base_config~~ | **DONE S042.** NEW: `pfsense/sudoers-svc-admin.txt`. |

### DONE
- [DONE] S27: First activation — Worker #4 memory file created
- [DONE] S27: Audit Phase B — diffed staging/ against DC01_v1.1_base_config/
- [DONE] S27: Audit Phase D — docs/BACKUP-MANIFEST.md created
- [DONE] S27: Audit Phase E — DC01.md/CLAUDE.md currency checked
- [DONE] S27: Audit Phase F — Obsidian KB (DB_01) full sync (34 pages)
- [DONE] S27: Audit Phase G — docs/AUDIT-REPORT.md completed
- [DONE] S27: docs/KB-SYNC-LOG.md created
- [DONE] S42: base_config refreshed — TrueNAS users, switch config, VM sudoers (5), pfSense sudoers

---

## Pending Sonny Decisions / GUI Tasks

| Item | Status | Notes |
|------|--------|-------|
| ~~pve03 MTU mismatch fix (VLAN 2550)~~ | **DONE S29** | Sonny fixed via GUI. Verified: nic0.2550 now mtu 9000. **Note:** nic0.10 (VLAN 10) still mtu 1500 — separate item. |
| Huntarr API config | PENDING | http://10.25.255.31:9705 — Sonarr/Radarr connections |
| ~~Rename VM 101 Plex → Plex-Server?~~ | **DONE S29** | Renamed in Proxmox. DC01.md + CLAUDE.md updated. |
| VM 103 DHCP 10.25.66.10 → static 10.25.66.25? | **DONE S041** | Static 10.25.66.25 applied. Ports bound to dirty VLAN only. dhcpcd disabled. |
| WireGuard keypair regeneration | PENDING | Private key exposed Session 23 |
| Credential rotation (svc-admin) | **CRITICAL** | `<REDACTED>` on ALL 10 systems. TICKET-0006. **6th session since first exposure.** |
| Verify pfSense SSH as svc-admin | VERIFIED S27 | SSH worked during audit pulls. |
| Verify pfSense webGUI login as svc-admin | **DONE S041** | Working. config.xml cleaned (groupname added, stale items removed). |
| Verify Proxmox webGUI login as svc-admin | PENDING | https://10.25.0.26:8006/ and https://10.25.0.28:8006/ |
| Nerf sonny-aif to minimal access | PENDING | After SSH key deployment. |
| Windows SMB to Storage VLAN | **DONE S040** | Sonny updated VPN config, all VLANs reachable from Windows. SMB mount to `10.25.25.25` working from Windows. |
| **VM 103 VLAN 66 firewall fix** | **CLOSED S038** | Was routing, not firewall. `route-to (lagg1)` in config.xml. Gluetun HEALTHY. |
| **WANDRGW gateway monitoring** | **PENDING (S037)** | Shows "Unknown" in dashboard. Fix: System→Routing→Gateways→Edit WANDRGW→set Monitor IP to `9.9.9.9` or `1.0.0.1`. Prerequisite for Phase 5b automatic WAN failover. Lower priority — gateway monitoring only, not blocking any functionality. |
| Generate SSH keypair for svc-admin | PENDING | Deploy to all systems, then rotate password. |
| pve02 cluster membership | **ASSESSED S035** | Recommendation: REMOVE. Full procedure at `infra/TICKET-0008-PVE02-ASSESSMENT.md`. |
| ~~VM 103 reboot verification~~ | **DONE S042** | 2 reboots. Reboot #1 found Docker 29+ fwmark regression → fixed with prio 201 rule. Reboot #2 fully clean. dhcpcd gone, DHCP ghost gone, all routing persisted, qBit HTTP 200 from VPN. |
| ~~LACP OUTAGE RECOVERY~~ | **FULLY RESOLVED S036** | LACP reformed, MTU 9000, Po2(SU). DR interfaces (igc0=WANDR, igc1=LANDR) assigned. LAN failover script deployed. Plan: `infra/DR-ARCHITECTURE-PLAN.md`. |
| ~~pfSense webGUI restrict to .255.X~~ | **DONE S031** | Anti-lockout disabled. Block rules on LAN ("This Firewall" :4443/:80) + WireGuard (.0.1 :4443/:80). Verified from pve01 (LAN) and VPN. Only VPN→.255.1 works. |
| ~~pve03 nic0.10 MTU fix~~ | **DONE S031** | VLAN 10 had no config file at all — would vanish on reboot. Created `vlan10-compute.conf` with MTU 9000 + IP 10.25.10.28/24. .bak duplicate cleaned. VM 104 NFS remounted successfully. |

---

## System State at Audit (S030)

| Component | State | Verified? |
|-----------|-------|-----------|
| pfSense lagg0 (LAN) | **LACP active** (S036). igc2+igc3 ACTIVE/COLLECTING/DISTRIBUTING. MTU **9000**. Switch Po2(SU) Gi1/47(P)+Gi1/48(P). `lacp rate fast` REMOVED from switch (was causing repeated err-disable). Errdisable recovery 30s. | YES (S036) |
| pfSense lagg1 (WAN) | **LACP active** (S036). ix2+ix3 ACTIVE/COLLECTING/DISTRIBUTING. IP 100.101.14.2/28. VIPs 69.65.20.58, 69.65.20.62. Upstream Po3: Gi1/27(ix3)+Gi1/29(ix2). | YES (S036) |
| pfSense WANDR (igc0) | **Active** (S036). IP 100.101.14.3/28. VIP 69.65.20.57/32. Gateway WANDRGW→100.101.14.1. Firewall rule: UDP 51820 allowed. VPN failover endpoint: 100.101.14.3:51820. TESTED WORKING. Upstream Gi1/30. | YES (S036) |
| pfSense LANDR (igc1) | **Standby** (S036). No IP. Switch Gi1/46 trunk. Failover script at `/opt/dc01/scripts/lan-failover.sh`. Watchdog cron at `/opt/dc01/scripts/lagg0-watchdog.sh` (every 60s). | YES (S036) |
| pfSense webGUI | VPN→.255.1:4443 ONLY (F-020 CLOSED S031) | YES |
| Switch config (Cisco 4948E-F) | Plaintext passwords on con/VTY (F-018). Config-register 0x2102 pending reload. Po2(SU) LACP Gi1/47(P)+Gi1/48(P). Gi1/46 = LAN-DR trunk (igc1). Errdisable recovery: link-flap **30s** (reduced from 300s). `lacp rate fast` REMOVED from Gi1/47-48. | YES (S036) |
| All 5 VMs | Running, NFS mounted, Docker healthy, 0 temp files. VM 103: policy routing + docker-table200-routes.service for WG access (S042). | YES (S042) |
| TrueNAS web UI | 10.25.255.25 only (IPv4). [::]:80/443 (IPv6 leak — F-021) | YES |
| TrueNAS NFS/SMB | Bound to 10.25.25.25 + 10.25.255.25 only | YES |
| TrueNAS SSH | ~~0.0.0.0:22~~ Bound to eno4 only (F-022 CLOSED S033) | YES |
| HA quorum | OK (pve02 LRM dead 15+ days) | YES |
| Proxmox versions | pve01: 9.1.5, pve03: 9.1.6 (DRIFT — F-008) | YES |
| pfSense outbound routing | `route-to (lagg1 100.101.14.1)` on opt5+opt6 internet rules. Default route still igc0 (kernel limitation). S042: DIRTY VLAN pass rule added (WG return traffic 10.25.66.0/24→10.25.100.0/24). Config backup: `config.xml.backup-s042`. | YES (S042) |
| Docker versions | 13/13 match compose files (100%) | YES |
| svc-admin access | 10/10 systems via SSH. **9/9 UID/GID correct (S031).** | YES |
| NFS mounts | 5/5 VMs consistent. Backward compat symlinks REMOVED (S040). VMs 101/102 route NFS via switch (static route `10.25.25.0/24 via 10.25.5.5`, persisted in `/etc/network/interfaces`). VMs 104/105 route via switch natively. | YES (S040) |
| Temp file scan | 10/10 CLEAN. Zero PHP/PY/artifacts. | YES |

---

## Update Log

| Time | Worker | Action |
|------|--------|--------|
| 2026-02-19 S21 | Orchestrator | Session startup. LACP recovery + FAILOVER established. |
| 2026-02-19 S22 | Orchestrator | Phases 0-4 complete. Plex fixed, new services deployed, compose standardized. |
| 2026-02-19 S23 | Orchestrator | VPN→MGMT routing fixed (asymmetric routing on all 5 VMs). |
| 2026-02-19 S24 | Orchestrator | Phase 5 DONE (92 files). Switch SSH fixed. |
| 2026-02-20 S25 | Orchestrator | pfSense webGUI solved (port 4443). LACP staged with checkpoint. IMP-001/002 exercised. |
| 2026-02-20 MIGRATION | Orchestrator | Restructured TASKBOARD from 5-worker to 3-worker layout. |
| 2026-02-20 S26 | Orchestrator | svc-admin standardized across all 10 systems. |
| 2026-02-20 S27 | Orchestrator | FULL BOOT. First audit under JARVIS v1.1. EXEC=audit, WORKERS=all. |
| 2026-02-20 S27 | Worker #1 | Phase A: Pulled live configs from 10/10 systems to staging/S027-20260220/. |
| 2026-02-20 S27 | Worker #4 | Phase B: Diffed staging against DC01_v1.1_base_config. 4 diffs found (1 EXPECTED, 1 STALE, 2 NEW). |
| 2026-02-20 S27 | Worker #2 | Phase C: Validated diffs. Created TICKET-0006 through TICKET-0012 (7 new findings). |
| 2026-02-20 S27 | Worker #4 | Phase D: Created docs/BACKUP-MANIFEST.md. Identified 5 backup items needing update. |
| 2026-02-20 S27 | Worker #4 | Phase E: DC01.md/CLAUDE.md currency check. Minor updates needed (PVE versions, TrueNAS GID). |
| 2026-02-20 S27 | Worker #4 | Phase F: Obsidian KB (DB_01) full sync. 34 pages created. Existing S17 files archived. |
| 2026-02-20 S27 | Worker #4 | Phase G: docs/AUDIT-REPORT.md completed. 17 findings total (4 CRITICAL, 5 HIGH, 5 MEDIUM, 3 LOW). |
| 2026-02-20 S27 | Worker #3 | Process observation: First audit session ran smoothly. Worker #4 first activation successful. |
| 2026-02-20 S27 | Orchestrator | Audit complete. Next audit: 2026-03-20 or after major changes. |
| 2026-02-20 S28 | Orchestrator | Warm Start. EXEC=live, WORKERS=#1+#2+#3, CONTEXT=dc01, SCOPE=none. Awaiting tasking. |
| 2026-02-20 S28 | Worker #1 | TICKET-0001 RESOLVED. Fixed Lesson #2 in ARCHITECTURE.md + DC01.md. Correct terminology, DANGER callout, cross-ref #13/#14. Backup at ~/backup-ARCHITECTURE-S028/. |
| 2026-02-20 S28 | Worker #1 | NFS migration plan written. 6 phases, full rollback, 6 audit findings. Plan at ~/.claude/plans/robust-churning-peacock.md. AWAITING GO. |
| 2026-02-20 S28 | Orchestrator | Session handoff. TICKET-0001 closed. NFS migration planned, not executed. Next session: execute migration. |
| 2026-02-20 S29 | Orchestrator | Warm Start. EXEC=live, WORKERS=#1+#2+#3, CONTEXT=dc01, SCOPE=none, INCIDENT=auto, VERBOSITY=normal. Awaiting tasking. |
| 2026-02-20 S29 | Worker #1 | VM 101 renamed Plex → Plex-Server. Verified running. Backup at ~/backup-vm101-rename-S029/. |
| 2026-02-20 S29 | Worker #1 | pve03 VLAN 2550 MTU fix VERIFIED — nic0.2550 now mtu 9000. [CONFIRMED] |
| 2026-02-20 S29 | Worker #2 | NEW FINDING: pve03 nic0.10 (VLAN 10, Compute) still mtu 1500 vs vmbr0v10 mtu 9000. Same mismatch pattern. |
| 2026-02-20 S29 | Worker #1 | DC01.md + CLAUDE.md updated — VM 101 name, pve03 MTU decision resolved. |
| 2026-02-20 S29 | Worker #1 | NFS MIGRATION COMPLETE. Phase 0: baselines captured (VM 104 stale NFS fixed). Phase 1: 5 VMs migrated (104→105→103→102→101). VM 104 had skeleton dirs under old mount — cleaned. Phase 2: 30 compose refs updated. Phase 3: Rolling restart on real paths. Phase 5: 57 base_config refs updated. Phase 6: All verified. |
| 2026-02-20 S29 | Worker #2 | VM 104 NFS instability observed AGAIN during verification. Same S22 pattern. Root cause still [HYPOTHESIS] — may be MTU, NFS timeout, or pve03 network. |
| 2026-02-20 S29 | Worker #1 | Web UI restriction: TrueNAS bound to 10.25.255.25 only (midclt). VPN route added + persisted. |
| 2026-02-20 S29 | Worker #1 | Web UI restriction: pve01 iptables (interface-based) + VPN route persisted in vlan2550-mgmt.conf. Verified: .0.X blocked, .255.X working. |
| 2026-02-20 S29 | Worker #1 | Web UI restriction: pve03 iptables (interface-based) + VPN route. All persisted. Verified: .0.X blocked, .255.X working. Deployed via pve01 hop. |
| 2026-02-20 S29 | Worker #2 | pfSense webGUI: `webguiinterfaces` config option NOT functional in this version (0 code references). Cannot restrict via nginx binding. Needs firewall rule via GUI. Added to Sonny pending tasks. |
| 2026-02-20 S29 | Worker #1 | NFS/SMB binding: TrueNAS NFS bound to 10.25.25.25 + 10.25.255.25. SMB same. VM 101/102/104/105 fstab → 10.25.25.25 (Storage VLAN). VM 103 stays on 10.25.255.25 (dirty VLAN can't reach storage). Proxmox HA storage updated. |
| 2026-02-20 S30 | Orchestrator | Warm Start. EXEC=audit, WORKERS=all (#1+#2+#3+#4), CONTEXT=dc01, SCOPE=none. Security-focused audit per Sonny Note: temp files, SOC compliance, svc-admin perms, web UI binding, VLAN separation. |
| 2026-02-20 S30 | Worker #1 | Phase A: Pulled live configs from 10/10 systems. 4 parallel agents (pve01/03, VMs, TrueNAS/pfSense, switch). ~198 files to staging/S030-20260220/. Password file race condition recovered. |
| 2026-02-20 S30 | Worker #2 | Phase C: 20 total findings (5 CRITICAL, 6 HIGH, 4 MEDIUM, 5 LOW). 1 closed (F-011), 9 new findings. F-013 upgraded to CRITICAL (F-018 plaintext passwords). SOC posture: HIGH RISK. |
| 2026-02-20 S30 | Worker #4 | Credential hygiene: 3 items redacted in staging (TrueNAS TLS key, WG private key, switch plaintext passwords). |
| 2026-02-20 S30 | Orchestrator | AUDIT COMPLETE. Report at docs/AUDIT-REPORT-S030.md. Temp files: CLEAN (10/10). svc-admin: 7/9 correct. NFS: 5/5 consistent. Docker: 13/13 matched. Next audit: 2026-03-20 or post-SSH-key-deployment. |
| 2026-02-20 S31 | Orchestrator | Warm Start. EXEC=live, WORKERS=#1+#2+#3, CONTEXT=dc01, SCOPE=none, INCIDENT=auto, VERBOSITY=normal. Awaiting tasking. |
| 2026-02-20 S31 | Worker #1 | F-023 CLOSED. pve03 VLAN 10: created vlan10-compute.conf (MTU 9000, IP 10.25.10.28/24, bridge-ports nic0.10). Removed duplicate vlan2550-mgmt.conf.bak. Applied runtime MTU. VM 104 NFS remounted. VM 105 unaffected. |
| 2026-02-20 S31 | Worker #2 | NEW FINDING: pve03 VLAN 10 had NO persistent config — vmbr0v10 existed only at runtime. Reboot would have killed VM 104+105 networking. Now persisted. Also: pve03 has WiFi adapter (wlp4s0, state DOWN) — Asus B550-E onboard. Not a risk (DOWN) but documented. |
| 2026-02-20 S31 | Worker #1 | F-019 CLOSED. pfSense svc-admin: UID 2002→3003, GID 0(wheel)→950(truenas_admin). Group created, config.xml updated, SSH verified. Backup at config.xml.backup-session31. |
| 2026-02-20 S31 | Worker #1 | TICKET-0007 CLOSED. TrueNAS svc-admin: primary GID 3000→950 via midclt user.update. Home dir chgrp'd. SSH verified. |
| 2026-02-20 S31 | Worker #2 | TICKET-0009/pve01 update: DEFERRED. apt says "all packages up to date" at 9.1.5. 9.1.6 not in repo yet. Mirror lag. |
| 2026-02-20 S31 | Worker #2 | svc-admin UID/GID now 9/9 correct across all systems (was 7/9 at S030 audit). |
| 2026-02-20 S31 | Worker #1 | F-020 CLOSED. pfSense webGUI locked to VPN→.255.1 only. Anti-lockout disabled, block rules on LAN+WireGuard for :4443/:80. Verified from pve01 (LAN) + VPN. |
| 2026-02-20 S31 | Worker #2 | FULL FIREWALL AUDIT. All 9 pfSense interfaces reviewed via screenshots. 7 findings: F-A (Mamadou — intentional), F-B (Overseerr NAT IP fixed, rule disabled), F-C (stale PUBLIC Plex NAT deleted), F-D (WG key — pending), F-E (WG0 duplicate deleted), F-F (EasyRule deleted), F-G (LAN mgmt→VPN deleted). All cleanup applied by Sonny. Verified: webGUI lockdown intact, LAN connectivity intact. |
| 2026-02-20 S31 | Worker #1 | VM 101 PLEX DOWN. Root cause: pfSense state table lost NFS TCP connection state after firewall rule changes. NFS writes hang (37KB stuck in send queue), Plex enters D-state on SQLite lock. Rebooted VM from Proxmox, NFS remounted, but Plex D-state again on NFS writeback. Ownership fix applied (3000→3003 on TrueNAS). Container starts without chown storm but hits NFS lock D-state. UNRESOLVED — needs Docker infra overhaul (local configs). |
| 2026-02-20 S31 | Orchestrator | NEW PROJECT: Docker Infrastructure Overhaul planned and approved. Move all compose + configs LOCAL to `/opt/dc01/`. Rename NFS `plex/` → `media/` (lowercase). NFS mount hardening (soft + timeo). Full plan at ~/Jarvis & Sonny's Memory/DC01-Docker-Infrastructure-Overhaul-Plan.md. |
| 2026-02-20 S32 | Orchestrator | FULL BOOT. Session S032-20260220. EXEC=live, WORKERS=#1+#2+#3, CONTEXT=dc01, SCOPE=none, INCIDENT=auto, VERBOSITY=normal. Primary goal: Execute Docker Infrastructure Overhaul. VM 101 (Plex) DOWN — overhaul is time-sensitive. |
| 2026-02-20 S32 | Worker #1 | Phase 0: Pre-flight. 13/13 containers verified. Pre-change baseline at logs/PRECHANGE-S032. TrueNAS backup: arr-data-backup-pre-overhaul-S032 (826MB). |
| 2026-02-20 S32 | Worker #1 | Phase 1: NFS restructure. `mv plex media`, `ln -s media plex`. Subdirs lowercase with backward symlinks. Verified from VM 104. |
| 2026-02-20 S32 | Worker #1 | Phase 2-3: VM 104 (Tdarr-Node) + VM 105 (Tdarr-Server) migrated. Clean stop/start. |
| 2026-02-20 S32 | Worker #1 | Phase 4: VM 103 (qBit) migrated. All 3 containers up, gluetun healthy. |
| 2026-02-20 S32 | Worker #1 | Phase 5: VM 102 (Arr-Stack) — NFS D-state on docker compose down. Force stop hung, lock file conflict. Killed PID, removed lock, rebooted from Proxmox. Config copy via tar-over-SSH (NFS cp unreliable). All 7 containers up. |
| 2026-02-20 S32 | Worker #1 | Phase 6: VM 101 (Plex) — D-state container, compose file null bytes, Proxmox force stop + reboot. Config 269MB via tar-over-SSH. Plex running, claimed, port 32400 responding. |
| 2026-02-20 S32 | Worker #1 | Phase 7: NFS mount hardening. All 5 VMs: fstab updated to `soft,timeo=150,retrans=3,bg`. Rolling unmount/remount with container stop/start. 13/13 containers verified. |
| 2026-02-20 S32 | Worker #1 | Phase 8: Backup cron. tar-based backup script (rsync unavailable). Daily 03:00 cron on all 5 VMs. NFS 7-day retention. Old configs archived on NFS + locally renamed .pre-overhaul. |
| 2026-02-20 S32 | Worker #1 | Phase 9: Documentation. WIP-DOCKER-OVERHAUL.md marked COMPLETE. CLAUDE.md updated (Plex/Arr Stack section, Docker standards, Session 32 findings, Phase 7 added). TASKBOARD updated. |
| 2026-02-20 S32 | Orchestrator | DOCKER INFRASTRUCTURE OVERHAUL COMPLETE. All 9 phases executed. 13/13 containers running from local `/opt/dc01/`. VM 101 (Plex) RESTORED after being DOWN since S031. |
| 2026-02-20 S32 | Orchestrator | Full systems check: 13/13 containers, all web UIs on .255.X responding, rogue LAN access verified blocked from 4 network perspectives. |
| 2026-02-20 S32 | Worker #1 | LACP CUTOVER COMPLETE. config.xml backup-session32. Round 1: switch L3/L2 mismatch, pfSense auto-reverted (safety net worked). Round 2: timing gap, pfSense auto-reverted again. Manual `ifconfig lagg0 laggproto lacp` after switch ready — LACP formed <5s. |
| 2026-02-20 S32 | Worker #1 | MTU fix: `ifconfig lagg0 mtu 9000` + config.xml `<mtu>9000</mtu>` persisted. Switch Po2 already MTU 9198. |
| 2026-02-20 S32 | Worker #1 | Post-LACP verification: Po2(SU) Gi1/47(P)+Gi1/48(P). Switch 1ms, TrueNAS 0.3ms, pve01 0.3ms. 13/13 containers. pfSense webGUI 200. Gluetun restarted (WG session disrupted by LACP transition). `write memory` saved. |
| 2026-02-20 S32 | Orchestrator | LACP PROJECT COMPLETE. Phase 6 of DC01 v1.1 Overhaul DONE. WIP-LACP-CUTOVER.md deleted per completion instructions. |
| 2026-02-20 S33 | Worker #1 | TICKET-0002 RESOLVED. Image pinning now enforced (S032). ARCHITECTURE.md Container Standard + Security Posture updated. PUID 3000→3003. |
| 2026-02-20 S33 | Worker #1 | TICKET-0003 RESOLVED. Lesson #12 updated Gi1/25→Gi1/10 in both ARCHITECTURE.md and DC01.md. Cable move note added. |
| 2026-02-20 S33 | Worker #1 | TICKET-0004 RESOLVED. WSL Workstation section added to ARCHITECTURE.md. svc-admin (UID 3003) added to Cluster section. Lesson #10 pvesh detail added. |
| 2026-02-20 S33 | Worker #1 | TICKET-0005 RESOLVED. NFS Mount Strategy updated for S029 binding changes. fstab patterns updated with S032 mount options. Compose File Reference rewritten for /opt/dc01/ (S032). |
| 2026-02-20 S33 | Worker #1 | F-022 CLOSED. TrueNAS SSH bound to eno4 only (`bindiface: ["eno4"]`). Verified: 10.25.255.25:22 + localhost. Pre-change baseline at logs/PRECHANGE-S033. |
| 2026-02-20 S33 | Worker #2 | F-021 CANNOT FIX via middleware. `ui_v6address` requires ≥1 entry, only `::` available. No IPv6 routing in environment. Downgraded LOW. |
| 2026-02-20 S34 | Orchestrator | Full scorched-earth infrastructure overhaul. 4 analysis reports, 20+ fix categories across 10 systems. NFS sysctl, VM networks, Docker hardening, backup cron, security updates, switch NTP, pve03 swap. 13 Sonny action items documented. |
| 2026-02-20 S35 | Worker #1 | F-024 CLOSED — TrueNAS timezone already America/Chicago. F-025 CLOSED — VLANs 113/715 removed from switch, config saved. |
| 2026-02-20 S35 | Worker #1 | Switch config-register already 0x2102 (applied S034, pending reload). pve03 pve-test.sources removed. |
| 2026-02-20 S35 | Worker #1 | VM 104 GPU: vendor-reset kernel module completely absent on pve03. Needs DKMS build from gnif/vendor-reset, must load before vfio-pci, requires pve03 reboot. |
| 2026-02-20 S35 | Worker #1 | NFS optimization: Already optimal. rsize/wsize at 1MB kernel max for NFSv3. nconnect not available (NFSv4.1+ only). Sysctl tuned. |
| 2026-02-20 S35 | Worker #1 | Performance baselines: **CRITICAL** — VMs 101/102 (VLAN 5) NFS writes fail with I/O error after 60s. VMs 104/105 (VLAN 10) write at 101-111 MB/s. Root cause: pfSense VLAN sub-interface MTU 1500 blocking jumbo NFS frames. |
| 2026-02-20 S35 | Worker #1 | VM CPU/RAM allocations documented. TICKET-0008 pve02 assessed — recommend REMOVE from cluster. |
| 2026-02-20 S35 | Worker #1 | ARCHITECTURE.md drift review: 47 corrections applied (37 stale, 10 missing). Full alignment with DC01.md. |
| 2026-02-20 S35 | Worker #2 | Backup strategy: PBS on pve03 as VM 106 recommended. Monitoring: Uptime Kuma on VM 102 recommended. TICKET-0011 assessed (no action until TrueNAS 26.04). |
| 2026-02-20 S35 | **INCIDENT** | **LACP OUTAGE.** Sonny changed pfSense VLAN sub-interface MTU via GUI → "Apply Changes" restarted lagg0 members → LACP PDU exchange interrupted → switch err-disabled Gi1/47+Gi1/48. All inter-VLAN routing DOWN. pfSense rebooted 2x, interfaces bounced, failover mode tried — switch ports remain err-disabled. Fix requires switch console access: `shut/no shut` on Gi1/47-48. pfSense config.xml cleaned (MTU removed for safe LACP reform). Backup at config.xml.backup-s035-lacp-fix. |
| 2026-02-21 S36 | Orchestrator | FULL BOOT. S035 outage resolved externally. lagg0 in FAILOVER (not LACP), MTU 1500, Gi1/47-48 standalone (no Po2). DR architecture plan written. |
| 2026-02-21 S36 | Worker #1 | Full state verification: pfSense 8 interfaces mapped, switch port status pulled, config.xml reviewed. Plan at `infra/DR-ARCHITECTURE-PLAN.md`. Phase 1 (LAN LACP restore) ready NOW. |
| 2026-02-21 S36 | Worker #1 | **Phase 1 COMPLETE.** LACP reformed: Po2(SU), Gi1/47(P)+Gi1/48(P). MTU 9000 restored (runtime + config.xml via perl). Errdisable recovery added (link-flap, 300s). All 8 endpoints verified. |
| 2026-02-21 S36 | Worker #1 | **Phase 2 COMPLETE.** Gi1/46 configured as LAN-DR trunk (VLANs 1/5/10/25/66/2550, MTU 9198, portfast edge trunk). igc1 linked up. |
| 2026-02-21 S36 | Worker #1 | **Phase 3 COMPLETE (with incident).** opt7=LANDR(igc1), opt8=WANDR(igc0) added to config.xml via perl. `rc.reload_interfaces` bounced all interfaces → switch err-disabled Gi1/47-48 AGAIN. |
| 2026-02-21 S36 | Worker #1 | **LACP RECOVERY via DR port.** Created igc1.2550 temp interface, added /32 host route for switch via igc1.2550 (overrides stuck /24 on down lagg0.2550). SSH'd to switch via pfSense ProxyJump, `shut/no shut` on Gi1/47-48. LACP reformed in seconds. Cleaned up temp routes/interfaces, removed stale igc2 IP (10.25.0.100). |
| 2026-02-21 S36 | Worker #1 | **LAN failover script deployed** at `/opt/dc01/scripts/lan-failover.sh`. Uses runtime ifconfig only (NOT rc.reload_interfaces). Supports activate/deactivate/status. Tested status command. |
| 2026-02-21 S36 | Worker #1 | **New Lessons:** L1: Never `rc.reload_interfaces` with LACP active. L2: /32 host route overrides /24 for DR recovery. L3: SSH ProxyJump for switch access. L4: Cisco config via stdin pipe. L5-L7: FreeBSD sed/tcsh/stale IP gotchas. |
| 2026-02-21 S36 | Worker #1 | **LACP stability fix:** Removed `lacp rate fast` from Gi1/47-48. Was causing repeated err-disable cycles during reboots (4+ times this session). Normal LACP rate (30s) is much more tolerant. Errdisable recovery reduced 300s→30s. |
| 2026-02-21 S36 | Worker #1 | **Phase 4 attempt 1 FAILED.** Runtime WAN migration (ix2→lagg1) broke VPN — pf firewall rules bound to ix2 in config.xml. Rollback left duplicate IPs, corrupted pf state. Required full reboot to recover. |
| 2026-02-21 S36 | Worker #1 | **WANDR configured.** igc0 = 100.101.14.3/28, VIP 69.65.20.57/32, gateway WANDRGW→100.101.14.1. Firewall rule for WireGuard (UDP 51820). VPN failover TESTED AND WORKING via 100.101.14.3:51820. Key finding: routed /29 goes to primary WAN — use transit IP for WANDR. |
| 2026-02-21 S36 | Worker #1 | **Phase 4 COMPLETE.** Config.xml: added lagg1 (ix3+ix2, LACP), changed WAN `<if>` from ix2 to lagg1. Sonny added Gi1/29 to Po3 on upstream. Rebooted with VPN on WANDR. lagg1 LACP formed, both ports ACTIVE/COLLECTING/DISTRIBUTING. All endpoints verified. |
| 2026-02-21 S36 | Worker #1 | **New Lessons:** L8-L13: Runtime WAN migration fails (pf binding), set up DR before changes, duplicate IPs cause ARP flap, remove lacp rate fast, errdisable 30s, routed /29 goes to primary WAN. |
| 2026-02-21 S37 | Orchestrator | FULL BOOT. S037-20260221. EXEC=live, WORKERS=#1+#2+#3, CONTEXT=dc01, SCOPE=none, INCIDENT=auto, VERBOSITY=normal, COMPACT=60%. Worker memory-notes stale (S032→S037). Image processed: pfSense dashboard showing WANDRGW gateway "Unknown". |
| 2026-02-21 S37 | Worker #1 | WANDRGW diagnosis: [PROBABLE] dpinger routing conflict — WANGW and WANDRGW share same gateway IP (100.101.14.1) on same /28 subnet. Fix: set different Monitor IP in GUI. |
| 2026-02-21 S37 | Worker #1 | DC01.md S036 sync COMPLETE: pfSense Interface Inventory section added, switch port map updated, Firewall Public IPs expanded, WireGuard DR failover endpoint, 13 lessons (#21-33), S036+S037 change log, F-S037-WANDRGW finding added. |
| 2026-02-21 S37 | Worker #1 | CLAUDE.md updated: pfSense section rewritten for S036 state. INC-001 status → RESOLVED. |
| 2026-02-21 S37 | Worker #1 | **Health check (read-only SSH):** VMs 101/102/104/105 healthy. pfSense all LAGs UP. TrueNAS mega-pool ONLINE (0 errors). Switch Po1+Po2 SU. pve01 quorum OK. |
| 2026-02-21 S37 | Worker #1 | **F-S034-MTU CLOSED.** All VLAN sub-interfaces (lagg0.5/10/25/66/2550) now MTU 9000. S035 GUI changes persisted in config.xml, took effect after S036 reboots. |
| 2026-02-21 S37 | Worker #1 | ~~F-S037-VM103-FW~~ | **CLOSED S038.** Root cause was routing (default→igc0), not firewall flags. `route-to` fix applied. |
| 2026-02-23 S38 | Orchestrator | WARM START. S038-20260223. EXEC=live, WORKERS=#1+#2+#3, CONTEXT=dc01, SCOPE=none, INCIDENT=auto, VERBOSITY=normal, COMPACT=60%. |
| 2026-02-23 S38 | Worker #1 | DIAGNOSIS: ALL VMs (not just VM 103) have zero outbound internet. Root cause: default route → igc0 (WANDR) → NAT to transit IP 100.101.14.3 → transit IP not publicly routable → return traffic fails. Only VIP NAT on lagg1 works. |
| 2026-02-23 S38 | Worker #1 | **INC-S038 SELF-INFLICTED.** Changed igc0 /28→/32 to fix default route → killed default route → VPN died. Sonny rebooted pfSense at datacenter to recover. |
| 2026-02-23 S38 | Worker #1 | **DEFAULT ROUTE FIX COMPLETE.** Added `gateway=WANGW` (compiles to `route-to (lagg1 100.101.14.1)`) to opt5+opt6 "Allow internet outbound" rules in config.xml. Reloaded with rc.filter_configure. All VMs now have internet. Config.xml backup: config.xml.backup-s038-gateway-fix. |
| 2026-02-23 S38 | Worker #1 | **F-S037-VM103-FW CLOSED.** Gluetun now HEALTHY after internet restored + container restart. Original S037 diagnosis (TCP-only flags) was WRONG — flags S/SA does NOT restrict to TCP in FreeBSD pf. Issue was purely routing. |
| 2026-02-23 S38 | Worker #2 | S037 finding F-S037-VM103-FW reclassified: root cause was routing, not firewall rule protocol. `flags S/SA` in FreeBSD pf applies only to TCP within the rule — UDP/ICMP still pass. |
| 2026-02-23 S39 | Orchestrator | FULL BOOT. S039-20260223. Worker memory-notes refreshed (S037→S039). No crisis. |
| 2026-02-23 S39 | Worker #1 | **Full health check (10/10 systems).** All healthy. 13/13 containers running. mega-pool ONLINE (0 errors). Both LAGs SU. All VLAN SVIs UP. pfSense uptime 57min — rebooted to fix change from another session (10.25.100.14, Windows/Chrome, ~15:57-17:28). Gluetun reconnected (29min). No new findings. |
| 2026-02-23 S39 | Worker #1 | **pfSense change audit:** Diffed config.xml vs backup-s038-gateway-fix. Only delta = our S038 route-to additions. Other session's changes were runtime-only, cleared by reboot. Config clean. |
| 2026-02-23 S39 | Worker #1 | **VLAN Traffic Segregation — Plan approved.** 5 phases: WSL SMB→Storage VLAN, pve03 ISO NFS→Storage VLAN, VM 102 Docker port binding, VM 105 Docker port binding split, documentation. Exceptions approved: VM 101 (Plex, host networking), VM 103 (qBit, no storage NIC by design). |
| 2026-02-23 S39 | Worker #1 | **Phase 1 DONE.** WSL SMB mounts moved from `10.25.255.25` to `10.25.25.25` (Storage VLAN). Required: (1) Sonny added 10.25.25.0/24 to WG AllowedIPs, (2) Sonny added pfSense rule on STORAGE: pass from STORAGE net to 10.25.100.0/24, (3) TrueNAS policy routing: `ip rule from 10.25.25.25 to 10.25.100.0/24 lookup table 100` → `via 10.25.25.1 dev bond0` (persisted via midclt post-init script id=2). Both SMB shares verified working. SSH to .255.25 unaffected. |
| 2026-02-23 S39 | Worker #1 | **Phase 2 DONE.** pve03 ISO NFS mount moved from `10.25.0.26` (LAN) to `10.25.25.26` (Storage VLAN). Required: (1) pve01 `/etc/exports` updated to allow `10.25.25.28` (backup at `/etc/exports.backup-S039`), (2) NFSv3 forced in fstab (NFSv4 server-side referral was redirecting to LAN IP). Mount verified: `addr=10.25.25.26`, NFSv3. |
| 2026-02-23 S39 | Worker #1 | **Phase 3 DONE.** VM 102 Docker: all 7 port bindings changed from `"PORT:PORT"` to `"10.25.255.31:PORT:PORT"`. Compose backup at `docker-compose.yml.backup-S039`. All 7 containers verified running. Web UIs accessible on .255.31 (HTTP 200/302/307), blocked on .5.31 (HTTP 000). |
| 2026-02-23 S39 | Worker #1 | **Phase 4 DONE.** VM 105 Docker: Web UI `:8265` bound to `10.25.255.33` (mgmt), server `:8266` bound to `10.25.10.33` (compute). Compose backup at `docker-compose.yml.backup-S039`. Web UI verified on .255.33:8265 (200), blocked on .10.33:8265 (000). Server verified on .10.33:8266 (302). VM 104 Tdarr-Node reconnected (`Node connected & registered, count:2`). |
| 2026-02-23 S39 | Worker #1 | **Phase 5 DONE.** Documentation updated: CLAUDE.md (VM 103 approved exception, VM 102/105 port bindings, Web UI Access Policy exceptions), ARCHITECTURE.md (pve03 ISO NFS, Tdarr port bindings, pve01 exports ACL, F-S034-MTU closed, WG Storage VLAN note), TASKBOARD.md (this entry). |
| 2026-02-23 S40 | Orchestrator | Session start. Image processed: `storage rules.png` (pfSense STORAGE VLAN rules confirmed). Deleted. |
| 2026-02-23 S40 | Worker #1 | **Windows SMB fix:** Sonny updated VPN config. All VLANs reachable from Windows. SMB mount to `10.25.25.25` working. |
| 2026-02-23 S40 | Worker #1 | **NFS share cleanup:** Deleted `arr-data-backup-pre-overhaul-S032/` (1.1GB stale), `media/.perf-test-s035-vm101` (0B artifact), `media/downloads/test` (0B stale). Removed `/mnt/nfs-mega-share` backward compatibility symlinks from all 5 VMs. |
| 2026-02-23 S40 | Worker #1 | **NFS write failure diagnosed.** VMs 101/102 (VLAN 5) NFS writes to 10.25.25.25 broken since S035. Root cause: pfSense pf cannot reliably forward sustained TCP NFS traffic between VLAN sub-interfaces on same lagg. Small writes OK, large writes stall/I/O error. VMs 104/105 (VLAN 10) unaffected — route via switch L3, bypass pfSense. |
| 2026-02-23 S40 | Worker #1 | **S038 rule interaction:** `route-to (lagg1)` on opt5 had `destination: any`, catching inter-VLAN NFS traffic. Even after adding pass rules, underlying TCP forwarding issue persisted. |
| 2026-02-23 S40 | Worker #1 | **NFS write fix COMPLETE.** Added static route `10.25.25.0/24 via 10.25.5.5` on VMs 101/102. NFS now routes through Cisco 4948E-F L3 switch (SVI routing) instead of pfSense. Persisted in `/etc/network/interfaces` (backup at `interfaces.backup-S040`). |
| 2026-02-23 S40 | Worker #1 | **pfSense dead rules:** Added 2 "Allow inter-VLAN (NFS, services)" rules on opt5+opt6 (trackers 1771903089, 1771903090). Below "Block RFC1918 10/8" — never match. Left in place. Config backup: `config.xml.backup-s040-nfs-fix`. |
| 2026-02-23 S40 | Worker #1 | **Backup cron fixed.** `mountpoint -q` unreliable after lazy unmounts. Changed to `grep -q "/mnt/truenas/nfs-mega-share " /proc/mounts` on all 5 VMs. Backups run successfully: Plex 199MB, Arr-Stack 50MB landed on NFS. All 5 VMs now have current backups. |
| 2026-02-23 S40 | Worker #1 | **Lesson #35:** pfSense pf cannot reliably forward sustained large TCP NFS writes between VLAN sub-interfaces on same lagg. Route inter-VLAN storage via switch L3 (SVI routing). |
| 2026-02-23 S40 | Worker #1 | **Lesson #36:** `mountpoint -q` unreliable after `umount -l`. Use `grep -q "<path> " /proc/mounts` for reliable mount detection in scripts. |
| 2026-02-24 S41 | Worker #1 | pfSense svc-admin config.xml cleanup: added groupname, removed stale item tags. Backup: config.xml.backup-s041-user-cleanup. |
| 2026-02-24 S41 | Worker #1 | VM 103: DHCP→static 10.25.66.25. Docker ports (8080/6881/8191) bound to 10.25.66.25 (dirty VLAN only). dhcpcd disabled. Backups: interfaces.backup-S041, docker-compose.yml.backup-S041. |
| 2026-02-24 S41 | Worker #2 | IP binding audit: 5/5 VMs verified. VM 103 finding resolved (ports now dirty VLAN only). |
| 2026-02-24 S42 | Worker #1 | **Reboot verification:** pfSense STORAGE rule VERIFIED (runtime + config.xml). VMs 101/102 static routes VERIFIED. VM 103 reboot still pending (dhcpcd lingering). |
| 2026-02-24 S42 | Worker #1 | **TrueNAS post-init FIXED.** `initshutdownscript.query` (not `tunable.query`) revealed 2 duplicate COMMAND entries. Deleted both, created clean ID 3 with `;` separators + `2>/dev/null`. |
| 2026-02-24 S42 | Worker #4 | **base_config refreshed:** TrueNAS users.txt, switch running-config (redacted), VM sudoers (5 files NEW), pfSense sudoers (NEW). |
| 2026-02-24 S42 | Worker #1 | **Service IP & Port Map** added to DC01.md. 20 infrastructure services + 16 Plex stack containers. All IPs/ports/VLANs from live SSH pulls. |
| 2026-02-24 S42 | Worker #1 | **qBit VPN access — 3-layer fix.** Layer 1: pfSense pass rule on DIRTY for WG return (if-bound states). Layer 2: VM 103 policy routing (ip rule from 10.25.66.25 to 10.25.100.0/24 → table 200 via ens18). Layer 3: Docker bridge routes in table 200 (fwmark 0x1 collision). Persisted: `/etc/network/interfaces` + systemd `docker-table200-routes.service`. |
| 2026-02-24 S42 | Worker #1 | **Lessons #37-38 added.** #37: Docker fwmark routing table collision. #38: pfSense if-bound states. |
| 2026-02-24 S42 | Worker #2 | F-S037-VM103-FW re-closed with full S042 verification. qBit WebUI accessible from WireGuard VPN (HTTP 200). |
| 2026-02-24 S42 | Worker #1 | **VM 103 reboot verification (2 reboots).** Reboot #1: Docker 29+ no longer creates CONNMARK/fwmark rules — container replies routed wrong interface. Fixed with `ip rule from 172.16.0.0/12 to 10.25.100.0/24 lookup 200 prio 201`. Reboot #2: ALL clean — static IP, no DHCP ghost, dhcpcd gone, policy rules persisted, Docker 3/3 healthy, NFS mounted, qBit HTTP 200 from VPN. Lesson #37 updated. |
| 2026-02-24 S43 | Jarvis | **pvestatd fix (both nodes).** All VMs showing "?" in Proxmox GUI + all metrics "-". Root cause: pvestatd hung since Feb 20 in NFS timeout loop (truenas-os-drive storage). pve03 pvestatd required SIGKILL. Both restarted, stats resumed. VMs were running fine the whole time. |
| 2026-02-24 S43 | Jarvis | **Cluster health verified.** 2-node quorate (pve01+pve03), pve02 fully dropped from corosync membership. No HA resources configured (resources.cfg absent). CRM idle (normal). |
| 2026-02-24 S43 | Jarvis | **pve02 homework updated** (`~/homework_for_DC01.md`). Added TICKET-0008 reference, truenas-os-drive warning, rewrote Phase 5 (Remove vs. Reintegrate), updated cluster state context. |
| 2026-02-24 S43 | Jarvis | **Lesson #39 added.** pvestatd NFS timeout hang — kills all VM status display, fix is restart pvestatd. |
