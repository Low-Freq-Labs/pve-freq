# TICKET-0005: VLAN 5 NFS Exception IP Discrepancy -- pfSense Rule References 10.25.25.25 but VMs Mount via 10.25.0.25

**Priority:** P2 (high)

## Context

- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 4 (VLAN Map, line 140) and Section 5 (NFS Mount Strategy, lines 312-313)
- **DC01.md reference:** VLAN Map (line 373), VM NFS fstab entries (lines 234-235)

**ARCHITECTURE.md VLAN Map (line 140):**
```
| 5 | 10.25.5.0/24 | igc3.5 (Public) | Vlan5: 10.25.5.5 | Public-facing services (Plex, Arr) |
  RFC1918 block + NFS exception (10.25.25.25) + internet pass |
```

**ARCHITECTURE.md NFS Mount Strategy (line 313):**
```
| 5 (Public) | 10.25.0.25 | eno1 | VMs have static route `10.25.0.0/24 via 10.25.5.5` (switch SVI) |
```

**DC01.md VM fstab (lines 234-235):**
```
| 101 | 10.25.0.25:/mnt/mega-pool/nfs-mega-share ... |
| 102 | 10.25.0.25:/mnt/mega-pool/nfs-mega-share ... |
```

## Diagnosis

The VLAN Map row for VLAN 5 says the pfSense NFS exception is for `10.25.25.25` (the VLAN 25 storage IP on bond0). But VLAN 5 VMs actually mount NFS via `10.25.0.25` (the VLAN 1 LAN IP on eno1), using a static route `10.25.0.0/24 via 10.25.5.5` to reach it through the switch SVI.

This means either:
- (a) The pfSense exception should be for `10.25.0.25` (the IP actually used), or
- (b) The exception is correctly for `10.25.25.25` but there is an additional exception for `10.25.0.0/24` that is not documented, or
- (c) The exception IP in the VLAN Map is carried verbatim from DC01.md (line 373 says the same `10.25.25.25`) and represents the actual pfSense rule, while the NFS traffic takes a path that bypasses pfSense entirely (via the switch SVI static route, so the pfSense exception may be a belt-and-suspenders entry for the storage VLAN).

The ARCHITECTURE.md and DC01.md both have this same value, so this is not a Worker #1 fabrication. However, it is confusing and potentially misleading. The relationship between the pfSense NFS exception and the actual NFS traffic path needs clarification.

## Recommendations

1. Add a clarifying note to the VLAN 5 row in the VLAN Map:
```
NFS exception (10.25.25.25) allows VLAN 5 VMs to reach TrueNAS storage IP if
routed through pfSense. In practice, VLAN 5 VMs mount NFS via 10.25.0.25 using
a static route through the switch SVI (10.25.5.5), bypassing pfSense entirely.
```

2. Verify on pfSense whether the exception is actually for 10.25.25.25 or 10.25.0.25 -- if the NFS traffic never hits pfSense, the exception may be irrelevant or there may be an undocumented exception for 10.25.0.0/24.
