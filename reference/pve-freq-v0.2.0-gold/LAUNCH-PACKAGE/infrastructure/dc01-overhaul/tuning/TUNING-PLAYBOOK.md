# DC01 Performance Tuning Playbook

> **Author:** Worker #4 (Performance & Tuning Engineer)
> **Date:** 2026-02-19
> **Scope:** DC01 cluster -- pve01 (10.25.0.26), pve03 (10.25.0.28), TrueNAS R530 (10.25.0.25)
> **Companion document:** WORKER1-NOTES.md (specific tuning recommendations)
> **Ground truth:** DC01.md Session 18 rewrite

This playbook provides a reproducible, step-by-step methodology for measuring, tuning, and validating DC01's performance. Every command is real and runnable on the actual DC01 hardware. Every measurement has context for what "normal" looks like.

---

## 1. Baseline Assumptions

### 1.1 Hardware

| System | Hardware | CPU | RAM | Storage | NICs |
|---|---|---|---|---|---|
| TrueNAS | Dell R530 | 2x Xeon E5-2620 v3 (6c/12t, 2.4 GHz) | 88 GB (mixed DIMMs) | 8x 6 TB HGST SAS, PERC H730P JBOD | 4x BCM5720 1 GbE |
| pve01 | Dell T620 | 2x Xeon E5-2620 v0 (6c/12t, 2.0 GHz) | 256 GB | Local ZFS (os-pool-hdd) | 2x Intel I350 1 GbE |
| pve03 | Asus B550-E | Consumer AMD (details undocumented) | 31 GB | Local SSD (os-drive-ssd) | 1x 1 GbE (single NIC) |

### 1.2 Hardware Alerts (Active)

| System | Alert | Impact on Tuning |
|---|---|---|
| TrueNAS | PSU 1 FAILED, Fan 6 DEAD | Thermal throttling risk. Monitor temps before increasing workload. |
| pve01 | PSU 2 FAILED | Single PSU. Increased compute load = higher power draw on one rail. |

### 1.3 Network Topology

```
                     Cisco WS-C4948E-F (10.25.0.5)
                     MTU 9198 system-wide
                     +-----------+
    Gi1/1 (trunk)    |           |  Gi1/9 (trunk)
    pve01 nic0 ------+           +------ pve01 nic1
    (vmbr0, VMs)     |           |  (vmbr1, storage)
                     |           |
    Gi1/2 (trunk)    |           |  Gi1/8+Gi1/11 = Po1 (LACP, access VLAN 25)
    pve03 nic0 ------+           +------ TrueNAS bond0 (eno2+eno3)
    (everything)     |           |       10.25.25.25, MTU 9000
                     |           |
    Gi1/10 (trunk)   |           |  Gi1/7 (access 2550)
    TrueNAS eno1 ----+           +------ TrueNAS eno4
    10.25.0.25       |           |       10.25.255.25, MTU 1500
                     |           |
    Gi1/48 (trunk)   |           |
    pfSense fw01 ----+           |
    10.25.0.1        +-----------+
```

### 1.4 Storage Layout

```
TrueNAS ZFS Pool: mega-pool
  +-- RAIDZ2 vdev 1 (4x 6TB HGST SAS)
  +-- RAIDZ2 vdev 2 (4x 6TB HGST SAS)
  Capacity: ~22 TB total, ~740 GB used (4%)
  No SLOG, no L2ARC

Datasets:
  mega-pool/nfs-mega-share  -> /mnt/mega-pool/nfs-mega-share  (primary NFS share)
  mega-pool/ha-proxmox-disk -> /mnt/mega-pool/ha-proxmox-disk (HA storage)
  mega-pool/smb-share       -> /mnt/mega-pool/smb-share       (SMB)
```

### 1.5 NFS Traffic Paths

| Client | TrueNAS IP | TrueNAS Interface | Path MTU | Notes |
|---|---|---|---|---|
| pve01 host | 10.25.25.25 | bond0 (VLAN 25) | 9000 | Dedicated storage NIC (nic1/vmbr1.25) |
| pve03 host | 10.25.25.25 | bond0 (VLAN 25) | 9000 | Shared NIC (vmbr0.25 on nic0) |
| VM 101 (Plex) | 10.25.0.25 | eno1 (VLAN 1) | 9000 | Via static route on VM |
| VM 102 (Arr) | 10.25.0.25 | eno1 (VLAN 1) | 9000 | Via static route on VM |
| VM 103 (qBit) | 10.25.255.25 | eno4 (VLAN 2550) | 1500 | Dirty VLAN isolation path |
| VM 104 (Tdarr Node) | 10.25.0.25 | eno1 (VLAN 1) | 9000 | Via TrueNAS static route for return |
| VM 105 (Tdarr Server) | 10.25.0.25 | eno1 (VLAN 1) | 9000 | Light I/O |

### 1.6 Current NFS Mount Options

All VMs use:
```
nfsvers=3,_netdev,nofail,defaults
```
No explicit rsize, wsize, nconnect, hard, timeo, or retrans.

### 1.7 Workload Profile

| VM | Primary Workload | I/O Pattern | Peak Bandwidth | Concurrency |
|---|---|---|---|---|
| 101 (Plex) | Media streaming | Large sequential reads | ~40 Mbps per 1080p stream | 1-5 concurrent streams |
| 102 (Arr) | Media management | Mixed small metadata + large file moves | Bursty | Low |
| 103 (qBit) | Download to NFS | Large sequential writes | Up to link speed | 5-50 concurrent torrents |
| 104 (Tdarr Node) | GPU transcode | Read source + write output (sequential) | ~100-300 Mbps combined | 1-2 concurrent jobs |
| 105 (Tdarr Server) | Coordination | Minimal NFS I/O | Negligible | N/A |

---

## 2. Baseline Measurement Commands

Run ALL baseline measurements BEFORE making any tuning changes. Record outputs in a timestamped log file.

### 2.1 NFS Performance

#### 2.1a. Check Current NFS Mount Options (All VMs)

**Run on:** Each VM (101-105) via SSH through pve01 jump host or Proxmox guest agent API

```bash
# Show current mount options
mount -t nfs
# Expected output:
# 10.25.0.25:/mnt/mega-pool/nfs-mega-share on /mnt/truenas/nfs-mega-share type nfs (rw,relatime,vers=3,...)

# Detailed mount statistics (NFSv3)
nfsstat -m
# Shows: rsize, wsize, hard/soft, timeo, retrans, server IP, mount path
# "Normal" for current config: rsize=1048576, wsize=1048576 (if kernel negotiated max)
# or rsize=65536, wsize=65536 (if negotiation settled lower)
```

#### 2.1b. NFS I/O Statistics (All VMs)

**Run on:** VM 101 (Plex), VM 104 (Tdarr Node) -- the heaviest NFS users

```bash
# Install nfsiostat if not present
apt-get install -y nfs-common

# Real-time NFS I/O stats, 5-second intervals, 12 samples (1 minute total)
nfsiostat 5 12
# Key metrics to record:
#   ops/s    - NFS operations per second
#   rpc bklog - RPC backlog (should be 0 or near 0)
#   read:    - read ops/s, kB/s, avg RTT (ms), avg exe (ms)
#   write:   - write ops/s, kB/s, avg RTT (ms), avg exe (ms)
#
# "Normal" for this hardware:
#   Idle:     <10 ops/s, RTT <2ms
#   Plex 1 stream: 50-200 read ops/s, 10-50 MB/s, RTT <5ms
#   Tdarr transcode: 100-500 ops/s combined, 30-100 MB/s, RTT <10ms
#   qBit download: 100-300 write ops/s, 10-50 MB/s, RTT <10ms
#
# RED FLAGS:
#   RTT > 50ms consistently
#   RPC backlog > 10
#   exe time >> RTT (indicates server-side queueing)
```

#### 2.1c. NFS Server Statistics (TrueNAS)

**Run on:** TrueNAS (10.25.0.25) via SSH

```bash
# NFS server-side statistics
nfsstat -s
# Key metrics:
#   rpc: total calls, badcalls, badfmt
#   nfsv3: read, write, commit, getattr, lookup, access counts
#
# "Normal": badcalls should be 0. read/write dominate for media workload.

# NFS thread utilization (if available)
cat /proc/net/rpc/nfsd
# The "th" line shows thread pool utilization
# If all threads are busy, NFS performance degrades
# Default is usually 8 threads. For this workload, 16-32 is better.
```

#### 2.1d. NFS Throughput Test (fio)

**Run on:** VM 101 (Plex) -- representative of read-heavy workload

```bash
# Install fio if not present
apt-get install -y fio

# Sequential read test (simulates Plex streaming)
# Creates a 1 GB test file on NFS, reads it sequentially
fio --name=seq-read \
    --directory=/mnt/truenas/nfs-mega-share \
    --rw=read \
    --bs=1M \
    --size=1G \
    --numjobs=1 \
    --runtime=60 \
    --time_based \
    --group_reporting \
    --output=baseline-seq-read.json \
    --output-format=json

# Key metrics from output:
#   bw (bandwidth): expect 80-110 MB/s (1 GbE theoretical max ~117 MB/s with jumbo)
#   iops: ~80-110 for 1M block size
#   lat avg: expect <5ms for sequential reads from ARC
#   lat 99th percentile: expect <20ms

# Sequential write test (simulates qBit downloads)
fio --name=seq-write \
    --directory=/mnt/truenas/nfs-mega-share \
    --rw=write \
    --bs=1M \
    --size=1G \
    --numjobs=1 \
    --runtime=60 \
    --time_based \
    --group_reporting \
    --output=baseline-seq-write.json \
    --output-format=json

# Key metrics:
#   bw: expect 50-80 MB/s (RAIDZ2 write penalty + NFS overhead)
#   lat avg: expect <20ms
#   lat 99th: expect <100ms (ZFS TXG commits cause periodic spikes)

# Concurrent read test (simulates multiple Plex streams)
fio --name=concurrent-read \
    --directory=/mnt/truenas/nfs-mega-share \
    --rw=read \
    --bs=1M \
    --size=512M \
    --numjobs=4 \
    --runtime=60 \
    --time_based \
    --group_reporting \
    --output=baseline-concurrent-read.json \
    --output-format=json

# Key metrics:
#   aggregate bw: should still approach 100 MB/s (link limit, not disk limit for cached data)
#   per-job bw: ~25 MB/s each (link shared)
#   lat: should not spike beyond 2x single-job latency

# CLEANUP after tests:
rm -f /mnt/truenas/nfs-mega-share/seq-read.0.0 /mnt/truenas/nfs-mega-share/seq-write.0.0
rm -f /mnt/truenas/nfs-mega-share/concurrent-read.*.0
```

**Run on:** VM 103 (qBit) -- write-heavy over MTU 1500 path

```bash
# Same sequential write test, but over the management NIC path
fio --name=seq-write-dirty \
    --directory=/mnt/truenas/nfs-mega-share \
    --rw=write \
    --bs=1M \
    --size=1G \
    --numjobs=1 \
    --runtime=60 \
    --time_based \
    --group_reporting \
    --output=baseline-seq-write-dirty.json \
    --output-format=json

# Expected:
#   bw: 40-70 MB/s (lower due to MTU 1500 overhead + management NIC path)
#   lat: higher than VLAN 25 path due to smaller packets

# CLEANUP:
rm -f /mnt/truenas/nfs-mega-share/seq-write-dirty.0.0
```

### 2.2 ZFS Performance

**Run on:** TrueNAS (10.25.0.25) via SSH

#### 2.2a. ARC Statistics

```bash
# Comprehensive ARC summary
arc_summary
# Key sections to record:
#   ARC size: current / target max / min
#   ARC efficiency: hit rate (target: >90% for media workload)
#   L2ARC: should show "not present"
#   Memory: total, free, ARC

# If arc_summary is not available (some TrueNAS versions):
# Manual ARC stats:
cat /proc/spl/kstat/zfs/arcstats | grep -E "^(hits|misses|size|c_max|c_min|prefetch)"
# Calculate hit rate: hits / (hits + misses) * 100
# "Normal": >85% hit rate after warmup (hours of normal usage)
# Fresh boot: hit rate will be low and climb over time

# ARC max setting:
cat /sys/module/zfs/parameters/zfs_arc_max
# 0 = auto (50% of RAM = ~44 GB)
# Should be tuned to 70 GB (see WORKER1-NOTES.md item 2a)
```

#### 2.2b. ZFS Pool I/O Statistics

```bash
# Pool-level I/O stats, 5-second intervals, 12 samples
zpool iostat -v mega-pool 5 12
# Key metrics:
#   operations (read/write per second): per vdev and per disk
#   bandwidth (read/write MB/s): per vdev and per disk
#
# "Normal" idle: <10 ops/s, <1 MB/s
# "Normal" under Plex load: 50-200 ops/s reads, 10-80 MB/s
# "Normal" under Tdarr: 100-500 ops/s combined, 30-100 MB/s
#
# RED FLAGS:
#   One vdev significantly busier than the other -> unbalanced writes
#   Any disk showing errors
#   Write ops >> read ops during media serving (should be read-dominated)

# Dataset-level I/O (ZFS 2.4+):
zpool iostat -l mega-pool 5 12
# Shows latency percentiles per vdev
```

#### 2.2c. ZFS Dataset Properties

```bash
# Check all tunable properties on the main dataset
zfs get all mega-pool/nfs-mega-share | grep -E "(recordsize|compression|atime|sync|logbias|primarycache|secondarycache|redundant_metadata)"
# Expected:
#   recordsize: 128K (default, recommend 1M for media -- see WORKER1-NOTES.md 2b)
#   compression: lz4 or off
#   atime: on or off (off is better for NFS performance)
#   sync: standard
#   logbias: latency
#   primarycache: all
#   secondarycache: all
#
# Quick wins if not already set:
#   atime=off: eliminates access time updates on reads (significant for Plex)
#   compression=lz4: free performance (LZ4 is faster than disk I/O)

# Check ZFS pool status and errors
zpool status mega-pool
# Should show ONLINE, 0 errors on all disks
# Last scrub: 2026-02-08 (documented)
```

### 2.3 Network Performance

#### 2.3a. Link Speed and Offload Verification

**Run on:** pve01 (10.25.0.26)

```bash
# Link speed and duplex
ethtool nic0 | grep -E "Speed|Duplex|Link detected"
ethtool nic1 | grep -E "Speed|Duplex|Link detected"
# Expected: Speed: 1000Mb/s, Duplex: Full, Link detected: yes

# Hardware offloads
ethtool -k nic0 | grep -E "^(tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload|rx-checksumming|tx-checksumming)"
ethtool -k nic1 | grep -E "^(tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload|rx-checksumming|tx-checksumming)"
# Expected: all "on". If any are "off", see WORKER1-NOTES.md item 3c.

# Ring buffer sizes
ethtool -g nic0
ethtool -g nic1
# Record current and maximum values. Larger ring buffers reduce packet drops under load.

# Interrupt coalescing
ethtool -c nic0
ethtool -c nic1
# Record rx-usecs, tx-usecs. Defaults vary by driver.

# NIC driver and firmware
ethtool -i nic0
ethtool -i nic1
# Record driver version for reproducibility.
```

**Run on:** pve03 (10.25.0.28)

```bash
# Same checks on the single NIC
ethtool nic0 | grep -E "Speed|Duplex|Link detected"
ethtool -k nic0 | grep -E "^(tcp-segmentation-offload|generic-segmentation-offload|generic-receive-offload|rx-checksumming|tx-checksumming)"
ethtool -g nic0
ethtool -c nic0
ethtool -i nic0
```

**Run on:** TrueNAS (10.25.0.25)

```bash
# Bond status and member health
cat /proc/net/bonding/bond0
# Verify: Mode=802.3ad, LACP rate=slow/fast, both members MII Status=up, Aggregator ID matches

# Per-member traffic distribution (snapshot)
for iface in eno2 eno3; do
    echo "=== $iface ==="
    echo "RX bytes: $(cat /sys/class/net/$iface/statistics/rx_bytes)"
    echo "TX bytes: $(cat /sys/class/net/$iface/statistics/tx_bytes)"
    echo "RX packets: $(cat /sys/class/net/$iface/statistics/rx_packets)"
    echo "TX packets: $(cat /sys/class/net/$iface/statistics/tx_packets)"
done
# Compare RX/TX bytes between eno2 and eno3.
# If one carries >70% of traffic, hash policy change is warranted.

# All NIC offloads on bond members
ethtool -k eno1 | grep -E "^(tcp-segmentation|generic-segmentation|generic-receive|rx-checksum|tx-checksum)"
ethtool -k eno2 | grep -E "^(tcp-segmentation|generic-segmentation|generic-receive|rx-checksum|tx-checksum)"
ethtool -k eno3 | grep -E "^(tcp-segmentation|generic-segmentation|generic-receive|rx-checksum|tx-checksum)"
```

#### 2.3b. Network Throughput (iperf3)

**Run on:** TrueNAS as server, pve01/pve03 as clients

```bash
# On TrueNAS (install if needed):
apt-get install -y iperf3   # SCALE
pkg install iperf3           # CORE

# Start iperf3 server:
iperf3 -s -p 5201
```

```bash
# On pve01 -- test VLAN 25 storage path (dedicated NIC):
iperf3 -c 10.25.25.25 -p 5201 -t 30 -P 4 --bind 10.25.25.26
# Expected: ~940 Mbps aggregate (1 GbE minus overhead)
# -P 4 = 4 parallel streams to test NIC aggregation

# On pve01 -- test VLAN 1 path (shared NIC):
iperf3 -c 10.25.0.25 -p 5201 -t 30 -P 4 --bind 10.25.0.26
# Expected: ~940 Mbps aggregate

# On pve03 -- test VLAN 25 storage path (shared NIC):
iperf3 -c 10.25.25.25 -p 5201 -t 30 -P 4 --bind 10.25.25.28
# Expected: ~940 Mbps aggregate. But if VM traffic is concurrent, this will be lower.

# Jumbo frame validation (critical -- Lesson #8):
iperf3 -c 10.25.25.25 -p 5201 -t 10 -M 8972
# -M 8972 = MSS for 9000 MTU (9000 - 20 IP - 8 TCP)
# If this fails or shows dramatically lower throughput, jumbo frames are broken somewhere.
```

#### 2.3c. MTU Verification

**Run on:** pve01, pve03

```bash
# Verify jumbo frames work end-to-end (Lesson #8):
ping -M do -s 8972 10.25.25.25 -c 5
# -M do = don't fragment
# -s 8972 = payload size (8972 + 28 IP/ICMP header = 9000)
# Expected: 5 replies, no "Frag needed" errors

# From VM 101 (via guest agent or SSH):
ping -M do -s 8972 10.25.0.25 -c 5
# Same expected result

# From VM 103 (MTU 1500 path -- expect FAILURE at 8972):
ping -M do -s 1472 10.25.255.25 -c 5
# -s 1472 = max for MTU 1500 (1472 + 28 = 1500)
# Expected: 5 replies. At -s 1473, expect "Frag needed" (confirms MTU 1500).
```

#### 2.3d. TCP Tunable Baseline

**Run on:** pve01, pve03, VMs 101-105

```bash
# Current TCP buffer sizes
sysctl net.core.rmem_max net.core.wmem_max
sysctl net.ipv4.tcp_rmem net.ipv4.tcp_wmem
# Record current values. Defaults are usually:
#   rmem_max = 212992
#   wmem_max = 212992
#   tcp_rmem = 4096 131072 6291456
#   tcp_wmem = 4096 16384 4194304

# TCP features
sysctl net.ipv4.tcp_window_scaling   # Should be 1
sysctl net.ipv4.tcp_timestamps       # Should be 1
sysctl net.ipv4.tcp_sack             # Should be 1

# NFS-specific: sunrpc transport settings
sysctl sunrpc.tcp_slot_table_entries 2>/dev/null
sysctl sunrpc.tcp_max_slot_table_entries 2>/dev/null
# Default: 2 / 65536. Low slot count can throttle NFS. Minimum recommended: 128.
```

### 2.4 VM Resource Baseline

**Run on:** pve01 (10.25.0.26)

```bash
# NUMA topology
numactl --hardware
# Record: number of nodes, CPUs per node, memory per node
# Expected: 2 nodes (2x E5-2620 v0), 12 CPUs each (6c + HT), ~128 GB each

# Which NUMA node owns each NIC
cat /sys/class/net/nic0/device/numa_node
cat /sys/class/net/nic1/device/numa_node
# Record: tells you which NUMA node to pin NFS-heavy VMs to

# VM resource allocation
for vmid in 101 102 103 105; do
    echo "=== VM $vmid ==="
    qm config $vmid | grep -E "^(memory|cores|sockets|cpu|balloon|numa|hostpci)"
done
# Record current values for all VMs

# Host memory usage
free -h
# Expected: ~220+ GB free on pve01 (256 GB total, ~36 GB allocated to VMs)

# Host CPU usage
uptime
mpstat -P ALL 5 3
# Record: load average and per-CPU utilization
# "Normal" idle: load <2, CPU <10% except for occasional spikes
```

**Run on:** pve03 (10.25.0.28)

```bash
# Memory (critical -- only 31 GB total, 16 GB to VM 104)
free -h
# Expected: ~13-15 GB free (31 GB - 16 GB VM104 - ~2 GB host overhead)
# RED FLAG: <4 GB free means pve03 is under memory pressure

# CPU
uptime
mpstat -P ALL 5 3

# GPU passthrough status
lspci | grep -i amd
# Should show RX 580 bound to vfio-pci (not amdgpu/radeon)
```

### 2.5 Disk I/O Baseline (Proxmox Hosts)

**Run on:** pve01

```bash
# iostat for all block devices, 5-second intervals, 12 samples
iostat -xz 5 12
# Key metrics:
#   await: average I/O wait time (ms). >20ms = potential issue
#   %util: device utilization. >80% = saturated
#   r/s, w/s: read/write operations per second
#
# For NFS clients, this shows LOCAL disk I/O only.
# NFS I/O appears in nfsiostat, not iostat.
```

---

## 3. First-Pass Tuning Plan

Organized by priority. Apply in this order, measuring before and after each change.

### Phase 1: NFS Mount Optimization (Priority: HIGH, Risk: LOW)

**Estimated time:** 30 minutes total, <1 minute downtime per VM

#### Step 1: Record baseline NFS throughput
```bash
# On VM 101 (Plex):
fio --name=baseline-read --directory=/mnt/truenas/nfs-mega-share --rw=read --bs=1M --size=1G --numjobs=1 --runtime=60 --time_based --group_reporting
# Record: bw, iops, avg lat, p99 lat
```

#### Step 2: Update fstab on VM 101 (test VM first)
```bash
# SSH to VM 101 (10.25.5.30 via pve01 jump, or 10.25.255.30 via mgmt)
# Backup current fstab
cp /etc/fstab /etc/fstab.bak.$(date +%Y%m%d)

# Edit fstab -- change NFS line from:
# 10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,defaults 0 0
# To:
# 10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,nconnect=4,hard,timeo=50,retrans=5,_netdev,nofail 0 0

vi /etc/fstab
```

#### Step 3: Remount and verify
```bash
# Stop Docker services using NFS first
docker compose -f /mnt/truenas/nfs-mega-share/plex/docker-compose.plex.yml down

# Unmount and remount
umount /mnt/truenas/nfs-mega-share
mount /mnt/truenas/nfs-mega-share

# Verify new options
mount -t nfs | grep nfs-mega-share
# Should show: rsize=1048576,wsize=1048576,nconnect=4,hard,timeo=50,retrans=5

nfsstat -m
# Confirm all options

# Restart Docker services
docker compose -f /mnt/truenas/nfs-mega-share/plex/docker-compose.plex.yml up -d
```

#### Step 4: Measure post-tuning
```bash
# Same fio test as Step 1
fio --name=tuned-read --directory=/mnt/truenas/nfs-mega-share --rw=read --bs=1M --size=1G --numjobs=1 --runtime=60 --time_based --group_reporting
# Compare: bw, iops, avg lat, p99 lat against baseline
```

#### Step 5: If improvement confirmed, apply to remaining VMs
```bash
# Repeat Steps 2-3 on VMs 102, 103, 104, 105
# VM 103 uses 10.25.255.25 as the NFS server IP (do not change the IP, only the mount options)
# Stop/start Docker services on each VM around the remount
```

#### Rollback (if any VM breaks):
```bash
cp /etc/fstab.bak.$(date +%Y%m%d) /etc/fstab
umount /mnt/truenas/nfs-mega-share
mount /mnt/truenas/nfs-mega-share
# Restart Docker services
```

### Phase 2: ZFS ARC Tuning (Priority: HIGH, Risk: LOW)

**Estimated time:** 15 minutes. No downtime required for setting change; reboot for persistence.

#### Step 1: Record baseline ARC state
```bash
# On TrueNAS:
arc_summary > /tmp/arc_baseline_$(date +%Y%m%d).txt
cat /proc/spl/kstat/zfs/arcstats | grep -E "^(hits|misses|size|c_max|c_min)" > /tmp/arc_stats_baseline.txt
```

#### Step 2: Check current ARC max
```bash
cat /sys/module/zfs/parameters/zfs_arc_max
# If 0: auto mode (~44 GB for 88 GB system)
# Record value
```

#### Step 3: Set ARC max to 70 GB
```bash
# Via TrueNAS GUI (recommended for persistence):
# System Settings -> Advanced -> Sysctl
# Add: Variable=vfs.zfs.arc_max, Value=75161927680, Type=sysctl

# Or immediate (non-persistent) via SSH:
echo 75161927680 > /sys/module/zfs/parameters/zfs_arc_max

# Verify:
cat /sys/module/zfs/parameters/zfs_arc_max
# Should show: 75161927680
```

#### Step 4: Verify ARC growth over time
```bash
# Wait 1-2 hours under normal workload, then:
arc_summary | grep -A5 "ARC size"
# ARC size should be growing toward 70 GB
# Hit rate should be improving (compare to baseline)
```

#### Step 5: Set atime=off on NFS dataset (if not already)
```bash
# Check current:
zfs get atime mega-pool/nfs-mega-share

# If "on", disable:
zfs set atime=off mega-pool/nfs-mega-share
# Takes effect immediately for new reads. No downtime.
```

#### Rollback:
```bash
# Remove sysctl via TrueNAS GUI, or:
echo 0 > /sys/module/zfs/parameters/zfs_arc_max
# ARC returns to auto-sizing on next boot
zfs set atime=on mega-pool/nfs-mega-share
```

### Phase 3: Network Stack Tuning (Priority: MEDIUM, Risk: LOW)

**Estimated time:** 20 minutes. No downtime.

#### Step 1: Record baseline TCP settings
```bash
# On pve01:
sysctl net.core.rmem_max net.core.wmem_max net.ipv4.tcp_rmem net.ipv4.tcp_wmem > /tmp/tcp_baseline_$(date +%Y%m%d).txt
```

#### Step 2: Apply TCP buffer tuning
```bash
# On pve01 -- create sysctl file:
cat > /etc/sysctl.d/99-nfs-tuning.conf << 'EOF'
# DC01 NFS performance tuning -- Worker #4
# Applied: $(date)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 1048576 16777216
net.ipv4.tcp_wmem = 4096 1048576 16777216
net.core.netdev_max_backlog = 5000
EOF

sysctl -p /etc/sysctl.d/99-nfs-tuning.conf
# Verify:
sysctl net.core.rmem_max net.core.wmem_max
```

#### Step 3: Repeat on pve03 and VMs 101-105
```bash
# Same file on each system
# VMs: SSH in and create the same /etc/sysctl.d/99-nfs-tuning.conf
# Apply: sysctl -p /etc/sysctl.d/99-nfs-tuning.conf
```

#### Step 4: Verify NIC offloads and fix if needed
```bash
# On pve01:
for nic in nic0 nic1; do
    echo "=== $nic offloads ==="
    ethtool -k $nic | grep -E "^(tcp-segmentation|generic-segmentation|generic-receive|rx-checksum|tx-checksum)"
done

# Enable if any are off:
# ethtool -K nic0 tso on gso on gro on tx-checksum-ipv4 on rx-checksum on
```

#### Step 5: MTU verification (non-destructive, always run)
```bash
# From pve01 storage NIC:
ping -M do -s 8972 10.25.25.25 -c 5
# Must succeed. If it fails, jumbo frames are broken -- STOP and investigate.
```

#### Rollback:
```bash
rm /etc/sysctl.d/99-nfs-tuning.conf
sysctl --system
```

### Phase 4: VM Resource Allocation (Priority: MEDIUM, Risk: LOW-MEDIUM)

**Estimated time:** 30 minutes. Requires VM restarts.

#### Step 1: Disable ballooning on pve01 VMs
```bash
# On pve01:
for vmid in 101 102 103 105; do
    echo "VM $vmid balloon: $(qm config $vmid | grep balloon)"
    qm set $vmid --balloon 0
done
# Changes take effect after VM restart. Schedule during maintenance window.
```

#### Step 2: NUMA awareness (optional, measure first)
```bash
# Check NUMA topology:
numactl --hardware
cat /sys/class/net/nic1/device/numa_node
# If nic1 is on node 0, pin NFS-heavy VMs (101, 103) to node 0

# Example for VM 101:
qm set 101 --numa 1
# Then in /etc/pve/qemu-server/101.conf, add:
# numa0: cpus=0-5,hostnodes=0,memory=8192,policy=preferred
# Requires VM restart
```

#### Rollback:
```bash
qm set 101 --balloon 1024
qm set 101 --numa 0
# Restart VM
```

---

## 4. Stepwise Tuning Workflow

Follow this process for EVERY tuning change. Never skip steps.

```
                    +------------------+
                    |  1. BASELINE     |
                    |  Record metrics  |
                    |  (fio, nfsiostat,|
                    |   arc_summary)   |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  2. CHANGE ONE   |
                    |  THING           |
                    |  Document what   |
                    |  you changed     |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  3. MEASURE      |
                    |  Same metrics    |
                    |  as baseline     |
                    |  Wait 10+ min    |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    |  4. COMPARE      |
                    |  Better? Worse?  |
                    |  Same?           |
                    +--------+---------+
                            / \
                           /   \
                     Better     Worse/Same
                       |             |
                       v             v
               +----------+   +----------+
               | 5. KEEP  |   | 5. ROLL  |
               | Document |   |    BACK  |
               | the win  |   | Document |
               +----------+   | why      |
                               +----------+
                             |
                             v
                    +------------------+
                    |  6. NEXT CHANGE  |
                    |  Return to       |
                    |  step 1          |
                    +------------------+
```

### Measurement Protocol

For each change, record these metrics:

| Metric | Tool | Run On | Duration |
|---|---|---|---|
| NFS sequential read throughput | `fio --rw=read --bs=1M` | VM 101 | 60 sec |
| NFS sequential write throughput | `fio --rw=write --bs=1M` | VM 103 | 60 sec |
| NFS concurrent read throughput | `fio --rw=read --numjobs=4` | VM 101 | 60 sec |
| NFS latency (avg + p99) | `nfsiostat 5 12` | VM 101, VM 104 | 60 sec |
| ZFS ARC hit rate | `arc_summary` | TrueNAS | Snapshot |
| ZFS pool IOPS | `zpool iostat -v mega-pool 5 12` | TrueNAS | 60 sec |
| Network throughput (raw) | `iperf3 -c <ip> -t 30` | pve01, pve03 | 30 sec |
| Host CPU utilization | `mpstat -P ALL 5 6` | pve01, pve03 | 30 sec |

### Documentation Template

For each change, log:

```
## Change: [NAME]
Date: YYYY-MM-DD HH:MM
System: [node/VM]
File changed: [path]
Old value: [exact old config]
New value: [exact new config]

### Baseline metrics (before):
- NFS read BW: XX MB/s
- NFS write BW: XX MB/s
- NFS read latency (avg/p99): XX/XX ms
- ARC hit rate: XX%

### Post-change metrics (after):
- NFS read BW: XX MB/s
- NFS write BW: XX MB/s
- NFS read latency (avg/p99): XX/XX ms
- ARC hit rate: XX%

### Verdict: KEEP / ROLLBACK
### Reason: [why]
```

---

## 5. Monitoring Setup Recommendations

### 5.1 Immediate: Shell-Based Monitoring Scripts

No monitoring stack is deployed. Until Uptime Kuma or similar is installed, use simple scripts.

#### NFS Health Check (cron on each VM)

Create `/usr/local/bin/nfs-health-check.sh` on VMs 101-105:

```bash
#!/bin/bash
# NFS health check for DC01 VMs
# Add to root crontab: */5 * * * * /usr/local/bin/nfs-health-check.sh

LOGFILE="/var/log/nfs-health.log"
MOUNT="/mnt/truenas/nfs-mega-share"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Check if mount is alive (timeout after 5 seconds)
if timeout 5 stat "$MOUNT" > /dev/null 2>&1; then
    # Mount is responsive
    LATENCY=$(timeout 10 dd if="$MOUNT/plex/docker-compose.plex.yml" of=/dev/null bs=4k count=1 2>&1 | grep -oP '[\d.]+ s' | head -1)
    echo "$TIMESTAMP OK latency=$LATENCY" >> "$LOGFILE"
else
    echo "$TIMESTAMP FAIL NFS mount unresponsive" >> "$LOGFILE"
    # Optional: send alert via webhook, email, etc.
fi

# Rotate log at 10 MB
if [ "$(stat -c%s "$LOGFILE" 2>/dev/null)" -gt 10485760 ]; then
    mv "$LOGFILE" "$LOGFILE.old"
fi
```

#### ZFS Health Check (cron on TrueNAS)

Create `/usr/local/bin/zfs-health-check.sh` on TrueNAS:

```bash
#!/bin/bash
# ZFS health check for DC01 TrueNAS
# Add to crontab: */15 * * * * /usr/local/bin/zfs-health-check.sh

LOGFILE="/var/log/zfs-health.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Pool health
POOL_STATE=$(zpool status mega-pool | grep "state:" | awk '{print $2}')
ERRORS=$(zpool status mega-pool | grep "errors:" | head -1)

# ARC stats
ARC_SIZE=$(cat /proc/spl/kstat/zfs/arcstats | grep "^size" | awk '{print $3}')
ARC_HITS=$(cat /proc/spl/kstat/zfs/arcstats | grep "^hits" | awk '{print $3}')
ARC_MISSES=$(cat /proc/spl/kstat/zfs/arcstats | grep "^misses" | awk '{print $3}')
ARC_SIZE_GB=$(echo "scale=1; $ARC_SIZE / 1073741824" | bc)
if [ $((ARC_HITS + ARC_MISSES)) -gt 0 ]; then
    ARC_HIT_PCT=$(echo "scale=1; $ARC_HITS * 100 / ($ARC_HITS + $ARC_MISSES)" | bc)
else
    ARC_HIT_PCT="N/A"
fi

echo "$TIMESTAMP pool=$POOL_STATE arc=${ARC_SIZE_GB}GB hit_rate=${ARC_HIT_PCT}% $ERRORS" >> "$LOGFILE"

if [ "$POOL_STATE" != "ONLINE" ]; then
    echo "$TIMESTAMP CRITICAL: mega-pool state is $POOL_STATE" >> "$LOGFILE"
fi

# Rotate log
if [ "$(stat -c%s "$LOGFILE" 2>/dev/null)" -gt 10485760 ]; then
    mv "$LOGFILE" "$LOGFILE.old"
fi
```

#### pve03 NIC Saturation Monitor

Create `/usr/local/bin/nic-monitor.sh` on pve03:

```bash
#!/bin/bash
# NIC saturation monitor for pve03 single-NIC bottleneck
# Add to crontab: * * * * * /usr/local/bin/nic-monitor.sh

LOGFILE="/var/log/nic-saturation.log"
IFACE="nic0"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Get bytes in 1-second interval
RX1=$(cat /sys/class/net/$IFACE/statistics/rx_bytes)
TX1=$(cat /sys/class/net/$IFACE/statistics/tx_bytes)
sleep 1
RX2=$(cat /sys/class/net/$IFACE/statistics/rx_bytes)
TX2=$(cat /sys/class/net/$IFACE/statistics/tx_bytes)

RX_RATE=$(( (RX2 - RX1) * 8 / 1000000 ))  # Mbps
TX_RATE=$(( (TX2 - TX1) * 8 / 1000000 ))  # Mbps

echo "$TIMESTAMP rx=${RX_RATE}Mbps tx=${TX_RATE}Mbps" >> "$LOGFILE"

# Alert threshold: 850 Mbps (85% of 1 GbE)
if [ "$RX_RATE" -gt 850 ] || [ "$TX_RATE" -gt 850 ]; then
    echo "$TIMESTAMP WARNING: NIC approaching saturation rx=${RX_RATE} tx=${TX_RATE}" >> "$LOGFILE"
fi

# Rotate log
if [ "$(stat -c%s "$LOGFILE" 2>/dev/null)" -gt 10485760 ]; then
    mv "$LOGFILE" "$LOGFILE.old"
fi
```

### 5.2 Medium-Term: Structured Monitoring

When a proper monitoring stack is deployed (Uptime Kuma, Prometheus+Grafana, or similar), monitor these metrics:

| Category | Metric | Alert Threshold | Source |
|---|---|---|---|
| **NFS** | Mount responsiveness | >5 sec or unresponsive | stat on mount point |
| **NFS** | Read latency (avg) | >50 ms sustained | nfsiostat |
| **NFS** | Write latency (avg) | >100 ms sustained | nfsiostat |
| **NFS** | RPC backlog | >10 sustained | nfsiostat |
| **ZFS** | Pool state | != ONLINE | zpool status |
| **ZFS** | ARC hit rate | <80% sustained | /proc/spl/kstat/zfs/arcstats |
| **ZFS** | ARC size | <50 GB (if tuned to 70 GB max) | /proc/spl/kstat/zfs/arcstats |
| **ZFS** | Disk errors (read/write/checksum) | >0 | zpool status |
| **Network** | pve03 NIC utilization | >85% | /sys/class/net/nic0/statistics/ |
| **Network** | Bond member distribution | >80/20 skew | /sys/class/net/eno{2,3}/statistics/ |
| **Network** | Packet drops (any NIC) | >0 per minute | ethtool -S or /sys/class/net/*/statistics/rx_dropped |
| **Hardware** | TrueNAS temperatures | >70C any disk | smartctl -A /dev/sdX |
| **Hardware** | TrueNAS PSU status | PSU 1 still failed | ipmitool sensor |
| **Hardware** | pve01 PSU status | PSU 2 still failed | ipmitool sensor |
| **VM** | Docker container health | unhealthy or exited | docker ps |
| **Cluster** | Corosync quorum | <2 nodes | pvecm status |
| **Cluster** | HA manager state | error | ha-manager status |

### 5.3 Long-Term Performance Regression Detection

After applying tuning changes, establish a "tuned baseline" and run automated performance tests weekly:

```bash
#!/bin/bash
# Weekly performance regression test
# Run on VM 101 (Plex) via cron: 0 3 * * 0 /usr/local/bin/perf-regression.sh

LOGDIR="/var/log/perf-regression"
mkdir -p "$LOGDIR"
DATE=$(date +%Y%m%d)

# Sequential read (Plex workload proxy)
fio --name=weekly-read \
    --directory=/mnt/truenas/nfs-mega-share \
    --rw=read \
    --bs=1M \
    --size=1G \
    --numjobs=1 \
    --runtime=60 \
    --time_based \
    --group_reporting \
    --output="$LOGDIR/read-$DATE.json" \
    --output-format=json

# Concurrent read (multiple streams)
fio --name=weekly-concurrent \
    --directory=/mnt/truenas/nfs-mega-share \
    --rw=read \
    --bs=1M \
    --size=512M \
    --numjobs=4 \
    --runtime=60 \
    --time_based \
    --group_reporting \
    --output="$LOGDIR/concurrent-$DATE.json" \
    --output-format=json

# NFS stats snapshot
nfsstat -m > "$LOGDIR/nfsmount-$DATE.txt"

# Cleanup test files
rm -f /mnt/truenas/nfs-mega-share/weekly-read.0.0 /mnt/truenas/nfs-mega-share/weekly-concurrent.*.0

# Extract key metrics for trend analysis
READ_BW=$(jq '.jobs[0].read.bw_bytes' "$LOGDIR/read-$DATE.json" 2>/dev/null)
READ_LAT=$(jq '.jobs[0].read.lat_ns.mean' "$LOGDIR/read-$DATE.json" 2>/dev/null)
echo "$DATE read_bw_bytes=$READ_BW read_lat_ns=$READ_LAT" >> "$LOGDIR/trend.log"
```

Compare `trend.log` weekly. Any regression >20% from the tuned baseline warrants investigation.

---

## Appendix A: Quick Reference -- All DC01 Performance-Relevant IPs

| System | IP | VLAN | Use |
|---|---|---|---|
| TrueNAS (NFS via LAN) | 10.25.0.25 | 1 | VM NFS mounts (101, 102, 104, 105) |
| TrueNAS (NFS via storage) | 10.25.25.25 | 25 | Proxmox host-level NFS (pve01, pve03) |
| TrueNAS (NFS via mgmt) | 10.25.255.25 | 2550 | VM 103 NFS (dirty VLAN isolation) |
| TrueNAS (SSH for tuning) | 10.25.0.25 | 1 | SSH from pve01 |
| pve01 (host) | 10.25.0.26 | 1 | SSH, Proxmox API |
| pve01 (storage) | 10.25.25.26 | 25 | NFS storage path |
| pve01 (mgmt) | 10.25.255.26 | 2550 | Corosync, iDRAC |
| pve03 (host) | 10.25.0.28 | 1 | SSH, Proxmox API |
| pve03 (storage) | 10.25.25.28 | 25 | NFS storage path (shared NIC) |
| pve03 (mgmt) | 10.25.255.28 | 2550 | Corosync |
| VM 101 (Plex) | 10.25.5.30 / 10.25.255.30 | 5 / 2550 | Service / management |
| VM 102 (Arr) | 10.25.5.31 / 10.25.255.31 | 5 / 2550 | Service / management |
| VM 103 (qBit) | 10.25.66.10 / 10.25.255.32 | 66 / 2550 | Service / management |
| VM 104 (Tdarr Node) | 10.25.10.34 / 10.25.255.34 | 10 / 2550 | Service / management |
| VM 105 (Tdarr Server) | 10.25.10.33 / 10.25.255.33 | 10 / 2550 | Service / management |

## Appendix B: Expected Performance Ranges

These are realistic expectations for DC01's hardware, not theoretical maximums.

| Metric | Idle | Plex (1 stream) | Plex (4 streams) | Tdarr Transcode | qBit Download |
|---|---|---|---|---|---|
| NFS read BW | <1 MB/s | 10-50 MB/s | 40-100 MB/s | 30-60 MB/s | <5 MB/s |
| NFS write BW | <1 MB/s | <1 MB/s | <1 MB/s | 10-40 MB/s | 20-60 MB/s |
| NFS read latency | <2 ms | <5 ms (ARC hit) | <10 ms | <10 ms | N/A |
| NFS write latency | <5 ms | N/A | N/A | <30 ms | <30 ms |
| ARC hit rate | N/A | 80-95% | 60-90% | 50-80% | N/A |
| pve01 CPU | <5% | <10% | 15-30% | <5% | <5% |
| pve03 CPU | <5% | N/A | N/A | 10-30% (GPU offload) | N/A |
| pve03 NIC util | <5% | N/A | N/A | 30-70% | N/A |
| Link utilization (any) | <5% | 10-50% | 40-100% | 30-70% | 20-60% |

**Key constraints:**
- All network paths are 1 GbE (theoretical max ~117 MB/s with jumbo, ~940 Mbps)
- RAIDZ2 write IOPS is limited to ~single-disk IOPS per vdev (~100-150 IOPS for 7200 RPM SAS)
- RAIDZ2 read IOPS scales with number of data disks per vdev (2 data disks per RAIDZ2 vdev of 4)
- ZFS ARC eliminates most read IOPS for hot data
- pve03 single NIC is the tightest bottleneck when Tdarr is active

## Appendix C: Files Modified by This Playbook

All changes are tracked here for audit and rollback purposes.

| File | System | Change | Phase |
|---|---|---|---|
| `/etc/fstab` | VMs 101-105 | NFS mount options | Phase 1 |
| `/etc/sysctl.d/99-nfs-tuning.conf` | pve01, pve03, VMs 101-105 | TCP buffer sizes | Phase 3 |
| TrueNAS sysctl (GUI) | TrueNAS | vfs.zfs.arc_max = 75161927680 | Phase 2 |
| ZFS dataset property | TrueNAS | atime=off on mega-pool/nfs-mega-share | Phase 2 |
| `/etc/pve/qemu-server/*.conf` | pve01 | balloon=0, NUMA pinning | Phase 4 |
| `/etc/network/if-up.d/qos-pve03` | pve03 | QoS traffic prioritization (if applied) | Optional |

---

*End of tuning playbook. All changes should be applied incrementally with measurement. When in doubt, do not change.*
