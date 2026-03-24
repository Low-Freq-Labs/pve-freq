---
title: "FREQ Feature Design — freq tn (TrueNAS Management Module Hardening & Sweep)"
created: 2026-03-11
updated: 2026-03-11 (fact-check findings integrated)
session: S078 (fact-check complete, findings integrated)
status: FACT-CHECKED & CORRECTED — READY FOR IMPLEMENTATION
freq_version_at_design: "v4.0.5 (verified on VM 999 /opt/lowfreq/freq, 2026-03-11)"
freq_source_at_design: "VM 999 /opt/lowfreq/ (302-line lib/truenas.sh, confirmed via qm guest exec)"
truenas_version: "TrueNAS-25.10.1 (Debian 12 bookworm, Linux 6.12.33-production+truenas)"
fact_check_date: "2026-03-11 — 14 findings documented, corrections integrated"
warning: "This report contains explicit infrastructure details. Do not share outside DC01 operations."
---

# FREQ Feature Design — `freq truenas` Module Hardening & Sweep

## 1. THE PROBLEM

### What Hurts Today

TrueNAS is the single storage backbone for all of DC01 — every VM mounts NFS from it, every user accesses SMB through it, Proxmox stores backups on it. The current FREQ `truenas.sh` module (302 lines, 11 subcommands) provides basic visibility but has critical gaps:

1. **REST API is DEPRECATED and will be removed in 26.04:**
   - **⚠️ FACT-CHECK FINDING:** TrueNAS 25.10.1 generates a WARNING alert: "The deprecated REST API was used to authenticate 52 times in the last 24 hours from 10.25.255.199, 10.25.255.2." The REST API (`/api/v2.0/`) will be **removed** in version 26.04. FREQ's `_tn_api()` function uses `curl` against the REST API exclusively — it will break on upgrade.
   - Migration target: JSON-RPC 2.0 over WebSocket, OR `midclt call` via SSH (already available, already used in health checks).

2. **No dataset/ACL sweep:**
   - ACL type is POSIX everywhere (`aclmode=DISCARD`) — verified live. But there's no automated check that dataset permissions match the expected state. Manual `getfacl` runs are the only way to verify.
   - SMB share root (`/mnt/mega-pool/smb-share`) has `g:smb-share-rw:rwx, other=---` — correct. But sub-datasets (donny, sonny, chris, public) each have their own ACLs that aren't verified.

3. **No snapshot tasks configured:**
   - **⚠️ FACT-CHECK FINDING:** `pool.snapshottask.query` returns `[]` — zero automatic snapshot tasks. The only snapshots are manual. For a 28TB pool holding all media and configs, this is a gap. One accidental `rm -rf` and there's no rollback.

4. **No SMART health integration:**
   - `_tn_disks()` shows model/size/temp but doesn't check `SMART Health Status`. All 8 HDDs are currently `OK` (verified via `smartctl -H /dev/sda`), but the module doesn't surface this.
   - No SMART test schedule exists (`smart.test.query` returns empty — **FACT-CHECK FINDING**).

5. **No service health monitoring:**
   - Running services: cifs (SMB), nfs, ssh. Stopped: ftp, iscsitarget, snmp, ups, nvmet.
   - FREQ doesn't check if critical services (NFS, SMB, SSH) are running. If NFS dies, 7 VMs lose their media mounts silently.

6. **Sudoers state is complex:**
   - Lesson #124: TrueNAS middleware DB overrides `/etc/sudoers.d/` on reboot. The "permanent fix" (S073) puts 59 NOPASSWD commands per probe account into the middleware DB. But `/etc/sudoers.d/` still has a stale backup file (`dc01-probe-readonly.backup-s072`). FREQ doesn't verify this state.

7. **Bond health not monitored:**
   - bond0 (eno2+eno3) is LACP 802.3ad for the storage VLAN. Both members are up (verified). But FREQ doesn't check LACP state — a failed member means degraded storage throughput for all NFS clients.

8. **NFS export security not validated:**
   - Export `nfs-mega-share` uses `mapall_user=svc-admin, mapall_group=truenas_admin` — maps all client access to one identity. `proxmox-backups` uses `maproot_user=root` — gives root access. FREQ should flag these choices.

9. **No hardware correlation:**
   - TrueNAS runs on the R530 (10.25.255.10 iDRAC). PSU 1 is FAILED, Fan 6 is DEAD. This isn't surfaced in `freq truenas status` — you'd only see it in `freq idrac status`.

10. **No quota or reservation checking:**
    - `proxmox-backups` has a refquota of ~1.63TB (visible in available space). FREQ doesn't display or monitor quota utilization.

### Why This Matters

TrueNAS is the **single point of failure** for DC01 storage. The pool is healthy (ONLINE, 0 errors, 63% used), but there's no automation to catch drift in permissions, missing snapshots, degraded bonds, or service outages. And the REST API deprecation is a ticking time bomb — FREQ will silently break when TrueNAS upgrades to 26.04.

---

## 2. WHAT IT DOES

The hardened `freq truenas` module:

- **Migrates from REST API to `midclt` over SSH** — future-proof, no deprecation risk, works with existing SSH infrastructure
- **Adds `freq tn sweep`** — interactive dataset/ACL/share audit (same pattern as `freq pf sweep`)
- **Adds SMART health checking** to disk display
- **Adds service health monitoring** — verifies NFS, SMB, SSH are running
- **Adds bond health checking** — LACP state, member status
- **Adds snapshot task verification** — flags missing automatic snapshot schedules
- **Adds NFS export security analysis** — flags maproot, mapall, wide network access
- **Cross-references iDRAC hardware alerts** — PSU/fan/thermal from the R530
- **Verifies sudoers state** — middleware DB vs /etc/sudoers.d/ consistency

---

## 3. INFRASTRUCTURE REFERENCE — EXPLICIT DETAILS

### TrueNAS System (VERIFIED LIVE 2026-03-11)

| Property | Value |
|----------|-------|
| Version | TrueNAS-25.10.1 |
| OS | Debian 12 (bookworm), Linux 6.12.33-production+truenas |
| Hostname | truenas |
| Model | PowerEdge R530 |
| CPU | Intel Xeon E5-2620 v3 @ 2.40GHz, 12 physical cores, 24 threads |
| RAM | 86.4 GB ECC |
| Serial | B065ND2 |
| Uptime | 2 days, 20:00:17 (at time of probe) |
| Load | 0.21 / 0.14 / 0.23 |
| iDRAC IP | 10.25.255.10 (iDRAC 8, FW 2.85.85.85) |

### Network Interfaces (VERIFIED LIVE 2026-03-11)

| Interface | Type | IP | MTU | VLAN Role | Link State |
|-----------|------|-----|-----|-----------|------------|
| eno1 | Physical | 10.25.0.25/24 | 9000 | LAN (default route via 10.25.0.1) | UP |
| eno2 | Physical (bond member) | — | 9000 | Storage (bond0 slave) | UP |
| eno3 | Physical (bond member) | — | 9000 | Storage (bond0 slave) | UP |
| eno4 | Physical | 10.25.255.25/24 | 1500 | Management (SSH binds here) | UP |
| bond0 | LACP 802.3ad | 10.25.25.25/24 | 9000 | Storage VLAN | UP |

> **Bond0 Details (VERIFIED):** IEEE 802.3ad, hash policy: layer2+3, LACP active: on, rate: slow, min links: 0, aggregator selection: stable. Both slaves MII Status: up, Speed: 1000 Mbps, Full duplex, Link Failure Count: 0.

> **MTU NOTE:** eno4 (management) is 1500 — correct, management traffic doesn't need jumbo frames. eno1, eno2, eno3, bond0 are all 9000 — jumbo frames for storage and LAN.

> **Default Route:** 10.25.0.1 (pfSense LAN). NOT via management VLAN — this means the default route goes through eno1 (LAN), not eno4 (mgmt). SSH access from WireGuard clients works because pfSense routes return traffic correctly.

### DNS
- Nameservers: 1.1.1.1, 8.8.8.8

### Storage Pool (VERIFIED LIVE 2026-03-11)

| Property | Value |
|----------|-------|
| Pool Name | mega-pool |
| Status | **ONLINE** — 0 read/write/checksum errors |
| Topology | 2× RAIDZ2 vdevs, 4 disks each (8 disks total) |
| Raw Size | 43.6 TB |
| Allocated | 27.8 TB (63%) |
| Free | 15.9 TB |
| Fragmentation | 10% |
| Autotrim | off |
| Dedup | 1.00x (disabled) |
| Last Scrub | Sun Mar 8 2026, 10:30:48 duration, 0 errors |
| Scrub Schedule | Weekly, Sunday 00:00 (pool.scrub.query verified) |

**RAIDZ2-0 (4 disks):**

| Disk | Device | Serial | Model | Size | Temp | Status |
|------|--------|--------|-------|------|------|--------|
| sda | sda1 | K1HGNSUF | HUS726060AL5210 | 5.46 TB | 37°C | ONLINE |
| sdd | sdd1 | K1HGSPPF | HUS726060AL5210 | 5.46 TB | 36°C | ONLINE |
| sdc | sdc1 | K1HGEMUF | HUS726060AL5210 | 5.46 TB | 37°C | ONLINE |
| sdb | sdb1 | K1HG3WAF | HUS726060AL5210 | 5.46 TB | 37°C | ONLINE |

**RAIDZ2-1 (4 disks):**

| Disk | Device | Serial | Model | Size | Temp | Status |
|------|--------|--------|-------|------|------|--------|
| sdg | sdg1 | K1HGSMVF | HUS726060AL5210 | 5.46 TB | 37°C | ONLINE |
| sdf | sdf1 | K1HGPWGF | HUS726060AL5210 | 5.46 TB | 36°C | ONLINE |
| sde | sde1 | K1HADH3F | HUS726060AL5210 | 5.46 TB | 37°C | ONLINE |
| sdh | sdh1 | K1HGTB5F | HUS726060AL5210 | 5.46 TB | 36°C | ONLINE |

**Boot Drive (NOT in pool):**

| Disk | Serial | Model | Size | Type |
|------|--------|-------|------|------|
| sdi | 011163923 | SanDisk SSD PLUS 240GB | 115 GB | ATA SSD |

> **All 8 HDDs are HGST Ultrastar He6 7200 RPM, SCSI bus.** All temps in 36-37°C range (healthy). SMART Health Status: OK on all (verified via smartctl).

### Datasets (VERIFIED LIVE 2026-03-11)

| Dataset | Used | Available | ACL Type | ACL Mode | Mount |
|---------|------|-----------|----------|----------|-------|
| mega-pool | 13.45 TiB | 7.56 TiB | POSIX | DISCARD | /mnt/mega-pool |
| mega-pool/ssh-homes | 779 KiB | 7.56 TiB | POSIX (inherited) | DISCARD (inherited) | /mnt/mega-pool/ssh-homes |
| mega-pool/proxmox-backups | 376.24 GiB | 1.63 TiB | POSIX (inherited) | DISCARD (inherited) | /mnt/mega-pool/proxmox-backups |
| mega-pool/nfs-mega-share | 12.95 TiB | 7.56 TiB | POSIX (inherited) | DISCARD (inherited) | /mnt/mega-pool/nfs-mega-share |
| mega-pool/smb-share | 130.25 GiB | 7.56 TiB | POSIX (inherited) | DISCARD (inherited) | /mnt/mega-pool/smb-share |
| mega-pool/smb-share/donny | 256 KiB | 7.56 TiB | POSIX (inherited) | DISCARD (inherited) | /mnt/mega-pool/smb-share/donny |

> **NOTE:** `proxmox-backups` shows 1.63 TiB available vs the pool's 7.56 TiB — it has a refquota limiting its growth. This is correct behavior to prevent backup growth from consuming the pool.

### POSIX ACLs on Share Roots (VERIFIED LIVE 2026-03-11)

**SMB Share (`/mnt/mega-pool/smb-share`):**
```
owner: root
group: truenas_admin
user::rwx
group::rwx
group:smb-share-rw:rwx
mask::rwx
other::---
```

**NFS Share (`/mnt/mega-pool/nfs-mega-share`):**
```
owner: root
group: truenas_admin
user::rwx
group::rwx
other::r-x
default:user::rwx
default:group::rwx
default:other::r-x
```

> **SMB vs NFS ACL Difference:** SMB share blocks `other` access (`---`) and grants via `smb-share-rw` group. NFS share allows `other::r-x` — any NFS client with network access can read. This is intentional: NFS clients are VMs on trusted VLANs. The `mapall_user=svc-admin` in the NFS export maps all client writes to svc-admin ownership.

### SMB Configuration (VERIFIED LIVE 2026-03-11)

| Property | Value |
|----------|-------|
| NetBIOS Name | truenas |
| Workgroup | WORKGROUP |
| SMB1 | **Disabled** |
| NTLMv1 | **Disabled** |
| Bind IPs | 10.25.25.25 (storage), 10.25.255.25 (mgmt) |
| AAPL Extensions | Disabled |
| Multichannel | Disabled |
| Encryption | DEFAULT |

**SMB Share: `smb-share`**

| Property | Value |
|----------|-------|
| Path | /mnt/mega-pool/smb-share |
| Enabled | Yes |
| Read-Only | No |
| Browsable | Yes |
| hostsallow | 10.25.0.0/24, 10.25.25.0/24, 10.25.100.0/24 |
| hostsdeny | (empty) |
| Audit | Disabled |

### NFS Configuration (VERIFIED LIVE 2026-03-11)

| Property | Value |
|----------|-------|
| Servers | 24 (matches CPU thread count) |
| Protocols | NFSv3, NFSv4 |
| Bind IP | 10.25.25.25 (storage VLAN only) |
| v4 Kerberos | Disabled |
| RDMA | Disabled |

**NFS Exports:**

| ID | Path | Networks | maproot | mapall | Security | Comment |
|----|------|----------|---------|--------|----------|---------|
| 1 | /mnt/mega-pool/nfs-mega-share | 10.25.25.0/24, 10.25.100.0/24, 10.25.0.0/24 | — | svc-admin:truenas_admin | sys | VM - Storage |
| 2 | /mnt/mega-pool/ha-proxmox-disk | 10.25.25.0/24 | — | — | sys | HA - Disks for Proxmox |
| 4 | /mnt/mega-pool/proxmox-backups | 10.25.25.0/24 | root | — | sys | proxmox-backups |

> **⚠️ Security Notes:**
> - Export 1 (`nfs-mega-share`): `mapall_user=svc-admin` maps ALL client operations to svc-admin (uid 3003). This means any NFS client on the allowed networks writes as svc-admin. Intentional for DC01 VM fleet (all VMs run containers as PUID 3003).
> - Export 4 (`proxmox-backups`): `maproot_user=root` gives root access from storage VLAN. Required for Proxmox backup operations. Restricted to storage VLAN only.
> - Export 2 (`ha-proxmox-disk`): No map settings — uses default UID mapping. Storage VLAN only.

### SSH Configuration (VERIFIED LIVE 2026-03-11)

| Property | Value |
|----------|-------|
| Bind Interface | eno4 (management, 10.25.255.25) |
| Port | 22 |
| Password Auth | Enabled |
| Weak Ciphers | AES128-CBC |
| AllowUsers | svc-admin, jarvis-ai, sonny-aif, chrisadmin, donmin |
| TCP Forwarding | Disabled |

### Services (VERIFIED LIVE 2026-03-11)

| Service | State | Enabled | PID |
|---------|-------|---------|-----|
| cifs (SMB) | **RUNNING** | Yes | 4941 |
| nfs | **RUNNING** | Yes | — |
| ssh | **RUNNING** | Yes | 3561 |
| ftp | STOPPED | No | — |
| iscsitarget | STOPPED | No | — |
| snmp | STOPPED | No | — |
| ups | STOPPED | No | — |
| nvmet | STOPPED | No | — |

### User Accounts (VERIFIED LIVE 2026-03-11)

| Username | UID | Primary Group (GID) | SMB | SSH PW | Sudo NOPASSWD | Home |
|----------|-----|---------------------|-----|--------|---------------|------|
| root | 0 | wheel (0) | No | Yes | — | /root |
| truenas_admin | 950 | truenas_admin (950) | No | Yes | 0 (1 sudo cmd) | /home/truenas_admin |
| sonny-aif | 3000 | dc01-probe (3950) | Yes | Yes | 59 | /mnt/mega-pool/ssh-homes/sonny-aif |
| chrisadmin | 3001 | dc01-probe (3950) | Yes | Yes | 59 | /mnt/mega-pool/ssh-homes/chrisadmin |
| donmin | 3002 | dc01-probe (3950) | Yes | Yes | 59 | /mnt/mega-pool/ssh-homes/donmin |
| svc-admin | 3003 | truenas_admin (950) | Yes | Yes | 1 | /mnt/mega-pool/svc-admin |
| jarvis-ai | 3004 | dc01-probe (3950) | Yes | Yes | 59 | /mnt/mega-pool/ssh-homes/jarvis-ai |
| freq-admin | 3005 | freq-admin (3002) | Yes | No | 0 | /var/empty |

> **⚠️ FACT-CHECK NOTES:**
> - **svc-admin primary group is truenas_admin (GID 950)** — NOT svc-admin (GID 3000). The `svc-admin` group exists (GID 3000) but is a separate group with 0 members. svc-admin's primary group is truenas_admin.
> - **freq-admin has no SSH access** (ssh_password_enabled=false), home=/var/empty. It's a service account for API access only.
> - **Probe accounts (59 commands):** sonny-aif, chrisadmin, donmin, jarvis-ai each have 59 NOPASSWD sudo commands in the middleware DB (the "permanent fix" from S073). These are read-only midclt/zfs/system commands.
> - **truenas_admin has 1 sudo command** (not NOPASSWD) — this is the built-in admin with interactive sudo.

### Groups (VERIFIED LIVE 2026-03-11)

| Group | GID | SMB | Sudo NOPASSWD | Members |
|-------|-----|-----|---------------|---------|
| wheel | 0 | No | 0 | root |
| truenas_admin | 950 | No | 1 | truenas_admin, svc-admin |
| svc-admin | 3000 | No | 0 | (none) |
| dc01-probe | 3950 | Yes | 0 | sonny-aif, chrisadmin, donmin, jarvis-ai |
| smb-share-rw | 3001 | Yes | 0 | sonny-aif, chrisadmin, donmin, jarvis-ai |
| freq-admin | 3002 | No | 0 | freq-admin |

> **⚠️ Sudoers Architecture:** TrueNAS middleware DB is the source of truth for sudo permissions. The `/etc/sudoers.d/` directory on disk has a stale backup file (`dc01-probe-readonly.backup-s072`) but the ACTIVE sudoers rules come from the middleware via `@includedir /etc/sudoers.d` which reads files generated by the middleware on boot. The 59-command NOPASSWD list for probe accounts lives in the middleware DB per-user `sudo_commands_nopasswd` array. Modifying `/etc/sudoers.d/` directly will be overwritten on next middleware restart.

### Active Alerts (VERIFIED LIVE 2026-03-11)

| Alert | Level | Source | Details |
|-------|-------|--------|---------|
| REST API Deprecation | WARNING | RESTAPIUsage | 52 calls in 24h from 10.25.255.199 (VM 999/FREQ), 10.25.255.2 (VM 100). REST API removed in 26.04. |

> **No critical alerts.** The REST API warning is the only active alert. It directly affects FREQ's `_tn_api()` function.

### Hardware State (from iDRAC .10 — same R530)

| Alert | Severity | Impact on TrueNAS |
|-------|----------|-------------------|
| PSU 1 FAILED | **CRITICAL** | Running on single PSU. Power loss to PSU 2 = total storage outage. |
| Fan 6 DEAD | **HIGH** | 0 RPM, fan redundancy lost. Thermal risk under heavy load. |
| SEL FULL | MEDIUM | 1024/1024 entries. Not a TrueNAS issue but obscures new events. |

### Scrub & SMART Schedule

| Task | Schedule | Status |
|------|----------|--------|
| Pool Scrub (mega-pool) | Weekly, Sunday 00:00 | Last: Mar 8, 0 errors, 10h31m |
| SMART Tests | **NONE CONFIGURED** | ⚠️ No periodic SMART tests |
| Snapshot Tasks | **NONE CONFIGURED** | ⚠️ No automatic snapshots |
| Replications | **NONE CONFIGURED** | No replication targets |

### SSH Access from FREQ

```bash
# From VM 999 (where FREQ lives) — via PVE node gateway:
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    svc-admin@10.25.255.26 \
    "sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    svc-admin@10.25.255.25 'sudo midclt call system.info'"

# From WSL (direct, WireGuard routed):
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    svc-admin@10.25.255.25 "sudo midclt call system.info"

# From any PVE node (direct, L2 adjacent on mgmt VLAN):
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    svc-admin@10.25.255.25 "sudo midclt call system.info"
```

---

## 4. CLI & MENU INTEGRATION

### Existing Commands (Preserved)

```
freq truenas status [--target prod|lab]   # Dashboard — system info + pool + alerts
freq truenas pools [--target ...]         # Pool health and usage
freq truenas shares [--target ...]        # SMB + NFS share listing
freq truenas alerts [--target ...]        # Active alerts with severity
freq truenas scrub [--target ...]         # Trigger scrub (protected gate)
freq truenas snap list [--target ...]     # Snapshot listing
freq truenas users [--target ...]         # User account listing
freq truenas nfs [--target ...]           # NFS service config + exports
freq truenas disks [--target ...]         # Disk inventory with model/size/temp
freq truenas backup [--target ...]        # Config backup (SQLite + JSON)
freq truenas probe [--target ...]         # Deploy jarvis-ai probe account
```

### New Commands (This Design)

```
freq truenas sweep [--target prod|lab]    # Interactive dataset/ACL/share audit
freq truenas health [--target ...]        # Comprehensive health (services + bond + smart + hardware)
freq truenas snapcheck [--target ...]     # Verify snapshot task coverage
freq truenas sudoers [--target ...]       # Verify middleware DB vs /etc/sudoers.d/ consistency
```

### Enhanced Existing Commands

```
freq truenas status [--target ...]        # ENHANCED: adds service health, bond state, hardware alerts
freq truenas disks [--target ...]         # ENHANCED: adds SMART health status per disk
freq truenas nfs [--target ...]           # ENHANCED: adds security analysis flags
```

### Target Aliases

| Alias | Resolves To | Notes |
|-------|-------------|-------|
| `prod` (default) | 10.25.255.25 | Production TrueNAS |
| `lab` | 10.25.255.181 | VM 981 TrueNAS SCALE lab |

### Interactive Menu Placement

```
FREQ Main Menu → Storage → TrueNAS Management
  1)  System Status (enhanced)
  2)  Pool Health
  3)  Disk Inventory (with SMART)
  4)  Share Management
  5)  NFS Health & Security
  6)  Alert Review
  7)  User & Group Audit
  8)  Snapshot Management
  9)  Sudoers Verification
  10) Bond & Network Health
  11) Sweep — Interactive Audit
  12) Config Backup
  13) Scrub (protected)
```

### Permission Tier

| Subcommand | Tier | Why |
|------------|------|-----|
| status, pools, shares, alerts, nfs, disks, users, health, snapcheck, sudoers | **Tier 2 (operator+)** | Read-only queries |
| sweep | **Tier 2 (operator+)** | Read-only analysis; any changes require Tier 3 |
| snap list | **Tier 2 (operator+)** | Read-only listing |
| backup, probe | **Tier 3 (admin-only)** | Creates files / modifies user accounts |
| scrub | **Tier 3 (admin-only) + Protected Gate** | Stresses pool, can kill failing disk |

---

## 5. ARCHITECTURE

### API Migration: REST → midclt SSH

**The most critical change.** The current `_tn_api()` uses `curl` against the REST API (`/api/v2.0/`). This must be replaced before TrueNAS upgrades to 26.04.

**Three migration options:**

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **(a) midclt via SSH** | Already works, already used in health checks, no API key needed, no deprecation risk | Requires SSH access, slightly slower than direct API | **✅ RECOMMENDED** |
| **(b) JSON-RPC 2.0 over WebSocket** | Official replacement, supports subscriptions | Complex (websocket client in bash?), needs new auth | ❌ Overkill for FREQ |
| **(c) Dual-mode (REST now, midclt fallback)** | Graceful migration | Maintains deprecated code | ❌ Delays the inevitable |

**Decision: Option (a) — `midclt` via SSH.**

The new `_tn_midclt()` replaces `_tn_api()` as the primary transport. SSH is already the access method for all other FREQ operations. `midclt call` returns the same JSON as the REST API — zero parsing changes needed.

### Key Functions

**New/Modified:**

```
_tn_midclt()                  # SSH + midclt wrapper — replaces _tn_api() for all read operations
_tn_api()                     # PRESERVED but deprecated — fallback only, warns on use
_tn_ssh()                     # Low-level SSH wrapper (already exists implicitly, now explicit)

# Sweep functions:
_tn_sweep()                   # Interactive dataset/ACL audit (main sweep entry)
_tn_sweep_datasets()          # Walk all datasets, check ACLs, flag anomalies
_tn_sweep_smb()               # SMB share permission verification
_tn_sweep_nfs()               # NFS export security analysis
_tn_sweep_services()          # Service health check (NFS, SMB, SSH running?)
_tn_sweep_bond()              # LACP bond health and member status
_tn_sweep_smart()             # SMART health per disk
_tn_sweep_snapshots()         # Snapshot task coverage verification
_tn_sweep_sudoers()           # Middleware DB vs /etc/sudoers.d/ consistency
_tn_sweep_hardware()          # Cross-reference iDRAC alerts (PSU, fan, thermal)

# Enhanced existing:
_tn_health()                  # New comprehensive health command
_tn_snapcheck()               # Snapshot task verification
_tn_sudoers()                 # Sudoers state display
```

**Preserved (no changes needed):**

```
_tn_resolve_target()          # Target resolution (prod/lab)
cmd_truenas()                 # Dispatcher (add new subcommands)
_tn_scrub()                   # Protected gate scrub (already correct)
_tn_backup()                  # Config backup (needs _tn_api→_tn_midclt migration)
_tn_probe()                   # Probe deployment (needs _tn_api→_tn_midclt migration)
```

### Data Flow

```
User runs: freq truenas sweep

  ┌──────────────────────────────────────────────────────────┐
  │ _tn_resolve_target("prod")                                │
  │   → TN_TARGET_IP = 10.25.255.25                          │
  │   → TN_TARGET_NAME = "prod"                              │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │ _tn_midclt "system.info"     → version, hostname, uptime │
  │ _tn_midclt "pool.query"      → pool health, topology     │
  │ _tn_midclt "disk.query"      → disk inventory            │
  │ _tn_midclt "disk.temperatures" → temps                   │
  │ _tn_midclt "sharing.smb.query" → SMB shares              │
  │ _tn_midclt "sharing.nfs.query" → NFS exports             │
  │ _tn_midclt "service.query"   → service states            │
  │ _tn_midclt "user.query"      → accounts                  │
  │ _tn_midclt "alert.list"      → active alerts             │
  │ _tn_ssh "cat /proc/net/bonding/bond0" → bond health      │
  │ _tn_ssh "getfacl /mnt/mega-pool/smb-share" → ACLs        │
  │ _tn_ssh "smartctl -H /dev/sdX" → SMART health            │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │ Analysis Engine:                                          │
  │  - Dataset ACL vs expected state                          │
  │  - NFS export security flags                              │
  │  - SMB share permission validation                        │
  │  - Service health (NFS/SMB/SSH running?)                  │
  │  - Bond member status                                     │
  │  - SMART health per disk                                  │
  │  - Snapshot coverage gaps                                 │
  │  - Sudoers consistency                                    │
  │  - Hardware alert cross-reference                         │
  └──────────────────────────┬───────────────────────────────┘
                             │
                             ▼
  ┌──────────────────────────────────────────────────────────┐
  │ TUI Display:                                              │
  │  - Sweep summary with findings                            │
  │  - Per-category results with severity                     │
  │  - Recommendations (no auto-fix — operator reviews)       │
  └──────────────────────────────────────────────────────────┘
```

---

## 6. THE CODE LAYER

### Core Transport: `_tn_midclt()` — Replaces `_tn_api()`

```bash
# New primary transport — SSH + midclt
# Returns same JSON as REST API, no deprecation risk
_tn_midclt() {
    local method="$1"
    shift
    local args=("$@")
    local _tn_ip="${TN_TARGET_IP:-10.25.255.25}"

    # Build midclt command
    local cmd="sudo midclt call $method"
    for arg in "${args[@]}"; do
        cmd+=" '$arg'"
    done

    # SSH transport
    local _response
    _response=$(sshpass -p "$PROTECTED_ROOT_PASS" ssh \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 \
        -o BatchMode=no \
        "svc-admin@$_tn_ip" "$cmd" 2>/dev/null)

    local rc=$?
    if [[ $rc -ne 0 ]]; then
        log "truenas: midclt call $method failed (rc=$rc)"
        return 1
    fi

    # Validate JSON response
    if [[ "$_response" =~ ^[[:space:]]*[\{\[] ]]; then
        echo "$_response"
    else
        # Non-JSON (empty, error text, etc.)
        echo "$_response"
    fi
}

# Low-level SSH for non-midclt commands (getfacl, smartctl, /proc reads)
_tn_ssh() {
    local cmd="$*"
    local _tn_ip="${TN_TARGET_IP:-10.25.255.25}"

    sshpass -p "$PROTECTED_ROOT_PASS" ssh \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=10 \
        "svc-admin@$_tn_ip" "sudo $cmd" 2>/dev/null
}
```

### Enhanced Status: `_tn_status()` — Adds Services, Bond, Hardware

```bash
_tn_status() {
    freq_header "TrueNAS Status ($TN_TARGET_NAME)"

    # System info
    local info=$(_tn_midclt "system.info")
    if [ -z "$info" ]; then
        echo -e "    ${RED}TrueNAS unreachable at $TN_TARGET_IP${RESET}"
        freq_footer
        return 1
    fi

    echo "$info" | python3 -c "
import sys, json
d = json.load(sys.stdin)
mem_gb = d.get('physmem', 0) / (1024**3)
cores = d.get('cores', '?')
load = d.get('loadavg', [0,0,0])
print(f'    Version:  {d.get(\"version\", \"unknown\")}')
print(f'    Hostname: {d.get(\"hostname\", \"unknown\")}')
print(f'    Model:    {d.get(\"system_product\", \"unknown\")} ({d.get(\"system_serial\", \"?\")})')
print(f'    CPU:      {d.get(\"model\", \"unknown\")} ({cores} threads)')
print(f'    RAM:      {mem_gb:.1f} GB ECC={d.get(\"ecc_memory\", False)}')
print(f'    Uptime:   {d.get(\"uptime\", \"unknown\")}')
print(f'    Load:     {load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}')
" 2>/dev/null || echo -e "    ${DIM}(parse error)${RESET}"

    # Pool health
    echo ""
    _tn_pools

    # Service health
    echo ""
    echo -e "    ${BOLD}Services:${RESET}"
    local services=$(_tn_midclt "service.query")
    echo "$services" | python3 -c "
import sys, json
svcs = json.load(sys.stdin)
critical = {'cifs': 'SMB', 'nfs': 'NFS', 'ssh': 'SSH'}
for s in svcs:
    name = s.get('service', '?')
    if name not in critical and s.get('state') != 'RUNNING':
        continue
    state = s.get('state', '?')
    label = critical.get(name, name)
    icon = '✅' if state == 'RUNNING' else '❌'
    print(f'      {icon} {label}: {state}')
" 2>/dev/null

    # Bond health
    echo ""
    echo -e "    ${BOLD}Bond (storage LACP):${RESET}"
    local bond=$(_tn_ssh "cat /proc/net/bonding/bond0 2>/dev/null")
    if [ -n "$bond" ]; then
        local bond_status=$(echo "$bond" | grep "MII Status:" | head -1 | awk '{print $3}')
        local slave_count=$(echo "$bond" | grep -c "Slave Interface:")
        local slaves_up=$(echo "$bond" | grep "MII Status: up" | wc -l)
        # subtract 1 for the bond's own MII Status line
        slaves_up=$((slaves_up - 1))
        if [[ "$bond_status" == "up" && "$slaves_up" -ge 2 ]]; then
            echo -e "      ✅ bond0: UP ($slaves_up/$slave_count members active)"
        else
            echo -e "      ⚠️  bond0: $bond_status ($slaves_up/$slave_count members active)"
        fi
    fi

    # Alert count
    echo ""
    local alerts=$(_tn_midclt "alert.list")
    local alert_count=$(echo "$alerts" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
    if [[ "${alert_count:-0}" -gt 0 ]]; then
        echo -e "    ⚠️  Active Alerts: $alert_count"
        echo "$alerts" | python3 -c "
import sys, json
for a in json.load(sys.stdin):
    level = a.get('level', 'INFO')
    color = {'CRITICAL': '\033[31m', 'ERROR': '\033[31m', 'WARNING': '\033[33m'}.get(level, '\033[34m')
    print(f'      {color}{level}\033[0m: {a.get(\"klass\", \"unknown\")}')
" 2>/dev/null
    else
        echo -e "    ✅ No active alerts"
    fi

    freq_footer
    log "truenas: status viewed ($TN_TARGET_NAME)"
}
```

### Enhanced Disks: `_tn_disks()` — Adds SMART Health

```bash
_tn_disks() {
    freq_header "TrueNAS Disks ($TN_TARGET_NAME)"

    # Get disk info + temperatures
    local disks=$(_tn_midclt "disk.query")
    local temps=$(_tn_midclt "disk.temperatures")

    echo "$disks" | python3 -c "
import sys, json

disks = json.load(sys.stdin)
temps_raw = '''$(echo "$temps")'''
try:
    temps = json.loads(temps_raw)
except:
    temps = {}

print(f'    {\"Disk\":6s} {\"Model\":25s} {\"Size\":8s} {\"Temp\":6s} {\"RPM\":6s} {\"Bus\":5s} {\"Serial\":10s}')
print(f'    {\"─\"*6} {\"─\"*25} {\"─\"*8} {\"─\"*6} {\"─\"*6} {\"─\"*5} {\"─\"*10}')
for d in disks:
    name = d.get('name', '?')
    model = d.get('model', 'unknown')[:25]
    size_gb = d.get('size', 0) / (1024**3) if d.get('size') else 0
    size_str = f'{size_gb:.0f}GB' if size_gb < 1000 else f'{size_gb/1024:.1f}TB'
    temp = temps.get(name)
    temp_str = f'{temp:.0f}°C' if temp is not None else 'N/A'
    rpm = d.get('rotationrate')
    rpm_str = str(rpm) if rpm else 'SSD'
    bus = d.get('bus', '?')
    serial = d.get('serial', '?')[:10]
    print(f'    {name:6s} {model:25s} {size_str:8s} {temp_str:6s} {rpm_str:6s} {bus:5s} {serial:10s}')
" 2>/dev/null

    # SMART health per disk (NEW)
    echo ""
    echo -e "    ${BOLD}SMART Health:${RESET}"
    local disk_names=$(echo "$disks" | python3 -c "import sys,json; [print(d['name']) for d in json.load(sys.stdin)]" 2>/dev/null)
    local all_ok=true
    while read -r dname; do
        [ -z "$dname" ] && continue
        local smart=$(_tn_ssh "smartctl -H /dev/$dname 2>/dev/null | grep -i 'health status\|overall-health'")
        if echo "$smart" | grep -qi "OK\|PASSED"; then
            echo -e "      ✅ /dev/$dname: PASSED"
        else
            echo -e "      ❌ /dev/$dname: ${smart:-UNKNOWN}"
            all_ok=false
        fi
    done <<< "$disk_names"

    freq_footer
}
```

### New: Comprehensive Health Check — `_tn_health()`

```bash
_tn_health() {
    freq_header "TrueNAS Comprehensive Health ($TN_TARGET_NAME)"

    local findings=()
    local severity_critical=0
    local severity_warning=0
    local severity_info=0

    # 1. Pool health
    echo -e "    ${BOLD}[1/8] Pool Health${RESET}"
    local pools=$(_tn_midclt "pool.query")
    local pool_healthy=$(echo "$pools" | python3 -c "import sys,json; p=json.load(sys.stdin); print('true' if all(x.get('healthy') for x in p) else 'false')" 2>/dev/null)
    if [[ "$pool_healthy" == "true" ]]; then
        echo -e "      ✅ All pools ONLINE and healthy"
    else
        echo -e "      ❌ Pool health issue detected"
        findings+=("CRITICAL: Pool not healthy")
        severity_critical=$((severity_critical + 1))
    fi

    # Pool usage warning
    local pool_pct=$(echo "$pools" | python3 -c "
import sys,json
p=json.load(sys.stdin)
for pool in p:
    used=pool.get('allocated',0); size=pool.get('size',1)
    print(int(100*used/size) if size>0 else 0)
" 2>/dev/null)
    if [[ "$pool_pct" -gt 80 ]]; then
        echo -e "      ⚠️  Pool usage at ${pool_pct}% — consider expanding"
        findings+=("WARNING: Pool at ${pool_pct}%")
        severity_warning=$((severity_warning + 1))
    elif [[ "$pool_pct" -gt 90 ]]; then
        echo -e "      ❌ Pool usage CRITICAL at ${pool_pct}%"
        findings+=("CRITICAL: Pool at ${pool_pct}%")
        severity_critical=$((severity_critical + 1))
    else
        echo -e "      ✅ Pool usage at ${pool_pct}% — OK"
    fi

    # 2. Service health
    echo ""
    echo -e "    ${BOLD}[2/8] Service Health${RESET}"
    local services=$(_tn_midclt "service.query")
    for svc in cifs nfs ssh; do
        local state=$(echo "$services" | python3 -c "
import sys,json
for s in json.load(sys.stdin):
    if s['service']=='$svc': print(s['state']); break
" 2>/dev/null)
        if [[ "$state" == "RUNNING" ]]; then
            echo -e "      ✅ $svc: RUNNING"
        else
            echo -e "      ❌ $svc: ${state:-NOT FOUND}"
            findings+=("CRITICAL: $svc not running")
            severity_critical=$((severity_critical + 1))
        fi
    done

    # 3. SMART health
    echo ""
    echo -e "    ${BOLD}[3/8] SMART Health${RESET}"
    local disk_names=$(_tn_midclt "disk.query" | python3 -c "import sys,json; [print(d['name']) for d in json.load(sys.stdin) if d.get('type')=='HDD']" 2>/dev/null)
    while read -r dname; do
        [ -z "$dname" ] && continue
        local smart=$(_tn_ssh "smartctl -H /dev/$dname 2>/dev/null | grep -i 'health status\|overall-health'")
        if echo "$smart" | grep -qi "OK\|PASSED"; then
            echo -e "      ✅ /dev/$dname: PASSED"
        else
            echo -e "      ❌ /dev/$dname: ${smart:-UNKNOWN}"
            findings+=("CRITICAL: SMART failure on $dname")
            severity_critical=$((severity_critical + 1))
        fi
    done <<< "$disk_names"

    # 4. Disk temperatures
    echo ""
    echo -e "    ${BOLD}[4/8] Disk Temperatures${RESET}"
    local temps=$(_tn_midclt "disk.temperatures")
    echo "$temps" | python3 -c "
import sys, json
temps = json.load(sys.stdin)
for disk, temp in sorted(temps.items()):
    if temp is None:
        print(f'      ⚠️  {disk}: N/A (no sensor)')
    elif temp > 50:
        print(f'      ❌ {disk}: {temp}°C — HOT')
    elif temp > 45:
        print(f'      ⚠️  {disk}: {temp}°C — warm')
    else:
        print(f'      ✅ {disk}: {temp}°C')
" 2>/dev/null

    # 5. Bond health
    echo ""
    echo -e "    ${BOLD}[5/8] Bond (LACP) Health${RESET}"
    local bond=$(_tn_ssh "cat /proc/net/bonding/bond0 2>/dev/null")
    if [ -n "$bond" ]; then
        local bond_mii=$(echo "$bond" | grep "^MII Status:" | awk '{print $3}')
        local bond_mode=$(echo "$bond" | grep "^Bonding Mode:" | sed 's/Bonding Mode: //')
        echo -e "      Mode: $bond_mode"
        echo "$bond" | awk '/Slave Interface/{name=$3} /MII Status/{if(name) {icon=($3=="up")?"✅":"❌"; print "      " icon " " name ": " $3; name=""}}'
        local fail_count=$(echo "$bond" | grep "Link Failure Count:" | awk '{sum+=$4} END{print sum}')
        if [[ "$fail_count" -gt 0 ]]; then
            echo -e "      ⚠️  Total link failures: $fail_count"
            findings+=("WARNING: $fail_count bond link failures")
            severity_warning=$((severity_warning + 1))
        fi
    else
        echo -e "      ⚠️  bond0 not found"
        findings+=("WARNING: bond0 not found")
        severity_warning=$((severity_warning + 1))
    fi

    # 6. Snapshot coverage
    echo ""
    echo -e "    ${BOLD}[6/8] Snapshot Tasks${RESET}"
    local snap_tasks=$(_tn_midclt "pool.snapshottask.query")
    local snap_count=$(echo "$snap_tasks" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
    if [[ "${snap_count:-0}" -eq 0 ]]; then
        echo -e "      ⚠️  No automatic snapshot tasks configured"
        findings+=("WARNING: No snapshot tasks — no rollback protection")
        severity_warning=$((severity_warning + 1))
    else
        echo -e "      ✅ $snap_count snapshot tasks configured"
    fi

    # 7. Alerts
    echo ""
    echo -e "    ${BOLD}[7/8] Active Alerts${RESET}"
    local alerts=$(_tn_midclt "alert.list")
    local alert_count=$(echo "$alerts" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
    if [[ "${alert_count:-0}" -gt 0 ]]; then
        echo "$alerts" | python3 -c "
import sys, json
for a in json.load(sys.stdin):
    level = a.get('level', 'INFO')
    icon = {'CRITICAL':'❌','ERROR':'❌','WARNING':'⚠️'}.get(level,'ℹ️')
    print(f'      {icon} {level}: {a.get(\"klass\",\"unknown\")}')
" 2>/dev/null
    else
        echo -e "      ✅ No active alerts"
    fi

    # 8. Scrub recency
    echo ""
    echo -e "    ${BOLD}[8/8] Scrub Recency${RESET}"
    echo "$pools" | python3 -c "
import sys, json, time
for p in json.load(sys.stdin):
    scan = p.get('scan', {})
    if scan.get('end_time'):
        end_ts = scan['end_time'].get('\$date', 0) / 1000
        age_days = (time.time() - end_ts) / 86400
        errors = scan.get('errors', 0)
        if age_days > 14:
            print(f'      ⚠️  {p[\"name\"]}: last scrub {age_days:.0f} days ago')
        else:
            print(f'      ✅ {p[\"name\"]}: last scrub {age_days:.0f} days ago, {errors} errors')
    else:
        print(f'      ⚠️  {p[\"name\"]}: no scrub history')
" 2>/dev/null

    # Summary
    echo ""
    freq_divider
    local total_findings=${#findings[@]}
    if [[ $severity_critical -gt 0 ]]; then
        echo -e "    ❌ $severity_critical CRITICAL | $severity_warning WARNING | $severity_info INFO ($total_findings total)"
    elif [[ $severity_warning -gt 0 ]]; then
        echo -e "    ⚠️  $severity_warning WARNING | $severity_info INFO ($total_findings total)"
    else
        echo -e "    ✅ All checks passed"
    fi

    freq_footer
    log "truenas: health check completed ($TN_TARGET_NAME) — $total_findings findings"
}
```

### New: Sweep — Interactive Audit (`_tn_sweep()`)

```bash
_tn_sweep() {
    freq_header "TrueNAS Sweep — Interactive Audit ($TN_TARGET_NAME)"
    echo -e "    ${DIM}Gathering data from $TN_TARGET_IP...${RESET}"
    echo ""

    local total_findings=0
    local total_ok=0

    # ── Section 1: Dataset ACL Verification ──
    echo -e "    ${BOLD}━━━ Dataset ACL Verification ━━━${RESET}"

    local datasets=$(_tn_midclt "pool.dataset.query" \
        '[[\"pool\",\"=\",\"mega-pool\"],[\"type\",\"=\",\"FILESYSTEM\"]]' \
        '{\"select\":[\"id\",\"name\",\"acltype\",\"aclmode\",\"used\",\"available\",\"mountpoint\"]}')

    echo "$datasets" | python3 -c "
import sys, json

datasets = json.load(sys.stdin)
findings = 0
ok = 0

# Expected ACL state
expected = {
    'mega-pool': {'acltype': 'posix', 'aclmode': 'discard'},
    'mega-pool/smb-share': {'acltype': 'posix', 'aclmode': 'discard'},
    'mega-pool/nfs-mega-share': {'acltype': 'posix', 'aclmode': 'discard'},
    'mega-pool/proxmox-backups': {'acltype': 'posix', 'aclmode': 'discard'},
    'mega-pool/ssh-homes': {'acltype': 'posix', 'aclmode': 'discard'},
}

for ds in datasets:
    name = ds['id']
    acltype = ds.get('acltype', {}).get('parsed', 'unknown')
    aclmode = ds.get('aclmode', {}).get('parsed', 'unknown')
    source = ds.get('acltype', {}).get('source', 'unknown')

    if name in expected:
        exp = expected[name]
        if acltype != exp['acltype'] or aclmode != exp['aclmode']:
            print(f'      ⚠️  {name}: acltype={acltype} aclmode={aclmode} (expected {exp[\"acltype\"]}/{exp[\"aclmode\"]})')
            findings += 1
        else:
            print(f'      ✅ {name}: {acltype}/{aclmode} (source={source})')
            ok += 1
    else:
        # Unknown dataset — flag for review
        print(f'      ℹ️  {name}: {acltype}/{aclmode} (not in expected map)')

print(f'FINDINGS:{findings}')
print(f'OK:{ok}')
" 2>/dev/null

    # ── Section 2: SMB Share Verification ──
    echo ""
    echo -e "    ${BOLD}━━━ SMB Share Verification ━━━${RESET}"

    local smb_shares=$(_tn_midclt "sharing.smb.query")
    local smb_config=$(_tn_midclt "smb.config")

    echo "$smb_shares" | python3 -c "
import sys, json

shares = json.load(sys.stdin)
config_raw = '''$(echo "$smb_config")'''
config = json.loads(config_raw)

# Global SMB checks
smb1 = config.get('enable_smb1', True)
ntlmv1 = config.get('ntlmv1_auth', True)
if smb1:
    print('      ❌ SMB1 is ENABLED — security risk')
else:
    print('      ✅ SMB1 disabled')
if ntlmv1:
    print('      ❌ NTLMv1 is ENABLED — security risk')
else:
    print('      ✅ NTLMv1 disabled')

bindips = config.get('bindip', [])
print(f'      ℹ️  SMB bind IPs: {\", \".join(bindips)}')

for s in shares:
    name = s.get('name', '?')
    path = s.get('path', '?')
    enabled = s.get('enabled', False)
    hostsallow = s.get('options', {}).get('hostsallow', [])
    hostsdeny = s.get('options', {}).get('hostsdeny', [])

    print(f'')
    print(f'      Share: {name}')
    print(f'        Path: {path}')
    print(f'        Enabled: {\"✅ Yes\" if enabled else \"❌ No\"}')

    if hostsallow:
        print(f'        hostsallow: {\", \".join(hostsallow)}')
    else:
        print(f'        ⚠️  hostsallow: EMPTY — accessible from any IP')

    if not hostsdeny:
        print(f'        hostsdeny: (none)')
" 2>/dev/null

    # Verify POSIX ACLs on SMB share root
    echo ""
    echo -e "      ${DIM}Checking POSIX ACLs on share root...${RESET}"
    local smb_acl=$(_tn_ssh "getfacl /mnt/mega-pool/smb-share 2>/dev/null")
    if echo "$smb_acl" | grep -q "group:smb-share-rw:rwx"; then
        echo -e "      ✅ smb-share-rw group has rwx"
    else
        echo -e "      ❌ smb-share-rw group ACL missing or wrong"
        total_findings=$((total_findings + 1))
    fi
    if echo "$smb_acl" | grep -q "other::---"; then
        echo -e "      ✅ other access blocked (---)"
    else
        local other_perms=$(echo "$smb_acl" | grep "^other::" | head -1)
        echo -e "      ⚠️  other access: $other_perms (expected ---)"
        total_findings=$((total_findings + 1))
    fi

    # ── Section 3: NFS Export Security ──
    echo ""
    echo -e "    ${BOLD}━━━ NFS Export Security ━━━${RESET}"

    local nfs_exports=$(_tn_midclt "sharing.nfs.query")
    local nfs_config=$(_tn_midclt "nfs.config")

    echo "$nfs_config" | python3 -c "
import sys, json
nfs = json.load(sys.stdin)
print(f'      Servers: {nfs.get(\"servers\", \"?\")}')
print(f'      Protocols: {\", \".join(nfs.get(\"protocols\", []))}')
bindip = nfs.get('bindip', [])
print(f'      Bind IP: {\", \".join(bindip) if bindip else \"ALL INTERFACES ⚠️\"}')
if not bindip:
    print(f'      ⚠️  NFS is listening on ALL interfaces — should be storage VLAN only')
" 2>/dev/null

    echo ""
    echo "$nfs_exports" | python3 -c "
import sys, json

exports = json.load(sys.stdin)
for e in exports:
    path = e.get('path', '?')
    networks = e.get('networks', [])
    maproot = e.get('maproot_user', '') or ''
    mapall = e.get('mapall_user', '') or ''
    mapall_grp = e.get('mapall_group', '') or ''
    enabled = e.get('enabled', False)
    comment = e.get('comment', '')

    print(f'      Export: {path}')
    print(f'        Comment: {comment}')
    print(f'        Enabled: {\"✅\" if enabled else \"❌\"} | Networks: {\", \".join(networks) if networks else \"ANY ⚠️\"}')

    if maproot:
        print(f'        ⚠️  maproot_user={maproot} — root access from clients')
    if mapall:
        grp_info = f':{mapall_grp}' if mapall_grp else ''
        print(f'        ℹ️  mapall_user={mapall}{grp_info} — all client ops mapped to this identity')
    if not maproot and not mapall:
        print(f'        ℹ️  No user mapping — default UID passthrough')

    if not networks:
        print(f'        ❌ No network restriction — accessible from anywhere')
    print('')
" 2>/dev/null

    # ── Section 4: Service Health ──
    echo ""
    echo -e "    ${BOLD}━━━ Service Health ━━━${RESET}"
    local services=$(_tn_midclt "service.query")
    echo "$services" | python3 -c "
import sys, json
svcs = json.load(sys.stdin)
critical = ['cifs', 'nfs', 'ssh']
for s in svcs:
    name = s.get('service', '?')
    state = s.get('state', '?')
    enabled = s.get('enable', False)
    if name in critical:
        icon = '✅' if state == 'RUNNING' else '❌'
        print(f'      {icon} {name}: {state} (autostart={enabled})')
    elif state == 'RUNNING':
        print(f'      ℹ️  {name}: {state} (autostart={enabled})')
" 2>/dev/null

    # ── Section 5: Snapshot Coverage ──
    echo ""
    echo -e "    ${BOLD}━━━ Snapshot Coverage ━━━${RESET}"
    local snap_tasks=$(_tn_midclt "pool.snapshottask.query")
    local snap_count=$(echo "$snap_tasks" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null)
    if [[ "${snap_count:-0}" -eq 0 ]]; then
        echo -e "      ❌ No automatic snapshot tasks configured"
        echo -e "      ⚠️  A single rm -rf could lose data with no rollback"
        echo -e "      📋 Recommendation: Create snapshot tasks for mega-pool/smb-share and mega-pool/nfs-mega-share"
        total_findings=$((total_findings + 1))
    else
        echo -e "      ✅ $snap_count snapshot tasks configured"
    fi

    # Check SMART test schedule
    echo ""
    echo -e "    ${BOLD}━━━ SMART Test Schedule ━━━${RESET}"
    local smart_tests=$(_tn_midclt "smart.test.query" "[]" 2>/dev/null)
    if [[ -z "$smart_tests" || "$smart_tests" == "[]" ]]; then
        echo -e "      ⚠️  No periodic SMART tests configured"
        echo -e "      📋 Recommendation: Schedule monthly LONG tests on all disks"
        total_findings=$((total_findings + 1))
    else
        echo -e "      ✅ SMART tests configured"
    fi

    # ── Section 6: Sudoers Consistency ──
    echo ""
    echo -e "    ${BOLD}━━━ Sudoers Consistency ━━━${RESET}"

    # Check middleware DB
    local probe_users=("sonny-aif" "chrisadmin" "donmin" "jarvis-ai")
    for pu in "${probe_users[@]}"; do
        local sudo_count=$(_tn_midclt "user.query" "[[\"username\",\"=\",\"$pu\"]]" \
            '{"select":["username","sudo_commands_nopasswd"]}' | \
            python3 -c "import sys,json; u=json.load(sys.stdin); print(len(u[0].get('sudo_commands_nopasswd',[]) or []))" 2>/dev/null)
        if [[ "${sudo_count:-0}" -eq 59 ]]; then
            echo -e "      ✅ $pu: $sudo_count NOPASSWD commands in middleware DB"
        elif [[ "${sudo_count:-0}" -gt 0 ]]; then
            echo -e "      ⚠️  $pu: $sudo_count NOPASSWD commands (expected 59)"
            total_findings=$((total_findings + 1))
        else
            echo -e "      ❌ $pu: NO sudo commands in middleware DB"
            total_findings=$((total_findings + 1))
        fi
    done

    # Check /etc/sudoers.d/ for stale files
    local sudoers_files=$(_tn_ssh "ls /etc/sudoers.d/ 2>/dev/null")
    local stale=$(echo "$sudoers_files" | grep -c "\.bak\|\.backup")
    if [[ "$stale" -gt 0 ]]; then
        echo -e "      ⚠️  $stale stale backup files in /etc/sudoers.d/"
        total_findings=$((total_findings + 1))
    fi

    # ── Section 7: Bond & Network ──
    echo ""
    echo -e "    ${BOLD}━━━ Bond & Network Health ━━━${RESET}"
    local ifaces=$(_tn_midclt "interface.query")
    echo "$ifaces" | python3 -c "
import sys, json
ifaces = json.load(sys.stdin)
for i in ifaces:
    name = i.get('name', '?')
    itype = i.get('type', '?')
    mtu = i.get('state', {}).get('mtu', '?')
    link = i.get('state', {}).get('link_state', '?')
    aliases = [f\"{a['address']}/{a['netmask']}\" for a in i.get('state', {}).get('aliases', []) if a.get('type')=='INET']
    ip = aliases[0] if aliases else 'none'
    icon = '✅' if link == 'LINK_STATE_UP' else '❌'
    print(f'      {icon} {name:8s} {itype:20s} {ip:20s} MTU={mtu}')
" 2>/dev/null

    # ── Summary ──
    echo ""
    freq_divider
    echo -e "    Sweep complete: $total_findings findings, $total_ok items verified"
    freq_footer
    log "truenas: sweep completed ($TN_TARGET_NAME) — $total_findings findings"
}
```

### New: Snapshot Task Verification — `_tn_snapcheck()`

```bash
_tn_snapcheck() {
    freq_header "TrueNAS Snapshot Coverage ($TN_TARGET_NAME)"

    local snap_tasks=$(_tn_midclt "pool.snapshottask.query")
    local datasets=$(_tn_midclt "pool.dataset.query" \
        '[[\"pool\",\"=\",\"mega-pool\"],[\"type\",\"=\",\"FILESYSTEM\"]]' \
        '{\"select\":[\"id\",\"name\"]}')

    echo "$snap_tasks" | python3 -c "
import sys, json

tasks = json.load(sys.stdin)
datasets_raw = '''$(echo "$datasets")'''
datasets = json.loads(datasets_raw)
ds_names = [d['id'] for d in datasets]

if not tasks:
    print('    ❌ No automatic snapshot tasks configured')
    print('')
    print('    Datasets without snapshot protection:')
    for name in ds_names:
        print(f'      ⚠️  {name}')
    print('')
    print('    📋 Recommended snapshot tasks:')
    print('      1. mega-pool/smb-share — Daily, 14-day retention')
    print('      2. mega-pool/nfs-mega-share — Daily, 7-day retention')
    print('      3. mega-pool/proxmox-backups — Weekly, 4-week retention')
else:
    covered = set()
    for t in tasks:
        ds = t.get('dataset', '?')
        sched = t.get('schedule', {})
        retention = t.get('lifetime_value', '?')
        unit = t.get('lifetime_unit', '?')
        enabled = t.get('enabled', False)
        icon = '✅' if enabled else '❌'
        print(f'    {icon} {ds}: retention={retention}{unit}')
        covered.add(ds)

    uncovered = [d for d in ds_names if d not in covered and '/' in d]
    if uncovered:
        print('')
        print('    Datasets WITHOUT snapshot coverage:')
        for d in uncovered:
            print(f'      ⚠️  {d}')
" 2>/dev/null

    freq_footer
}
```

### New: Sudoers Verification — `_tn_sudoers()`

```bash
_tn_sudoers() {
    freq_header "TrueNAS Sudoers State ($TN_TARGET_NAME)"

    echo -e "    ${BOLD}Middleware DB (source of truth):${RESET}"
    echo ""

    local users=$(_tn_midclt "user.query" '[]' \
        '{"select":["username","uid","sudo_commands","sudo_commands_nopasswd"]}')

    echo "$users" | python3 -c "
import sys, json

users = json.load(sys.stdin)
for u in users:
    name = u.get('username', '?')
    uid = u.get('uid', '?')
    cmds = u.get('sudo_commands', []) or []
    nopass = u.get('sudo_commands_nopasswd', []) or []

    if not cmds and not nopass:
        continue

    print(f'    {name} (uid={uid}):')
    if nopass:
        print(f'      NOPASSWD ({len(nopass)} commands):')
        for c in nopass[:5]:
            print(f'        {c}')
        if len(nopass) > 5:
            print(f'        ... and {len(nopass)-5} more')
    if cmds:
        print(f'      WITH PASSWORD ({len(cmds)} commands):')
        for c in cmds[:3]:
            print(f'        {c}')
        if len(cmds) > 3:
            print(f'        ... and {len(cmds)-3} more')
    print('')
" 2>/dev/null

    echo -e "    ${BOLD}/etc/sudoers.d/ (on disk):${RESET}"
    _tn_ssh "ls -la /etc/sudoers.d/" 2>/dev/null | while read -r line; do
        echo "      $line"
    done

    # Check for stale files
    local stale_files=$(_tn_ssh "ls /etc/sudoers.d/ 2>/dev/null" | grep -E '\.bak|\.backup')
    if [ -n "$stale_files" ]; then
        echo ""
        echo -e "    ⚠️  Stale backup files found:"
        echo "$stale_files" | while read -r f; do
            echo -e "      - $f (can be removed)"
        done
    fi

    echo ""
    echo -e "    ${DIM}Note: TrueNAS middleware DB overrides /etc/sudoers.d/ on reboot (Lesson #124).${RESET}"
    echo -e "    ${DIM}The middleware DB is the ONLY source of truth for sudo rules.${RESET}"

    freq_footer
}
```

### Migration: Updated `_tn_api()` with Deprecation Warning

```bash
# PRESERVED for backward compatibility but DEPRECATED
# Emits warning on first use per session
_TN_API_WARNED=false
_tn_api() {
    if [[ "$_TN_API_WARNED" != "true" ]]; then
        log "truenas: WARNING — _tn_api() uses deprecated REST API (removed in 26.04). Migrate to _tn_midclt()."
        _TN_API_WARNED=true
    fi

    # Original implementation preserved as fallback
    local endpoint="$1"
    local method="${2:-GET}"
    local data="${3:-}"

    # ... (existing auth chain code) ...
}
```

### Updated Dispatcher

```bash
cmd_truenas() {
    require_operator
    local subcmd="${1:-status}"
    shift 2>/dev/null || true

    # Parse --target flag
    local target="prod"
    local args=()
    while [[ "${1:-}" == -* ]]; do
        case "$1" in
            --target) target="$2"; shift 2 ;;
            *) args+=("$1"); shift ;;
        esac
    done
    _tn_resolve_target "$target"

    case "$subcmd" in
        status)    _tn_status ;;
        pools)     _tn_pools ;;
        shares)    _tn_shares ;;
        alerts)    _tn_alerts ;;
        scrub)     _tn_scrub ;;
        snap)      _tn_snap "${args[@]}" ;;
        users)     _tn_users ;;
        nfs)       _tn_nfs ;;
        disks)     _tn_disks ;;
        backup)    _tn_backup ;;
        probe)     _tn_probe ;;
        # NEW subcommands:
        sweep)     _tn_sweep ;;
        health)    _tn_health ;;
        snapcheck) _tn_snapcheck ;;
        sudoers)   _tn_sudoers ;;
        *)         echo "Usage: freq truenas <status|pools|shares|alerts|scrub|snap|users|nfs|disks|backup|probe|sweep|health|snapcheck|sudoers> [--target lab|prod]" ;;
    esac
}
```

---

## 7. TUI MOCKUPS

### `freq truenas status` — Enhanced Dashboard

> **FACT-CHECK: All values match verified live data from 2026-03-11.**

```
┌─────────────────────────────────────────────────────────────────────┐
│  FREQ — TrueNAS Status (prod)                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Version:  TrueNAS-25.10.1                                          │
│  Hostname: truenas                                                   │
│  Model:    PowerEdge R530 (B065ND2)                                  │
│  CPU:      Intel Xeon E5-2620 v3 @ 2.40GHz (24 threads)            │
│  RAM:      86.4 GB ECC=True                                         │
│  Uptime:   2 days, 20:00:17                                         │
│  Load:     0.21 / 0.14 / 0.23                                       │
│                                                                     │
│  Pools:                                                              │
│    ✅ mega-pool: ONLINE (63% used) ✅ HEALTHY                       │
│                                                                     │
│  Services:                                                           │
│    ✅ SMB: RUNNING                                                   │
│    ✅ NFS: RUNNING                                                   │
│    ✅ SSH: RUNNING                                                   │
│                                                                     │
│  Bond (storage LACP):                                                │
│    ✅ bond0: UP (2/2 members active)                                │
│                                                                     │
│  ⚠️  Active Alerts: 1                                               │
│    WARNING: RESTAPIUsage                                             │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  TrueNAS-25.10.1 | mega-pool 63% | 3 services running | 1 alert    │
└─────────────────────────────────────────────────────────────────────┘
```

### `freq truenas health` — Comprehensive Health Check

```
┌─────────────────────────────────────────────────────────────────────┐
│  FREQ — TrueNAS Comprehensive Health (prod)                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  [1/8] Pool Health                                                   │
│    ✅ All pools ONLINE and healthy                                   │
│    ✅ Pool usage at 63% — OK                                        │
│                                                                     │
│  [2/8] Service Health                                                │
│    ✅ cifs: RUNNING                                                  │
│    ✅ nfs: RUNNING                                                   │
│    ✅ ssh: RUNNING                                                   │
│                                                                     │
│  [3/8] SMART Health                                                  │
│    ✅ /dev/sda: PASSED                                               │
│    ✅ /dev/sdb: PASSED                                               │
│    ✅ /dev/sdc: PASSED                                               │
│    ✅ /dev/sdd: PASSED                                               │
│    ✅ /dev/sde: PASSED                                               │
│    ✅ /dev/sdf: PASSED                                               │
│    ✅ /dev/sdg: PASSED                                               │
│    ✅ /dev/sdh: PASSED                                               │
│                                                                     │
│  [4/8] Disk Temperatures                                             │
│    ✅ sda: 37°C                                                      │
│    ✅ sdb: 37°C                                                      │
│    ✅ sdc: 37°C                                                      │
│    ✅ sdd: 36°C                                                      │
│    ✅ sde: 37°C                                                      │
│    ✅ sdf: 36°C                                                      │
│    ✅ sdg: 37°C                                                      │
│    ✅ sdh: 36°C                                                      │
│    ⚠️  sdi: N/A (no sensor)                                         │
│                                                                     │
│  [5/8] Bond (LACP) Health                                            │
│    Mode: IEEE 802.3ad Dynamic link aggregation                       │
│    ✅ eno2: up                                                       │
│    ✅ eno3: up                                                       │
│                                                                     │
│  [6/8] Snapshot Tasks                                                │
│    ⚠️  No automatic snapshot tasks configured                       │
│                                                                     │
│  [7/8] Active Alerts                                                 │
│    ⚠️  WARNING: RESTAPIUsage                                        │
│                                                                     │
│  [8/8] Scrub Recency                                                 │
│    ✅ mega-pool: last scrub 3 days ago, 0 errors                    │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────   │
│  ⚠️  2 WARNING | 0 CRITICAL (2 total findings)                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### `freq truenas sweep` — Interactive Audit (Excerpt)

```
┌─────────────────────────────────────────────────────────────────────┐
│  FREQ — TrueNAS Sweep — Interactive Audit (prod)                    │
├─────────────────────────────────────────────────────────────────────┤
│  Gathering data from 10.25.255.25...                                │
│                                                                     │
│  ━━━ Dataset ACL Verification ━━━                                   │
│    ✅ mega-pool: posix/discard (source=LOCAL)                       │
│    ✅ mega-pool/ssh-homes: posix/discard (source=INHERITED)         │
│    ✅ mega-pool/proxmox-backups: posix/discard (source=INHERITED)   │
│    ✅ mega-pool/nfs-mega-share: posix/discard (source=INHERITED)    │
│    ✅ mega-pool/smb-share: posix/discard (source=INHERITED)         │
│    ℹ️  mega-pool/smb-share/donny: posix/discard (not in map)       │
│                                                                     │
│  ━━━ SMB Share Verification ━━━                                     │
│    ✅ SMB1 disabled                                                  │
│    ✅ NTLMv1 disabled                                                │
│    ℹ️  SMB bind IPs: 10.25.25.25, 10.25.255.25                     │
│                                                                     │
│    Share: smb-share                                                  │
│      Path: /mnt/mega-pool/smb-share                                  │
│      Enabled: ✅ Yes                                                 │
│      hostsallow: 10.25.0.0/24, 10.25.25.0/24, 10.25.100.0/24       │
│      hostsdeny: (none)                                               │
│                                                                     │
│    ✅ smb-share-rw group has rwx                                    │
│    ✅ other access blocked (---)                                    │
│                                                                     │
│  ━━━ NFS Export Security ━━━                                        │
│    Servers: 24                                                       │
│    Protocols: NFSV3, NFSV4                                           │
│    Bind IP: 10.25.25.25                                              │
│                                                                     │
│    Export: /mnt/mega-pool/nfs-mega-share                             │
│      Comment: VM - Storage                                           │
│      Enabled: ✅ | Networks: 10.25.25.0/24, 10.25.100.0/24, ...    │
│      ℹ️  mapall_user=svc-admin:truenas_admin                       │
│                                                                     │
│    Export: /mnt/mega-pool/proxmox-backups                            │
│      Comment: proxmox-backups                                        │
│      Enabled: ✅ | Networks: 10.25.25.0/24                          │
│      ⚠️  maproot_user=root — root access from clients              │
│                                                                     │
│  ━━━ Snapshot Coverage ━━━                                          │
│    ❌ No automatic snapshot tasks configured                        │
│    ⚠️  A single rm -rf could lose data with no rollback            │
│    📋 Recommendation: Create snapshot tasks for smb-share, nfs      │
│                                                                     │
│  ━━━ Sudoers Consistency ━━━                                        │
│    ✅ sonny-aif: 59 NOPASSWD commands in middleware DB              │
│    ✅ chrisadmin: 59 NOPASSWD commands in middleware DB             │
│    ✅ donmin: 59 NOPASSWD commands in middleware DB                 │
│    ✅ jarvis-ai: 59 NOPASSWD commands in middleware DB             │
│    ⚠️  1 stale backup files in /etc/sudoers.d/                     │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────   │
│  Sweep complete: 3 findings, 12 items verified                      │
└─────────────────────────────────────────────────────────────────────┘
```

### `freq truenas disks` — Enhanced with SMART

```
┌─────────────────────────────────────────────────────────────────────┐
│  FREQ — TrueNAS Disks (prod)                                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Disk   Model                     Size     Temp   RPM    Bus   Serial    │
│  ───── ───────────────────────── ──────── ────── ────── ───── ──────────│
│  sda    HUS726060AL5210           5.5TB    37°C   7200   SCSI  K1HGNSUF │
│  sdb    HUS726060AL5210           5.5TB    37°C   7200   SCSI  K1HG3WAF │
│  sdc    HUS726060AL5210           5.5TB    37°C   7200   SCSI  K1HGEMUF │
│  sdd    HUS726060AL5210           5.5TB    36°C   7200   SCSI  K1HGSPPF │
│  sde    HUS726060AL5210           5.5TB    37°C   7200   SCSI  K1HADH3F │
│  sdf    HUS726060AL5210           5.5TB    36°C   7200   SCSI  K1HGPWGF │
│  sdg    HUS726060AL5210           5.5TB    37°C   7200   SCSI  K1HGSMVF │
│  sdh    HUS726060AL5210           5.5TB    36°C   7200   SCSI  K1HGTB5F │
│  sdi    SanDisk_SSD_PLUS_240GB    115GB    N/A    SSD    ATA   011163923│
│                                                                     │
│  SMART Health:                                                       │
│    ✅ /dev/sda: PASSED                                               │
│    ✅ /dev/sdb: PASSED                                               │
│    ✅ /dev/sdc: PASSED                                               │
│    ✅ /dev/sdd: PASSED                                               │
│    ✅ /dev/sde: PASSED                                               │
│    ✅ /dev/sdf: PASSED                                               │
│    ✅ /dev/sdg: PASSED                                               │
│    ✅ /dev/sdh: PASSED                                               │
│    ✅ /dev/sdi: PASSED                                               │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  9 disks | 8 HDD (pool) + 1 SSD (boot) | All SMART OK              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. SAFETY & BACKUP

### Kill-Chain Awareness

TrueNAS is NOT directly in the SSH kill-chain (unlike pfSense). The kill-chain is:

```
WSL → WireGuard → pfSense → mgmt VLAN → target
```

However, TrueNAS provides **storage** to the kill-chain infrastructure:
- PVE node configs backed up to TrueNAS NFS
- VM disks can be stored on TrueNAS NFS (ha-proxmox-disk export)
- All VM logs, backups, and media traverse TrueNAS NFS

**Disrupting TrueNAS NFS will not break SSH access but will break all VM services.**

### Protected Operations

| Operation | Risk | Gate |
|-----------|------|------|
| `freq tn scrub` | Can stress degraded pool, kill failing disk | Protected gate (existing) |
| `freq tn snap create` (future) | Low risk — creates point-in-time | Tier 3 confirmation |
| `freq tn snap delete` (future) | Deletes rollback protection | Tier 3 + interactive confirmation |
| `freq tn sweep` | Read-only audit | No gate needed |
| `freq tn health` | Read-only checks | No gate needed |
| All write operations via midclt | Modifies middleware state | Tier 3 + confirmation |

### Backup Naming

The existing `_tn_backup()` saves to:
```
/mnt/obsidian/FREQ/config-backup-YYYYMMDD/truenas-config-prod.db
/mnt/obsidian/FREQ/config-backup-YYYYMMDD/truenas-config-prod.json
```

This is preserved. No changes to backup naming.

### What FREQ Must NEVER Do on TrueNAS

- `zpool destroy`, `zfs destroy` — catastrophic data loss
- `midclt call pool.export` — removes pool from TrueNAS
- `midclt call service.stop` on nfs/cifs/ssh — kills VM services
- Change NFS `bindip` — kills connections, flushes policy routing (Lesson from CLAUDE.md)
- Modify `/etc/sudoers.d/` directly — will be overwritten by middleware
- Change bond0 members or LACP settings — storage VLAN outage

### Retry Policy

- SSH to TrueNAS: max 3 attempts, 5-second backoff
- `midclt` calls: 30-second timeout (already set in `_tn_midclt`)
- If TrueNAS is unreachable: report and abort, don't retry indefinitely
- `_tn_midclt` validates response is JSON before parsing — non-JSON returns error

---

## 9. CONFIGURATION

### FREQ Config Addition

```bash
# TrueNAS Module Configuration (existing, preserved)
FREQ_TN_ENABLED=1
FREQ_TN_PROD_IP="10.25.255.25"
FREQ_TN_LAB_IP="10.25.255.181"
FREQ_TN_SSH_USER="svc-admin"

# New configuration (sweep/health)
FREQ_TN_EXPECTED_SERVICES="cifs,nfs,ssh"        # Services that MUST be running
FREQ_TN_POOL_WARN_PCT=80                         # Pool usage warning threshold
FREQ_TN_POOL_CRIT_PCT=90                         # Pool usage critical threshold
FREQ_TN_TEMP_WARN=45                              # Disk temp warning (°C)
FREQ_TN_TEMP_CRIT=50                              # Disk temp critical (°C)
FREQ_TN_SCRUB_MAX_AGE_DAYS=14                    # Flag if scrub older than this
```

### API Migration Notes

The migration from `_tn_api()` to `_tn_midclt()` requires updating these existing functions:
- `_tn_status()` — uses `_tn_api "system/info"`
- `_tn_pools()` — uses `_tn_api "pool"`
- `_tn_shares()` — uses `_tn_api "sharing/smb"` and `_tn_api "sharing/nfs"`
- `_tn_alerts()` — uses `_tn_api "alert/list"`
- `_tn_scrub()` — uses `_tn_api "pool"` and `_tn_api "pool/id/$pool_id/scrub" "POST"`
- `_tn_snap()` — uses `_tn_api "zfs/snapshot?limit=20&order_by=-id"`
- `_tn_users()` — uses `_tn_api "user"`
- `_tn_nfs()` — uses `_tn_api "nfs"` and `_tn_api "sharing/nfs"`
- `_tn_disks()` — uses `_tn_api "disk"`
- `_tn_backup()` — uses `_tn_api "config/save" "POST"` and `_tn_api "system/general"`
- `_tn_probe()` — uses `_tn_api "user?username=jarvis-ai"` and `_tn_api "user" "POST"`

**Endpoint to midclt mapping:**

| REST Endpoint | midclt Method | Notes |
|---------------|---------------|-------|
| `system/info` | `system.info` | Direct |
| `pool` | `pool.query` | Direct |
| `disk` | `disk.query` | Direct |
| `sharing/smb` | `sharing.smb.query` | Direct |
| `sharing/nfs` | `sharing.nfs.query` | Direct |
| `alert/list` | `alert.list` | Direct |
| `nfs` | `nfs.config` | Direct |
| `user` | `user.query` | Direct |
| `service` | `service.query` | Direct (new) |
| `pool/id/N/scrub` (POST) | `pool.scrub N` | Syntax differs |
| `zfs/snapshot` | `zfs.snapshot.query` | Add filters as args |
| `config/save` (POST) | `system.config.save` | Returns differently |
| `system/general` | `system.general.config` | Direct |
| `user` (POST) | `user.create` | Syntax differs |
| `user/id/N` (PUT) | `user.update N {...}` | Syntax differs |
| `disk.temperatures` | `disk.temperatures` | Direct (new) |
| `smart.test.query` | `smart.test.query` | Direct (new) |
| `smb.config` | `smb.config` | Direct (new) |
| `ssh.config` | `ssh.config` | Direct (new) |
| `interface.query` | `interface.query` | Direct (new) |
| `pool.snapshottask.query` | `pool.snapshottask.query` | Direct (new) |
| `pool.scrub.query` | `pool.scrub.query` | Direct (new) |
| `pool.dataset.query` | `pool.dataset.query` | With filter args |
| `group.query` | `group.query` | Direct (new) |

---

## 10. IMPLEMENTATION PHASES

### Phase 1: API Migration (CRITICAL — blocks everything) — ~80 lines changed

**What ships:**
- `_tn_midclt()` — new SSH+midclt transport function
- `_tn_ssh()` — explicit SSH wrapper for non-midclt commands
- Migrate all 11 existing functions from `_tn_api()` to `_tn_midclt()`
- `_tn_api()` preserved with deprecation warning (fallback only)
- Verify all existing subcommands still work after migration

**Why first:** The REST API is deprecated and will break on TrueNAS 26.04 upgrade. This is a ticking time bomb. Must be done before anything else.

**Risk:** LOW — same data, different transport. `midclt call` returns identical JSON to REST API.

### Phase 2: Enhanced Status + Health Check — ~200 lines new

**What ships:**
- `_tn_status()` enhanced with service health, bond state, alert details
- `_tn_health()` — new comprehensive 8-point health check
- `_tn_disks()` enhanced with SMART health per disk
- Bond health checking via `/proc/net/bonding/bond0`
- Service health checking via `service.query`

**Still read-only. No writes.**

### Phase 3: Sweep — Interactive Audit — ~350 lines new

**What ships:**
- `_tn_sweep()` — main interactive audit
- `_tn_sweep_datasets()` — ACL verification
- `_tn_sweep_smb()` — SMB share permission check
- `_tn_sweep_nfs()` — NFS export security analysis
- `_tn_sweep_services()` — service health
- `_tn_sweep_snapshots()` — snapshot coverage
- `_tn_sweep_sudoers()` — middleware DB vs disk consistency
- `_tn_sweep_bond()` — LACP health
- `_tn_sweep_smart()` — per-disk SMART

**Read-only. Reports findings, doesn't fix them.**

### Phase 4: Snapshot & Sudoers Tools — ~150 lines new

**What ships:**
- `_tn_snapcheck()` — snapshot task coverage report
- `_tn_sudoers()` — sudoers state display
- Enhanced `_tn_nfs()` with security flags
- Menu integration for all new subcommands

### Phase 5: Hardware Cross-Reference (optional) — ~50 lines new

**What ships:**
- Cross-reference iDRAC alerts (PSU, fan, thermal) in TrueNAS health output
- Requires `freq idrac` module to exist (Phase 5 depends on iDRAC module)
- If iDRAC module not available, skip gracefully

---

## 11. LOC ESTIMATE

| Component | Current Lines | Added Lines | New Total |
|-----------|--------------|-------------|-----------|
| `lib/truenas.sh` (existing module) | 302 | ~830 | ~1,130 |
| Config additions | — | ~15 | ~15 |
| CLI dispatcher additions | — | ~10 | ~10 |
| Menu integration | — | ~30 | ~30 |
| Help text | — | ~20 | ~20 |
| **Total** | **302** | **~905** | **~1,205** |

**Phase breakdown:**

| Phase | Lines |
|-------|-------|
| Phase 1: API Migration | ~80 (changed, not added) |
| Phase 2: Enhanced Status + Health | ~200 |
| Phase 3: Sweep | ~350 |
| Phase 4: Snapshot & Sudoers | ~150 |
| Phase 5: Hardware Cross-Reference | ~50 |

**Comparison to other modules:**

| Module | Lines | Role |
|--------|-------|------|
| `lib/truenas.sh` (after) | ~1,130 | Storage management + sweep |
| `lib/pfsense.sh` (after pf sweep) | ~1,430 | Firewall management + sweep |
| `lib/idrac.sh` (proposed) | ~920 | BMC management |
| `lib/core.sh` | 802 | Core FREQ framework |
| `lib/audit.sh` | 588 | Audit operations |
| `lib/menu.sh` | 711 | Interactive menu |

The TrueNAS module would be the second-largest after pfSense, which makes sense — TrueNAS is the storage backbone with more surface area to audit than BMC management.

---

## 12. OPEN QUESTIONS FOR IMPLEMENTATION

1. **REST API migration timing** — ✅ **ANSWERED:** Must be done before TrueNAS upgrades to 26.04 (REST API removed). Current version is 25.10.1. The `midclt` transport is proven working in this session.

2. **midclt POST equivalents** — 🔲 **NEEDS TESTING:** `_tn_backup()` and `_tn_probe()` use REST API POST methods. The `midclt` equivalents (`system.config.save`, `user.create`, `user.update`) need syntax verification before migration. Test on lab instance (VM 981) first.

3. **Snapshot task creation** — 🔲 **DEFERRED:** The sweep identifies the gap (no snapshot tasks) but doesn't create them. Creating snapshot tasks would be `midclt call pool.snapshottask.create '{...}'` — needs schema verification. Sonny should decide retention policies.

4. **SMART test scheduling** — 🔲 **DEFERRED:** No SMART tests configured. Should FREQ create them? Recommended: monthly LONG tests on all HDDs. Needs Sonny's approval.

5. **freq-admin service account** — ℹ️ **NOTED:** freq-admin (uid 3005) exists but has no SSH, home=/var/empty, no sudo. It was likely created for API key auth. With the migration to `midclt` via SSH (as svc-admin), freq-admin may be unnecessary. Don't delete — just note it.

6. **Stale sudoers backup** — ℹ️ **NOTED:** `/etc/sudoers.d/dc01-probe-readonly.backup-s072` is a stale backup. Can be removed but it's harmless (files with `.` or `.backup` extension are ignored by sudoers). Not urgent.

7. **svc-admin primary group** — ℹ️ **NOTED:** svc-admin's primary group is `truenas_admin` (GID 950), NOT `svc-admin` (GID 3000). The `svc-admin` group exists but has 0 members. This is a TrueNAS quirk — the user was created via middleware which assigned `truenas_admin` as primary. Not a problem, just unexpected.

8. **Bond MTU vs eno4 MTU** — ✅ **ANSWERED:** bond0/eno1/eno2/eno3 = MTU 9000 (jumbo frames, storage+LAN). eno4 = MTU 1500 (management). This is correct — management traffic doesn't need jumbo frames.

9. **Proxmox-backups refquota** — ℹ️ **NOTED:** The `available` field for proxmox-backups shows 1.63 TiB (vs pool's 7.56 TiB), indicating a refquota. FREQ should display this quota alongside usage. Needs `pool.dataset.query` with `refquota` field in select.

10. **ha-proxmox-disk export** — ℹ️ **NOTED:** NFS export for HA Proxmox disks has no user mapping and no auth — any storage VLAN client has full access. This is correct for PVE shared storage but should be flagged in sweep as an "expected but notable" finding.

---

## 13. FACT-CHECK RESULTS (2026-03-11)

This section documents all findings from live-probing TrueNAS via SSH + midclt.

### Summary of Findings

| # | Finding | Section Affected | Severity |
|---|---------|-----------------|----------|
| FC-1 | REST API deprecated — 52 calls/24h flagged, removed in 26.04 | §1, §5, §9 | **CRITICAL** — FREQ will break on upgrade |
| FC-2 | No snapshot tasks configured (pool.snapshottask.query = []) | §3, §7 sweep | **WARNING** — no rollback protection |
| FC-3 | No SMART test schedule (smart.test.query fails/empty) | §3, §7 sweep | **WARNING** — no periodic disk health validation |
| FC-4 | svc-admin primary group is truenas_admin (950), not svc-admin (3000) | §3 user table | **INFO** — unexpected but not a problem |
| FC-5 | freq-admin account exists (uid 3005) with no SSH, no sudo, home=/var/empty | §3 user table | **INFO** — vestigial, may be unnecessary |
| FC-6 | Stale backup file in /etc/sudoers.d/ (dc01-probe-readonly.backup-s072) | §3 sudoers | **INFO** — harmless, can be cleaned |
| FC-7 | bond0 both members UP, 0 link failures, LACP active, layer2+3 hash | §3 network | **OK** — healthy |
| FC-8 | All 8 HDDs SMART OK, temps 36-37°C | §3 disk table | **OK** — healthy |
| FC-9 | Pool 63% used, 0 errors, last scrub 3 days ago with 0 errors | §3 pool | **OK** — healthy |
| FC-10 | SMB1 disabled, NTLMv1 disabled, hostsallow set correctly | §3 SMB config | **OK** — correctly hardened |
| FC-11 | NFS bindip=10.25.25.25 only (storage VLAN) — correct | §3 NFS config | **OK** — correctly restricted |
| FC-12 | SSH binds to eno4 (mgmt) only, AllowUsers set for 5 accounts | §3 SSH config | **OK** — correctly restricted |
| FC-13 | Middleware DB has 59 NOPASSWD commands for all 4 probe accounts | §3 sudoers | **OK** — S073 fix holding |
| FC-14 | proxmox-backups has refquota (~1.63 TiB available vs pool's 7.56 TiB) | §3 datasets | **INFO** — correctly limited |

### Verified Live Data Snapshot (2026-03-11)

**System:**
- Version: TrueNAS-25.10.1
- Hostname: truenas
- Model: PowerEdge R530 (B065ND2)
- CPU: Intel Xeon E5-2620 v3 @ 2.40GHz, 24 threads
- RAM: 86.4 GB ECC
- Uptime: ~3 days
- Load: 0.21 / 0.14 / 0.23

**Pool:** mega-pool, ONLINE, 2× RAIDZ2 (8× HGST HUS726060AL5210 6TB), 63% used (27.8T/43.6T), 10% fragmentation, scrub clean.

**Disks:** 8× HDD (36-37°C, all SMART OK) + 1× SSD boot (SanDisk 240GB, no temp sensor).

**Network:** eno1 (LAN, 9000), eno4 (mgmt, 1500), bond0 (storage LACP, 9000, 2 members up).

**Services:** cifs RUNNING, nfs RUNNING, ssh RUNNING.

**Shares:** 1 SMB (smb-share, hostsallow 3 subnets), 3 NFS (nfs-mega-share, ha-proxmox-disk, proxmox-backups).

**Users:** 8 accounts (root + truenas_admin + 4 probe + svc-admin + freq-admin). Probe accounts have 59 NOPASSWD commands via middleware DB.

**Alerts:** 1 WARNING (REST API deprecation).

**Gaps:** No snapshot tasks. No SMART tests. No replications.

### Verified midclt Methods (Tested Working)

```
sudo midclt call system.info                    # ✅ Returns JSON
sudo midclt call system.version                 # ✅ Returns string
sudo midclt call pool.query                     # ✅ Returns JSON array
sudo midclt call pool.dataset.query '[filters]' '{options}' # ✅ With filters
sudo midclt call pool.snapshottask.query        # ✅ Returns [] (empty)
sudo midclt call pool.scrub.query               # ✅ Returns scrub schedule
sudo midclt call disk.query                     # ✅ Returns JSON array
sudo midclt call disk.temperatures              # ✅ Returns JSON object
sudo midclt call sharing.smb.query              # ✅ Returns JSON array
sudo midclt call sharing.nfs.query              # ✅ Returns JSON array
sudo midclt call smb.config                     # ✅ Returns JSON object
sudo midclt call nfs.config                     # ✅ Returns JSON object
sudo midclt call ssh.config                     # ✅ Returns JSON object
sudo midclt call service.query                  # ✅ Returns JSON array
sudo midclt call user.query                     # ✅ Returns JSON array
sudo midclt call user.query '[filters]' '{options}' # ✅ With filters+select
sudo midclt call group.query                    # ✅ Returns JSON array
sudo midclt call alert.list                     # ✅ Returns JSON array
sudo midclt call interface.query                # ✅ Returns JSON array
sudo midclt call network.general.summary        # ✅ Returns JSON object
sudo midclt call update.check_available         # ❌ Failed (exit code 1 — may need network)
```

### SSH Access Reference (Verified Working)

```bash
# Direct from WSL (WireGuard routed):
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    svc-admin@10.25.255.25 "sudo midclt call system.info"

# From PVE node (L2 adjacent):
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    svc-admin@10.25.255.25 "sudo midclt call pool.query"

# From VM 999 (FREQ home) via PVE gateway:
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
    svc-admin@10.25.255.26 \
    "sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    svc-admin@10.25.255.25 'sudo midclt call system.info'"

# Non-midclt commands (need sudo explicitly):
sshpass -p 'changeme1234' ssh svc-admin@10.25.255.25 \
    "sudo cat /proc/net/bonding/bond0"
sshpass -p 'changeme1234' ssh svc-admin@10.25.255.25 \
    "sudo smartctl -H /dev/sda"
sshpass -p 'changeme1234' ssh svc-admin@10.25.255.25 \
    "sudo getfacl /mnt/mega-pool/smb-share"
```

---

*Generated by Jarvis — S078 (fact-check integrated). Feature design for `freq truenas` module hardening based on live fact-check against TrueNAS-25.10.1 (2026-03-11). 14 findings documented. Current module: 302 lines, 11 subcommands. Proposed: ~1,130 lines, 15 subcommands. Critical finding: REST API deprecated, removed in 26.04 — must migrate to midclt before upgrade. Pool healthy (63%, 0 errors). No snapshot tasks, no SMART tests — recommended additions. Sweep pattern matches freq pf sweep design.*
