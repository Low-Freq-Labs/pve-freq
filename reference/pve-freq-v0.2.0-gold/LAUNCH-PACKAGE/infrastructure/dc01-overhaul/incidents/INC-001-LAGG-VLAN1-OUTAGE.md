# INC-001: pfSense LAGG / VLAN 1 Outage

**Status:** RESOLVED — LACP fully operational (S032), broken by S035 LACP outage, fully restored S036 with DR architecture
**Opened:** 2026-02-19 Session 20
**Severity:** HIGH
**Affected Systems:** pfSense fw01, all LAN devices (VLAN 1)

## Timeline

| When | What |
|------|------|
| Session 19 | pfSense LAGG discussed in overhaul plan (Phase 6). No bonds configured yet. |
| Session 20 | LACP attempt. Multiple failures: LACP key mismatch, Gi1/47 err-disabled, VLAN 1 broken. Reverted to single-member FAILOVER. |
| Between S20-S21 | pfSense rebooted. VLAN 1 restored (cause unknown — likely stale ARP/MAC resolved by reboot). |
| Session 21 | Cleaned up switch (Po2 deleted, Gi1/47 standalone), added igc2 to FAILOVER, tested both directions. LACP cutover staged but paused for handoff. |

## Root Cause Analysis

### Session 20 Failures
1. **Gi1/48 was NOT in Po2** — switch expected LACP only on Gi1/47, not Gi1/48
2. **LACP key mismatch** — igc2 advertised key 0x8003 vs igc3 key 0x01CB (possible FreeBSD/pfSense bug or stale config)
3. **channel-misconfig err-disable** killed Gi1/47 on the switch (auto-recovery was disabled)
4. **Session 20 misdiagnosis** — "duplicate `<members>` tags" was incorrectly identified as the root cause. The empty tag was for WireGuard interface group, not LAGG.

### Contributing Factors
- No change management checklist before LACP configuration
- No pre-change baseline captured
- errdisable auto-recovery was disabled for all causes
- No monitoring detected the VLAN 1 outage

## Resolution

### Completed (Session 21)
- Switch cleaned to known-good state (standalone trunks, no dead port-channels)
- FAILOVER established and tested with both members
- errdisable auto-recovery enabled for channel-misconfig (30 sec)
- Handoff documentation written with exact LACP cutover commands

### Completed (Session 32)
- LACP cutover executed successfully — Po2(SU), Gi1/47(P)+Gi1/48(P)
- MTU 9000 restored on lagg0 (runtime + config.xml)
- All connectivity verified

### Incident S035 (LACP Outage #2)
- Sonny changed pfSense VLAN MTU via GUI → "Apply Changes" bounced lagg0 members → switch err-disabled both ports
- Recovery required physical datacenter visit to remove channel-group from switch
- Resulted in FAILOVER mode (degraded)

### Final Resolution (Session 36)
- LACP re-established with channel-group on Gi1/47-48
- MTU 9000 restored via runtime ifconfig + config.xml perl edit
- `lacp rate fast` REMOVED (caused repeated err-disable during reboots)
- Errdisable recovery: link-flap interval 30s
- DR architecture deployed: LANDR (igc1/Gi1/46), WANDR (igc0), WAN LAG (lagg1)
- LAN failover script at `/opt/dc01/scripts/lan-failover.sh`
- 13 new lessons learned (#21-33 in DC01.md)

## Lessons Learned
1. Always verify XML structure in context — grep hits can be misleading across different sections
2. errdisable auto-recovery should be enabled for LACP-related causes during initial setup
3. Both switch ports MUST be consistently configured before enabling LACP
4. pfSense web UI is the recommended method for LAGG protocol changes, but config.xml + ifconfig works for member additions
5. FAILOVER should be verified working before attempting LACP (incremental approach)
