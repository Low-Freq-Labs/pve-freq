# Worker #4 — Performance & Tuning Engineer — Memory Notes
> Session 25 (2026-02-20) — FRESH REBUILD
> Source: All memory files read (LOCAL-FIRST, SMB-FALLBACK)

---

## SECTION 1 — What I Read (LOCAL vs SMB)

| File | Source | Found |
|------|--------|-------|
| CLAUDE.md | SMB (symlink) | YES |
| DC01.md | SMB | YES |
| Sonny-Homework-OutOfScope.md | SMB | YES |
| TASKBOARD.md | LOCAL | YES |
| ARCHITECTURE.md | LOCAL (~/dc01-overhaul/infra/) | YES |
| tuning/TUNING-PLAYBOOK.md | LOCAL | YES |
| tuning/WORKER1-NOTES.md | LOCAL | YES |
| CONSOLIDATED-FINDINGS.md | LOCAL | YES |

SMB Status: MOUNTED and accessible.

---

## SECTION 2 — Current DC01 State (Performance Focus)

### Network Performance
- **Core switch (Cisco 4948E-F):** MTU 9198 on all ports. Jumbo frames enabled end-to-end from switch to storage.
- **pfSense lagg0:** MTU 1500 — **BOTTLENECK.** Should be 9000. This limits all tagged VLAN traffic through pfSense to standard frames. Affects NFS performance for VMs routing through pfSense.
- **pve01 interfaces:** vmbr0=9000, vmbr1=9000, vmbr1.25=9000, vmbr0v2550=9000. Properly configured.
- **pve03 interfaces:** vmbr0=9000, but vmbr0v2550 has MTU mismatch (bridge=9000, underlying nic0.2550=1500). Management VLAN only — does not affect storage performance.
- **LAGG status:** FAILOVER mode with 2 members. LACP would provide 2Gbps aggregate bandwidth. Currently limited to 1Gbps active link.
- **Storage VLAN 25:** Dedicated NIC on pve01 (vmbr1→Gi1/9). pve03 uses trunk (vmbr0v25 via Gi1/2). TrueNAS LACP bond via Po1 (Gi1/8+Gi1/11).

### Storage Performance
- **ZFS pool (mega-pool):** 8x 6TB SAS on PERC H730P in JBOD mode. Raidz2 (assumed from DC01.md disk count). ~22TB usable.
- **NFS export:** /mnt/mega-pool/nfs-mega-share. Mounted on all VMs at /mnt/truenas/nfs-mega-share.
- **NFS mount options:** Standard (need verification of rsize/wsize, hard/soft, nconnect settings).
- **Known NFS issue:** SQLite on NFS is unreliable — Bazarr, Huntarr, Agregarr configs moved to local /opt/.
- **Known NFS issue:** VM 104 experienced stale NFS mount (D-state processes, Session 22). Root cause: NFS server timeout or network blip. Recovered after VM reboot.

### VM Resource Allocation
| VM | CPU | RAM | Storage Path | GPU |
|----|-----|-----|-------------|-----|
| 101 Plex | TBD | TBD | NFS | Intel iGPU (passthrough /dev/dri) |
| 102 Arr-Stack | TBD | TBD | NFS + local /opt/ | None |
| 103 qBit-Downloader | TBD | TBD | NFS + local CONFIG_DIR | None |
| 104 Tdarr-Node | TBD | TBD | NFS | Radeon RX580 |
| 105 Tdarr-Server | TBD | TBD | NFS | None |

(Exact CPU/RAM allocations need verification from Proxmox API or qm config)

### Key Performance Metrics (Unmeasured)
- NFS throughput (no baseline established)
- ZFS IOPS (no baseline established)
- Plex transcode performance (no baseline)
- Tdarr encode throughput (no baseline)
- Network throughput per VLAN (no baseline)

---

## SECTION 3 — Open Risks / Known Issues (Performance)

1. **HIGH: pfSense lagg0 MTU=1500.** All inter-VLAN traffic through pfSense limited to standard frames. NFS traffic from VMs through pfSense gateway will fragment at 1500. Should be 9000.
2. **HIGH: FAILOVER mode limits bandwidth.** Only igc3 active = 1Gbps. LACP would provide 2Gbps aggregate. LACP cutover pending.
3. **MEDIUM: No performance baselines exist.** Cannot measure improvement or degradation without baseline metrics. Need: NFS throughput, ZFS IOPS, network bandwidth per VLAN.
4. **MEDIUM: NFS mount options not optimized.** Default mount options may not include: nconnect (parallel connections), rsize/wsize tuning, hard mounts. Need verification.
5. **MEDIUM: pve03 single NIC.** All traffic (storage, management, VM, corosync) shares one 1GbE link through Gi1/2. Potential bottleneck for Tdarr Node (104) which does heavy media reads/writes.
6. **LOW: Plex transcode uses local /tmp.** Good for performance (avoids NFS for ephemeral data). Verify /tmp has adequate space.
7. **LOW: No NUMA pinning documented.** Both servers are dual-socket. VM placement relative to NUMA nodes may affect memory access latency.

---

## SECTION 4 — Out-of-Scope Areas

- pve02 (10.25.0.27) — entirely out of scope
- VM 100 (SABnzbd) — Sonny's homework
- VMs 800-899 — not ours, do not touch
- GigeNet client systems — only when explicitly client-scoped
- Worker #4 provides tuning recommendations. Infra changes executed by Worker #1.

---

## SECTION 5 — My Immediate Responsibilities This Session

1. **LACP performance impact assessment.** If LACP cutover happens, document: expected bandwidth improvement (1G→2G aggregate), any latency changes, hashing algorithm impact on traffic distribution.
2. **MTU fix monitoring.** If lagg0 MTU is changed to 9000, verify end-to-end jumbo frame path and measure NFS throughput before/after.
3. **Establish performance baselines** if Sonny directs. Priority: NFS throughput (iperf3 or dd), ZFS IOPS (fio), network per-VLAN bandwidth.
4. **Review NFS mount options** on all VMs. Recommend optimizations if suboptimal.
5. **Maintain tuning/TUNING-PLAYBOOK.md** and tuning/WORKER1-NOTES.md with any new findings.

---

## SESSION LOG

Session 19 – Planned: Initial tuning assessment / Done: TUNING-PLAYBOOK.md + WORKER1-NOTES.md written
Session 21 – Planned: LACP performance prep / Done: Memory rebuilt
Session 22 – Planned: Phase 0-4 performance review / Done: Memory rebuilt
Session 24 – Planned: Phase 5 performance artifacts / Done: Memory rebuilt
Session 25 – Planned: Startup, LACP/MTU prep / Done: Memory rebuilt. Pre-change baseline captured (switch 0.6ms, TrueNAS 0.2ms, pve01 0.2ms from pfSense). / Next: After LACP, compare latencies. Verify MTU 9000 end-to-end. Measure NFS throughput.
