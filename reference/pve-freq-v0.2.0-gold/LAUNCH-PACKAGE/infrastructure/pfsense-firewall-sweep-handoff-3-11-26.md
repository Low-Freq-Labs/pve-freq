---
title: "pfSense Firewall Rule Sweep — Handoff Report"
created: 2026-03-11
session: S078
status: IN PROGRESS — Start with Interface 1 (WireGuard)
physical_access: CONFIRMED — Sonny is at the datacenter
warning: "CRITICAL NETWORK CHANGE — One interface at a time, verify, then proceed"
---

# pfSense Firewall Rule Sweep — Handoff Report

## MISSION BRIEF

Sonny has requested a full firewall rule audit and prune on pfSense (10.25.255.1). Every rule on every interface must be reviewed, discussed with Sonny, and pruned or kept. This was analyzed in S078 and the full audit is documented below.

**Execution protocol (Sonny-approved):**
1. Work ONE interface at a time, in the order listed below
2. Present the rules on that interface to Sonny — explain each one, what it does, whether it's needed
3. Sonny decides: KEEP, DELETE, or MODIFY for each rule
4. Before ANY change: `sudo cp /cf/conf/config.xml /cf/conf/config.xml.bak-sweep-<interface>`
5. Make the changes
6. Verify connectivity is intact (ping, SSH, service checks as appropriate)
7. Sonny confirms good — THEN move to the next interface
8. If anything breaks: `sudo cp /cf/conf/config.xml.bak-sweep-<interface> /cf/conf/config.xml && sudo /etc/rc.filter_configure`

**DO NOT batch multiple interfaces. DO NOT assume Sonny's answers. Ask for every rule.**

---

## PHYSICAL ACCESS

**Sonny confirmed he is at the datacenter.** pfSense writes are AUTHORIZED.

If Sonny says he has left the datacenter at any point, STOP all pfSense writes immediately per CLAUDE.md §3.

---

## PFSENSE ACCESS

```bash
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 svc-admin@10.25.255.1
```

- **OS:** FreeBSD (pfSense) — uses tcsh, NOT bash
- **No heredocs, no `$()`** — use base64-encoded `/bin/sh` scripts or PHP via `b64decode`
- **sudo** is at `/usr/local/bin/sudo`
- **PHP config method** (proven working this session):
  ```
  echo '<base64-php-script>' | sudo /usr/bin/b64decode -r | sudo /usr/local/bin/php -f /dev/stdin
  ```
- **Backup command:** `sudo cp /cf/conf/config.xml /cf/conf/config.xml.bak-sweep-<name>`
- **Rollback command:** `sudo cp /cf/conf/config.xml.bak-sweep-<name> /cf/conf/config.xml && sudo /etc/rc.filter_configure`
- **Config change commit message pattern:** `write_config("S078 sweep: <description>")`

---

## EXISTING BACKUP

A pre-sweep backup already exists from the ICMP change earlier this session:
```
/cf/conf/config.xml.backup-s078-icmp-allow   (71400 bytes, 2026-03-11 17:08)
```

**Take a NEW backup before each interface change.** Name pattern: `config.xml.bak-sweep-<interface>`

---

## NETWORK TOPOLOGY REFERENCE

### Interfaces

| pfSense Interface | Real Interface | VLAN | Subnet | Gateway IP | Role |
|---|---|---|---|---|---|
| WAN (lagg1) | lagg1 | — | 100.101.14.0/28 + 69.65.20.56/29 | 100.101.14.1 | Internet uplink (LACP) |
| LAN (lagg0) | lagg0 | 1 (native) | 10.25.0.0/24 | 10.25.0.1 | Servers & legacy |
| WireGuard (tun_wg0) | tun_wg0 | — | 10.25.100.0/24 | 10.25.100.1 | VPN clients |
| opt2 / Management | lagg0.2550 | 2550 | 10.25.255.0/24 | 10.25.255.1 | OOB management |
| opt3 / Storage | lagg0.25 | 25 | 10.25.25.0/24 | 10.25.25.1 | NFS/SMB |
| opt4 / Compute | lagg0.10 | 10 | 10.25.10.0/24 | 10.25.10.1 | **EMPTY — no devices** |
| opt5 / Public | lagg0.5 | 5 | 10.25.5.0/24 | 10.25.5.1 | Plex, Arr services |
| opt6 / Dirty | lagg0.66 | 66 | 10.25.66.0/24 | 10.25.66.1 | qBit/SABnzbd — NAT via 69.65.20.61 |
| opt7 / WANDR | igc0 | — | 100.101.14.3 + 69.65.20.57 | 100.101.14.1 | DR WAN (BGP pending) |

### WireGuard Peers

| IP | Name |
|---|---|
| 10.25.100.10 | Sonny - MacBook |
| 10.25.100.11 | Chris - Laptop |
| 10.25.100.12 | Sonny - Desktop |
| 10.25.100.13 | Chris - Desktop |
| 10.25.100.14 | Sonny - Work |
| 10.25.100.15 | Chris - Work |
| 10.25.100.16 | Donny - Computer01 |
| 10.25.100.17 | Jonny - Phone |
| 10.25.100.18 | Sonny - Phone |
| 10.25.100.19 | Sonny - WSL home |
| 10.25.100.20 | Sonny - WSL Work |
| 10.25.100.21 | Janie - VPN phone |

### Kill-Chain (MEMORIZE — break this and we lose all remote access)
```
WSL (10.25.100.19) -> WireGuard -> pfSense (69.65.20.58:51820)
  -> decapsulate -> route to management VLAN (10.25.255.0/24) -> target
```

### NAT Rules (for reference — may also need review)

| Type | Source | Interface | Translates To | Description |
|---|---|---|---|---|
| Outbound | 10.25.66.0/24 | lagg1 (WAN) | 69.65.20.61 | Dirty VLAN dedicated exit IP |
| Outbound | any | lagg1 (WAN) | 69.65.20.58 | Main outbound NAT |
| Outbound | opt1 (WG) net | lagg1 (WAN) | 100.101.14.2 | VPN clients outbound |
| Outbound | tonatsubnets | lagg1 (WAN) | 100.101.14.2 | Catch-all outbound |
| Outbound | tonatsubnets | igc0 (WANDR) | 100.101.14.3 | DR outbound (pending BGP) |
| Port Forward | any -> 69.65.20.58:50000 | lagg1 (WAN) | 10.25.5.30:32400 | Plex remote access |
| Port Forward | any -> 69.65.20.62:8006 | lagg1 (WAN) | 10.25.0.9:8006 | Mamadou Server (QUESTIONABLE) |

---

## SWEEP ORDER & FULL RULE DETAILS

Work these interfaces in this exact order. Each section contains EVERY rule on that interface with full analysis.

---

### INTERFACE 1: WireGuard (tun_wg0) — 6 rules

**What this interface does:** Handles all VPN client traffic. Every remote connection from Sonny, Chris, Donny, etc. enters here. This is KILL-CHAIN CRITICAL.

**Rule evaluation order (top to bottom, all use `quick`):**

#### Rule W1: "WG to LAN"
- **Tracker:** 1770307004
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** 10.25.100.0/24 (all VPN clients)
- **Destination:** LAN network (10.25.0.0/24)
- **Created by:** sonny.aif@69.65.5.30
- **S078 Analysis:** Allows VPN users to reach LAN subnet. This is where PVE nodes live on their OS IPs (10.25.0.26/27/28), TrueNAS OS IP (10.25.0.25), and a few VMs. Required for Proxmox WebUI access if using LAN IPs. Also needed for Vaultwarden (10.25.0.75).
- **Pre-audit verdict:** KEEP — but ask Sonny if VPN users actually use LAN IPs or only mgmt IPs.

#### Rule W2: "WG to MANAGEMENT"
- **Tracker:** 1771264002
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** 10.25.100.0/24
- **Destination:** opt2 network (10.25.255.0/24)
- **S078 Analysis:** This is THE critical rule. All SSH management from WSL goes through here. Deleting this = total lockout.
- **Pre-audit verdict:** ABSOLUTELY KEEP. Do not touch.

#### Rule W3: "WG to PUBLIC"
- **Tracker:** 1771469610
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** 10.25.100.0/24
- **Destination:** opt5 network (10.25.5.0/24)
- **S078 Analysis:** Needed for accessing Plex WebUI, Sonarr/Radarr/Prowlarr WebUIs, and other services on their public VLAN IPs from VPN.
- **Pre-audit verdict:** KEEP.

#### Rule W4: "WG to Compute"
- **Tracker:** 1771469645
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** 10.25.100.0/24
- **Destination:** opt4 network (10.25.10.0/24)
- **S078 Analysis:** VLAN 10 (Compute) is documented as EMPTY. No VMs, no devices, no plans documented. This rule allows VPN access to a subnet with nothing on it.
- **Pre-audit verdict:** PRUNE CANDIDATE. Ask Sonny.

#### Rule W5: "WG to STORAGE"
- **Tracker:** 1771469853
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** 10.25.100.0/24
- **Destination:** opt3 network (10.25.25.0/24)
- **S078 Analysis:** WSL's SMB mount uses 10.25.25.25 (TrueNAS storage IP). Also needed for NFS troubleshooting. The SMB mount in fstab literally goes `//10.25.25.25/smb-share`.
- **Pre-audit verdict:** KEEP — WSL SMB mount depends on this.

#### Rule W6: "WG to DIRTY"
- **Tracker:** 1771524288
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** 10.25.100.0/24
- **Destination:** opt6 network (10.25.66.0/24)
- **S078 Analysis:** Dirty VLAN hosts qBit (10.25.66.25) and SABnzbd (10.25.66.150). However, both are managed via their MGMT IPs (10.25.255.32 and 10.25.255.150). The only reason to access dirty IPs would be SABnzbd WebUI on 10.25.66.150:8080 — but SABnzbd was rebound to 10.25.255.150 in S066.
- **Pre-audit verdict:** PRUNE CANDIDATE. Ask Sonny if he ever accesses dirty IPs directly.

#### Verification after WireGuard changes:
```bash
# From WSL — test each allowed VLAN
ping -c1 10.25.255.1    # Management (must work)
ping -c1 10.25.0.26     # LAN (must work if kept)
ping -c1 10.25.25.25    # Storage (must work)
ping -c1 10.25.5.30     # Public (must work)
ping -c1 10.25.66.25    # Dirty (only if kept)
ping -c1 10.25.10.1     # Compute (only if kept)

# SSH to a VM
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.26 "echo OK"
```

---

### INTERFACE 2: WAN (lagg1) — 3 rules

**What this interface does:** Internet-facing. Everything from the outside world hits this. Rules here determine what external traffic is allowed IN.

#### Rule WAN1: "Allow WireGuard VPN Access"
- **Tracker:** 1770305549
- **Action:** PASS (logged, reply-to lagg1)
- **Protocol:** UDP
- **Source:** any
- **Destination:** 69.65.20.58:51820
- **S078 Analysis:** This is the WireGuard listener. Without this, NO VPN connections work. Kill-chain critical.
- **Pre-audit verdict:** ABSOLUTELY KEEP. Do not touch.

#### Rule WAN2: "NAT Mamadou Server"
- **Tracker:** 1770744529
- **Action:** PASS (reply-to lagg1)
- **Protocol:** TCP
- **Source:** any
- **Destination:** 10.25.0.9:8006
- **Matching NAT RDR:** 69.65.20.62:8006 -> 10.25.0.9:8006
- **S078 Analysis:** Exposes Proxmox WebUI (port 8006) on IP 10.25.0.9 to the ENTIRE INTERNET via public IP 69.65.20.62. This is H-007 in the taskboard — "Mamadou NAT (Sonny decision)." IP 10.25.0.9 is NOT in the current VM inventory. This appears to be a friend's server or a decommissioned device.
- **Pre-audit verdict:** PRUNE CANDIDATE — significant security exposure. Ask Sonny. If Mamadou's device is gone, delete both the filter rule AND the NAT port forward.

#### Rule WAN3: "NAT Plex Outside Access"
- **Tracker:** 1770973773
- **Action:** PASS (reply-to lagg1)
- **Protocol:** TCP
- **Source:** any
- **Destination:** 10.25.5.30:32400
- **Matching NAT RDR:** 69.65.20.58:50000 -> 10.25.5.30:32400
- **S078 Analysis:** Plex remote streaming. Port 50000 on public IP forwards to Plex. Required for external Plex access. Custom connection URL `https://69.65.20.58:50000` is configured in Plex Preferences.xml.
- **Pre-audit verdict:** KEEP.

#### Verification after WAN changes:
```bash
# From WSL — verify VPN still works (if you touch anything here, test IMMEDIATELY)
ping -c1 10.25.255.1

# Plex remote access (from outside or check Plex dashboard for remote access status)
curl -s 'http://10.25.255.30:32400/identity?X-Plex-Token=wzyxB7DKi3siGMwXMFKu'
```

---

### INTERFACE 3: LAN (lagg0) — 3 rules

**What this interface does:** The untagged/native VLAN. PVE nodes, TrueNAS, switch, and some VMs have their OS IPs here. Has an auto-generated anti-lockout rule that processes BEFORE user rules.

**System rule (processes first):**
- Anti-lockout: PASS TCP from any to lagg0 self on ports 4443, 80, 22. This cannot be removed from rules — it's a pfSense safety feature.

#### Rule L1: "Block TCP to pfSense self on LAN"
- **Tracker:** 1772154294
- **Action:** BLOCK
- **Protocol:** TCP
- **Source:** LAN network (10.25.0.0/24)
- **Destination:** (self) — pfSense's own IPs
- **S078 Analysis:** Intent is to prevent LAN devices from reaching pfSense admin ports. BUT the anti-lockout rule fires FIRST and already passes TCP ports 4443/80/22. So this rule only blocks TCP to pfSense on non-admin ports (e.g., random TCP to pfSense on port 53 DNS, etc.). Partially effective.
- **Pre-audit verdict:** Ask Sonny if the intent is clear. May want to keep for defense-in-depth.

#### Rule L2: "Default allow LAN to any rule"
- **Tracker:** 0100000101
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** LAN network
- **Destination:** any
- **S078 Analysis:** Standard pfSense default. LAN is trusted, can reach everything. This is how PVE nodes, TrueNAS, etc. reach the internet and other VLANs.
- **Pre-audit verdict:** KEEP — removing this would break outbound from every LAN device.

#### Rule L3: "Default allow LAN IPv6 to any rule"
- **Tracker:** 0100000102
- **Action:** PASS
- **Protocol:** any (inet6)
- **Source:** LAN network
- **Destination:** any
- **S078 Analysis:** IPv6 equivalent. DC01 does not use IPv6 anywhere. No IPv6 addresses assigned. This is the pfSense default that was never removed.
- **Pre-audit verdict:** PRUNE CANDIDATE — does nothing, but harmless. Ask Sonny.

#### Verification after LAN changes:
```bash
# From WSL via VPN
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.26 "ping -c1 8.8.8.8"  # PVE node outbound
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.25 "ping -c1 8.8.8.8"  # TrueNAS outbound
```

---

### INTERFACE 4: Management (lagg0.2550 / opt2) — 5 rules

**What this interface does:** OOB management for all hosts. Every SSH session from WSL goes to a .255.x address on this VLAN. This is WHERE YOU LIVE.

#### Rule M1: "Allow MGMT to pfSense"
- **Tracker:** 1772118264
- **Action:** PASS
- **Protocol:** TCP
- **Source:** opt2 network (10.25.255.0/24)
- **Destination:** (self)
- **S078 Analysis:** Allows management devices to reach pfSense WebGUI (4443) and SSH (22) via TCP. Essential for managing pfSense from management VLAN.
- **Pre-audit verdict:** KEEP.

#### Rule M2: "Allow ICMP echo from Management to pfSense (S078)"
- **Tracker:** 1773266986
- **Action:** PASS
- **Protocol:** ICMP echo-request
- **Source:** opt2 network
- **Destination:** (self)
- **S078 Analysis:** Just added this session. Allows ping from management to pfSense.
- **Pre-audit verdict:** KEEP — we literally just added this.

#### Rule M3: "Block all outbound" (MISLEADING NAME)
- **Tracker:** 1771466256
- **Action:** BLOCK (quick)
- **Protocol:** any (inet)
- **Source:** any
- **Destination:** opt2 network
- **S078 Analysis:** Despite its name, this blocks inbound traffic TO management devices. It prevents anything coming through pfSense from reaching the management VLAN. Since rules M1 and M2 already pass management-to-pfSense traffic, this blocks everything else — like traffic from OTHER VLANs trying to reach management devices.
- **CRITICAL ISSUE:** This rule uses `quick` and is positioned BEFORE rules M4 and M5. Because pf evaluates `quick` rules in order, rules M4 and M5 NEVER FIRE — they are dead rules.
- **Pre-audit verdict:** KEEP (it provides management VLAN isolation) but RENAME to something accurate like "Block inbound to Management subnet." Also discuss the dead rules below.

#### Rule M4: "Passed via EasyRule" (DEAD)
- **Tracker:** 1773117359
- **Action:** PASS
- **Protocol:** ICMP echo-request
- **Source:** 10.25.255.180 (lab pfSense VM 980)
- **Destination:** any
- **S078 Analysis:** This rule is AFTER the block-quick in M3. It NEVER fires. 10.25.255.180 is the lab pfSense. Even if this rule were reachable, it only allows ICMP from the lab box.
- **Pre-audit verdict:** DELETE — dead rule. If lab pfSense ICMP is needed, it must go ABOVE M3.

#### Rule M5: "Lab pfSense (VM 980) outbound access" (DEAD)
- **Tracker:** 1773200100
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** 10.25.255.180 (lab pfSense VM 980)
- **Destination:** any
- **S078 Analysis:** Same problem — AFTER the block-quick in M3. NEVER fires. Lab pfSense cannot reach the internet through this rule.
- **Pre-audit verdict:** DELETE — dead rule. If VM 980 needs internet, rule must go ABOVE M3. But VM 980 is a lab pfSense that may not need internet at all. Ask Sonny.

#### Verification after Management changes:
```bash
# CRITICAL — test from WSL immediately after any change
ping -c1 10.25.255.1
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.1 "echo OK"
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.26 "echo OK"
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.30 "echo OK"
```

---

### INTERFACE 5: Storage (lagg0.25 / opt3) — 2 rules

**What this interface does:** Dedicated storage traffic — NFS between VMs and TrueNAS, SMB from WSL. All VMs have a dedicated ens20 NIC on this VLAN.

#### Rule S1: "Block TCP to pfSense self on STORAGE"
- **Tracker:** 1772154110
- **Action:** BLOCK
- **Protocol:** TCP
- **Source:** opt3 network (10.25.25.0/24)
- **Destination:** (self)
- **S078 Analysis:** Prevents storage devices from reaching pfSense admin ports via the storage interface. Good hardening — storage NICs shouldn't need pfSense admin access.
- **Pre-audit verdict:** KEEP.

#### Rule S2: "Allow all Local"
- **Tracker:** 1771465863
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** opt3 network
- **Destination:** opt3 network
- **S078 Analysis:** Allows storage VLAN devices to talk to each other through pfSense. But same-subnet traffic stays at L2 (switch handles it) — it never goes through pfSense. This rule would only fire if a device sent storage traffic to the gateway instead of directly to the destination via ARP.
- **Pre-audit verdict:** Likely never fires. PRUNE CANDIDATE but harmless. Ask Sonny.

#### Verification after Storage changes:
```bash
# Test NFS from a VM
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.30 "df -h /mnt/truenas/nfs-mega-share"
# Test SMB from WSL
ls /mnt/smb-sonny/sonny/JARVIS_PROD/CLAUDE.md
```

---

### INTERFACE 6: Compute (lagg0.10 / opt4) — 2 rules

**What this interface does:** NOTHING. VLAN 10 is empty. No VMs, no devices, no documented plans.

#### Rule C1: "Block TCP to pfSense self on COMPUTE"
- **Tracker:** 1772154665
- **Action:** BLOCK
- **Protocol:** TCP
- **Source:** opt4 network (10.25.10.0/24)
- **Destination:** (self)
- **S078 Analysis:** Protects nothing — VLAN is empty.
- **Pre-audit verdict:** PRUNE CANDIDATE. Ask Sonny if Compute VLAN has any future plans.

#### Rule C2: "Allow all Local connections"
- **Tracker:** 1771465746
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** opt4 network
- **Destination:** 10.25.10.1 (pfSense self on compute)
- **S078 Analysis:** Allows compute devices to reach pfSense gateway. Contradicts C1 (TCP blocked, but UDP/ICMP passes). VLAN is empty anyway.
- **Pre-audit verdict:** PRUNE CANDIDATE.

#### Verification: N/A — VLAN is empty. Just verify nothing else broke.

---

### INTERFACE 7: Public (lagg0.5 / opt5) — 7 rules

**What this interface does:** Plex, Sonarr, Radarr, Prowlarr, Tdarr, and other media services. VMs 101, 102, 104, 301 have their service NICs here. Internet access is required.

#### Rule P1: "Block TCP to pfSense self on PUBLIC"
- **Tracker:** 1772154783
- **Action:** BLOCK
- **Protocol:** TCP
- **Source:** opt5 network (10.25.5.0/24)
- **Destination:** (self)
- **S078 Analysis:** Prevents Plex/Arr VMs from reaching pfSense admin. Good hardening.
- **Pre-audit verdict:** KEEP.

#### Rule P2: "NFS to TrueNAS"
- **Tracker:** 1771468267
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** opt5 network
- **Destination:** 10.25.25.25 (TrueNAS storage IP)
- **S078 Analysis:** Cross-VLAN rule allowing Public -> Storage to reach TrueNAS NFS. BUT: all VMs mount NFS via their dedicated ens20 storage NIC (10.25.25.x -> 10.25.25.25). That traffic never touches pfSense — it goes directly over VLAN 25 at L2. This rule would only matter if a VM tried to NFS mount via its public IP, which none do.
- **Pre-audit verdict:** PRUNE CANDIDATE — likely never used. Ask Sonny. Can verify by checking pfctl rule hit counters.

#### Rule P3: "Block RFC1918 10/8"
- **Tracker:** 1771465908
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.0.0.0/8
- **S078 Analysis:** After allowing NFS to TrueNAS (P2), this blocks all other RFC1918. Prevents public VLAN from reaching any internal subnet. Standard isolation pattern.
- **Pre-audit verdict:** KEEP.

#### Rule P4: "Block RFC1918 172.16/12"
- **Tracker:** 1771465961
- **Action:** BLOCK
- **Source:** any
- **Destination:** 172.16.0.0/12
- **Pre-audit verdict:** KEEP.

#### Rule P5: "Block RFC1918 192.168"
- **Tracker:** 1771466002
- **Action:** BLOCK
- **Source:** any
- **Destination:** 192.168.0.0/16
- **Pre-audit verdict:** KEEP.

#### Rule P6: "Allow internet outbound"
- **Tracker:** 1771466024
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** opt5 network
- **Destination:** any
- **S078 Analysis:** After blocking RFC1918, this passes everything else — meaning only internet traffic is allowed. Plex needs this for metadata, streaming. Arr services need this for indexers.
- **Pre-audit verdict:** KEEP.

#### Rule P7: "NAT Plex Outside Access"
- **Tracker:** 1771466352
- **Action:** PASS
- **Protocol:** TCP
- **Source:** any
- **Destination:** 10.25.0.30:32400
- **S078 Analysis:** This allows traffic arriving on the PUBLIC interface destined for 10.25.0.30:32400. But Plex is at 10.25.5.30, NOT 10.25.0.30. The 10.25.0.x address is the OLD LAN IP from before Plex was moved to the Public VLAN. The actual NAT port forward (RDR) correctly targets 10.25.5.30. This filter rule appears to be a leftover that does nothing or catches traffic that shouldn't exist.
- **Pre-audit verdict:** DELETE — stale rule with wrong IP. The NAT RDR already handles Plex forwarding correctly.

#### Verification after Public changes:
```bash
# Plex internet access
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.30 "curl -s -o /dev/null -w '%{http_code}' https://plex.tv"
# Sonarr internet access
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.31 "curl -s -o /dev/null -w '%{http_code}' https://api.themoviedb.org"
# NFS still working
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.30 "df -h /mnt/truenas/nfs-mega-share"
```

---

### INTERFACE 8: Dirty (lagg0.66 / opt6) — 11 rules

**What this interface does:** Isolated download VLAN. qBit (VM 103) and SABnzbd (VM 201) have their service NICs here. Traffic NATs out via dedicated IP 69.65.20.61. Heavily locked down — no access to any other internal subnet.

#### Rule D1: "Block TCP to pfSense self on DIRTY"
- **Tracker:** 1772154826
- **Action:** BLOCK
- **Protocol:** TCP
- **Source:** opt6 network (10.25.66.0/24)
- **Destination:** (self)
- **Pre-audit verdict:** KEEP.

#### Rule D2: "Block LAN"
- **Tracker:** 1771465137
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.25.0.0/24
- **Pre-audit verdict:** KEEP — prevents dirty reaching LAN.

#### Rule D3: "Block Public VLAN"
- **Tracker:** 1771465189
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.25.5.0/24
- **Pre-audit verdict:** KEEP — prevents dirty reaching Plex/Arr.

#### Rule D4: "Block Computer VLAN"
- **Tracker:** 1771465249
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.25.10.0/24
- **S078 Analysis:** Compute is empty. This blocks access to nothing. However, it's defense-in-depth — if something ever goes on Compute VLAN, dirty can't reach it.
- **Pre-audit verdict:** Harmless. Ask Sonny — keep for safety or prune for cleanliness?

#### Rule D5: "Block Storage VLAN"
- **Tracker:** 1771465291
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.25.25.0/24
- **Pre-audit verdict:** KEEP — prevents dirty reaching TrueNAS.

#### Rule D6: "Block own subnet routing"
- **Tracker:** 1771465357
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.25.66.0/24
- **S078 Analysis:** Blocks dirty-to-dirty through pfSense. Same-subnet traffic goes L2 (switch), so this only fires if something routes through the gateway. Could prevent weird reflection attacks.
- **Pre-audit verdict:** Harmless defense-in-depth. Ask Sonny.

#### Rule D7: "Block Management VLAN"
- **Tracker:** 1771465429
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.25.255.0/24
- **Pre-audit verdict:** KEEP — critical. Prevents dirty reaching management.

#### Rule D8: "Block RFC1918 10/8 catch-all"
- **Tracker:** 1771466068
- **Action:** BLOCK
- **Source:** any
- **Destination:** 10.0.0.0/8
- **S078 Analysis:** Redundant with D2-D7 which already block every specific 10.25.x.0/24. This only catches subnets NOT explicitly listed (e.g., if you added 10.25.50.0/24 later). Safety net.
- **Pre-audit verdict:** KEEP — defense-in-depth catch-all.

#### Rule D9: "Block RFC1918 172.16/12"
- **Tracker:** 1771465571
- **Action:** BLOCK
- **Source:** any
- **Destination:** 172.16.0.0/12
- **Pre-audit verdict:** KEEP.

#### Rule D10: "Block RFC1918 192.168/16"
- **Tracker:** 1771465600
- **Action:** BLOCK
- **Source:** any
- **Destination:** 192.168.0.0/16
- **Pre-audit verdict:** KEEP.

#### Rule D11: "Allow internet outbound"
- **Tracker:** 1771465639
- **Action:** PASS
- **Protocol:** any (inet)
- **Source:** opt6 network
- **Destination:** any
- **S078 Analysis:** After all the blocks, only internet traffic remains. qBit/SABnzbd need this.
- **Pre-audit verdict:** KEEP.

#### Verification after Dirty changes:
```bash
# qBit can still reach internet
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.32 "curl -s -o /dev/null -w '%{http_code}' https://google.com"
# SABnzbd can still reach internet
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.150 "curl -s -o /dev/null -w '%{http_code}' https://google.com"
# Dirty CANNOT reach management
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no svc-admin@10.25.255.32 "ping -c1 -W2 10.25.255.1" # Should FAIL
```

---

### INTERFACE 9: WANDR (igc0 / opt7) — 2 rules

**What this interface does:** Disaster Recovery WAN. Second internet connection via igc0. Currently waiting on BGP configuration from Paul (network engineer).

#### Rule DR1: "Allow WireGuard DR ingress"
- **Tracker:** 1772079949
- **Action:** PASS
- **Protocol:** UDP
- **Source:** any
- **Destination:** 100.101.14.3:51820
- **S078 Analysis:** Pre-staged for DR WireGuard. BGP route from Paul not configured yet. Traffic cannot arrive at this IP until BGP is active.
- **Pre-audit verdict:** Harmless but non-functional. Ask Sonny if Paul/BGP is still happening.

#### Rule DR2: "Allow WireGuard DR VIP ingress"
- **Tracker:** 1772437481
- **Action:** PASS (logged)
- **Protocol:** UDP
- **Source:** any
- **Destination:** 69.65.20.57:51820
- **S078 Analysis:** Same situation — pre-staged for DR VIP. Non-functional until BGP.
- **Pre-audit verdict:** Same. Ask Sonny.

#### Verification: N/A unless DR is active.

---

## SUMMARY: PRUNE CANDIDATES BY CONFIDENCE

### HIGH CONFIDENCE DELETE (dead/broken rules)
| Interface | Rule | Tracker | Why |
|---|---|---|---|
| opt2 (Mgmt) | EasyRule ICMP .180 | 1773117359 | Dead — after block quick, never fires |
| opt2 (Mgmt) | Lab pfSense outbound | 1773200100 | Dead — after block quick, never fires |
| opt5 (Public) | NAT Plex 10.25.0.30 | 1771466352 | Stale IP — should be 10.25.5.30, NAT RDR is correct |

### SONNY DECISION REQUIRED
| Interface | Rule | Tracker | Question |
|---|---|---|---|
| WireGuard | WG to Compute | 1771469645 | VLAN 10 empty — any plans? |
| WireGuard | WG to DIRTY | 1771524288 | Do you access dirty IPs directly via VPN? |
| WAN | NAT Mamadou | 1770744529 | Is Mamadou still using this? Internet -> PVE WebUI. |
| LAN | LAN IPv6 to any | 0100000102 | IPv6 not used anywhere. Remove? |
| opt3 (Storage) | Allow all Local | 1771465863 | Same-subnet = L2, rule never fires. Remove? |
| opt4 (Compute) | Both rules | 1772154665 + 1771465746 | VLAN empty. Remove both? |
| opt5 (Public) | NFS to TrueNAS | 1771468267 | NFS uses VLAN 25 directly. Rule ever used? |
| opt6 (Dirty) | Block Compute | 1771465249 | Compute empty — keep for defense-in-depth? |
| opt6 (Dirty) | Block own subnet | 1771465357 | L2 handles this — keep for defense-in-depth? |
| opt7 (WANDR) | Both DR rules | 1772079949 + 1772437481 | BGP with Paul still happening? |

### RENAME (keep but fix misleading name)
| Interface | Rule | Tracker | Current Name | Suggested Name |
|---|---|---|---|---|
| opt2 (Mgmt) | Block all outbound | 1771466256 | "Block all outbound" | "Block inbound to Management subnet" |

---

## HOW TO DELETE A RULE VIA PHP

Use this pattern for each deletion. Replace TRACKER_ID with the rule's tracker number.

```php
<?php
require_once("config.inc");
require_once("filter.inc");
require_once("shaper.inc");

global $config;

$target_tracker = "TRACKER_ID";
$deleted = false;

if (is_array($config['filter']['rule'])) {
    foreach ($config['filter']['rule'] as $idx => $rule) {
        if (isset($rule['tracker']) && $rule['tracker'] == $target_tracker) {
            unset($config['filter']['rule'][$idx]);
            $config['filter']['rule'] = array_values($config['filter']['rule']);
            $deleted = true;
            break;
        }
    }
}

if ($deleted) {
    write_config("S078 sweep: Deleted rule tracker $target_tracker");
    filter_configure();
    echo "SUCCESS: Deleted rule tracker $target_tracker and reloaded filter\n";
} else {
    echo "ERROR: Rule tracker $target_tracker not found\n";
}
?>
```

Base64 encode, ship via:
```bash
echo '<base64>' | sudo /usr/bin/b64decode -r | sudo /usr/local/bin/php -f /dev/stdin
```

---

## HOW TO RENAME A RULE VIA PHP

```php
<?php
require_once("config.inc");
require_once("filter.inc");
require_once("shaper.inc");

global $config;

$target_tracker = "TRACKER_ID";
$new_descr = "NEW DESCRIPTION HERE";
$found = false;

if (is_array($config['filter']['rule'])) {
    foreach ($config['filter']['rule'] as $idx => &$rule) {
        if (isset($rule['tracker']) && $rule['tracker'] == $target_tracker) {
            $rule['descr'] = $new_descr;
            $found = true;
            break;
        }
    }
    unset($rule);
}

if ($found) {
    write_config("S078 sweep: Renamed rule tracker $target_tracker");
    filter_configure();
    echo "SUCCESS: Renamed rule tracker $target_tracker\n";
} else {
    echo "ERROR: Rule tracker $target_tracker not found\n";
}
?>
```

---

*Generated by Jarvis — S078. Physical access confirmed. Sweep execution should begin with Interface 1 (WireGuard).*
