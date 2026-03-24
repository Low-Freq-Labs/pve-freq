# Break Glass — Emergency Operations Procedure

> **Purpose:** When the specialist system is broken, here's how to operate while you fix it.
> **Audience:** Sonny (operator)
> **Created:** 2026-03-13 (Phase 3 prerequisite, per STRESS-TEST ISSUE-01)

---

## When To Use This

- SessionStart hook blocks ALL sessions (hash check bug or corrupted hash file)
- Cold storage hash file corrupted on SMB share
- Claude Code update changes hook behavior
- Model update degrades constitution adherence
- Screen session crashes mid-operation with half-completed work

---

## Scenario 1: Constitution Hash Mismatch (Session Won't Start)

**Symptom:** `CONSTITUTION MISMATCH. Expected: X Got: Y. REFUSING TO OPERATE.`

**If the change was authorized (you edited CLAUDE.md intentionally):**
```bash
cd /home/jarvis-ai/rick
sha256sum CLAUDE.md | cut -d' ' -f1 > cold-storage/claude-md-hash.sha256
# Add entry to cold-storage/CHANGELOG.md explaining the change
# Restart the session
```

**If the change was NOT authorized (corruption, rogue edit):**
```bash
cd /home/jarvis-ai/rick
# Restore from cold storage backup
cp cold-storage/CLAUDE.md.v1 CLAUDE.md
# Or restore from Obsidian warm backup
cp /mnt/obsidian/backup/jarvis-projects/freq-dev/CLAUDE.md .
# Restart the session
```

---

## Scenario 2: Cold Storage Corrupted

**Symptom:** Hash file empty, corrupted, or SMB share unmounted.

```bash
# Check if Obsidian is mounted
mountpoint -q /mnt/obsidian && echo "OK" || echo "MOUNT DOWN"

# If mount is down, remount
sudo mount -t cifs //10.25.25.25/smb-share/public/DB_01 /mnt/obsidian \
  -o credentials=/home/jarvis-ai/jarvis_prod/credentials/smb-credentials,vers=3.0,uid=3004,gid=3004

# Regenerate hash from current (verified) CLAUDE.md
cd /home/jarvis-ai/rick
sha256sum CLAUDE.md | cut -d' ' -f1 > cold-storage/claude-md-hash.sha256
```

---

## Scenario 3: Specialist System Completely Broken

**Symptom:** Can't start any specialist session. Hooks broken. Claude Code acting weird after update.

**Fallback: Use JARVIS directly.**

The old way still works. JARVIS in `jarvis_prod/` has full infrastructure access:
```bash
cd /home/jarvis-ai/jarvis_prod
claude   # Opens JARVIS with the original CLAUDE.md and full SSH access
```

JARVIS can:
- SSH to all hosts
- Run quick-check.sh
- Fix infrastructure issues
- Read/write memory files

JARVIS cannot (and should not):
- Write FREQ code (that's freq-dev's job)
- Modify the specialist system without operator approval

**This is the fire escape. Use it to fix the specialist system, then go back to normal.**

---

## Scenario 4: Screen Session Crash Mid-Operation

**Symptom:** Terminal closed, SSH dropped, screen died.

```bash
# Check if screen session still exists
screen -list

# If session exists, reattach
screen -r FREQDEV

# If session is dead, check for unsaved work
cd /home/jarvis-ai/rick
git status                    # Check for uncommitted changes
cat journal/CW-*.md | tail -20  # Read last journal checkpoints
ls tickets/open/              # Check for tickets filed before crash
```

The CW journal (Rule B13) is the recovery point. Everything up to the last `/checkpoint` is captured. Read the journal, understand where the session was, start a new session.

---

## Scenario 5: Model Degradation (Constitution Not Followed)

**Symptom:** Specialist ignores rules, drifts from constitution, stops using /ticket or /checkpoint.

1. Export the session: `/export problem-session.md`
2. Review against the 22 rules — which ones were violated?
3. Options:
   - Reword the violated rules to be more explicit
   - Add examples to the CLAUDE.md for the specific failure mode
   - Try a different model (Sonnet vs Opus)
   - Add a PreToolUse hook that specifically checks for the violation pattern
4. Update CLAUDE.md → update hash → update CHANGELOG → test again

---

## Recovery Priority

| Priority | Action |
|----------|--------|
| 1 | Stop. Don't make it worse. |
| 2 | Check the journal for last known good state |
| 3 | Check git for uncommitted changes |
| 4 | Restore from cold storage if constitution corrupted |
| 5 | Fall back to JARVIS if specialist system is broken |
| 6 | Fix the root cause |
| 7 | Update this document with the new failure mode |

---

*This document must exist before Phase 3 execution. STRESS-TEST ISSUE-01.*
