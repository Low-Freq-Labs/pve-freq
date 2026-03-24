# FIX-S034: VM 103 NFS VLAN Investigation

**Date:** 2026-02-20
**Session:** S034
**VM:** 103 (qBit-Downloader) at 10.25.255.32
**Status:** BLOCKED — Requires Sonny action in Proxmox GUI or pfSense

---

## Problem Statement

VM 103 mounts NFS from TrueNAS via the management VLAN (`10.25.255.25`) instead of the storage VLAN (`10.25.25.25`). NFS traffic should use the dedicated storage VLAN to avoid polluting management traffic.

## Investigation

### VM 103 NIC Layout

| NIC | IP | VLAN | Role |
|-----|-----|------|------|
| ens18 | 10.25.66.10/24 (DHCP) | 66 (Dirty) | Service NIC |
| ens19 | 10.25.255.32/24 (static) | 2550 (Management) | Mgmt + NFS (current) |

**No storage VLAN (25) NIC exists on this VM.**

### VM 103 Routing Table

```
default via 10.25.66.1 dev ens18 proto dhcp src 10.25.66.10 metric 1002
10.25.66.0/24 dev ens18 proto dhcp scope link src 10.25.66.10 metric 1002
10.25.100.0/24 via 10.25.255.1 dev ens19
10.25.255.0/24 dev ens19 proto kernel scope link src 10.25.255.32
```

No route to 10.25.25.0/24 exists.

### Ping Test: 10.25.25.25 from VM 103

```
2 packets transmitted, 0 received, 100% packet loss
```

**VM 103 cannot reach the storage VLAN.** The default gateway (10.25.66.1 on VLAN 66) does not route to VLAN 25. This is likely intentional — VLAN 66 is the "dirty" isolation network.

### Current NFS Mount (fstab)

```
10.25.255.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0
```

Using management VLAN IP because it's the only path available.

## Resolution Options for Sonny

### Option A: Add a Storage VLAN NIC in Proxmox (Recommended)

1. In Proxmox GUI (pve01 > VM 103 > Hardware):
   - Add > Network Device
   - Bridge: select the bridge tagged for VLAN 25 (storage)
   - VLAN Tag: 25
   - Model: VirtIO
2. Inside VM 103: configure the new NIC (ens20) with static IP `10.25.25.32/24`
3. Update `/etc/fstab`: change `10.25.255.25` to `10.25.25.25`
4. Remount NFS

**Pros:** Proper network segmentation. NFS traffic stays off mgmt VLAN.
**Cons:** Adds a third NIC to VM 103. Requires VM reboot (or hotplug if supported).

### Option B: Add a Static Route via pfSense

Add a route on the VLAN 2550 management interface so 10.25.25.0/24 is reachable:
```
up ip route add 10.25.25.0/24 via 10.25.255.1 dev ens19
```
Then update fstab to use `10.25.25.25`.

**Pros:** No Proxmox hardware change needed. Quick.
**Cons:** NFS traffic still rides the management NIC (just targets a different TrueNAS IP). Traffic still crosses VLANs through pfSense — adds latency. Not true network segmentation.

### Option C: Leave As-Is (Acceptable)

VM 103 is the only VM on the dirty VLAN. Its NFS traffic volume is downloads only (qBittorrent completed files being moved). Management VLAN can handle this.

**Pros:** No changes needed. Working today.
**Cons:** NFS on mgmt VLAN is technically wrong per DC01 standards.

## Additional Finding: VMs 101 and 102 Also Affected

During investigation, discovered that VMs 101 (Plex) and 102 (Arr-Stack) also mount NFS via `10.25.255.25` despite being able to reach `10.25.25.25`:

| VM | NFS Target | Can Reach 10.25.25.25? | Fix Possible? |
|----|------------|------------------------|---------------|
| 101 (Plex) | 10.25.255.25 | YES (via pfSense routing from VLAN 5) | YES |
| 102 (Arr-Stack) | 10.25.255.25 | YES (via pfSense routing from VLAN 5) | YES |
| 103 (qBit) | 10.25.255.25 | NO (VLAN 66 isolated) | NO (see options above) |
| 104 (Tdarr-Node) | 10.25.25.25 | YES (via pfSense routing from VLAN 10) | Already correct |
| 105 (Tdarr-Server) | 10.25.25.25 | YES (via pfSense routing from VLAN 10) | Already correct |

**VMs 101 and 102 can be fixed immediately** by updating fstab from `10.25.255.25` to `10.25.25.25` and remounting. However, note that without a dedicated storage VLAN NIC, this traffic still routes through pfSense (service NIC default gateway > pfSense > storage VLAN) rather than going direct. True fix for all VMs would be adding storage VLAN NICs.

**Not actioned** — out of scope for this task. Documenting for Sonny's decision.

## No Changes Made

VM 103 cannot reach the storage VLAN. No fix was applied. This finding is escalated to Sonny for a decision on which option to pursue.
