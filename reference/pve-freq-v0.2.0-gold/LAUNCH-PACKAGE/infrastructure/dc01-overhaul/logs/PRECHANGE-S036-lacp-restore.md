# Pre-Change Baseline — S036 Phase 1: LAN LACP Restore

> **Session:** S036-20260221
> **Operation:** Restore LACP on lagg0 (igc2+igc3), restore MTU 9000, add errdisable recovery
> **Risk Level:** LOW (brief LAN interruption during LACP negotiation)

## Pre-Change State

### pfSense lagg0
- Protocol: FAILOVER (runtime) / LACP (config.xml)
- Members: igc2 (MASTER/ACTIVE), igc3 (backup, flags=0)
- MTU: 1500
- IP: 10.25.0.1/24
- VLANs: .5, .10, .25, .66, .2550

### Switch
- Gi1/47: standalone trunk, connected, MTU 9198, `lacp rate fast`, NO channel-group
- Gi1/48: standalone trunk, connected, MTU 9198, `lacp rate fast`, NO channel-group
- Po2: exists but EMPTY (SD = layer 2, down)

### Config Backup
- pfSense: `/cf/conf/config.xml.backup-s036-pre-lacp` (67270 bytes)

## Rollback Procedure

### If LACP fails to form:
```
# Switch: remove channel-group
conf t
interface range GigabitEthernet1/47 - 48
no channel-group 2
end
write memory
```

### If pfSense loses connectivity:
```
# pfSense: revert to failover
sudo ifconfig lagg0 laggproto failover
```

### If MTU change causes issues:
```
# pfSense: revert MTU
sudo ifconfig lagg0 mtu 1500
```
