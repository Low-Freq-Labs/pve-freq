# DC01 Audit Report — S027-20260220 — 2026-02-20

> **First audit under JARVIS v1.1 framework. Baseline establishment.**
> EXEC: audit | WORKERS: all | SCOPE: none (full DC01)

---

## Backup Status

| System | Backup Current? | Diffs Found | Classification | Action Needed |
|--------|----------------|-------------|----------------|---------------|
| docker-compose.arr.yml | YES | None | - | None |
| docker-compose.plex.yml | YES | None | - | None |
| docker-compose.tdarr.yml | YES | None | - | None |
| docker-compose.tdarr-node.yml | PARTIAL | apiKey redacted in backup, plaintext in live | EXPECTED | Live file has plaintext API key — security risk |
| docker-compose.qbit.yml | YES | None | - | None |
| pve01 interfaces | YES | None | - | None |
| pve01 sudoers | YES | svc-admin already present | - | None |
| pve03 interfaces | YES | None | - | None |
| pve03 sudoers | YES | svc-admin already present | - | None |
| pve01 corosync.conf | YES | Matches live | - | None |
| pve03 corosync.conf | YES | Matches live (shared file) | - | None |
| TrueNAS users.txt | **NO** | Backup empty (query failed S24) | STALE | Needs update with live user data |
| TrueNAS zpool status | YES | No errors, pool healthy | - | None |
| TrueNAS NFS exports | YES | 7 networks, mapall correct | - | None |
| Switch running-config | **OUTDATED** | svc-admin user added S26 (+72 bytes) | NEW | Update backup with current config |
| pfSense config | **DOCS ONLY** | No live config in backup (documented only) | NEW | Consider adding sanitized config.xml |
| VM sudoers | NOT IN BACKUP | svc-admin added to all 5 VMs (S26) | NEW | Add svc-admin sudoers to VM backup templates |

---

## Docker Version Status

| VM | Service | Running Version | Pinned Version (Compose) | Match? |
|----|---------|----------------|-------------------------|--------|
| 101 | Plex | 1.43.0.10492-121068a07-ls293 | 1.43.0.10492-121068a07-ls293 | YES |
| 102 | Prowlarr | 2.3.0.5236-ls137 | 2.3.0.5236-ls137 | YES |
| 102 | Sonarr | 4.0.16.2944-ls302 | 4.0.16.2944-ls302 | YES |
| 102 | Radarr | 6.0.4.10291-ls292 | 6.0.4.10291-ls292 | YES |
| 102 | Bazarr | v1.5.5-ls337 | v1.5.5-ls337 | YES |
| 102 | Overseerr | v1.34.0-ls157 | v1.34.0-ls157 | YES |
| 102 | Huntarr | 9.3.7 | 9.3.7 | YES |
| 102 | Agregarr | v2.4.0 | v2.4.0 | YES |
| 103 | qBittorrent | 5.1.4-r2-ls440 | 5.1.4-r2-ls440 | YES |
| 103 | Gluetun | v3.41.1 | v3.41.1 | YES |
| 103 | FlareSolverr | v3.4.6 | v3.4.6 | YES |
| 104 | Tdarr Node | latest | latest (no semver) | YES (expected) |
| 105 | Tdarr Server | latest | latest (no semver) | YES (expected) |

**All 13 containers running pinned versions match compose files. Zero version drift.**

---

## Proxmox Version Status

| Node | PVE Manager | Kernel Running | Kernel Available | QEMU | Notes |
|------|-------------|----------------|-----------------|------|-------|
| pve01 | **9.1.5** | 6.17.9-1-pve | 6.17.9-1-pve | 10.1.2-6 | Current |
| pve03 | **9.1.6** | 6.17.9-1-pve | **6.17.13-1-pve** | 10.1.2-**7** | VERSION DRIFT — pve-manager, kernel, QEMU all newer |

**FINDING [DRIFT]:** pve03 has been updated to PVE 9.1.6 while pve01 remains at 9.1.5. pve03 also has a newer kernel (6.17.13-1) available but not booted. This creates inconsistency in the cluster. pve01 should be updated to match, or this should be documented as intentional.

---

## HA & Cluster Status

| Component | State | Concern |
|-----------|-------|---------|
| Quorum | OK | Healthy |
| HA Master | pve03 (idle since Feb 17 15:55) | Normal |
| LRM pve01 | Idle (current) | Healthy |
| LRM pve02 | **DEAD since Feb 5** | **15 DAYS STALE — investigate** |
| LRM pve03 | Idle (current) | Healthy |

**FINDING [PROBABLE]:** pve02 LRM has been dead/unreachable for 15 days (since Feb 5). While pve02 is OUT OF SCOPE, its dead LRM status affects cluster quorum calculations. If pve02 is permanently offline, it should be removed from the cluster to prevent quorum issues if one of the remaining two nodes goes down.

---

## Infrastructure Findings

### CRITICAL

| # | Finding | Confidence | Ticket |
|---|---------|------------|--------|
| F-001 | Dual single-PSU operation: R530 PSU1 + T620 PSU2 failed | [CONFIRMED] | PA-01 (existing) |
| F-002 | No VM backup strategy — zero automated backups | [CONFIRMED] | DP-01 (existing) |
| F-003 | No monitoring/alerting — failures discovered by impact only | [CONFIRMED] | ML-01 (existing) |
| F-004 | Temp password `changeme1234!` on ALL 10 systems — single compromise = full access | [CONFIRMED] | TICKET-0006 (new) |

### HIGH

| # | Finding | Confidence | Ticket |
|---|---------|------------|--------|
| F-005 | pfSense lagg0 MTU=1500 (should be 9000) — limits all inter-VLAN traffic | [CONFIRMED] | Existing |
| F-006 | TrueNAS svc-admin primary GID is 3000, not 950 (truenas_admin) | [CONFIRMED] | TICKET-0007 (new) |
| F-007 | pve02 HA LRM dead 15 days — quorum risk if another node fails | [PROBABLE] | TICKET-0008 (new) |
| F-008 | Proxmox version drift: pve03 at 9.1.6, pve01 at 9.1.5 | [CONFIRMED] | TICKET-0009 (new) |
| F-009 | iDRAC default passwords on both production servers | [CONFIRMED] | AC-03 (existing) |

### MEDIUM

| # | Finding | Confidence | Ticket |
|---|---------|------------|--------|
| F-010 | Tdarr API key plaintext in live compose (backup properly redacted) | [CONFIRMED] | TICKET-0010 (new) |
| F-011 | pve03 MTU mismatch: vmbr0v2550=9000, nic0.2550=1500 | [CONFIRMED] | Sonny GUI task |
| F-012 | TrueNAS REST API deprecation warning — removed in 26.04 | [CONFIRMED] | TICKET-0011 (new) |
| F-013 | Switch `no service password-encryption` — type 7 passwords would be cleartext | [CONFIRMED] | TICKET-0012 (new) |
| F-014 | base_config TrueNAS users.txt incomplete (query failed S24) | [CONFIRMED] | Phase D update |

### LOW

| # | Finding | Confidence | Ticket |
|---|---------|------------|--------|
| F-015 | TICKET-0001 (P1) unresolved for 8 sessions | [CONFIRMED] | Escalation |
| F-016 | VM 104 SSH slow/timeout — possible NFS stale mount intermittent | [HYPOTHESIS] | Monitor |
| F-017 | VM 103 still on DHCP (10.25.66.10) — Sonny decision pending | [CONFIRMED] | Sonny decision |

---

## DC01.md Currency

| Section | Current? | Update Needed? | Proposed Edit |
|---------|----------|----------------|---------------|
| Physical Hardware | YES | Minor | Add TrueNAS version 25.10.1, pfSense version 26.03.b |
| Proxmox cluster | PARTIAL | YES | pve01 is PVE 9.1.5, pve03 is PVE 9.1.6 (not both 9.1.5) |
| VMs | YES | No | Accurate |
| Docker versions | YES | No | All match live |
| Network | YES | No | LAGG status accurate |
| svc-admin | YES | Minor | Note TrueNAS primary GID 3000 (not 950) |
| Session history | YES | No | Current through S26 |

---

## CLAUDE.md Currency

| Section | Current? | Update Needed? | Proposed Edit |
|---------|----------|----------------|---------------|
| Identity | YES | No | - |
| Our Memory Logs | YES | No | - |
| Infrastructure | PARTIAL | YES | pve03 is PVE 9.1.6, not 9.1.5. Add pfSense version. |
| Plex Stack | YES | No | Docker versions match |
| SSH Access | YES | No | svc-admin access confirmed on all systems |
| Session findings | YES | No | S26 findings accurate |
| Pending decisions | YES | No | All still pending |

---

## Knowledge Base Sync

| Obsidian Page | Status | Notes |
|---------------|--------|-------|
| 00-Overview.md | Created | First audit baseline |
| 01-Hardware.md | Created | PSU/fan alerts documented |
| 02-Network/ (5 pages) | Created | VLAN map, switch, firewall, WG, jumbo |
| 03-Storage/ (4 pages) | Created | ZFS, NFS, SMB |
| 04-VMs/ (6 pages) | Created | Inventory + per-VM detail |
| 05-Services/ (3 pages) | Created | Compose index, URLs, versions |
| 06-Cluster/ (3 pages) | Created | HA, corosync, storage |
| 07-Security/ (4 pages) | Created | SSH, users, sudo, audit |
| 08-Backups/ (2 pages) | Created | Manifest, rebuild guide |
| 09-Lessons-Learned.md | Created | 9 hard-won rules |
| 10-Runbooks/ (4 pages) | Created | NFS, VM, network, contacts |
| _audit/ (2 pages) | Created | Last audit, history |
| Existing files | Archived | Moved to _archive-pre-audit/ |

---

## Open Findings Summary

| Priority | Count | Details |
|----------|-------|---------|
| CRITICAL | 4 | PSU failures, no backups, no monitoring, temp password everywhere |
| HIGH | 5 | MTU, GID mismatch, pve02 dead, version drift, iDRAC passwords |
| MEDIUM | 5 | Tdarr API key, pve03 MTU, REST API deprecation, switch encryption, backup gap |
| LOW | 3 | TICKET-0001 aging, VM104 slowness, VM103 DHCP |
| **Total** | **17** | 4 existing, 7 new tickets, 6 tracked items |

---

## Audit Summary

- **Systems audited:** 10/10 (pve01, pve03, VMs 101-105, TrueNAS, switch, pfSense)
- **Systems reachable:** 10/10 over VPN
- **Backup files checked:** 92 files in DC01_v1.1_base_config
- **Backup diffs found:** 4 (1 EXPECTED, 1 STALE, 2 NEW)
- **Docker versions matched:** 13/13 (100%)
- **New tickets created:** 7 (TICKET-0006 through TICKET-0012)
- **KB pages written:** 34 (full vault creation)
- **SMB-PUBLIC reachable:** YES
- **Credential exposure in staging files:** Switch hashes (type 5 MD5, standard), Tdarr API key (already known)
- **Session tag:** S027-20260220

---

## Next Audit Recommended

**Date:** 2026-03-20 (30-day cadence)
**Or:** After any of: LACP cutover, credential rotation, pve01 update to 9.1.6, backup strategy deployment

---

## Appendix: Phase A Pull Summary

| System | Pull Method | Status | File |
|--------|-----------|--------|------|
| pve01 | SSH svc-admin@10.25.0.26 | COMPLETE | staging/S027-20260220/pve01/full-pull.txt |
| pve03 | SSH svc-admin@10.25.0.28 | COMPLETE | staging/S027-20260220/pve03/full-pull.txt |
| VM 101 | SSH svc-admin@10.25.255.30 | COMPLETE | staging/S027-20260220/vm101/full-pull.txt |
| VM 102 | SSH svc-admin@10.25.255.31 | COMPLETE | staging/S027-20260220/vm102/full-pull.txt |
| VM 103 | SSH svc-admin@10.25.255.32 | COMPLETE | staging/S027-20260220/vm103/full-pull.txt |
| VM 104 | SSH svc-admin@10.25.255.34 | COMPLETE (retry) | staging/S027-20260220/vm104/full-pull.txt |
| VM 105 | SSH svc-admin@10.25.255.33 | COMPLETE | staging/S027-20260220/vm105/full-pull.txt |
| TrueNAS | SSH svc-admin@10.25.0.25 | COMPLETE | staging/S027-20260220/truenas/full-pull.txt |
| Switch | SSH svc-admin@10.25.255.5 | COMPLETE | staging/S027-20260220/switch/running-config.txt |
| pfSense | SSH svc-admin@10.25.255.1 | PARTIAL (tcsh shell issues) | staging/S027-20260220/pfsense/full-pull.txt + supplemental-pull.txt |
