# FIX-S034: Backup Seed — First Manual Backup Run

**Session:** S034
**Date:** 2026-02-20 20:05 CST
**Operator:** Jarvis (automated)

## Objective

Manually run `/opt/dc01/backups/backup.sh` on all 5 Plex stack VMs to seed the first backup. The daily cron (03:00) hadn't fired yet since deployment.

## Execution Summary

| VM | Host | IP | Tarball | Local Size | NFS Copy | Status |
|----|------|----|---------|------------|----------|--------|
| 101 | plex | 10.25.255.30 | dc01-configs-20260220-2005.tar.gz | 195M | YES | OK |
| 102 | arr-stack | 10.25.255.31 | dc01-configs-20260220-2005.tar.gz | 50M | YES | OK (tar warning: huntarr config changed during read — non-fatal) |
| 103 | qbit | 10.25.255.32 | dc01-configs-20260220-2005.tar.gz | 5.6M | YES | OK (socket file ignored — expected) |
| 104 | tdarr-node | 10.25.255.34 | dc01-configs-20260220-2005.tar.gz | 15K | YES | OK |
| 105 | tdarr | 10.25.255.33 | dc01-configs-20260220-2005.tar.gz | 6.3M | YES | OK |

**Total NFS backup footprint:** ~257M across 5 VMs.

## Issues Encountered & Resolved

### NFS Write Failures (Transient)

**Problem:** Initial parallel backup runs on all 5 VMs simultaneously caused NFS I/O errors on `cp` (close syscall). The `set -euo pipefail` in the backup script caused immediate exit on failure. VM 101's soft NFS mount (`soft,timeo=150,retrans=3`) dropped entirely after repeated failures.

**Root cause analysis:**
- ZFS pool healthy (ONLINE, no errors, 6% used, 19.6T available)
- NFS server healthy (24 threads, 9M+ calls, no bad calls)
- NFS dataset: rw, no quota, all_squash with anonuid=3003/anongid=950
- Local writes on TrueNAS: 755 MB/s — no issue
- Small NFS writes (4KB–50MB): Success at 92 MB/s
- Large NFS writes (100MB–200MB): Success at 107 MB/s when run individually
- Jumbo frame ping (MTU 9000) from VM VLAN 5 to TrueNAS VLAN 25 fails — but NFS still works with TCP fragmentation
- **Conclusion:** Transient NFS overload from 5 simultaneous large writes. Not a persistent issue.

**Resolution:**
1. Lazy-unmounted stale NFS on affected VMs (`sudo umount -l`)
2. Remounted fresh (`sudo mount /mnt/truenas/nfs-mega-share`)
3. Ran backups sequentially (one VM at a time) — all succeeded

### Stale NFS Directories

Old hostname-based directories exist on NFS from earlier deployment attempts:
- `plex-server/` — empty (old name for VM 101)
- `qbit-downloader/` — empty (old name for VM 103)
- `tdarr-server/` — empty (old name for VM 105)

Current correct directories: `plex/`, `arr-stack/`, `qbit/`, `tdarr-node/`, `tdarr/`

**Action:** Low priority cleanup. Can be removed anytime.

## Verification

### NFS Backup Directory Listing (from VM 101)
```
/mnt/truenas/nfs-mega-share/media/config-backups/
├── arr-stack/    → 1 tarball (50M)
├── plex/         → 2 tarballs (195M each)
├── qbit/         → 3 tarballs (5.6M each)
├── tdarr/        → 3 tarballs (6.3M each)
└── tdarr-node/   → 2 tarballs (14-15K each)
```

### Tarball Integrity (spot check — VM 101)
```
tar tzf dc01-configs-20260220-2005.tar.gz → 2,279 files
Contents: configs/plex/Library/Application Support/Plex Media Server/...
Status: VALID
```

### Local Backup Retention
All VMs have local copies at `/opt/dc01/backups/`. 3-day local retention, 7-day NFS retention enforced by the script's `find -mtime` pruning.

## Observation: Jumbo Frame Issue

Jumbo frame (MTU 9000) pings from VM 101 (VLAN 5, 10.25.5.30) to TrueNAS (VLAN 25, 10.25.25.25) fail — 100% packet loss. Standard pings work fine. This indicates a potential MTU mismatch on the inter-VLAN path (pfSense gateway at 10.25.5.1). NFS operates over TCP so it fragments successfully, but this is worth investigating for performance optimization.

**Not blocking.** NFS reads/writes work fine via TCP fragmentation.

## DONE
