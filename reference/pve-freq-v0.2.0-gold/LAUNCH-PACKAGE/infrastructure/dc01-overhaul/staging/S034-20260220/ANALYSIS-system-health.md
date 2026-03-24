# DC01 System Health Analysis -- S034

**Date:** 2026-02-20
**Data captured:** ~19:30 CST
**Analyst:** Jarvis
**Scope:** pve03 deep-dive + cross-system health check (pve01, pve03, VM 101-105, TrueNAS, pfSense, switch)

---

## Table of Contents

1. [Summary of Findings](#summary-of-findings)
2. [pve03 Deep-Dive](#pve03-deep-dive)
3. [Cross-System Health](#cross-system-health)
4. [Finding Details](#finding-details)

---

## Summary of Findings

### Critical (Requires Immediate Attention)

| # | System | Issue |
|---|--------|-------|
| C-01 | pve02 | **HA LRM dead for 15 days** -- last heartbeat Thu Feb 5 19:21:30. Node is unresponsive in the cluster. |
| C-02 | pve03 | **No swap configured** -- 0B swap on a 32GB node running a 16GB VM. OOM killer is one memory spike away. |

### High (Should Be Addressed Soon)

| # | System | Issue |
|---|--------|-------|
| H-01 | pve01/pve03 | **NFS performance sysctl not tuned** -- `net.core.rmem_max` and `net.core.wmem_max` at default 212992 (208KB) on BOTH Proxmox nodes. Recommended: 16MB+ for NFS over jumbo frames. |
| H-02 | All VMs (101-105) | **NFS performance sysctl not tuned** -- Same `rmem_max`/`wmem_max` at 212992 on all VMs. |
| H-03 | pve01/pve03 | **vm.swappiness=60 (default)** -- Hypervisors should generally run lower (10-30) to avoid swapping out VM memory. pve03 has no swap at all so this is moot there, but pve01 has 8GB swap. |
| H-04 | VM 103 (qBit) | **NFS mount uses 10.25.255.25 (Management VLAN)** instead of 10.25.25.25 (Storage VLAN). All other VMs correctly use the Storage VLAN for NFS. This puts NFS traffic on the management network. |
| H-05 | TrueNAS | **Timezone set to America/Los_Angeles** -- should be America/Chicago to match all other systems. |
| H-06 | pve03 | **ZFS rpool needs feature upgrade** -- `zpool status` says "Some supported and requested features are not enabled on the pool." Action: `zpool upgrade rpool`. |
| H-07 | VM 102 & VM 103 | **Security updates available** -- `libgnutls30t64`, `libpng16-16t64`, and `linux-image-amd64` (kernel 6.12.69 -> 6.12.73) pending. |
| H-08 | pve01 vs pve03 | **pve-manager version mismatch** -- pve01 runs 9.1.5, pve03 runs 9.1.6. Several other package differences exist (see details). |
| H-09 | Switch | **NTP is not enabled** -- switch has no time sync configured. |

### Medium (Informational / Cleanup)

| # | System | Issue |
|---|--------|-------|
| M-01 | pve03 | **nic1 defined but not used** -- `iface nic1 inet manual` with MTU 9000 in interfaces file, but nic1 has no VLAN bridges and no IP. Unlike pve01, which uses nic1 for vmbr1 (storage). |
| M-02 | pve03 | **NFS ISO share mounts via LAN IP (10.25.0.26)** -- fstab mounts from pve01's LAN IP, not the storage VLAN. Works, but not consistent with the storage VLAN design. |
| M-03 | pve03 | **pve-test.sources repo enabled** -- test/unstable Proxmox repo is active. This is likely intentional (pve03 was upgraded first) but should be disabled for production stability. |
| M-04 | pve01 | **Leftover .bak file** -- `/etc/network/interfaces.d/vlan2550-mgmt.conf.bak` should be cleaned up. |
| M-05 | pve01 | **nic1 has no MTU set in main interfaces file** -- line 19 says `iface nic1 inet manual` without `mtu 9000`, but the separate vmbr1.conf file does set `mtu 9000` on nic1. This is fine operationally but inconsistent with pve03's approach. |
| M-06 | TrueNAS | **REST API deprecation warning** -- TrueNAS alerts show the deprecated REST API was used 3 times in 24 hours from 10.25.100.19. REST API will be removed in TrueNAS 26.04. Migrate to JSON-RPC 2.0 over WebSocket. |
| M-07 | VM 104 & VM 105 | **System clock synchronized: no** -- NTP service is active but clock is not yet synchronized. Likely just needs more time after boot (VM 104 uptime only 20h). |
| M-08 | pve01 | **pve-test.sources NOT present** -- pve01 does not have the test repo, but pve03 does. This explains the version mismatch. |
| M-09 | Corosync | **pve02 ring0_addr uses LAN IP (10.25.0.27)** while pve01 and pve03 use management VLAN IPs (.255.26 and .255.28). Inconsistency, though pve02 is effectively dead. |

---

## pve03 Deep-Dive

### 1. Network -- ALL PASS

**Interfaces configured:**

| Interface | MTU (Config) | MTU (Live) | IP | Status |
|-----------|-------------|------------|-----|--------|
| nic0 | 9000 | 9000 | (bridge slave) | UP |
| nic1 | 9000 | N/A | none | **NOT PRESENT in live output** |
| wlp4s0 | 1500 | 1500 | none | DOWN (WiFi, unused) |
| vmbr0 | 9000 | 9000 | 10.25.0.28/24 | UP |
| vmbr0v5 | 9000 | 9000 | 10.25.5.28/24 | UP |
| vmbr0v10 | 9000 | 9000 | 10.25.10.28/24 | UP |
| vmbr0v25 | 9000 | 9000 | 10.25.25.28/24 | UP |
| vmbr0v2550 | 9000 | 9000 | 10.25.255.28/24 | UP |

**Verdict:** All required VLAN bridges present and running at MTU 9000. Network is clean. nic1 is configured in interfaces file but not visible in live output -- likely a secondary physical NIC that is either not cabled or not present on this hardware (pve03 is different hardware than pve01's T620). See M-01.

**Routes:** Correct. Default via 10.25.0.1, VPN route (10.25.100.0/24 via 10.25.255.1) present.

**VM 104 connectivity:** tap104i0 on vmbr0v10 (Compute VLAN), tap104i1 on vmbr0v2550 (Management VLAN). Both at MTU 9000. Correct.

### 2. Storage

**ZFS Pools:**

| Pool | Size | Used | Free | Health | Notes |
|------|------|------|------|--------|-------|
| os-pool-ssd | 1.73T | 6.57G (0%) | 1.73T | ONLINE | Mirror of 2x Samsung 1.9TB SAS SSDs. VM 104 disks here. |
| rpool | 888G | 3.17G (0%) | 885G | ONLINE | Mirror of 2x Micron 960GB SSDs. **Needs feature upgrade (H-06).** |

**storage.cfg:** Matches pve01's config (shared /etc/pve/storage.cfg). Contains:
- `local` (dir) -- `/var/lib/vz`
- `local-lvm` -- **disabled** (correct, using ZFS instead)
- `os-drive-hdd` -- pve01 only (ZFS on HDDs)
- `os-drive-ssd` -- pve03 only (ZFS on SSDs)
- `os-pool-ssd` -- pve02 only (separate entry)
- `iso-storage` -- shared NFS ISO share
- `truenas-os-drive` -- HA Proxmox disk on TrueNAS NFS

**pvesm status:** Failed to run (`command not found` -- likely ran as svc-admin without PATH to PVE tools). Not a system issue.

### 3. HA (High Availability)

- **Quorum:** OK
- **Master:** pve03 (idle) -- correct, pve03 is the current HA master.
- **pve01 LRM:** idle, timestamp Fri Feb 20 19:30:32 -- healthy.
- **pve02 LRM:** `old timestamp - dead?` -- Thu Feb 5 19:21:30. **15 days dead (C-01).**
- **pve03 LRM:** idle, timestamp Fri Feb 20 19:30:35 -- healthy.
- **watchdog-mux:** active (running).
- **pve-ha-crm:** active (running).
- **pve-ha-lrm:** active (running).

### 4. Services

- **Failed services:** 0. Clean.
- **Running services:** 46 units. All expected PVE services present (pvedaemon, pveproxy, pve-cluster, corosync, pve-firewall, proxmox-firewall, etc.).
- **Notable:** chrony running (NTP), smartmontools running, ZFS zed running.

### 5. Sysctl (NFS Performance Tuning)

| Parameter | Current Value | Recommended | Status |
|-----------|--------------|-------------|--------|
| `net.core.rmem_max` | 212992 (208KB) | 16777216 (16MB) | **NOT TUNED (H-01)** |
| `net.core.wmem_max` | 212992 (208KB) | 16777216 (16MB) | **NOT TUNED (H-01)** |
| `vm.swappiness` | 60 | 10-30 for hypervisor | **Default, but moot -- no swap (C-02/H-03)** |

### 6. Fstab

```
proc /proc proc defaults 0 0
10.25.0.26:/os-pool-hdd/iso-storage  /mnt/iso-share  nfs  defaults,_netdev  0  0
```

- ISO share mounted from pve01 via LAN IP `10.25.0.26` -- works but uses LAN instead of Storage VLAN (M-02).
- **No NFS mount to TrueNAS mega-share** -- correct, pve03 does not need it directly (VMs mount their own NFS).
- **HA Proxmox disk mount** is handled by Proxmox's storage.cfg NFS definition, not fstab. Confirmed mounted in `mounts.txt` via `10.25.25.25:/mnt/mega-pool/ha-proxmox-disk`.

### 7. Corosync

pve01 and pve03 corosync configs are **identical**. Both show:
- config_version: 8
- cluster_name: dc01-cluster
- secauth: on
- ip_version: ipv4-6
- pve01: ring0_addr 10.25.255.26
- pve02: ring0_addr 10.25.0.27 (LAN -- inconsistent with others, M-09)
- pve03: ring0_addr 10.25.255.28

### 8. Kernel / Modules

- **Running kernel:** 6.17.9-1-pve (matches pve01)
- **Available kernel:** 6.17.13-1-pve is installed but not booted. Next reboot will pick it up.
- **softdog:** Listed in `/etc/modules` AND confirmed loaded (`lsmod` shows `softdog 12288 2`). Correct for HA watchdog.
- **Other notable modules:** cifs (for SMB), nfsv4, 8021q (VLAN), bonding.

### 9. iptables (Web UI Restriction)

```
-A INPUT -i vmbr0v2550 -p tcp --dport 8006 -j ACCEPT
-A INPUT -s 10.25.0.26/32 -p tcp --dport 8006 -j ACCEPT
-A INPUT -i lo -p tcp --dport 8006 -j ACCEPT
-A INPUT -p tcp --dport 8006 -j DROP
```

Correct. Port 8006 (Proxmox Web UI) only accessible from:
1. Management VLAN (vmbr0v2550)
2. pve01 cluster peer (10.25.0.26)
3. Localhost

All other access is DROPped. Matches the Phase 1 security hardening from the overhaul.

---

## Cross-System Health

### Disk Usage (All Systems)

| System | Filesystem | Size | Used | Use% | Status |
|--------|-----------|------|------|------|--------|
| pve01 | /dev/mapper/pve-root | 94G | 8.1G | 10% | OK |
| pve03 | rpool/ROOT/pve-1 | 861G | 3.2G | 1% | OK |
| VM 101 (Plex) | /dev/sda1 | 60G | 2.8G | 5% | OK |
| VM 102 (Arr-Stack) | /dev/sda1 | 60G | 6.6G | 12% | OK |
| VM 103 (qBit) | /dev/sda1 | 60G | 2.7G | 5% | OK |
| VM 104 (Tdarr-Node) | /dev/sda2 | 59G | 7.1G | 13% | OK |
| VM 105 (Tdarr-Server) | /dev/sda1 | 60G | 8.0G | 15% | OK |
| TrueNAS (boot-pool) | boot-pool/ROOT/25.10.1 | 108G | 105M | 1% | OK |
| TrueNAS (mega-pool) | mega-pool/nfs-mega-share | 21T | 745G | 4% | OK |

**No system is above 80%. All clear.**

### Memory Usage

| System | Total | Used | Available | Swap | Status |
|--------|-------|------|-----------|------|--------|
| pve01 | 251Gi | 40Gi | 210Gi | 8Gi (0% used) | OK |
| pve03 | 31Gi | 21Gi | 10Gi | **0B (NONE)** | **WARNING (C-02)** |
| VM 101 (Plex) | 7.8Gi | 521Mi | 7.3Gi | 3.3Gi (0%) | OK |
| VM 102 (Arr-Stack) | 7.8Gi | 1.7Gi | 6.1Gi | 3.3Gi (0%) | OK |
| VM 103 (qBit) | 3.8Gi | 612Mi | 3.2Gi | 3.3Gi (1.3% used) | OK |
| VM 104 (Tdarr-Node) | 15Gi | 587Mi | 15Gi | 3.3Gi (0%) | OK |
| VM 105 (Tdarr-Server) | 3.8Gi | 591Mi | 3.3Gi | 3.3Gi (0%) | OK |
| TrueNAS | 86Gi | 62Gi | 23Gi | 0B (NONE) | OK (ZFS ARC uses RAM by design) |

pve03 has 31GB total, VM 104 is allocated 16GB, leaving ~15GB for the hypervisor. Currently 10Gi available. With **no swap at all**, any memory pressure will trigger OOM killer immediately. This is risky.

### Uptime

| System | Uptime | Status |
|--------|--------|--------|
| pve01 | 1 day, 8h | OK (recent reboot Feb 19) |
| pve03 | 2 days, 10h | OK (recent reboot Feb 18) |
| VM 101 (Plex) | 4h 6m | OK (recently started) |
| VM 102 (Arr-Stack) | 4h 31m | OK (recently started) |
| VM 103 (qBit) | 1 day, 8h | OK |
| VM 104 (Tdarr-Node) | 20h 53m | OK |
| VM 105 (Tdarr-Server) | 1 day, 8h | OK |
| TrueNAS | 2 days, 4h | OK |
| pfSense | 23h 18m | OK |

All systems recently rebooted (likely kernel update cycle). No abnormal uptimes.

### Load Average

| System | Load (1/5/15 min) | CPUs (est.) | Status |
|--------|-------------------|-------------|--------|
| pve01 | 2.85 / 2.81 / 2.68 | Many (dual Xeon) | OK -- low relative to CPU count |
| pve03 | 2.00 / 2.00 / 2.00 | Fewer | OK -- steady, likely Tdarr transcoding |
| VM 101 | 0.00 / 0.00 / 0.00 | 4 | OK -- idle |
| VM 102 | 0.40 / 0.22 / 0.17 | 4 | OK |
| VM 103 | 0.00 / 0.00 / 0.00 | 2 | OK -- idle |
| VM 104 | 1.01 / 1.01 / 1.00 | 4 | OK -- steady GPU transcode load |
| VM 105 | 0.04 / 0.05 / 0.01 | 2 | OK |
| TrueNAS | 0.20 / 0.06 / 0.02 | Dual Xeon | OK |
| pfSense | 0.32 / 0.20 / 0.17 | 4 | OK |

### Kernel Versions

| System | Kernel | Status |
|--------|--------|--------|
| pve01 | 6.17.9-1-pve | OK (6.17.13 available, not yet booted) |
| pve03 | 6.17.9-1-pve | OK (6.17.13 available, not yet booted) |
| VM 101 | 6.12.69+deb13-amd64 | **Update available: 6.12.73 (H-07)** |
| VM 102 | 6.12.69+deb13-amd64 | **Update available: 6.12.73 (H-07)** |
| VM 103 | 6.12.69+deb13-amd64 | **Update available: 6.12.73 (H-07)** |
| VM 104 | 6.12.73+deb13-amd64 | OK (already updated) |
| VM 105 | 6.12.69+deb13-amd64 | OK (no update listed in apt) |
| TrueNAS | 6.12.33-production+truenas | OK (managed by TrueNAS) |
| pfSense | FreeBSD 16.0-CURRENT | OK (managed by pfSense) |

### APT Upgrades Available

| System | Packages | Status |
|--------|----------|--------|
| pve01 | None | OK |
| pve03 | None | OK |
| VM 101 | None | OK |
| VM 102 | libgnutls30t64, libpng16-16t64, linux-image-amd64 | **3 security updates (H-07)** |
| VM 103 | libgnutls30t64, libpng16-16t64, linux-image-amd64 | **3 security updates (H-07)** |
| VM 104 | None | OK |
| VM 105 | None | OK |

### Failed Services

| System | Failed Units | Status |
|--------|-------------|--------|
| pve01 | 0 | OK |
| pve03 | 0 | OK |
| VM 101 | 0 | OK |
| VM 102 | 0 | OK |
| VM 103 | 0 | OK |
| VM 104 | 0 | OK |
| VM 105 | 0 | OK |

**All clear. Zero failed services across the entire stack.**

### NTP / Time Sync

| System | Timezone | NTP Active | Clock Synced | Status |
|--------|----------|-----------|-------------|--------|
| pve01 | America/Chicago | yes | yes | OK |
| pve03 | America/Chicago | yes | yes | OK |
| VM 101 | America/Chicago | yes | yes | OK |
| VM 102 | America/Chicago | yes | yes | OK |
| VM 103 | America/Chicago | yes | yes | OK |
| VM 104 | America/Chicago | yes | **no** | **WARNING (M-07)** |
| VM 105 | America/Chicago | yes | **no** | **WARNING (M-07)** |
| TrueNAS | **America/Los_Angeles** | N/A | N/A | **WRONG TIMEZONE (H-05)** |
| pfSense | N/A (FreeBSD) | ntpd running | yes (synced to 107.172.222.7) | OK |
| Switch | N/A | **NTP not enabled** | N/A | **NO NTP (H-09)** |

### Proxmox Package Differences (pve01 vs pve03)

| Package | pve01 | pve03 | Note |
|---------|-------|-------|------|
| pve-manager | 9.1.5 | **9.1.6** | pve03 is newer |
| proxmox-widget-toolkit | 5.1.5 | **5.1.6** | pve03 is newer |
| pve-container | 6.1.1 | **6.1.2** | pve03 is newer |
| proxmox-backup-client | 4.1.2-1 | **4.1.4-1** | pve03 is newer |
| pve-firmware | 3.17-2 | **3.18-1** | pve03 is newer |
| pve-qemu-kvm | 10.1.2-6 | **10.1.2-7** | pve03 is newer |
| pve-edk2-firmware | same | same | |
| microcode | intel-microcode (3.20251111) | amd64-microcode (3.20251202) | Different CPUs |

pve03 is running newer packages likely because it has `pve-test.sources` enabled while pve01 does not.

### NFS Mount Consistency

| VM | NFS Server IP | VLAN | Status |
|----|--------------|------|--------|
| VM 101 (Plex) | 10.25.25.25 | Storage (25) | OK |
| VM 102 (Arr-Stack) | 10.25.25.25 | Storage (25) | OK |
| VM 103 (qBit) | **10.25.255.25** | **Management (2550)** | **WRONG VLAN (H-04)** |
| VM 104 (Tdarr-Node) | 10.25.25.25 | Storage (25) | OK |
| VM 105 (Tdarr-Server) | 10.25.25.25 | Storage (25) | OK |

All VMs use consistent NFS mount options: `nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg`. Good.

---

## Finding Details

### C-01: pve02 HA LRM Dead (15 Days)

**Impact:** Cluster HA quorum is maintained (2 of 3 nodes), but pve02 is a dead weight. Any HA resources assigned to pve02 cannot be managed. Cluster logs will fill with warnings.

**Action:** Either recover pve02 or formally remove it from the cluster. The memory doc notes "LRM dead 15+ days -- needs removal or recovery."

### C-02: pve03 No Swap

**Impact:** pve03 has 31GB RAM with VM 104 allocated 16GB. Currently 10Gi available. With zero swap, any memory spike (ZFS ARC growth, kernel cache pressure, Tdarr process spike) will trigger the OOM killer immediately with no buffer.

**Action:** Either:
- Add a swap zvol: `zfs create -V 8G rpool/swap && mkswap /dev/zvol/rpool/swap && swapon /dev/zvol/rpool/swap` (and add to fstab)
- Or reduce VM 104's memory allocation if it does not need the full 16GB

### H-01 / H-02: NFS Performance Sysctl Not Tuned

**Impact:** Default socket buffer sizes (208KB) limit NFS throughput, especially over jumbo frame (MTU 9000) networks. Clients cannot fill the larger frames efficiently.

**Action:** On all systems doing NFS (pve01, pve03, VM 101-105), create `/etc/sysctl.d/99-nfs-performance.conf`:
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
```
Then `sysctl --system` to apply.

### H-04: VM 103 NFS on Management VLAN

**Impact:** NFS data traffic (downloads) goes over the management VLAN instead of the dedicated storage VLAN. This mixes data plane and management plane traffic.

**Action:** Change VM 103 fstab from `10.25.255.25` to `10.25.25.25`. Requires VM 103 to have a NIC on VLAN 25 (Storage). Verify its network config first -- it may only have VLAN 66 (Dirty) and VLAN 2550 (Mgmt) NICs, in which case adding a Storage VLAN NIC is needed.

### H-05: TrueNAS Wrong Timezone

**Impact:** Log timestamps will be 2 hours behind (Pacific vs Central). Makes cross-system log correlation difficult.

**Action:** TrueNAS Web UI > System > General Settings > change timezone from `America/Los_Angeles` to `America/Chicago`.

### H-09: Switch NTP Not Enabled

**Impact:** Switch clock will drift. Log timestamps unreliable for troubleshooting.

**Action:** Configure NTP on the Cisco 4948E-F:
```
ntp server 10.25.0.1
```
(Using pfSense as the NTP source, or use a public NTP server.)

---

## Overall Health Score

| Category | Score | Notes |
|----------|-------|-------|
| Network | 9/10 | All MTUs correct, all VLANs up. Minor: VM103 NFS on wrong VLAN. |
| Storage | 9/10 | All ZFS pools healthy, no errors. Minor: rpool needs feature upgrade. |
| Services | 10/10 | Zero failed services across all 7 Linux systems. |
| Security | 9/10 | Web UI iptables correct, sudoers clean. Pending: SSH key deployment. |
| Time Sync | 7/10 | TrueNAS wrong timezone, switch no NTP, 2 VMs not yet synced. |
| Updates | 8/10 | Security updates pending on VM 102/103, PVE package mismatch. |
| HA/Cluster | 6/10 | pve02 dead for 15 days, pve03 no swap. |
| Performance | 7/10 | NFS sysctl not tuned on any system. |

**Overall: 8/10 -- Good, with specific items needing attention.**

---

## Recommended Priority Order

1. **C-02** -- Add swap to pve03 (prevent OOM, 5-minute fix)
2. **H-07** -- Apply security updates on VM 102/103 (`apt update && apt upgrade`)
3. **H-05** -- Fix TrueNAS timezone (30-second Web UI change)
4. **H-04** -- Fix VM 103 NFS mount to use Storage VLAN
5. **H-01/H-02** -- Deploy NFS sysctl tuning across all systems
6. **H-06** -- Upgrade rpool features on pve03 (`zpool upgrade rpool`)
7. **H-09** -- Enable NTP on the switch
8. **C-01** -- Decide on pve02: recover or remove from cluster
9. **H-08** -- Either update pve01 to match pve03, or remove pve-test.sources from pve03
