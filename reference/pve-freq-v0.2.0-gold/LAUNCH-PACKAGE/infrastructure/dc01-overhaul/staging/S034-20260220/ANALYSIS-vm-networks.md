# VM Network Configuration Analysis Report

**Session:** S034
**Date:** 2026-02-20
**Scope:** VMs 101-105 network configuration audit
**Compared against:** DC01.md expected state + CLAUDE.md standards

---

## Executive Summary

**30 checks performed across 5 VMs. 5 findings requiring action.**

| Severity | Count |
|----------|-------|
| CRITICAL | 1     |
| HIGH     | 3     |
| MEDIUM   | 1     |
| LOW      | 0     |
| OK       | 25    |

---

## VM 101 — Plex-Server (VLAN 5, pve01)

### ens18 (Service NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.5.30/24 | 10.25.5.30/24 | **OK** |
| Gateway | 10.25.5.1 | 10.25.5.1 | **OK** |
| MTU (config) | 9000 | 9000 | **OK** |
| MTU (live) | 9000 | 9000 | **OK** |
| Link state | UP | UP | **OK** |
| Static route 10.25.0.0/24 | via 10.25.5.5 | via 10.25.5.5 | **OK** |

### ens19 (Management NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.255.30/24 | 10.25.255.30/24 | **OK** |
| Gateway | none | none | **OK** |
| MTU (config) | 9000 | 9000 | **OK** |
| MTU (live) | 9000 | 9000 | **OK** |
| Link state | UP | UP | **OK** |
| VPN return route | 10.25.100.0/24 via 10.25.255.1 dev ens19 | 10.25.100.0/24 via 10.25.255.1 dev ens19 | **OK** |

### DNS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Nameservers | 1.1.1.1, 8.8.8.8 | 1.1.1.1, 8.8.8.8 | **OK** |
| resolv.conf immutable (chattr +i) | Yes | Yes (`----i---------e-------`) | **OK** |

### NFS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| fstab server IP | 10.25.25.25 | 10.25.25.25 | **OK** |
| fstab mount path | /mnt/mega-pool/nfs-mega-share | /mnt/mega-pool/nfs-mega-share | **OK** |
| fstab mount point | /mnt/truenas/nfs-mega-share | /mnt/truenas/nfs-mega-share | **OK** |
| fstab options | nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg | nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg | **OK** |
| NFS mounted | Yes | Yes (type nfs, vers=3, addr=10.25.25.25) | **OK** |
| Media dirs accessible | Yes | Yes (movies, tv, audio, downloads, transcode visible) | **OK** |

**VM 101 Result: CLEAN -- No findings.**

---

## VM 102 — Arr-Stack (VLAN 5, pve01)

### ens18 (Service NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.5.31/24 | 10.25.5.31/24 | **OK** |
| Gateway | 10.25.5.1 | 10.25.5.1 | **OK** |
| MTU (config) | 9000 | 9000 | **OK** |
| MTU (live) | 9000 | 9000 | **OK** |
| Link state | UP | UP | **OK** |
| Static route 10.25.0.0/24 | via 10.25.5.5 | via 10.25.5.5 | **OK** |

### ens19 (Management NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.255.31/24 | 10.25.255.31/24 | **OK** |
| Gateway | none | none | **OK** |
| MTU (config) | 9000 | 9000 | **OK** |
| MTU (live) | 9000 | 9000 | **OK** |
| Link state | UP | UP | **OK** |
| VPN return route | 10.25.100.0/24 via 10.25.255.1 dev ens19 | 10.25.100.0/24 via 10.25.255.1 dev ens19 | **OK** |

### DNS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Nameservers | 1.1.1.1, 8.8.8.8 | 1.1.1.1, 8.8.8.8 | **OK** |
| resolv.conf immutable (chattr +i) | Yes | **NO** (`--------------e-------`) | **HIGH** |

### NFS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| fstab server IP | 10.25.25.25 | 10.25.25.25 | **OK** |
| fstab options | (standard) | nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg | **OK** |
| NFS mounted | Yes | Yes (type nfs, vers=3, addr=10.25.25.25) | **OK** |
| Media dirs accessible | Yes | Yes | **OK** |

### Finding F-S034-01 -- HIGH: resolv.conf not immutable on VM 102

- **What:** `/etc/resolv.conf` is NOT locked with `chattr +i` on VM 102. The immutable flag output shows `--------------e-------` (no `i` flag).
- **Risk:** DNS can be overwritten by DHCP client, systemd-resolved, or package upgrades, potentially breaking name resolution for all 7 arr services.
- **Impact:** If DNS gets overwritten, Prowlarr/Sonarr/Radarr/Bazarr indexer lookups and download client communications will fail.
- **Fix:** `sudo chattr +i /etc/resolv.conf` on VM 102.

---

## VM 103 — qBit-Downloader (VLAN 66, pve01)

### ens18 (Service NIC — Dirty VLAN)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Mode | DHCP | DHCP | **OK** |
| IP Address | DHCP (10.25.66.10) | 10.25.66.10/24 (dynamic) | **OK** |
| Default gateway | DHCP | 10.25.66.1 via DHCP | **OK** |
| MTU (config) | 9000 | **1500** | **CRITICAL** |
| MTU (live) | 9000 | **9000** | see below |
| Link state | UP | UP | **OK** |

### ens19 (Management NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.255.32/24 | 10.25.255.32/24 | **OK** |
| Gateway | none | none | **OK** |
| MTU (config) | 9000 | 9000 | **OK** |
| MTU (live) | 9000 | 9000 | **OK** |
| Link state | UP | UP | **OK** |
| VPN return route | 10.25.100.0/24 via 10.25.255.1 dev ens19 | 10.25.100.0/24 via 10.25.255.1 dev ens19 | **OK** |

### DNS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Nameservers | DHCP-provided (no restriction) | 1.1.1.1, 8.8.8.8 (via dhcpcd with domain infra.internal) | **OK** |
| resolv.conf immutable | Not required (DHCP) | Not immutable | **OK** |

### NFS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| fstab server IP | 10.25.255.25 (Mgmt VLAN) | 10.25.255.25 | **OK** |
| fstab options | (standard) | nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg | **OK** |
| NFS mounted | Yes | Yes (type nfs, vers=3, addr=10.25.255.25) | **OK** |
| Media dirs accessible | Yes | Yes | **OK** |

### Finding F-S034-02 -- CRITICAL: ens18 MTU config/live mismatch on VM 103

- **What:** The persistent network config (`/etc/network/interfaces`) sets ens18 MTU to `1500`, but the live interface is running at MTU `9000`. There is a config-vs-runtime discrepancy.
- **Detail:** The interfaces file explicitly says `mtu 1500` for ens18. However, `ip addr show` and `ip link show` both report MTU 9000 on ens18 at runtime. This means something OUTSIDE the interfaces file is setting the MTU — likely DHCP server option, a network script, or a manual override that was applied but never persisted properly.
- **Risk:** On next reboot, ens18 will come up with MTU 1500 (as configured). If the DHCP server on VLAN 66 is NOT pushing MTU 9000, the interface will drop to 1500 post-reboot. Since the switch has jumbo frames (MTU 9198) on all ports, an MTU mismatch could cause packet fragmentation or silent drops for large transfers through the VPN tunnel (Gluetun).
- **However:** VLAN 66 is the "dirty" internet-facing VLAN. Traffic leaving via Gluetun VPN will be encapsulated and the VPN endpoint may not support jumbo frames. MTU 1500 may actually be CORRECT here for VLAN 66 if the upstream doesn't support jumbos. The expected state says 9000, but this warrants a design decision.
- **Fix (if 9000 is desired):** Edit `/etc/network/interfaces` on VM 103, change `mtu 1500` to `mtu 9000` for ens18.
- **Alternative (if 1500 is intended):** Update DC01.md expected state to reflect MTU 1500 for VM 103 ens18, and investigate why the live MTU is 9000 (possibly the DHCP server on pfSense VLAN 66 is pushing MTU 9000).

---

## VM 104 — Tdarr-Node (VLAN 10, pve03)

### ens18 (Service NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.10.34/24 | 10.25.10.34/24 | **OK** |
| Gateway | 10.25.10.5 (switch SVI) | 10.25.10.5 | **OK** |
| MTU (config) | 9000 | **NOT SET in interfaces file** | **HIGH** |
| MTU (live) | 9000 | 9000 | see below |
| Link state | UP | UP | **OK** |
| DNS in interfaces | 1.1.1.1, 8.8.8.8 | **10.25.0.1** | **MEDIUM** |

### ens19 (Management NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.255.34/24 | 10.25.255.34/24 | **OK** |
| Gateway | none | none | **OK** |
| MTU (config) | 9000 | 9000 | **OK** |
| MTU (live) | 9000 | 9000 | **OK** |
| Link state | UP | UP | **OK** |
| VPN return route | 10.25.100.0/24 via 10.25.255.1 dev ens19 | 10.25.100.0/24 via 10.25.255.1 dev ens19 | **OK** |

### DNS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Nameservers (resolv.conf) | 1.1.1.1, 8.8.8.8 | 1.1.1.1, 8.8.8.8 | **OK** |
| resolv.conf immutable | Expected | **No immutable check output in file** (file only has 2 lines) | **HIGH** |

### NFS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| fstab server IP | 10.25.25.25 (Storage VLAN) | 10.25.25.25 | **OK** |
| fstab options | (standard) | nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg | **OK** |
| NFS mounted | Yes | Yes (type nfs, vers=3, addr=10.25.25.25) | **OK** |
| Media dirs accessible | Yes | Yes | **OK** |

### Finding F-S034-03 -- HIGH: ens18 MTU not set in interfaces file on VM 104

- **What:** The `/etc/network/interfaces` file on VM 104 does NOT specify `mtu 9000` for ens18. The ens19 stanza has `mtu 9000` explicitly, but ens18 does not. The live MTU IS 9000, meaning something else is setting it (likely the virtio driver defaulting to match the Proxmox vNIC config, or the switch LLDP).
- **Risk:** If the Proxmox VM hardware config changes or the VM is migrated, the MTU may revert to 1500 since it is not explicitly pinned in the OS network config.
- **Fix:** Add `mtu 9000` to the ens18 stanza in `/etc/network/interfaces` on VM 104.

### Finding F-S034-04 -- MEDIUM: dns-nameservers in interfaces file points to pfSense (10.25.0.1) instead of public DNS on VM 104

- **What:** The interfaces file has `dns-nameservers 10.25.0.1` for ens18, but the expected standard is `1.1.1.1 8.8.8.8`. The actual resolv.conf correctly shows `1.1.1.1` and `8.8.8.8`, so this is a config inconsistency but not a live issue.
- **Risk:** If resolvconf regenerates (package update, interface bounce), it would rewrite resolv.conf to point at `10.25.0.1` (pfSense). This would still work since pfSense acts as a DNS forwarder, but deviates from the DC01 standard. Also, resolv.conf has no immutable flag so it CAN be overwritten.
- **Fix:** Change `dns-nameservers 10.25.0.1` to `dns-nameservers 1.1.1.1 8.8.8.8` in `/etc/network/interfaces` on VM 104. Then set `chattr +i /etc/resolv.conf`.

### Finding F-S034-05a -- HIGH: resolv.conf not confirmed immutable on VM 104

- **What:** The resolv-conf.txt file for VM 104 contains only the nameserver lines and no `=== IMMUTABLE CHECK ===` section. This means we cannot confirm whether `chattr +i` is set. Given that the interfaces file points to `10.25.0.1` but resolv.conf shows `1.1.1.1`/`8.8.8.8`, the file was likely manually set and SHOULD be locked but may not be.
- **Fix:** Verify with `lsattr /etc/resolv.conf` on VM 104. If not immutable, set `chattr +i /etc/resolv.conf`.

---

## VM 105 — Tdarr-Server (VLAN 10, pve01)

### ens18 (Service NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.10.33/24 | 10.25.10.33/24 | **OK** |
| Gateway | 10.25.10.5 (switch SVI) | 10.25.10.5 | **OK** |
| MTU (config) | 9000 | **NOT SET in interfaces file** | **HIGH** |
| MTU (live) | 9000 | 9000 | see below |
| Link state | UP | UP | **OK** |
| DNS in interfaces | 1.1.1.1, 8.8.8.8 | **10.25.0.1** | **MEDIUM** |

### ens19 (Management NIC)
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| IP Address | 10.25.255.33/24 | 10.25.255.33/24 | **OK** |
| Gateway | none | none | **OK** |
| MTU (config) | 9000 | 9000 | **OK** |
| MTU (live) | 9000 | 9000 | **OK** |
| Link state | UP | UP | **OK** |
| VPN return route | 10.25.100.0/24 via 10.25.255.1 dev ens19 | 10.25.100.0/24 via 10.25.255.1 dev ens19 | **OK** |

### DNS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| Nameservers (resolv.conf) | 1.1.1.1, 8.8.8.8 | 1.1.1.1, 8.8.8.8 | **OK** |
| resolv.conf immutable | Expected | **No immutable check output in file** | **HIGH** |

### NFS
| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| fstab server IP | 10.25.25.25 (Storage VLAN) | 10.25.25.25 | **OK** |
| fstab options | (standard) | nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg | **OK** |
| NFS mounted | Yes | Yes (type nfs, vers=3, addr=10.25.25.25) | **OK** |
| Media dirs accessible | Yes | Yes | **OK** |

### Finding F-S034-05 -- HIGH: ens18 MTU not set in interfaces file on VM 105

- **What:** Identical issue to VM 104. The `/etc/network/interfaces` file on VM 105 does NOT specify `mtu 9000` for ens18. Live MTU is 9000 but it is not explicitly configured.
- **Fix:** Add `mtu 9000` to the ens18 stanza in `/etc/network/interfaces` on VM 105.

### Finding F-S034-06 -- MEDIUM: dns-nameservers in interfaces file points to pfSense (10.25.0.1) instead of public DNS on VM 105

- **What:** Same as VM 104. The interfaces file has `dns-nameservers 10.25.0.1` but the standard is `1.1.1.1 8.8.8.8`. resolv.conf is correct at runtime, but the config source is wrong.
- **Fix:** Change `dns-nameservers 10.25.0.1` to `dns-nameservers 1.1.1.1 8.8.8.8` in `/etc/network/interfaces` on VM 105. Then set `chattr +i /etc/resolv.conf`.

### Finding F-S034-05b -- HIGH: resolv.conf not confirmed immutable on VM 105

- **What:** Same as VM 104. No immutable check output in the staging pull for VM 105. Cannot confirm chattr +i status.
- **Fix:** Verify with `lsattr /etc/resolv.conf` on VM 105. If not immutable, set `chattr +i /etc/resolv.conf`.

---

## Consolidated Findings Summary

| ID | VM | Severity | Category | Summary | Fix |
|----|-----|----------|----------|---------|-----|
| F-S034-01 | 102 | HIGH | DNS | resolv.conf not immutable (chattr +i missing) | `chattr +i /etc/resolv.conf` |
| F-S034-02 | 103 | CRITICAL | MTU | ens18 config says MTU 1500 but live is 9000; will revert on reboot | Edit interfaces: change `mtu 1500` to `mtu 9000` OR update DC01.md if 1500 is intended |
| F-S034-03 | 104 | HIGH | MTU | ens18 has no MTU set in interfaces file (live is 9000 from elsewhere) | Add `mtu 9000` to ens18 stanza |
| F-S034-04 | 104 | MEDIUM | DNS | interfaces file dns-nameservers = 10.25.0.1 (not 1.1.1.1 8.8.8.8) | Change to `dns-nameservers 1.1.1.1 8.8.8.8` |
| F-S034-05a | 104 | HIGH | DNS | resolv.conf immutable status unknown (no check in staging pull) | Verify `lsattr /etc/resolv.conf`; set `chattr +i` if needed |
| F-S034-05 | 105 | HIGH | MTU | ens18 has no MTU set in interfaces file (live is 9000 from elsewhere) | Add `mtu 9000` to ens18 stanza |
| F-S034-06 | 105 | MEDIUM | DNS | interfaces file dns-nameservers = 10.25.0.1 (not 1.1.1.1 8.8.8.8) | Change to `dns-nameservers 1.1.1.1 8.8.8.8` |
| F-S034-05b | 105 | HIGH | DNS | resolv.conf immutable status unknown (no check in staging pull) | Verify `lsattr /etc/resolv.conf`; set `chattr +i` if needed |

---

## Pattern Analysis

### VMs 104 and 105 share identical issues
Both Tdarr VMs (VLAN 10) appear to have been built from the same template or provisioned at the same time. They share the exact same three issues:
1. Missing `mtu 9000` on ens18 in interfaces file
2. `dns-nameservers 10.25.0.1` instead of `1.1.1.1 8.8.8.8`
3. resolv.conf immutable status unconfirmed

This suggests these VMs were set up before the DC01 v1.1 standards were fully applied, and the overhaul only partially touched them (ens19 is correctly configured on both).

### VMs 101 and 102 (VLAN 5) are cleanest
These were likely the first VMs standardized during the overhaul. VM 101 is fully clean. VM 102 only lacks the immutable flag on resolv.conf.

### VM 103 (VLAN 66) has a design question
The CRITICAL finding on VM 103 requires a decision: is MTU 9000 correct for the dirty VLAN, or should it be 1500? The Gluetun VPN tunnel will add overhead, and the upstream ISP link almost certainly does not support jumbo frames. However, the switch has jumbo frames everywhere, and NFS traffic from this VM routes via ens19 (Mgmt VLAN) which IS 9000, so ens18 MTU may not matter for NFS performance.

---

## Recommended Fix Order

1. **F-S034-02 (CRITICAL):** Decide on VM 103 ens18 MTU. If 9000 is correct, update the interfaces file. If 1500 is correct, update DC01.md and investigate why live shows 9000.
2. **F-S034-03 + F-S034-05 (HIGH):** Add `mtu 9000` to ens18 on VMs 104 and 105.
3. **F-S034-01 (HIGH):** Set `chattr +i /etc/resolv.conf` on VM 102.
4. **F-S034-05a + F-S034-05b (HIGH):** Check and set `chattr +i /etc/resolv.conf` on VMs 104 and 105.
5. **F-S034-04 + F-S034-06 (MEDIUM):** Update `dns-nameservers` in interfaces files on VMs 104 and 105.

**Estimated fix time:** 15-20 minutes for all fixes (all are single-line config edits + chattr commands).

---

## What Passed (No Issues)

- All 5 VMs: correct IP addresses on both NICs
- All 5 VMs: correct gateways (or no gateway where appropriate)
- All 5 VMs: VPN return route (10.25.100.0/24 via 10.25.255.1 dev ens19) present and correct
- All 5 VMs: NFS mounted and accessible with correct options (nfsvers=3, soft, timeo=150, retrans=3, bg)
- All 5 VMs: correct NFS server IPs (Storage VLAN 10.25.25.25 for 101/102/104/105, Mgmt VLAN 10.25.255.25 for 103)
- All 5 VMs: all interfaces UP, no unexpected DOWN states
- All 5 VMs: ens19 (Mgmt NIC) MTU 9000 in both config and live
- VM 101: fully clean, zero findings
- VMs 101/102: static route 10.25.0.0/24 via 10.25.5.5 present and correct
