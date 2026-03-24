---
title: "S078 Continuation — Buildout Tasks + FREQ Idea Checker Handoff"
created: 2026-03-11
session: S078 (continuation)
status: READY FOR EXECUTION
physical_access: MUST CONFIRM at session start for Tasks 2-3
warning: "Read this entire document before executing. 4 buildout tasks + new FREQ workflow."
---

# S078 Continuation — Handoff Report

## WHAT HAPPENED THIS CONTEXT WINDOW

### Firewall Sweep (Previous Context)
Completed a full 9-interface pfSense firewall rule audit. 42→35 rules. 5 dead rules deleted, 1 hardened (W6: any→ICMP-only), 1 renamed (M3). Zero downtime. All changes verified live.

### This Context Window (Feature Design + Process)
1. **Wrote `freq pf sweep` feature design report** (1,046 lines) — turns the manual sweep we just did into a reusable FREQ command. Includes ready-to-use PHP scripts, TUI mockups, analysis engine design, safety patterns, and implementation phases.
2. **Created the "FREQ Idea Checker" process** — added to CLAUDE.md §4. Mandatory on every wrap-up: check manual work against FREQ's current features, write a feature design report if a gap exists.
3. **Updated CLAUDE.md** — Idea Checker always asks Sonny for current FREQ source location before looking. No assuming stale paths.

### Session Documentation Status
**⚠️ NOT YET DONE — carry into next context:**
- DC01.md Change Log entry for S078 (sweep results + feature design)
- TASKBOARD.md updates (sweep tasks closed, buildout tasks open)
- Lessons learned from S078 (if any new ones)

---

## FILES CREATED/MODIFIED THIS SESSION

| File | Location (SMB) | Location (Local) | Lines | What |
|---|---|---|---|---|
| Feature design | `/mnt/smb-sonny/public/DB_01/the future of freq/freq-pf-sweep-feature-design.md` | `~/JARVIS_LOCAL/the future of freq/freq-pf-sweep-feature-design.md` | 1,046 | `freq pf sweep` feature — full design with PHP, TUI, safety |
| Buildout handoff | `/mnt/smb-sonny/public/DB_01/pfsense-post-sweep-buildout-handoff-3-11-26.md` | `~/JARVIS_LOCAL/pfsense-post-sweep-buildout-handoff-3-11-26.md` | 530 | 4 buildout tasks with PHP templates, per-host commands |
| Sweep handoff | `/mnt/smb-sonny/public/DB_01/pfsense-firewall-sweep-handoff-3-11-26.md` | `~/JARVIS_LOCAL/pfsense-firewall-sweep-handoff-3-11-26.md` | 719 | Original sweep execution guide (COMPLETED) |
| CLAUDE.md | `/mnt/smb-sonny/sonny/JARVIS_PROD/CLAUDE.md` | `~/JARVIS_LOCAL/CLAUDE.md` | ~510 | Added Idea Checker §4, updated FREQ source step |
| This handoff | `/mnt/smb-sonny/public/DB_01/pfsense-buildout-and-freq-ideas-handoff-3-11-26.md` | `~/JARVIS_LOCAL/pfsense-buildout-and-freq-ideas-handoff-3-11-26.md` | — | You're reading it |

---

## ACCESS REFERENCE

### pfSense (FreeBSD/tcsh)
```bash
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 svc-admin@10.25.255.1
```
- sudo at `/usr/local/bin/sudo`
- PHP config method: `echo '<b64>' | sudo /usr/bin/b64decode -r | sudo /usr/local/bin/php -f /dev/stdin`
- Backup: `sudo cp /cf/conf/config.xml /cf/conf/config.xml.bak-<name>`

### All Hosts
```bash
sshpass -p 'changeme1234' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 svc-admin@<mgmt-ip>
```
Fleet password: `changeme1234` — ALL hosts, root + svc-admin.

### Kill-Chain
```
WSL (10.25.100.19) → WireGuard → pfSense (69.65.20.58:51820)
  → decapsulate → mgmt VLAN (10.25.255.0/24) → target
```
Break any hop = total lockout. Physical datacenter access required.

### Key IPs
| System | Mgmt IP | Notes |
|---|---|---|
| pfSense | 10.25.255.1 | FreeBSD — use b64decode pattern |
| TrueNAS | 10.25.255.25 | |
| pve01 | 10.25.255.26 | Hosts VM 666, 100-104, 811 |
| pve02 | 10.25.255.27 | Hosts VM 201, 202, 400 |
| pve03 | 10.25.255.28 | Hosts VM 301 (GPU) |
| VM 101 (Plex) | 10.25.255.30 | Public: 10.25.5.30 |
| VM 102 (Arr) | 10.25.255.31 | Public: 10.25.5.31 |
| VM 103 (qBit) | 10.25.255.32 | Dirty: 10.25.66.25 |
| VM 104 (Tdarr) | 10.25.255.33 | Public: 10.25.5.33 |
| VM 201 (SABnzbd) | 10.25.255.150 | Dirty: 10.25.66.150 |
| VM 202 (qBit2) | 10.25.255.35 | Dirty: 10.25.66.35 |
| VM 301 (Tdarr-Node) | 10.25.255.34 | Public: 10.25.5.34 |
| VM 666 (Jarvis-AI) | 10.25.255.3 | NEVER migrate |
| VM 811 (PDM) | 10.25.255.40 | |

---

## REMAINING TASKS — EXECUTION ORDER

### Task 1: Fix Asymmetric Routing (WG → Non-Management IPs)
**Risk:** Low per host | **pfSense needed:** No | **Physical access:** No

**Problem:** VPN clients (10.25.100.x) can reach management IPs but NOT LAN/Public IPs. Replies get forced out the management interface by a static route, antispoof drops them because the source IP doesn't match the arrival interface.

**Fix:** Replace global static route `10.25.100.0/24 via 10.25.255.1` with source-based policy routing on 10 hosts. Each host's management-addressed replies go via management gateway, and all other replies use the default route (which naturally exits on the correct interface).

**Full per-host commands, NIC names, file paths, and verification steps are in:**
`/mnt/smb-sonny/public/DB_01/pfsense-post-sweep-buildout-handoff-3-11-26.md` → TASK 1

**Quick reference — 3 host groups:**

| Group | Hosts | Route file | Key detail |
|---|---|---|---|
| A: PVE nodes | pve01 (.26), pve02 (.27), pve03 (.28) | `/etc/network/interfaces.d/vlan2550-mgmt.conf` | Mgmt NIC: `vmbr0v2550` |
| B: Standard VMs | VM 101 (.30), 102 (.31), 104 (.33), 301 (.34) | `/etc/network/interfaces` | Mgmt NIC: `ens18`, default GW: 10.25.5.1 via ens19 |
| C: Dirty VMs | VM 103 (.32), 202 (.35), 201 (.150) | `/etc/network/interfaces` | Already have table 200 policy routing for dirty replies. Just replace the global static route. Mgmt NIC: `ens19` |

**Execution order:** Start with VM 104 (tdarr) as guinea pig → verify → roll to remaining hosts.

**Verification per host:**
```bash
# From WSL — non-mgmt IP (should NOW work after fix)
ping -c1 10.25.5.33       # tdarr public IP
# From WSL — mgmt IP (must STILL work)
ssh svc-admin@10.25.255.33 "echo OK"
```

---

### Task 2: VLAN 10 GigeNet Employee Buildout
**Risk:** Medium | **pfSense needed:** Yes | **Physical access:** REQUIRED

**Purpose:** Repurpose VLAN 10 (Compute, lagg0.10, 10.25.10.0/24) as a GigeNet employee VLAN. Flat, simple, internet access, intra-VLAN comms. Gold standard isolation (modeled on Dirty VLAN).

**Steps:**
1. Delete C2 (tracker 1771465746) — old "Allow all Local connections"
2. Keep C1 (tracker 1772154665) — "Block TCP to pfSense self"
3. Add 9 new rules: block each internal VLAN + RFC1918 catch-all + allow internet outbound
4. After VLAN 10 is live: set up Mamadou WireGuard peer, then delete Mamadou NAT (filter rule tracker 1770744529 + NAT port-forward "Mamadou Server")

**Ready-to-run PHP template and full rule table in:**
`/mnt/smb-sonny/public/DB_01/pfsense-post-sweep-buildout-handoff-3-11-26.md` → TASK 2

---

### Task 3: LAN SSH/WebUI Lockdown
**Risk:** Medium | **pfSense needed:** Yes | **Physical access:** REQUIRED

**Purpose:** Block SSH (22) and WebUI (80, 443, 4443, 8006) from LAN to internal VLANs. LAN keeps SSH/WebUI access to pfSense only (via anti-lockout rule). Insert 4 block rules between L1 (block TCP self) and L2 (allow any to any).

**Design alongside Task 2, same session. Proposed rules in:**
`/mnt/smb-sonny/public/DB_01/pfsense-post-sweep-buildout-handoff-3-11-26.md` → TASK 3

---

### Task 4: DR Emergency WireGuard Config
**Risk:** Zero | **pfSense needed:** No | **Physical access:** No

**Purpose:** Create `dc01-emergency.conf` pointing to 100.101.14.3:51820 (DR WAN via igc0). If primary WAN dies, Sonny switches to this profile. No pfSense changes needed — DR rules already in place (trackers 1772079949, 1772437481).

**Steps:**
1. Copy existing WireGuard client `.conf`
2. Change only: `Endpoint = 69.65.20.58:51820` → `Endpoint = 100.101.14.3:51820`
3. Save as `dc01-emergency.conf`
4. Install on phone + laptop as separate WG profile
5. Test: disable primary, enable emergency, verify connectivity

**Full details in:**
`/mnt/smb-sonny/public/DB_01/pfsense-post-sweep-buildout-handoff-3-11-26.md` → TASK 4

---

### Task 5: S078 Session Documentation (DEFERRED FROM THIS WINDOW)
**Risk:** Zero | **pfSense needed:** No | **Physical access:** No

**What needs to happen:**
1. **DC01.md Change Log** — Add S078 entry covering:
   - Firewall sweep: 42→35 rules, 5 deleted, 1 hardened, 1 renamed
   - `freq pf sweep` feature design written (1,046 lines)
   - FREQ Idea Checker process added to CLAUDE.md
2. **TASKBOARD.md** — Update sweep tasks to completed, add buildout tasks (1-4) as open
3. **Lessons learned** — Any new lessons from S078 (if applicable)
4. **TICKET-0006** — Announce status (42+ sessions open, fleet password `changeme1234`)

---

## NEW PROCESS: FREQ IDEA CHECKER

**Added to CLAUDE.md §4 this session. The rule is:**

On every wrap-up or handoff:
1. Inventory manual tasks completed in the context window
2. **Ask Sonny where the current FREQ source is** (do NOT assume — version/path changes between sessions)
3. Check each manual task against FREQ's current commands
4. If no existing command covers it → write a feature design report to `/mnt/smb-sonny/public/DB_01/the future of freq/freq-<module>-<feature>-feature-design.md`
5. Reports must include only pure facts observed in the context window — explicit IPs, creds, permissions, file paths. No assumptions. No placeholders.
6. Note the feature report in the handoff so the next context window knows it exists

**Feature reports written so far:**
| File | Lines | What |
|---|---|---|
| `freq-pf-sweep-feature-design.md` | 1,046 | Interactive firewall rule audit/sweep command |

---

## CURRENT FIREWALL STATE (35 Rules Post-Sweep)

```
[0]  WireGuard  | pass  | any  | WG subnet → LAN                  | WG to LAN
[1]  WireGuard  | pass  | any  | WG subnet → Management            | WG to MGMT
[2]  WireGuard  | pass  | any  | WG subnet → Public                | WG to PUBLIC
[3]  WireGuard  | pass  | any  | WG subnet → Compute               | WG to Compute
[4]  WireGuard  | pass  | any  | WG subnet → Storage               | WG to STORAGE
[5]  WireGuard  | pass  | icmp | WG subnet → Dirty                 | WG to DIRTY (ICMP only)
[6]  WAN        | pass  | udp  | any → 69.65.20.58:51820            | WireGuard VPN Access
[7]  WAN        | pass  | tcp  | any → 10.25.0.9:8006               | NAT Mamadou (DELETE after Task 2)
[8]  WAN        | pass  | tcp  | any → 10.25.5.30:32400             | NAT Plex
[9]  LAN        | block | tcp  | LAN net → (self)                   | Block TCP to pfSense self
[10] LAN        | pass  | any  | LAN net → any                      | Allow LAN to any (Task 3 inserts before this)
[11] LAN        | pass  | any  | LAN net → any                      | Allow LAN IPv6 to any
[12] Mgmt       | pass  | tcp  | MGMT net → (self)                  | Allow MGMT to pfSense
[13] Mgmt       | pass  | icmp | MGMT net → (self)                  | Allow ICMP to pfSense
[14] Mgmt       | block | any  | any → MGMT net                     | Block inbound to Management
[15] Storage    | block | tcp  | Storage net → (self)                | Block TCP to pfSense self
[16] Compute    | block | tcp  | Compute net → (self)                | Block TCP to pfSense self
[17] Compute    | pass  | any  | Compute net → Compute IP            | Allow local (DELETE in Task 2)
[18] Public     | block | tcp  | Public net → (self)                 | Block TCP to pfSense self
[19] Public     | block | any  | any → 10.0.0.0/8                    | Block RFC1918 10/8
[20] Public     | block | any  | any → 172.16.0.0/12                 | Block RFC1918 172.16/12
[21] Public     | block | any  | any → 192.168.0.0/16                | Block RFC1918 192.168/16
[22] Public     | pass  | any  | Public net → any                    | Allow internet outbound
[23] Dirty      | block | tcp  | Dirty net → (self)                  | Block TCP to pfSense self
[24] Dirty      | block | any  | any → 10.25.0.0/24                  | Block LAN
[25] Dirty      | block | any  | any → 10.25.5.0/24                  | Block Public
[26] Dirty      | block | any  | any → 10.25.10.0/24                 | Block Compute
[27] Dirty      | block | any  | any → 10.25.25.0/24                 | Block Storage
[28] Dirty      | block | any  | any → 10.25.255.0/24                | Block Management
[29] Dirty      | block | any  | any → 10.0.0.0/8                    | Block RFC1918 10/8 catch-all
[30] Dirty      | block | any  | any → 172.16.0.0/12                 | Block RFC1918 172.16/12
[31] Dirty      | block | any  | any → 192.168.0.0/16                | Block RFC1918 192.168/16
[32] Dirty      | pass  | any  | Dirty net → any                     | Allow internet outbound
[33] WANDR      | pass  | udp  | any → 100.101.14.3:51820            | DR WireGuard ingress
[34] WANDR      | pass  | udp  | any → 69.65.20.57:51820             | DR WireGuard VIP ingress
```

### Config Backups on pfSense
```
/cf/conf/config.xml.backup-s078-icmp-allow
/cf/conf/config.xml.bak-sweep-wireguard
/cf/conf/config.xml.bak-sweep-management
/cf/conf/config.xml.bak-sweep-storage
/cf/conf/config.xml.bak-sweep-public
/cf/conf/config.xml.bak-sweep-dirty
```

---

## RECOMMENDED NEXT STEPS

1. **Read this handoff** + the detailed buildout handoff (`pfsense-post-sweep-buildout-handoff-3-11-26.md`)
2. **Task 5 first** (session docs) — quick, zero risk, gets S078 properly closed in DC01.md
3. **Task 1 next** (asymmetric routing) — no pfSense needed, can do from anywhere, start with VM 104
4. **Tasks 2+3 together** (VLAN 10 + LAN lockdown) — need pfSense writes, need physical access confirmed
5. **Task 4 anytime** (DR WG config) — client-side only, zero risk

---

*Generated by Jarvis — S078 continuation. Firewall sweep done, feature design written, Idea Checker process established. 5 tasks remain for next context window.*
