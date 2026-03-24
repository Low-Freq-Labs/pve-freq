# Disaster Recovery Architecture — Netgate 4100 / pfSense

> **Status:** IN PROGRESS — Phases 1-4 COMPLETE, Phase 5 PARTIAL, Phase 6 DEFERRED
> **Session:** S036-20260221
> **Priority:** P1
> **Impact:** WAN + LAN failover architecture, pfSense interface reassignment, switch config changes
> **Risk Level:** HIGH (WAN changes will drop VPN, LAN LACP reform touches production)
> **Last Updated:** S036-20260221 — WAN LAG (lagg1) COMPLETE, WANDR tested as VPN failover, LACP stable

---

## 1. Current State (Verified S036)

### pfSense — Netgate 4100
- **Model:** Netgate 4100, Serial 2020221213
- **OS:** pfSense 26.03-BETA, FreeBSD 16.0-CURRENT
- **CPU:** Intel Atom C3338R @ 1.80GHz (2 cores)
- **Crypto:** QAT active, IPsec-MB active, AES-NI inactive

### Interface Inventory

| Interface | Type | MAC | Link | Speed | Current Role | Switch Port |
|-----------|------|-----|------|-------|-------------|-------------|
| igc0 | 2.5GbE copper | 90:ec:77:2e:0d:6c | **active** | 1000baseT | Unassigned | **NOT on our switch** |
| igc1 | 2.5GbE copper | 90:ec:77:2e:0d:6d | **active** | 1000baseT | Unassigned | **NOT on our switch** |
| igc2 | 2.5GbE copper | 90:ec:77:2e:0d:6e | active | 1000baseT | lagg0 MASTER (LAN) | Gi1/47 (standalone trunk) |
| igc3 | 2.5GbE copper | 90:ec:77:2e:0d:6e | active | 1000baseT | lagg0 backup (LAN) | Gi1/48 (standalone trunk) |
| ix0 | 10GbE SFP+ | ff:ff:ff:ff:ff:ff | **no carrier** | — | Unassigned | Not connected |
| ix1 | 10GbE SFP+ | ff:ff:ff:ff:ff:ff | **no carrier** | — | Unassigned | Not connected |
| ix2 | 10GbE SFP+ | 90:ec:77:2e:0d:6b | active | 1000baseT | **WAN** (100.101.14.2/28) | Upstream (GigeNet) |
| ix3 | 10GbE SFP+ | 90:ec:77:2e:0d:6a | active | 1000baseT | Unassigned | Upstream (GigeNet) |

### Current Assignments (config.xml)

| pfSense Name | Interface | IP | Gateway |
|-------------|-----------|-----|---------|
| WAN | **lagg1 (ix2+ix3)** | 100.101.14.2/28 | WANGW (100.101.14.1) |
| LAN | lagg0 (igc2+igc3) | 10.25.0.1/24 | — |
| OPT1 (WG0) | tun_wg0 | 10.25.100.1/24 | — |
| **WANDR** | **igc0** | **100.101.14.3/28** | **WANDRGW (100.101.14.1)** |
| **LANDR** | **igc1** | **(standby, no IP)** | — |
| Public (VLAN 5) | lagg0.5 | 10.25.5.1/24 | — |
| Compute (VLAN 10) | lagg0.10 | 10.25.10.1/24 | — |
| Storage (VLAN 25) | lagg0.25 | 10.25.25.1/24 | — |
| Dirty (VLAN 66) | lagg0.66 | 10.25.66.1/24 | — |
| Management (VLAN 2550) | lagg0.2550 | 10.25.255.1/24 | — |

### Current Issues (Updated S036)
- ~~**lagg0 running FAILOVER**~~ FIXED S036 — LACP active, both ports ACTIVE/COLLECTING/DISTRIBUTING
- ~~**lagg0 MTU 1500**~~ FIXED S036 — MTU 9000 restored (runtime + config.xml)
- ~~**Switch Gi1/47-48 standalone**~~ FIXED S036 — Po2(SU) with Gi1/47(P) + Gi1/48(P)
- ~~**No errdisable recovery**~~ FIXED S036 — `errdisable recovery cause link-flap` interval 300s
- **igc0 on upstream GigeNet** — This is by design (WAN DR), connects to upstream Gi1/31
- ~~**igc1 not on our switch**~~ FIXED S036 — igc1 connected to Gi1/46, trunk configured

### Switch State (Cisco 4948E-F)

| Port | Status | Config | Notes |
|------|--------|--------|-------|
| Gi1/47 | connected | trunk, VLANs 1/5/10/25/66/2550, MTU 9198, `lacp rate fast` | **No channel-group** |
| Gi1/48 | connected | trunk, VLANs 1/5/10/25/66/2550, MTU 9198, `lacp rate fast` | **No channel-group** |
| Po2 | down (SD) | trunk, VLANs 1/5/10/25/66/2550, MTU 9198 | **Empty — no members** |

---

## 2. Target Architecture

```
                    ┌──────────────────────────────────────────┐
                    │          GigeNet Upstream                 │
                    │      (ISP Router/Switch)                  │
                    └───┬─────┬──────────┬─────────────────────┘
                        │     │          │
                   ix2  │  ix3│     igc0 │
                   (WAN1) (WAN2)   (WAN DR)
                        │     │          │
                    ┌───┴─────┴──────────┴─────────────────────┐
                    │          Netgate 4100                      │
                    │          pfSense 26.03                     │
                    │                                            │
                    │  WAN LAG (lagg1)    WAN DR     LAN DR      │
                    │  ix2 + ix3          igc0       igc1        │
                    │  [LACP/Failover]    [Single]   [Single]    │
                    │                                            │
                    │        LAN LAG (lagg0)                     │
                    │        igc2 + igc3                         │
                    │        [LACP]                              │
                    └───┬─────┬──────────────────────┬──────────┘
                        │     │                      │
                   igc2 │ igc3│                 igc1 │
                        │     │                      │
                    ┌───┴─────┴──────────────────────┴──────────┐
                    │     Cisco 4948E-F (gigecolo)               │
                    │                                            │
                    │  Po2 (LACP)         LAN-DR-Port            │
                    │  Gi1/47 + Gi1/48    Gi1/46 (proposed)      │
                    │  [trunk, all VLANs]  [trunk, all VLANs]    │
                    └───────────────────────────────────────────┘
```

### Port Assignment Summary

| Interface | Role | Connection | Mode | MTU |
|-----------|------|-----------|------|-----|
| **ix2 + ix3** | WAN LAG (lagg1) | GigeNet upstream | LACP or Failover | 1500 (WAN) |
| **igc0** | WAN DR | GigeNet upstream (separate port) | Single, no lag | 1500 (WAN) |
| **igc1** | LAN DR | Cisco Gi1/46 (proposed) | Single trunk, no lag | 9000 |
| **igc2 + igc3** | LAN LAG (lagg0) | Cisco Gi1/47+48 via Po2 | LACP | 9000 |
| ix0, ix1 | Unused | Not connected | — | — |

### pfSense Interface Assignments (Target)

| pfSense Name | Interface | IP | Gateway | Notes |
|-------------|-----------|-----|---------|-------|
| WAN | **lagg1** (ix2+ix3) | 100.101.14.2/28 | WANGW (100.101.14.1) | **DONE S036** — Moved from ix2 |
| LAN | lagg0 (igc2+igc3) | 10.25.0.1/24 | — | Unchanged |
| OPT1 (WG0) | tun_wg0 | 10.25.100.1/24 | — | Unchanged |
| **WANDR** | **igc0** | **100.101.14.3/28** | **WANDRGW (100.101.14.1)** | **DONE S036** — VIP 69.65.20.57/32, VPN tested |
| **LANDR** | **igc1** | **None (standby)** | — | DONE S036 — failover script handles activation |
| Public (VLAN 5) | lagg0.5 | 10.25.5.1/24 | — | Unchanged |
| Compute (VLAN 10) | lagg0.10 | 10.25.10.1/24 | — | Unchanged |
| Storage (VLAN 25) | lagg0.25 | 10.25.25.1/24 | — | Unchanged |
| Dirty (VLAN 66) | lagg0.66 | 10.25.66.1/24 | — | Unchanged |
| Management (VLAN 2550) | lagg0.2550 | 10.25.255.1/24 | — | Unchanged |

### Failover Behavior

| Scenario | Detection | Action | Downtime |
|----------|-----------|--------|----------|
| **WAN LAG failure** | pfSense gateway monitoring (dpinger) | Automatic — gateway group routes to igc0 (WAN DR) | ~5-10s (dpinger interval) |
| **LAN LAG failure** | Manual (loss of LAN connectivity) | Manual runbook — swap LAN from lagg0 to igc1 | ~2-5min (runbook execution) |
| **Single WAN port failure** | LACP/failover handles automatically | Transparent — lagg1 continues on surviving port | 0s (transparent) |
| **Single LAN port failure** | LACP handles automatically | Transparent — lagg0 continues on surviving port | 0s (transparent) |

---

## 3. Prerequisites & Assumptions

### MUST VERIFY BEFORE EXECUTION

| # | Item | Status | Action Required |
|---|------|--------|-----------------|
| P1 | **WAN LAG upstream support** — Does GigeNet upstream support LACP on ix2+ix3 ports? | **UNKNOWN** | Sonny to confirm with GigeNet. If no LACP: use failover mode instead. |
| P2 | **igc1 cabling to our switch** — igc1 currently has link but is NOT on our Cisco 4948E-F. LAN DR requires igc1 connected to our switch. | **NOT DONE** | Sonny to re-patch igc1 from wherever it currently goes → Cisco Gi1/46 (or other available port). |
| P3 | **igc0 upstream connectivity** — igc0 shows link to upstream. Confirm it reaches the same ISP gateway (100.101.14.1) or a separate one. | **UNKNOWN** | Sonny to confirm igc0 can reach WAN gateway. May need IP assignment from GigeNet. |
| P4 | **WAN DR IP address** — igc0 needs its own IP on the WAN subnet (or a separate WAN subnet). | **UNKNOWN** | Sonny to obtain from GigeNet: secondary IP on 100.101.14.0/28 or separate /30. |
| P5 | **ix3 upstream connectivity** — ix3 shows link to upstream. Confirm it connects to same device as ix2 (required for LAG). | **ASSUMED YES** | Verify after lagg1 creation. |

### Assumptions (will validate during execution)
- A1: ix2 and ix3 connect to the same upstream device (same L2 domain)
- A2: igc0 can route to the internet through the upstream
- A3: Switch Gi1/46 is available (currently showing notconnect, configured for VLAN 66)
- A4: pfSense 26.03-BETA supports multiple LAGGs (lagg0 + lagg1)

---

## 4. Execution Phases

### Phase 1: Restore LAN LACP + MTU 9000 (LOW RISK) — COMPLETE S036

**What:** Reform LACP on existing LAN LAG, restore jumbo frames.
**Impact:** Brief LAN interruption during LACP negotiation (~5-10 seconds).
**Rollback:** Remove channel-group from switch ports → immediate fallback to standalone.
**Result:** LACP formed, MTU 9000 restored, errdisable recovery added. Broken once by `rc.reload_interfaces` in Phase 3, recovered via DR port host route trick.

**Steps:**
1. Pre-change baseline → `logs/PRECHANGE-S036-lacp-restore.md`
2. Backup pfSense config.xml
3. Switch: Add channel-group to Gi1/47-48
   ```
   conf t
   interface range GigabitEthernet1/47 - 48
   channel-group 2 mode active
   end
   write memory
   ```
4. pfSense: Set lagg0 to LACP (config already says lacp, just runtime)
   ```
   sudo ifconfig lagg0 laggproto lacp
   ```
5. Verify LACP forms: both ports ACTIVE/COLLECTING/DISTRIBUTING
6. Restore MTU 9000 (runtime first):
   ```
   sudo ifconfig lagg0 mtu 9000
   ```
7. Verify connectivity to pve01, TrueNAS, VMs
8. Persist MTU to config.xml (manual edit, NOT GUI)
9. Add errdisable recovery to switch:
   ```
   conf t
   errdisable recovery cause link-flap
   errdisable recovery interval 300
   end
   write memory
   ```

### Phase 2: Configure LAN DR Switch Port (LOW RISK) — COMPLETE S036

**What:** Prepare switch port for igc1 (LAN DR).
**Impact:** None — configuring an unused port.
**Rollback:** `no switchport mode trunk` on the port.
**REQUIRES:** P2 (igc1 cabled to switch) — DONE
**Result:** Gi1/46 configured as trunk (VLANs 1/5/10/25/66/2550), MTU 9198, portfast edge trunk. igc1 linked up.

**Steps:**
1. Identify target switch port (Gi1/46 proposed — currently VLAN 66, notconnect)
2. Configure switch port:
   ```
   conf t
   interface GigabitEthernet1/46
   description LAN-DR-pfSense-igc1
   switchport trunk allowed vlan 1,5,10,25,66,2550
   switchport mode trunk
   mtu 9198
   no channel-group
   end
   write memory
   ```
3. Verify igc1 link comes up on Gi1/46 (check MAC 90ec.772e.0d6d)

### Phase 3: Assign DR Interfaces in pfSense (LOW RISK) — COMPLETE S036

**What:** Add igc1 (LANDR) and igc0 (WANDR) as OPT interfaces, no IPs, standby mode.
**Impact:** `rc.reload_interfaces` broke LACP (Lesson S036). Recovered via DR port.
**Rollback:** Remove interface assignment.
**REQUIRES:** Phase 2 complete, P2 (cabling) — DONE
**Result:** opt7=LANDR(igc1), opt8=WANDR(igc0) in config.xml and runtime. No IPs assigned yet.
**LESSON:** NEVER use `rc.reload_interfaces` when LACP is active — it bounces ALL interfaces including LAG members, causing switch err-disable.

**Steps:**
1. pfSense GUI: Interfaces > Assignments > Add igc1 as new OPT interface
2. Name it `LANDR`
3. Enable the interface, set to "None" for IP configuration
4. Description: "LAN Disaster Recovery - Standby"
5. Save (do NOT click Apply Changes yet — see lesson from S035)
6. Verify igc1 appears in interface list

### Phase 4: Create WAN LAG (HIGH RISK — VPN DROP) — COMPLETE S036

**What:** Create lagg1 (ix2+ix3), move WAN assignment from ix2 to lagg1.
**Impact:** VPN dropped during reboot. Recovered via WANDR (igc0) failover path.
**Result:** lagg1 LACP active, both ix2 and ix3 ACTIVE/COLLECTING/DISTRIBUTING. WAN IP 100.101.14.2/28, VIPs 69.65.20.58 and 69.65.20.62 all on lagg1. Config persisted.

**What actually happened:**
1. First attempt (runtime-only) FAILED — moved WAN IP from ix2 to lagg1 at runtime, but pf firewall rules stayed bound to ix2 in config.xml. VPN never reconnected.
2. Rollback left duplicate IPs on ix2 and lagg1 — gateway couldn't ARP. Fixed by removing duplicate.
3. pf firewall state was corrupted — `pfctl -d/-e`, WireGuard restart, `rc.filter_configure` all failed. Required full reboot.
4. Second attempt (config.xml + reboot) SUCCEEDED:
   - Configured WANDR first (igc0 = 100.101.14.3, VPN failover tested and working)
   - Edited config.xml: added lagg1 definition (ix3+ix2, LACP), changed WAN `<if>` from ix2 to lagg1
   - Sonny added Gi1/29 to channel-group 3 on upstream switch
   - Rebooted from console with VPN on WANDR endpoint (100.101.14.3:51820)
   - LACP formed on both ports, VPN reconnected

**Upstream switch (I-C1.03-SWITCH) port mapping:**
- Gi1/27 → ix3 (in channel-group 3 / Po3)
- Gi1/29 → ix2 (in channel-group 3 / Po3)
- Gi1/30 → igc0 (WANDR, standalone)

**Lessons:**
- L8: Runtime WAN IP migration doesn't update pf firewall rules — must edit config.xml and reboot
- L9: Always set up WANDR as VPN failover BEFORE attempting WAN changes
- L10: Duplicate IPs on two interfaces causes ARP flapping — gateway won't respond
- L11: `lacp rate fast` on switch causes repeated err-disable during reboots — use normal rate

### Phase 5: Configure WAN DR Interface (MEDIUM RISK) — PARTIAL S036

**What:** Assign igc0 as WAN DR with failover gateway group.
**Result (PARTIAL):** Interface configured with IP, gateway, VIP, and firewall rule. VPN failover TESTED AND WORKING. Gateway group NOT yet created.

**Completed:**
1. igc0 assigned as opt8 (WANDR) in config.xml — DONE Phase 3
2. IP: 100.101.14.3/28 — DONE S036
3. Gateway: WANDRGW = 100.101.14.1 on opt8 — DONE S036
4. VIP: 69.65.20.57/32 as IP alias on opt8 — DONE S036 (note: traffic to this IP arrives on ix2/lagg1 because upstream routes /29 to 100.101.14.2)
5. Firewall rule: Allow UDP 51820 to 100.101.14.3 on igc0 — DONE S036
6. WireGuard VPN tested through WANDR (endpoint 100.101.14.3:51820) — WORKING

**Remaining (Phase 5b):**
- Create Gateway Group `WANFAILOVER` (Tier 1: WANGW, Tier 2: WANDRGW)
- Update default gateway from WANGW → WANFAILOVER group
- Test automatic failover (dpinger-based)

**Key finding:** The routed /29 (69.65.20.56/29) is routed by the upstream to 100.101.14.2 (primary WAN). VIP 69.65.20.57 on igc0 does NOT receive inbound traffic — packets arrive on lagg1 instead. For WANDR VPN, use the transit IP 100.101.14.3:51820 directly.

### Phase 6: Create LAN DR VLAN Interfaces (LOW RISK — PREPARATION ONLY)

**What:** Pre-create VLAN sub-interfaces on igc1 matching lagg0 VLANs, but leave them disabled.
**Impact:** None — disabled interfaces.
**Purpose:** Speeds up LAN failover — VLANs already exist, just need IP swap.

**Steps:**
1. pfSense GUI: Interfaces > VLANs > Add:
   - igc1 VLAN 5 (Public DR)
   - igc1 VLAN 10 (Compute DR)
   - igc1 VLAN 25 (Storage DR)
   - igc1 VLAN 66 (Dirty DR)
   - igc1 VLAN 2550 (Management DR)
2. Do NOT assign IPs (would conflict with lagg0 VLANs)
3. Document VLAN interface names for runbook

---

## 5. LAN Failover Runbook (igc1 takeover)

### When to Use
- lagg0 is DOWN (both igc2 and igc3 lost — e.g., switch err-disable on Po2)
- VPN to pfSense still works (WAN is separate)
- Need to restore LAN routing through igc1

### Procedure (via SSH to pfSense)

**Step 1: Verify lagg0 is truly down**
```
ifconfig lagg0 | grep status
# Expected: "status: no carrier" or DOWN
```

**Step 2: Edit config.xml — swap LAN parent interface**
```
# Backup first
cp /cf/conf/config.xml /cf/conf/config.xml.backup-landr-failover

# Option A: Change LAN from lagg0 to igc1
# In config.xml, find: <if>lagg0</if> (in the <lan> section)
# Change to: <if>igc1</if>
# Also change all VLAN parent interfaces from lagg0 to igc1
```

**Step 3: Automated swap script (DEPLOYED at /opt/dc01/scripts/lan-failover.sh)**

Script is staged on pfSense. Uses **runtime ifconfig only** — NOT `rc.reload_interfaces` (which breaks LACP).

```sh
# Check status
sudo /opt/dc01/scripts/lan-failover.sh status

# Activate DR (fail over to igc1)
sudo /opt/dc01/scripts/lan-failover.sh activate

# Deactivate DR (restore lagg0)
sudo /opt/dc01/scripts/lan-failover.sh deactivate
```

The script:
- Creates VLAN sub-interfaces (igc1.5, igc1.10, igc1.25, igc1.66, igc1.2550) on demand
- Moves IPs from lagg0 VLANs → igc1 VLANs (or reverse)
- Sets MTU 9000 on igc1 to match lagg0
- Backs up config.xml before each operation
- Safety check: warns if lagg0 is still active (use `--force` to override)

**Step 4: Verify LAN DR is working**
```
ifconfig igc1          # Should show IPs on VLAN sub-interfaces
ping -c 3 10.25.0.26   # pve01 (if switch port is up)
ping -c 3 10.25.255.25  # TrueNAS
```

**Step 5: When primary LAN is restored**
- Fix the root cause (switch err-disable, cable, etc.)
- Verify lagg0 can form LACP
- Run: `lan-failover.sh deactivate`
- Verify all VMs reachable through lagg0

### Critical Notes
- The failover script uses sed on config.xml — this is safe because we're replacing exact XML tags
- `/etc/rc.reload_interfaces` reloads all interfaces from config.xml
- VPN stays up throughout (WAN is separate)
- VLANs on igc1 inherit configuration from config.xml
- igc1 must be physically connected to the switch BEFORE this works

---

## 6. WAN Failover Runbook (igc0 takeover)

### When to Use
- WAN LAG (lagg1 / ix2+ix3) is down
- Internet/VPN connectivity lost through primary WAN
- igc0 (WAN DR) has been pre-configured with gateway group

### Behavior (Automatic)
If Phase 5 is complete (gateway group configured), WAN failover is **automatic**:
1. dpinger detects WAN gateway (100.101.14.1) unreachable via lagg1
2. Gateway group shifts traffic to WANDRGW via igc0
3. VPN re-establishes through igc0
4. All outbound traffic routes through igc0

### Manual Override (if automatic failover fails)
```
# SSH to pfSense (may need console if VPN is also down)

# Check gateway status
pfctl -vvsr | grep -i gateway

# Force default route through igc0
route delete default
route add default [WANDRGW_IP]
```

### Recovery (when primary WAN restored)
1. Verify lagg1 has link: `ifconfig lagg1 | grep status`
2. Gateway group should auto-revert to primary (Tier 1)
3. Verify: `netstat -rn | grep default` shows lagg1 as primary

---

## 7. Prevention Measures (Post-Implementation)

### Switch Configuration
1. **errdisable recovery** for link-flap (300s auto-recovery)
2. **Separate Po2 for LAN LAG** — igc1 (LAN DR) intentionally NOT in Po2
3. **Spanning tree portfast** on LAN DR port (single host, no loops)

### pfSense Operational Rules
1. **NEVER change interface MTU via GUI on LACP members** (Lesson #19 from S035)
2. **MTU changes:** Runtime `ifconfig` first, verify LACP stable, then persist to config.xml
3. **VLAN sub-interfaces** inherit MTU from parent — no separate setting needed
4. **Config backups** before ANY interface change: `cp /cf/conf/config.xml /cf/conf/config.xml.backup-<session>`

### Monitoring (Future)
- Monitor lagg0 and lagg1 link state
- Monitor dpinger for WAN gateway health
- Alert on port-channel member loss
- Alert on err-disable events on switch

---

## 8. Phase Dependencies & Execution Order

```
Phase 1 (LAN LACP restore) ──────────────────────────────► COMPLETE S036 ✓
    │
Phase 2 (LAN DR switch port) ────────────────────────────► COMPLETE S036 ✓
    │
Phase 3 (DR interface assignment) ────────────────────────► COMPLETE S036 ✓
    │
Phase 4 (WAN LAG) ───────────────────────────────────────► COMPLETE S036 ✓
    │                                lagg1 (ix2+ix3) LACP active
Phase 5 (WAN DR config) ─────────────────────────────────► PARTIAL S036
    │                                Interface/IP/gateway/VPN DONE
    │                                Gateway group PENDING
Phase 6 (LAN DR VLANs) ──────────────────────────────────► DEFERRED
                                     Failover script creates VLANs on-demand
```

**Phases 1-4 complete.** WAN LAG operational via config.xml edit + reboot.
WANDR (igc0) configured and VPN-tested as failover path (100.101.14.3:51820).
LAN failover script deployed at `/opt/dc01/scripts/lan-failover.sh`.
Remaining: Gateway group for automatic WAN failover (Phase 5b).

---

## 9. Open Questions for Sonny (Updated S036)

| # | Question | Status | Answer |
|---|----------|--------|--------|
| Q1 | Does the GigeNet upstream support LACP on the ix2+ix3 ports? | **ANSWERED** | Yes — Sonny will configure upstream LACP himself. Config provided (Po3, Gi1/29+30). |
| Q2 | igc1 cabled to our switch Gi1/46? | **DONE** | Confirmed connected S036. |
| Q3 | WAN DR IP for igc0? | **ANSWERED** | 69.65.20.57 |
| Q4 | Where does igc0 connect? | **ANSWERED** | Same upstream device, port Gi1/31 |
| Q5 | Console access to Netgate? | **ANSWERED** | Yes, Sonny has console access |
| Q6 | What is the subnet mask and gateway for 69.65.20.57 on igc0? | **ANSWERED** | 69.65.20.56/29 is routed to 100.101.14.2 by upstream. VIP on igc0 doesn't receive inbound traffic. igc0 uses transit IP 100.101.14.3/28, gateway 100.101.14.1. |
| Q7 | Which upstream port does ix3 connect to? | **ANSWERED** | ix3→Gi1/27, ix2→Gi1/29, igc0→Gi1/30 on upstream I-C1.03-SWITCH |

---

## 10. Lessons Learned (S036)

| # | Lesson | Context |
|---|--------|---------|
| L1 | **NEVER run `rc.reload_interfaces` when LACP is active** — it bounces ALL interfaces including LAG members, causing switch err-disable. Use runtime `ifconfig` commands or reboot instead. | Phase 3 broke LACP |
| L2 | **Host route trick for DR recovery** — When lagg0 is down and routes are stuck, add a `/32 host route` via the DR port to override the `/24 network route`. This bypasses FreeBSD's refusal to modify connected routes. | Recovered from Phase 3 LACP break |
| L3 | **SSH ProxyJump for switch access** — When WSL can't reach the switch directly (broken LAN path), use `ssh -o ProxyCommand="ssh -W %h:%p pfSense" switch` to tunnel through pfSense. | Used to clear err-disable via DR port |
| L4 | **Cisco IOS config via SSH stdin** — Cisco doesn't accept config commands via SSH exec. Pipe commands through stdin: `echo "conf t..." \| ssh -T switch` | Phase 1 recovery |
| L5 | **FreeBSD sed doesn't support `\t`** — Use perl for config.xml edits that need tab indentation. | Phase 1 MTU persist |
| L6 | **pfSense tcsh breaks bash quoting** — Use base64-encoded scripts via `b64decode -r \| sudo sh` for multi-line operations. | All pfSense operations |
| L7 | **Clean up stale IPs on LACP members** — After recovering from LACP outage, check if member interfaces (igc2/igc3) have stale IP assignments that create wrong routing table entries. | Post-recovery cleanup |
| L8 | **Runtime WAN IP migration doesn't update pf firewall** — Moving WAN IP from ix2 to lagg1 at runtime leaves pf rules bound to ix2. Must edit config.xml and reboot. | Phase 4 first attempt |
| L9 | **Set up WANDR before WAN changes** — Always configure and test the DR WAN path (igc0) BEFORE making WAN LAG changes. This provides a VPN fallback if the migration fails. | Phase 4 recovery |
| L10 | **Duplicate IPs cause ARP flapping** — If two interfaces have the same IP, the upstream gateway sees conflicting ARP responses and stops responding. Always remove IPs from old interface before/after migration. | Phase 4 rollback |
| L11 | **Remove `lacp rate fast` from switch** — Fast LACP rate (1s PDU) causes rapid link-flap detection during reboots/interface restarts, leading to repeated err-disable. Normal rate (30s) is much more tolerant. | LACP stability fix |
| L12 | **Errdisable recovery 30s** — Reduced from 300s to 30s for faster auto-recovery. Combined with watchdog cron (60s), max auto-recovery time is ~90s. | Switch config |
| L13 | **Routed /29 goes to primary WAN** — The 69.65.20.56/29 block is routed by upstream to 100.101.14.2 (primary WAN IP). VIPs from this block on WANDR (igc0) won't receive inbound traffic. Use transit IP (100.101.14.3) for WANDR services. | Phase 5 discovery |

## 11. Rollback Matrix

| Phase | Rollback Procedure | Time to Rollback |
|-------|-------------------|-----------------|
| Phase 1 | `no channel-group 2` on Gi1/47-48 → standalone trunks, `ifconfig lagg0 laggproto failover` | 30 seconds |
| Phase 2 | `default interface Gi1/46` on switch | 10 seconds |
| Phase 3 | Remove igc1 from Interfaces > Assignments | 30 seconds |
| Phase 4 | Change WAN from lagg1 → ix2, delete lagg1 (needs console if VPN down) | 2-5 minutes |
| Phase 5 | Remove WANDR interface, delete gateway group, restore single gateway | 2 minutes |
| Phase 6 | Remove VLAN interfaces from igc1 | 1 minute |
