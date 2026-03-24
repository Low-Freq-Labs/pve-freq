# TASKBOARD — DC01 5-Agent Workflow

> Last updated: 2026-02-20 Session 25 (Phases 0-5 COMPLETE — Phase 6 LACP next)
> Maintained by: Master Orchestrator

---

## ACTIVE INCIDENT: pfSense LAGG → LACP Conversion

**Status:** IN PROGRESS — PAUSED for handoff
**Current State:** FAILOVER WORKING (2 members, tested both directions)
**Next Step:** Execute LACP cutover (Steps 1-5 in LACP-LAGG-SESSION-NOTES.md)
**Expected Outage:** ~5-10 seconds LAN during cutover
**Handoff File:** `~/LACP-LAGG-SESSION-NOTES.md` — contains exact commands and rollback plan

---

## Session 22 Progress

### Completed (Session 22)
- [DONE] Phase 0 — Services Health Check (PRIORITY 1)
- [DONE] FIX: Plex Preferences.xml + DB files had restrictive permissions (600/644) — fixed to 664 from TrueNAS
- [DONE] FIX: VM 104 stale NFS mount — D-state processes, rebooted from pve03, NFS remounted, tdarr-node restarted
- [DONE] All 5 VMs verified: SSH, NFS, Docker, HTTP health — ALL GREEN

### Completed (Session 22) — continued
- [DONE] Phase 1 — Web UI Migration: Docker port bindings audited, .255.X reachability verified
- [DONE] Phase 1 — DC01.md updated with canonical Management Access URLs table

### Phase 1 Remaining (Sonny GUI tasks)
- [ ] pve03: Fix MTU mismatch on management VLAN (vmbr0v2550=9000, nic0.2550=1500)
- [DONE] pfSense: WireGuard→MGMT and MANAGEMENT interface rules confirmed in place (Session 23)
- [DONE] VPN→VM .255.X connectivity: Fixed asymmetric routing with static routes on all 5 VMs (Session 23)
- [DONE S25] pfSense: webGUI reachable on ALL IPs via port 4443 (not 443). Root cause [CONFIRMED]: custom TCP port. https://10.25.255.1:4443/ and https://10.25.0.1:4443/ both return HTTP 200.

### Completed (Session 22) — Phase 2
- [DONE] Phase 2 — Huntarr (huntarr/huntarr:9.3.7) deployed on VM 102, port 9705, local config at /opt/huntarr-config
- [DONE] Phase 2 — Agregarr (agregarr/agregarr:v2.4.0) deployed on VM 102, port 7171, local config at /opt/agregarr-config
- [DONE] Phase 2 — Both services verified on .255.X management VLAN (HTTP 302/307)
- [DONE] Phase 2 — DC01.md updated with new services

### Phase 2 Remaining (Sonny GUI tasks)
- [ ] Huntarr: Configure Sonarr/Radarr API connections via web UI (http://10.25.255.31:9705)
- [ ] Agregarr: Configure Plex/Radarr/Sonarr/Overseerr API connections via web UI (http://10.25.255.31:7171)

### Completed (Session 22) — Phase 3
- [DONE] Phase 3 — VM 103 renamed qBit-Download → qBit-Downloader
- [DONE] Phase 3 — VM 105 renamed Tdarr → Tdarr-Server
- [DONE] Phase 3 — VM IDs all within 101-199 range (confirmed)
- [DONE] Phase 3 — DC01.md updated with new names

### Phase 3 Remaining (Sonny decisions)
- [ ] VM 101: Rename "Plex" → "Plex-Server"?
- [ ] VM 103: Change DHCP 10.25.66.10 → static 10.25.66.25?

### Completed (Session 22) — Phase 4
- [DONE] Phase 4 — All 5 compose files backed up (.bak-session22)
- [DONE] Phase 4 — DC01 header comments added to all compose files
- [DONE] Phase 4 — Image versions pinned: Plex, Prowlarr, Sonarr, Radarr, Bazarr, Overseerr, Gluetun, qBittorrent, FlareSolverr
- [DONE] Phase 4 — Tdarr/Tdarr-Node kept :latest (no semver tags on ghcr.io), version noted in header
- [DONE] Phase 4 — Services alphabetically ordered in docker-compose.arr.yml
- [DONE] Phase 4 — All 13 containers redeployed and verified healthy

### In Progress
- [DONE] Phase 5: DC01_v1.1_base_config (Repeatable Backup) — 92 files, 1.1MB on NFS at /mnt/truenas/nfs-mega-share/DC01_v1.1_base_config/

---

## Session 23 Progress

### Completed (Session 23)
- [DONE] VPN→MGMT VLAN connectivity fix: Root cause identified as asymmetric routing (VMs reply via service VLAN default GW, not mgmt VLAN)
- [DONE] Static routes added to all 5 VMs: `10.25.100.0/24 via 10.25.255.1 dev ens19` (runtime + persistent in /etc/network/interfaces)
- [DONE] Direct SSH from WSL to all VMs verified working on .255.X IPs over VPN
- [DONE] pfSense firewall rules audited: WireGuard→MANAGEMENT + MANAGEMENT interface rules confirmed already in place by Sonny
- [DONE] SECURITY: WireGuard private key exposed in chat — flagged for keypair regeneration

### Session 23 Remaining (Sonny GUI tasks)
- [DONE S25] pfSense webGUI port mystery RESOLVED — custom port 4443 (not 443). Both LAN and MGMT IPs accessible. Previous "Listen on All" diagnosis was irrelevant.
- [ ] SECURITY: Regenerate WireGuard keypair (private key exposed in chat Sessions 23+)

---

## Session 21 Progress

### Completed
- [DONE] Bootstrap: incidents/, logs/ dirs created, PROJECT_STRUCTURE.md written
- [DONE] Memory audit: all files read from SMB (mounted), LACP notes from LOCAL
- [DONE] All 5 worker memory notes rebuilt FRESH
- [DONE] Startup Status Report produced
- [DONE] SECURITY: Flagged credentials in user chat and old session notes
- [DONE] LACP-LAGG-SESSION-NOTES.md sanitized (credentials removed, replaced with vault reference)
- [DONE] Live probe: pfSense, switch, VLAN 1 all healthy
- [DONE] CRITICAL FINDING: Session 20 "duplicate members" diagnosis was WRONG (empty tag was WireGuard, not LAGG)
- [DONE] Switch cleanup: Gi1/47 removed from Po2, Po2 deleted, both ports now standalone trunks
- [DONE] pfSense: igc2 added to lagg0 FAILOVER (config.xml + ifconfig)
- [DONE] FAILOVER tested both directions — WORKING PERFECTLY
- [DONE] Switch: errdisable auto-recovery for channel-misconfig enabled (30 sec)
- [DONE] Config.xml safely reverted to FAILOVER proto before handoff

### Remaining (for next session)
- [TODO] Execute LACP cutover (switch Po2 + pfSense proto change)
- [TODO] Verify LACP forms (etherchannel summary, ifconfig -v lagg0)
- [TODO] Fix MTU on lagg0 (1500 → 9000)
- [TODO] Run connectivity tests (all VLANs, NFS, services)
- [TODO] Save final switch config
- [TODO] Update DC01.md with final LACP state
- [TODO] Create formal incident record in incidents/

### Deferred (after LACP)
- [ ] Worker #1: Address P1 ticket (Lesson #2 vs #13/#14 contradiction)
- [ ] Worker #1: Address P2 tickets
- [ ] All Round 2 tasks from previous session

---

## System State at Handoff

| Component | State | Safe? |
|-----------|-------|-------|
| pfSense lagg0 | FAILOVER, igc3 MASTER+ACTIVE, igc2 standby | YES |
| pfSense config.xml | proto=failover, members=igc3,igc2 | YES (matches running) |
| Switch Gi1/47 | Standalone trunk, connected | YES |
| Switch Gi1/48 | Standalone trunk, connected | YES |
| Switch Po2 | DELETED | YES |
| Switch Po1 (TrueNAS) | LACP SU, Gi1/8+Gi1/11 bundled | YES |
| VLAN 1 | Working | YES |
| All tagged VLANs | Working | YES |
| config.xml backup | /cf/conf/config.xml.backup-session21 | YES |

---

## Update Log

| Time | Worker | Action |
|------|--------|--------|
| 2026-02-19 S21 | Orchestrator | Session startup: SMB mounted, all files read, 5 worker notes rebuilt |
| 2026-02-19 S21 | Orchestrator | FINDING: Session 20 "duplicate members" was wrong — empty tag was WireGuard, not LAGG |
| 2026-02-19 S21 | Worker #1 | Switch cleanup: Po2 deleted, Gi1/47 clean standalone trunk |
| 2026-02-19 S21 | Worker #1 | pfSense: igc2 added to lagg0 FAILOVER, tested both directions |
| 2026-02-19 S21 | Worker #3 | errdisable auto-recovery enabled on switch |
| 2026-02-19 S21 | Orchestrator | HANDOFF: config.xml reverted to failover for safety, notes written |
| 2026-02-19 S22 | Orchestrator | Session startup: SMB mounted, all files read, Phase 0 crisis check clean |
| 2026-02-19 S22 | Orchestrator | SECURITY FINDING: Credentials pasted in chat AGAIN (pfSense, pve01, pve03, TrueNAS, VMs). Not written to disk. Password rotation recommended. |
| 2026-02-19 S22 | Orchestrator | All 5 worker memory notes rebuild dispatched (parallel agents) |
| 2026-02-19 S22 | Worker #1 | Phase 0: Plex Preferences.xml permissions fixed (600→664) via TrueNAS sudo |
| 2026-02-19 S22 | Worker #1 | Phase 0: Plex DB files permissions fixed (644→664) — resolved crash loop (N2DB9ExceptionE) |
| 2026-02-19 S22 | Worker #1 | Phase 0: VM 104 rebooted from pve03 (D-state processes from stale NFS), NFS remounted, tdarr-node restarted |
| 2026-02-19 S22 | Orchestrator | Phase 0 COMPLETE — all 5 VMs healthy, all services responding |
| 2026-02-19 S22 | Worker #1 | Phase 1: Docker port bindings audited (all 0.0.0.0), .255.X reachability verified |
| 2026-02-19 S22 | Worker #1 | Phase 1 FINDING: pve03 .255.X blocked by MTU mismatch (bridge 9000, NIC 1500) |
| 2026-02-19 S22 | Worker #1 | Phase 1 FINDING: pfSense .255.X blocked — anti-lockout only on lagg0, not lagg0.2550 |
| 2026-02-19 S22 | Worker #1 | Phase 1 FINDING: VPN→MGMT VLAN TCP blocked by pfSense (ICMP works, HTTP/HTTPS doesn't) |
| 2026-02-19 S22 | Orchestrator | Phase 1 DONE (Jarvis portion) — DC01.md updated with Management Access URLs |
| 2026-02-19 S22 | Worker #1 | Phase 2: Huntarr (9.3.7) + Agregarr (v2.4.0) deployed on VM 102, local config dirs created |
| 2026-02-19 S22 | Worker #1 | Phase 2: Both services verified on .255.X management VLAN |
| 2026-02-19 S22 | Orchestrator | Phase 2 DONE (Jarvis portion) — Sonny configures API keys via web UIs |
| 2026-02-19 S22 | Worker #1 | Phase 3: VM 103 renamed qBit-Downloader, VM 105 renamed Tdarr-Server |
| 2026-02-19 S22 | Worker #1 | Phase 4: All 5 compose files standardized — headers, pinned versions, alphabetical |
| 2026-02-19 S22 | Worker #1 | Phase 4: 13 containers redeployed and verified across 5 VMs |
| 2026-02-19 S22 | Orchestrator | SESSION 22 HANDOFF: Phases 0-4 DONE. Phase 5 (base_config backup) is next. Memory files updated. |
| 2026-02-19 S23 | Orchestrator | Session startup: SMB mounted, Phase 0 health check attempted |
| 2026-02-19 S23 | Orchestrator | FINDING: VPN→MGMT VLAN SSH failed — all VMs unreachable on .255.X from WSL |
| 2026-02-19 S23 | Orchestrator | FINDING: pfSense firewall rules (WireGuard + MANAGEMENT) already in place — Sonny added them between sessions |
| 2026-02-19 S23 | Orchestrator | ROOT CAUSE: Asymmetric routing — VMs reply via service VLAN default GW, pfSense drops mismatched states |
| 2026-02-19 S23 | Worker #1 | Static route `10.25.100.0/24 via 10.25.255.1 dev ens19` added to all 5 VMs (runtime + persistent) |
| 2026-02-19 S23 | Orchestrator | VPN→VM .255.X SSH verified working on all 5 VMs — direct access from WSL, no pve01 jump needed |
| 2026-02-19 S23 | Orchestrator | SECURITY: WG private key exposed in chat. pfSense .255.1:443 still blocked (webGUI binding, not firewall). |
| 2026-02-19 S23 | Orchestrator | SESSION 23 HANDOFF: VPN→VM routing fixed. Phase 5 (base_config backup) is next. Memory files updated. |
| 2026-02-19 S24 | Orchestrator | Session startup: SMB MOUNTED, all files read. DC01 skill contract verified (11 dirs, 6 anchor files — all present). |
| 2026-02-19 S24 | Orchestrator | SECURITY: Credentials exposed in chat AGAIN (pfSense root, pve01 root, pve03 root, TrueNAS admin, VMs root). NOT written to disk. All 5 passwords need rotation. |
| 2026-02-19 S24 | Orchestrator | Phase 0 Crisis Check: No FAILED tasks, no truncated files. INC-001 PARTIALLY RESOLVED (FAILOVER working, LACP pending). No crisis recovery needed. |
| 2026-02-19 S24 | Orchestrator | Phase 1 Memory Audit: CLAUDE.md=SMB(symlink), DC01.md=SMB, GigeNet.md=SMB, Homework.md=SMB, Overhaul Plan=SMB. TASKBOARD/worker notes=LOCAL. |
| 2026-02-19 S24 | Orchestrator | Phase 2 Worker Memory Sync: All 5 memory-notes-workerX.md rebuilt FRESH in parallel (W1=427L, W2=144L, W3=194L, W4=207L, W5=168L). |
| 2026-02-19 S24 | Orchestrator | Phase 3 Startup Declaration: Session 24 boot sequence COMPLETE. Ready for Phase 5 work. |
| 2026-02-19 S24 | Worker #1 | Phase 5: Created DC01_v1.1_base_config directory structure on NFS (38 dirs) |
| 2026-02-19 S24 | Worker #1 | Phase 5: Pulled configs from pve01 (18 files), pve03 (12 files), 5 VMs (25 files), TrueNAS (9 files), switch (3 files) |
| 2026-02-19 S24 | Worker #1 | Phase 5: Copied 5 Docker compose files + env.template to backup |
| 2026-02-19 S24 | Worker #1 | Phase 5: Created templates — VM network, fstab, user-setup.sh, docker-install.sh, WSL configs (11 files) |
| 2026-02-19 S24 | Worker #1 | Phase 5: Created pfSense documentation (6 files — interfaces, rules, VIPs/NAT, WireGuard, LAGG, backup instructions) |
| 2026-02-19 S24 | Worker #1 | Phase 5: Created iDRAC documentation (2 files — R530 + T620) |
| 2026-02-19 S24 | Worker #1 | Phase 5: README.md rebuild guide written (1,689 lines, 19 sections) |
| 2026-02-19 S24 | Worker #3 | Phase 5: Credential scan — 1 finding (Tdarr API key in compose backup). Redacted. 91 files clean. |
| 2026-02-19 S24 | Worker #1 | Switch SSH fix: Static route changed 10.25.100.0/24 via 10.25.0.1 → via 10.25.255.1 (same asymmetric routing fix as VMs). Direct SSH from WSL to 10.25.255.5 now works. SSH config added (~/.ssh/config with legacy crypto for Cisco IOS). |
| 2026-02-19 S24 | Orchestrator | Phase 5: DC01_v1.1_base_config COMPLETE — 92 files, 1.1MB on NFS. Switch SSH fixed. |
| 2026-02-19 S24 | Orchestrator | Agregarr API config: Keys pulled (Radarr, Sonarr, Overseerr). Sonny on Sources page — all optional (Trakt, MDBList, Tautulli, MAL, Maintainerr). Told to skip to next page. Sonny reported possible issue — investigate next session. |
| 2026-02-19 S24 | Orchestrator | pfSense Admin Access: Screenshot captured — Sonny working on webGUI "Listen on" fix. Status unknown — check next session. |
| 2026-02-19 S24 | Orchestrator | SESSION 24 HANDOFF: Phase 5 DONE. Switch SSH fixed. Agregarr + pfSense GUI work in progress by Sonny. |
| 2026-02-20 S25 | Orchestrator | Session startup: SMB MOUNTED, all files read. DC01 skill contract verified (all dirs + anchor files present). |
| 2026-02-20 S25 | Orchestrator | SECURITY: Credentials exposed in chat AGAIN (pfSense, pve01, pve03, TrueNAS, VMs root). NOT written to disk. All 5 passwords STILL need rotation (3rd session in a row). |
| 2026-02-20 S25 | Orchestrator | Phase 0 Crisis Check: No FAILED tasks, no truncated files. INC-001 still PARTIALLY RESOLVED (FAILOVER working, LACP pending). |
| 2026-02-20 S25 | Orchestrator | FINDING: pfSense "Listen on All" diagnosis [DISPROVEN]. Screenshot of Admin Access page shows NO interface-binding option. WebGUI default is all interfaces. Root cause of .255.1:443 failure is different. |
| 2026-02-20 S25 | Orchestrator | FINDING: Agregarr Sources page screenshot shows Trakt/MDBList/Tautulli/MAL/Maintainerr — all OPTIONAL. Sonny should click Continue. |
| 2026-02-20 S25 | Orchestrator | FINDING: Firewall rules screenshots confirmed — WG→MGMT rule active (12 KiB matched), MGMT rules correct (VPN+LAN pass, block-all else). |
| 2026-02-20 S25 | Orchestrator | Phase 1 Memory Audit: CLAUDE.md=SMB(symlink), DC01.md=SMB, GigeNet.md=SMB, Homework.md=SMB, Overhaul Plan=SMB. TASKBOARD/worker notes=LOCAL. All found. |
| 2026-02-20 S25 | Orchestrator | Phase 2 Worker Memory Sync: All 5 memory-notes-workerX.md rebuilt FRESH in parallel (W1=112L, W2=90L, W3=98L, W4=99L, W5=82L). Total: 481 lines. |
| 2026-02-20 S25 | Orchestrator | Phase 3 Startup Declaration: Session 25 boot sequence COMPLETE. Ready for work. |
| 2026-02-20 S25 | Worker #1 | pfSense webGUI investigation: ICMP works, TCP 443 fails on both .0.1 and .255.1. Tested from VM (VLAN 5) and pve01 (LAN). |
| 2026-02-20 S25 | Worker #1 | ROOT CAUSE [CONFIRMED]: pfSense webGUI on custom port 4443. HTTP 80 → redirect to HTTPS 4443. Both https://10.25.0.1:4443/ and https://10.25.255.1:4443/ return HTTP 200. |
| 2026-02-20 S25 | Worker #1 | CLOSED: Sessions 22-24 misdiagnosis chain (wrong port → "firewall issue" → "Listen on All" → [DISPROVEN]). Root cause was always the non-standard port. |
| 2026-02-20 S25 | Worker #1 | LACP PREP: Pre-change baseline captured (switch: Gi1/47+48 standalone trunks, Po2 deleted, Po1 healthy; pfSense: FAILOVER, igc3 ACTIVE, igc2 standby, connectivity to switch/TrueNAS/pve01 healthy). |
| 2026-02-20 S25 | Worker #1 | LACP PREP: Checkpoint file created at infra/WIP-LACP-CUTOVER.md per IMP-001. Awaiting human approval per IMP-002. |
| 2026-02-20 S25 | Orchestrator | Sonny deferred LACP cutover. IMP-002 human gate respected. |
| 2026-02-20 S25 | Orchestrator | SESSION 25 HANDOFF: pfSense webGUI mystery solved (port 4443). Agregarr done. LACP staged with checkpoint file. All memory files updated. |
