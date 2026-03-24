# DC01 Infrastructure Architecture

> **Source of truth:** DC01.md (Session 18 rewrite, updated through S039, 2026-02-23)
> **Maintained by:** Worker #1 (Infrastructure Architect)
> **Last updated:** 2026-02-23 (S039 — VLAN traffic segregation: pve03 ISO NFS→Storage VLAN, VM 102/105 Docker port binding, exceptions documented)

---

## 1. Overview

DC01 is a colocated 3-node Proxmox VE cluster at a GigeNet facility, serving as the primary infrastructure for media automation (Plex, Arr stack, Tdarr transcoding, qBittorrent downloads) and general-purpose compute. The cluster uses a Dell PowerEdge R530 running TrueNAS as its NFS storage backend, with a Cisco WS-C4948E-F as the core switch and a pfSense Plus appliance as the perimeter firewall.

The environment is segmented across six VLANs (LAN, Public, Compute, Storage, Dirty, Management) with jumbo frames end-to-end, LACP-bonded storage and firewall uplinks, and WireGuard VPN for remote administration from a WSL2 workstation.

There is currently **no full VM backup strategy** (no Proxmox Backup Server) -- daily Docker config backups were deployed in S032/S034 (tar to local + NFS, 7-day retention). PBS evaluation is pending.

---

## 2. Physical Hardware

### Dell PowerEdge R530 -- TrueNAS (10.25.0.25)

| Field | Value |
|---|---|
| iDRAC | 10.25.255.10 (LOM1 on Gi1/10 trunk, VLAN 2550 tagged) |
| Service Tag | B065ND2 |
| CPUs | 2x Xeon E5-2620 v3 |
| RAM | 88 GB (mixed DIMMs) |
| RAID | PERC H730P (JBOD mode) |
| Disks | 8x 6 TB HGST SAS |
| NICs | 4x BCM5720 1 GbE (eno1-eno4) |
| iDRAC FW | 2.85.85.85 |

**Active Alerts:**
- **PSU 1 FAILED** -- Dell 05RHVVA00, 750W Delta. Running on single PSU. No power redundancy.
- **Fan 6 DEAD** -- 0 RPM, all fans report "Redundancy Lost."

### Dell PowerEdge T620 -- pve01 (10.25.0.26)

| Field | Value |
|---|---|
| iDRAC | 10.25.255.11 (Dedicated port on Gi1/5, VLAN 2550 access) |
| Service Tag | 69MGVV1 |
| CPUs | 2x Xeon E5-2620 v0 |
| RAM | 256 GB |
| NICs | 2x Intel I350 1 GbE |
| iDRAC FW | 2.65.65.65 |

**Active Alerts:**
- **PSU 2 FAILED** -- Dell 06W2PWA00, 750W Flex. Running on single PSU. No power redundancy.

### Asus B550-E -- pve03 (10.25.0.28)

| Field | Value |
|---|---|
| IPMI | None (consumer motherboard) |
| CPUs | Consumer AMD (details not documented) |
| RAM | 31 GB |
| NICs | 1x 1 GbE (single NIC -- bottleneck risk) |
| GPU | Radeon RX 580 (PCIe passthrough to VM 104) |

No hardware alerts. Consumer-grade board with no out-of-band management.

### Replacement Parts Needed

| Server | Component | Dell Part # | Model | Notes |
|---|---|---|---|---|
| R530 (TrueNAS) | PSU 1 | 05RHVVA00 | 750W Delta RDNT | Match working PSU 2 (same model) |
| R530 (TrueNAS) | Fan 6 | -- | Embedded fan assembly | Hot-swappable. Search by Service Tag B065ND2 |
| T620 (pve01) | PSU 2 | 06W2PWA00 | 750W Flex RDNT | Working PSU 1 is 05NF18A01 (also 750W Delta) |

**Ordering these parts is URGENT.** Both the TrueNAS storage server and the primary hypervisor are running on single PSUs with zero power redundancy.

---

## 3. Cluster Topology

### Node Summary

| Node | Hostname | Hardware | Kernel | RAM | Hosted VMs | Role Notes |
|---|---|---|---|---|---|---|
| 1 | pve01 | Dell T620 | 6.17.9-1-pve | 256 GB | 101, 102, 103, 105, 420, 802, 804 | Primary hypervisor. 2 NICs. ipmitool + sshpass installed. |
| 2 | pve02 | Unknown | 6.17.9-1-pve | 125 GB | 100 (SABnzbd) | **OUT OF SCOPE.** LRM dead 15+ days (TICKET-0008). No VLAN 25 or 2550. os-pool-ssd storage. |
| 3 | pve03 | Asus B550-E | 6.17.9-1-pve | 32 GB | 104 (Tdarr Node) | HA master. Single NIC. RX 580 passthrough. 8GB ZFS swap (S034). |

**Admins:** sonny-aif, chrisadmin, donmin, jonnybegood
**svc-admin (UID 3003, GID 950):** Primary service account. NOPASSWD sudo on all 10 systems. Proxmox PAM admin. Docker group member on all VMs. Standardized S026.
**sonny-aif (UID 3000, GID 950):** Personal admin account. Will be nerfed to minimal access after SSH key deployment. Cannot run `qm list` directly -- use Proxmox REST API instead (see Lesson #9).

### Node Interface Table

| Node | Interface | IP | VLAN | Switch Port | MTU | Role |
|---|---|---|---|---|---|---|
| pve01 | nic0 -> vmbr0 | 10.25.0.26/24 | 1 (trunk native) | Gi1/1 | 9000 | Primary bridge (VMs + host VLAN 1) |
| pve01 | nic1 -> vmbr1 | -- | trunk | Gi1/9 | 9000 | Dedicated storage NIC (Session 17) |
| pve01 | vmbr1.25 | 10.25.25.26/24 | 25 | Gi1/9 | 9000 | Host storage (dedicated NIC, separate from VM traffic) |
| pve01 | vmbr0v2550 | 10.25.255.26/24 | 2550 | (via Gi1/1 trunk) | 9000 | Host management (Proxmox VLAN bridge) |
| pve02 | eno3 -> vmbr0 | 10.25.0.27/24 | 1 (trunk native) | Gi1/3 | 9000 | Primary bridge |
| pve02 | eno1np0 | -- | -- | Gi1/4 | -- | Second NIC, unconfigured |
| pve02 | (missing) | -- | 25 | -- | -- | **VLAN 25 storage NOT configured** (homework) |
| pve02 | (missing) | -- | 2550 | -- | -- | **VLAN 2550 management NOT configured** (homework) |
| pve03 | nic0 -> vmbr0 | 10.25.0.28/24 | 1 (trunk native) | Gi1/2 | 9000 | Primary bridge (single NIC -- all traffic) |
| pve03 | vmbr0v5 | 10.25.5.28/24 | 5 | (via Gi1/2 trunk) | 9000 | VLAN 5 Public (Proxmox VLAN bridge) |
| pve03 | vmbr0v10 | 10.25.10.28/24 | 10 | (via Gi1/2 trunk) | 9000 | Compute VLAN (added S031, persisted in vlan10-compute.conf) |
| pve03 | vmbr0v25 | 10.25.25.28/24 | 25 | (via Gi1/2 trunk) | 9000 | Host storage (Proxmox VLAN bridge) |
| pve03 | vmbr0v2550 | 10.25.255.28/24 | 2550 | (via Gi1/2 trunk) | 9000 | Host management (Proxmox VLAN bridge) |

**Key design difference:** pve01 has dedicated storage on a second NIC (vmbr1.25 on Gi1/9), while pve03 shares its single NIC for all traffic including storage (vmbr0v25 on Gi1/2).

### Corosync Configuration

| Field | Value |
|---|---|
| Config version | 8 |
| Transport | knet |
| pve01 ring0 | 10.25.255.26 (VLAN 2550) |
| pve02 ring0 | 10.25.0.27 (VLAN 1 -- no VLAN 2550 configured) |
| pve03 ring0 | 10.25.255.28 (VLAN 2550) |

Cross-VLAN routing between ring0 addresses is verified working. The VLAN 2550 split-brain bug (vmbr0.2550 vs vmbr0v2550) was resolved in Session 17 and had previously broken corosync connectivity.

### HA Configuration

| Component | pve01 | pve02 | pve03 |
|---|---|---|---|
| pve-ha-lrm | enabled, running | DEAD 15+ days (TICKET-0008) | enabled, running |
| pve-ha-crm | enabled, running | DEAD 15+ days (TICKET-0008) | enabled, running |
| Watchdog module | softdog (persistent via /etc/modules) | -- | softdog (persistent via /etc/modules) |
| watchdog-mux | running | -- | running |

- **Current HA master:** pve03
- **Shared storage for HA:** `truenas-os-drive` (NFS, 20 TB, mounted at `/mnt/pve/ha-proxmox-disk`)

---

## 4. Network Architecture

### VLAN Map

| VLAN | Subnet | pfSense Interface | Switch SVI | Description | pfSense Policy |
|---|---|---|---|---|---|
| 1 | 10.25.0.0/24 | lagg0 (LAN) | Vlan1: 10.25.0.5 | Main LAN -- servers & legacy | Default allow |
| 5 | 10.25.5.0/24 | lagg0.5 (Public) | Vlan5: 10.25.5.5 | Public-facing services (Plex, Arr) | RFC1918 block + NFS exception (10.25.25.25) + internet pass |
| 10 | 10.25.10.0/24 | lagg0.10 (Compute) | Vlan10: 10.25.10.5 | Compute (Tdarr) -- no internet | Local only |
| 25 | 10.25.25.0/24 | lagg0.25 (Storage) | Vlan25: 10.25.25.5 | Dedicated storage network | Local only, no outbound |
| 66 | 10.25.66.0/24 | lagg0.66 (DIRTY) | -- (none) | Dirty/untrusted (qBit+VPN) | RFC1918 block + NAT via 69.65.20.61 |
| 2550 | 10.25.255.0/24 | lagg0.2550 (Management) | Vlan2550: 10.25.255.5 | Out-of-band management | Block rule in place |
| -- | 10.25.100.0/24 | tun_wg0 (WG0) | -- | WireGuard VPN clients | -- |

### Inter-VLAN Routing Design

Not all VLANs use pfSense as their gateway. This is by design:

| VLAN | Gateway | Why |
|---|---|---|
| 1 (LAN) | 10.25.0.1 (pfSense) | Full internet, default allow |
| 5 (Public) | 10.25.5.1 (pfSense) | Needs internet + RFC1918 filtering |
| 10 (Compute) | **10.25.10.5 (Switch SVI)** | No internet needed. pfSense rules would block NFS to 10.25.25.25. Switch SVI routes NFS directly via L3 switching. |
| 25 (Storage) | 10.25.25.5 (Switch SVI) | Local only storage network |
| 66 (Dirty) | 10.25.66.1 (pfSense) | Needs internet NAT via dirty VIP |
| 2550 (Mgmt) | 10.25.255.5 (Switch SVI) | pfSense has block rule. Switch SVI handles inter-VLAN. |

### Network Devices

| Device | OS IP | Mgmt/iDRAC IP | Model | Notes |
|---|---|---|---|---|
| Firewall (fw01) | 10.25.0.1 | -- | pfSense Plus (FreeBSD 16.0) | WAN: 100.101.14.2/28. WebGUI port **4443** (VPN->.255.1 only). LACP lagg0 (igc2+igc3). Anti-lockout disabled. |
| Core Switch | 10.25.0.5 | -- | Cisco WS-C4948E-F | IOS 15.2(4)E10a, hostname `gigecolo`. Direct SSH via `ssh gigecolo` (VPN, .255.5). Legacy: pve01 jump host. |
| TrueNAS | 10.25.0.25 | 10.25.255.10 | Dell PowerEdge R530 | See Physical Hardware |
| pve01 | 10.25.0.26 | 10.25.255.11 | Dell PowerEdge T620 | See Physical Hardware |
| pve02 | 10.25.0.27 | 10.25.0.12 (cable not plugged in) | Unknown | OUT OF SCOPE |
| pve03 | 10.25.0.28 | -- (no IPMI) | Asus B550-E | Consumer board |

### Firewall Public IPs

| IP | Purpose |
|---|---|
| 100.101.14.2/28 | Transit/upstream subnet |
| 69.65.20.58 | **Primary public VIP** (WireGuard endpoint, Plex port forward) -- SACRED, do not change without VPN migration plan |
| 69.65.20.62 | Public VIP 2 |
| 69.65.20.61 | VLAN 66 Dirty NAT outbound |
| 69.65.20.56/29 | Full routed block (usable .57-.62). Default gw: 100.101.14.1 |

### pfSense LAGG Status

pfSense LAN interface uses lagg0 in **LACP mode** (802.3ad). Members: igc2 (Gi1/47) + igc3 (Gi1/48), both ACTIVE/COLLECTING/DISTRIBUTING. MTU 9000. Switch side: Port-channel2 (LACP, SU). Converted from failover → LACP in S032.

### Switch Port Map (Cisco 4948E-F -- 10.25.0.5)

**Layout:** Ports 1-12 = nodes/infrastructure, Ports 13-24 = available, Ports 25-46 = VLAN 66 dirty pool, Ports 47-48 = pfSense LACP (Po2).

#### Ports 1-12: Nodes & Infrastructure

| Port | Name | Status | VLAN Config | Connected Device |
|---|---|---|---|---|
| Gi1/1 | Hypervisor-Trunk | connected | trunk (1,5,10,25,66,2550) | pve01 nic0 (vmbr0) |
| Gi1/2 | Hypervisor-Trunk | connected | trunk (1,5,10,25,66,2550) | pve03 nic0 (vmbr0) |
| Gi1/3 | Hypervisor-Trunk | connected | trunk (1,5,10,25,66,2550) | pve02 NIC 1 |
| Gi1/4 | Hypervisor-Trunk | connected | trunk (1,5,10,25,66,2550) | pve02 NIC 2 |
| Gi1/5 | Management-VLAN2550 | connected | access 2550 | pve01 iDRAC dedicated port (10.25.255.11) |
| Gi1/6 | Management-VLAN2550 | not connected | access 2550 | Reserved: pve02 iDRAC |
| Gi1/7 | Management-VLAN2550 | connected | access 2550 | TrueNAS eno4 (10.25.255.25) |
| Gi1/8 | Storage-VLAN25 | connected | access 25 | TrueNAS eno3 (bond0 member, LACP Po1) |
| Gi1/9 | Hypervisor-Trunk | connected | trunk (1,5,10,25,66,2550) | pve01 nic1 (vmbr1) -- dedicated storage |
| Gi1/10 | TrueNAS-eno1-iDRAC-LOM | connected | trunk (native 1, allowed 2550) | TrueNAS eno1 (10.25.0.25) + iDRAC LOM (10.25.255.10 tagged 2550) |
| Gi1/11 | Storage-VLAN25 | connected | access 25 | TrueNAS eno2 (bond0 member, LACP Po1) |
| Gi1/12 | Storage-VLAN25 | not connected | access 25 | Spare |
| **Po1** | **Port-channel1** | **connected** | **access 25** | **LACP: Gi1/8+Gi1/11 -> TrueNAS bond0 (storage)** |

#### Ports 13-24: Available Infrastructure

| Port | Name | VLAN | Notes |
|---|---|---|---|
| Gi1/13-20 | Storage-VLAN25 | access 25 | Available for future storage NICs |
| Gi1/21-24 | Public-VLAN5 | access 5 | Available for future public-facing devices |

#### Ports 25-47: VLAN 66 Dirty Pool

| Port | Name | VLAN | Notes |
|---|---|---|---|
| Gi1/25-35 | DIRTY-VLAN66 | access 66 | Dirty/untrusted devices |
| Gi1/36 | (no description) | access 1 | **NOT OUR HARDWARE -- DO NOT TOUCH** |
| Gi1/37-46 | DIRTY-VLAN66 | access 66 | Dirty/untrusted devices |

#### Ports 47-48: pfSense LACP Uplink (Po2)

| Port | Name | Status | VLAN | Connected Device |
|---|---|---|---|---|
| Gi1/47 | pfSense-LACP | connected (Po2 member) | trunk (1,5,10,25,66,2550) | pfSense igc2 (lagg0 LACP member) |
| Gi1/48 | pfSense-LACP | connected (Po2 member) | trunk (1,5,10,25,66,2550) | pfSense igc3 (lagg0 LACP member) |
| **Po2** | **Port-channel2** | **SU (Layer2, In Use)** | **trunk (1,5,10,25,66,2550)** | **LACP: Gi1/47(P) + Gi1/48(P) -> pfSense lagg0. MTU 9198. Created S032.** |
| Te1/49-52 | -- | not connected | -- | 10 GbE (no X2 modules installed) |

**Orphaned VLANs:** VLANs 113 and 715 investigated S034 and removed S035. Zero ports, zero SVIs, zero trunk carriage -- confirmed safe and deleted.

### Jumbo Frame Configuration

Jumbo frames (MTU 9000) are configured end-to-end. All components must match or NFS silently fails (Lesson #8).

| Component | MTU | Notes |
|---|---|---|
| Switch (all ports) | 9198 | System-wide setting |
| Proxmox hosts (vmbr0, sub-interfaces) | 9000 | All bridges and VLAN interfaces |
| VMs (ens18, ens19) | 9000 | Both service and management NICs |
| TrueNAS (eno1, bond0) | 9000 | LAN and storage interfaces |
| TrueNAS (eno4) | 1500 | Management NIC -- no jumbo frames |

### WireGuard VPN

| Field | Value |
|---|---|
| Server | pfSense fw01 (10.25.0.1) |
| Tunnel network | 10.25.100.0/24 |
| Public endpoint | **69.65.20.58** (SACRED -- see Lesson #1) |
| WSL client IP | 10.25.100.19 |
| WSL client config | /etc/wireguard/wg0.conf (root-only, chmod 600) |
| Routes pushed | 10.25.0.0/24, 10.25.5.0/24, 10.25.10.0/24, 10.25.25.0/24, 10.25.100.0/24, 10.25.255.0/24 (S039: added Storage VLAN) |

**VPN Reachability:**

| Subnet | Reachable? | Notes |
|---|---|---|
| 10.25.0.0/24 (LAN) | Yes | Direct |
| 10.25.5.0/24 (Public) | Yes | pfSense routes |
| 10.25.10.0/24 (Compute) | Yes | Fixed S023: switch static route + VM static routes + pfSense rules |
| 10.25.255.0/24 (Mgmt) | Yes | Fixed S023: same mechanism |
| 10.25.66.0/24 (Dirty) | Yes | Fixed S023: same mechanism |

All VLANs reachable from VPN since Session 23. Switch static route `ip route 10.25.100.0 255.255.255.0 10.25.0.1` saved. VM static routes `10.25.100.0/24 via 10.25.255.1 dev ens19` persisted on all 5 VMs.

### WSL Workstation (Admin Interface)

| Field | Value |
|---|---|
| Hostname | wsl-debian |
| OS | Linux (WSL2) -- Kernel 6.6.87.2-microsoft-standard-WSL2 |
| User | sonny-aif (uid=3000, gid=950) |
| VPN IP | 10.25.100.19 (WireGuard) |
| Packages | openssh-client, sshpass, cifs-utils |

**SMB mount:** `/mnt/smb-sonny` → `//10.25.25.25/smb-share/sonny` (Jarvis memory logs, S039: moved to Storage VLAN). Auto-mount via `.bashrc` (fails silently if VPN down). Passwordless sudo for mount only (`/etc/sudoers.d/smb-sonny`). Symlinks: `~/CLAUDE.md`, `~/Jarvis & Sonny's Memory/`.

---

## 5. Storage Architecture

### TrueNAS ZFS Pool

| Field | Value |
|---|---|
| Pool name | mega-pool |
| Status | ONLINE, no errors |
| Layout | 2x RAIDZ2 vdevs (4 disks each, 8 total) |
| Capacity | ~22 TB total, ~740 GB used (4%), ~21 TB free |
| Last scrub | 2026-02-08, 0 errors |

### ZFS Datasets

| Dataset | Mount Point | Purpose |
|---|---|---|
| mega-pool/nfs-mega-share | /mnt/mega-pool/nfs-mega-share | Primary NFS share (media data only -- compose files and configs moved local to /opt/dc01/ in S032) |
| mega-pool/ha-proxmox-disk | /mnt/mega-pool/ha-proxmox-disk | Proxmox HA shared storage (20 TB, world-accessible NFS) |
| mega-pool/smb-share | /mnt/mega-pool/smb-share | SMB share for Jarvis memory logs |

### NFS Export Configuration

```
/mnt/mega-pool/nfs-mega-share
  Networks: 172.28.16.0/20, 10.25.100.0/24, 10.25.0.0/24, 10.25.25.0/24,
            10.25.10.0/24, 10.25.5.0/24, 10.25.255.0/24
  Options: rw, all_squash, no_subtree_check
  mapall_user: svc-admin (uid=3003), mapall_group: truenas_admin (gid=950)

/mnt/mega-pool/ha-proxmox-disk
  Networks: * (world-accessible)
  Options: rw, no_subtree_check
```

**NFS squash behavior:** `all_squash` maps ALL incoming writes to uid/gid=950. The UID of the writing user does not matter -- what matters is that PGID 950 matches across systems. Currently 7 networks are allowed on nfs-mega-share -- an audit to reduce this to the minimum is a pending hardening task.

### NFS Mount Strategy Per VLAN

Different VLANs reach TrueNAS via different IPs depending on their network isolation:

| VLAN | TrueNAS IP Used | Interface | Why |
|---|---|---|---|
| 1 (LAN) | 10.25.0.25 | eno1 | Same VLAN, direct L2 |
| 5 (Public) | 10.25.25.25 | bond0 | NFS/SMB bound to Storage+Mgmt VLANs only (S029). VMs route via switch SVI. |
| 10 (Compute) | 10.25.25.25 | bond0 | Switch SVI routes directly. TrueNAS has static route for return. |
| 66 (Dirty) | **10.25.255.25** | **eno4** | VLAN 66 is isolated. Management NIC provides L2 path via VLAN 2550. |
| 25 (Storage) | 10.25.25.25 | bond0 | Direct L2 on storage VLAN (Proxmox host-level mounts) |

### TrueNAS Static Routes (persistent via midclt)

| Destination | Gateway | Purpose |
|---|---|---|
| 10.25.5.0/24 | 10.25.0.5 (switch SVI) | VLAN 5 return traffic via switch, not pfSense (prevents asymmetric routing) |
| 10.25.10.0/24 | 10.25.0.5 (switch SVI) | VLAN 10 return traffic via switch, not pfSense |

### VM fstab Patterns

All NFS mounts use NFSv3. **Mandatory options:** `nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg` (Lessons #3, S032 hardening).

```
# VLAN 5 VMs (101, 102) -- via bond0 Storage VLAN (S029: NFS bound to Storage+Mgmt only)
10.25.25.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0

# VLAN 66 VM (103) -- via eno4 management NIC (dirty VLAN can't reach Storage VLAN)
10.25.255.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0

# VLAN 10 VMs (104, 105) -- via bond0 Storage VLAN with TrueNAS static route for return
10.25.25.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0
```

**S032 mount hardening:** `soft` returns I/O error instead of D-state hang. `timeo=150` (15s timeout). `bg` retries mount in background on boot. Prevents the NFS D-state lockups that took down VM 101 in S031.

### TrueNAS NIC Inventory

| Interface | IP | VLAN | Switch Port | MTU | Status |
|---|---|---|---|---|---|
| eno1 | 10.25.0.25/24 | 1 (native on trunk) | Gi1/10 | 9000 | Active |
| **bond0** | **10.25.25.25/24** | **25 (Storage)** | **Port-channel1 (Gi1/8+Gi1/11)** | **9000** | **Active -- LACP 802.3ad, LAYER2+3 hash, ~2 Gbps aggregate** |
| eno2 | -- (bond0 member) | 25 | Gi1/11 (Po1) | 9000 | bond0 member |
| eno3 | -- (bond0 member) | 25 | Gi1/8 (Po1) | 9000 | bond0 member |
| eno4 | 10.25.255.25/24 | 2550 (Management) | Gi1/7 | 1500 | Active |
| iDRAC (LOM1) | 10.25.255.10/24 | 2550 (tagged on Gi1/10) | Gi1/10 | -- | Active |

### Storage LACP Bond (bond0 / Port-channel1)

- **Bond type:** 802.3ad (LACP)
- **Hash policy:** LAYER2+3
- **Members:** eno2 (Gi1/11) + eno3 (Gi1/8)
- **Aggregate bandwidth:** ~2 Gbps
- **IP:** 10.25.25.25/24 on VLAN 25
- **MTU:** 9000 (jumbo frames)
- **Switch side:** Port-channel1 (LACP active), access VLAN 25

### Dedicated Storage NIC on pve01 (vmbr1.25)

pve01 has a dedicated second NIC (nic1) for storage traffic, configured in Session 17:

- **Interface:** vmbr1.25 on nic1 (Intel I350 port 2)
- **IP:** 10.25.25.26/24
- **Switch port:** Gi1/9 (trunk)
- **MTU:** 9000
- **Config file:** `/etc/network/interfaces.d/vlan25-storage.conf`

This separates storage I/O from VM traffic on pve01. pve03 does not have this luxury (single NIC).

### ISO Storage (pve01 NFS Export)

| Field | Value |
|---|---|
| Source | pve01 ZFS dataset `os-pool-hdd/iso-storage` |
| Bind mount (pve01) | `/os-pool-hdd/iso-storage` -> `/mnt/iso-share` (in fstab) |
| NFS export ACL (pve01) | `10.25.0.27(rw,sync,...) 10.25.0.28(rw,sync,...) 10.25.25.28(rw,sync,...)` (S039: added storage VLAN for pve03) |
| NFS mount (pve02) | `10.25.0.26:/os-pool-hdd/iso-storage /mnt/iso-share nfs defaults,_netdev 0 0` |
| NFS mount (pve03) | `10.25.25.26:/os-pool-hdd/iso-storage /mnt/iso-share nfs nfsvers=3,defaults,_netdev 0 0` (S039: moved to Storage VLAN, forced NFSv3) |
| Contents | 28 ISOs |
| Boot ordering | Requires `x-systemd.requires=zfs-mount.service,x-systemd.after=zfs-mount.service` in fstab (Lesson #15) |

---

## 6. VM Inventory

### Full VM Table

| VMID | Name | Node | Status | Service VLAN | Service IP | Mgmt IP (.2550) | Gateway | RAM | NFS Mount IP | Key Services |
|---|---|---|---|---|---|---|---|---|---|---|
| 100 | SABnzbd | pve02 | running | 1 (LAN) | 10.25.0.150 | -- | 10.25.0.1 | 16 GB | -- | SABnzbd (8080). **OUT OF SCOPE.** |
| 101 | Plex-Server | pve01 | running | 5 (Public) | 10.25.5.30 | 10.25.255.30 | 10.25.5.1 | 8 GB | 10.25.25.25 | Plex Media Server (32400) |
| 102 | Arr-Stack | pve01 | running | 5 (Public) | 10.25.5.31 | 10.25.255.31 | 10.25.5.1 | 8 GB | 10.25.25.25 | Prowlarr, Sonarr, Radarr, Bazarr, Overseerr, Huntarr, Agregarr |
| 103 | qBit-Downloader | pve01 | running | 66 (Dirty) | 10.25.66.10 (DHCP) | 10.25.255.32 | 10.25.66.1 | 4 GB | 10.25.255.25 | qBittorrent + Gluetun VPN + FlareSolverr |
| 104 | Tdarr-Node | pve03 | running | 10 (Compute) | 10.25.10.34 | 10.25.255.34 | 10.25.10.5 | 16 GB | 10.25.25.25 | Tdarr Node (RX 580 GPU) |
| 105 | Tdarr-Server | pve01 | running | 10 (Compute) | 10.25.10.33 | 10.25.255.33 | 10.25.10.5 | 4 GB | 10.25.25.25 | Tdarr Server (8265/8266) |
| 420 | DonnyisGay | pve01 | stopped | -- | -- | -- | -- | 8 GB | -- | Purpose unknown |
| 802 | Blue | pve01 | running | 1 (LAN) | 10.25.0.75 | -- | 10.25.0.1 | ~4 GB | -- | Password vault. **Sonny only. Do not touch.** |

**Out of scope VMs:**
- VM 100 (SABnzbd) on pve02 -- Sonny's homework
- VM 802 (Blue) -- Sonny's password vault, managed by Sonny only
- VM 420 (DonnyisGay) -- stopped, purpose unknown
- **All VMs in the 800-899 range are NOT ours.** Do not touch, investigate, or reference.

### Proxmox Net Config Per VM

| VMID | net0 | net1 |
|---|---|---|
| 101 | `virtio=<mac>,bridge=vmbr0,tag=5,firewall=1` | `virtio=<mac>,bridge=vmbr0,tag=2550` |
| 102 | `virtio=BC:24:11:80:53:59,bridge=vmbr0,tag=5,firewall=1` | `virtio=BC:24:11:63:7E:9C,bridge=vmbr0,tag=2550` |
| 103 | `virtio=BC:24:11:56:78:89,bridge=vmbr0,tag=66,firewall=1` | `virtio=BC:24:11:1B:78:4C,bridge=vmbr0,tag=2550` |
| 104 | `virtio=BC:24:11:F8:D3:4E,bridge=vmbr0,tag=10` | `virtio=BC:24:11:9F:A8:0B,bridge=vmbr0,tag=2550` |
| 105 | `virtio=<mac>,bridge=vmbr0,tag=10` | `virtio=BC:24:11:FF:F0:54,bridge=vmbr0,tag=2550` |

**Pattern:** Every in-scope VM gets two NICs:
- **net0** -- service VLAN (where the application traffic lives), bridged to vmbr0 with appropriate VLAN tag
- **net1** -- management VLAN (2550), bridged to vmbr0 with tag 2550, for out-of-band SSH access

### VM OS Network Config Patterns

**VLAN 5 VMs (101, 102):**
```
# /etc/network/interfaces
auto ens18
iface ens18 inet static
    address 10.25.X.X/24
    gateway 10.25.5.1
    dns-nameservers 1.1.1.1 8.8.8.8
    mtu 9000
    up ip route add 10.25.0.0/24 via 10.25.5.5

auto ens19
iface ens19 inet static
    address 10.25.255.X/24
    mtu 9000
```

**VLAN 66 VM (103 -- Dirty):**
```
auto ens18
iface ens18 inet dhcp
    mtu 9000

auto ens19
iface ens19 inet static
    address 10.25.255.32/24
    mtu 9000
```

**VLAN 10 VMs (104, 105 -- Compute, no internet):**
```
auto ens18
iface ens18 inet static
    address 10.25.10.X/24
    gateway 10.25.10.5    # Switch SVI, NOT pfSense (by design -- see Lesson #5)
    dns-nameservers 1.1.1.1 8.8.8.8
    mtu 9000

auto ens19
iface ens19 inet static
    address 10.25.255.X/24
    mtu 9000
```

### VM 104 (Tdarr Node) -- GPU Passthrough Details

| Field | Value |
|---|---|
| Node | pve03 |
| OS | Debian 13 (trixie), kernel 6.12.73+deb13-amd64 |
| Disk | 64 GB (os-drive-ssd) |
| GPU | Radeon RX 580 via PCIe passthrough |
| Proxmox hostpci | `0000:06:00.0;0000:06:00.1,pcie=1` |
| Devices in guest | /dev/dri/card0, /dev/dri/card1, /dev/dri/renderD128, /dev/kfd |
| Docker | 29.2.1 with compose plugin |
| Secure Boot | Enabled (MS certs 2023w) |
| Firmware pkg | firmware-amd-graphics + libdrm-amdgpu1 |
| GPU encoding | hevc_vaapi=working, h264_vaapi=available but not working (normal for AMD/VAAPI) |

---

## 7. Services

### Container Standard

| Field | Value |
|---|---|
| PUID | 3003 (svc-admin) |
| PGID | 950 (truenas_admin) |
| TZ | America/Chicago |
| Image preference | LinuxServer.io (LSIO) preferred |
| Image pinning | Pin specific versions, no `:latest` — **enforced S032** (exception: Tdarr ghcr.io has no semver tags) |

### Compose File Reference

**Post-S032 Docker Overhaul:** All compose files and configs are LOCAL on each VM at `/opt/dc01/`. NFS is used ONLY for media data.

| VM | Compose Location | Config Location | Services |
|---|---|---|---|
| 101 | /opt/dc01/compose/docker-compose.yml | /opt/dc01/configs/plex/ | Plex |
| 102 | /opt/dc01/compose/docker-compose.yml | /opt/dc01/configs/{prowlarr,sonarr,radarr,bazarr,overseerr,huntarr,agregarr}/ | Prowlarr, Sonarr, Radarr, Bazarr, Overseerr, Huntarr, Agregarr |
| 103 | /opt/dc01/compose/docker-compose.yml | /opt/dc01/configs/{qbittorrent,gluetun}/ | qBittorrent + Gluetun + FlareSolverr |
| 104 | /opt/dc01/compose/docker-compose.yml | /opt/dc01/configs/tdarr-node/ | Tdarr Node |
| 105 | /opt/dc01/compose/docker-compose.yml | /opt/dc01/configs/tdarr/ | Tdarr Server |

**Backup:** Daily cron at 03:00 (`/etc/cron.d/dc01-backup`) → tar to NFS `media/config-backups/<hostname>/`. 7-day NFS retention, 3-day local.

### Service Details

#### Plex Media Server (VM 101 -- 10.25.5.30:32400)

| Field | Value |
|---|---|
| Server name | DC01 |
| Networking | Host mode (no Docker bridge) |
| GPU | /dev/dri passthrough (Intel, hardware transcode) |
| Transcode dir | /tmp (local, not NFS) |
| Libraries | TV Shows (/tv), Movies (/movies) |
| allowedNetworks | 10.25.0.0/255.255.0.0, 10.25.100.0/255.255.255.0 |
| secureConnections | 1 (preferred, allows insecure fallback) |
| customConnections | http://10.25.5.30:32400 |
| Port forward | WAN 50000 -> 10.25.5.30:32400 (pfSense NAT) |
| DNS | 1.1.1.1, 8.8.8.8 (resolv.conf locked with `chattr +i`) |
| PLEX_CLAIM | Not stored -- one-time use, expires 4 min. Get fresh from plex.tv/claim |

#### Arr Stack (VM 102 -- 10.25.5.31)

| Service | Port | Config Location | Notes |
|---|---|---|---|
| Prowlarr | 9696 | /opt/dc01/configs/prowlarr/ (LOCAL) | Indexer manager |
| Sonarr | 8989 | /opt/dc01/configs/sonarr/ (LOCAL) | TV show management |
| Radarr | 7878 | /opt/dc01/configs/radarr/ (LOCAL) | Movie management |
| Bazarr | 6767 | /opt/dc01/configs/bazarr/ (LOCAL) | Subtitle management. SQLite on NFS resolved by S032 local migration. |
| Overseerr | 5055 | /opt/dc01/configs/overseerr/ (LOCAL) | Request management. DB permissions resolved by S032 local migration. |
| Huntarr | 9705 | /opt/dc01/configs/huntarr/ (LOCAL) | Auto-searches missing media. Added S025. |
| Agregarr | 7171 | /opt/dc01/configs/agregarr/ (LOCAL) | Plex collection manager. Added S025. |

All service configs migrated from NFS to local `/opt/dc01/configs/` in S032. Service IPs audited S016, re-verified S032. **S039: All 7 ports bound to 10.25.255.31 (management VLAN only).** Web UIs inaccessible on service VLAN (.5.31).

#### qBittorrent (VM 103 -- 10.25.66.10)

| Field | Value |
|---|---|
| VLAN | 66 (Dirty) -- isolated, NAT via 69.65.20.61 |
| VPN container | Gluetun (healthy) |
| FlareSolverr | Running |
| Compose location | /opt/dc01/compose/docker-compose.yml + /opt/dc01/compose/.env |
| CONFIG_DIR | /opt/dc01/configs/qbittorrent/ + /opt/dc01/configs/gluetun/ (LOCAL) |
| DOWNLOADS_DIR | /mnt/truenas/nfs-mega-share/media/downloads/ |
| NFS access | Via 10.25.255.25 (management NIC, same L2 as VLAN 2550) |
| Internet egress | 69.65.20.61 (dirty VIP -- confirmed) |

#### Tdarr Server (VM 105 -- 10.25.10.33)

| Field | Value |
|---|---|
| Web UI | http://10.25.255.33:8265 (S039: bound to management VLAN only) |
| Server port | 10.25.10.33:8266 (S039: bound to compute VLAN for Tdarr-Node) |
| Auth | Enabled |
| Internal node | Disabled (internalNode=false) |
| Compose | /opt/dc01/compose/docker-compose.yml (LOCAL) |

#### Tdarr Node (VM 104 -- 10.25.10.34)

| Field | Value |
|---|---|
| Server connection | 10.25.10.33:8266 |
| Node ID | Radeon-RX580\|6Core |
| GPU | RX 580 (/dev/dri + /dev/kfd passthrough) |
| Version | v2.58.02 (matches server) |
| Compose | /opt/dc01/compose/docker-compose.yml (LOCAL) |
| group_add | video + 992 (render GID -- numeric only, no group name in container) |

### Media Directory Layout (on NFS)

**Post-S032 Docker Overhaul:** NFS root renamed from `plex/` to `media/` (lowercase). All compose files and configs moved LOCAL to `/opt/dc01/` on each VM. NFS holds media data ONLY.

```
/mnt/truenas/nfs-mega-share/media/
|-- movies/
|-- tv/
|-- audio/
|-- downloads/
|   +-- complete/
|       |-- radarr/
|       +-- tv-sonarr/
|-- transcode/
+-- config-backups/          # Daily backup cron targets (S032/S034)
    |-- plex/                # VM 101
    |-- arr-stack/           # VM 102
    |-- qbit/                # VM 103
    |-- tdarr-node/          # VM 104
    +-- tdarr/               # VM 105
```

**Backup cron (S032/S034):** Script at `/opt/dc01/backups/backup.sh` on all 5 VMs. Cron at `/etc/cron.d/dc01-backup`, 03:00 daily. Tar to local + copy to NFS `media/config-backups/<hostname>/`. 7-day NFS retention, 3-day local. S034 hardening: tar exit code 1 handled as warning (Docker modifies files mid-tar), atomic NFS write via temp+rename.

---

## 8. High Availability

### Current HA State

| Component | pve01 | pve02 | pve03 |
|---|---|---|---|
| pve-ha-lrm | enabled, running | DEAD 15+ days (TICKET-0008) | enabled, running |
| pve-ha-crm | enabled, running | DEAD 15+ days (TICKET-0008) | enabled, running |
| Watchdog | softdog (loaded, persistent via /etc/modules) | -- | softdog (loaded, persistent via /etc/modules) |
| watchdog-mux | running | -- | running |

- **Current HA master:** pve03
- pve02 LRM dead since Feb 5 2026 (15+ days). Node still defined in corosync but expected_votes reduced to 2 for 2-node quorum. Assessment at `infra/TICKET-0008-PVE02-ASSESSMENT.md`.

### Shared Storage for HA

| Field | Value |
|---|---|
| Storage name | truenas-os-drive |
| Type | NFS |
| Capacity | 20 TB |
| Mount point | /mnt/pve/ha-proxmox-disk |
| NFS export | /mnt/mega-pool/ha-proxmox-disk |
| Access | World-accessible (`*`), rw, no_subtree_check |

### Corosync

| Field | Value |
|---|---|
| Config version | 8 |
| Transport | knet |
| pve01 ring0 | 10.25.255.26 (VLAN 2550) |
| pve02 ring0 | 10.25.0.27 (VLAN 1 -- lacks VLAN 2550) |
| pve03 ring0 | 10.25.255.28 (VLAN 2550) |

Cross-VLAN routing between all nodes is verified working. Corosync ring0 addresses on the management VLAN were broken until the vmbr0.2550 -> vmbr0v2550 fix was applied in Session 17 (see Lesson #14).

After pve01's kernel upgrade reboot in Session 17, pve01 + pve03 maintained 2-node quorum. pve02 was disconnected and needs a corosync restart (out of scope).

---

## 9. Security Posture

### Current State

The cluster has undergone **significant hardening in S029-S034** but several critical items remain.

| Task | Status | Notes |
|---|---|---|
| SSH hardening (key-only auth, disable passwords) | **PARTIAL** | X11Forwarding disabled on all 7 Linux systems (S034). Password auth still enabled — pending SSH key deployment (TICKET-0006). |
| Fail2ban on exposed services | NOT DONE | No brute-force protection |
| Proxmox API restriction to management VLAN | **DONE (S029)** | iptables on pve01/pve03: web UI restricted to VLAN 2550 + cluster peer + localhost only |
| Docker security (no privileged, pin versions) | **DONE (S032)** | All 13 containers pinned. Exception: Tdarr (no semver). Configs local at `/opt/dc01/`. .env permissions 600 (S034). |
| NFS export audit | **PARTIAL** | nfs-mega-share has 7 networks (needs reduction). ha-proxmox-disk open to `*` (needs Proxmox IP restriction). |
| Management VLAN lockdown (SSH/HTTPS) | **PARTIAL** | Proxmox web UI restricted (S029). TrueNAS web UI bound .255.25 only (S029). pfSense webGUI VPN-only on port 4443 (S031). Full SSH lockdown pending. |
| iDRAC password changes | NOT DONE | Both iDRACs still have default passwords |
| TrueNAS SSH restriction | **DONE (S033)** | SSH bound to eno4 only (`bindiface: ["eno4"]`). Accessible on 10.25.255.25:22 + localhost. Weak ciphers remain (AES128-CBC, NONE — needs GUI fix). |
| Monitoring (Uptime Kuma or similar) | NOT DONE | No PSU/fan alerts, no service health, no NFS monitoring. Recommendation at `infra/RECOMMENDATION-MONITORING.md`. |
| Proxmox Backup Server | NOT DONE | Daily config backup cron exists (S032). No full VM backups. Recommendation at `infra/RECOMMENDATION-BACKUP-STRATEGY.md`. |

### What IS in Place

- VLAN segmentation (6 VLANs with distinct security policies)
- pfSense RFC1918 blocking on VLAN 5 (Public) and VLAN 66 (Dirty)
- VLAN 66 dirty NAT isolation via separate public VIP (69.65.20.61)
- VLAN 10 (Compute) has no internet access by design
- NFS all_squash maps all writes to svc-admin uid=3003 / gid=950 (no root squash escalation risk)
- WireGuard VPN for remote access (not exposing SSH directly)
- DNS locked with `chattr +i` on VMs 101, 102, 104, 105 (resolv.conf immutable, S034)
- Proxmox web UI restricted to VLAN 2550 via iptables (S029)
- TrueNAS web UI bound to .255.25 only (S029)
- pfSense webGUI restricted to VPN->.255.1:4443 only (S031, anti-lockout disabled, block rules on LAN+WireGuard)
- Docker image pinning enforced, all configs local (S032)
- Daily config backup cron on all 5 VMs (S032/S034)
- NFS sysctl tuning on all 7 Linux systems (16MB buffers, S034)
- SSH X11Forwarding disabled on all 7 Linux systems (S034)
- Switch password encryption enabled, NTP configured (S034)
- Plex sudo group membership cleaned up (S034)
- Docker .env permissions 600 root:root (S034)

---

## 10. Backup & Recovery

### Current State: Config Backups Active, No Full VM Backups

The single biggest remaining operational risk is the lack of full VM backup infrastructure.

### What Exists Today

- **Daily config backup cron (S032/S034):** Script at `/opt/dc01/backups/backup.sh` on all 5 VMs. Cron at `/etc/cron.d/dc01-backup`, 03:00 daily. Tar to local + NFS `media/config-backups/<hostname>/`. 7-day NFS retention, 3-day local. S034 hardening: tar exit code 1 as warning, atomic NFS write via temp+rename.
- **Manual backups before changes:** Admins create backup directories in home dirs before modifying configs (e.g., `~/backup-ARCHITECTURE-S028/`). Ad-hoc but consistent.
- **ZFS scrubs:** mega-pool scrubbed periodically (last: 2026-02-08, 0 errors). Protects against silent corruption but is not a backup.
- **DC01_v1.1_base_config:** 92-file baseline backup on NFS at `/mnt/truenas/nfs-mega-share/DC01_v1.1_base_config/`. Created S024.
- **All Docker configs LOCAL:** Compose files and app configs at `/opt/dc01/` on each VM (S032). Protected by daily backup cron.

### Planned: Proxmox Backup Server (PBS)

PBS evaluation pending. Recommendation at `infra/RECOMMENDATION-BACKUP-STRATEGY.md`.

### Remaining Recovery Gaps

- No full VM snapshots or disk-level backups
- No offsite replication
- No tested restore procedure
- No Proxmox host config backup (beyond manual pre-change baselines)

---

## 11. Known Issues & Risks

### Hardware Risks

| Issue | Severity | Impact | Mitigation |
|---|---|---|---|
| TrueNAS PSU 1 failed | **CRITICAL** | Single PSU -- any failure = total storage loss | Order replacement Dell 05RHVVA00 |
| TrueNAS Fan 6 dead | HIGH | Thermal risk, all fans report "Redundancy Lost" | Order replacement fan by Service Tag B065ND2 |
| pve01 PSU 2 failed | **CRITICAL** | Single PSU -- any failure = all VMs on pve01 down (101-103, 105, 420, 802, 804) | Order replacement Dell 06W2PWA00 |
| pve03 single NIC | MEDIUM | All traffic (VM, storage, management, corosync) shares one 1 GbE link | No mitigation short of adding a second NIC |

### Network Risks

| Issue | Severity | Notes |
|---|---|---|
| ~~pfSense VLAN sub-interface MTU 1500 (F-S034-MTU)~~ | ~~HIGH~~ | **CLOSED S037.** All VLAN sub-interfaces now MTU 9000. |
| VM 103 no storage VLAN NIC (F-S034-VM103) | MEDIUM | NFS traffic over management VLAN. **Approved exception S039** — dirty VM isolation by design. |
| Mamadou Server NAT exposes port 8006 (F-S034-NAT) | MEDIUM | NAT rule forwards 8006 to 10.25.0.9. Proxmox UI exposed to internet. Sonny review needed. |
| pve02 missing VLAN 25 and 2550 | LOW | Out of scope (homework). pve02 has no storage VLAN or management VLAN. |

**Resolved:** pve03 vmbr0v25/vmbr0v5 split-brain -- already uses correct Proxmox VLAN bridge naming. VPN reachability -- all VLANs reachable since S023.

### Application Risks

| Issue | Severity | Notes |
|---|---|---|
| No full VM backup strategy | **CRITICAL** | Daily config cron exists (S032). PBS planned but not deployed. Full VM loss = rebuild from OS install. |
| No monitoring | HIGH | PSU/fan failures, NFS hangs, service outages go undetected. No alerting. Recommendation pending. |
| VM 104 GPU passthrough fails on restart (F-S034-GPU) | HIGH | amdgpu error -22. Needs vendor-reset DKMS module on pve03 host. Requires host reboot. |
| TrueNAS weak SSH ciphers (F-S034-CIPHER) | HIGH | AES128-CBC and NONE accepted. Needs GUI fix (SSH service settings). |
| ha-proxmox-disk NFS export open (F-S034-NFS-ACL) | HIGH | Export allows `*` (any host). Restrict to Proxmox node IPs only (GUI). |

**Resolved (S032/S034):** Overseerr DB permissions -- fixed by local migration. SQLite on NFS -- all configs now local at `/opt/dc01/configs/`.

### Operational Risks

| Issue | Notes |
|---|---|
| pve02 LRM dead 15+ days (TICKET-0008) | Node still in corosync config, votes adjusted to 2. Assessment at `infra/TICKET-0008-PVE02-ASSESSMENT.md`. |
| Gi1/36 unknown hardware | Access VLAN 1, not our hardware. Do not touch. |

**Resolved (S035):** VLANs 113/715 removed from switch (confirmed orphaned, zero ports/SVIs/trunk carriage).

---

## 12. Lessons Learned

These are 16 hard-won rules from real incidents across Sessions 1-17. Violating any of them has caused outages, lockouts, or data loss.

### 1. WireGuard Endpoint = Sacred (Session 4 -- VPN Lockout)
Before ANY VIP/WAN IP change: check pfSense VPN -> WireGuard -> Server for the bound endpoint. If the IP being changed matches, do NOT proceed. Order: (1) Add new IP, (2) Update WireGuard server, (3) Update all clients, (4) Test, (5) ONLY THEN remove old IP. Always have LAN/console access before touching firewall or VPN remotely.

### 2. vmbr0 Address Is Sacred (Session 11 -- Network Lockout)
`vmbr0` on pve01 MUST keep `10.25.0.26/24`. It IS the VLAN 1 management IP. Management VLAN belongs on the Proxmox VLAN bridge `vmbr0v2550`, NEVER on vmbr0 itself and NEVER on a dot sub-interface like `vmbr0.2550` (see Lessons #13/#14 for the split-brain bug that makes dot sub-interfaces unreliable). Changing vmbr0's address drops ALL connectivity instantly. Recovery requires iDRAC virtual console.

> **DANGER:** Using `vmbr0.2550` instead of `vmbr0v2550` will silently break corosync and management access. This caused a cluster outage in Session 17.

### 3. NFS fstab Must Have `_netdev,nofail` (Session 12 -- Boot Hang)
Without `_netdev`: Linux mounts NFS before networking is up -- hang. Without `nofail`: NFS failure stops boot entirely -- console-only recovery. Always use both on every NFS fstab entry.

### 4. Asymmetric Routing Breaks NFS (Session 13 -- TCP Timeout)
VMs on VLAN 5 (gateway=pfSense) routing to TrueNAS via switch SVI causes asymmetric paths. Return traffic goes through pfSense which drops it (no state entry). Fix: static routes on TrueNAS so return traffic goes through the switch SVI, not pfSense. VLAN 5 VMs also need `up ip route add 10.25.0.0/24 via 10.25.5.5` in their interfaces config.

### 5. VLAN 10 Gateway Must Be Switch SVI, Not pfSense (Session 11)
VLAN 10 pfSense rule only allows traffic to pfSense's own interface IP. NFS traffic to 10.25.25.25 would be blocked. Switch SVI (10.25.10.5) routes NFS directly via L3 switching, bypassing pfSense. This is correct by design.

### 6. SQLite Cannot Run on NFS (Session 15 -- Bazarr Corruption)
NFSv3 file locking is unreliable. Any service using SQLite MUST have its config/DB on local disk, not NFS. **RESOLVED S032:** All configs moved local to `/opt/dc01/configs/` on each VM.

### 7. VLAN 5 VMs Must Use Public DNS (Session 15 -- DNS Resolution)
VLAN 5 firewall blocks RFC1918 by design. Internal DNS (10.25.0.1) is unreachable. Use 1.1.1.1/8.8.8.8 only. Lock resolv.conf with `chattr +i` to prevent overwrite.

### 8. Jumbo Frames Must Match End-to-End (Session 1 -- NFS Failure)
Switch, Proxmox hosts, VMs, and TrueNAS must ALL have jumbo frames enabled. If the switch has default MTU 1500 and everything else is 9000, packets >1500 bytes are silently dropped. NFS mount fails with no useful error message.

### 9. Guest Agent API for VM Root Access (Session 12)
`qm exec` does not exist in PVE 9. `qm guest exec` breaks with flags. Use Python + Proxmox REST API directly: auth -> /agent/exec -> poll /agent/exec-status. Requires qemu-guest-agent running in VM.

### 10. Proxmox VM Create: Use pvesh on Target Node (Sessions 6-7)
Cross-node API calls for VM creation have format issues in PVE 9. Always SSH to the target node and use `pvesh create` directly. `allFunctions=1` is rejected by pvesh schema -- edit the config file directly or use semicolon-separated function list in the host field.

### 11. pfSense Config Cannot Be Written via SSH as Non-Root (Session 6)
config.xml is root:wheel 644. sonny-aif can read but not write. PHP scripts execute but writes silently fail. Must use pfSense web GUI or root SSH for config changes.

### 12. iDRAC LOM + VLAN Tagging (Session 10)
R530 has no dedicated iDRAC port -- iDRAC shares eno1's physical port (LOM1). To isolate iDRAC to VLAN 2550: configure **Gi1/10** as trunk (native VLAN 1, allowed 2550), enable iDRAC VLAN tagging via `racadm set iDRAC.NIC.VLanID 2550` + `VLanEnable Enabled`. (Originally Gi1/25; cable moved to Gi1/10 in Session 17.)

### 13. VLAN Sub-Interface on Bridge vs on Physical NIC (Session 17 -- VLAN 2550 Broken)
Creating a VLAN sub-interface on a Proxmox bridge (e.g., `vmbr0.2550`) does NOT work if a VLAN sub-interface also exists on the physical NIC (e.g., `nic0.2550` created by Proxmox for VM VLAN bridges). The kernel delivers incoming tagged frames to `nic0.2550` first, so `vmbr0.2550` never receives replies. Fix: assign host IPs to the Proxmox VLAN bridge (e.g., `vmbr0v2550`) instead.

### 14. VLAN 2550 Split-Brain Breaks Corosync (Session 17 -- HA Enablement)
Same root cause as #13. When Proxmox VLAN-aware bridges create `nic0.XXXX` sub-interfaces, a host IP on `vmbr0.XXXX` will not receive traffic. Use `vmbr0vXXXX` instead. This broke corosync ring0 on management VLAN addresses until the host IPs were moved to `vmbr0v2550`.

### 15. ZFS Bind Mount Ordering on Boot (Session 17 -- iso-storage Empty After Reboot)
A bind mount in fstab fires during early boot before ZFS datasets are mounted. The bind gets the empty directory from the root ext4 filesystem, not the ZFS data. Fix: add `x-systemd.requires=zfs-mount.service,x-systemd.after=zfs-mount.service` to the fstab options.

### 16. Always Eject ISO After OS Install (Session 17 -- VMs 802/804 Won't Start)
Installer ISOs left mounted in `ide2:` cause VMs to refuse to start once the ISO file is deleted from storage. Fix: always run `qm set <vmid> --ide2 none,media=cdrom` after OS installation to detach the ISO.

### 17. Parallel NFS Writes Can Overwhelm Soft Mounts (Session 34)
Multiple concurrent tar/cp operations to NFS with `soft` mount can cause I/O errors under load. Atomic NFS writes (temp file + rename) are more reliable. Backup scripts should serialize NFS writes and handle tar exit code 1 as a warning (Docker modifies files mid-tar).

### 18. AMD Polaris GPU Passthrough Needs vendor-reset (Session 34)
AMD Polaris GPUs (RX 470/480/570/580/590) have a known reset bug — the GPU enters a bad state when the VM stops, producing `amdgpu error -22` on next start. Fix: install the `vendor-reset` DKMS kernel module on the Proxmox HOST (not the VM). The module must load BEFORE vfio-pci. Without it, a full host reboot is required between VM stop/start cycles.

---

## 13. Out of Scope

The following items are explicitly excluded from this architecture document and from Worker #1's responsibilities:

| Item | Reason |
|---|---|
| **pve02** (10.25.0.27) | Out of scope. Unknown hardware. No VLAN 25 or 2550 configured. Sonny's homework. |
| **VM 100 (SABnzbd)** | Runs on pve02. Out of scope. |
| **VMs 800-899** | Not our VMs. Do not touch, investigate, or reference. VM 802 (Blue) is Sonny's password vault. VM 804 (Talos) is Donmin's. Both running on pve01. |
| **VM 420 (DonnyisGay)** | Stopped. Purpose unknown. Do not touch. |
| **GigeNet client work** | Separate infrastructure. Not part of DC01 cluster operations. |
| **pfSense GUI configuration** | Firewall rule changes are Sonny's GUI task (documented in DC01.md with step-by-step instructions). |
| **Bazarr reconfiguration** | Web UI task for Sonny (connect to Sonarr/Radarr, set subtitle providers). |
| **WordPress/cPanel migration** | Future project, not yet scoped. From GigeNet company resources. |

<!-- TICKET-0001 RESOLVED S028: Lesson #2 amended to use correct "Proxmox VLAN bridge" terminology,
warn against vmbr0.2550, cross-reference Lessons #13/#14, and add DANGER callout. -->

<!-- TICKET-0002 RESOLVED S033: Image pinning now enforced post-S032 Docker Overhaul. Tdarr exception noted. -->
<!-- TICKET-0003 RESOLVED S033: Lesson #12 updated to Gi1/10 with S17 cable move note. -->
<!-- TICKET-0004 RESOLVED S033: svc-admin added to Cluster section. PUID fixed 3000→3003. Lesson #10 pvesh detail added. WSL section added. -->
<!-- TICKET-0005 RESOLVED S033: NFS Mount Strategy updated to reflect S029 binding changes. fstab patterns updated with S032 mount options. -->
