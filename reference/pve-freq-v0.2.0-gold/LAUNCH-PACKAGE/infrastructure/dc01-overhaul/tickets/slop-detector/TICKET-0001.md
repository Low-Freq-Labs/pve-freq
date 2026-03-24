# TICKET-0001: Lesson #2 Contradicts Lessons #13/#14 -- Stale vmbr0.2550 Reference

**Priority:** P1 (critical)
**Status:** RESOLVED — S028-20260220

## Context

- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 12 (Lessons Learned), Lesson #2 (line 748)
- **DC01.md reference:** Lesson #2 (line 698), Lesson #13 (line 730), Lesson #14 (line 733)

**ARCHITECTURE.md Lesson #2 stated:**
```
Management VLAN belongs on sub-interface `vmbr0.2550`, NEVER on vmbr0 itself.
```

**ARCHITECTURE.md Lessons #13 and #14 state:**
```
Fix: assign host IPs to the Proxmox VLAN bridge (e.g., `vmbr0v2550`) instead.
```

## Diagnosis

Lesson #2 explicitly told operators to put management IPs on `vmbr0.2550`. Lessons #13 and #14 explain that `vmbr0.2550` is broken due to the kernel split-brain sub-interface bug and that `vmbr0v2550` must be used instead. An operator following Lesson #2 would recreate the exact failure that Session 17 fixed.

This contradiction existed in the DC01.md ground truth as well, but the ARCHITECTURE.md rewrite should have reconciled it.

The Node Interface Table (Section 3) correctly shows `vmbr0v2550` for both pve01 and pve03, so the table and the lesson directly contradicted each other within the same document.

## Resolution (S028-20260220)

All three recommendations applied to BOTH files:

1. **ARCHITECTURE.md Lesson #2:** Amended to use correct terminology ("Proxmox VLAN bridge `vmbr0v2550`"), added explicit warning against `vmbr0.2550`, added cross-reference to Lessons #13/#14, added DANGER callout.

2. **DC01.md Lesson #2:** Same fix applied to the source of truth document.

3. Stale slop-detector HTML comment replaced with resolution note.

**Backups:** `~/backup-ARCHITECTURE-S028/` (both ARCHITECTURE.md and DC01.md originals)
