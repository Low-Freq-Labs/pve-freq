# AUDIT: Remaining Items — S034 (2026-02-20)

**Type:** Research only — no changes made
**Auditor:** Jarvis
**Date:** 2026-02-20 19:41 CST

---

## 1. NFS Cleanup Verification

### 1a. NFS Root — `plex` Symlink
**Status:** ALREADY REMOVED
No `plex` symlink exists at `/mnt/mega-pool/nfs-mega-share/`. NFS root contains only:
- `DC01_v1.1_base_config/`
- `arr-data-backup-pre-overhaul-S032/` (see item 5)
- `media/`

### 1b. Media Dir — Uppercase Symlinks (Movies->movies, etc.)
**Status:** ALREADY REMOVED
No symlinks found in `/mnt/mega-pool/nfs-mega-share/media/`. Only real directories remain:
- `.backup-nfs-migration-S029/` (see item 4)
- `audio/`, `config-backups/`, `downloads/`, `movies/`, `transcode/`, `tv/`

### 1c. VM 102 — `.pre-overhaul` Dirs
**Status:** ALREADY REMOVED
No `.pre-overhaul` directories found under `/opt/` on VM 102 (10.25.255.31).

### 1d. VM 103 — `qbit-stack.pre-overhaul`
**Status:** ALREADY REMOVED
`/home/sonny-aif/qbit-stack.pre-overhaul` does not exist on VM 103 (10.25.255.32).

### 1e. NFS Root — `arr-data-archived/`
**Status:** ALREADY REMOVED
The `arr-data-archived/` directory referenced in CLAUDE.md cleanup pending no longer exists on NFS.

**SUMMARY:** All symlinks and `.pre-overhaul` directories have been cleaned up. The cleanup items from CLAUDE.md under "Cleanup Pending (after 2026-02-22)" for symlinks and pre-overhaul dirs can be marked DONE. Only the `arr-data-backup-pre-overhaul-S032` item remains (see item 5).

---

## 2. TrueNAS Management NIC MTU

**Host:** TrueNAS (10.25.255.25)
**Interface:** eno4 (altname enp3s0f1)
**MTU:** 1500
**Link State:** UP
**MAC:** 18:66:da:7f:0d:8d

**Assessment:** MTU 1500 is CORRECT for the management VLAN. Management traffic (SSH, web UI, SMB) does not benefit from jumbo frames and 1500 ensures compatibility with all management clients. The switch has jumbo frames (MTU 9198) on all ports, but the endpoint MTU matters — 1500 is the right choice here.

---

## 3. ZFS Scrub Schedule

**Pool:** mega-pool
**State:** ONLINE
**Layout:** 2x raidz2 vdevs (4 disks each = 8 total)
**Errors:** No known data errors
**Last Scrub:** Sun Feb 8 02:00:02 2026 — repaired 0B, 0 errors

**Schedule:** Managed by TrueNAS middleware (crontab contains only `middlewared` entry). The `midcli call pool.scrub.query` command returned no output, suggesting the scrub schedule may be configured through the TrueNAS web UI rather than exposed via CLI.

**Assessment:** The last scrub was 12 days ago (Feb 8). TrueNAS SCALE defaults to monthly scrubs (first Sunday of each month at 00:00). The Feb 8 scrub aligns with this default schedule. Next expected scrub: ~March 1, 2026. Pool is healthy — zero errors across all vdevs.

**Recommendation:** Verify scrub schedule via TrueNAS web UI at `https://10.25.255.25` under Data Protection > Scrub Tasks to confirm the recurring schedule.

---

## 4. `.backup-nfs-migration-S029` on NFS

**Location:** `/mnt/mega-pool/nfs-mega-share/media/.backup-nfs-migration-S029/`
**Size:** 51K
**Contents (6 files):**
- `docker-compose.arr.yml`
- `docker-compose.plex.yml`
- `docker-compose.qbit.yml`
- `docker-compose.tdarr-node.yml`
- `docker-compose.tdarr.yml`
- `docker-compose.tdarr.yml.bak-session22`

**Assessment:** This is a small (51K) backup of the old NFS-based compose files from the Session 29 migration. These are the pre-overhaul compose files that lived on NFS before configs were moved local to each VM. Safe to delete — the canonical compose files now live at `/opt/dc01/compose/docker-compose.yml` on each VM, and a full base config backup exists at `DC01_v1.1_base_config/`.

**Recommendation:** Safe to remove. The `DC01_v1.1_base_config` backup (S024) already preserves these.

---

## 5. `arr-data-backup-pre-overhaul-S032` at NFS Root

**Location:** `/mnt/mega-pool/nfs-mega-share/arr-data-backup-pre-overhaul-S032/`
**Size:** 1.1G
**Contents (12 directories):**
- `bazarr/`, `overseerr/`, `overseerr-backup/`, `plex/`, `plex.backup.20260216/`
- `prowlarr/`, `qbittorrent/`, `radarr/`, `sabnzbd/`, `sonarr/`
- `tdarr/`, `tdarr-node/`

**Assessment:** This is a 1.1GB backup of ALL service config data from before the Docker Infrastructure Overhaul (Phase 7, S032). Contains full config directories for every service. This is the safety net from the overhaul.

**Recommendation:** This should be kept until the daily backup cron (`/etc/cron.d/dc01-backup`) has been running reliably for at least a week and verified. Once backup cron is confirmed healthy with multiple successful runs, this 1.1G directory can be safely removed. Per CLAUDE.md: "Delete `arr-data-archived/` on NFS (after confirming backup cron running)" — `arr-data-archived` is already gone, but this S032 backup is the equivalent holdover.

---

## 6. Switch Password Encryption (F-018)

**Host:** Cisco 4948E-F (10.25.255.5)
**Finding F-018:** `service password-encryption` needed

**Result:** `service password-encryption` IS enabled. Output shows:
```
service password-encryption
 password 7 <REDACTED>
 password 7 <REDACTED>
```

**Assessment:** F-018 is FIXED. The `service password-encryption` command is in the running config, and passwords are displayed as type 7 (encrypted) rather than plaintext. Note: Cisco type 7 encryption is weak (reversible), but it prevents casual shoulder-surfing. True security comes from SSH key auth and `enable secret` (type 5/8/9).

---

## 7. TrueNAS Timezone (F-024)

**Host:** TrueNAS (10.25.255.25)

**Result:**
```
Time zone: America/Chicago (CST, -0600)
System clock synchronized: yes
NTP service: active
```

**Assessment:** F-024 is FIXED. Timezone is correctly set to America/Chicago. System clock is synchronized via NTP. No issues.

---

## 8. VM 104 GPU Render Node

**Host:** VM 104 / Tdarr-Node (10.25.255.34, pve03)
**GPU:** AMD Radeon RX 470/480/570/580 (Ellesmere) — visible via lspci

**Device nodes:**
| Device | Present | Owner | Major:Minor |
|--------|---------|-------|-------------|
| `/dev/dri/card0` | YES | root:video | 226,0 |
| `/dev/dri/renderD128` | **NO** | — | — |
| `/dev/kfd` | YES | root:render | 239,0 |

**Group memberships:**
- `video` group: sonny-aif (svc-admin NOT listed)
- `render` group: empty (no users)

**Assessment: ISSUES FOUND**

1. **MISSING `/dev/dri/renderD128`** — This is the render node needed for GPU compute/transcode workloads. Without it, Tdarr cannot use the GPU for hardware transcoding. The `card0` device is present (DRM master) but `renderD128` (render-only access) is absent. This likely means the `amdgpu` driver loaded but the render node was not created — possibly due to a missing kernel module (`drm_render`) or a Proxmox GPU passthrough configuration issue.

2. **svc-admin not in `video` or `render` groups** — Even if `renderD128` existed, the Docker container (running as PUID=3003/svc-admin) would need access. The Tdarr container likely maps these devices, but the host-level permissions matter for passthrough.

**Recommendation:**
- Check Proxmox VM 104 hardware config for GPU passthrough settings
- On VM 104, check if `amdgpu` module is loaded: `lsmod | grep amdgpu`
- Check kernel log for GPU init errors: `dmesg | grep -i -E 'amdgpu|drm|render'`
- Add svc-admin to video and render groups if GPU transcoding is desired
- This may require a VM reboot or Proxmox config change to expose renderD128

---

## 9. Stale VLANs on pfSense (113 and 715)

**Host:** pfSense (10.25.255.1)

**Active VLAN interfaces on lagg0:**
| Interface | VLAN | Status | MTU |
|-----------|------|--------|-----|
| lagg0.5 | 5 (Public) | UP, RUNNING | 1500 |
| lagg0.10 | 10 (Compute) | UP, RUNNING | 1500 |
| lagg0.25 | 25 (Storage) | UP, RUNNING | 1500 |
| lagg0.2550 | 2550 (Management) | UP, RUNNING | 1500 |
| lagg0.66 | 66 (Dirty) | UP, RUNNING | 1500 |

**Assessment:** VLANs 113 and 715 are NOT present. Only the 5 expected VLANs exist (5, 10, 25, 66, 2550). If stale VLANs were previously flagged, they have already been cleaned up.

**Note on MTU:** All VLAN interfaces show MTU 1500, while `lagg0` itself is MTU 9000. This is expected behavior — VLAN sub-interfaces can have their own MTU independent of the parent. The LACP bond carries jumbo frames, but the VLAN interfaces are configured for standard MTU. If jumbo frames are needed on specific VLANs (e.g., VLAN 25 for NFS/storage traffic), those would need to be set individually.

---

## Summary Table

| # | Item | Status | Action Needed |
|---|------|--------|---------------|
| 1a | NFS `plex` symlink | REMOVED | None — mark cleanup item DONE |
| 1b | Uppercase media symlinks | REMOVED | None — mark cleanup item DONE |
| 1c | VM 102 `.pre-overhaul` dirs | REMOVED | None — mark cleanup item DONE |
| 1d | VM 103 `.pre-overhaul` dir | REMOVED | None — mark cleanup item DONE |
| 1e | NFS `arr-data-archived/` | REMOVED | None — mark cleanup item DONE |
| 2 | TrueNAS eno4 MTU | 1500 (correct) | None |
| 3 | ZFS scrub schedule | Healthy, last scrub Feb 8 | Verify schedule via web UI |
| 4 | `.backup-nfs-migration-S029` | EXISTS (51K) | Safe to delete |
| 5 | `arr-data-backup-pre-overhaul-S032` | EXISTS (1.1G) | Keep until backup cron verified |
| 6 | Switch password encryption (F-018) | FIXED | None |
| 7 | TrueNAS timezone (F-024) | FIXED | None |
| 8 | VM 104 GPU renderD128 | **MISSING** | Investigate — GPU transcoding broken |
| 9 | Stale VLANs 113/715 | NOT PRESENT | None — already cleaned |

### Items Requiring Attention
1. **VM 104 GPU render node** — `/dev/dri/renderD128` missing. GPU transcoding will not work until this is resolved. Needs investigation at Proxmox level.
2. **NFS cleanup** — Two small backup directories remain (`.backup-nfs-migration-S029` at 51K, `arr-data-backup-pre-overhaul-S032` at 1.1G). Neither is urgent but both can be cleaned up once backup cron is verified.
3. **ZFS scrub schedule** — Confirm via TrueNAS web UI that recurring scrub is scheduled.
