# Worker #1 — Infrastructure Architect — Memory Notes
> Session 25 (2026-02-20) — FRESH REBUILD
> Source: All memory files read (LOCAL-FIRST, SMB-FALLBACK)

---

## SECTION 1 — What I Read (LOCAL vs SMB)

| File | Source | Found |
|------|--------|-------|
| CLAUDE.md | SMB (symlink ~/CLAUDE.md → /mnt/smb-sonny/...) | YES |
| DC01.md | SMB (/mnt/smb-sonny/Jarvis & Sonny's Memory/DC01.md) | YES |
| GigeNet.md | SMB | YES |
| Sonny-Homework-OutOfScope.md | SMB | YES |
| DC01_v1.1_Overhaul_Plan.md | SMB | YES |
| TASKBOARD.md | LOCAL (~/dc01-overhaul/TASKBOARD.md) | YES |
| LACP-LAGG-SESSION-NOTES.md | LOCAL (~/LACP-LAGG-SESSION-NOTES.md) | YES |
| ARCHITECTURE.md | LOCAL (~/dc01-overhaul/infra/ARCHITECTURE.md) | YES |
| INC-001-LAGG-VLAN1-OUTAGE.md | LOCAL (~/dc01-overhaul/incidents/) | YES |
| CONSOLIDATED-FINDINGS.md | LOCAL (~/dc01-overhaul/CONSOLIDATED-FINDINGS.md) | YES |

SMB Status: MOUNTED and accessible.

---

## SECTION 2 — Current DC01 State

### Physical Hardware
- **R530 (TrueNAS 10.25.0.25):** 2x E5-2620 v3, 88GB RAM, 8x 6TB SAS JBOD. **PSU 1 FAILED, Fan 6 DEAD.** Running on single PSU. iDRAC at 10.25.255.10. Service Tag B065ND2.
- **T620 (pve01 10.25.0.26):** 2x E5-2620 v0, 256GB RAM. **PSU 2 FAILED.** Running on single PSU. iDRAC at 10.25.255.11. Service Tag 69MGVV1.
- **Replacement parts documented but NOT ORDERED.** R530: Dell 05RHVVA00 (PSU) + fan by service tag. T620: Dell 06W2PWA00 (PSU).

### Proxmox Cluster (3-node)
- pve01 (10.25.0.26/10.25.255.26) — T620, 256GB, hosts VMs 101-105, 420, 802, 804. Kernel 6.17.9-1-pve.
- pve02 (10.25.0.27) — OUT OF SCOPE. Hosts SABnzbd VM 100.
- pve03 (10.25.0.28/10.25.255.28 staged) — Consumer board, 31GB, hosts Tdarr Node VM 104. Kernel 6.17.9-1-pve.
- HA: pve-ha-lrm + pve-ha-crm enabled on pve01 + pve03. HA master: pve03. Shared storage: truenas-os-drive NFS.
- Corosync: knet transport. Config version 8. ring0: pve01=10.25.255.26, pve02=10.25.0.27, pve03=10.25.255.28.

### Storage
- TrueNAS ZFS pool: mega-pool, 8x 6TB SAS JBOD under PERC H730P. Dataset: nfs-mega-share.
- NFS export: /mnt/mega-pool/nfs-mega-share mounted on VMs at /mnt/truenas/nfs-mega-share.
- NFS migration COMPLETE (zfs-share → nfs-mega-share, /mnt → /mnt/truenas/nfs-mega-share).
- Plex stack data lives at /mnt/truenas/nfs-mega-share/plex/.
- SQLite-on-NFS unreliable — Bazarr, Huntarr, Agregarr use local /opt/ configs.

### Networking
- Core switch: Cisco 4948E-F at 10.25.0.5/10.25.255.5 (hostname gigecolo). MTU 9198 all ports.
- pfSense fw01: LAN=lagg0 (FAILOVER, igc3 MASTER+ACTIVE, igc2 standby), WAN=ix2. MTU on lagg0=1500 (NEEDS 9000).
- VLANs: 1(LAN), 5(Public), 10(Compute), 25(Storage), 66(Dirty), 2550(Management).
- VPN: WireGuard at 10.25.100.1/24 on pfSense tun_wg0. WSL VPN IP: 10.25.100.19.
- Static routes on all 5 VMs + switch: 10.25.100.0/24 via 10.25.255.1 dev ens19 (fixes VPN→MGMT asymmetric routing).
- Direct SSH from WSL to all VMs on .255.X and switch on .255.5 over VPN — no pve01 jump needed.

### VMs (Plex Stack)
| VM | Service IP | Mgmt IP | Role |
|----|-----------|---------|------|
| 101 Plex | 10.25.5.30 | 10.25.255.30 | Plex Media Server (GPU passthrough) |
| 102 Arr-Stack | 10.25.5.31 | 10.25.255.31 | Prowlarr, Sonarr, Radarr, Bazarr, Overseerr, Huntarr, Agregarr |
| 103 qBit-Downloader | 10.25.66.10 (DHCP) | 10.25.255.32 | qBittorrent + Gluetun VPN + FlareSolverr |
| 104 Tdarr-Node | 10.25.10.34 | 10.25.255.34 | Tdarr worker (RX580 GPU, on pve03) |
| 105 Tdarr-Server | 10.25.10.33 | 10.25.255.33 | Tdarr Web UI + task manager |

### DC01 v1.1 Overhaul Status
- Phases 0-5: ALL COMPLETE
- Phase 6 (LACP): IN PROGRESS — FAILOVER working, LACP cutover staged but paused
- Phase 5 output: DC01_v1.1_base_config at /mnt/truenas/nfs-mega-share/DC01_v1.1_base_config/ (92 files, 1.1MB)

---

## SECTION 3 — Open Risks / Known Issues

1. **CRITICAL: Dual single-PSU operation.** R530 PSU 1 + T620 PSU 2 both failed. Parts NOT ordered. Single point of failure on both servers.
2. **CRITICAL: No VM backup strategy.** Zero automated backups. No PBS deployed. Total rebuild from scratch on catastrophic failure.
3. **CRITICAL: No monitoring/alerting.** Zero monitoring deployed. PSU/fan failures go undetected.
4. **HIGH: pfSense LAGG LACP conversion pending.** FAILOVER working, LACP cutover staged. INC-001 partially resolved. Known LACP key mismatch risk from Session 20.
5. **HIGH: pfSense lagg0 MTU=1500.** Should be 9000 for jumbo frames. Blocks end-to-end jumbo frame path.
6. **MEDIUM: pfSense webGUI unreachable on 10.25.255.1:443.** Previous "Listen on All" diagnosis [DISPROVEN] — no such option exists. Root cause TBD. ICMP works, TCP 443 fails. Needs live testing.
7. **MEDIUM: pve03 MGMT VLAN MTU mismatch.** vmbr0v2550=9000 but nic0.2550=1500. Needs Proxmox network config fix (Sonny GUI task).
8. **LOW: iDRAC default passwords.** Both servers running default Dell iDRAC passwords. Need rotation.
9. **SECURITY: Credentials exposed in chat Sessions 23, 24, 25.** All 5 system passwords need rotation. WireGuard keypair needs regeneration.
10. **SLOP: ARCHITECTURE.md Lesson #2 contradicts Lessons #13/#14.** TICKET-0001 filed, fix documented. Not yet applied.

---

## SECTION 4 — Out-of-Scope Areas

- pve02 (10.25.0.27) — entirely out of scope
- VM 100 (SABnzbd on pve02) — Sonny's homework
- VMs 800-899 — not ours, do not touch
- GigeNet client systems — only when explicitly client-scoped
- Sonny-Homework-OutOfScope.md tasks (SABnzbd NFS migration, pve02 VLANs)

---

## SECTION 5 — My Immediate Responsibilities This Session

1. **Support LACP cutover if Sonny requests it.** INC-001 LACP conversion sequence is staged in LACP-LAGG-SESSION-NOTES.md. Includes switch Po2 creation, pfSense proto change, MTU fix, and rollback plan. HIGH RISK — requires human approval per IMP-002.
2. **Investigate pfSense .255.1:443 root cause.** Previous diagnosis disproven. Need live probe to determine if webGUI is listening, if there's a pf self-traffic issue, or if it's MTU/fragmentation.
3. **Apply TICKET-0001 fix to ARCHITECTURE.md.** Lesson #2 needs amendment to reference vmbr0v2550 instead of vmbr0.2550.
4. **Address any Sonny-reported Agregarr issues.** Session 24 noted Sonny reported a possible issue — needs investigation.
5. **Maintain infra/ directory and ARCHITECTURE.md** as source of truth for DC01 infrastructure state.

---

## SESSION LOG

Session 21 – Planned: LACP cutover / Done: Switch cleanup, FAILOVER established + tested, LACP staged / Next: Execute LACP cutover
Session 22 – Planned: Phase 0-4 overhaul / Done: All 4 phases complete (Plex fix, VM104 reboot, UI migration, new services, renames, compose standardization) / Next: Phase 5 base_config backup
Session 23 – Planned: Phase 5 + health check / Done: VPN→MGMT routing fix (asymmetric routing on all 5 VMs) / Next: Phase 5
Session 24 – Planned: Phase 5 base_config / Done: Phase 5 COMPLETE (92 files, 1.1MB). Switch SSH fixed. / Next: Phase 6 LACP + pfSense .255.1 investigation
Session 25 – Planned: Startup, pfSense webGUI investigation, LACP prep / Done: pfSense .255.1 root cause [CONFIRMED] (custom port 4443). Pre-change baseline captured. Checkpoint file written (infra/WIP-LACP-CUTOVER.md). DC01.md + CLAUDE.md updated. / Next: Execute LACP cutover (Steps 1-5 in WIP-LACP-CUTOVER.md). Then MTU 1500→9000.
