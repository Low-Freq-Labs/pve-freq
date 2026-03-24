# S037 Emergency Handoff — Created 2026-02-22

> **WHY THIS FILE EXISTS:** VPN is down due to pfSense default route deletion during S037.
> SMB share is inaccessible. This local backup preserves session context until pfSense reboot.
> **CLAUDE.md backup** is in this same directory — copy it back to SMB after VPN is restored.

## CRITICAL: Monday Recovery Steps (Sonny @ datacenter 4pm)

1. **Reboot pfSense** — Menu option 5, or power cycle
   - config.xml is correct: `<defaultgw4>WANGW</defaultgw4>` (lagg1)
   - VIP 69.65.20.61 persisted to config.xml (added S037)
   - config.xml backup at: `/cf/conf/config.xml.backup-s037-pre-filter-reload`
2. **Reconnect VPN** — Both primary (69.65.20.58) and WANDR (100.101.14.3) endpoints
3. **Remount SMB** — Open new WSL terminal or `sudo mount /mnt/smb-sonny`
4. **Restore CLAUDE.md** — Copy `~/dc01-overhaul/emergency-backup-s037/CLAUDE.md` back to SMB if the SMB version is stale
5. **Run health check** — Verify all systems came back cleanly

## What Happened in S037

### Phase 1: Documentation Sync (SAFE — completed successfully)
- Full Boot (worker memory-notes stale S032→S037)
- Processed pfSense dashboard screenshot (WANDRGW "Unknown" gateway)
- Updated CLAUDE.md: pfSense section rewritten for S036 state
- Updated DC01.md: Interface inventory, 13 lessons (#21-33), S036/S037 change logs
- Updated TASKBOARD.md, INC-001 (→RESOLVED), all 3 worker memory-notes
- Credential scan: CLEAN

### Phase 2: Health Check (read-only SSH)
- VMs 101/102/104/105: All healthy, containers UP, NFS mounted
- VM 103: gluetun UNHEALTHY — restart loop, zero internet
- pfSense: All LAGs healthy (lagg0 LACP, lagg1 LACP, WANDR active, LANDR active)
- TrueNAS: mega-pool ONLINE, 0 errors, 6% used
- Switch: Po1(SU), Po2(SU)
- pve01: All VMs running, HA quorum OK

### Phase 3: VM 103 Investigation (root cause found, partially fixed)

**Root cause is TWO issues:**

1. **Missing VIP 69.65.20.61** — The NAT rule for VLAN 66 translates to 69.65.20.61, but that IP was never added as a VIP on lagg1. Only .58, .62, .57 existed. Likely lost during S036 WAN migration (ix2→lagg1).
   - **FIX APPLIED AND PERSISTED:** Added to config.xml as IP alias on wan interface + applied at runtime via `ifconfig lagg1 alias 69.65.20.61/32`. Survives reboot.

2. **Default route on igc0 instead of lagg1** — `netstat -rn` showed `default 100.101.14.1 UGS igc0`. Config says WANGW (lagg1) but runtime route went through igc0 (WANDR). Both interfaces share the same /28 subnet (100.101.14.0/28), causing FreeBSD to resolve the gateway to igc0.
   - **THIS IS WHAT BROKE VPN.** While attempting to fix the route via `route delete default; route add...`, the VPN tunnel died because pfSense lost the ability to route WireGuard return packets.
   - **FIX:** Reboot pfSense. Config.xml has correct `<defaultgw4>WANGW</defaultgw4>`.

**Additional finding: F-S034-MTU CLOSED**
- All VLAN sub-interfaces (lagg0.5/10/25/66/2550) now MTU 9000
- S035 GUI MTU changes persisted in config.xml, took effect after S036 reboots

### Phase 4: Outage (current state)
- pfSense default route deleted/corrupted during fix attempt
- VPN down — both primary and WANDR endpoints unreachable
- SMB share unmounted (VPN required)
- All remote access to DC01 infrastructure LOST
- Waiting for Sonny to physically reboot pfSense (Monday 4pm)

## Files Modified This Session (on SMB — may need verification after restore)

1. **~/Jarvis & Sonny's Memory/CLAUDE.md**
   - pfSense section rewritten for S036
   - F-S034-MTU marked CLOSED in Cluster Hardening
   - Added svc.env credential file reference
   - Added Lesson S037-L1 (never modify routes remotely)
   - Added VIP 69.65.20.61 to WAN LAG VIP list

2. **~/Jarvis & Sonny's Memory/DC01.md**
   - pfSense Interface Inventory section added
   - VLAN sub-interface MTU table: 1500→9000
   - F-S034-MTU CLOSED in Open Findings
   - F-S037-VM103-FW OPENED (CRITICAL) — VLAN 66 + missing VIP + wrong default route
   - 13 new Lessons Learned (#21-33)
   - S036 + S037 change log entries
   - Sonny's Tasks: VM 103 firewall fix added

3. **~/dc01-overhaul/TASKBOARD.md** (LOCAL — safe)
   - S037 boot entry, health check results, F-S034-MTU closed, F-S037-VM103-FW opened
   - VM 103 firewall fix added to Pending Sonny Decisions

4. **~/dc01-overhaul/incidents/INC-001-LAGG-VLAN1-OUTAGE.md** (LOCAL — safe)
   - Status → RESOLVED, S032/S035/S036 history added

5. **All 3 worker memory-notes** (LOCAL — safe) — freshly rewritten for S037

## Post-Reboot Status (2026-02-23 — pfSense rebooted by Sonny)

| Check | Result |
|-------|--------|
| VPN | **UP** — WireGuard reconnected, pfSense LAN (10.25.5.1) reachable |
| SMB | **UP** — mounted and accessible |
| VIP 69.65.20.61 | **ACTIVE on lagg1** — persisted through reboot |
| Default route | **STILL ON igc0** — `default 100.101.14.1 UGS igc0` — reboot did NOT fix |
| pfSense internet | **DOWN** — ping 1.1.1.1 100% loss (wrong default route) |
| VM 101 (VLAN 10) | **UNREACHABLE** — SSH timed out, pfSense can't ping 10.25.10.101 either |
| VM 103 (VLAN 66) | **UNREACHABLE** — SSH timed out |
| Proxmox (10.25.0.25) | **Reachable from pfSense** but not from WSL (firewall/routing) |
| VLAN 5 hosts | **Working** — 10.25.5.30 responds to ping |
| lagg0 LACP | **Healthy** — igc2+igc3 both ACTIVE, COLLECTING, DISTRIBUTING |
| CLAUDE.md | **Synced** — emergency backup copied to SMB |

**KEY FINDING:** Default route on igc0 is NOT a transient issue — it persists across reboots. The shared /28 subnet is a structural problem. This needs a permanent fix (move WANDR to different subnet or policy routing).

**VLAN 10 unreachable** needs investigation — VMs may be down, or pf rules may be blocking, or it could be related to the default route issue.

## Remaining TODO

1. **FIX DEFAULT ROUTE** — This is the root blocker. Options: (a) pfSense GUI System→Routing→set gateway interface explicitly, (b) move WANDR to different subnet, (c) policy routing
2. Test VM 103 internet after default route is fixed — restart gluetun if needed
3. Investigate VLAN 10 unreachable — check Proxmox VM status, pf rules
4. WANDRGW Monitor IP fix (GUI — set to 9.9.9.9)
5. Update F-S037-VM103-FW with complete root cause
6. Full health check once routing is fixed

## Credential Reference

- **Credential file:** `~/svc.env` (Username + Password for svc-admin)
- **SSH pattern:** `grep Password ~/svc.env | cut -d'=' -f2 | tr -d ' ' > /tmp/.svc-pass && sshpass -f /tmp/.svc-pass ssh svc-admin@<host>`
- **Password has `!`** — if writing manually, use Python to avoid bash history expansion
