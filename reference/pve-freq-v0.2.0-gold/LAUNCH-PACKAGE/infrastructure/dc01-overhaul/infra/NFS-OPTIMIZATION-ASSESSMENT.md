# DC01 NFS Mount Optimization Assessment

> Generated: S035-20260220
> Priority: P3
> Status: Assessment Complete — No Changes Required

---

## Current State (All 5 VMs)

| Parameter | Value | Optimal? |
|-----------|-------|----------|
| NFS Version | NFSv3 | Yes — intentional. NFSv3 avoids complex locking, adequate for media workload |
| Protocol | TCP (data), UDP (mount) | Yes — standard |
| rsize/wsize | 1048576 (1 MB) | **Yes — already optimal** for MTU 9000 jumbo frame environment |
| Mount type | soft | Yes — intentional (S032). Returns I/O error instead of D-state hang |
| Timeout | timeo=150 (15s) | Yes — prevents hung processes on NFS outage |
| Retries | retrans=3 | Yes — balanced between reliability and hang avoidance |
| Background | bg | Yes — boot completes even if NFS is unavailable |
| Network dependency | _netdev,nofail | Yes — mandatory (Lesson #3) |
| Sysctl tuning | 16 MB rmem/wmem max, 1 MB defaults | Yes — matched to rsize/wsize |

## Optimization Options Evaluated

### nconnect (Multiple TCP Connections)
- **Verdict: NOT APPLICABLE**
- `nconnect` is an NFSv4.1+ feature only. Our environment uses NFSv3 intentionally.
- Upgrading to NFSv4.1 would introduce lock manager complexity that previously caused SQLite corruption and D-state hangs (Lesson #6). Not recommended for this workload.

### rsize/wsize Tuning
- **Verdict: ALREADY OPTIMAL**
- Current 1 MB (1048576) is the standard maximum for NFSv3.
- For MTU 9000: each NFS operation = ~114 jumbo packets. This is well-suited for sequential media reads (Plex streaming, Tdarr transcoding) and bulk downloads (qBittorrent).
- Increasing beyond 1 MB has no effect on NFSv3 — the kernel caps at 1048576.

### actimeo (Attribute Caching)
- **Verdict: NO CHANGE NEEDED**
- Default attribute caching (3-60 seconds) is appropriate. Media files are written once and read many times.
- Arr stack services write download completion markers which benefit from prompt attribute cache expiry. Current defaults handle this.

### noatime
- **Verdict: MINOR — LOW PRIORITY**
- Adding `noatime` to fstab would reduce NFS metadata writes by skipping access time updates on reads.
- Impact: Minimal for our workload (Plex already uses its own DB for access tracking). Would save a few IOPS during library scans.
- Not urgent — current performance is adequate.

## Inconsistencies Found

| Item | VMs Affected | Severity | Action |
|------|-------------|----------|--------|
| NFS target IP | VM 103 uses 10.25.255.25 (Mgmt VLAN) | **Known issue** | Needs storage NIC (Sonny GUI task). No CLI fix. |
| x-systemd.mount-timeout=infinity | VMs 102, 103 (active mount only) | Cosmetic | Not in fstab. Self-resolves on next clean reboot. |
| Tdarr :latest tags | VMs 104, 105 | **Known exception** | Tdarr ghcr.io has no semver tags. Documented. |
| VM 103 memory pressure | 4 GB total, 142 MB free (3.3 GB available) | Monitor | Not NFS-related but tightest allocation. |

## Conclusion

**No NFS mount changes recommended.** The current configuration is well-optimized:
- rsize/wsize at kernel maximum for NFSv3
- Sysctl buffers properly matched
- Mount options hardened for reliability (soft/timeo/retrans/bg)
- Consistent across all 5 VMs
- Only gap is VM 103 using management VLAN for NFS (requires hardware change)

The single largest potential improvement would be adding a storage VLAN NIC to VM 103, which would move its NFS traffic from the shared management network to the dedicated storage VLAN. This is a Sonny GUI task in Proxmox.
