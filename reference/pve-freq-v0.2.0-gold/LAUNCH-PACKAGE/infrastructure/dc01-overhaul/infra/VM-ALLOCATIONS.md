# DC01 VM CPU/RAM Allocations

> Generated: S035-20260220
> Source: `qm config` from pve01 and pve03

---

## Our VMs (101-105)

| VMID | Name | Host | Status | vCPUs | RAM | Disk | VLANs | Notes |
|------|------|------|--------|-------|-----|------|-------|-------|
| 101 | Plex-Server | pve01 | running | 6 | 8 GB | 64G (os-drive-hdd) | 5 (Public), 2550 (Mgmt) | CPU type: host, balloon=0 |
| 102 | Arr-Stack | pve01 | running | 4 | 8 GB | 64G (os-drive-hdd) | 5 (Public), 2550 (Mgmt) | CPU type: host, balloon=0 |
| 103 | qBit-Downloader | pve01 | running | 4 | 4 GB | 64G (os-drive-hdd) | 66 (Dirty), 2550 (Mgmt) | CPU type: host, balloon=0 |
| 104 | Tdarr-Node | pve03 | running | 4 | 16 GB | 64G (os-drive-ssd) | 10 (Compute), 2550 (Mgmt) | CPU type: host, balloon=0, RX580 GPU passthrough (06:00.0+06:00.1), OVMF/UEFI |
| 105 | Tdarr-Server | pve01 | running | 2 | 4 GB | 64G (os-drive-hdd) | 10 (Compute), 2550 (Mgmt) | CPU type: host, balloon=0 |

**Totals (Our VMs):**

| Resource | pve01 (VMs 101-103, 105) | pve03 (VM 104) | Combined |
|----------|--------------------------|----------------|----------|
| vCPUs | 16 | 4 | 20 |
| RAM | 24 GB | 16 GB | 40 GB |
| Disk | 256 GB | 64 GB | 320 GB |

---

## Host Resource Utilization

### pve01 (Dell PowerEdge T620)

- **CPU:** 2x Xeon E5-2620 v0 -- 6 cores/socket, HT on = **24 logical CPUs**
- **RAM:** ~252 GB total, ~208 GB available to VMs
- **Storage:** os-drive-hdd (ZFS)

| Category | vCPUs Allocated | RAM Allocated |
|----------|-----------------|---------------|
| Our VMs (101, 102, 103, 105) | 16 | 24 GB |
| Out-of-scope VMs (420, 802, 804) | 10 | ~20 GB |
| **Total allocated** | **26** | **~44 GB** |
| **Host capacity** | **24 logical** | **~252 GB** |
| **Remaining (RAM)** | -- | **~208 GB** |

> **CPU note:** 26 vCPUs allocated against 24 logical CPUs = slight overcommit (1.08x).
> This is normal and acceptable for workloads that are not all CPU-bound simultaneously.
> Proxmox schedules vCPUs across physical cores -- light overcommit is standard practice.

### pve03 (AMD Consumer Build)

- **CPU:** 16 cores (AMD consumer CPU)
- **RAM:** 32 GB total, ~10 GB available to additional VMs
- **Storage:** os-drive-ssd (ZFS), ~850 GB free. 8 GB ZFS swap.

| Category | vCPUs Allocated | RAM Allocated |
|----------|-----------------|---------------|
| Our VMs (104) | 4 | 16 GB |
| **Total allocated** | **4** | **16 GB** |
| **Host capacity** | **16 logical** | **32 GB** |
| **Remaining** | **12** | **~10 GB** |

> **RAM note:** VM 104 consumes 50% of pve03's total RAM. With Proxmox overhead and ZFS ARC,
> only ~10 GB remains available. This host is **tight on memory** -- any new VM here must be
> carefully sized. ZFS ARC will shrink under pressure, which degrades storage performance.

---

## Key Observations

1. **pve01 has massive RAM headroom.** With ~252 GB total and only ~44 GB allocated across all
   VMs (ours + out-of-scope), there is roughly 208 GB of unused RAM. This host can comfortably
   absorb additional VMs or RAM increases to existing ones.

2. **pve03 is RAM-constrained.** VM 104 (Tdarr-Node) takes 16 GB of 32 GB total. After Proxmox
   overhead and ZFS ARC, only ~10 GB remains. Adding another VM here requires careful planning.
   The GPU passthrough makes this the only host suitable for hardware transcoding workloads.

3. **CPU overcommit on pve01 is minimal.** 26 vCPUs allocated against 24 logical CPUs (1.08x)
   is well within safe limits. Plex and Tdarr-Server are intermittent CPU users. The arr services
   are mostly idle (I/O and network bound). No action needed.

4. **pve03 has plenty of CPU headroom.** Only 4 of 16 cores allocated. CPU is not a constraint
   on this host -- RAM is the bottleneck.

5. **All our VMs use `cpu: host` and `balloon=0`.** CPU type `host` passes through all host CPU
   features (required for some workloads, optimal for single-host VMs). Ballooning is disabled
   so each VM gets its full RAM allocation guaranteed -- no memory overcommit risk.

6. **Storage is HDD-backed on pve01, SSD-backed on pve03.** VM 104 benefits from SSD storage
   for Tdarr transcode I/O. All pve01 VMs run on spinning disk -- acceptable for current
   workloads since media data lives on TrueNAS NFS anyway.

---

## Out-of-Scope VMs on pve01

These VMs are **not ours** (IDs 420, 800-899) but they consume pve01 resources:

| VMID | Name | Status | vCPUs | RAM | Disk | Notes |
|------|------|--------|-------|-----|------|-------|
| 420 | DonnyisGay | stopped | 4 | 8 GB | 64G (local-lvm) | CPU: x86-64-v2-AES. Stopped -- no active resource use. |
| 802 | Blue | running | 2 | ~4 GB | 80G (os-drive-hdd) | CPU: host. Running -- consuming resources. |
| 804 | Talos | running | 4 | ~8 GB | 80G (os-drive-hdd) | CPU: host. Running -- consuming resources. |

**Running out-of-scope total:** 6 vCPUs, ~12 GB RAM (VMs 802 + 804).

VM 420 is stopped and uses no active CPU/RAM, but its 64G disk on `local-lvm` (not `os-drive-hdd`)
occupies space on a separate storage pool.

> These VMs are outside our control. Do not modify, stop, or reconfigure them. They are noted
> here only for awareness of shared resource consumption on pve01.
