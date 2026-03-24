# TICKET-0002: Container Image Pinning Stated as Current Standard but Is Only a TODO in DC01.md

**Priority:** P2 (high)

## Context

- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 7 (Services), Container Standard table (line 494)
- **DC01.md reference:** Container Standard (line 355-363), Cluster Hardening task list (line 607)

**ARCHITECTURE.md states (line 494):**
```
| Image pinning | Pin specific versions, no `:latest` |
```

**DC01.md Container Standard (lines 355-363) says:**
```
| Images | LinuxServer.io (LSIO) preferred |
```
No mention of version pinning as a current standard.

**DC01.md Cluster Hardening (line 607) says:**
```
- [ ] **Docker security** — No privileged unless required, pin image versions
```
This is an unchecked TODO item.

## Diagnosis

Worker #1 promoted an aspirational hardening task to the status of an established operational standard. This is AI slop -- making the document look more complete than reality. If an operator reads the Container Standard table, they will believe image pinning is already enforced across all compose files. In reality, no audit has been performed and the compose files may well use `:latest` tags.

The ARCHITECTURE.md Security Posture section (line 656) partially acknowledges this ("LSIO images preferred, version pinning is the standard but not audited"), but the Container Standard table presents it as a plain fact without qualification.

## Recommendations

1. Remove the `Image pinning` row from the Container Standard table, or change it to:

```
| Image pinning | **NOT YET ENFORCED** -- Pin specific versions, no `:latest` (hardening TODO) |
```

2. Ensure Section 9 (Security Posture) and Section 7 (Container Standard) are consistent. If one says it's a TODO, the other must not present it as done.

3. An actual audit of all compose files for `:latest` tags should be filed as a separate task.
