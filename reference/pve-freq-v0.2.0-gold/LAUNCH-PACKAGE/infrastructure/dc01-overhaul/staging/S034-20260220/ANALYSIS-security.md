# DC01 Security Posture Audit -- S034

**Date:** 2026-02-20
**Auditor:** Jarvis (Automated Security Analysis)
**Scope:** All in-scope systems: pve01, pve03, VM 101-105, TrueNAS, pfSense, Cisco Switch
**Data Source:** `/home/sonny-aif/dc01-overhaul/staging/S034-20260220/`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Identity & Access -- svc-admin](#2-identity--access----svc-admin)
3. [Identity & Access -- sonny-aif](#3-identity--access----sonny-aif)
4. [Identity & Access -- Other Users](#4-identity--access----other-users)
5. [Sudo Configuration](#5-sudo-configuration)
6. [SSH Security](#6-ssh-security)
7. [Firewall Rules](#7-firewall-rules)
8. [Credential Exposure](#8-credential-exposure)
9. [TrueNAS Specific](#9-truenas-specific)
10. [Switch Specific](#10-switch-specific)
11. [pfSense Specific](#11-pfsense-specific)
12. [NFS Security](#12-nfs-security)
13. [Findings Summary Table](#13-findings-summary-table)
14. [Recommendations](#14-recommendations)

---

## 1. Executive Summary

The overall security posture is **reasonable for a homelab/production hybrid environment** but has several issues requiring attention. The svc-admin service account is correctly standardized (UID 3003, GID 950) across all 10 systems. Root SSH login is disabled on all Linux systems. Proxmox web UI iptables restrictions are properly in place.

**Critical findings:**
- CRITICAL: Plaintext WireGuard private key exposed in VM103 `.env` file AND in the staging data collection
- CRITICAL: Switch running-config.txt contains plaintext console/VTY passwords
- CRITICAL: TrueNAS SSH private host keys (RSA, ECDSA, Ed25519) are exposed in base64 in the staging data
- CRITICAL: TrueNAS user password hashes (Unix + SMB/NTLM) exposed in the staging data for ALL users

**High findings:**
- HIGH: `no service password-encryption` on the Cisco switch -- all passwords stored as type 5 (MD5) or plaintext
- HIGH: TrueNAS has weak ciphers enabled: AES128-CBC and NONE
- HIGH: Password authentication still enabled for SSH on all Linux VMs (default)
- HIGH: NFS export `/mnt/mega-pool/ha-proxmox-disk` allows access from ANY host (`*`)
- HIGH: pfSense sonny-aif UID=2000, chrisadmin UID=2001 -- not matching expected UID scheme

---

## 2. Identity & Access -- svc-admin

### UID/GID Verification

| System | UID | GID | Primary Group | Expected | Status |
|--------|-----|-----|---------------|----------|--------|
| pve01 | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| pve03 | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| VM 101 (Plex) | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| VM 102 (Arr) | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| VM 103 (qBit) | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| VM 104 (Tdarr-Node) | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| VM 105 (Tdarr-Server) | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| TrueNAS | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| pfSense | 3003 | 950 | truenas_admin | 3003:950 | PASS |
| Switch | N/A (privilege 15) | N/A | N/A | privilege 15 | PASS |

**Result: svc-admin UID/GID is CORRECT and CONSISTENT across all 10 systems.**

### Group Membership

| System | Groups | Docker Group | Status |
|--------|--------|-------------|--------|
| pve01 | truenas_admin, sudo | N/A (hypervisor) | PASS |
| pve03 | truenas_admin, sudo | N/A (hypervisor) | PASS |
| VM 101 | truenas_admin, sudo, docker | YES (GID 989) | PASS |
| VM 102 | truenas_admin, sudo, docker | YES (GID 103) | PASS |
| VM 103 | truenas_admin, sudo, docker | YES (GID 103) | PASS |
| VM 104 | truenas_admin, sudo, docker | YES (GID 989) | PASS |
| VM 105 | truenas_admin, sudo, docker | YES (GID 989) | PASS |
| TrueNAS | truenas_admin, builtin_administrators, builtin_users | N/A | PASS |
| pfSense | truenas_admin, admins | N/A | PASS |

### TrueNAS Roles
- svc-admin: `FULL_ADMIN` role -- CORRECT
- svc-admin: `sudo_commands_nopasswd: ["ALL"]` via truenas_admin group -- CORRECT
- svc-admin: `ssh_password_enabled: true` -- correct for current phase (pre-SSH-key)
- svc-admin: Member of groups 40 (builtin_administrators), 43 (truenas_admin), 91 (builtin_users)

---

## 3. Identity & Access -- sonny-aif

### UID/GID by System

| System | UID | GID | Primary Group | Expected | Status |
|--------|-----|-----|---------------|----------|--------|
| pve01 | 1001 | 1001 | sonny-aif | 3000:950 | **DEVIATION** |
| pve03 | 1000 | 1000 | sonny-aif | 3000:950 | **DEVIATION** |
| VM 101 | 3000 | 950 | truenas_admin | 3000:950 | PASS |
| VM 102 | 3000 | 950 | truenas_admin | 3000:950 | PASS |
| VM 103 | 3000 | 950 | truenas_admin | 3000:950 | PASS |
| VM 104 | 3000 | 950 | truenas_admin | 3000:950 | PASS |
| VM 105 | 3000 | 950 | truenas_admin | 3000:950 | PASS |
| TrueNAS | 3000 | 950 | truenas_admin | 3000:950 | PASS |
| pfSense | 2000 | 65534 | nobody | 3000:950 | **DEVIATION** |

**Findings:**
- **F-SEC-001 (MEDIUM):** pve01 sonny-aif is UID 1001:1001 -- this is the Proxmox default installer UID. Not matching the standard 3000:950. This is expected behavior for Proxmox hosts (sonny-aif was the initial install user) but creates NFS ownership mismatches if sonny-aif accesses NFS from the hypervisor directly.
- **F-SEC-002 (MEDIUM):** pve03 sonny-aif is UID 1000:1000 -- same situation as pve01 but different UID (1000 vs 1001). Inconsistent even between the two Proxmox hosts.
- **F-SEC-003 (MEDIUM):** pfSense sonny-aif is UID 2000 with GID 65534 (nobody). Not matching standard. pfSense uses its own UID allocation. The primary group is `nobody` (65534) rather than `truenas_admin` (950). This is a known pfSense limitation but worth documenting.

---

## 4. Identity & Access -- Other Users

### Users Present Across Systems

| User | pve01 | pve03 | VMs | TrueNAS | pfSense | Switch | Notes |
|------|-------|-------|-----|---------|---------|--------|-------|
| root | Yes | Yes | Yes | Yes (pwd disabled) | Yes | N/A | Expected |
| svc-admin | Yes | Yes | Yes (all) | Yes | Yes | Yes | Standard |
| sonny-aif | Yes | Yes | Yes (all) | Yes | Yes | Yes | Standard |
| truenas_admin | No | No | No | Yes (UID 950) | No | No | TrueNAS default admin |
| chrisadmin | No | No | No | Yes (UID 3001) | Yes (UID 2001) | No | Known admin |
| donmin | No | No | No | Yes (UID 3002) | No | No | Known admin |
| jonnybegood | No | No | No | No | No | No | **MISSING** |
| admin | No | No | No | No | Yes (UID 0) | Yes (priv 15) | pfSense default / switch admin |
| gigecolo | No | No | No | No | No | Yes (priv 15) | Switch legacy user |
| plex | No | No | Sudo only (VM101) | No | No | No | See below |

**Findings:**
- **F-SEC-004 (LOW):** `jonnybegood` is listed as an admin in CLAUDE.md but does not exist on ANY system in the data collection. Either this user was never created, has been removed, or exists only in Proxmox PAM auth (which would not show in `/etc/passwd`).
- **F-SEC-005 (INFO):** `donmin` user exists on pve01 in the `users` group (GID 100) alongside sonny-aif. This is from the Proxmox default group -- harmless but inconsistent since donmin does not have a full account on pve01.
- **F-SEC-006 (LOW):** `plex` user appears in the sudo group on VM 101 (`sudo:x:27:plex,sonny-aif,svc-admin`). This is likely the Plex Media Server system user. Having it in the sudo group is unnecessary and a minor privilege escalation risk. Plex should not need sudo.
- **F-SEC-007 (MEDIUM):** pfSense `admin` user has UID 0 (root equivalent via `admin:*:0:0`). This is the default pfSense admin account. It should be reviewed -- if not actively used, consider disabling or strengthening.
- **F-SEC-008 (LOW):** Switch has legacy `gigecolo` user with privilege 15. If this is not actively used, it should be removed to reduce attack surface.
- **F-SEC-009 (LOW):** Switch has generic `admin` user with privilege 15. Combined with `gigecolo` and `svc-admin`, that is 3 privilege-15 accounts plus the enable secret. Consider consolidating to svc-admin only.
- **F-SEC-010 (MEDIUM):** pfSense `chrisadmin` user has UID 2001 with GID 65534 (nobody) and is in the `admins` group. The UID does not match TrueNAS (3001). This is a pfSense-specific deviation since pfSense manages its own UIDs.

---

## 5. Sudo Configuration

### Per-System Sudo Audit

| System | svc-admin NOPASSWD ALL | sonny-aif NOPASSWD ALL | Method | Status |
|--------|----------------------|----------------------|--------|--------|
| pve01 | Yes (`/etc/sudoers.d/svc-admin`) | Yes (`/etc/sudoers.d/sonny-aif`) | sudoers.d files | PASS |
| pve03 | Yes (`/etc/sudoers.d/svc-admin`) | Yes (`/etc/sudoers.d/sonny-aif`) | sudoers.d files | PASS |
| VM 101 | Yes (`/etc/sudoers.d/svc-admin`) | Yes (`/etc/sudoers.d/sonny-aif`) | sudoers.d files | PASS |
| VM 102 | Yes (`/etc/sudoers.d/svc-admin`) | Yes (`/etc/sudoers.d/sonny-aif`) | sudoers.d files | PASS |
| VM 103 | Yes (`/etc/sudoers.d/svc-admin`) | Yes (`/etc/sudoers.d/sonny-aif`) | sudoers.d files | PASS |
| VM 104 | Yes (`/etc/sudoers.d/svc-admin`) | Yes (`/etc/sudoers.d/sonny-aif`) | sudoers.d files | PASS |
| VM 105 | Yes (`/etc/sudoers.d/svc-admin`) | Yes (`/etc/sudoers.d/sonny-aif`) | sudoers.d files | PASS |
| TrueNAS | Yes (truenas_admin group) | Yes (truenas_admin group) | group-level NOPASSWD ALL | PASS |
| pfSense | Yes (`/usr/local/etc/sudoers.d/svc-admin`) | No explicit file | sudoers.d file | PASS |

**File permissions on sudoers.d files:** All systems show `-r--r----- root root` (0440) -- CORRECT.

**Findings:**
- **F-SEC-011 (INFO):** All Linux systems also have `%sudo ALL=(ALL:ALL) ALL` in the main sudoers file. Since both svc-admin and sonny-aif are in the sudo group AND have NOPASSWD sudoers.d entries, the NOPASSWD rule takes precedence (sudoers.d processed after). No issue, just noting the double-coverage.
- **F-SEC-012 (INFO):** TrueNAS truenas_admin group provides `sudo_commands_nopasswd: ["ALL"]` to all members (truenas_admin, sonny-aif, chrisadmin, donmin, svc-admin). This is by design for the admin group.

---

## 6. SSH Security

### sshd_config Comparison

| Setting | pve01 | pve03 | VM101 | VM102 | VM103 | VM104 | VM105 | TrueNAS |
|---------|-------|-------|-------|-------|-------|-------|-------|---------|
| PermitRootLogin | **no** | **no** | **no** | **no** | **no** | **no** | **no** | **without-password** |
| PasswordAuthentication | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | **no** (global), **yes** (per-user Match) |
| PubkeyAuthentication | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | commented (default yes) | **yes** (explicit) |
| KbdInteractiveAuthentication | **no** | **no** | **no** | **no** | **no** | **no** | **no** | N/A |
| X11Forwarding | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** | N/A |
| UsePAM | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** | **yes** |
| ListenAddress | default (all) | default (all) | default (all) | default (all) | default (all) | default (all) | default (all) | **127.0.0.1, 10.25.255.25, fe80::...%eno4** |
| Include sshd_config.d | Yes | Yes | Yes | Yes | Yes | Yes | Yes | No |

**Findings:**
- **F-SEC-013 (HIGH):** PasswordAuthentication is NOT explicitly disabled on ANY of the 7 Linux systems (pve01, pve03, VM101-105). The line is commented out, meaning it defaults to `yes`. Combined with `UsePAM yes`, password-based SSH login is ACTIVE on all these systems. This is a known pre-SSH-key-deployment state but remains a risk.
- **F-SEC-014 (MEDIUM):** TrueNAS `PermitRootLogin without-password` allows root login via SSH key. While root currently has `password_disabled: true` and `sshpubkey: null`, if a root SSH key were ever deployed, root could SSH in directly. Recommendation: Set to `no` and use svc-admin with sudo instead.
- **F-SEC-015 (HIGH):** TrueNAS weak ciphers enabled: `AES128-CBC` and `NONE`. The `NONE` cipher is particularly dangerous -- it means SSH connections can negotiate NO ENCRYPTION. The `Ciphers +aes128-cbc` line in sshd_config adds the deprecated CBC cipher to the allowed list. This should be removed.
- **F-SEC-016 (MEDIUM):** X11Forwarding is enabled on all 7 Linux systems. These are headless servers with no X11 display. X11 forwarding should be disabled to reduce attack surface.
- **F-SEC-017 (INFO):** TrueNAS SSH correctly binds to eno4 (management VLAN 2550) via `ListenAddress 10.25.255.25` plus localhost. The fe80 link-local address is also bound to eno4. SSH binding is CORRECT as expected.
- **F-SEC-018 (MEDIUM):** TrueNAS has per-user Match blocks enabling PasswordAuthentication for truenas_admin, sonny-aif, and svc-admin. This is necessary for the current password-based workflow but should be removed after SSH key deployment.
- **F-SEC-019 (INFO):** All Linux systems include `/etc/ssh/sshd_config.d/*.conf` which could contain overrides. The contents of these directories were not collected. If any drop-in config re-enables password auth or root login, it would not be visible in this audit.

---

## 7. Firewall Rules

### Proxmox Nodes -- iptables (Port 8006 Restriction)

**pve01:**
```
-A INPUT -i vmbr0v2550 -p tcp --dport 8006 -j ACCEPT       # Management VLAN interface
-A INPUT -s 10.25.0.28/32 -p tcp --dport 8006 -j ACCEPT     # pve03 cluster peer
-A INPUT -i lo -p tcp --dport 8006 -j ACCEPT                 # Localhost
-A INPUT -p tcp --dport 8006 -j DROP                          # Drop all else
```
**Status: CORRECT.** Rules match expected state exactly. The cluster peer is pve03 (10.25.0.28), management VLAN interface is vmbr0v2550, and all other access to port 8006 is dropped.

**pve03:**
```
-A INPUT -i vmbr0v2550 -p tcp --dport 8006 -j ACCEPT       # Management VLAN interface
-A INPUT -s 10.25.0.26/32 -p tcp --dport 8006 -j ACCEPT     # pve01 cluster peer
-A INPUT -i lo -p tcp --dport 8006 -j ACCEPT                 # Localhost
-A INPUT -p tcp --dport 8006 -j DROP                          # Drop all else
```
**Status: CORRECT.** Mirror of pve01 rules with the appropriate peer IP (10.25.0.26 = pve01).

**Drop statistics confirm rules are active:**
- pve01: 42 packets dropped
- pve03: 27 packets dropped

### VM Firewalls

VMs 101-103 have Docker-managed iptables rules (DOCKER chains). No custom INPUT rules beyond Docker defaults.
VMs 104-105 have NO iptables file collected (no Docker networking rules visible since they use host networking or different Docker modes).

**Findings:**
- **F-SEC-020 (INFO):** All VM INPUT policies are `ACCEPT`. There are no host-level INPUT firewall rules on any VM. This is standard for internal VMs behind pfSense, but means any service listening on a VM is accessible from any VLAN that can route to it. Network segmentation relies entirely on pfSense rules.
- **F-SEC-021 (INFO):** VM103 DOCKER-USER chain has a blanket `RETURN` rule, meaning all forwarded traffic passes through without filtering. This is the Docker default but means Docker port mappings are accessible from any source.

### pfSense -- pf Rules

**Key security rules identified:**
1. Default deny (both IPv4 and IPv6) in and out -- CORRECT baseline
2. Anti-lockout disabled (confirmed by absence of anti-lockout pass rule)
3. WebGUI blocks in place:
   - `block drop in quick on WireGuard ... to 10.25.0.1 port = http` -- blocks HTTP on LAN IP from VPN
   - `block drop in quick on WireGuard ... to 10.25.0.1 port = 4443` -- blocks WebGUI port on LAN IP from VPN
   - `block drop in quick on lagg0 ... to (self) port = http` -- blocks HTTP on LAN
   - `block drop in quick on lagg0 ... to (self) port = 4443` -- blocks WebGUI on LAN
4. WireGuard VPN access rules:
   - VPN subnet (10.25.100.0/24) has pass rules to: LAN, MANAGEMENT, PUBLIC, COMPUTE, DIRTY networks
5. VLAN isolation:
   - VLAN 66 (Dirty): Blocked from LAN, Public, Compute, Storage, own-subnet-routing, Management, and all RFC1918 catch-alls. Only allowed outbound internet.
   - VLAN 5 (Public): NFS to TrueNAS (10.25.25.25) allowed. RFC1918 blocked. Internet outbound allowed.
   - VLAN 10 (Compute): Only local connections to gateway (10.25.10.1) allowed.
   - VLAN 25 (Storage): Only intra-VLAN traffic allowed.
   - VLAN 2550 (Management): VPN and LAN allowed in. All other sources blocked.
6. sshguard and virusprot tables active -- brute-force protection present.

**Findings:**
- **F-SEC-022 (MEDIUM):** VLAN 5 (Public) has `pass in quick on lagg0.5 ... from <OPT5_NETWORK> to 10.25.25.25` -- this allows the Public VLAN to reach the TrueNAS storage IP for NFS. This is intentional (Plex needs NFS) but means any compromised Public VLAN device could attempt NFS access.
- **F-SEC-023 (LOW):** VLAN 10 (Compute) only allows connections to its own gateway (10.25.10.1). There is no explicit rule allowing Compute VLAN to reach the Storage VLAN (10.25.25.0/24) for NFS. VM104 and VM105 would need a route through their management NIC or a missing rule to access NFS. If NFS works from these VMs, there may be routing via management VLAN that bypasses this restriction.
- **F-SEC-024 (INFO):** WAN rules allow inbound: WireGuard UDP (port 51820 on 69.65.20.58), NAT to Mamadou Server (port 8006 on 10.25.0.9), and NAT to Plex (port 32400 on 10.25.5.30). These are expected external services.
- **F-SEC-025 (MEDIUM):** The NAT rule for "Mamadou Server" passes TCP port 8006 from the internet to 10.25.0.9 -- this appears to be a Proxmox web UI NAT. Exposing Proxmox web UI directly to the internet is a significant risk. Verify this is intentional and consider restricting source IPs.

---

## 8. Credential Exposure

### CRITICAL: Plaintext Credentials in Staging Data

- **F-SEC-026 (CRITICAL):** `switch/running-config.txt` (the UNREDACTED version) contains plaintext passwords:
  - Line 30: `enable secret 5 <REDACTED>`
  - Line 32-35: All username secret 5 hashes in cleartext
  - Lines 508, 512: **PLAINTEXT console and VTY passwords: `<REDACTED>`**
  - The redacted version (`running-config-redacted.txt`) has `<REDACTED>` markers in the right places, but the unredacted file should NOT be stored in staging.

- **F-SEC-027 (CRITICAL):** `truenas/users.txt` contains Unix password hashes (`$6$rounds=...`) and SMB/NTLM hashes for ALL users:
  - truenas_admin: Unix hash + SMB hash exposed
  - sonny-aif: Unix hash + SMB hash exposed
  - chrisadmin: Unix hash + SMB hash exposed + password history hashes
  - donmin: Unix hash + SMB hash exposed + 2 password history hashes
  - svc-admin: Unix hash + SMB hash exposed + 2 password history hashes

- **F-SEC-028 (CRITICAL):** `truenas/ssh-config.txt` contains base64-encoded SSH private host keys:
  - `host_ecdsa_key`: Full private key in base64
  - `host_ed25519_key`: Full private key in base64
  - `host_rsa_key`: Full private key in base64
  - These are the SERVER's SSH host keys. If compromised, an attacker could perform MITM attacks on SSH connections to TrueNAS.

- **F-SEC-029 (CRITICAL):** `vm103/docker-env.txt` contains a plaintext WireGuard private key:
  - `WIREGUARD_PRIVATE_KEY=<REDACTED>`
  - This is the Gluetun VPN client private key. If this is a real key for a paid VPN service, it is now exposed.

### Credential Exposure in Deployed Configs

- **F-SEC-030 (HIGH):** The Cisco switch has `no service password-encryption` configured. While the enable secret and username secrets use type 5 (MD5 hashing), the console and VTY line passwords are stored in **PLAINTEXT** in the running config (visible as `<REDACTED>`). `service password-encryption` would encode these as type 7 (weak obfuscation, but better than plaintext).

---

## 9. TrueNAS Specific

### SSH Binding
- SSH binds to: `127.0.0.1`, `10.25.255.25`, `fe80::1a66:daff:fe7f:d8d%eno4`
- eno4 is confirmed as the Management VLAN interface (10.25.255.25)
- **Status: CORRECT.** SSH is properly restricted to eno4 (management) only.

### Web UI Binding
- `ui_address: ['10.25.255.25']` -- bound to management VLAN only
- `ui_v6address: ['::']` -- IPv6 listens on all interfaces (known finding F-021, LOW risk, no IPv6 routing)
- **Status: CORRECT** (with known IPv6 caveat).

### User Roles
| User | UID | Roles | FULL_ADMIN | SSH Password | SMB |
|------|-----|-------|------------|-------------|-----|
| root | 0 | FULL_ADMIN | Yes | No | No |
| truenas_admin | 950 | FULL_ADMIN | Yes | Yes | No |
| sonny-aif | 3000 | FULL_ADMIN | Yes | Yes | Yes |
| chrisadmin | 3001 | FULL_ADMIN | Yes | No | Yes |
| donmin | 3002 | FULL_ADMIN | Yes | No | Yes |
| svc-admin | 3003 | FULL_ADMIN | Yes | Yes | Yes |

**Findings:**
- **F-SEC-031 (MEDIUM):** Both `truenas_admin` (the TrueNAS default admin) and `svc-admin` are `FULL_ADMIN` with SSH password enabled. When SSH key auth is deployed, the `truenas_admin` account should have its SSH password disabled as svc-admin becomes the primary.
- **F-SEC-032 (LOW):** Root account has `password_disabled: true` and `sshpubkey: null` -- GOOD. Root cannot log in via password or SSH key.
- **F-SEC-033 (INFO):** TrueNAS services running: cifs (SMB), nfs, ssh. FTP, iSCSI, SNMP, UPS, NVMe are all stopped/disabled. Good minimal service footprint.

### Weak Ciphers
- **F-SEC-034 (HIGH):** TrueNAS SSH has `weak_ciphers: ["AES128-CBC", "NONE"]` enabled. The `NONE` cipher allows UNENCRYPTED SSH sessions. The `AES128-CBC` cipher is deprecated due to known attacks (BEAST, Lucky13). These MUST be removed.
- The sshd_config confirms: `Ciphers +aes128-cbc` is active.

---

## 10. Switch Specific

### Password Encryption
- **F-SEC-035 (HIGH):** `no service password-encryption` -- passwords in running-config are not encrypted.
- Enable secret: type 5 (MD5-based) -- acceptable
- Username secrets: type 5 (MD5-based) -- acceptable
- Console/VTY line passwords: **PLAINTEXT** -- unacceptable
- **Remediation:** Run `service password-encryption` and change line passwords to use `secret` instead of `password`.

### User Accounts
| Username | Privilege Level | Notes |
|----------|----------------|-------|
| admin | 15 | Generic -- should be removed |
| gigecolo | 15 | Legacy hostname-based -- should be removed |
| sonny-aif | 15 | Standard |
| svc-admin | 15 | Standard |

- **F-SEC-036 (MEDIUM):** 4 privilege-15 accounts plus an enable secret is excessive. Recommend consolidating to svc-admin only (plus enable secret for emergency console access).

### Access Security
- SSH version 2 enforced -- GOOD
- HTTP/HTTPS server disabled (`no ip http server`, `no ip http secure-server`) -- GOOD
- VTY lines 0-4 use `login local` with `transport input ssh` -- SSH only, no telnet -- GOOD

---

## 11. pfSense Specific

### User Accounts
| User | UID | GID | Shell | Groups | Notes |
|------|-----|-----|-------|--------|-------|
| admin | 0 | 0 | /etc/rc.initial | wheel | Root-equivalent default |
| chrisadmin | 2001 | 65534 | /bin/tcsh | admins | Non-standard UID |
| sonny-aif | 2000 | 65534 | /bin/tcsh | admins | Non-standard UID |
| svc-admin | 3003 | 950 | /bin/tcsh | admins, truenas_admin | CORRECT |

- **F-SEC-037 (LOW):** pfSense uses its own UID allocation. sonny-aif=2000, chrisadmin=2001 do not match the Linux/TrueNAS standard. This is expected behavior for pfSense (BSD-based) but breaks NFS UID consistency if pfSense ever accesses NFS (it should not).

### Sudo
- svc-admin: `ALL=(ALL) NOPASSWD: ALL` in sudoers.d -- CORRECT

### WebGUI
- LACP config: LACP mode, fast timeout, igc2+igc3 -- CORRECT per CLAUDE.md
- Anti-lockout disabled -- CORRECT per policy
- WebGUI blocked on LAN IP (lagg0) and WAN IP from VPN -- CORRECT

---

## 12. NFS Security

### Export Configuration
```
/mnt/mega-pool/nfs-mega-share  -- 7 networks, all_squash to 3003:950
/mnt/mega-pool/ha-proxmox-disk -- * (ANY HOST), no squash
```

- **F-SEC-038 (HIGH):** The `ha-proxmox-disk` NFS export allows access from ANY host (`*`) with NO mapall/squash restrictions. Any device that can reach the NFS port on TrueNAS can mount this share with full permissions. This is the Proxmox HA disk storage and should be restricted to Proxmox node IPs only.

### NFS Binding
- NFS service binds to: `10.25.25.25` (Storage VLAN), `10.25.255.25` (Management VLAN)
- **Status: CORRECT.** NFS is not exposed on the LAN (10.25.0.25).

### Media Share Security
- `nfs-mega-share` uses `all_squash` with `anonuid=3003, anongid=950` -- maps all access to svc-admin:truenas_admin -- CORRECT
- Networks allowed: 172.28.16.0/20 (Docker internal), 10.25.100.0/24 (VPN), 10.25.0.0/24 (LAN), 10.25.25.0/24 (Storage), 10.25.10.0/24 (Compute), 10.25.5.0/24 (Public), 10.25.255.0/24 (Management)
- **F-SEC-039 (MEDIUM):** The NFS export allows 7 networks. Per CLAUDE.md future plans, this should be reduced to minimum needed. The VPN subnet (10.25.100.0/24) and Docker internal (172.28.16.0/20) allowances may not be necessary for production.

---

## 13. Findings Summary Table

| ID | Severity | System | Finding |
|----|----------|--------|---------|
| F-SEC-001 | MEDIUM | pve01 | sonny-aif UID 1001:1001 (not 3000:950) |
| F-SEC-002 | MEDIUM | pve03 | sonny-aif UID 1000:1000 (not 3000:950) |
| F-SEC-003 | MEDIUM | pfSense | sonny-aif UID 2000:65534 (not 3000:950) |
| F-SEC-004 | LOW | All | jonnybegood user missing from all systems |
| F-SEC-005 | INFO | pve01 | donmin in users group (no full account) |
| F-SEC-006 | LOW | VM 101 | plex user in sudo group (unnecessary) |
| F-SEC-007 | MEDIUM | pfSense | Default admin account (UID 0) still present |
| F-SEC-008 | LOW | Switch | Legacy gigecolo user with privilege 15 |
| F-SEC-009 | LOW | Switch | Generic admin user with privilege 15 |
| F-SEC-010 | MEDIUM | pfSense | chrisadmin UID 2001 not matching standard |
| F-SEC-011 | INFO | All Linux | Double sudo coverage (group + sudoers.d) |
| F-SEC-012 | INFO | TrueNAS | truenas_admin group provides NOPASSWD ALL |
| F-SEC-013 | HIGH | All Linux (7) | PasswordAuthentication not explicitly disabled |
| F-SEC-014 | MEDIUM | TrueNAS | PermitRootLogin without-password (key-based root possible) |
| F-SEC-015 | HIGH | TrueNAS | Weak ciphers: AES128-CBC and NONE enabled |
| F-SEC-016 | MEDIUM | All Linux (7) | X11Forwarding enabled on headless servers |
| F-SEC-017 | INFO | TrueNAS | SSH binding to eno4 only -- CORRECT |
| F-SEC-018 | MEDIUM | TrueNAS | Per-user password auth Match blocks |
| F-SEC-019 | INFO | All Linux (7) | sshd_config.d includes not audited |
| F-SEC-020 | INFO | VMs 101-105 | No host-level INPUT firewall rules |
| F-SEC-021 | INFO | VM 103 | DOCKER-USER chain blanket RETURN |
| F-SEC-022 | MEDIUM | pfSense | Public VLAN can reach TrueNAS NFS |
| F-SEC-023 | LOW | pfSense | Compute VLAN has no explicit NFS path |
| F-SEC-024 | INFO | pfSense | Expected WAN NAT rules present |
| F-SEC-025 | MEDIUM | pfSense | Proxmox Web UI (8006) NAT to internet |
| F-SEC-026 | CRITICAL | Staging | Plaintext switch passwords in running-config.txt |
| F-SEC-027 | CRITICAL | Staging | Unix + SMB password hashes for all TrueNAS users |
| F-SEC-028 | CRITICAL | Staging | SSH private host keys exposed in base64 |
| F-SEC-029 | CRITICAL | Staging | WireGuard private key in VM103 docker-env.txt |
| F-SEC-030 | HIGH | Switch | no service password-encryption -- plaintext line passwords |
| F-SEC-031 | MEDIUM | TrueNAS | truenas_admin and svc-admin both FULL_ADMIN with SSH pwd |
| F-SEC-032 | LOW | TrueNAS | Root password disabled and no SSH key -- GOOD |
| F-SEC-033 | INFO | TrueNAS | Minimal service footprint -- GOOD |
| F-SEC-034 | HIGH | TrueNAS | NONE cipher allows unencrypted SSH |
| F-SEC-035 | HIGH | Switch | Plaintext console/VTY passwords in running config |
| F-SEC-036 | MEDIUM | Switch | 4 privilege-15 accounts (excessive) |
| F-SEC-037 | LOW | pfSense | Non-standard UIDs (BSD limitation) |
| F-SEC-038 | HIGH | TrueNAS | ha-proxmox-disk NFS export open to ANY host |
| F-SEC-039 | MEDIUM | TrueNAS | NFS export allows 7 networks (more than needed) |

### Severity Count

| Severity | Count |
|----------|-------|
| CRITICAL | 4 |
| HIGH | 6 |
| MEDIUM | 13 |
| LOW | 7 |
| INFO | 9 |
| **Total** | **39** |

---

## 14. Recommendations

### Immediate Actions (CRITICAL)

1. **Delete `switch/running-config.txt`** from staging (the unredacted version). Keep only `running-config-redacted.txt`. The plaintext passwords are now in this file on disk.
2. **Delete or redact `truenas/users.txt`** -- it contains crackable password hashes and NTLM hashes for every admin account.
3. **Delete or redact `truenas/ssh-config.txt`** SSH host private keys section -- or at minimum, ensure this staging data is not accessible to untrusted parties.
4. **Rotate the WireGuard private key** on VM103 since it is now exposed in `vm103/docker-env.txt`. Generate a new keypair and update the VPN provider config.

### Short-Term Actions (HIGH)

5. **Enable `service password-encryption`** on the Cisco switch and change line passwords to use `secret` keyword.
6. **Remove weak ciphers on TrueNAS:** Via the web UI, remove `AES128-CBC` and `NONE` from the allowed SSH ciphers list.
7. **Explicitly set `PasswordAuthentication no`** in sshd_config on all 7 Linux systems (pve01, pve03, VM101-105) AFTER deploying SSH keys. This is the planned SSH key deployment task.
8. **Restrict `ha-proxmox-disk` NFS export** to Proxmox node IPs only (10.25.0.26, 10.25.0.27, 10.25.0.28) instead of `*`.

### Medium-Term Actions

9. **Remove plex from sudo group** on VM 101.
10. **Consolidate switch users** to svc-admin only. Remove admin and gigecolo accounts.
11. **Disable X11Forwarding** on all headless Linux systems.
12. **Set TrueNAS PermitRootLogin to `no`** instead of `without-password`.
13. **Review the Mamadou Server NAT rule** (pfSense F-SEC-025) -- Proxmox 8006 exposed to internet is high risk.
14. **Reduce NFS allowed networks** to only those that actually need NFS access.
15. **Verify jonnybegood account** status -- is it in Proxmox PAM only, or was it never created?
16. **Standardize pfSense UIDs** for sonny-aif and chrisadmin if possible (may require user recreation on pfSense).

---

*End of Security Audit Report -- S034*
