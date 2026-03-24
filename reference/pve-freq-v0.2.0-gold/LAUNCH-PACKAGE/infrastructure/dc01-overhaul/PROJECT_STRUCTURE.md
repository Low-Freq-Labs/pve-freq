# DC01 Overhaul — Project Structure

> **Purpose:** DC01 cluster management, LACP/LAGG incident response, and infrastructure overhaul workflow.
> **Maintained by:** 5-agent Claude Code team (Master Orchestrator + Workers 1-5)

## Directory Layout

| Directory | Purpose |
|-----------|---------|
| `infra/` | Infrastructure documentation and architecture |
| `infra/proxmox/` | Proxmox node configs, interface examples |
| `infra/truenas/` | TrueNAS NFS export definitions, mount examples |
| `scripts/` | Operational scripts (health checks, backups, diagnostics) |
| `tickets/` | Issue tracking |
| `tickets/slop-detector/` | AI Slop Detector findings (Worker #2) |
| `compliance/` | SOC compliance findings and remediation plans (Worker #3) |
| `tuning/` | Performance tuning recommendations and playbooks (Worker #4) |
| `workflow/` | Workflow improvement notes and backlog (Worker #5) |
| `incidents/` | Active and resolved incident documentation |
| `logs/` | Session logs and audit trails |

## Key Files

| File | Purpose |
|------|---------|
| `TASKBOARD.md` | Central task tracking for all 5 workers |
| `CONSOLIDATED-FINDINGS.md` | Master reference — all worker findings merged |
| `PROJECT_STRUCTURE.md` | This file — project layout reference |
| `infra/ARCHITECTURE.md` | Full DC01 architecture documentation |

## How Workers Use These Folders

- **Worker #1 (Infra Architect):** Owns `infra/`, reads all memory files, produces architecture docs
- **Worker #2 (Slop Detector):** Reviews Worker #1 output, files tickets in `tickets/slop-detector/`
- **Worker #3 (SOC Compliance):** Reviews all artifacts, writes findings to `compliance/`
- **Worker #4 (Performance):** Writes tuning recommendations to `tuning/`
- **Worker #5 (Workflow Meta):** Observes all workers, writes to `workflow/`
- **Orchestrator:** Maintains `TASKBOARD.md`, `CONSOLIDATED-FINDINGS.md`, coordinates all workers

## Memory Sources (LOCAL-FIRST, SMB-FALLBACK)

1. `~/CLAUDE.md` — Jarvis's Memory (symlinked to SMB share)
2. `~/Jarvis & Sonny's Memory/DC01.md` — Full system inventory
3. `~/Jarvis & Sonny's Memory/GigeNet.md` — Client issue log
4. `~/Jarvis & Sonny's Memory/Sonny-Homework-OutOfScope.md` — Out-of-scope guides
5. `~/LACP-LAGG-SESSION-NOTES.md` — Session 20 LACP troubleshooting notes (LOCAL)
