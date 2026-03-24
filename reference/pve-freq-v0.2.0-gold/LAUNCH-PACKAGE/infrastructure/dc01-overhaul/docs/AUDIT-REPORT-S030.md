# DC01 Audit Report — S030-20260220 — 2026-02-20

> **Second audit. Follow-up to S027 baseline. Post-S029 changes validated.**
> EXEC: audit | WORKERS: all | SCOPE: none (full DC01)
> Sonny's audit note: temp files, SOC compliance, svc-admin gaps, web UI binding, VLAN separation

---

## S027 → S030 Finding Tracker

| S027 # | Finding | S027 Severity | S030 Status | Notes |
|--------|---------|---------------|-------------|-------|
| F-001 | Dual single-PSU operation (R530 PSU1 + T620 PSU2 failed) | CRITICAL | **STILL OPEN** | No change. Hardware replacement needed. |
| F-002 | No VM backup strategy | CRITICAL | **STILL OPEN** | No change. Proxmox Backup Server evaluation pending. |
| F-003 | No monitoring/alerting | CRITICAL | **STILL OPEN** | No change. Uptime Kuma or similar not deployed. |
| F-004 | Temp password `changeme1234!` on ALL 10 systems | CRITICAL | **STILL OPEN** | Confirmed live. SSH key deployment + rotation still pending. |
| F-005 | pfSense lagg0 MTU=1500 (should be 9000) | HIGH | **STILL OPEN** | Confirmed. Limits jumbo frame throughput on all inter-VLAN traffic. |
| F-006 | TrueNAS svc-admin primary GID 3000 ≠ 950 | HIGH | **STILL OPEN** | Confirmed: `gid=3000(svc-admin)`. TICKET-0007. |
| F-007 | pve02 HA LRM dead | HIGH | **STILL OPEN** | Dead since Feb 5 (now 15+ days). Quorum risk persists. |
| F-008 | Proxmox version drift: pve03 > pve01 | HIGH | **STILL OPEN** | pve01=9.1.5, pve03=9.1.6. QEMU/kernel/widget-toolkit also diverged. |
| F-009 | iDRAC default passwords | HIGH | **STILL OPEN** | No change. Both R530 + T620 iDRACs still at defaults. |
| F-010 | Tdarr API key plaintext in compose | MEDIUM | **VERIFY** | Need compose file re-check (not pulled this session). |
| F-011 | pve03 MTU mismatch: vmbr0v2550 vs nic0.2550 | MEDIUM | **CLOSED** | Sonny fixed via Proxmox GUI (S29). Verified: both at 9000. |
| F-012 | TrueNAS REST API deprecation (removed in 26.04) | MEDIUM | **STILL OPEN** | Still running 25.10.x. Migration deadline approaching. |
| F-013 | Switch `no service password-encryption` | MEDIUM | **UPGRADED → CRITICAL** | Now F-018. Plaintext passwords discovered on console/VTY lines. |
| F-014 | base_config TrueNAS users.txt incomplete | MEDIUM | **STILL OPEN** | Needs base_config update with live user data. |
| F-015 | TICKET-0001 (P1) unresolved | LOW | **STILL OPEN** | 11+ sessions old. Needs triage or closure. |
| F-016 | VM 104 NFS instability | LOW | **STILL OPEN** | Observed again S29 (3rd occurrence). Root cause: likely pve03 nic0.10 MTU mismatch. |
| F-017 | VM 103 still on DHCP (10.25.66.10) | LOW | **STILL OPEN** | Sonny decision still pending. |

**S027 Score: 17 findings. S030: 1 closed, 1 upgraded, 15 still open.**

---

## New Findings — S030

### CRITICAL

| # | Finding | Confidence | System | Details |
|---|---------|------------|--------|---------|
| F-018 | Switch plaintext passwords on console & VTY lines | [CONFIRMED] | Switch | `no service password-encryption` + literal `m4st3rp4$$` on `line con 0` and `line vty 0 4`. Anyone with console or `show running-config` access sees the password. Upgrades S027 F-013 from MEDIUM. **Immediate action: `service password-encryption` + change password.** |

### HIGH

| # | Finding | Confidence | System | Details |
|---|---------|------------|--------|---------|
| F-019 | pfSense svc-admin UID/GID does not match DC01 standard | [CONFIRMED] | pfSense | UID=2002 (should be 3003), GID=0/wheel (should be 950/truenas_admin). Breaks the "standardized across ALL 10 systems" claim. pfSense BSD user management assigns UIDs sequentially; fixing requires `pw usermod`. |
| F-020 | pfSense webGUI accessible on ALL interfaces | [CONFIRMED] | pfSense | nginx binds `*:4443` and `*:80` on both IPv4 and IPv6. WebGUI reachable from LAN (10.25.0.1), all VLANs, and WireGuard. Violates management-VLAN-only policy. Known from S029 — `webguiinterfaces` config option non-functional. **Fix: Firewall rule on LAN/VLAN interfaces blocking TCP:4443 to self.** |

### MEDIUM

| # | Finding | Confidence | System | Details |
|---|---------|------------|--------|---------|
| F-021 | TrueNAS IPv6 web listeners bypass IPv4 binding restriction | [CONFIRMED] | TrueNAS | `ui_address` correctly set to `["10.25.255.25"]` but `[::]:80` and `[::]:443` listen on ALL IPv6 interfaces. Any host with IPv6 connectivity to TrueNAS can reach the web UI, bypassing the management-VLAN-only intent. **Fix: set `ui_v6address` to a specific IPv6 address or disable IPv6 web binding.** |
| F-022 | TrueNAS SSH listens on 0.0.0.0:22 (all networks) | [CONFIRMED] | TrueNAS | SSH reachable from LAN (10.25.0.25), Storage VLAN (10.25.25.25), and Mgmt VLAN (10.25.255.25). Should be restricted to management VLAN only, or disabled when not in active use. SSH is currently `enabled: true` in service config. |
| F-023 | pve03 nic0.10 (VLAN 10 Compute) MTU still 1500 vs vmbr0v10 at 9000 | [CONFIRMED] | pve03 | Same mismatch pattern as F-011 (now closed). VM 104 on Compute VLAN suffers NFS instability (F-016, 3rd occurrence). **Fix: Proxmox GUI → pve03 → Network → vmbr0v10 → set NIC MTU to 9000.** |

### LOW

| # | Finding | Confidence | System | Details |
|---|---------|------------|--------|---------|
| F-024 | TrueNAS timezone America/Los_Angeles ≠ DC01 standard | [CONFIRMED] | TrueNAS | All VMs use `America/Chicago`. TrueNAS at `America/Los_Angeles`. Causes 2-hour log timestamp offset. **Fix: `midclt call system.general.update '{"timezone":"America/Chicago"}'`** |
| F-025 | Stale VLANs 113 and 715 on switch | [CONFIRMED] | Switch | No description, no ports assigned. Hygiene issue — leftover from pre-DC01 config. **Fix: `no vlan 113` and `no vlan 715` if confirmed unused.** |
| ~~F-026~~ | ~~Switch Gi1/36 unconfigured~~ | EXPECTED | Switch | **Per Sonny:** Device on this port is expected and by design. Current default config works correctly for this port. No action needed. |

---

## SOC Compliance Assessment

### AC — Access Control

| Check | Status | Details |
|-------|--------|---------|
| Unique accounts per admin | PASS | 4 named users on Proxmox (donmin, root, sonny-aif, svc-admin). Named users on switch. |
| Principle of least privilege | **FAIL** | svc-admin has NOPASSWD sudo + full admin on ALL systems. Single account = full access everywhere. No role separation. |
| Password policy | **FAIL** | Temp password `changeme1234!` still active on all 10 systems. No complexity enforcement. No rotation policy. |
| SSH key authentication | **FAIL** | Password-only SSH auth. No SSH keys deployed. No key-only enforcement. |
| Multi-factor authentication | **FAIL** | MFA not configured on any system. |
| Inactive account management | WARN | pve02-related accounts stale (LRM dead 15 days). sonny-aif account pending decommission. |

### DP — Data Protection

| Check | Status | Details |
|-------|--------|---------|
| Backup strategy | **FAIL** | No automated VM backups. No Proxmox Backup Server. Config backup (base_config) exists but is manual/static. |
| Backup testing | **FAIL** | No restore tests performed. |
| Encryption at rest | **FAIL** | ZFS pool not encrypted. VM disks not encrypted. |
| Encryption in transit | PARTIAL | NFS v3 (no encryption). SMB likely SMB3. Web UIs use TLS. SSH encrypted. |

### NS — Network Security

| Check | Status | Details |
|-------|--------|---------|
| VLAN segmentation | PASS | 6 VLANs properly segmented (LAN, Public, Compute, Storage, Dirty, Management). |
| Web UI isolation to management | PARTIAL | pve01/pve03: PASS (iptables). TrueNAS IPv4: PASS. **pfSense: FAIL** (all interfaces). **TrueNAS IPv6: FAIL** (all interfaces). |
| Service traffic separation | PASS | NFS/SMB bound to Storage + Mgmt VLANs. VMs access NFS via Storage VLAN. VM 103 correctly isolated on Dirty VLAN via Mgmt. |
| Firewall rules | PARTIAL | pfSense inter-VLAN rules not hardened. VLAN 5 can potentially reach more than just Storage. |
| Switch security | **FAIL** | Plaintext passwords. No port security. No 802.1X. No DHCP snooping. |

### ML — Monitoring & Logging

| Check | Status | Details |
|-------|--------|---------|
| Centralized logging | **FAIL** | No syslog server. Each system logs locally only. |
| Alerting | **FAIL** | No automated alerts for PSU failure, disk issues, NFS stale, service down. |
| Log retention | **FAIL** | No defined retention policy. Default system rotation only. |
| Audit trail | PARTIAL | Manual audit reports (S027, S030). No continuous audit logging. |

### PA — Physical & Availability

| Check | Status | Details |
|-------|--------|---------|
| Redundant power | **FAIL** | Both servers running on single PSU. R530 has dead Fan 6. |
| High availability | PARTIAL | Proxmox HA configured but pve02 dead. 2-node cluster = no real HA. |
| Disaster recovery | **FAIL** | No DR plan. No offsite backups. Single datacenter. |

### CM — Change Management

| Check | Status | Details |
|-------|--------|---------|
| Change tracking | PASS | All changes documented in CLAUDE.md session findings + DC01.md. |
| Config backups pre-change | PASS | Backup procedure in CLAUDE.md. config.xml backups on pfSense. |
| Rollback capability | PARTIAL | Config backups exist but no automated rollback. ZFS snapshots not used for config management. |

### VM — Vulnerability Management

| Check | Status | Details |
|-------|--------|---------|
| Patch cadence | PARTIAL | pve03 updated (9.1.6), pve01 behind (9.1.5). No defined cadence. |
| Container updates | PASS | All 13 containers at pinned versions matching compose files. |
| OS updates (VMs) | UNKNOWN | VM OS update status not checked this session. |

**Overall SOC Posture: HIGH RISK** — Improved from S027 (web UI restrictions, NFS VLAN binding) but fundamental gaps remain in access control, backup, monitoring, and password management.

---

## Docker Version Status

| VM | Service | Running Version | Pinned? | Match? |
|----|---------|----------------|---------|--------|
| 101 | Plex | 1.43.0.10492-121068a07-ls293 | YES | YES |
| 102 | Prowlarr | 2.3.0.5236-ls137 | YES | YES |
| 102 | Sonarr | 4.0.16.2944-ls302 | YES | YES |
| 102 | Radarr | 6.0.4.10291-ls292 | YES | YES |
| 102 | Bazarr | v1.5.5-ls337 | YES | YES |
| 102 | Overseerr | v1.34.0-ls157 | YES | YES |
| 102 | Huntarr | 9.3.7 | YES | YES |
| 102 | Agregarr | v2.4.0 | YES | YES |
| 103 | qBittorrent | 5.1.4-r2-ls440 | YES | YES |
| 103 | Gluetun | v3.41.1 | YES | YES |
| 103 | FlareSolverr | v3.4.6 | YES | YES |
| 104 | Tdarr Node | latest | NO (expected) | YES |
| 105 | Tdarr Server | latest | NO (expected) | YES |

**All 13 containers running versions match compose files. Zero version drift. Tdarr `:latest` is expected — no semver tags on ghcr.io.**

---

## Proxmox Version Status

| Node | PVE Manager | Kernel Running | Kernel Available | QEMU | Notes |
|------|-------------|----------------|-----------------|------|-------|
| pve01 | **9.1.5** | 6.17.9-1-pve | 6.17.9-1-pve | 10.1.2-6 | Behind pve03 |
| pve03 | **9.1.6** | 6.17.9-1-pve | **6.17.13-1-pve** | 10.1.2-**7** | Newer kernel available but not booted |

**Version drift still present (F-008). Additionally: pve03 has proxmox-backup-client 4.1.4 vs pve01 4.1.2, widget-toolkit 5.1.6 vs 5.1.5, pve-container 6.1.2 vs 6.1.1, pve-firmware 3.18 vs 3.17. pve01 should be updated to match.**

---

## svc-admin Standardization Verification

| System | UID | GID | Groups | NOPASSWD sudo | Status |
|--------|-----|-----|--------|---------------|--------|
| pve01 | 3003 | 950 | truenas_admin, sudo | YES | **PASS** |
| pve03 | 3003 | 950 | truenas_admin, sudo | YES | **PASS** |
| VM 101 | 3003 | 950 | truenas_admin, sudo, docker | YES | **PASS** |
| VM 102 | 3003 | 950 | truenas_admin, sudo, docker | YES | **PASS** |
| VM 103 | 3003 | 950 | truenas_admin, sudo, docker | YES | **PASS** |
| VM 104 | 3003 | 950 | truenas_admin, sudo, docker | YES | **PASS** |
| VM 105 | 3003 | 950 | truenas_admin, sudo, docker | YES | **PASS** |
| TrueNAS | 3003 | **3000** | svc-admin, builtin_administrators, truenas_admin | YES | **FAIL** — GID 3000 ≠ 950 |
| pfSense | **2002** | **0 (wheel)** | wheel, admins | YES | **FAIL** — UID and GID mismatch |
| Switch | N/A | N/A | privilege 15 | N/A | **PASS** (IOS model) |

**Score: 7/9 matching (excluding switch). TrueNAS GID and pfSense UID/GID still non-standard.**

---

## NFS Mount Consistency

| VM | fstab Server IP | Mount Point | NFS Version | Backward Symlink | Status |
|----|----------------|-------------|-------------|-------------------|--------|
| 101 | 10.25.25.25 | /mnt/truenas/nfs-mega-share | nfsvers=3 | /mnt/nfs-mega-share → /mnt/truenas/nfs-mega-share | **PASS** |
| 102 | 10.25.25.25 | /mnt/truenas/nfs-mega-share | nfsvers=3 | Present | **PASS** |
| 103 | 10.25.255.25 | /mnt/truenas/nfs-mega-share | nfsvers=3 | /mnt/nfs-mega-share → /mnt/truenas/nfs-mega-share | **PASS** (Mgmt VLAN — expected for dirty) |
| 104 | 10.25.25.25 | /mnt/truenas/nfs-mega-share | nfsvers=3 | Present | **PASS** |
| 105 | 10.25.25.25 | /mnt/truenas/nfs-mega-share | nfsvers=3 | Present | **PASS** |

**All 5 VMs consistent. S029 NFS migration fully verified.**

**NFS Health Note:** VM 102 NFS mount was unresponsive during audit pull (`df -h` timed out, directory listings empty). Mount exists and shows correct server IP (10.25.25.25) but was stale/slow. This is on pve01, separate from VM 104's chronic NFS issues on pve03. May indicate broader NFS stability concern — possibly TrueNAS NFS service under load, or intermittent Storage VLAN connectivity.

---

## Web UI / Service Binding Verification

| System | Web UI Binding (IPv4) | IPv6 | Management Only? | Finding |
|--------|----------------------|------|-----------------|---------|
| pve01 | *:8006 (iptables restricts to vmbr0v2550) | N/A | **PASS** | iptables rules verified |
| pve03 | *:8006 (iptables restricts to vmbr0v2550) | N/A | **PASS** | iptables rules verified |
| TrueNAS | 10.25.255.25:80, 10.25.255.25:443 | **[::]:80, [::]:443** | **PARTIAL** | IPv4 correct, IPv6 leaks (F-021) |
| pfSense | *:4443, *:80 | *:4443, *:80 | **FAIL** | All interfaces, IPv4 + IPv6 (F-020) |

| System | NFS Binding | SMB Binding | Service VLAN Only? |
|--------|------------|------------|-------------------|
| TrueNAS NFS | 10.25.25.25:2049, 10.25.255.25:2049 | N/A | **PASS** — Storage + Mgmt |
| TrueNAS SMB | N/A | 10.25.25.25:445, 10.25.255.25:445 | **PASS** — Storage + Mgmt |

| System | SSH Binding | Management Only? |
|--------|------------|-----------------|
| pve01 | 0.0.0.0:22 | No restriction (but less critical — server SSH) |
| pve03 | 0.0.0.0:22 | No restriction |
| TrueNAS | 0.0.0.0:22 | **FAIL** — accessible from all networks (F-022) |
| pfSense | *:22 | No restriction |
| All VMs | 0.0.0.0:22 | No restriction |

---

## Temp File / Artifact Scan

| System | PHP files | PY files | Temp artifacts | Bad bash remnants | Status |
|--------|-----------|----------|----------------|-------------------|--------|
| pve01 | None | None | None | None | **CLEAN** |
| pve03 | None | None | None | None | **CLEAN** |
| TrueNAS | None | None | None | N/A | **CLEAN** |
| pfSense | None | None | rules.debug.old, kea scripts (normal) | N/A | **CLEAN** |
| VM 101 | None | None | None | None | **CLEAN** |
| VM 102 | None | None | None | None | **CLEAN** |
| VM 103 | None | None | None | None | **CLEAN** |
| VM 104 | None | None | None | None | **CLEAN** |
| VM 105 | None | None | None | None | **CLEAN** |
| NFS share | None | None | None | N/A | **CLEAN** |

**Zero temp files, zero PHP/PY remnants, zero bad bash artifacts across all 10 systems + NFS share.**

---

## Credential Hygiene — Staging Files

| Item | Found In | Action | Status |
|------|----------|--------|--------|
| TrueNAS TLS private key | truenas-general-config.txt | Redacted to `<REDACTED - TLS PRIVATE KEY>` | **DONE** |
| WireGuard private key | pfsense-config-xml.txt line 2043 | Redacted to `<REDACTED - WG PRIVATE KEY>` | **DONE** |
| pfSense SSL private key | pfsense-config-xml.txt line 1886 | Redacted to `<REDACTED - SSL PRIVATE KEY>` | **DONE** |
| Switch console/VTY passwords (2x) | switch-running-config.txt lines 497/501 | Redacted to `<REDACTED - PLAINTEXT PASSWORD>` | **DONE** |
| TrueNAS SHA-512 password hashes (11x) | truenas-users.txt | Redacted to `<REDACTED - SHA512 HASH>` | **DONE** |
| pfSense bcrypt hashes (6x) | pfsense-config-xml.txt | Kept — bcrypt hashes are non-reversible | OK |
| Switch type 5 MD5 hashes (4x) | switch-running-config.txt | Kept — standard for IOS config | OK |
| `/tmp/.svc-pass` password file | /tmp/.svc-pass | Used for SSH automation, contains temp password | **CLEANED UP** by pve01/pve03 agent |

---

## Positive Changes Since S027

1. **pve01/pve03 webGUI restricted** — iptables rules on port 8006 accept only vmbr0v2550, cluster peer, localhost. Verified working.
2. **TrueNAS web UI bound to management VLAN** — `ui_address: ["10.25.255.25"]` (IPv4 correct).
3. **TrueNAS NFS bound to Storage + Mgmt VLANs** — `bindip: ["10.25.25.25", "10.25.255.25"]`.
4. **TrueNAS SMB bound to Storage + Mgmt VLANs** — Same binding as NFS.
5. **NFS mount migration complete** — All 5 VMs at `/mnt/truenas/nfs-mega-share` with backward-compat symlinks.
6. **pve03 VLAN 2550 MTU fixed** — nic0.2550 now at 9000 (F-011 closed).
7. **VM 101 renamed** — "Plex" → "Plex-Server" per naming standard.
8. **VPN routes persisted** — pve01, pve03, TrueNAS, switch all have persistent `10.25.100.0/24` routes via management VLAN gateway.

---

## Open Findings Summary

| Priority | Count | Details |
|----------|-------|---------|
| CRITICAL | 5 | PSU failures (F-001), no backups (F-002), no monitoring (F-003), temp password everywhere (F-004), switch plaintext passwords (F-018) |
| HIGH | 6 | lagg0 MTU (F-005), TrueNAS GID (F-006), pve02 dead (F-007), version drift (F-008), iDRAC defaults (F-009), pfSense svc-admin UID (F-019), pfSense webGUI all interfaces (F-020) |
| MEDIUM | 4 | TrueNAS IPv6 bypass (F-021), TrueNAS SSH all networks (F-022), pve03 nic0.10 MTU (F-023), TrueNAS REST API deprecation (F-012) |
| LOW | 4 | TrueNAS timezone (F-024), stale VLANs (F-025), TICKET-0001 aging (F-015), VM 103 DHCP (F-017) |
| **Total** | **19** | 16 carried from S027 (1 closed), 9 new, 1 dismissed (F-026 expected). Net +2 from S027's 17. |

---

## Priority Actions — Sonny

### Immediate (This Week)
1. **Switch: `service password-encryption`** — One command, fixes F-018/F-013. Then change the console/VTY password.
2. **Clean up `/tmp/.svc-pass`** — `rm /tmp/.svc-pass` after this audit session.

### Short Term (Next Session)
3. **SSH key deployment + password rotation** — Eliminates F-004 (CRITICAL). Generate keypairs for svc-admin, deploy to all 10 systems, set SSH to key-only.
4. **pfSense webGUI firewall rule** — Block TCP:4443 to self on LAN/VLAN interfaces. Fixes F-020.
5. **pve03 nic0.10 MTU fix** — Proxmox GUI → Network → set nic0.10 to MTU 9000. Likely fixes VM 104 NFS (F-016/F-023).
6. **TrueNAS IPv6 web binding** — `midclt call system.general.update '{"ui_v6address": []}'` to disable IPv6 web listeners. Fixes F-021.

### Medium Term
7. **TrueNAS timezone** — `midclt call system.general.update '{"timezone": "America/Chicago"}'`. Fixes F-024.
8. **pve01 update to 9.1.6** — Match pve03. Fixes F-008.
9. **pfSense svc-admin UID/GID** — `pw usermod svc-admin -u 3003` on pfSense. Fixes F-019.
10. **Switch: remove stale VLANs** — `no vlan 113` and `no vlan 715`. Fixes F-025.

---

## Audit Summary

- **Systems audited:** 10/10 (pve01, pve03, VMs 101-105, TrueNAS, switch, pfSense)
- **Systems reachable:** 10/10 over VPN via svc-admin
- **Staging files collected:** ~198 files in `staging/S030-20260220/`
- **Docker versions matched:** 13/13 (100%)
- **NFS mounts consistent:** 5/5 (100%)
- **svc-admin standardized:** 7/9 (78%) — TrueNAS GID + pfSense UID/GID non-standard
- **Temp/artifact scan:** 10/10 clean (0 PHP, 0 PY, 0 bad bash)
- **Credential exposures found + redacted:** 16 items across 4 files (TLS key, WG key, SSL key, 2 plaintext passwords, 11 SHA-512 hashes)
- **Findings: S027→S030:** 17 → 20 (1 closed, 9 new, net +3)
- **SOC posture:** HIGH RISK (improved from S027 but fundamental gaps remain)
- **Session tag:** S030-20260220

---

## Next Audit Recommended

**Date:** 2026-03-20 (30-day cadence)
**Or:** After any of: SSH key deployment, LACP cutover, password rotation, pve01 update

---

## Appendix: Phase A Pull Summary

| System | Pull Method | Files | Status |
|--------|-----------|-------|--------|
| pve01 | SSH svc-admin@10.25.255.26 | 22 | COMPLETE |
| pve03 | SSH svc-admin@10.25.255.28 | 22 | COMPLETE |
| VM 101 | SSH svc-admin@10.25.255.30 | 24 | COMPLETE |
| VM 102 | SSH svc-admin@10.25.255.31 | 21 | COMPLETE (re-pull after password file race) |
| VM 103 | SSH svc-admin@10.25.255.32 | 25 | COMPLETE (re-pull after password file race) |
| VM 104 | SSH svc-admin@10.25.255.34 | ~22 | COMPLETE |
| VM 105 | SSH svc-admin@10.25.255.33 | 24 | COMPLETE |
| TrueNAS | SSH svc-admin@10.25.255.25 | 24 | COMPLETE |
| Switch | SSH svc-admin@10.25.255.5 | 6 | COMPLETE |
| pfSense | SSH svc-admin@10.25.255.1 | 9 | COMPLETE (tcsh shell, `sh -c` wrapper used) |
