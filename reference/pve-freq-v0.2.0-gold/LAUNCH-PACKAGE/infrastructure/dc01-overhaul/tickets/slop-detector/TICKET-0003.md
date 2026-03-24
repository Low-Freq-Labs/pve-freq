# TICKET-0003: Lesson #12 Uses Vague "switch port" Instead of Correct Gi1/10 After Session 17 Cable Move

**Priority:** P3 (medium)

## Context

- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 12 (Lessons Learned), Lesson #12 (line 778)
- **DC01.md reference:** Lesson #12 (line 661), Session 17 change log item 6 (line 863)

**ARCHITECTURE.md Lesson #12 states:**
```
To isolate iDRAC to VLAN 2550: configure switch port as trunk (native VLAN 1,
allowed 2550), enable iDRAC VLAN tagging via `racadm set iDRAC.NIC.VLanID 2550`
+ `VLanEnable Enabled`.
```

**DC01.md Lesson #12 states:**
```
To isolate iDRAC to VLAN 2550: configure Gi1/25 as trunk (native VLAN 1,
allowed 2550)...
```

**DC01.md Session 17 item 6 (line 863):**
```
TrueNAS eno1 cable moved: Gi1/25 → Gi1/10.
```

## Diagnosis

DC01.md Lesson #12 still references the old port `Gi1/25`, which is stale after the Session 17 cable move to `Gi1/10`. ARCHITECTURE.md attempted to fix this by making the reference generic ("switch port"), but this introduces vagueness into an operational lesson that should be precise. An operator reading this lesson needs to know exactly which port to configure.

The switch port map in ARCHITECTURE.md Section 4 (line 202) correctly identifies Gi1/10 as the TrueNAS eno1/iDRAC LOM trunk port. But the lesson itself doesn't reference it.

## Recommendations

1. Update Lesson #12 to specify the correct port:

```
R530 has no dedicated iDRAC port -- iDRAC shares eno1's physical port (LOM1).
To isolate iDRAC to VLAN 2550: configure Gi1/10 as trunk (native VLAN 1,
allowed 2550), enable iDRAC VLAN tagging via `racadm set iDRAC.NIC.VLanID 2550`
+ `VLanEnable Enabled`.
```

2. Add a note that this was originally Gi1/25 and moved to Gi1/10 in Session 17, to prevent confusion if someone compares against older documentation.
