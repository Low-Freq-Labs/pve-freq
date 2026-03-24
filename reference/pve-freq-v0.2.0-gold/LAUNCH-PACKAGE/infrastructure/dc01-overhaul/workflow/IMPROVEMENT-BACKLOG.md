# Improvement Backlog -- 5-Worker Workflow

> **Created:** 2026-02-19
> **Author:** Worker #5 (Workflow Tuning Meta-Engineer)
> **Format:** Each item has a Short Name, Description, Affected Worker(s), Suggested Change, and Priority (P1-P4).

---

## P1 -- Must Fix Before Next Orchestration Round

---

### IMP-001: Pre-Change Checkpoint Files

**Description:** Any infrastructure change (network, storage, firewall, cluster) must produce a checkpoint file on disk BEFORE the change is applied. This file documents the change intent, the expected before/after state, the rollback procedure, and the out-of-band access path if the change goes wrong. The file is deleted only after the change is verified successful. If a session crashes mid-change, the checkpoint file guides recovery.

**Affected Worker(s):** Worker #1 (primary), Master Orchestrator (enforcement)

**Suggested Change:** Add this to the Worker #1 system prompt:

```
RULE: Before executing any infrastructure change, you MUST write a file
to infra/WIP-<short-name>.md containing:
  - What is being changed (exact device, interface, config file)
  - Current state (exact values before change)
  - Target state (exact values after change)
  - Rollback procedure (step-by-step to restore current state)
  - Out-of-band access path (how to reach the device if the change breaks connectivity)
  - Verification command (how to confirm the change worked)
Delete this file ONLY after running the verification command successfully.
If you are starting a session and find an existing WIP-*.md file, STOP.
Read it, assess the situation, and report to the Orchestrator before proceeding.
```

**Priority:** P1

---

### IMP-002: High-Risk Operation Gate

**Description:** Certain operations have caused outages historically (LAGG, vmbr0, corosync, pfSense WAN). These must require explicit human confirmation before execution. The Orchestrator prompt should include a hardcoded list of gated operations, and Worker #1 must write a BLOCKED-ON-HUMAN.md file and halt when it encounters one.

**Affected Worker(s):** Worker #1, Master Orchestrator

**Suggested Change:** Add this to both the Orchestrator and Worker #1 system prompts:

```
HIGH-RISK OPERATIONS (require Sonny's explicit approval before execution):
  - Any change to pfSense LAN interface (lagg0, igc3)
  - Any change to vmbr0 address on any Proxmox node
  - Any change to corosync configuration
  - Any change to ZFS pool topology (add/remove vdev, replace disk)
  - Any change to WireGuard VPN endpoint IP
  - Any change to TrueNAS bond0 (LACP configuration)
  - Any change to switch trunk port configuration (Gi1/1, Gi1/2, Gi1/48)

When you encounter one of these operations:
  1. Write workflow/BLOCKED-ON-HUMAN.md explaining what you want to do and why.
  2. STOP and report to the Orchestrator.
  3. Do NOT proceed until Sonny explicitly approves.
```

**Priority:** P1

---

### IMP-003: Dependency-Ordered Worker Scheduling

**Description:** The current approach launches all 5 workers in parallel. Workers #2-4 depend on Worker #1's ARCHITECTURE.md, and Worker #5 depends on all outputs. If Worker #1 has not finished when #2-4 start reading, they either block or operate on incomplete data. Worker #5 sees nothing from #2-4 if they are still running.

**Affected Worker(s):** Master Orchestrator (scheduling), all workers (indirectly)

**Suggested Change:** Modify the Orchestrator prompt to use phased scheduling:

```
SCHEDULING PROTOCOL:
  Phase A: Launch Worker #1 only. Wait for infra/ARCHITECTURE.md to appear on disk.
  Phase B: Launch Workers #2, #3, #4 in parallel. All read Worker #1 output.
           Wait for all three to write their primary output files.
  Phase C: Launch Worker #5. Reads all artifacts from Phases A and B.
  Phase D: Re-launch Worker #1 with instructions to read and address all
           tickets (Worker #2), compliance notes (Worker #3), and tuning
           notes (Worker #4). This closes the feedback loop.
  Phase E: (Optional) Re-launch Worker #5 to assess the quality of the
           feedback integration from Phase D.

If parallelism is required for speed, the Orchestrator MAY launch Workers
#2-5 together but MUST verify that infra/ARCHITECTURE.md exists first.
Worker #5 should note in its output which artifacts were available at
read time and which were missing.
```

**Priority:** P1

---

### IMP-004: Feedback Loop Closure

**Description:** Worker #2 has filed TICKET-0001, but there is no scheduled mechanism for Worker #1 to read and respond to it. Without a response round, tickets accumulate without resolution. The feedback loop is the core value proposition of the multi-worker system.

**Affected Worker(s):** Worker #1 (response), Worker #2 (verification), Master Orchestrator (scheduling)

**Suggested Change:** Add to the Orchestrator prompt:

```
FEEDBACK LOOP:
  After Workers #2-4 complete their review pass:
  1. Re-invoke Worker #1 with the instruction:
     "Read all files in tickets/slop-detector/, compliance/, and tuning/.
      For each ticket or note, either apply the fix or write a rebuttal
      explaining why you disagree. Update ARCHITECTURE.md accordingly.
      After all fixes, increment the version marker at the top of the file."
  2. Re-invoke Worker #2 with the instruction:
     "Re-review ARCHITECTURE.md. For each ticket you filed, verify the fix
      was applied correctly. Close resolved tickets by renaming them to
      TICKET-XXXX-RESOLVED.md. File new tickets for any remaining issues."
```

**Priority:** P1

---

## P2 -- Should Fix Soon

---

### IMP-005: Context Window Budget Management

**Description:** DC01.md is 920+ lines. ARCHITECTURE.md is 808 lines. Memory notes are 50-75 lines each. A worker that must read all of these plus multiple tickets/notes is spending most of its context window on reference material, leaving little room for reasoning. Workers need a strategy for selective reading.

**Affected Worker(s):** All workers, Master Orchestrator

**Suggested Change:** Add to each worker's system prompt:

```
CONTEXT BUDGET:
  Your effective context window is finite. To maximize reasoning capacity:
  1. Read your memory-notes file FIRST (it is a compressed summary).
  2. Read ARCHITECTURE.md section-by-section using line offsets, not all at once.
     Only read sections relevant to your current task.
  3. If you need to verify a specific fact, grep for it rather than re-reading
     entire files.
  4. For Worker #1: ARCHITECTURE.md is YOUR output. You should be able to
     regenerate sections from memory + memory-notes. Do not re-read the
     entire file unless you are doing a consistency check.
```

Additionally, the Orchestrator should consider splitting ARCHITECTURE.md into smaller per-topic files (e.g., `infra/network.md`, `infra/storage.md`, `infra/vms.md`) once it exceeds 1000 lines. This allows workers to read only the sections they need. However, this adds file management overhead, so it should be deferred until the single-file approach becomes a concrete problem.

**Priority:** P2

---

### IMP-006: Scope Enforcement Prompt Hardening

**Description:** Three distinct scopes exist (DC01, GigeNet, Sonny Homework), and the memory notes define them clearly. However, scope leakage is a recurring risk flagged in Worker #5's memory notes. The current scope definitions rely on workers reading and respecting them. A stronger approach would make scope violations syntactically detectable.

**Affected Worker(s):** All workers, Master Orchestrator

**Suggested Change:** Add to every worker's system prompt:

```
SCOPE ENFORCEMENT:
  IN SCOPE: DC01 cluster -- pve01, pve03, TrueNAS (10.25.0.25), Cisco 4948E-F,
            pfSense fw01, VMs 101-105.
  OUT OF SCOPE: pve02 (10.25.0.27), VM 100, VMs 800-899, GigeNet client work,
                Sonny's homework tasks.

  HARD STOP TRIGGERS -- if you find yourself writing about any of these, STOP
  immediately and reassess:
  - Any IP in the 10.25.0.27 range (pve02)
  - VM IDs 100, 420, 800-899
  - The string "GigeNet" in a context other than "colocated at GigeNet"
  - WordPress, cPanel, or hosting migration
  - SABnzbd (VM 100 service)

  If a task legitimately requires touching an out-of-scope item, write a
  BLOCKED-ON-SCOPE.md file explaining the dependency and STOP.
```

**Priority:** P2

---

### IMP-007: Standardized File Naming Conventions

**Description:** The current file naming is mostly consistent (UPPERCASE-WITH-DASHES.md for documents, TICKET-XXXX.md for tickets), but some patterns are not codified. Consistent naming makes it easier for workers to discover each other's output via glob patterns.

**Affected Worker(s):** All workers, Master Orchestrator

**Suggested Change:** Add to the Orchestrator prompt:

```
FILE NAMING CONVENTIONS:
  infra/ARCHITECTURE.md          -- Single architecture document (Worker #1)
  infra/WIP-*.md                 -- Work-in-progress checkpoint files (Worker #1)
  infra/.READY                   -- Signal file: ARCHITECTURE.md is complete
  tickets/slop-detector/TICKET-XXXX.md          -- Open tickets (Worker #2)
  tickets/slop-detector/TICKET-XXXX-RESOLVED.md -- Resolved tickets (Worker #2)
  compliance/WORKER1-NOTES.md    -- Review of Worker #1 output (Worker #3)
  compliance/WORKER2-NOTES.md    -- Review of Worker #2 tickets (Worker #3)
  tuning/WORKER1-NOTES.md        -- Performance notes on architecture (Worker #4)
  tuning/TUNING-PLAYBOOK.md      -- Actionable tuning steps (Worker #4)
  workflow/WORKFLOW-NOTES.md      -- Meta-analysis (Worker #5)
  workflow/IMPROVEMENT-BACKLOG.md -- Prioritized improvements (Worker #5)
  workflow/BLOCKED-ON-HUMAN.md    -- Human decision required (any worker)
  workflow/BLOCKED-ON-SCOPE.md    -- Scope question (any worker)
  TASKBOARD.md                   -- Global task tracking (Orchestrator only)

  Rules:
  - All filenames UPPERCASE with dashes, .md extension.
  - Tickets are numbered sequentially (TICKET-0001, TICKET-0002, ...).
  - Workers MUST NOT create files outside their designated directories.
  - The Orchestrator MUST NOT create files in worker directories.
```

**Priority:** P2

---

### IMP-008: Reduce Duplication Between Memory Notes and ARCHITECTURE.md

**Description:** Worker #1's memory-notes-worker1.md contains a condensed version of the same information now in ARCHITECTURE.md. The memory notes were essential during bootstrap (before ARCHITECTURE.md existed), but now they risk drifting from the authoritative document. Workers #2-5 read the memory notes as their primary reference, which means they may be operating from stale data if the architecture doc is updated.

**Affected Worker(s):** Worker #1 (source of duplication), Workers #2-5 (consumers), Master Orchestrator

**Suggested Change:** Add to the Orchestrator prompt for subsequent rounds:

```
MEMORY NOTES LIFECYCLE:
  - Memory notes (memory-notes-worker*.md) are BOOTSTRAP artifacts.
    They were created to give each worker initial context before
    ARCHITECTURE.md existed.
  - Once ARCHITECTURE.md is marked as complete (infra/.READY exists),
    memory notes are FROZEN. No worker should update them.
  - Workers #2-5 should treat ARCHITECTURE.md as the source of truth
    and memory notes as supplementary context only.
  - If a fact in a memory note contradicts ARCHITECTURE.md, the
    architecture document wins.
  - Worker #1 should NOT update memory-notes-worker1.md when it updates
    ARCHITECTURE.md. The notes are a historical snapshot of initial context.
```

**Priority:** P2

---

## P3 -- Nice to Have

---

### IMP-009: Ticket Actionability Standard

**Description:** TICKET-0001 is well-written, but there is no formal standard for what makes a ticket "actionable." Without a standard, future tickets may be vague ("Section 5 seems wrong") or missing key fields. A template ensures consistent quality.

**Affected Worker(s):** Worker #2 (author), Worker #1 (consumer), Worker #3 (reviewer of tickets)

**Suggested Change:** Add this template to Worker #2's system prompt:

```
TICKET TEMPLATE (mandatory fields):
  # TICKET-XXXX: <Short descriptive title>

  **Priority:** P1 (critical) | P2 (important) | P3 (minor) | P4 (cosmetic)
  **File:** <exact path to the file containing the issue>
  **Section:** <section name or number in the file>
  **Line(s):** <approximate line numbers, if known>

  ## What ARCHITECTURE.md Says
  <exact quote from the document>

  ## What DC01.md / Ground Truth Says
  <exact quote or reference from the source document>

  ## Diagnosis
  <explanation of why this is wrong, vague, or dangerous>

  ## Recommended Fix
  <exact replacement text that Worker #1 can copy-paste>

  ## Verification
  <how to confirm the fix was applied correctly>
```

**Priority:** P3

---

### IMP-010: Human (Sonny) Integration Points

**Description:** The workflow currently has no explicit protocol for when to pause and wait for human input. Some operations inherently require Sonny (pfSense GUI changes, hardware ordering, scope decisions), but this is not codified. Workers may either block indefinitely waiting for input that has not been requested, or proceed without input that was needed.

**Affected Worker(s):** All workers, Master Orchestrator

**Suggested Change:** Add to the Orchestrator prompt:

```
HUMAN INTEGRATION POINTS:
  The following actions CANNOT be completed by any worker and require
  Sonny's direct involvement. When a worker's task depends on one of
  these, it should document the dependency in its output and move on
  to other tasks rather than blocking.

  SONNY-ONLY ACTIONS:
  - pfSense web GUI configuration (firewall rules, NAT, VPN settings)
  - Hardware ordering (PSU replacements, fan assemblies, NIC cards)
  - Bazarr web UI reconfiguration (Sonarr/Radarr connections, subtitle providers)
  - Scope decisions ("should pve02 be brought into scope?")
  - iDRAC password changes (requires physical/console access)
  - Any change requiring root SSH on pfSense
  - Budget/purchasing decisions

  FORMAT: When a worker encounters a SONNY-ONLY dependency, write it as:
  > **BLOCKED ON SONNY:** <one-line description of what is needed>
  in its output file, and continue with other work.

  The Orchestrator should compile all BLOCKED-ON-SONNY items from all
  worker outputs into a summary for Sonny at the end of each round.
```

**Priority:** P3

---

### IMP-011: Session Observability and Logging

**Description:** When a session crashes, there is no record of what the agent was doing at the time. The TASKBOARD records high-level status, but not the granular sequence of actions within a session. Adding structured logging would aid post-crash diagnosis and help Worker #5 analyze workflow efficiency.

**Affected Worker(s):** All workers, Master Orchestrator

**Suggested Change:** Add to each worker's system prompt:

```
OBSERVABILITY:
  At the START of your session, write a single line to your output file:
    > **Session started:** <timestamp> | Task: <current task description>

  At the END of your session (or when you complete a major milestone),
  append:
    > **Session ended:** <timestamp> | Completed: <what was done>

  If you are about to perform a high-risk or long-running operation,
  write a progress marker:
    > **In progress:** <timestamp> | Doing: <what you are doing now>

  These markers help Worker #5 and the Orchestrator understand session
  flow and diagnose crashes.
```

This is lightweight (3 lines per session) and does not require any tooling changes. It simply asks workers to self-report their state transitions.

**Priority:** P3

---

### IMP-012: Source Document Preservation

**Description:** The original CLAUDE.md and DC01.md files are not accessible in the working directory. The memory notes were extracted from them, but the extraction is lossy (920 lines compressed to ~63 lines). If a worker needs to verify a fact against the original source -- as Worker #2 does when checking ARCHITECTURE.md accuracy -- it cannot.

**Affected Worker(s):** Worker #2 (primary -- needs ground truth for verification), all workers

**Suggested Change:** Add to the Orchestrator prompt:

```
SOURCE DOCUMENT PRESERVATION:
  The original source documents (CLAUDE.md, DC01.md, GigeNet.md,
  Sonny-Homework-OutOfScope.md) MUST remain accessible throughout
  the workflow. Options:
  1. Keep copies in dc01-overhaul/source/ (read-only reference).
  2. If they are in a parent directory, document their exact paths
     in TASKBOARD.md so workers can find them.
  3. NEVER delete or move source documents until the workflow is
     complete and all workers confirm they no longer need them.

  Worker #2 in particular MUST have access to DC01.md to verify
  ARCHITECTURE.md accuracy. Without it, slop detection is limited
  to internal consistency checks only.
```

**Priority:** P3

---

## P4 -- Long-Term / Deferred

---

### IMP-013: Architecture Document Versioning

**Description:** ARCHITECTURE.md will be updated multiple times across feedback rounds. Without version markers, it is impossible to know which version a reviewer assessed. Worker #2 might file a ticket against v1, Worker #1 fixes it in v2, but Worker #3 reviewed v1 and its compliance notes reference the old text.

**Affected Worker(s):** Worker #1 (author), Workers #2-4 (reviewers)

**Suggested Change:** Add a version header to ARCHITECTURE.md:

```
At the top of ARCHITECTURE.md, maintain:
  > **Version:** 1.0 (initial draft)
  > **Changelog:**
  > - v1.0 (2026-02-19): Initial architecture document from DC01.md
  > - v1.1 (2026-02-19): Applied TICKET-0001 fix (Lesson #2 correction)

When a reviewer files a ticket, it should reference the version:
  "Reviewed against ARCHITECTURE.md v1.0"

When Worker #1 applies fixes, it increments the version and logs
the change. This creates an audit trail.
```

**Priority:** P4

---

### IMP-014: Automated Consistency Checks

**Description:** Worker #2 manually identifies contradictions (like TICKET-0001). Some of these checks could be automated with simple scripts -- for example, searching for `vmbr0.2550` (without the `v`) in ARCHITECTURE.md, or verifying that all IPs mentioned in the VM table match the VLAN map. This does not replace Worker #2's judgment but catches low-hanging fruit.

**Affected Worker(s):** Worker #2 (assisted by scripts), Worker #1 (benefits from automated validation)

**Suggested Change:** Add to scripts/README.md:

```
PLANNED SCRIPTS:
  - consistency-check.sh: Grep ARCHITECTURE.md for known-bad patterns:
    - "vmbr0.2550" (should be vmbr0v2550)
    - "vmbr0.25" (should be vmbr0v25 on pve03 if used as host IP)
    - ":latest" in any Docker image reference
    - Any IP in the 10.25.0.27 range (pve02, out of scope)
    - "VM 100" or "SABnzbd" outside the Out of Scope section
  - ip-audit.sh: Extract all IPs from ARCHITECTURE.md and cross-reference
    against the VLAN map to flag IPs that don't belong to their stated VLAN.

  These scripts are recommendations for future implementation. They should
  be run by the Orchestrator before launching Worker #2 to pre-screen for
  trivial issues.
```

**Priority:** P4

---

### IMP-015: Multi-Round Convergence Metric

**Description:** The workflow is designed to iterate (Worker #1 writes, Workers #2-4 review, Worker #1 fixes, repeat). But there is no defined convergence criterion -- when is the document "good enough" to stop iterating? Without this, the workflow could loop indefinitely or stop too early.

**Affected Worker(s):** Master Orchestrator, Worker #5 (measures convergence)

**Suggested Change:** Add to the Orchestrator prompt:

```
CONVERGENCE CRITERIA:
  The review-fix cycle stops when ALL of the following are true:
  1. Worker #2 has zero open P1 or P2 tickets.
  2. Worker #3 has flagged no new CRITICAL or HIGH compliance findings
     in the latest round.
  3. Worker #4's tuning recommendations have been either applied or
     explicitly deferred (with documented rationale).
  4. Worker #5 confirms no systemic workflow issues remain.

  If after 3 rounds the criteria are not met, escalate to Sonny with
  a summary of unresolved items.
```

**Priority:** P4

---

## Summary Table

| ID | Short Name | Priority | Affected Workers |
|---|---|---|---|
| IMP-001 | Pre-Change Checkpoint Files | P1 | #1, Orchestrator |
| IMP-002 | High-Risk Operation Gate | P1 | #1, Orchestrator |
| IMP-003 | Dependency-Ordered Scheduling | P1 | Orchestrator, all |
| IMP-004 | Feedback Loop Closure | P1 | #1, #2, Orchestrator |
| IMP-005 | Context Window Budget | P2 | All |
| IMP-006 | Scope Enforcement Hardening | P2 | All |
| IMP-007 | File Naming Conventions | P2 | All |
| IMP-008 | Reduce Memory Notes Duplication | P2 | #1, #2-5, Orchestrator |
| IMP-009 | Ticket Actionability Standard | P3 | #2, #1, #3 |
| IMP-010 | Human Integration Points | P3 | All |
| IMP-011 | Session Observability | P3 | All |
| IMP-012 | Source Document Preservation | P3 | #2, all |
| IMP-013 | Architecture Versioning | P4 | #1, #2-4 |
| IMP-014 | Automated Consistency Checks | P4 | #2, #1 |
| IMP-015 | Multi-Round Convergence Metric | P4 | Orchestrator, #5 |

---

## Post-Incident Additions (Session 21)

---

### IMP-016: Mandatory Pre-Change Baseline Capture

**Description:** Session 20 applied LACP changes to pfSense and the switch without documenting the exact pre-change state. When things broke, recovery required reconstructing the baseline from memory and live probing. Every infrastructure change must capture a "before" snapshot — not just a rollback plan, but the actual running-state output of the relevant commands.

**Affected Worker(s):** Worker #1 (execution), Master Orchestrator (enforcement)

**Suggested Change:** Add to the Worker #1 system prompt, immediately after the IMP-001 Pre-Change Checkpoint rule:

```
PRE-CHANGE BASELINE:
  Before ANY infrastructure change, capture and save the CURRENT running state
  to the WIP checkpoint file. This is NOT the same as a rollback plan — this is
  the actual command output showing what the system looks like RIGHT NOW.

  Examples:
  - Before changing pfSense LAGG: save output of `ifconfig lagg0`, `ifconfig -v lagg0`
  - Before changing switch port-channel: save output of `show etherchannel summary`,
    `show run int Gi1/47`, `show run int Gi1/48`, `show run int Po2`
  - Before changing VLANs: save output of `show vlan brief`
  - Before changing config.xml: save a timestamped backup with
    `cp /cf/conf/config.xml /cf/conf/config.xml.backup-<session-tag>`

  The baseline MUST be saved to disk BEFORE the first change command is executed.
  If a session crashes, the next session can compare live state against the baseline
  to understand exactly what changed.
```

**Priority:** P1

---

### IMP-017: Credential Detection and Sanitization Rule

**Description:** Session 20's LACP-LAGG-SESSION-NOTES.md contained plaintext passwords. The user also pasted credentials directly in chat during Session 21. While CLAUDE.md says "no passwords in logs," there is no active enforcement mechanism. The master prompt should include an explicit detection-and-scrub directive.

**Affected Worker(s):** Master Orchestrator (primary), all workers

**Suggested Change:** Add to the Master Orchestrator prompt, in the Global Rules section:

```
CREDENTIAL HYGIENE (HARD RULE — NO EXCEPTIONS):
  1. NEVER write passwords, API keys, tokens, or secrets to ANY file.
     Use "<VAULT>" or "<pw>" as placeholder text.
  2. If the user pastes credentials in chat, acknowledge them for the
     current SSH/API call but NEVER echo them back or write them to disk.
  3. Before writing ANY handoff document, session notes, or memory file,
     scan the content for patterns that look like credentials:
     - Strings following "password", "passwd", "secret", "token", "key"
     - sshpass -p '<anything>'
     - Any string that appears to be a password in command examples
     Replace all matches with "<VAULT>" and add a note:
     "Credentials: Refer to Sonny's password vault (VM 802)"
  4. If you discover credentials in an EXISTING file, flag it immediately
     as a SECURITY FINDING and sanitize the file.
  5. After sanitization, recommend password rotation to Sonny.
```

**Priority:** P1

---

### IMP-018: Diagnosis Confidence Labeling

**Description:** Session 20 documented the "duplicate `<members>` tags" finding as a definitive root cause. Session 21 proved it was wrong — the empty tag belonged to the WireGuard interface group. If Session 20 had labeled the finding with a confidence level, Session 21 would have been more appropriately skeptical. All diagnostic findings should carry an explicit confidence marker.

**Affected Worker(s):** Worker #1 (infrastructure diagnosis), Master Orchestrator (enforcement)

**Suggested Change:** Add to the Worker #1 and Master Orchestrator system prompts:

```
DIAGNOSIS CONFIDENCE LABELING:
  When documenting any root cause, failure mode, or diagnostic finding,
  ALWAYS include a confidence label:

  - CONFIRMED: Verified by direct observation and reproduced or explained
    by first principles. Safe to act on.
  - PROBABLE: Consistent with observed symptoms and supported by evidence,
    but not conclusively verified. Act on it but monitor closely.
  - HYPOTHESIS: Plausible explanation that has NOT been verified. Do NOT
    act on this without further investigation.
  - DISPROVEN: Previously hypothesized but now known to be wrong.
    Document what disproved it and what the actual cause was.

  Format: "[CONFIRMED]", "[PROBABLE]", "[HYPOTHESIS]", or "[DISPROVEN]"
  placed immediately after the finding statement.

  Example:
    "Root cause: LACP key mismatch between igc2 (0x8003) and igc3 (0x01CB) [PROBABLE]"
    "Root cause: Duplicate <members> tags in config.xml [DISPROVEN — empty tag
     was for WireGuard interface group, not LAGG]"
```

**Priority:** P1

---

### IMP-019: Incident Record Creation at Outage Time

**Description:** The formal incident record (INC-001) was created in Session 21 — one full session AFTER the outage occurred in Session 20. By the time the record was written, key details had to be reconstructed from memory and incomplete notes. Incident records should be created immediately when an outage is detected, even if incomplete.

**Affected Worker(s):** Master Orchestrator (enforcement), Worker #1 (creation)

**Suggested Change:** Add to the Master Orchestrator prompt:

```
INCIDENT MANAGEMENT:
  When ANY of the following occur, IMMEDIATELY create an incident record
  in incidents/INC-XXX-<short-name>.md:
  - Production service becomes unreachable
  - Unplanned network outage (any VLAN)
  - Data loss or corruption detected
  - Hardware failure alert
  - Security incident

  The initial record does NOT need to be complete. Use this template:
    # INC-XXX: <Short Description>
    **Status:** ACTIVE
    **Opened:** <session tag>
    **Severity:** CRITICAL | HIGH | MEDIUM | LOW
    **Affected Systems:** <list>
    **Symptoms:** <what is broken, as observed>
    **Initial Actions:** <what has been tried so far>

  Fill in Root Cause, Resolution, and Lessons Learned as they become known.
  Do NOT wait until the incident is resolved to create the record.
```

**Priority:** P2

---

### IMP-020: Platform Syntax Reference

**Description:** Two commands failed in Session 21 due to platform-specific syntax: `sed -i` (FreeBSD requires `sed -i ''`) and `no channel-group 2` (Cisco IOS requires `no channel-group 2 mode active`). These are not edge cases — they will recur every time pfSense or the switch is configured. A quick-reference section in the master prompt would prevent repeat failures.

**Affected Worker(s):** Worker #1 (primary consumer), Master Orchestrator

**Suggested Change:** Add to the Worker #1 system prompt or to CLAUDE.md's Infrastructure section:

```
PLATFORM SYNTAX GOTCHAS:
  pfSense (FreeBSD):
  - sed in-place: `sed -i '' 's|old|new|' file` (NOT `sed -i 's|old|new|' file`)
  - pkg install, not apt install
  - ifconfig, not ip (no iproute2)
  - /cf/conf/config.xml is the persistent config (survives reboot)
  - `ifconfig lagg0 laggproto <proto>` changes LAGG protocol live

  Cisco IOS (4948E-F, IOS 15.2):
  - Remove channel-group: `no channel-group <N> mode active` (mode keyword required)
  - errdisable: Cannot disable detection, only enable auto-recovery:
    `errdisable recovery cause channel-misconfig`
  - `write memory` to save (not `copy run start` — both work but `wr` is shorter)
  - SSH requires legacy algorithms: KexAlgorithms=+diffie-hellman-group14-sha1,
    HostKeyAlgorithms=+ssh-rsa, PubkeyAcceptedKeyTypes=+ssh-rsa
```

**Priority:** P2

---

### IMP-021: Incident Response Mode (Reduced Worker Set)

**Description:** Session 21 was dominated by Worker #1 infrastructure work. Workers #2-4 had no new architecture artifacts to review and produced no output. Running all 5 workers during an incident response session wastes context window and orchestration overhead. The master prompt should support an "incident response mode" that activates only the workers needed.

**Affected Worker(s):** Master Orchestrator (scheduling)

**Suggested Change:** Add to the Master Orchestrator prompt:

```
INCIDENT RESPONSE MODE:
  When the session's primary objective is incident response (active outage,
  recovery from failed change, emergency fix), use a reduced worker set:

  - Worker #1 (Infra Architect): ACTIVE — executes diagnosis and fix
  - Worker #5 (Workflow Meta): ACTIVE — observes and documents for post-incident review
  - Workers #2, #3, #4: STANDBY — only activated if Worker #1 produces new
    architecture artifacts that need review

  This reduces bootstrap overhead from 5 workers to 2, allowing more context
  window for the actual incident work.

  Return to full 5-worker mode when the session's primary objective is
  planned work (overhaul phases, new deployments, documentation).
```

**Priority:** P2

---

## Updated Summary Table

| ID | Short Name | Priority | Affected Workers |
|---|---|---|---|
| IMP-001 | Pre-Change Checkpoint Files | P1 | #1, Orchestrator |
| IMP-002 | High-Risk Operation Gate | P1 | #1, Orchestrator |
| IMP-003 | Dependency-Ordered Scheduling | P1 | Orchestrator, all |
| IMP-004 | Feedback Loop Closure | P1 | #1, #2, Orchestrator |
| IMP-005 | Context Window Budget | P2 | All |
| IMP-006 | Scope Enforcement Hardening | P2 | All |
| IMP-007 | File Naming Conventions | P2 | All |
| IMP-008 | Reduce Memory Notes Duplication | P2 | #1, #2-5, Orchestrator |
| IMP-009 | Ticket Actionability Standard | P3 | #2, #1, #3 |
| IMP-010 | Human Integration Points | P3 | All |
| IMP-011 | Session Observability | P3 | All |
| IMP-012 | Source Document Preservation | P3 | #2, all |
| IMP-013 | Architecture Versioning | P4 | #1, #2-4 |
| IMP-014 | Automated Consistency Checks | P4 | #2, #1 |
| IMP-015 | Multi-Round Convergence Metric | P4 | Orchestrator, #5 |
| **IMP-016** | **Pre-Change Baseline Capture** | **P1** | **#1, Orchestrator** |
| **IMP-017** | **Credential Detection & Sanitization** | **P1** | **Orchestrator, all** |
| **IMP-018** | **Diagnosis Confidence Labeling** | **P1** | **#1, Orchestrator** |
| **IMP-019** | **Incident Record at Outage Time** | **P2** | **Orchestrator, #1** |
| **IMP-020** | **Platform Syntax Reference** | **P2** | **#1, Orchestrator** |
| **IMP-021** | **Incident Response Mode** | **P2** | **Orchestrator** |
| **IMP-MIGRATION-001** | **3-Worker Migration Monitoring** | **P3** | **#3, Orchestrator** |

---

## Post-Migration Addition (2026-02-20)

---

### IMP-MIGRATION-001: Monitor 3-Worker System

**Description:** Migration from 5-worker to 3-worker system completed 2026-02-20. Monitor for 3-5 sessions to validate the consolidation works correctly.

**Watch for:**
- Worker #1 scope too broad? Does it struggle with both infra + tuning in one pass?
- Worker #2 quality gate working? Are slop tickets and compliance findings still being caught?
- Warm start working correctly? Any cases where full boot should have triggered but didn't?
- Any workflow regressions compared to the 5-worker system?

**Affected Worker(s):** Worker #3 (primary monitor), Master Orchestrator

**Status:** OPEN
**Priority:** P3
