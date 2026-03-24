# INCIDENT S035: LACP Outage — Recovery Guide

> **Status:** ACTIVE OUTAGE
> **Priority:** P0
> **Created:** 2026-02-20 S035
> **Impact:** ALL inter-VLAN routing DOWN. No VPN access to any device behind pfSense.

---

## What Happened

1. Sonny changed pfSense VLAN sub-interface MTU to 9000 via GUI
2. pfSense "Apply Changes" restarted lagg0 member interfaces (igc2, igc3)
3. LACP PDU exchange was interrupted during the interface restart
4. Link flapping triggered switch (Cisco 4948E-F) to err-disable Gi1/47 and Gi1/48
5. Without lagg0, pfSense cannot route ANY LAN/VLAN traffic
6. All VMs, Proxmox nodes, TrueNAS — unreachable from VPN

## What Still Works

- VPN to pfSense itself (through WAN/WireGuard on ix2)
- SSH to pfSense at 10.25.255.1
- Devices on the SAME VLAN can communicate through the switch (no pfSense needed)
- Docker containers may still run but NFS mounts are broken (inter-VLAN)

## Recovery Attempted (All Failed)

1. Bounced igc2/igc3 from pfSense — no link
2. Set lagg0 to failover mode (non-LACP) — no link
3. Reset LACP protocol (`ifconfig lagg0 laggproto lacp`) — no link
4. Removed igc2 from lagg, standalone with IP — no link
5. pfSense reboot #1 (with MTU 9000 in config.xml) — no link
6. Removed MTU from config.xml, pfSense reboot #2 — no link
7. Forced media settings on igc2 (1000baseT full-duplex) — no link
8. Brought up ALL unused interfaces (igc0, igc1, ix0, ix1, ix3) — none have carrier
9. Checked iDRAC accessibility — unreachable (behind broken lagg0)

**Conclusion:** Switch ports are err-disabled. Cannot be fixed from pfSense.

## Recovery Steps (Requires Switch Access)

### Option A: Console Access (Preferred)

Connect to switch console (serial cable to Gi1/48 console port):

```
enable
Password: <use svc-admin password>

conf t
interface range GigabitEthernet1/47 - 48
shutdown
no shutdown
end

write memory
```

### Option B: SSH from a Device on the LAN

If any device on the LAN (10.25.0.0/24) or Management VLAN (10.25.255.0/24) is reachable:

```
sshpass -f /tmp/.svc-pass ssh -o KexAlgorithms=+diffie-hellman-group14-sha1 \
  -o HostKeyAlgorithms=+ssh-rsa -o PubkeyAcceptedAlgorithms=+ssh-rsa \
  svc-admin@10.25.255.5
```

Then run the same commands as Option A.

### Option C: Physical Cable Bounce (Last Resort)

Unplug and re-plug the Ethernet cables from switch ports Gi1/47 and Gi1/48.
**NOTE:** This may NOT clear err-disable on all Cisco platforms. `shut/no shut` is more reliable.

## After Switch Ports Are Restored

1. **Verify LACP forms automatically:**
   ```
   sshpass -f /tmp/.svc-pass ssh svc-admin@10.25.255.1 'ifconfig lagg0 | grep -E "laggport|status"'
   ```
   Expected: `laggport: igc2 flags=1c<ACTIVE,COLLECTING,DISTRIBUTING>`, `status: active`

2. **If LACP doesn't form, manually trigger:**
   ```
   sudo ifconfig lagg0 laggproto lacp
   ```

3. **Restore MTU 9000 (runtime only first):**
   ```
   sudo ifconfig lagg0 mtu 9000
   ```

4. **Verify connectivity:**
   ```
   ping -c 3 10.25.255.26    # pve01
   ping -c 3 10.25.255.25    # TrueNAS
   ping -c 3 10.25.255.30    # VM 101
   ```

5. **Persist MTU to config.xml** (only after everything is confirmed working):
   ```
   sudo sed -i 's|</lan>|\t\t\t<mtu>9000</mtu>\n\t\t</lan>|' /cf/conf/config.xml
   ```
   Or set via pfSense GUI: Interfaces > LAN > MTU: 9000 > Save > **DO NOT click Apply Changes until LACP is verified stable.**

6. **Verify NFS on all VMs** — check containers are running, NFS mounts responsive.

## Preventing Recurrence

### Lesson Learned: Never Change pfSense Interface MTU via GUI on LACP Members

The pfSense GUI's "Apply Changes" restarts ALL interfaces associated with the parent,
including LACP members. This disrupts LACP negotiation and can trigger switch err-disable.

**Safe procedure for MTU changes:**
1. Set MTU at runtime: `ifconfig lagg0 mtu 9000` (LACP stays up)
2. Verify LACP is still active
3. Only then persist to config.xml manually (not via GUI)
4. VLAN sub-interfaces inherit MTU from parent — no separate setting needed

### Switch Configuration to Add

After recovery, add err-disable auto-recovery to the switch:
```
conf t
errdisable recovery cause link-flap
errdisable recovery interval 300
end
write memory
```

This ensures that if a similar event occurs, the switch auto-recovers after 5 minutes
instead of requiring manual intervention.

## pfSense State

- **config.xml:** MTU removed from LAN interface (safe for LACP formation at default 1500)
- **Backup:** `/cf/conf/config.xml.backup-s035-lacp-fix` (has original MTU 9000)
- **All other config:** Intact (firewall rules, NAT, WireGuard, interfaces)
- **Runtime:** lagg0 set to LACP protocol, igc2+igc3 as members, both "no carrier"
