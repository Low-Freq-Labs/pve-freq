# Tuning Notes for Worker #1 (Infrastructure Architect)

> **From:** Worker #4 (Performance & Tuning Engineer)
> **Date:** 2026-02-19
> **Scope:** DC01 cluster -- pve01, pve03, TrueNAS (R530), Cisco 4948E-F
> **Ground truth:** DC01.md Session 18 rewrite, ARCHITECTURE.md

These are concrete, incremental tuning suggestions grounded in DC01's actual hardware. Each change is individually testable and reversible. Apply them one at a time with baseline measurements before and after.

---

## 1. NFS Mount Options

### Current State

All VM fstab entries use minimal options:
```
nfsvers=3,_netdev,nofail,defaults
```
The `defaults` keyword expands to `rw,suid,dev,exec,auto,nouser,async`. This means the kernel uses its own defaults for rsize/wsize (typically negotiated, often 1 MB on modern kernels), no multi-connection, hard mount, and default timeouts.

### 1a. Explicit rsize/wsize (1 MB)

- **Description:** Set explicit NFS read/write block sizes to 1 MB (1048576 bytes) to ensure large sequential I/O operations (media streaming, transcoding, downloads) transfer data in the largest possible chunks. Modern kernels usually negotiate this, but being explicit prevents surprises after kernel updates or NFS server config changes.
- **Concrete Change:** On every VM (101-105), update `/etc/fstab`:
  ```
  # Before
  10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,defaults 0 0

  # After
  10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,_netdev,nofail 0 0
  ```
  Apply without reboot: `sudo umount /mnt/truenas/nfs-mega-share && sudo mount /mnt/truenas/nfs-mega-share`
  Verify: `nfsstat -m` or `mount | grep nfs` -- confirm rsize/wsize show 1048576.
- **Expected Impact:** Ensures maximum transfer unit per NFS RPC. On a 1 GbE link with jumbo frames, this allows the NFS layer to fill full TCP windows. Plex streaming and Tdarr reads benefit most. Typical improvement: 5-15% throughput for large sequential reads if the kernel was previously negotiating a smaller size.
- **Risk Level:** Low. 1 MB is the NFSv3 maximum and is the standard recommendation for media workloads. All modern kernels and TrueNAS support it.
- **Rollback:** Remove `rsize=1048576,wsize=1048576` from fstab. Remount.

### 1b. nconnect=4 for Multi-Stream NFS

- **Description:** Open multiple TCP connections to the NFS server per mount point. By default, NFSv3 uses a single TCP connection. `nconnect` allows up to 16 parallel connections, improving throughput when the bottleneck is per-connection TCP overhead rather than raw link speed. On a 1 GbE link, nconnect=4 is the sweet spot -- enough parallelism without excessive connection overhead.
- **Concrete Change:** On VMs 101, 104, and 105 (the heaviest NFS users), update `/etc/fstab`:
  ```
  10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,nconnect=4,_netdev,nofail 0 0
  ```
  **Prerequisite:** Kernel >= 5.3 (all VMs run 6.x kernels -- verified). TrueNAS does not need any config change.
  Verify: `cat /proc/mounts | grep nfs` should show `nconnect=4`.
- **Expected Impact:** Improved concurrent read/write throughput. Most beneficial for VM 104 (Tdarr Node) doing simultaneous read-source + write-output, and VM 101 (Plex) doing multiple concurrent streams. Typical improvement: 10-30% for concurrent I/O patterns, minimal for single-stream sequential I/O.
- **Risk Level:** Low. nconnect is stable in kernels >= 5.3. Start with 4 connections; increase to 8 only if measurement shows improvement.
- **Rollback:** Remove `nconnect=4` from fstab. Remount.

### 1c. Hard Mount with Explicit Timeouts

- **Description:** The current `defaults` keyword implies `hard` mount (which is correct for data integrity), but the default timeo and retrans values are very aggressive -- timeo=600 (60 seconds) and retrans=3 before major timeout. For a colocated 1 GbE environment with no WAN latency, we can set tighter initial timeouts but more retransmits, which improves responsiveness during transient issues without risking data corruption.
- **Concrete Change:** On all VMs (101-105):
  ```
  10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,nconnect=4,hard,timeo=50,retrans=5,_netdev,nofail 0 0
  ```
  This sets initial timeout to 5 seconds (timeo is in deciseconds) and 5 retransmissions before escalation, compared to the default 60-second initial timeout with 3 retries.
- **Expected Impact:** Faster detection and recovery from transient NFS hiccups. No impact on steady-state performance. Prevents Docker containers from hanging for minutes when NFS has a brief stall.
- **Risk Level:** Low. `hard` ensures no silent data corruption. The only risk is more frequent retransmit log messages if TrueNAS is briefly slow, but this is also useful as a canary.
- **Rollback:** Replace `hard,timeo=50,retrans=5` with `defaults` in fstab. Remount.

**WARNING:** Do NOT use `soft` mounts. Soft mounts return EIO on timeout, which corrupts Docker container data and can destroy SQLite databases (Lesson #6 already documents this class of issue). Always use `hard`.

### 1d. VM 103 (qBit) Special Case

- **Description:** VM 103 reaches TrueNAS via the management NIC (10.25.255.25, eno4, MTU 1500). This path does NOT support jumbo frames. The rsize/wsize should still be 1 MB (NFS fragmentation handles it), but nconnect is more important here because the 1500 MTU path has more per-packet overhead.
- **Concrete Change:**
  ```
  10.25.255.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,nconnect=4,hard,timeo=50,retrans=5,_netdev,nofail 0 0
  ```
  Same options as other VMs. The TrueNAS IP stays at 10.25.255.25 per the VLAN 66 isolation design.
- **Expected Impact:** qBit downloads are write-heavy. nconnect=4 helps by parallelizing write RPCs. The 1500 MTU path is the real bottleneck here -- see item 3e below for TCP tuning that helps compensate.
- **Risk Level:** Low.
- **Rollback:** Revert fstab. Remount.

---

## 2. ZFS ARC Tuning

### Current State

TrueNAS R530 has 88 GB RAM. ZFS ARC (Adaptive Replacement Cache) defaults to using up to 50% of system RAM on TrueNAS, but the actual max can be verified with `sysctl vfs.zfs.arc.max` on FreeBSD-based TrueNAS or checking `/sys/module/zfs/parameters/zfs_arc_max` on Linux-based TrueNAS. The exact TrueNAS version (CORE vs SCALE) determines the OS, but the tuning principles are the same.

### 2a. ARC Maximum Size

- **Description:** With 88 GB of RAM and the current workload being predominantly media serving (Plex reads, Tdarr reads, Arr metadata), ARC is the single most impactful performance lever. The server runs only NFS/SMB services -- it does not host VMs. ARC should be set as high as possible, reserving memory for the OS and NFS server threads.
- **Concrete Change:**
  - **If TrueNAS SCALE (Linux-based):** Set via TrueNAS GUI: System Settings -> Advanced -> Sysctl -> add `vfs.zfs.arc_max` = `75161927680` (70 GB). Alternatively, SSH in and:
    ```bash
    # Check current ARC settings
    cat /proc/spl/kstat/zfs/arcstats | grep -E "c_max|c_min|size"
    # Verify current usage
    arc_summary
    ```
  - **If TrueNAS CORE (FreeBSD-based):** Set via TrueNAS GUI: System -> Tunables -> add `vfs.zfs.arc.max` = `75161927680`.
  - 70 GB ARC leaves 18 GB for OS, NFS server, SMB, and kernel. This is generous for a storage-only server.
- **Expected Impact:** ARC is a read cache. With the media library at ~740 GB used, 70 GB of ARC can cache approximately 9.5% of the working data. For Plex's active library (frequently watched content), the cache hit rate should be very high. Each ARC hit avoids a disk seek on spinning HGST SAS drives (typical seek: 4-8 ms). This translates directly to lower NFS read latency and higher concurrent stream capacity.
- **Risk Level:** Low. 70 GB is well within the safe range for 88 GB total. TrueNAS manages ARC dynamically -- it will not allocate the full 70 GB unless the data is accessed. If memory pressure occurs, ARC shrinks automatically.
- **Rollback:** Remove the sysctl entry. Reboot TrueNAS (ARC setting changes typically require reboot to take effect on TrueNAS).

### 2b. ZFS Recordsize Alignment

- **Description:** ZFS `recordsize` determines the maximum block size for files in a dataset. The default is 128 KB. For large media files (movies, TV episodes, transcode output), a larger recordsize reduces metadata overhead and improves sequential read throughput. For small-file workloads (Docker configs, SQLite DBs), the default is fine.
- **Concrete Change:** Create a separate dataset for media with 1 MB recordsize:
  ```bash
  # On TrueNAS via SSH or GUI:
  # Check current recordsize
  zfs get recordsize mega-pool/nfs-mega-share

  # If a migration to a separate media dataset is planned:
  zfs create -o recordsize=1M mega-pool/nfs-mega-share/media
  # Then move Movies/, TV/, Audio/ into this sub-dataset
  ```
  **However:** This is a structural change requiring data migration. The simpler approach is to change the existing dataset's recordsize (only affects new writes):
  ```bash
  zfs set recordsize=1M mega-pool/nfs-mega-share
  ```
  This changes recordsize for newly written files only. Existing files keep their original block size.
- **Expected Impact:** Reduces metadata overhead for large media files. Each 1 GB movie file uses ~1,000 blocks at 1 MB recordsize vs ~8,000 blocks at 128 KB. This means fewer metadata lookups during sequential reads. Improvement: 5-10% for large sequential reads (Plex streaming). No impact on already-written files.
- **Risk Level:** Medium. Changing recordsize on the live dataset is safe (it only affects new writes), but if small files (Docker configs) are also written to this dataset, they waste space (a 1 KB file uses 1 MB of disk). The ideal solution is a sub-dataset for media, but that requires a data move.
- **Rollback:** `zfs set recordsize=128K mega-pool/nfs-mega-share` (only affects future writes).

### 2c. ZFS Prefetch Tuning

- **Description:** ZFS has a built-in prefetch mechanism that detects sequential reads and reads ahead. For media streaming workloads, the prefetch is critical. Verify it is enabled and not capped.
- **Concrete Change:**
  ```bash
  # On TrueNAS:
  # Verify prefetch is enabled (should be 1)
  sysctl vfs.zfs.prefetch_disable    # FreeBSD CORE
  cat /sys/module/zfs/parameters/zfs_prefetch_disable  # Linux SCALE

  # Should be 0 (prefetch enabled). If it is 1, fix it:
  sysctl vfs.zfs.prefetch_disable=0  # CORE
  echo 0 > /sys/module/zfs/parameters/zfs_prefetch_disable  # SCALE
  ```
- **Expected Impact:** If prefetch was disabled (unlikely on defaults), enabling it dramatically improves sequential read throughput for Plex and Tdarr. If already enabled (likely), no change needed.
- **Risk Level:** Low. Prefetch should always be on for this workload.
- **Rollback:** `sysctl vfs.zfs.prefetch_disable=1` (but you would not want to do this).

---

## 3. Network Tunables

### 3a. TCP Buffer Sizes on Proxmox Hosts

- **Description:** Linux default TCP buffer sizes (wmem/rmem) are often conservative. For NFS over 1 GbE with jumbo frames (MTU 9000), larger TCP buffers allow the kernel to keep more data in flight, improving throughput for both reads and writes. The bandwidth-delay product for a LAN with <1 ms RTT is small, but larger buffers help with bursty NFS traffic.
- **Concrete Change:** On pve01 and pve03 (the Proxmox hosts that mount NFS for HA storage), add to `/etc/sysctl.d/99-nfs-tuning.conf`:
  ```bash
  # TCP buffer sizes: min, default, max (bytes)
  net.core.rmem_max = 16777216
  net.core.wmem_max = 16777216
  net.ipv4.tcp_rmem = 4096 1048576 16777216
  net.ipv4.tcp_wmem = 4096 1048576 16777216

  # NFS-specific: increase socket backlog
  net.core.netdev_max_backlog = 5000
  ```
  Apply without reboot: `sysctl -p /etc/sysctl.d/99-nfs-tuning.conf`
  Verify: `sysctl net.core.rmem_max net.core.wmem_max`
- **Expected Impact:** Allows TCP to use up to 16 MB buffers per connection. On 1 GbE LAN, the BDP is tiny (~125 KB at 1 ms RTT), but the default buffer (typically 4 MB max) can be a bottleneck during concurrent NFS sessions. Improvement: 5-10% for concurrent NFS I/O, negligible for single-stream.
- **Risk Level:** Low. These are standard Linux network tuning values used in production NFS environments. Memory impact is negligible -- TCP allocates dynamically up to the max, not the max upfront.
- **Rollback:** Delete `/etc/sysctl.d/99-nfs-tuning.conf` and run `sysctl --system`.

### 3b. Same TCP Tuning on VMs

- **Description:** The VMs themselves also benefit from larger TCP buffers for their NFS client connections.
- **Concrete Change:** On VMs 101-105, create `/etc/sysctl.d/99-nfs-tuning.conf` with the same content as 3a. Apply with `sysctl -p /etc/sysctl.d/99-nfs-tuning.conf`.
- **Expected Impact:** Same as 3a. Plex (VM 101) and Tdarr Node (VM 104) benefit most.
- **Risk Level:** Low.
- **Rollback:** Delete file, `sysctl --system`.

### 3c. NIC Offload Verification

- **Description:** Intel I350 (pve01) and BCM5720 (TrueNAS) NICs support hardware offloads (TSO, GSO, GRO, checksum offload). These should be enabled to reduce CPU overhead for NFS traffic. Verify they are not inadvertently disabled.
- **Concrete Change:**
  ```bash
  # On pve01 -- check both NICs:
  ethtool -k nic0 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"
  ethtool -k nic1 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"

  # On TrueNAS -- check all active NICs:
  ethtool -k eno1 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"
  ethtool -k eno2 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"
  ethtool -k eno3 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"

  # If any are off, enable them:
  ethtool -K nic0 tso on gso on gro on
  ```
  To make persistent, add a post-up script in `/etc/network/interfaces` on Proxmox or use TrueNAS GUI tunable.
- **Expected Impact:** If offloads were disabled, re-enabling them can improve throughput by 10-30% and significantly reduce CPU usage for NFS traffic. If already enabled (likely on defaults), no change.
- **Risk Level:** Low. These are standard offloads supported by both the Intel I350 and BCM5720.
- **Rollback:** `ethtool -K nic0 tso off gso off gro off` (but you would not want to do this).

### 3d. Interrupt Coalescing on Storage NICs

- **Description:** NIC interrupt coalescing batches multiple incoming packets into a single interrupt. This reduces CPU overhead at the cost of slightly higher latency per packet. For bulk NFS traffic (media streaming, downloads), this is a net win.
- **Concrete Change:**
  ```bash
  # On pve01 storage NIC (nic1 / vmbr1, Intel I350):
  # Check current settings:
  ethtool -c nic1

  # Set moderate coalescing (if not already set):
  ethtool -C nic1 rx-usecs 50 tx-usecs 50

  # On TrueNAS bond0 members:
  ethtool -C eno2 rx-usecs 50 tx-usecs 50
  ethtool -C eno3 rx-usecs 50 tx-usecs 50
  ```
  Persist on Proxmox via `/etc/network/interfaces` post-up directive:
  ```
  post-up ethtool -C nic1 rx-usecs 50 tx-usecs 50
  ```
- **Expected Impact:** Reduces interrupt rate by 30-50%, freeing CPU cycles on both pve01 and TrueNAS. On the Xeon E5-2620 v0 (pve01) and E5-2620 v3 (TrueNAS), interrupt overhead is measurable. Adds ~50 microseconds of latency per packet, which is irrelevant for bulk NFS but worth noting for latency-sensitive workloads (none in this environment).
- **Risk Level:** Low. 50 microseconds is conservative. The default is typically 3-10 microseconds depending on driver.
- **Rollback:** `ethtool -C nic1 rx-usecs 3 tx-usecs 3` (or whatever the default was -- capture before changing).

### 3e. VM 103 (qBit) TCP Window Scaling

- **Description:** VM 103's NFS path to TrueNAS traverses the management NIC (eno4, MTU 1500). This is a 1 GbE link without jumbo frames, so per-packet overhead is higher. TCP window scaling is enabled by default on modern kernels, but verify it.
- **Concrete Change:**
  ```bash
  # On VM 103:
  sysctl net.ipv4.tcp_window_scaling   # Should be 1
  sysctl net.ipv4.tcp_timestamps       # Should be 1
  sysctl net.ipv4.tcp_sack             # Should be 1
  ```
  If any are 0, set to 1 via `/etc/sysctl.d/99-nfs-tuning.conf`.
- **Expected Impact:** Ensures TCP can use full window sizes for download writes. If already enabled (very likely), no change.
- **Risk Level:** Low.
- **Rollback:** Revert sysctl.

---

## 4. VM Placement Optimization

### Current Placement

| VM | Node | RAM | Workload | Notes |
|---|---|---|---|---|
| 101 (Plex) | pve01 (256 GB) | 8 GB | Read-heavy streaming | Intel GPU transcode to local /tmp |
| 102 (Arr) | pve01 (256 GB) | 8 GB | Mixed metadata I/O | |
| 103 (qBit) | pve01 (256 GB) | 4 GB | Write-heavy downloads | NFS via mgmt NIC (slow path) |
| 104 (Tdarr Node) | pve03 (31 GB) | 16 GB | GPU transcode, NFS I/O | RX 580 passthrough -- CANNOT MOVE |
| 105 (Tdarr Server) | pve01 (256 GB) | 4 GB | Light coordination | |
| 420 (stopped) | pve01 | 8 GB | Unknown | |
| 802 (Blue) | pve01 | ~4 GB | Password vault | Sonny only |

### 4a. Current Placement is Mostly Optimal

- **Description:** The placement is largely dictated by hardware constraints. VM 104 MUST be on pve03 (RX 580 GPU passthrough). All other production VMs are on pve01, which has 256 GB RAM and dedicated storage NIC. pve02 is out of scope. There is limited opportunity to redistribute.
- **Concrete Change:** No VM migration recommended. The one VM that could potentially move is VM 105 (Tdarr Server, 4 GB RAM, light I/O) to pve03, since the Tdarr server communicates heavily with its node (VM 104) over VLAN 10. However, pve03 has only 31 GB RAM with 16 GB already allocated to VM 104 -- adding 4 GB for VM 105 leaves only 11 GB for the host, which is tight for a Proxmox hypervisor with HA services running.
- **Expected Impact:** Moving VM 105 to pve03 would reduce cross-node VLAN 10 traffic between Tdarr server and node. But the network path (both on same switch, <1 ms) makes this negligible. Not recommended given pve03's RAM constraints.
- **Risk Level:** N/A (no change recommended).
- **Rollback:** N/A.

### 4b. RAM Allocation Review

- **Description:** pve01 has 256 GB RAM with only ~36 GB allocated across active VMs (8+8+4+4+4 = 28 GB for production, plus ~4 GB for Blue and 8 GB for stopped VM 420). That is under 15% utilization. This is fine -- ample headroom for future VMs and PBS.
- **Concrete Change:** Consider increasing Plex (VM 101) RAM to 16 GB if Plex transcoding cache or metadata indexing is observed to pressure memory. Use Proxmox GUI or:
  ```bash
  # On pve01:
  qm set 101 --memory 16384
  # Requires VM restart to take effect
  ```
- **Expected Impact:** Plex benefits from more RAM for its metadata database and transcoder cache. 16 GB is the recommended minimum for large Plex libraries.
- **Risk Level:** Low. pve01 has abundant RAM.
- **Rollback:** `qm set 101 --memory 8192` and restart VM.

### 4c. CPU Pinning (NUMA Awareness)

- **Description:** pve01 has 2x Xeon E5-2620 v0 (2 NUMA nodes, 6 cores / 12 threads each). By default, Proxmox distributes VM vCPUs across all cores. For NFS-heavy VMs, pinning to a single NUMA node avoids cross-NUMA memory access latency (~20-40 ns penalty per access).
- **Concrete Change:**
  ```bash
  # On pve01, identify NUMA topology:
  numactl --hardware
  # Expect: node 0 = cores 0-5 (+ HT 12-17), node 1 = cores 6-11 (+ HT 18-23)

  # Pin Plex (VM 101) to NUMA node 0:
  qm set 101 --numa 1
  # In /etc/pve/qemu-server/101.conf, add/edit:
  # numa0: cpus=0-5,hostnodes=0,memory=8192,policy=preferred

  # Pin Tdarr Server (VM 105) to same node as its NIC interrupt handler
  ```
  **Note:** Determining which NUMA node the NICs are on requires:
  ```bash
  cat /sys/class/net/nic0/device/numa_node
  cat /sys/class/net/nic1/device/numa_node
  ```
  Pin NFS-heavy VMs to the NUMA node that owns the storage NIC (nic1).
- **Expected Impact:** 5-15% reduction in NFS latency for pinned VMs, due to avoiding cross-NUMA memory copies. Most impactful for Plex (streaming) and VM 103 (downloads).
- **Risk Level:** Medium. Incorrect NUMA pinning (pinning too many vCPUs to one node) can cause CPU contention. Only pin if you verify the NUMA topology first. Start with VM 101 only.
- **Rollback:** `qm set 101 --numa 0` to disable NUMA awareness.

### 4d. Disable Memory Ballooning

- **Description:** Proxmox enables ballooning by default, which lets the hypervisor reclaim unused VM memory. On a host with 256 GB RAM and <15% utilization, ballooning is unnecessary overhead. Disabling it gives VMs guaranteed memory and avoids balloon-related latency spikes.
- **Concrete Change:**
  ```bash
  # On pve01, for each VM:
  qm set 101 --balloon 0
  qm set 102 --balloon 0
  qm set 103 --balloon 0
  qm set 105 --balloon 0
  # Do NOT touch VM 802 (Sonny only)
  ```
  Requires VM restart for some changes to take effect.
- **Expected Impact:** Eliminates occasional latency spikes caused by the balloon driver reclaiming pages. Most noticeable during Plex library scans or Arr stack indexing operations. Marginal improvement -- primarily a stability/consistency measure.
- **Risk Level:** Low. With 256 GB on pve01 and <40 GB allocated, there is zero risk of memory pressure.
- **Rollback:** `qm set 101 --balloon 1024` (or whatever the original value was).

---

## 5. pve03 Single NIC Bottleneck Mitigation

### Current State

pve03 (Asus B550-E) has a single 1 GbE NIC. All traffic flows through this one link:
- VM 104 NFS I/O to TrueNAS (read source + write transcoded files)
- Corosync heartbeat (management VLAN 2550)
- Proxmox API / web UI
- VM guest console traffic

### 5a. Traffic Prioritization via QoS (tc)

- **Description:** Use Linux traffic control (tc) on pve03 to prioritize corosync heartbeat traffic over NFS bulk data. Without this, a Tdarr transcode operation saturating the NIC could delay corosync heartbeats, causing false HA failover events.
- **Concrete Change:** On pve03, create `/etc/network/if-up.d/qos-pve03`:
  ```bash
  #!/bin/bash
  # Only apply to the physical NIC
  if [ "$IFACE" != "nic0" ]; then exit 0; fi

  # Create HTB qdisc with 3 classes
  tc qdisc add dev nic0 root handle 1: htb default 30

  # Total bandwidth: 1Gbit
  tc class add dev nic0 parent 1: classid 1:1 htb rate 1000mbit

  # Class 1:10 - Corosync/Management (guaranteed 100Mbit, can burst to 200Mbit)
  tc class add dev nic0 parent 1:1 classid 1:10 htb rate 100mbit ceil 200mbit prio 1

  # Class 1:20 - NFS storage (guaranteed 700Mbit, can burst to 900Mbit)
  tc class add dev nic0 parent 1:1 classid 1:20 htb rate 700mbit ceil 900mbit prio 2

  # Class 1:30 - Everything else (default, 200Mbit guaranteed)
  tc class add dev nic0 parent 1:1 classid 1:30 htb rate 200mbit ceil 500mbit prio 3

  # Filters: VLAN 2550 (management) -> class 10
  tc filter add dev nic0 parent 1:0 protocol 802.1Q prio 1 u32 \
      match u16 0x09F6 0x0FFF at -4 flowid 1:10

  # Filters: VLAN 25 (storage) -> class 20
  tc filter add dev nic0 parent 1:0 protocol 802.1Q prio 2 u32 \
      match u16 0x0019 0x0FFF at -4 flowid 1:20
  ```
  Make executable: `chmod +x /etc/network/if-up.d/qos-pve03`
- **Expected Impact:** Guarantees corosync heartbeats are never starved, even when Tdarr is saturating the NIC with transcode I/O. Prevents false HA failover events.
- **Risk Level:** Medium. TC rules are complex and the VLAN tag matching needs testing. Incorrect filters could misclassify traffic. Test in a maintenance window.
- **Rollback:** `tc qdisc del dev nic0 root` removes all QoS rules instantly.

### 5b. Tdarr Bandwidth Limiting

- **Description:** A simpler alternative to QoS: limit Tdarr's NFS throughput at the application level. Tdarr has a "Schedule" feature that can limit concurrent workers. Reducing GPU workers from the default to 1 at a time limits NFS contention.
- **Concrete Change:** In Tdarr Web UI (http://10.25.10.33:8265):
  - Navigate to the node "Radeon-RX580|6Core"
  - Set GPU workers to 1
  - Set CPU workers to 0 (GPU-only transcoding)
  - Enable "Limit concurrent file moves" if available
- **Expected Impact:** Limits peak NFS throughput to a single transcode stream (~30-80 Mbps for HEVC). Leaves ample bandwidth for corosync and management. Reduces transcode throughput but prevents NIC saturation.
- **Risk Level:** Low. This is an application-level limit, easily reversible.
- **Rollback:** Increase GPU workers back to previous value.

### 5c. Long-Term: Add a Second NIC (USB 3.0 Ethernet)

- **Description:** The Asus B550-E has USB 3.0 ports. A USB 3.0 to Gigabit Ethernet adapter can provide a second network path for storage traffic. While not ideal (USB adds CPU overhead and latency), it eliminates the single-NIC bottleneck entirely.
- **Concrete Change:**
  1. Purchase a USB 3.0 Gigabit Ethernet adapter (Realtek RTL8153 chipset recommended -- well-supported by Linux).
  2. Connect to a VLAN 25 access port on the switch (e.g., Gi1/12, which is already configured as Storage-VLAN25 and currently not connected).
  3. Configure on pve03:
     ```
     # /etc/network/interfaces
     auto enx<mac>
     iface enx<mac> inet manual
         mtu 9000

     auto vmbr1
     iface vmbr1 inet manual
         bridge-ports enx<mac>
         bridge-stp off
         bridge-fd 0
         mtu 9000

     auto vmbr1.25
     iface vmbr1.25 inet static
         address 10.25.25.29/24
         mtu 9000
     ```
  4. Migrate VM 104's NFS mount to use the storage VLAN IP (10.25.25.25) on VLAN 25 over the new NIC.
- **Expected Impact:** Completely separates storage traffic from management/corosync. Storage gets a dedicated 1 GbE path. Management/corosync get the existing NIC with no contention.
- **Risk Level:** Medium. USB Ethernet adds ~0.5 ms latency and consumes CPU for USB processing. Jumbo frame support varies by adapter. Test thoroughly.
- **Rollback:** Unplug USB adapter, revert /etc/network/interfaces, remount NFS to old path.

---

## 6. TrueNAS LACP bond0 Hash Policy Optimization

### Current State

TrueNAS bond0 uses **LAYER2+3** hash policy (MAC + IP addresses). This distributes traffic across the two bond members (eno2 on Gi1/11, eno3 on Gi1/8) based on the source/destination MAC and IP pair. With the current topology:

- pve01 (10.25.25.26) is the only Proxmox host-level NFS client on VLAN 25
- VMs mount via 10.25.0.25 or 10.25.255.25 (not bond0)
- pve03 (10.25.25.28) mounts via VLAN 25, but through vmbr0.25 (shared NIC -- different MAC/IP)

### 6a. Hash Policy Analysis

- **Description:** LAYER2+3 hashing means each unique (src_MAC+src_IP, dst_MAC+dst_IP) pair maps to a specific bond member. Since there are only 2-3 unique source IPs on VLAN 25, the hash distribution is limited. One bond member may carry 90%+ of the traffic. Switching to LAYER3+4 (IP + port) would distribute based on TCP port numbers, giving much better distribution for multiple NFS connections.
- **Concrete Change:**
  ```bash
  # On TrueNAS via GUI: Network -> Interfaces -> bond0 -> Edit
  # Change hash policy from LAYER2+3 to LAYER3+4

  # Or via CLI (TrueNAS SCALE):
  # Check current:
  cat /proc/net/bonding/bond0
  # Change requires midclt or GUI -- bond config changes require interface restart

  # On the Cisco switch, verify port-channel load balance:
  ssh pve01 -t "sshpass -p '<pass>' ssh admin@10.25.0.5 'show etherchannel load-balance'"
  # Should show: src-dst-ip or src-dst-ip-port
  # If it shows src-dst-mac, change it:
  # (config)# port-channel load-balance src-dst-ip
  ```
  **CRITICAL:** The switch and TrueNAS MUST use compatible hash policies. If TrueNAS uses LAYER3+4 but the switch uses src-dst-mac, traffic may be misrouted.
- **Expected Impact:** Better distribution across the two bond members when multiple NFS clients are active. With only 2-3 clients, the improvement is modest -- maybe evening out from 70/30 to 50/50 split. The real benefit comes when pve02 is onboarded to VLAN 25 (adding a third NFS client).
- **Risk Level:** Medium. Changing the hash policy requires a brief bond0 restart, which will interrupt ALL NFS traffic to/from VLAN 25. Plan for a maintenance window. The switch port-channel configuration change is non-disruptive but must match.
- **Rollback:** Change hash policy back to LAYER2+3 via TrueNAS GUI. Change switch back with `port-channel load-balance src-dst-mac`.

### 6b. Bond Traffic Monitoring

- **Description:** Before changing the hash policy, measure the current distribution to confirm the imbalance.
- **Concrete Change:**
  ```bash
  # On TrueNAS:
  # Per-member traffic counters:
  cat /proc/net/bonding/bond0
  # Look at "MII Status" and note both members are active

  # Per-interface byte counters (run twice, 10 seconds apart, calculate delta):
  cat /sys/class/net/eno2/statistics/rx_bytes
  cat /sys/class/net/eno3/statistics/rx_bytes
  cat /sys/class/net/eno2/statistics/tx_bytes
  cat /sys/class/net/eno3/statistics/tx_bytes
  ```
  If one member carries >70% of traffic, the hash policy change is worthwhile.
- **Expected Impact:** Diagnostic only. No performance change.
- **Risk Level:** Low (read-only).
- **Rollback:** N/A (read-only).

---

## Summary: Priority Order for Implementation

| Priority | Item | Expected Gain | Risk | Downtime |
|---|---|---|---|---|
| 1 | NFS mount options (1a-1d) | 10-30% NFS throughput | Low | Per-VM remount (<1 min each) |
| 2 | ZFS ARC tuning (2a) | Significant for Plex reads | Low | TrueNAS reboot for persistent |
| 3 | TCP buffer sizes (3a-3b) | 5-10% concurrent I/O | Low | None (sysctl -p) |
| 4 | NIC offload verification (3c) | 0-30% if disabled | Low | None |
| 5 | Disable ballooning (4d) | Stability improvement | Low | VM restart |
| 6 | Tdarr worker limit (5b) | pve03 stability | Low | None |
| 7 | NUMA pinning (4c) | 5-15% NFS latency | Medium | VM restart |
| 8 | Interrupt coalescing (3d) | CPU overhead reduction | Low | None |
| 9 | LACP hash policy (6a) | Better bond distribution | Medium | Brief NFS interruption |
| 10 | pve03 QoS (5a) | Corosync protection | Medium | None (additive) |
| 11 | ZFS recordsize (2b) | 5-10% sequential reads | Medium | None (new writes only) |
| 12 | USB NIC for pve03 (5c) | Eliminates bottleneck | Medium | Hardware purchase + config |

---

## Important Warnings

1. **Never change multiple tunables simultaneously.** Always: baseline -> change one -> measure -> decide -> rollback or keep.
2. **TrueNAS PSU 1 is FAILED. Fan 6 is DEAD.** Any tuning that increases TrueNAS workload (higher ARC, more NFS connections) should be accompanied by thermal monitoring. Order replacement parts FIRST.
3. **pve01 PSU 2 is FAILED.** Same caution -- increased workload on pve01 means more power draw on the single remaining PSU.
4. **Do not use `soft` NFS mounts.** Ever. Lesson #6 (SQLite corruption) was caused by exactly this class of issue. `hard` mounts are the only safe option for data-bearing NFS.
5. **Jumbo frames are fragile.** Any MTU change must be verified end-to-end (Lesson #8). The current configuration is correct -- do not touch MTU values as part of tuning.
6. **VM 103 NFS path (eno4, MTU 1500) is inherently slower.** This is by design (VLAN 66 isolation). Do not attempt to route VM 103 NFS traffic over bond0/VLAN 25 -- it would break the dirty VLAN isolation model.
