# Phase 3 Bootstrap — Scope Lock

> **Purpose:** Define exactly what the bootstrap session does. No scope creep. Practice the discipline before the specialist exists.
> **Status:** NEARLY COMPLETE — local build done, source deployed, git initialized. Screen + live hook tests remain.
> **Per:** STRESS-TEST ISSUE-09 (bootstrap paradox)

---

## What This Is

Phase 3 is "The Last JARVIS Session." JARVIS performs the infrastructure setup as a one-time, scoped exception. After Phase 3 completes, JARVIS steps down from FREQ development. freq-dev takes over.

This is a ceremony, not a gradual transition.

---

## Scope — LOCKED

### DONE

- [x] Create `/home/jarvis-ai/rick/` directory structure
- [x] Write CLAUDE.md constitution (B1-B14, F1-F8)
- [x] Write `.claude/settings.json` (permission denies + hooks)
- [x] Write 4 Skills: /ticket, /checkpoint, /preflight, /test
- [x] Initialize cold storage (hash CLAUDE.md, backup v1, changelog)
- [x] Write MEMORY.md (auto-memory seed)
- [x] Write BREAK-GLASS.md (ISSUE-01 prerequisite)
- [x] Deploy warm backup to Obsidian
- [x] Write this scope-lock document (ISSUE-09 prerequisite)
- [x] Copy FREQ v1.0.0 source from VM 999 to `src/` (17,720 lines confirmed)
- [x] Remove SSH private key from dev copy (security)
- [x] Add deny rules for data/keys and data/vault
- [x] Git init with clean first commit (63 files, 18,518 lines)
- [x] Git second commit: security fix (key removal + deny rules)
- [x] Verify SessionStart hook logic (hash match + mismatch both tested)

### PENDING

- [ ] Live test: Launch Claude Code in freq-dev project directory
  - Method: `cd /home/jarvis-ai/rick && claude`
  - Verify: SessionStart hook fires, constitution verified message appears
  - Test: Try SSH in session → should be BLOCKED by both deny + PreToolUse hook
  - Test: Try reading src/ → should be ALLOWED
  - Test: Invoke each skill (/ticket, /checkpoint, /preflight, /test)

- [ ] Configure GNU screen (test first)
  - Method: `screen -S FREQDEV`, verify Claude Code works inside screen
  - If screen breaks Claude: fall back to tmux
  - Multiuser: `ctrl+a :multiuser on`, `ctrl+a :acl add sonny-aif`

### OUT OF SCOPE (do NOT do during bootstrap)

- Writing FREQ code
- Modifying FREQ source
- Running the debug matrix
- Creating additional specialists
- Obsidian cleanup
- Lab environment setup
- Anything on VM 999 besides copying source

---

## Verification Checklist

```
[x] rick/ structure matches plan (21 dirs, 65 files)
[x] CLAUDE.md hash matches cold-storage hash (c1bdb3ef...)
[x] Warm backup exists in Obsidian (/mnt/obsidian/backup/jarvis-projects/freq-dev/)
[x] SessionStart hook logic verified (match + mismatch both pass)
[  ] Live SessionStart hook test (launch actual Claude session)
[  ] PreToolUse hook blocks SSH/sudo (live test)
[  ] All 4 Skills are invocable (live test)
[x] Source code present in src/ (17,720 lines across 39 libs)
[x] Git repo initialized (2 commits, master branch)
[  ] Screen session works with Claude Code (or tmux fallback documented)
[x] BREAK-GLASS.md exists and is accurate
[x] SSH private key removed from dev environment
[x] data/keys and data/vault denied in settings.json
```

## Rollback

If anything goes wrong during bootstrap:
```bash
# Nuclear option — remove everything and start over
rm -rf /home/jarvis-ai/rick/
# Obsidian backup survives at /mnt/obsidian/backup/jarvis-projects/freq-dev/
```

---

*This scope is LOCKED. Changes require explicit operator approval and a note in this document.*
*Last updated: 2026-03-13 S156 — source deployed, git initialized, security hardened.*
