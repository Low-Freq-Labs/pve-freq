# Pre-Change Baseline: TrueNAS Policy Routing for WG→Storage VLAN
# Session: S039-20260223
# System: TrueNAS (10.25.255.25 / 10.25.25.25)

## Purpose
Add source-based routing so replies FROM 10.25.25.25 (Storage IP) to WireGuard
clients (10.25.100.0/24) go via bond0 → pfSense 10.25.25.1 (Storage VLAN),
while replies FROM 10.25.255.25 (Management IP) continue via eno4 → pfSense
10.25.255.1 (Management VLAN).

## Pre-Change State
- Route: `10.25.100.0/24 via 10.25.255.1 dev eno4`
- Rules: default only (local, main, default)
- bond0: 10.25.25.25/24 (Storage VLAN)
- eno4: 10.25.255.25/24 (Management VLAN)

## Changes Applied
1. `ip route add 10.25.100.0/24 via 10.25.25.1 dev bond0 table 100`
2. `ip rule add from 10.25.25.25 to 10.25.100.0/24 lookup 100 priority 100`

## Rollback
```
ip rule del from 10.25.25.25 to 10.25.100.0/24 lookup 100 priority 100
ip route del 10.25.100.0/24 via 10.25.25.1 dev bond0 table 100
```

## pfSense Dependency
Requires pfSense rule on STORAGE (lagg0.25): pass from STORAGE net to 10.25.100.0/24
(added by Sonny via GUI before this change).
