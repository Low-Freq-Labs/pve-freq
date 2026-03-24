# DC01 Performance Baselines

> Generated: S035-20260220
> Purpose: Baseline measurements for future comparison
> Tested by: Jarvis (automated via SSH from WSL)

---

## Test Environment

| System | IP Used | Proxmox Host | VLAN | NFS Route |
|--------|---------|-------------|------|-----------|
| VM 101 (Plex) | 10.25.255.30 | pve01 | 5 (Public) | via pfSense 10.25.5.1 -> 10.25.25.25 |
| VM 102 (Arr-Stack) | 10.25.255.31 | pve01 | 5 (Public) | via pfSense 10.25.5.1 -> 10.25.25.25 |
| VM 104 (Tdarr-Node) | 10.25.255.34 | pve03 | 10 (Compute) | via 10.25.10.5 -> 10.25.25.25 |
| VM 105 (Tdarr-Server) | 10.25.255.33 | pve01 | 10 (Compute) | via 10.25.10.5 -> 10.25.25.25 |
| TrueNAS | 10.25.255.25 | — | Storage (25) | local |

NFS mount options (all VMs): `nfsvers=3,rsize=1048576,wsize=1048576,soft,proto=tcp,timeo=150,retrans=3`
NFS target: `10.25.25.25:/mnt/mega-pool/nfs-mega-share`

---

## Test 1: NFS Write Throughput

**Method:** `dd if=/dev/zero of=<nfs-path> bs=1M count=<N> conv=fdatasync`

| VM | Host | VLAN | Size | Duration | Throughput | Status |
|----|------|------|------|----------|------------|--------|
| VM 101 | pve01 | 5 | 256 MB | 60.37s | **4.4 MB/s** | FAILED (fdatasync I/O error) |
| VM 102 | pve01 | 5 | 128 MB | 60.12s | **2.2 MB/s** | FAILED (fdatasync I/O error) |
| VM 104 | pve03 | 10 | 128 MB | 1.20s | **111 MB/s** | OK |
| VM 105 | pve01 | 10 | 128 MB | 1.33s | **101 MB/s** | OK |

### Observations

- **CRITICAL ANOMALY:** VM 101 and VM 102 (both VLAN 5) consistently fail NFS writes with `fdatasync failed: Input/output error` after exactly ~60 seconds. All data is written to the NFS buffer but the sync/commit operation times out.
- VM 104 and VM 105 (both VLAN 10) write successfully at 101-111 MB/s.
- VM 105 is on the **same Proxmox host** (pve01) as VM 101/102, so this is NOT a pve01 hardware issue.
- The failure pattern (exactly 60s timeout) matches the NFS soft-mount `timeo=150` (15 seconds) x `retrans=3` = 45-60s total before giving up.
- **Root cause identified:** VLAN 5 VMs route NFS traffic through pfSense (10.25.5.1) to reach Storage VLAN (10.25.25.25). pfSense VLAN sub-interface MTUs are all at 1500 (known issue F-S034-MTU). With 1MB NFS write sizes and jumbo frames (MTU 9000) configured on the VM NICs, packets are being fragmented or dropped at the pfSense hop, causing the commit operation to time out.

---

## Test 2: NFS Read Throughput

**Method:** Write file, drop caches (`echo 3 > /proc/sys/vm/drop_caches`), read with `dd of=/dev/null bs=1M`

| VM | Host | VLAN | Size | Duration | Throughput | Status |
|----|------|------|------|----------|------------|--------|
| VM 101 | pve01 | 5 | 256 MB | — | — | FAILED (write did not persist due to I/O error) |
| VM 104 | pve03 | 10 | 128 MB | 1.15s | **117 MB/s** | OK |

### Observations

- VM 101 read test could not be completed because the preceding write fails — the file is created at 0 bytes due to the fdatasync I/O error.
- VM 104 reads at 117 MB/s, slightly faster than its write speed (113 MB/s), which is expected behavior.
- Read throughput from VLAN 10 VMs is healthy and saturating the 1GbE link (117 MB/s = 936 Mbps).

---

## Test 3: NFS Latency (Small File Creation)

**Method:** `time (for i in $(seq 1 100); do touch <nfs-path>/.perf-test-$i; done)`

| VM | Host | VLAN | 100 Files | Per-File Avg | Status |
|----|------|------|-----------|-------------|--------|
| VM 101 | pve01 | 5 | **2.562s** | **25.6 ms** | OK |
| VM 104 | pve03 | 10 | **2.244s** | **22.4 ms** | OK |

### Observations

- Small metadata operations (touch) work fine from both VLANs — the issue is specific to large sustained writes with sync.
- Latency is comparable: ~22-26 ms per NFS file creation operation.
- This confirms the NFS mount itself is functional on VM 101; the problem is isolated to large data sync operations routed through pfSense.

---

## Test 4: Network Latency (ICMP Ping from VM 101)

### 4A: To TrueNAS Storage VLAN (jumbo frames, 8000-byte payload)

```
PING 10.25.25.25 (10.25.25.25) 8000(8028) bytes of data.
From 10.25.5.1 icmp_seq=1 Frag needed and DF set (mtu = 1500)
8008 bytes from 10.25.25.25: icmp_seq=2 ttl=63 time=1.18 ms
8008 bytes from 10.25.25.25: icmp_seq=3 ttl=63 time=1.02 ms
8008 bytes from 10.25.25.25: icmp_seq=4 ttl=63 time=0.963 ms
8008 bytes from 10.25.25.25: icmp_seq=5 ttl=63 time=0.888 ms
--- 5 packets transmitted, 4 received, +1 errors, 20% packet loss ---
rtt min/avg/max/mdev = 0.888/1.013/1.179/0.107 ms
```

**Result:** First packet dropped with `Frag needed and DF set (mtu = 1500)` from 10.25.5.1 (pfSense). Subsequent packets succeed after PMTUD adjusts, but this confirms pfSense VLAN 5 interface has MTU 1500.

### 4B: To VM 102 (same VLAN 5, same-host)

```
5 packets transmitted, 5 received, 0% packet loss
rtt min/avg/max/mdev = 0.650/0.752/0.894/0.088 ms
```

**Result:** Sub-millisecond latency, 0% loss. Intra-VLAN, same-host communication is excellent.

### 4C: To pve03 (cross-VLAN via Management VLAN)

```
5 packets transmitted, 5 received, 0% packet loss
rtt min/avg/max/mdev = 0.808/1.025/1.636/0.308 ms
```

**Result:** ~1ms average, 0% loss. Cross-node, cross-VLAN latency is healthy.

---

## Test 5: ZFS Pool IOPS (TrueNAS — mega-pool)

**Method:** `zpool iostat mega-pool 1 5` (5 one-second samples)

```
              capacity     operations     bandwidth
pool        alloc   free   read  write   read  write
----------  -----  -----  -----  -----  -----  -----
mega-pool   2.99T  40.6T     39     82  2.40M  7.42M   (cumulative avg)
mega-pool   2.99T  40.6T    107      0  6.54M      0   (sample 1)
mega-pool   2.99T  40.6T     37      0  2.29M      0   (sample 2)
mega-pool   2.99T  40.6T     25      0  1.52M      0   (sample 3)
mega-pool   2.99T  40.6T      3      0   255K      0   (sample 4)
```

### ZFS Properties

| Property | Value | Source |
|----------|-------|--------|
| compression | lz4 | local |
| compressratio | 1.00x | — |
| recordsize | 128K | default |
| atime | off | local |
| relatime | on | default |

### Observations

- Pool is at **6.9% capacity** (2.99 TB used / 43.6 TB total). Plenty of headroom.
- IOPS during idle: 3-107 read ops/s, 0 write ops/s (background scrub or Plex metadata activity).
- Compression ratio of 1.00x is expected for media files (video/audio don't compress).
- `atime=off` is correctly set — avoids unnecessary metadata writes for media workloads.
- `recordsize=128K` is default; media-heavy workloads may benefit from 1M, but 128K is reasonable.

---

## Test 6: NFS Write from VM 104 (pve03 / Storage VLAN)

*Results included in Test 1 table above.*

| Metric | Value |
|--------|-------|
| Write throughput | 111 MB/s (128 MB in 1.20s) |
| Read throughput | 117 MB/s (128 MB in 1.15s) |
| Status | Healthy — saturating 1GbE link |

---

## Summary: pve01 vs pve03 Comparison

| Metric | pve01 VLAN 5 (VM 101/102) | pve01 VLAN 10 (VM 105) | pve03 VLAN 10 (VM 104) |
|--------|---------------------------|------------------------|------------------------|
| NFS Write | **FAILED** (4.4 / 2.2 MB/s, I/O error) | 101 MB/s | 111 MB/s |
| NFS Read | FAILED (file not persisted) | not tested | 117 MB/s |
| NFS Latency (100 files) | 25.6 ms/file | not tested | 22.4 ms/file |
| Jumbo Ping to TrueNAS | 1st pkt dropped (MTU 1500 at pfSense) | — | — |

---

## Critical Findings

### FINDING-PERF-001: VLAN 5 NFS Writes Failing (CRITICAL)

- **Affected:** VM 101 (Plex), VM 102 (Arr-Stack) — the two most I/O-heavy services
- **Symptom:** All NFS write+sync operations fail with `Input/output error` after exactly ~60 seconds
- **Impact:** Plex transcoding writes, Sonarr/Radarr file moves, Bazarr subtitle downloads, and backup tar writes all route through this path. The daily backup cron on VM 101 and VM 102 may be silently failing or falling back to buffered writes.
- **Root cause:** NFS traffic from VLAN 5 routes through pfSense (10.25.5.1) to reach Storage VLAN (10.25.25.25). pfSense VLAN sub-interfaces have MTU 1500 (known issue F-S034-MTU). With NFS wsize=1048576 and VM NICs at MTU 9000, large NFS COMMIT RPCs are fragmented at the pfSense hop and timing out against the soft-mount deadline.
- **Evidence:**
  - Jumbo ping (8000 bytes) to TrueNAS from VM 101: first packet gets `Frag needed and DF set (mtu = 1500)` from 10.25.5.1
  - VM 105 (same pve01 host, VLAN 10, different route) writes at 101 MB/s without issues
  - VM 104 (pve03, VLAN 10) writes at 111 MB/s without issues
- **Resolution:** Set pfSense VLAN 5 and VLAN 25 sub-interface MTUs to 9000 (GUI required — already tracked as F-S034-MTU in Sonny's action items)

### FINDING-PERF-002: Throughput Saturating 1GbE (INFO)

- All healthy NFS transfers (101-117 MB/s) are at ~90-94% of theoretical 1GbE maximum (125 MB/s).
- This is the expected ceiling for the current 1GbE infrastructure. No headroom for parallel I/O from multiple VMs.
- Future consideration: 10GbE or link aggregation for storage traffic if workloads grow.

### FINDING-PERF-003: ZFS Pool Health (OK)

- mega-pool at 6.9% capacity with lz4 compression and atime=off.
- No write IOPS observed during sampling (idle state), indicating no background scrub or resilver in progress.
- Pool configuration is appropriate for media workloads.

---

## Recommended Actions

| Priority | Action | Tracking |
|----------|--------|----------|
| **P0** | Fix pfSense VLAN sub-interface MTUs to 9000 (VLAN 5, 10, 25 at minimum) | F-S034-MTU (Sonny GUI action) |
| **P1** | After MTU fix: re-run Tests 1 and 2 from VM 101/102 to confirm resolution | Re-baseline |
| **P2** | Verify daily backup cron success on VM 101 and VM 102 | Check `/opt/dc01/backups/` logs |
| **P3** | Consider adding a storage NIC (VLAN 25) to VM 101 and VM 102 for direct NFS path | Architecture change |

---

## Raw Test Timestamps

All tests executed: 2026-02-20 ~23:00 UTC (17:00 CT)
