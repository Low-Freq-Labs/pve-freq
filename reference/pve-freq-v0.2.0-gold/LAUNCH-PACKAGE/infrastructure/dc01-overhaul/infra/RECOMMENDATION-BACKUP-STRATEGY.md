# DC01 Backup Strategy Recommendation

> Generated: S035-20260220
> Priority: P3
> Status: Recommendation — Awaiting Sonny Review

---

## Current State

- **Config backups only:** Daily cron at 03:00 on all 5 VMs. Tar archives to local + NFS (`media/config-backups/<hostname>/`). 7-day NFS retention, 3-day local.
- **No VM-level backups.** If a VM disk dies or gets corrupted, full rebuild from scratch.
- **No Proxmox Backup Server (PBS).**
- **No offsite copies of anything.**

### What's at Risk

| Scenario | Current Recovery | With PBS |
|----------|-----------------|----------|
| Docker config corruption | Restore from NFS tar (minutes) | Same, plus full VM rollback |
| VM disk failure | Full OS reinstall + reconfigure (hours) | Restore VM from backup (minutes) |
| pve01 total loss (single PSU!) | Rebuild everything (days) | Restore all VMs to pve03 or replacement (hours) |
| TrueNAS pool loss | **Unrecoverable** — 22TB gone | Still gone unless offsite exists |
| Accidental `rm -rf` on NFS media | **Unrecoverable** | Still gone unless ZFS snapshots or offsite |

The Docker config backups are good for what they do, but they only protect container configs. The OS, packages, network config, cron jobs, sysctl tuning, mount points, Docker itself — none of that is backed up.

---

## 1. Where to Deploy PBS

**Recommendation: Dedicated VM on pve03 (VM ID 106).**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Bare metal on pve03 | Best performance | Destroys the Proxmox node, single-purpose machine | No |
| LXC container on pve03 | Lightweight | PBS needs kernel-level access for dedup, containers complicate this | No |
| VM on pve01 | Close to the VMs it backs up | pve01 is on a single PSU — if it dies, backups die with it | No |
| **VM on pve03** | Separate hardware from pve01, PBS runs clean in a VM, Proxmox natively integrates | Uses some of pve03's 32GB RAM | **Yes** |

Why pve03: The whole point of backups is surviving hardware failure. pve01 (T620) is running on a single PSU and hosts all production VMs. Putting PBS on pve03 means a pve01 failure doesn't also take out your backups.

### VM Spec for PBS (VM 106)

| Resource | Value | Rationale |
|----------|-------|-----------|
| CPU | 2 vCPUs | PBS is I/O-bound, not CPU-bound (except during dedup/GC) |
| RAM | 4 GB | Sufficient for PBS with 5 VMs. Dedup index needs ~1GB per TB of dedup data |
| OS Disk | 16 GB (on os-drive-ssd) | PBS OS is minimal |
| Backup Storage | See Section 2 | Separate disk/mount for actual backup data |
| Network | Management VLAN (.255.X) | Proxmox API communication |
| Name | `PBS-Backup` | Following DC01 naming convention |
| IP | 10.25.255.35 (Management) | Next available in our .25-.50 range |

---

## 2. Storage Requirements

### How Much Space Do We Need?

Current VM disk allocations (estimated):
- VM 101 (Plex): ~32GB OS + configs
- VM 102 (Arr-Stack): ~32GB OS + configs
- VM 103 (qBit): ~32GB OS + configs
- VM 104 (Tdarr-Node): ~32GB OS + configs
- VM 105 (Tdarr-Server): ~32GB OS + configs
- **Total raw:** ~160GB

PBS uses dedup and compression. Typical reduction is 40-60% for similar Debian/Ubuntu VMs. With incremental backups, subsequent backups are much smaller (only changed blocks).

**Estimated storage need:** 200-300GB for 4 weeks of daily backups with dedup.

### Where to Store Backups

**Recommendation: NFS-backed datastore on TrueNAS.**

| Option | Pros | Cons |
|--------|------|------|
| Local disk on pve03 | Fast, simple | pve03 only has a single SSD; limited space |
| **NFS on TrueNAS** | 22TB pool with 20TB free, ZFS checksums, expandable | Network-dependent, slower than local |
| iSCSI on TrueNAS | Better performance than NFS for block storage | More complex setup |

TrueNAS has 20+ TB free. NFS is already proven in the environment. PBS handles NFS datastores well.

**TrueNAS setup:**
- Create a dedicated dataset: `mega-pool/pbs-backups` (separate from media, own quota)
- Set quota: 500GB initially (generous headroom)
- NFS export to pve03 PBS VM only (tight ACL)
- Mount in PBS VM at `/mnt/pbs-storage`

**Important:** This means backups live on TrueNAS alongside the data. If TrueNAS dies, both are gone. See Section 6 for offsite considerations.

---

## 3. Retention Policy

**Recommendation: Keep it simple, expand later.**

| Retention | Value | What This Means |
|-----------|-------|-----------------|
| Daily (keep-daily) | 7 | Last 7 days of daily backups |
| Weekly (keep-weekly) | 4 | Last 4 Saturday backups |
| Monthly (keep-monthly) | 2 | Last 2 first-of-month backups |

**Total retention window:** ~2 months of rollback capability.

This is conservative on storage. With dedup, 7 dailies + 4 weeklies + 2 monthlies for 5 small VMs will likely use 150-250GB.

The existing Docker config backup cron (7-day NFS, 3-day local) stays exactly as-is. It's faster for "I just need to restore a Sonarr config" scenarios. PBS is for "the whole VM is toast" scenarios.

---

## 4. Backup Schedule

**Current:** Docker config backup cron fires at 03:00 on all 5 VMs.

**Recommendation:** PBS backups at 04:00, staggered by VM.

| Time | What |
|------|------|
| 03:00 | Existing Docker config backup (all VMs, ~2-3 min each) |
| 03:15 | Config backups complete, NFS write load settles |
| 04:00 | PBS: VM 101 (Plex) |
| 04:20 | PBS: VM 102 (Arr-Stack) |
| 04:40 | PBS: VM 103 (qBit) |
| 05:00 | PBS: VM 104 (Tdarr-Node) |
| 05:20 | PBS: VM 105 (Tdarr-Server) |

Why stagger: All 5 VMs are on pve01. Running them all at once would hammer the NFS link and local I/O. 20-minute gaps let each backup complete before the next starts. First full backup will be slower; incrementals after that are fast (minutes, not tens of minutes).

PBS schedules are configured in the Proxmox GUI (Datacenter > Storage > PBS datastore > Backup Jobs). No cron files needed.

---

## 5. What to Back Up

**Recommendation: Full VM backups via PBS. Keep existing config backups too.**

| Layer | Tool | What It Covers |
|-------|------|----------------|
| Docker configs | Existing cron/tar | Service configs only. Fast restore for app-level issues |
| **Full VM** | **PBS** | OS, packages, network, Docker, configs, everything. Full disaster recovery |

### Backup Mode

PBS supports three modes:

| Mode | Speed | Consistency | Downtime |
|------|-------|-------------|----------|
| Snapshot | Fast | Good (uses QEMU dirty bitmap) | None |
| Suspend | Medium | Perfect | Brief pause |
| Stop | Slow | Perfect | Full downtime |

**Recommendation: Snapshot mode.** Zero downtime, and these VMs don't run databases that need quiesced I/O. Docker containers with config files on ext4 are fine with snapshot-consistent backups.

### What NOT to Back Up

- **NFS media data** (movies, TV shows, downloads) — this is on TrueNAS, not in the VMs. PBS backs up VM disks only. Media protection is a separate concern (ZFS snapshots, offsite replication).
- **VM 100 (SABnzbd on pve02)** — out of scope per existing rules.
- **VMs 800-899** — not ours.

---

## 6. Offsite / Replication Considerations

**Current risk:** TrueNAS holds ALL data AND all backups (if we put PBS storage on NFS). Single PSU, failed fan. If TrueNAS dies, everything dies.

### Tiered approach (implement in order of priority):

**Tier 1 — ZFS Snapshots (Do Now, Free)**
- Enable automated ZFS snapshots on TrueNAS for `mega-pool/pbs-backups` and `mega-pool/nfs-mega-share`
- Periodic snapshots protect against accidental deletion and ransomware
- This is a TrueNAS GUI task (Periodic Snapshot Tasks)
- **Does NOT protect against hardware failure**

**Tier 2 — USB/External Drive (Do Soon, Cheap)**
- Periodic manual copy of PBS datastore to an external USB drive
- Plug into TrueNAS or pve03, rsync the PBS datastore
- Even monthly is better than nothing
- Cost: $50-80 for a 1TB external drive

**Tier 3 — Offsite Replication (Do Later, Requires Planning)**
- PBS supports native datastore sync to a remote PBS instance
- Could be a small box at home, at GigeNet's office, or a cloud VPS
- Requires stable network link and a second PBS installation
- This is the real disaster recovery play but needs more infrastructure

**Recommendation for now:** Tier 1 (ZFS snapshots) immediately — it's free and takes 5 minutes in the TrueNAS GUI. Tier 2 when Sonny can grab an external drive. Tier 3 is a future project.

---

## 7. Implementation Steps

### Phase A: TrueNAS Prep (15 min)

1. TrueNAS GUI: Create dataset `mega-pool/pbs-backups`
   - Quota: 500GB
   - Compression: lz4 (default)
   - Record size: 128K (good for large sequential writes)
2. Create NFS share for `pbs-backups`
   - Mapall User: `svc-admin`
   - Mapall Group: `truenas_admin`
   - Authorized Networks: `10.25.255.35/32` (PBS VM only) or `10.25.10.0/24` if using Compute VLAN
3. Enable periodic ZFS snapshots on `pbs-backups` dataset (daily, 30-day retention)

### Phase B: PBS VM Creation (30 min)

1. Download PBS ISO from https://www.proxmox.com/en/downloads (Proxmox Backup Server)
2. Upload ISO to pve03 local storage
3. Create VM 106 on pve03:
   - Name: `PBS-Backup`
   - CPU: 2 cores, type: host
   - RAM: 4096 MB
   - Disk: 16 GB on os-drive-ssd
   - Network: vmbr0, VLAN tag 2550 (Management)
   - IP: 10.25.255.35/24, GW: 10.25.255.1
4. Install PBS from ISO (standard install, takes ~5 minutes)
5. Access PBS web UI: `https://10.25.255.35:8007`

### Phase C: Storage & Datastore Config (15 min)

1. In PBS VM: mount NFS share
   ```
   mkdir -p /mnt/pbs-storage
   # Add to /etc/fstab:
   10.25.25.25:/mnt/mega-pool/pbs-backups /mnt/pbs-storage nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3 0 0
   mount /mnt/pbs-storage
   ```
2. PBS GUI: Add Datastore
   - Name: `dc01-backups`
   - Backing Path: `/mnt/pbs-storage`
3. Configure retention: keep-daily=7, keep-weekly=4, keep-monthly=2
4. Configure garbage collection: daily at 06:00 (after all backups complete)
5. Configure verification: weekly, check one backup per job

### Phase D: Proxmox Integration (15 min)

1. pve01 GUI: Datacenter > Storage > Add > Proxmox Backup Server
   - ID: `pbs-dc01`
   - Server: `10.25.255.35`
   - Datastore: `dc01-backups`
   - Username: `root@pam` (or create a dedicated backup user)
   - Fingerprint: (shown in PBS GUI under Dashboard)
2. Repeat on pve03 (for VM 104 backups)
3. Create backup jobs:
   - Datacenter > Backup > Add
   - Storage: `pbs-dc01`
   - Schedule: Per the schedule in Section 4
   - Mode: Snapshot
   - VMs: Select individually (101, 102, 103, 104, 105)
   - Retention: Use datastore defaults
   - Notification: Email (configure SMTP in Datacenter > Options > Email)

### Phase E: Verify (15 min)

1. Run a manual backup of the smallest VM first (VM 104 or 105)
2. Verify it shows up in PBS GUI under Datastore > Content
3. Test restore: create a temporary VM from the backup, boot it, verify it works, delete it
4. Run one full backup cycle of all 5 VMs
5. Check dedup ratio in PBS GUI (Dashboard > Dedup Factor)

**Total estimated time: ~90 minutes** for a fully working PBS with all 5 VMs backed up.

---

## 8. Estimated Resource Requirements

### PBS VM Resources (Ongoing)

| Resource | Idle | During Backup Window |
|----------|------|---------------------|
| CPU | Negligible | 1-2 cores active (dedup, compression) |
| RAM | ~1 GB used | ~2-3 GB (dedup index loaded) |
| Network | Negligible | 50-200 Mbps bursts per VM backup |
| NFS I/O | Negligible | Sequential writes during backup, reads during GC/verify |

### Storage Growth (Estimated)

| Timeframe | Estimated Usage | Notes |
|-----------|----------------|-------|
| First full backup | ~80-100 GB | All 5 VMs, compressed + deduped |
| After 1 week | ~120-150 GB | 7 incrementals are small (few GB each) |
| After 1 month | ~180-250 GB | Weeklies and monthly add up slowly |
| Steady state | ~200-300 GB | With retention pruning and GC |

500GB quota on TrueNAS gives plenty of headroom.

### Impact on Existing Systems

| System | Impact |
|--------|--------|
| pve01 | Snapshot I/O during backup window (04:00-06:00). Minimal — VMs continue running |
| pve03 | PBS VM uses 4GB RAM from 32GB total. VM 104 (Tdarr-Node) unaffected |
| TrueNAS | Additional NFS traffic during backup window. With 20TB free, storage is not a concern |
| Network | Backup traffic on Management VLAN. 1GbE links are sufficient for 5 small VMs |

---

## Summary

| Item | Recommendation |
|------|---------------|
| Deployment | VM 106 on pve03, 2 vCPU / 4GB RAM / 16GB disk |
| Storage | NFS-backed on TrueNAS (`mega-pool/pbs-backups`, 500GB quota) |
| Retention | 7 daily / 4 weekly / 2 monthly |
| Schedule | 04:00-06:00 daily, staggered 20 min per VM |
| Backup scope | Full VM snapshots (all 5 VMs) + keep existing config cron |
| Offsite | ZFS snapshots now, USB drive soon, remote PBS later |
| Time to implement | ~90 minutes |
| Ongoing cost | 4GB RAM on pve03, 200-300GB on TrueNAS |
