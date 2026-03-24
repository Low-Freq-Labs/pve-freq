# FIX-S034: Backup Cron Investigation & Fix

**Date:** 2026-02-20
**Session:** S034
**Scope:** VMs 101, 102, 103, 104, 105 — daily backup cron at `/etc/cron.d/dc01-backup`

---

## Problem Statement

Only VM 104 (tdarr-node) was producing NFS backups. VMs 101, 102, 103, 105 had **empty** pre-created NFS backup directories (`plex-server/`, `arr-stack/`, `qbit-downloader/`, `tdarr-server/`).

---

## Root Causes Found (3 issues)

### Issue 1: NFS Stale Mounts on pve01 VMs (VMs 101, 102)

**Symptom:** `cp` to NFS returns `Input/output error`. dmesg shows `nfs: server 10.25.25.25 not responding, timed out`. NFS TCP connections stuck in `FIN-WAIT-1` with ~1MB pending data.

**Affected:** VM 101 (plex) and VM 102 (arr-stack) — both hosted on pve01, both using `10.25.25.25` (Storage VLAN 25) as NFS target.

**Root Cause:** The NFS TCP connections from pve01 VMs to the TrueNAS storage VLAN IP (`10.25.25.25`) were going stale. Traffic routes from VLAN 5 (10.25.5.x) through the pfSense gateway, which appears to have intermittent issues maintaining long-lived NFS sessions to VLAN 25. The `soft` mount option causes operations to return I/O errors instead of hanging indefinitely (by design), but the mount itself stays in a broken state.

**Fix Applied:**
- Changed fstab on VM 101 and VM 102 from `10.25.25.25` to `10.25.255.25` (Management VLAN)
- Force unmounted stale NFS mounts (`sudo umount -f -l`) and remounted via `.255.25`
- Management VLAN routing is more direct (ens19 → .255.25) and doesn't traverse inter-VLAN routing through pfSense

**Note:** VM 103 (qbit) already used `.255.25` in fstab. VMs 104 and 105 use `.25.25` but are on VLAN 10 (Compute) which has a more reliable path to storage VLAN — left unchanged since they work.

**Follow-up needed:** Investigate why pve01 VLAN 5 → VLAN 25 NFS sessions go stale. May be pfSense firewall state timeout, MTU mismatch on the inter-VLAN path, or switch-level issue. This is a separate infrastructure investigation.

### Issue 2: `set -euo pipefail` + tar Exit Code 1

**Symptom:** On VM 102 (arr-stack), Docker services (Huntarr, Prowlarr, etc.) modify config files while tar is running. tar returns exit code 1 with message `configs/huntarr: file changed as we read it`. With `set -euo pipefail`, this kills the script before the NFS copy.

**Root Cause:** `set -e` treats any non-zero exit as fatal. tar exit code 1 is a **warning** (files changed during archive), not an error. The archive is still valid and complete. Exit code 2+ indicates actual errors.

**Fix Applied:** Changed `set -euo pipefail` to `set -uo pipefail` (removed `-e`). Added explicit exit code handling for tar:
- Exit 0: success
- Exit 1: warning (logged, script continues)
- Exit 2+: actual error (script aborts)

### Issue 3: Hostname vs NFS Directory Mismatch

**Symptom:** Pre-created NFS directories used VM display names (`plex-server`, `qbit-downloader`, `tdarr-server`), but the backup script uses `/etc/hostname` which returns shorter names (`plex`, `qbit`, `tdarr`). The `mkdir -p` in the script creates NEW directories with the hostname-based names, so backups go to `plex/` while monitoring looks at the empty `plex-server/`.

**Affected:**
| VM | /etc/hostname | Pre-created NFS dir | Actual backup dir |
|----|---------------|--------------------|--------------------|
| 101 | plex | plex-server | plex |
| 102 | arr-stack | arr-stack | arr-stack (MATCH) |
| 103 | qbit | qbit-downloader | qbit |
| 104 | tdarr-node | tdarr-node | tdarr-node (MATCH) |
| 105 | tdarr | tdarr-server | tdarr |

**Fix Applied:**
- Removed empty wrong-name NFS directories (`plex-server/`, `qbit-downloader/`, `tdarr-server/`)
- Hostname-based directories are now canonical (`plex/`, `qbit/`, `tdarr/`)
- No hostname changes needed — the script's `mkdir -p` creates the correct directories

---

## Fixes Applied

### 1. Updated backup script on ALL 5 VMs

**File:** `/opt/dc01/backups/backup.sh` (original backed up as `backup.sh.bak-20260220`)

**Changes:**
- `set -euo pipefail` → `set -uo pipefail` (allow tar exit 1)
- Added tar exit code handling (exit 1 = warning, exit 2+ = error)
- Added local backup size verification (abort if 0 bytes)
- NFS copy now uses temp file + atomic rename to prevent 0-byte files on NFS errors
- Added cleanup of partial temp files on NFS copy failure

### 2. Updated fstab on VMs 101 and 102

**VMs 101, 102:** `/etc/fstab` NFS entry changed from `10.25.25.25` to `10.25.255.25`

### 3. Cleaned up NFS config-backups directory

- Removed 5 zero-byte tar.gz files (failed copy artifacts)
- Removed 3 empty wrong-name directories (`plex-server/`, `qbit-downloader/`, `tdarr-server/`)

---

## Verification

Manual backup run on all 5 VMs after fixes:

| VM | Hostname | Local Backup | NFS Backup | Size | Status |
|----|----------|-------------|------------|------|--------|
| 101 | plex | OK | OK | 204 MB | VERIFIED |
| 102 | arr-stack | OK | OK | 52 MB | VERIFIED |
| 103 | qbit | OK | OK | 5.8 MB | VERIFIED |
| 104 | tdarr-node | OK | OK | 14 KB | VERIFIED (was already working) |
| 105 | tdarr | OK | OK | 6.5 MB | VERIFIED |

---

## NFS Backup Directory Layout (Final)

```
/mnt/truenas/nfs-mega-share/media/config-backups/
├── arr-stack/      ← VM 102 (52 MB backups)
├── plex/           ← VM 101 (204 MB backups)
├── qbit/           ← VM 103 (5.8 MB backups)
├── tdarr/          ← VM 105 (6.5 MB backups)
└── tdarr-node/     ← VM 104 (14 KB backups)
```

---

## Open Items

1. **pve01 Storage VLAN NFS stability:** VMs on pve01 using VLAN 5 → VLAN 25 have intermittent NFS session failures. Workaround: using management VLAN `.255.25` for NFS. Root cause needs investigation (pfSense state table, MTU, switch config).

2. **VM 101 Plex backup size:** 204 MB per backup (Plex configs are large). At 7-day NFS retention, this is ~1.4 GB for Plex alone. Consider excluding Plex cache/thumbnails from backup if size becomes a concern.

3. **Cron has never actually fired at 03:00:** These VMs may have been deployed today (Feb 20). The cron will fire for the first time tonight at 03:00. The manual runs confirm the scripts work.

---

## Fixed Backup Script (deployed to all 5 VMs)

```bash
#!/bin/bash
# DC01 Config Backup Script
# Backs up /opt/dc01/configs/ to NFS, keeps last 7 days
set -uo pipefail

HOSTNAME_TAG=$(cat /etc/hostname | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
BACKUP_DIR="/opt/dc01/backups"
NFS_BACKUP="/mnt/truenas/nfs-mega-share/media/config-backups/${HOSTNAME_TAG}"
DATE=$(date +%Y%m%d-%H%M)
TARBALL="dc01-configs-${DATE}.tar.gz"

# Create local backup
# tar exit code 1 = "file changed as we read it" (non-fatal warning)
tar czf "${BACKUP_DIR}/${TARBALL}" -C /opt/dc01 configs/ 2>&1
TAR_EXIT=$?
if [ $TAR_EXIT -gt 1 ]; then
    echo "ERROR: tar failed with exit code ${TAR_EXIT}" >&2
    exit 1
elif [ $TAR_EXIT -eq 1 ]; then
    echo "WARNING: tar reported file changes during backup (non-fatal)"
fi

# Verify local backup is not empty
if [ ! -s "${BACKUP_DIR}/${TARBALL}" ]; then
    echo "ERROR: Local backup is empty, aborting" >&2
    exit 1
fi

# Copy to NFS (soft mount means this fails gracefully if NFS is down)
if mountpoint -q /mnt/truenas/nfs-mega-share; then
    mkdir -p "${NFS_BACKUP}"
    # Copy to temp file first, then atomic rename to avoid 0-byte files
    cp "${BACKUP_DIR}/${TARBALL}" "${NFS_BACKUP}/.${TARBALL}.tmp"
    if [ $? -eq 0 ]; then
        mv "${NFS_BACKUP}/.${TARBALL}.tmp" "${NFS_BACKUP}/${TARBALL}"
    else
        echo "WARNING: NFS copy failed, removing partial file" >&2
        rm -f "${NFS_BACKUP}/.${TARBALL}.tmp"
    fi
    # Prune NFS backups older than 7 days
    find "${NFS_BACKUP}" -name "dc01-configs-*.tar.gz" -mtime +7 -delete 2>/dev/null || true
else
    echo "WARNING: NFS not mounted, backup saved locally only" >&2
fi

# Prune local backups older than 3 days (NFS has the longer retention)
find "${BACKUP_DIR}" -name "dc01-configs-*.tar.gz" -mtime +3 -delete 2>/dev/null || true

echo "Backup complete: ${TARBALL}"
```

---

**Status:** DONE
**Completion signal:** All 5 VMs producing valid NFS backups. Cron fires at 03:00 nightly.
