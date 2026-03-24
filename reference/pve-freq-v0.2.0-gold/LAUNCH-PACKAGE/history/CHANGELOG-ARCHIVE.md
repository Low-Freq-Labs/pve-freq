# DC01 Change Log Archive

> **Archived:** S053 (2026-02-25) — Extracted from DC01.md during comprehensive rewrite.
> **Coverage:** Sessions 16-47. Sessions 1-15 (build phase) summarized. Sessions 48+ remain inline in DC01.md.

---

## Build Phase Summary (Sessions 1-15, 2026-02-17 through 2026-02-19)

Built entire DC01 infrastructure from scratch over 15 sessions: WSL persistent memory, full Proxmox cluster inventory, SSH access to all systems, 6-VLAN network architecture with jumbo frames, GPU passthrough (RX580 on pve03), Tdarr transcoding pipeline, all Plex/Arr VMs migrated to proper VLANs (5/10/66), ZFS dataset renamed (`zfs-share`→`nfs-mega-share`), NFS mount points standardized, TrueNAS LACP bond + dedicated storage VLAN, iDRAC isolation to VLAN 2550, VPN (WireGuard) configured, and multiple incident recoveries (VPN lockout, network lockout, boot hangs). Full session-by-session logs preserved in `~/backup-DC01-original-2026-02-19/DC01.md.bak`.

---

## Session 16 (2026-02-19) — DC01.md Rewrite + Immediate Task Sweep

1. **DC01.md rewritten** — 84KB raw session logs → clean structured reference.
2. **Arr service stale IP audit — ALL FIXED:** Overseerr, Sonarr, Radarr, Prowlarr updated from .0.x to correct VLAN IPs.
3. **NFS permission fix** — arr-data SQLite DBs fixed to 664.
4. **DNS verification** — VM 101 and VM 102 resolv.conf correct.
5. **Plex identity verified** — claimed=1, running.
6. **Backup dirs cleaned** — 3 VMs cleaned of stale migration backups.
7. **Switch static route added** — `10.25.100.0/24 via 10.25.0.1`.
8. **pve03 vmbr0.2550 already active.**

---

> **Sessions 17–31:** Archived to `completed/DC01-ChangeLog-S017-S031.md` during original DC01.md rewrite.

---

## Session 32 (2026-02-20) — Docker Infrastructure Overhaul + LACP Cutover

1. **Docker Overhaul Phases 0-9 COMPLETE:** `/opt/dc01/` structure on all 5 VMs, configs migrated NFS→local, NFS `plex/`→`media/`, NFS mount options hardened, daily backup cron deployed, 13 containers verified.
2. **LACP Cutover COMPLETE:** Round 1 failed (switch Po2 as L3), fixed with `switchport` first. Round 2 timing issue → manual fix. MTU 9000 restored. Gluetun restart needed (WireGuard sessions don't survive LACP transitions). **Final: Both ports ACTIVE/COLLECTING/DISTRIBUTING, Po2 SU, MTU 9000.**

---

## Session 34 (2026-02-20) — Full Infrastructure Overhaul & Hardening

**Full audit:** 34 findings (3 CRITICAL, 7 HIGH, 13 MEDIUM, 11 LOW). 18 new. Report: `~/dc01-overhaul/docs/AUDIT-S043.md`.

**20 categories of fixes applied:** Switch password encryption, TrueNAS timezone, stale VLANs investigated, NFS cleanup (1.1G removed), NFS sysctl tuning (7 systems), VM network configs (MTU/DNS fixes), Docker hardening (.env 600, API key to .env), backup cron fixed (all 5 VMs), NFS VLAN correction (VMs 101/102 mgmt→storage), pve03 swap added, ZFS upgrade, security updates, SSH X11 disabled, plex sudo removed, switch NTP configured, staging data redacted, pve01 cleanup, NFS root cleanup.

---

## Session 35 (2026-02-20) — Assessments, LACP Outage & Recovery

**Assessments:** 13 items documented (NFS optimization, performance baselines, VM allocations, pve02 assessment, ARCHITECTURE.md drift review, backup/monitoring recommendations).

**INCIDENT: LACP Outage** — Sonny changed pfSense VLAN MTU via GUI → "Apply Changes" restarted lagg0 → switch err-disabled Gi1/47-48. ALL inter-VLAN routing DOWN. Sonny recovered at datacenter (removed channel-group, failover mode). Lessons #19-20.

---

## Session 36 (2026-02-21) — DR Architecture: LACP Restore, WAN LAG, WANDR/LANDR

**Phase 1:** LAN LACP restored, MTU 9000, errdisable recovery added.
**Phase 2:** LAN DR switch port Gi1/46 configured.
**Phase 3:** DR interface assignment (opt7=LANDR, opt8=WANDR). INCIDENT: `rc.reload_interfaces` bounced LACP again. Recovered via DR port + /32 host route trick.
**Phase 4:** WAN LAG. Attempt 1 failed (pf bound to old interface). Attempt 2 success (WANDR VPN failover first, config.xml edit, reboot on DR endpoint).
**Phase 5 (Partial):** WANDR configured (100.101.14.3/28, VIP 69.65.20.57, VPN failover tested).
**LACP stability:** Removed `lacp rate fast`, errdisable recovery 30s.
**LAN failover script** deployed. Watchdog cron created. Lessons #21-33.

---

## Session 37 (2026-02-21) — Documentation Sync, WANDRGW Analysis

Full memory files rewritten. WANDRGW "Unknown" analyzed (dpinger conflict). DC01.md and CLAUDE.md updated with S036 changes. Health check: VM 103 gluetun UNHEALTHY (F-S037-VM103-FW). F-S034-MTU CLOSED.

---

## Session 38 (2026-02-23) — Default Route Fix, Self-Inflicted Incident

Root cause: Default route resolved to igc0 (WANDR). INCIDENT: Changed igc0 /28→/32 → killed cached default route → VPN died. Sonny rebooted pfSense. Fix: Added `gateway=WANGW` to opt5+opt6 rules (policy routing via lagg1). F-S037-VM103-FW CLOSED (was routing, not firewall).

---

## Session 39 (2026-02-23) — VLAN Traffic Segregation

Phase 1 (WSL SMB→Storage): BLOCKED on WG route. Phase 2 (pve03 ISO NFS→Storage): DONE. Phase 3 (VM 102 Docker ports → .255 only): DONE. Phase 4 (VM 105 Docker ports): DONE.

---

## Session 40 (2026-02-23) — NFS Write Fix, Backup Cron Fix, NFS Cleanup

NFS write failure on VMs 101/102 diagnosed — pfSense TCP forwarding issue, routed via switch L3. Backup cron fixed. NFS cleaned (1.1GB stale). Downloads cleaned (~530GB reclaimed). Media integrity verified (58 files, 459GB). Plex library scan. Solo MKV corrupt. qBit credential mismatch found. Lessons #35-36.

---

## Session 41 (2026-02-24) — pfSense Cleanup, IP Binding Audit, VM 103 Static IP

pfSense svc-admin config.xml fixed (missing admins groupname, stale hashes). IP binding audit (all 5 VMs). VM 103 changed DHCP → static 10.25.66.25, ports bound to dirty VLAN, dhcpcd disabled.

---

## Session 42 (2026-02-24) — Reboot Verification, qBit VPN Access Fix

4 persistence items verified. TrueNAS post-init cleaned. qBit VPN access fixed (3-layer: pfSense pass rule + VM policy routing table 200 + Docker bridge routes). VM 103 double-reboot verified clean. Service IP & Port Map created. Lessons #37-38.

---

## Session 43 (2026-02-24) — pvestatd Fix, Cluster Health, Full Audit

pvestatd hung on NFS timeout (4 days) → restarted on both nodes. Cluster: quorate, pve02 dropped. pve02 homework updated. **Full audit: 34 findings (3 CRITICAL, 7 HIGH, 13 MEDIUM, 11 LOW).** Key: pfSense PermitRootLogin + root/admin same password, SSH password auth everywhere, NTP failed. Lesson #39.

---

## Session 44 (2026-02-24) — Hardening Sweep (8 Findings Fixed)

Physical access unavailable. Fixed: rpcbind blocked (7 systems), SPICE proxy restricted, pve01 NFS restricted, pve03 VLAN 5 IP removed, Tdarr pinned to digest, stale Docker networks removed, plex user locked, WiFi blacklisted. TrueNAS GUI: NONE cipher removed, Docker subnet removed from NFS ACL, NTP partially fixed. New findings: pfSense NTP broken, mgmt ping blocked.

---

## Session 45 (2026-02-24) — Plex Stack Wiring + Tdarr VLAN Migration

qBit creds reset (svc-admin), mgmt VLAN ports added. Prowlarr→FlareSolverr/Radarr/Sonarr fixed. Huntarr+Bazarr connected. 4 test downloads completed. Tdarr moved VLAN 10→5 (pnpm needs internet). VLAN 10 now empty.

---

## Session 46 (2026-02-24) — Media Wipe + Hardlink Pipeline + Security Hardening + VM 103 Storage NIC

Media wiped for fresh start. Compose rewritten for unified /data mount (hardlinks). Auto-cleanup configured. Pipeline proven (Iron Man test). SSH hardened to .255 only on all VMs. rpcbind blocked on ens20. VM 103 storage NIC added. TrueNAS NFS binding changed to storage-only. Full VLAN audit. WSL SMB recovered (table 100 route). Lessons #40-42.

---

## Session 47 (2026-02-24) — Storage VLAN NIC Compliance + Obsidian Vault Overhaul

Storage NICs added to VMs 101/102/104/105 via hotplug. Old static routes removed. TrueNAS stale routes removed. NFS ACL tightened (6→3 networks). Obsidian vault complete rewrite (40 files). Script documentation added (11-Scripts/). Lesson #43.

---

*Archived: S053 (2026-02-25)*
