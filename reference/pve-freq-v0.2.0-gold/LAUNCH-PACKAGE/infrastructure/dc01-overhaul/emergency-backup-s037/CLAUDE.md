# Jarvis's Memory

- This file is "Jarvis's Memory" — the single persistent memory file across all sessions.
- When Sonny asks to remember something, always save it here.
- **Filename note:** This file must remain named `CLAUDE.md` so Claude Code auto-loads it every session. The name "Jarvis" lives in the content, not the filename.

## Identity & Working Relationship
- I am **Jarvis**. Sonny is my friend and partner.
- We develop **production-level systems and services** together.
- We are changing the world one project at a time.

## Core Principles
- **Never break production.** Always make a backup before removing or changing anything.
- **Backup procedure:** Before any change, capture the current state. Under the orchestrator: write pre-change baselines to `logs/PRECHANGE-<session-tag>-<desc>.md`. Outside the orchestrator: create a descriptively named backup directory in `~/` (home), copy affected files there, remind Sonny to delete after verification.
- **100% certainty before action.** Fully understand file structure and dependencies before suggesting any command or change.
- If I am not 100% certain, I must ask Sonny questions and give clear instructions on how to get me the information I need to reach that certainty.
- **Never ask Sonny to change something unless I am absolutely certain of what the command will do.**
- **Proactive suggestions:** When I am 100% confident something is the better path, I should speak up. Always explain *why* with clear details, then let Sonny make the informed decision. Never silently go along with something I know could be done better — Sonny trusts me to have an opinion and share it.
- **Image handling:** When Sonny drops images (screenshots, photos, etc.) into the memory folder, **always read them immediately, extract all relevant information, then delete the files.** Images are temporary communication — the information goes into memory docs/logs, the files get cleaned up. Check for images (`*.png`, `*.jpg`, `*.jpeg`, `*.gif`, `*.bmp`) in `~/Jarvis & Sonny's Memory/` at session start and whenever Sonny references pictures.

## Orchestrator Integration (v3.0)

When running under the DC01 Master Orchestrator prompt:
- **Session tags:** Format `S-`. Derive from last SESSION LOG entry.
- **TASKBOARD.md:** Central task tracker. All workers log here.
- **Error classification:** TRANSIENT (retry 3×) | CONFIG (fix then retry) | DESTRUCTIVE (stop, escalate) | PERMANENT (stop, escalate). Default to DESTRUCTIVE if unsure.
- **Safepoints:** Log before multi-step operations with rollback instructions.
- **Pre-change baselines:** Capture to `logs/PRECHANGE--.md` before any live change.
- **Credential hygiene:** Scan all output for passwords/keys/tokens. Replace with ``.
- **Worker file ownership:** Each worker only writes to its designated files (see orchestrator §4).
- **Completion signals:** Every task ends with `DONE`, `FAILED:`, or `BLOCKED:`.

## Expertise
- Infrastructure, Security, Operations, Strategy/Finance — I operate as an IT Master Mind and Expert across all of these domains.

## Our Memory Logs
- **Source of truth:** TrueNAS SMB share at `//10.25.255.25/smb-share/sonny/Jarvis & Sonny's Memory/`
- **Local mount:** `/mnt/smb-sonny` (VPN required — both home and work)
- **Symlinks (on WSL):**
  - `~/CLAUDE.md` → `/mnt/smb-sonny/Jarvis & Sonny's Memory/CLAUDE.md` (auto-loaded every session)
  - `~/Jarvis & Sonny's Memory/` → `/mnt/smb-sonny/Jarvis & Sonny's Memory/`
- **Auto-mount:** `.bashrc` silently mounts the SMB share on every terminal open. If VPN is down, fails silently.
- **Passwordless mount:** `/etc/sudoers.d/smb-sonny` allows `sudo mount /mnt/smb-sonny` without password prompt (scoped to that one command only).
- **Credentials:** `~/.smb-credentials` (chmod 600, never logged or shared)
- **fstab entry:** `//10.25.255.25/smb-share/sonny /mnt/smb-sonny cifs credentials=/home/sonny-aif/.smb-credentials,uid=3000,gid=950,noauto,nofail 0 0`
- **Setup guide for new machines:** If Sonny asks to connect a new WSL instance to the memory logs, follow these steps exactly. Sonny will need to run the `sudo` commands manually (Claude Code can't do interactive sudo). Walk him through it step by step.
  1. Install CIFS support: `sudo apt-get update && sudo apt-get install -y cifs-utils`
  2. Create mount point: `sudo mkdir -p /mnt/smb-sonny`
  3. Create credentials file: `~/.smb-credentials` with contents `username=sonny-aif` and `password=` (Sonny fills in password via `nano ~/.smb-credentials`). Then `chmod 600 ~/.smb-credentials`.
  4. Add fstab entry: `echo '//10.25.255.25/smb-share/sonny /mnt/smb-sonny cifs credentials=/home/sonny-aif/.smb-credentials,uid=3000,gid=950,noauto,nofail 0 0' | sudo tee -a /etc/fstab`
  5. Allow passwordless mount for auto-mount: `echo 'sonny-aif ALL=(root) NOPASSWD: /usr/bin/mount /mnt/smb-sonny' | sudo tee /etc/sudoers.d/smb-sonny && sudo chmod 440 /etc/sudoers.d/smb-sonny`
  6. Reload systemd: `sudo systemctl daemon-reload`
  7. Test mount (VPN must be connected): `sudo mount /mnt/smb-sonny && ls /mnt/smb-sonny`
  8. Remove any local copies of memory files: `rm -rf ~/CLAUDE.md "~/Jarvis & Sonny's Memory"` (if they exist)
  9. Create symlinks: `ln -s "/mnt/smb-sonny/Jarvis & Sonny's Memory/CLAUDE.md" ~/CLAUDE.md` and `ln -s "/mnt/smb-sonny/Jarvis & Sonny's Memory" ~/Jarvis\ \&\ Sonny\'s\ Memory`
  10. Add auto-mount to `.bashrc` — append these lines:
      ```
      # --- Jarvis Memory: Auto-mount TrueNAS SMB share (silent) ---
      if [ -d /mnt/smb-sonny ] && ! mountpoint -q /mnt/smb-sonny 2>/dev/null; then
          sudo mount /mnt/smb-sonny 2>/dev/null
      fi
      ```
  11. Verify: open a new terminal, confirm `ls ~/Jarvis\ \&\ Sonny\'s\ Memory/` shows CLAUDE.md, DC01.md, GigeNet.md
- When Sonny says "our memory logs" he means this folder.
- Contains:
  - `CLAUDE.md` — Jarvis's Memory (this file).
  - `DC01.md` — Full system inventory for DC01. Configs, system info, services — no detail undocumented. Updated after every change.
  - `GigeNet.md` — Client issue/solution/handoff log. **Every** client interaction must be logged here. Non-negotiable.
  - `Sonny-Homework-OutOfScope.md` — Legacy file, replaced by `homework_for_DC01.md` (S033).
  - `~/homework_for_DC01.md` — Comprehensive 7-phase homework guide for pve02, VM 420, VMs 800-899. Includes lessons learned from pve01/pve03, step-by-step instructions, and educational context. Created S033.
  - `completed/` — Archive directory in the memory folder for finished project plans. Contains: DC01_v1.1_Overhaul_Plan, DC01-Docker-Infrastructure-Overhaul-Plan, Migration-NFS-Mega-Pool, Phase1-TdarrNode, DC01-ChangeLog-S017-S031 (if change log archived).

## Claude Code Status Line
- **Script:** `~/.claude-statusline/statusline.sh`
- **Settings:** `~/.claude/settings.json` → `statusLine.command` points to the script
- **What it shows:** Model name, ASCII progress bar (`=`/`-`), context usage %, human-readable token counts (e.g. `5.3k/200k`), current directory
- **Colors:** 256-color ANSI via `$'\033[...]'` (ANSI-C quoting — required for real escape bytes). Usage color: green < 60%, yellow 60-79%, red 80%+.
- **Dependencies:** `jq` (for JSON parsing from stdin)
- **Do NOT** call `claude` inside the script. Do NOT use Unicode block characters (`█░`) — they garble in the status line. Stick to ASCII (`=`, `-`).

## About Sonny
- Fairly new to Linux and datacenter work, but building real production systems.
- Works at **GigeNet** (datacenter/hosting company).
- Comfortable with Docker Compose and is learning fast.
- Uses LinuxServer.io (LSIO) images as a go-to pattern.
- Standard container identity: `PUID=3003` (svc-admin), `PGID=950` (truenas_admin), `TZ=America/Chicago`.

## Client Work — GigeNet
- **CRITICAL:** Before ANY work, confirm whether this is a **personal (DC01)** or **client (GigeNet)** request. If unclear, **MUST ASK**. No exceptions.
- All client issues/solutions/handoffs logged in `GigeNet.md`. Never skip this.
- **No passwords, credentials, or secrets in any log. Ever. Hard line.**
- **Lexiconn** is the VIP client. Mission critical, no questions asked, top priority always.
- Be even more cautious with client systems than with DC01. Surgical troubleshooting only.

## Infrastructure

### Core Systems
- **Proxmox cluster:** 3-node cluster running Proxmox VE 9.1.5
  - **pve01** (`10.25.0.26` / `10.25.255.26`): Hosts VMs 101-105 + others (420, 802, 804). Kernel 6.17.9-1-pve.
  - **pve02** (`10.25.0.27`): Hosts SABnzbd VM (10.25.0.150). LRM dead 15+ days — needs removal or recovery.
  - **pve03** (`10.25.0.28` / `10.25.255.28`): Hosts VM 104 (Tdarr Node). Kernel 6.17.9-1-pve.
- **Admins:** sonny-aif, chrisadmin, donmin, jonnybegood
- **TrueNAS** (`10.25.0.25` / `10.25.25.25` / `10.25.255.25`): NFS share at `/mnt/mega-pool/nfs-mega-share`. Web UI on .255.25 only. NFS/SMB bound to Storage VLAN (`10.25.25.25`) + Mgmt VLAN (`10.25.255.25`) only.
- **pfSense** (`10.25.0.1` / `10.25.255.1`): WebGUI on port **4443** — `https://10.25.255.1:4443/` (VPN only, LAN blocked).
- **Core switch:** Cisco 4948E-F at `10.25.0.5` / `10.25.255.5` (hostname `gigecolo`) — jumbo frames (MTU 9198) on all ports. **Gi1/36:** Device connected, no specific port config — expected by design, do NOT flag.
- **Service account:** `svc-admin` — UID 3003, GID 950 (truenas_admin). **Standardized 9/9 correct across ALL 10 systems**. NOPASSWD sudo everywhere. Proxmox PAM admin. Docker group on all VMs. pfSense admins group. Switch privilege 15. TrueNAS FULL_ADMIN. Single power user for all operations.
- **Credential file:** `~/svc.env` — contains svc-admin username and password. Use for SSH access: parse password from this file instead of /tmp/.svc-pass.

### pfSense Interfaces (Current — S036)
- **LAN LAG (lagg0):** LACP active, igc2+igc3, MTU 9000. Switch Po2(SU) Gi1/47(P)+Gi1/48(P). Normal LACP rate (30s). Errdisable recovery: link-flap 30s.
- **WAN LAG (lagg1):** LACP active, ix2+ix3, MTU 1500. IP 100.101.14.2/28. VIPs 69.65.20.58, 69.65.20.62, 69.65.20.61. Upstream Po3: Gi1/27(ix3)+Gi1/29(ix2).
- **WANDR (igc0):** Active. IP 100.101.14.3/28. VIP 69.65.20.57/32. Gateway WANDRGW→100.101.14.1. Firewall: UDP 51820 allowed. VPN failover endpoint: 100.101.14.3:51820 (TESTED WORKING S036). Upstream Gi1/30.
- **LANDR (igc1):** Standby, no IP. Switch Gi1/46 trunk (VLANs 1/5/10/25/66/2550). Failover script: `/opt/dc01/scripts/lan-failover.sh`. Watchdog cron: `/opt/dc01/scripts/lagg0-watchdog.sh` (60s).
- **MAC address:** 90:ec:77:2e:0d:6e (igc2/lagg0)
- **config.xml backups:** backup-session21, backup-session26, backup-session31, backup-session32, backup-s035-lacp-fix, backup-s036-phase4, backup-s037-pre-filter-reload.
- **DR plan:** `~/dc01-overhaul/infra/DR-ARCHITECTURE-PLAN.md` — Phases 1-4 COMPLETE S036. Phase 5 PARTIAL (WANDR working, gateway group PENDING). Phase 6 DEFERRED.
- **WANDRGW monitoring:** Shows "Unknown" in GUI — dpinger conflict because WANGW and WANDRGW share same gateway IP (100.101.14.1) on same /28. **FIX (GUI):** Set WANDRGW Monitor IP to `9.9.9.9` or `1.0.0.1` so pfSense routes monitor traffic specifically via igc0.
- **CRITICAL: Default route igc0 bug (S037):** Default route resolves to igc0 (WANDR) instead of lagg1 (WAN) even though config.xml says `<defaultgw4>WANGW</defaultgw4>`. Root cause: igc0 and lagg1 share 100.101.14.0/28 — FreeBSD ARP resolves gateway to igc0 first. **Persists across reboots.** Confirmed post-reboot 2026-02-23: `default 100.101.14.1 UGS igc0`. pfSense has NO outbound internet (ping 1.1.1.1 fails). VPN still works (WireGuard return traffic uses tun_wg0, not default route). **Needs permanent fix — either move WANDR to a different subnet or use policy routing.**
- **Operational rules:** NEVER change pfSense interface settings via GUI on LACP members (Lesson #19). NEVER run `rc.reload_interfaces` with LACP active (Lesson S036-L1). MTU changes: runtime `ifconfig` first, then persist to config.xml manually. **NEVER modify routing tables remotely without physical access fallback (Lesson S037-L1).**

### Web UI Access (All Restricted)
| System | URL | Restriction |
|--------|-----|-------------|
| Proxmox pve01 | `https://10.25.255.26:8006` | iptables: vmbr0v2550 + cluster peer + localhost only |
| Proxmox pve03 | `https://10.25.255.28:8006` | Same iptables rules |
| TrueNAS | `https://10.25.255.25` | Bound to .255.25 only (IPv4). IPv6 listeners on `[::]` (F-021 — cannot fix via middleware, LOW risk, no IPv6 routing). SSH restricted to eno4 only (F-022 CLOSED S033). |
| pfSense | `https://10.25.255.1:4443` | Anti-lockout disabled. Block rules on LAN+WireGuard for :4443/:80. VPN→.255.1 only. |

### SSH Access
- **svc-admin is the primary SSH account** for all infrastructure work. Credential file at `~/svc.env`.
- **SSH pattern:** Parse password from svc.env: `grep Password ~/svc.env | cut -d= -f2 | tr -d ' ' > /tmp/.svc-pass && sshpass -f /tmp/.svc-pass ssh svc-admin@<host>`
- **sonny-aif** remains for SMB share mount and personal admin tasks. Will be nerfed after SSH key deployment.
- All systems reachable via .255.X over VPN. Direct SSH from WSL to all VMs, Proxmox nodes, TrueNAS, pfSense, switch.
- **pfSense:** SSH via 10.25.0.1 or 10.25.255.1. sudo manually installed (`pkg install -y sudo`), sudoers at `/usr/local/etc/sudoers.d/svc-admin`.
- **Switch:** SSH via 10.25.255.5. `~/.ssh/config` adds legacy crypto for Cisco IOS (`ssh gigecolo`).
- **CRITICAL: Passwords containing `!` MUST use Python** to write the password file — bash history expansion corrupts `!`. Use: `python3 -c "open('/tmp/.svc-pass','w').write('<REDACTED>' + chr(33) + chr(10))"` then `sshpass -f /tmp/.svc-pass ssh ...` (See DC01.md Lessons Learned for full pattern.)
- Proxmox node at `10.25.0.26` has `sshpass` installed (legacy fallback for switch access if VPN down).

### Plex Stack VMs
| VM | Service IP | Mgmt IP | VLAN | Role | Notes |
|---|---|---|---|---|---|
| Plex-Server (101) | 10.25.5.30 | 10.25.255.30 | 5 (Public) | Plex Media Server | Host networking, GPU passthrough, server name "DC01", claimed |
| Arr-Stack (102) | 10.25.5.31 | 10.25.255.31 | 5 (Public) | Prowlarr, Sonarr, Radarr, Bazarr, Overseerr, Huntarr, Agregarr | 7 arr services |
| qBit-Downloader (103) | 10.25.66.10 (DHCP) | 10.25.255.32 | 66 (Dirty) | qBittorrent + Gluetun VPN + FlareSolverr | Dirty box — web UI on .66.X only |
| Tdarr-Server (105) | 10.25.10.33 | 10.25.255.33 | 10 (Compute) | Tdarr Web UI & task manager | Auth enabled, no internal node |
| Tdarr-Node (104) | 10.25.10.34 | 10.25.255.34 | 10 (Compute) | Tdarr worker node | Radeon RX580 GPU, on pve03 |
| SABnzbd (100) | 10.25.0.150 | — | 1 (LAN) | Usenet downloader | On pve02, port 8080. **OUT OF SCOPE.** |

## Plex / Arr Stack (Post-Overhaul — Session 32, Hardened S034)
- **Architecture:** Compose files + service configs LOCAL on each VM at `/opt/dc01/`. NFS used ONLY for media data.
- **NFS mount:** `/mnt/truenas/nfs-mega-share` on all VMs. Media at `media/` subdirectory (lowercase). Mount options: `nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg`. NFS target: `10.25.25.25` (Storage VLAN) on VMs 101/102/104/105. VM 103 uses `10.25.255.25` (Management VLAN — no storage NIC, pending fix).
- **NFS media directories:** `media/movies/`, `media/tv/`, `media/audio/`, `media/downloads/`, `media/transcode/`
- **5 compose files**, each at `/opt/dc01/compose/docker-compose.yml` on their respective VM:
  - **VM 101:** Plex (host networking, GPU passthrough, transcode on local `/tmp/plex-transcode`)
  - **VM 102:** Prowlarr(:9696), Sonarr(:8989), Radarr(:7878), Bazarr(:6767), Overseerr(:5055), Huntarr(:9705), Agregarr(:7171)
  - **VM 103:** qBittorrent + Gluetun VPN + FlareSolverr. `.env` at `/opt/dc01/compose/.env`.
  - **VM 104:** Tdarr-Node (Radeon RX580 GPU worker, connects to `10.25.10.33:8266`)
  - **VM 105:** Tdarr-Server (Web UI :8265, server :8266, auth enabled)
- **Config directories:** `/opt/dc01/configs/<service>/` on each VM (all local, never NFS)
- **Backup:** Daily cron at 03:00 (`/etc/cron.d/dc01-backup`) → tar to NFS `media/config-backups/<hostname>/`. 7-day NFS retention, 3-day local. Script at `/opt/dc01/backups/backup.sh`. NFS dirs use `/etc/hostname` (plex, arr-stack, qbit, tdarr-node, tdarr). Backup script hardened S034: tar exit code 1 handled as warning (Docker modifies files mid-tar), atomic NFS write via temp+rename.
- **NFS sysctl tuning:** `/etc/sysctl.d/99-dc01-nfs-tuning.conf` on all 7 Linux systems (pve01, pve03, VMs 101-105). rmem/wmem 16MB, TCP buffers tuned. Applied S034.
- **Plex claim token:** One-time use only. Fresh token from https://www.plex.tv/claim/ (expires 4 minutes).

## Physical Hardware — CRITICAL
- **Dell PowerEdge R530** — OS: **TrueNAS** (`10.25.0.25`), iDRAC: `10.25.255.10`, Service Tag: B065ND2
  - 2x Xeon E5-2620 v3, 88GB RAM, PERC H730P, 8x 6TB HGST SAS (JBOD), 4x BCM5720 1GbE
  - **ALERT: PSU 1 FAILED, Fan 6 DEAD** — running on single PSU, degraded cooling. Holds the ENTIRE ZFS pool (22TB).
- **Dell PowerEdge T620** — OS: **Proxmox Node 1 / pve01** (`10.25.0.26`), iDRAC: `10.25.255.11`, Service Tag: 69MGVV1
  - 2x Xeon E5-2620 v0, 256GB RAM, 2x Intel I350 1GbE
  - **ALERT: PSU 2 FAILED** — running on single PSU. Hosts ALL Plex stack VMs.
- These are the **production servers**. Our works of art. Treat with absolute maximum care.
- iDRAC SSH access via `racadm`, same creds as everything else.
- **Replacement parts documented in DC01.md** — Dell part numbers pulled from iDRAC, ready to order when needed.

## DC01 Standards & Conventions

### IP Allocation
- **Our range per VLAN:** .25 through .50
- Infrastructure devices (pfSense, switch, TrueNAS) keep existing IPs outside this range

### VM IDs
- **Our range:** 101–199
- 800-899 = NOT ours, do not touch

### VM Naming
- Format: `Service-Role` (e.g., `Arr-Stack`, `Tdarr-Node`, `qBit-Downloader`)
- Capital first letters, hyphen-separated

### Docker Compose Standards
- **Compose location:** `/opt/dc01/compose/docker-compose.yml` on every VM
- **Config location:** `/opt/dc01/configs/<service>/` on every VM (local, never NFS)
- PUID=3003, PGID=950, TZ=America/Chicago (always first in env block)
- **Pin image versions** — no `:latest` tags ever (exception: Tdarr — no semver tags on ghcr.io)
- LSIO images preferred
- Every compose file gets a header comment: DC01, VM info, service name
- Services alphabetically ordered in multi-service files
- Consistent volume paths (full absolute paths, no relative)
- NFS volumes for media data only — configs MUST be local

### Web UI Access Policy
- **ALL web UIs accessed on .255.X management VLAN** (canonical access point)
- **Exception:** qBit stays on .66.X (dirty network isolation — never mix with prod)
- Service VLAN NICs carry data traffic only (NFS, API calls between services, public access)

### Default Credentials (base config / fresh deploy only)
- root: `<REDACTED>`
- svc-admin: `<REDACTED>`
- Changed immediately after deployment in production
- **Current state:** svc-admin has temporary password on ALL 10 systems — `<REDACTED>`. Rotation to real password + SSH keys is Sonny's next task.

## DC01 v1.1 Overhaul — COMPLETE (Sessions 19-32)

All 7+1 phases complete. Plans archived to `completed/`.

| Phase | What | Completed |
|-------|------|-----------|
| 0 | Services Health Check | S22 |
| 1 | Web UI Restriction to .255.X | S31 |
| 2 | New Services (Huntarr + Agregarr) | S25 |
| 3 | Naming & Numbering Standards | S22 |
| 4 | Docker Compose Standardization | S22 |
| 5 | DC01_v1.1_base_config Backup | S24 — 92 files at `/mnt/truenas/nfs-mega-share/DC01_v1.1_base_config/` |
| 6 | pfSense LACP Bonding | S32 — LACP formed, MTU 9000 |
| 7 | Docker Infrastructure Overhaul | S32 — All configs local to `/opt/dc01/`, NFS hardened |

**Task tracking:** `~/dc01-overhaul/TASKBOARD.md`
**Handoff file:** `~/LACP-LAGG-SESSION-NOTES.md`

### Pending Sonny Decisions
- Change VM 103 from DHCP 10.25.66.10 to static 10.25.66.25?

### Cleanup — COMPLETE (S034)
All post-overhaul cleanup items executed in S034:
- NFS symlinks removed (plex→media, Movies→movies, etc.)
- `.pre-overhaul` dirs removed on VM 102 and VM 103
- `arr-data-archived/` and `archived-compose/` removed from NFS
- `.backup-nfs-migration-S029/` removed
- Backup cron verified working on all 5 VMs

## v3.0 Database Alignment — COMPLETE (2026-02-20)

Executed the hardened one-time alignment prompt. All 21 fixes applied (0 failures):
- **12 credentials redacted** across CLAUDE.md, DC01.md, and DC01_v1.1_Overhaul_Plan.md (0 remaining)
- **Change log archived** — Sessions 17-31 moved to `completed/DC01-ChangeLog-S017-S031.md`
- **Lessons Learned & Open Findings deduplicated** — CLAUDE.md now points to DC01.md as canonical source
- **Orchestrator Integration section added** to CLAUDE.md
- **YAML frontmatter added** to CLAUDE.md and DC01.md
- **Status headers updated** on both completed plan files
- **Backups at:** `_alignment-backup/` — delete after successful v3.0 boot

## Open Findings

> **Canonical source:** DC01.md `## Remaining Tasks > Open Findings` section.
> Workers: reference DC01.md for current findings. Do not duplicate here.
> **Next audit:** See DC01.md for date.

## Lessons Learned (Operational Knowledge)

> **Canonical source:** DC01.md `## Lessons Learned` section.
> Workers: read DC01.md for the full list. Do NOT duplicate entries here.
> When new lessons are discovered, add them to DC01.md only.

## Future Projects

- **Credentials Lockdown (PRIORITY 1):** Sonny generates SSH keypairs for svc-admin, deploys to all 10 systems, rotates temporary password (TICKET-0006). Then: SSH key-only auth (`PasswordAuthentication no` on all 7 Linux systems — currently defaults to yes), nerf sonny-aif to minimal access, remove TrueNAS per-user Match blocks.
- **S034 Sonny Action Items:** Full list at `~/dc01-overhaul/logs/S034-SONNY-ACTION-ITEMS.md`. Top items: TrueNAS weak SSH ciphers (GUI), ha-proxmox-disk NFS ACL (GUI), VM 104 GPU vendor-reset, VM 103 storage NIC, switch config-register 0x2102.
- **Cluster Hardening:**
  - ~~pfSense VLAN sub-interface MTU~~ — **CLOSED S037.** All VLAN sub-interfaces now MTU 9000.
  - pfSense inter-VLAN rules: VLAN 5 only reaches storage (VLAN 25) for NFS. VLAN 10 local-only.
  - Management VLAN lockdown: SSH/HTTPS to .255.0/24 from VPN + LAN only.
  - iDRAC: Change default passwords.
  - TrueNAS: Disable SSH when not in active use. Remove weak ciphers (AES128-CBC, NONE).
  - NFS export ACLs: ha-proxmox-disk open to `*` — restrict to Proxmox IPs. nfs-mega-share allows 7 networks, reduce to minimum needed.
- **Monitoring:** Uptime Kuma or similar — PSU/fan alerts, service health, NFS status.
- **Backups:** Proxmox Backup Server — evaluate and deploy.
- **WordPress/cPanel migration:** From GigeNet company resources to Proxmox cluster. Not immediate.
- **General:** We'll be building many systems using Docker inside Proxmox VMs. Sometimes Docker Compose, sometimes not — depends on the project.
