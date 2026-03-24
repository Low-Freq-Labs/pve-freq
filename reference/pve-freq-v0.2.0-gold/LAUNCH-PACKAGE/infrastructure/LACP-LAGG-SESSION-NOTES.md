# LACP LAGG Troubleshooting — Handoff Notes

**Last Updated:** 2026-02-20 Session 32
**Status:** LACP COMPLETE — Both ports ACTIVE/COLLECTING/DISTRIBUTING, MTU 9000, config saved.

---

## CURRENT STATE (READ THIS FIRST)

### pfSense lagg0 — LACP ACTIVE (Session 32)
- **Running protocol:** LACP
- **config.xml protocol:** `<proto>lacp</proto>` (matches running state)
- **Members:** igc2 (ACTIVE, COLLECTING, DISTRIBUTING via Gi1/47), igc3 (ACTIVE, COLLECTING, DISTRIBUTING via Gi1/48)
- **config.xml members:** `<members>igc3,igc2</members>`
- **VLAN 1:** WORKING — pfSense can reach switch (10.25.0.5), TrueNAS (10.25.0.25), pve01 (10.25.0.26)
- **Tagged VLANs:** ALL working (5, 10, 25, 66, 2550)
- **MTU:** 9000 on lagg0 (FIXED Session 32, persisted in config.xml)
- **MAC:** 90:ec:77:2e:0d:6e (igc2's MAC — changed from igc3's after LACP)
- **config.xml backups:** `backup-session21`, `backup-session26`, `backup-session31`, `backup-session32`

### Switch (Cisco 4948E-F at 10.25.0.5)
- **Po2:** LACP, SU (Layer2, In Use), trunk mode, VLANs 1,5,10,25,66,2550, MTU 9198
- **Gi1/47:** Member of Po2, LACP active, fast rate, status P (bundled)
- **Gi1/48:** Member of Po2, LACP active, fast rate, status P (bundled)
- **errdisable recovery:** channel-misconfig auto-recovery ENABLED, 30 second interval
- **Po1 (TrueNAS LACP):** Healthy — Gi1/8(P) + Gi1/11(P), VLAN 25 storage
- **Config SAVED to startup-config** (`write memory` Session 32)

### Connectivity Verified (Session 32)
- Switch: 1ms, TrueNAS: 0.3ms, pve01: 0.3ms
- 13/13 Docker containers running
- pfSense webGUI responding on VPN

---

## WHAT WAS DONE IN SESSION 21

1. Probed live state — discovered VLAN 1 was actually working (contrary to Session 20 notes)
2. Discovered Session 20 "duplicate members" was WRONG — the empty `<members>` tag was for WireGuard interface group, NOT for LAGG
3. Removed Gi1/47 from Po2 on switch (was suspended/dead)
4. Deleted Po2 from switch
5. Made Gi1/47 a clean standalone trunk
6. Added igc2 to lagg0 on pfSense (config.xml + ifconfig)
7. Tested FAILOVER successfully (both directions)
8. Enabled errdisable auto-recovery for channel-misconfig (30 second interval)
9. Pre-staged config.xml for LACP but REVERTED to failover for safety before handoff

---

## LACP CONVERSION — COMPLETED (Session 32)

### What Was Executed
1. **config.xml backup** → `backup-session32`
2. **config.xml edit** → `<proto>failover</proto>` → `<proto>lacp</proto>`
3. **Round 1 FAILED:** Switch Po2 created as L3 (routed) instead of L2 (switched). `Command rejected: Po2 is not a switching port.` pfSense delayed script auto-reverted to failover (safety net worked).
4. **Switch fix:** Deleted bad Po2. Recreated with `switchport` as FIRST command, then `switchport mode trunk`, then VLANs.
5. **Round 2 TIMING ISSUE:** ~40s gap between pfSense script launch and switch channel-group command. pfSense script checked too early, didn't find DISTRIBUTING, auto-reverted. Switch channel-group went through after revert — both ports suspended (no partner).
6. **Manual fix:** `sudo ifconfig lagg0 laggproto lacp` on pfSense with switch already in LACP mode. LACP formed in <5 seconds.
7. **MTU fix:** `ifconfig lagg0 mtu 9000` + config.xml `<mtu>9000</mtu>` persisted.
8. **Gluetun restart:** WireGuard VPN session disrupted by LACP transition. Container restart fixed it.
9. **`write memory`** on switch.

### Lessons Learned
- Cisco 4948E-F port-channels default to L3 (routed). **MUST use `switchport` as the first command** before `switchport mode trunk`.
- Delayed-script approach works for coordinating two devices when SSH will be lost during outage. Auto-revert safety net successfully fired twice.
- pfSense tcsh shell doesn't support bash heredocs. Use base64-encoded scripts piped through `b64decode -r`.
- After LACP forms, stale ARP cache on switch caused initial ping failure. Resolved on retry.
- WireGuard VPN sessions don't survive LACP transitions. Restart gluetun after cutover.

### Rollback Plan (kept for reference)
If LACP needs to be reverted:
```
# From pfSense (via WAN SSH):
ifconfig lagg0 laggproto failover
# This immediately reverts to FAILOVER mode and restores LAN

# Then on switch (once LAN is back):
conf t
interface range Gi1/47 - 48
 no channel-group 2 mode active
 no lacp rate fast
end
no interface Port-channel2
write memory
```

---

## PHYSICAL CABLING (CONFIRMED)

| pfSense NIC | MAC | Switch Port | Status |
|-------------|-----|-------------|--------|
| igc2 | 90:ec:77:2e:0d:6e | Gi1/47 | Connected, standalone trunk |
| igc3 | 90:ec:77:2e:0d:6f | Gi1/48 | Connected, standalone trunk |
| ix2 | 90:ec:77:2e:0d:6b | WAN uplink | Working (unrelated) |
| igc0 | 90:ec:77:2e:0d:6c | Nothing | no carrier |
| igc1 | 90:ec:77:2e:0d:6d | Nothing | no carrier |

## pfSense Interface Assignments (no conflicts)
- WAN = ix2
- LAN = lagg0 (10.25.0.1/24)
- lagg0.5 = Public (10.25.5.1/24)
- lagg0.10 = Compute (10.25.10.1/24)
- lagg0.25 = Storage (10.25.25.1/24)
- lagg0.66 = Dirty (10.25.66.1/24)
- lagg0.2550 = Management (10.25.255.1/24)
- tun_wg0 = WireGuard VPN (10.25.100.1/24)

## SSH Access Reference
- pfSense: `sshpass -p '<pw>' ssh -o StrictHostKeyChecking=no admin@10.25.0.1`
- Switch: `sshpass -p '<pw>' ssh -o StrictHostKeyChecking=no -o KexAlgorithms=+diffie-hellman-group14-sha1 -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedKeyTypes=+ssh-rsa sonny-aif@10.25.0.5`
- Credentials: In Sonny's password vault (VM 802). NOT stored here.
