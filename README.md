# freq-dev — FREQ v2.0 Python Core Builder

## What This Is

An autonomous Claude Code specialist environment for building PVE FREQ v2.0 — a Python rewrite of the 17,720-line bash datacenter management platform. This specialist has full SSH access to a controlled test zone (VMs 5000-5999) and will build, deploy, test, destroy, and rebuild until every command and menu works.

## How to Launch

```bash
cd /home/freq-ops/dev-ops/rick
claude
```

That's it. Claude Code reads `CLAUDE.md` (the mission), `.claude/settings.json` (permissions + hooks), and the SessionStart hook verifies the constitution hash. The agent knows what to build, where to build it, and how to test it.

## What It Does

1. Reads the bash FREQ source at `src/pve-freq/` (55 commands, 39 libs)
2. Builds a Python equivalent with 1:1 command parity
3. Deploys to VM 999 (10.25.255.50) via SSH
4. Tests against live DC01 infrastructure
5. When ready: destroys VM 999, recreates clean, runs `freq init`, verifies everything works
6. Repeats until all 14 menus have working data

## Safety

| Zone | Access |
|------|--------|
| VMs 5000-5999 on pve02 | FULL (create, destroy, clone, modify) |
| VM 999 (Nexus) | Local dev + build target |
| Production VMs (0-899) | BLOCKED by PreToolUse hook |
| Production credentials | BLOCKED by deny rules |
| Live fleet (read-only) | ALLOWED (SSH for data gathering) |

## Backups (taken before this was created)

- **vzdump:** VM 999 full snapshot on pve01 local storage (1.21GB, 2026-03-13)
- **Source:** `/mnt/obsidian/backup/freq-v1-pre-rebuild/pve-freq-full-backup-s156.tar.gz`
- **Snapshot:** VM 999 has PVE snapshot `freq-snap-20260309-231551`

## Recovery

If something goes wrong:
```bash
# Restore VM 999 from snapshot (route through JARVIS for root ops)
sudo -u freq-ops ssh -n -o StrictHostKeyChecking=no freq-ops@10.25.255.27 'sudo qm rollback 999 freq-snap-20260309-231551'

# Or just read the break-glass doc
cat /home/freq-ops/dev-ops/rick/docs/BREAK-GLASS.md
```

## Completion Gate

The session is NOT done until:
- [ ] `freq init` deploys to a clean Debian 13 VM
- [ ] All 55 commands have Python implementations
- [ ] All 14 TUI menus render with real data
- [ ] VM 999 was destroyed, recreated, deployed, and verified

## Files

| File | Purpose |
|------|---------|
| `CLAUDE.md` | Mission + rules + architecture + build order |
| `.claude/settings.json` | Permissions + hooks |
| `.claude/skills/` | /ticket, /checkpoint, /preflight, /test |
| `src/pve-freq/` | Bash v1.0.0 reference (17,720 lines) |
| `cold-storage/` | Constitution hash + backup |
| `docs/BREAK-GLASS.md` | Emergency procedures |
| `docs/BOOTSTRAP-SCOPE-LOCK.md` | What was done to set this up |
| `~/archive/` | Ghost archive (old FREQ versions, mailbox, workspaces) |
