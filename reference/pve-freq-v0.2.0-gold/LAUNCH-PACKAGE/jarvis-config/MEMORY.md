# JARVIS Auto-Memory — v2.0

## First Actions (every session)

1. `bash ~/jarvis_prod/scripts/quick-check.sh all` — 15-second fleet health check. Do this BEFORE any manual probing.
2. Read `memory/index.md` — find the right file for any query.
3. Read `memory/active-issues.md` — know what's open.
4. Check Obsidian: `mountpoint -q /mnt/obsidian && echo "OK" || echo "MOUNT DOWN"`. If down: `sudo mount -t cifs //10.25.25.25/smb-share/public/DB_01 /mnt/obsidian -o credentials=$HOME/jarvis_prod/credentials/smb-credentials,vers=3.0,uid=3004,gid=3004`
5. **Temp creds check:** `ls ~/temp-creds/` — if ANY files exist, **immediately notify Sonny**: "SECURITY: Temp credentials present in ~/temp-creds/: [list files]. Keep or purge?" This is a red flag by design.
6. Read user's request. Begin work.

Deep-dive only what quick-check flags. Do NOT manually replicate what the script covers.

## Permissions — Key Gotchas

**Full reference:** `/mnt/obsidian/DC01/guides/jarvis-ai-permissions.md` — read before guessing permissions.

- `sudo cat` reads ANY file on all Linux hosts + pfSense. Most powerful tool.
- `sudo journalctl` requires `--no-pager` flag (sudoers enforces it).
- Docker VMs: `sudo docker exec/stop/start/kill/compose up -d/down/pull` on all (vm101-104, vm201, vm202, vm301). `sudo tee /opt/dc01/*` for config writes.
- pfSense: `ifconfig` works WITHOUT sudo. `2>/dev/null` inside SSH strings breaks tcsh — redirect OUTSIDE only. Sudoers wipe on reboot/update.
- TrueNAS: `zpool` not in user PATH — must use `sudo zpool`. Sudoers in middleware DB (permanent).
- PVE: `/etc/pve/` files need `sudo cat` (root:www-data 640).

## Shell & API Environment

- Bash tool runs non-interactive shells. `.bashrc` NOT sourced.
- Load API env: `source ~/jarvis_prod/credentials/api-keys.env 2>/dev/null` — use `source`, NOT `eval+cat` (preflight hook blocks `cat` on credential files).
- For python3 subprocesses: `export $(cat ~/jarvis_prod/credentials/api-keys.env | grep -v '^#' | xargs) 2>/dev/null`
- **Temp credentials:** Save to `~/temp-creds/<purpose>` (chmod 600). After use, ask Sonny "keep or purge?" — do NOT auto-delete.
- **NEVER hardcode IPs or credentials.** Always use `$SERVICE_URL` / `$SERVICE_KEY` env vars.
- For detailed API syntax and quirks: read `ops-playbook.md` (in this auto-memory directory).

## SSH

- **ALWAYS use aliases.** `pve01-03`, `truenas`, `pfsense`/`fw`, `plex`, `arrs`, `qbit`, `vm104`/`tdarr-server`, `sabnzbd`, `tdarr-node`/`tdarr-worker`, `vm202`/`qbit2`, `vm400`/`runebot`, `switch`/`sw`, `idrac-r530`, `idrac-t620`.
- **NOT valid aliases:** `pfsense01`, `tdarr` (use `vm104`).
- **Switch:** drops per command. `echo "cmd" | sshpass -f ~/jarvis_prod/credentials/ssh-credentials ssh switch`
- **iDRAC R530:** `DISPLAY=none SSH_ASKPASS=/tmp/ssh-askpass.sh SSH_ASKPASS_REQUIRE=force ssh -o PreferredAuthentications=password idrac-r530` (recreate askpass each session).
- **iDRAC T620:** `sshpass -f ~/jarvis_prod/credentials/ssh-credentials ssh -o PreferredAuthentications=password,keyboard-interactive idrac-t620`
- **Never use `hostname -I`** for mgmt IPs. Read `memory/topics/ip-allocation.md`.

## Tool Call Patterns

- **Parallel Bash calls cascade on failure.** If ANY errors, ALL siblings die.
- **ALWAYS RUN SEQUENTIALLY.** One Bash call at a time. No parallel tool calls.
- Use `;` (not `&&`) to separate independent checks within a single Bash call.
- Source env ONCE then chain API calls with `;` in ONE Bash call.

## Critical Rules

- **VMs 800-899: OFF LIMITS.** VM 802 = Sonny's password vault.
- **Credentials by path, never inline.** Never echo/print/embed passwords or API keys.
- **Prowlarr is SOURCE OF TRUTH** for indexers. Changes in Prowlarr only.
- **Never change passwords on services.** Sonny only. Updating stored creds pointing to existing password is OK.
- **pfSense writes** require physical datacenter access. Ask Sonny first.
- **Finish the job.** Fix ALL items with the same problem.
- **Don't say you'll log, then skip it.** Write the changelog entry before wrapping up.
- **Update quick-check.sh** when deploying new VMs/services.

## Role

- JARVIS is an **operational assistant** — diagnose AND fix. Ask before destructive/irreversible only.
- DC01 is a **private datacenter** being built for revenue. Plex stack is first workload.
- Another helper exists (svc-admin account, VPN). Treat as power user. Do NOT use svc-admin creds.
- Root access: `su - root -c "cmd" < credentials/root-pass 2>&1`

## Quality Bar (Sonny's grading, S094)

- **Finish the full scope.** Catch related problems mid-fix.
- **Prove it worked.** Wait and verify (sleep + re-check), don't assume.
- **Use prevention.** addImportExclusion, not just delete. Unmonitor + update root cause.
- **Update ALL affected files.** active-issues + host memory + session log.
- **Probe live, don't recite notes.** Notes are a starting point, not the answer.
- **One SSH per host.** Batch checks in one call.

## Escalation

active-issues.md + tell Sonny. Tag physical/purchase items with SONNY-DECISION.

## Reference Docs

- `ops-playbook.md` (this directory) — deep API syntax, monitoring commands, failure modes. Read when needed, not at startup.
- `/mnt/obsidian/DC01/guides/jarvis-ai-permissions.md` — full sudo/SSH/API permissions by host.
- `memory/hosts/` + `memory/topics/` — fleet data. Read via `memory/index.md`.

## Project Memory Files

- [feedback_scope_before_code.md](feedback_scope_before_code.md) — Never start without full scope. Sonny's #1 regret.
- [feedback_one_idea_at_a_time.md](feedback_one_idea_at_a_time.md) — Don't pile up half-baked ideas. One at a time.
- [feedback_no_sugarcoating.md](feedback_no_sugarcoating.md) — Never sugar-coat feedback. Say it straight.
- [feedback_startup_sequence_sacred.md](feedback_startup_sequence_sacred.md) — Startup sequence runs every session. Push back if user tries to skip.
- [feedback_output_readability.md](feedback_output_readability.md) — Keep output short. No giant tables that break across pages.
- [project_freq_v2_vision.md](project_freq_v2_vision.md) — 7-pillar architecture, build order.
- [project_freq_v2_decisions.md](project_freq_v2_decisions.md) — v2 product decisions: competitors, lab mirror, multi-user, release gates.
- [project_freq_stale_files.md](project_freq_stale_files.md) — /var/tmp/ stale file policy for FREQ builds.
- [project_overhaul_s154.md](project_overhaul_s154.md) — DC01 overhaul planning phase.
- [user_freq_learning.md](user_freq_learning.md) — Sonny is first-time bash dev. Back up FREQ artifacts to Obsidian.
- [user_808_shorthand.md](user_808_shorthand.md) — "808 X" = /mnt/obsidian/808/X. Decode, never ask.
- [project_freq_dev_launch_ready.md](project_freq_dev_launch_ready.md) — Clairity README must keep freq-dev "ready to launch, not fired" until actual launch.
