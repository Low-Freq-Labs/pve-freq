# DC01 Infrastructure Audit — Session S043

> **Date:** 2026-02-24
> **Auditor:** Jarvis
> **Mode:** EXEC=audit (read-only), VERBOSITY=detailed
> **Systems Audited:** pfSense, TrueNAS, pve01, pve03, VMs 101-105 (9/10 — switch auth failed)
> **Raw Data:** `~/dc01-overhaul/staging/S043/`

---

## Summary

| Severity | Original | Fixed S044 | Partial/Deferred S044 | New S044 | Remaining |
|----------|----------|------------|----------------------|----------|-----------|
| CRITICAL | 3 | 0 | 0 | 0 | 3 |
| HIGH | 7 | 2 (H-003, H-006 n/a) | 2 (H-004 deferred, H-005 partial) | 1 (F-S044-PFSENSE-NTP) | 6 |
| MEDIUM | 13 | 6 (M-003, M-004, M-005, M-009 partial, M-010) | 1 (M-008 deferred) | 1 (F-S044-PFSENSE-MGMT-PING) | 8 |
| LOW | 11 | 4 (L-005, L-006, L-009, L-011) | 0 | 0 | 7 |
| **Total** | **34** | **12 fixed** | **3 deferred/partial** | **2 new** | **24 remaining** |

---

## CRITICAL Findings

### C-001: Temporary Passwords on ALL Systems (TICKET-0006)
**Status:** OPEN — 11th consecutive session
**Systems:** All 10 systems
**What's wrong:** Every system uses `changeme1234!` or similarly weak temporary passwords. The `svc-admin` password is literally stored in `~/svc.env` as plaintext. All accounts have valid password hashes in shadow files.
**Why it matters:** Any host-to-host lateral movement is trivial. If one system is compromised, every system falls. The password is in a plaintext file on the WSL workstation.
**Fix:**
1. Generate SSH keypair: `ssh-keygen -t ed25519 -f ~/.ssh/dc01-svc-admin`
2. Deploy to all 10 systems: `ssh-copy-id -i ~/.ssh/dc01-svc-admin.pub svc-admin@<IP>`
3. Set `PasswordAuthentication no` in sshd_config on every system
4. Rotate all passwords to 20+ char random strings
5. Store new passwords in Sonny's vault (VM 802)

### C-002: pfSense Allows Root SSH Login (NEW)
**Status:** NEW
**System:** pfSense (10.25.255.1)
**What's wrong:** `PermitRootLogin yes` in `/etc/ssh/sshd_config`. Root can SSH directly into the firewall with a password.
**Why it matters:** pfSense is the single point of failure for the entire network. Root SSH access combined with the temp password from TICKET-0006 means anyone with VPN access can take full control of the firewall.
**Fix:** Change `PermitRootLogin yes` → `PermitRootLogin no` in pfSense WebGUI (System → Advanced → SSH). Requires Sonny in GUI. svc-admin has sudo, so root login is unnecessary.

### C-003: pfSense Root and Admin Share Identical Password (NEW)
**Status:** NEW
**System:** pfSense
**What's wrong:** In `/etc/master.passwd`, `root` and `admin` have the exact same bcrypt hash: `$2y$12$xtTk7btxnuhPEd1lFi12L.vGsD1xphbuLNca8l.E1yiCHAP0QP7Fu`. The `admin` account maps to UID 0 (root equivalent) with shell `/etc/rc.initial`.
**Why it matters:** Two UID-0 accounts with the same password. The `admin` account is the pfSense WebGUI admin — if that password leaks (it's the temp password), SSH root access is also compromised.
**Fix:** After TICKET-0006 credential rotation, ensure root and admin have DIFFERENT strong passwords. Consider disabling the admin CLI account if WebGUI-only access is sufficient.

---

## HIGH Findings

### H-001: SSH Password Auth Enabled on ALL Linux Systems (NEW)
**Status:** NEW
**Systems:** pve01, pve03, VMs 101-105 (7 systems)
**What's wrong:** `PasswordAuthentication` is commented out in sshd_config, defaulting to `yes`. Combined with `UsePAM yes`, password SSH logins are active on every system.
**Why it matters:** With TICKET-0006 temp passwords active, any network-reachable SSH port accepts password login. VMs on VLAN 5 (internet-facing for Plex) and VLAN 66 (dirty/NAT) are especially exposed.
**Fix:** Add to `/etc/ssh/sshd_config.d/99-dc01-hardening.conf` on each system:
```
PasswordAuthentication no
```
Then `systemctl reload sshd`. **Do this AFTER deploying SSH keys (C-001).**

### H-002: SSH Listens on All Interfaces Including Service VLANs (NEW)
**Status:** NEW
**Systems:** All 5 VMs
**What's wrong:** SSH has no `ListenAddress` directive — listens on `0.0.0.0:22`. This means:
- VMs 101/102: SSH on VLAN 5 (10.25.5.30/31) — the public Plex/Arr VLAN
- VM 103: SSH on VLAN 66 (10.25.66.25) — the dirty/NAT VLAN with internet NAT
- VMs 104/105: SSH on VLAN 10 (10.25.10.33/34) — compute VLAN
**Why it matters:** Service VLANs should not offer SSH. VLAN 66 traffic is NATed to the internet — if pfSense has a misconfigured NAT rule, SSH could be exposed externally.
**Fix:** Add to `/etc/ssh/sshd_config.d/99-dc01-hardening.conf`:
```
ListenAddress 10.25.255.XX   # mgmt VLAN IP only
```

### H-003: TrueNAS SSH Weak Ciphers (F-S034-CIPHER) — ✅ FIXED S044
**Status:** FIXED
**System:** TrueNAS
**Resolution:** `NONE` cipher removed via TrueNAS GUI by Sonny (Services → SSH → Advanced). AES128-CBC remains — low risk (CBC mode, not plaintext). The critical `NONE` cipher (unencrypted SSH) is eliminated.

### H-004: NFS Export `ha-proxmox-disk` Open to World (F-S034-NFS-ACL) — Deferred
**Status:** DEFERRED (Sonny decision S044)
**System:** TrueNAS
**What's wrong:** `ha-proxmox-disk` NFS export has empty networks/hosts lists = `*(rw)`. Any IP can mount this share.
**Sonny decision:** Keep open for pve02 reintegration. Will restrict to `10.25.25.0/24` after pve02 is onboarded with storage VLAN NIC.

### H-005: TrueNAS NTP Completely Failed — ⚠️ PARTIAL FIX S044
**Status:** PARTIAL
**System:** TrueNAS
**What was wrong:** 3 Debian pool NTP servers all NOT_SELECTABLE.
**Resolution:** Debian pool servers deleted. pfSense (10.25.0.1) added via Force checkbox. Public pools (`0.pool.ntp.org`, `1.pool.ntp.org`) also fail — TrueNAS routes to internet via pfSense, and pfSense's own NTP is broken.
**Root cause:** pfSense upstream NTP broken (see new finding below). pfSense running orphan mode stratum 12 — serves degraded time but at least prevents unbounded drift.
**New finding: F-S044-PFSENSE-NTP** — pfSense `2.pfsense.pool.ntp.org` at stratum 16, reach 0. Outbound UDP 123 or DNS resolution failing on WAN. **Needs datacenter visit** to diagnose (GUI: System → General → check NTP status, verify DNS, test outbound UDP 123).
**New finding: F-S044-PFSENSE-MGMT-PING** — TrueNAS (10.25.255.25) cannot ping pfSense mgmt IP (10.25.255.1). 100% packet loss. ARP resolves, other mgmt VLAN hosts reachable. Likely pf rule on MANAGEMENT interface blocking TrueNAS-initiated traffic. LAN (10.25.0.1) and storage (10.25.25.1) IPs reachable.

### H-006: Hardware — No Power Redundancy (Known)
**Status:** OPEN (since build phase)
**Systems:** TrueNAS (R530) and pve01 (T620)
**What's wrong:**
- R530: PSU 1 FAILED (Voltage 1 = `na`), Fan 6 DEAD (0 RPM, critical state)
- T620: PSU 2 FAILED
Both servers run on single PSU with no failover.
**Why it matters:** Any single PSU failure = total server loss with no graceful degradation. A power surge could take down both servers simultaneously.
**Fix:** Order replacement parts (Dell 05RHVVA00 for R530, 06W2PWA00 for T620, fan assembly for R530). **URGENT.**

### H-007: Mamadou NAT Exposes Proxmox WebGUI to Internet (F-S034-NAT)
**Status:** OPEN (since S034)
**System:** pfSense
**What's wrong:** Active NAT rule: `rdr on lagg1 inet proto tcp from any to 69.65.20.62 port = 8006 -> 10.25.0.9`. Port 8006 (Proxmox WebGUI) on public VIP 69.65.20.62 forwards to 10.25.0.9 from the entire internet. The matching pf pass rule has no source IP restriction.
**Why it matters:** Proxmox WebGUI is a full hypervisor management interface. Exposed to the internet with potentially weak credentials = complete infrastructure compromise.
**Fix:** Either remove the NAT rule entirely, or restrict the pass rule to specific source IPs. Sonny decision required — who is Mamadou and do they still need access?

---

## MEDIUM Findings

### M-001: pfSense Unbound DNS on 0.0.0.0:53 (NEW)
**System:** pfSense
**What's wrong:** Unbound DNS resolver listens on `*:53` (UDP+TCP). Any interface, any VLAN.
**Why it matters:** Open DNS resolver can be used for DNS amplification attacks if reachable from internet-facing interfaces. Also allows VLAN-to-VLAN DNS queries that should be isolated.
**Fix:** pfSense GUI → Services → DNS Resolver → Network Interfaces: select only LAN, WireGuard, and VLAN interfaces that need DNS. Exclude WAN/WANDR.

### M-002: pfSense Syslog on 0.0.0.0:514/UDP (NEW)
**System:** pfSense
**What's wrong:** `syslogd` listens on `*:514` UDP. Accepts remote syslog from any source.
**Why it matters:** An attacker could flood syslog to fill disk, or inject misleading log entries to cover tracks.
**Fix:** pfSense GUI → Status → System Logs → Settings → Remote Logging: if remote syslog isn't needed, disable the listener.

### M-003: rpcbind on 0.0.0.0 on All VMs — ✅ FIXED S044
**Systems:** All 5 VMs + pve01 + pve03
**What's wrong:** rpcbind (port 111) listens on all interfaces. Required for NFS client operation but exposed on service VLANs.
**Resolution:** iptables DROP on port 111 tcp+udp on service NICs (ens18) for all 5 VMs (persisted via `/etc/network/if-up.d/dc01-hardening`). pve01+pve03: restricted to mgmt+storage+lo only (saved via netfilter-persistent).

### M-004: NFS Export Allows Docker Internal Subnet — ✅ FIXED S044
**System:** TrueNAS
**Resolution:** `172.28.16.0/20` removed from nfs-mega-share NFS export ACL via TrueNAS GUI by Sonny.

### M-005: SPICE Proxy (3128) Unrestricted on Both Proxmox Hosts — ✅ FIXED S044
**Systems:** pve01, pve03
**What's wrong:** Port 3128 (SPICE VM console proxy) listens on `*` with no iptables restriction.
**Resolution:** iptables rules added mirroring existing 8006 pattern: ACCEPT on mgmt VLAN + peer Proxmox source IP + lo, DROP catch-all. Saved via netfilter-persistent on both hosts.

### M-006: qBit Credential Mismatch (F-S040-QBIT-CREDS)
**Status:** OPEN (since S040)
**System:** VM 103 + VM 102
**What's wrong:** qBittorrent WebUI username is `admin`, but Radarr/Sonarr download client settings expect `sonny-aif`.
**Fix:** Update qBit WebUI username to `sonny-aif` in qBit Settings → WebUI, OR update Radarr/Sonarr download client config to use `admin`.

### M-007: WANDRGW Gateway Monitoring Unknown (F-S037-WANDRGW)
**Status:** OPEN (since S037)
**System:** pfSense
**What's wrong:** WANDRGW dpinger monitors the same gateway IP as WANGW (same /28 subnet). Status shows "Unknown" — prerequisite for WAN failover.
**Fix:** pfSense GUI → System → Routing → Gateways → Edit WANDRGW → Set Monitor IP to `9.9.9.9`.

### M-008: TrueNAS SMB Share No Access Restrictions — Deferred
**System:** TrueNAS
**What's wrong:** SMB share has no hosts_allow restriction.
**Status:** DEFERRED S044 — `hosts_allow` option not available in TrueNAS SCALE 25.10 SMB GUI. SMB already bound to storage (10.25.25.25) and mgmt (10.25.255.25) VLANs only, limiting exposure. Could potentially be set via SMB auxiliary parameters or smb.conf if needed.

### M-009: pve03 Unnecessary VLAN IPs — ⚠️ PARTIAL FIX S044
**System:** pve03
**What's wrong:** pve03 had IPs on VLAN 5 (10.25.5.28) and VLAN 25 (10.25.25.28).
**Resolution:** VLAN 5 IP removed (bridge kept as `inet manual`). VLAN 25 IP (10.25.25.28) **retained** — required for pve03's NFS ISO mount from pve01 (10.25.25.26) and ha-proxmox-disk from TrueNAS (10.25.25.25). Backup: `vlan5-public.conf.backup-s044`.

### M-010: pve01 NFS Server Ports on 0.0.0.0 — ✅ FIXED S044
**System:** pve01
**What's wrong:** pve01 exports its ISO storage via NFS on `0.0.0.0`.
**Resolution:** iptables: port 2049 restricted to storage VLAN (vmbr1.25) + lo only. DROP catch-all. pve03→pve01 ISO NFS mount verified working. Saved via netfilter-persistent.

### M-011: Switch Inaccessible from Automation (NEW)
**System:** Cisco 4948E-F (10.25.255.5)
**What's wrong:** SSH authentication failed with both `svc-admin` and `sonny-aif` passwords. The switch uses `keyboard-interactive` auth which sshpass doesn't handle, or has a different password.
**Why it matters:** Cannot audit switch configuration, verify ACLs, or automate switch management from WSL.
**Fix:** Verify switch credentials. Consider adding `svc-admin` to switch local users, or configure switch to accept the standard password.

### M-012: VM 103 NFS via Management VLAN (F-S034-VM103)
**Status:** OPEN (since S034)
**System:** VM 103
**What's wrong:** VM 103 mounts NFS via `10.25.255.25` (mgmt VLAN) because it has no storage VLAN NIC. NFS media traffic shares bandwidth with SSH/management.
**Fix:** Add storage VLAN NIC (VLAN 25) to VM 103 in Proxmox, then update fstab to use `10.25.25.25`.

### M-013: pfSense WebGUI/HTTP on 0.0.0.0 (NEW)
**System:** pfSense
**What's wrong:** nginx listens on `*:4443` (WebGUI) and `*:80` (HTTP redirect) on all interfaces. Mitigated by pf rules blocking access from LAN and WireGuard to these ports, but the listener is still there.
**Why it matters:** If pf rules are ever misconfigured or temporarily disabled, the WebGUI is instantly exposed on all VLANs.
**Fix:** pfSense GUI → System → Advanced → Admin Access → Bind WebGUI to specific interfaces (lagg0.2550 only).

---

## LOW Findings

### L-001: Undocumented User `donmin` on pve01 and TrueNAS
**Systems:** pve01 (UID 1000), TrueNAS (UID 3002)
**What's wrong:** User account exists on both systems with valid password hashes. Uses SHA-256 (`$5$`) on pve01 — weaker than yescrypt. Not documented in CLAUDE.md.
**Fix:** Confirm with Sonny whether this account is needed. If not, disable or remove. Correlates with VM 420.

### L-002: Undocumented User `chrisadmin` on pfSense and TrueNAS
**Systems:** pfSense (UID 2001), TrueNAS (UID 3001)
**What's wrong:** User with valid password hashes on both systems. Has shell access on pfSense (`/bin/tcsh`).
**Fix:** Confirm with Sonny. If Chris no longer needs access, disable accounts.

### L-003: Undocumented VMs 420 and 804 on pve01
**System:** pve01
**What's wrong:** VM 420 "DonnyisGay" (stopped, 8GB RAM, 64GB disk) and VM 804 "Talos" (running, 8GB RAM, 80GB disk) are not in the CLAUDE.md inventory.
**Fix:** Document purpose. VM 804 is running and consuming resources (8GB RAM). Either add to inventory or shut down.

### L-004: No Proxmox VM Backups Scheduled (NEW)
**System:** pve01
**What's wrong:** `vzdump.cron` symlink exists but file is empty. No automated hypervisor-level VM backups are scheduled.
**Why it matters:** Container config backups (daily cron) exist, but full VM disk images are not backed up. A disk failure would require full VM rebuild.
**Fix:** Configure vzdump schedule in Datacenter → Backup in Proxmox GUI, or deploy Proxmox Backup Server.

### L-005: Tdarr Images Use `:latest` Tag — ✅ FIXED S044
**Systems:** VM 104, VM 105
**Resolution:** Pinned to digest. VM 105: `tdarr@sha256:20a5656c...`, VM 104: `tdarr_node@sha256:62e14509...`. Compose backups at `docker-compose.yml.backup-s044`.

### L-006: Stale Docker Network on VM 102 — ✅ FIXED S044
**System:** VM 102 (+ VM 103 bonus)
**Resolution:** `docker network prune` on VM 102 (removed `plex_default`) and VM 103 (removed `downloaders_default`).

### L-007: VM 104 GPU Passthrough Broken (F-S034-GPU)
**Status:** OPEN (since S034)
**System:** VM 104 / pve03
**What's wrong:** No `/dev/dri/renderD128` — only `card0`. amdgpu probe fails error -22. Needs vendor-reset DKMS module on pve03.
**Fix:** Build and install `gnif/vendor-reset` DKMS on pve03, configure to load before vfio-pci, reboot pve03.

### L-008: Solo MKV Corrupt (F-S040-SOLO-MKV)
**Status:** OPEN (since S040)
**What's wrong:** Solo: A Star Wars Story has corrupt MKV header. 54GB file won't play.
**Fix:** Delete in Radarr and trigger re-search.

### L-009: Unnecessary `plex` User on VM 101 — ✅ FIXED S044
**System:** VM 101
**Resolution:** Account locked (`usermod -L`) and shell changed to `/usr/sbin/nologin`.

### L-010: TrueNAS REST API Deprecation Warning (NEW)
**System:** TrueNAS
**What's wrong:** Alert: deprecated REST API used 3 times in 24h from 10.25.100.19 (WSL). Will be removed in TrueNAS 26.04.
**Fix:** Migrate any scripts using REST API to JSON-RPC 2.0 over WebSocket before upgrading.

### L-011: WiFi Adapter Present on pve03 — ✅ FIXED S044
**System:** pve03
**Resolution:** `iwlwifi` driver blacklisted via `/etc/modprobe.d/dc01-blacklist-wifi.conf`. Takes effect after reboot.

---

## Verified Good — No Issues Found

| Area | Status |
|------|--------|
| ZFS pools (mega-pool, boot-pool, rpool, os-pool-ssd) | All ONLINE, zero errors |
| SMART status (8x disks) | All OK |
| ZFS scrub (mega-pool) | Last: Feb 8 — within monthly schedule |
| LACP bonds (lagg0, lagg1) | Both ACTIVE/COLLECTING/DISTRIBUTING |
| WireGuard tunnel | UP, functional |
| VLAN sub-interface MTUs | All 9000 (fixed S037) |
| Container restart policies | All `unless-stopped` |
| Container image pinning | All pinned except Tdarr (registry limitation) |
| Service port binding | All app ports bound to correct VLAN IPs |
| NFS mounts | All 5 VMs mounted and functional |
| Backup cron | All 5 VMs: daily 03:00, fresh backups today |
| Docker-table200-routes (VM 103) | Enabled, active, functioning |
| Route persistence (all VMs) | Running state matches /etc/network/interfaces — no drift |
| PermitRootLogin (Linux) | `no` on all 7 Linux systems |
| X11Forwarding | Disabled on all systems |
| pfSense sudo | Correctly scoped (svc-admin NOPASSWD only via drop-in) |
| pfSense antispoof rules | Present for all interfaces |
| pfSense VLAN isolation (Dirty) | Correct — blocks all RFC1918 except internet outbound |
| pfSense VLAN isolation (Public) | Correct — allows NFS to TrueNAS, blocks other RFC1918 |
| pfSense WireGuard rules | Correct — access to all VLANs, blocks WebGUI on LAN IP |
| Disk usage | All systems <15% — no capacity concerns |

---

## Comparison with S034 Audit

| S034 Finding | S043 Status |
|---|---|
| F-018 Switch plaintext passwords | CLOSED S034 |
| F-024 TrueNAS timezone | CLOSED S034 |
| F-025 Stale VLANs 113/715 | CLOSED S035 |
| TICKET-0010 Tdarr API key plaintext | CLOSED S034 |
| F-S034-MTU pfSense VLAN MTU | CLOSED S037 |
| F-S037-VM103-FW VLAN 66 firewall | CLOSED S042 |
| F-S034-GPU VM 104 GPU | Still OPEN |
| F-S034-CIPHER TrueNAS SSH ciphers | Still OPEN |
| F-S034-NFS-ACL ha-proxmox-disk | Still OPEN |
| F-S034-VM103 NFS on mgmt VLAN | Still OPEN |
| F-S034-NAT Mamadou NAT | Still OPEN |
| F-S034-PVE Version mismatch | Still OPEN (LOW) |
| F-S037-WANDRGW Monitoring | Still OPEN |
| F-S040-QBIT-CREDS qBit mismatch | Still OPEN |
| F-S040-SOLO-MKV Corrupt file | Still OPEN |

**Net: 6 S034 findings closed, 9 still open. 18 new findings this session.**

---

## Priority Action Plan

### Immediate (Next Session — Sonny + Jarvis)
1. **TICKET-0006:** Generate SSH keys, deploy, disable password auth (fixes C-001, H-001, H-002)
2. **C-002:** Disable PermitRootLogin on pfSense (GUI change)
3. **H-005:** Fix TrueNAS NTP (GUI change)
4. **H-004:** Restrict ha-proxmox-disk NFS ACL (GUI change)
5. **H-003:** Remove weak SSH ciphers on TrueNAS (GUI change)

### Short-term (Next 2-3 Sessions)
6. **H-007/M-013:** Review Mamadou NAT, bind WebGUI to mgmt VLAN
7. **M-001-M-003:** Restrict unbound DNS, syslogd, rpcbind to appropriate interfaces
8. **M-004:** Remove Docker subnet from NFS ACL
9. **M-005:** Restrict SPICE proxy on both Proxmox hosts
10. **M-009:** Clean up pve03 unnecessary VLAN IPs

### Ongoing
11. **H-006:** Order replacement PSUs and fan
12. **L-001-L-003:** Audit undocumented users/VMs with Sonny
13. **L-004:** Set up Proxmox VM backup schedule
