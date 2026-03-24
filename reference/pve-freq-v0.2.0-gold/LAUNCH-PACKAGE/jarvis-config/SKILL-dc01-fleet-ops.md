# DC01 Fleet Operations

Procedural knowledge for operating DC01 infrastructure. Steps, workflows, and SOPs — not reference data.

## Health Check Workflow

1. **Run `bash ~/jarvis_prod/scripts/quick-check.sh all`** — covers APIs, containers, ZFS, NFS, cluster, NTP in 15 seconds.
2. **Deep-dive only what's flagged.** Follow this order: containers → ZFS → NFS → arr health → queues → SABnzbd → Tdarr → disk → Plex.
3. **Full checks also include:** iDRAC sensors (T620+R530), NTP chain, WireGuard peers, Bazarr/Overseerr/Agregarr, pfSense filter logs, Plex transcode state.
4. **Cross-reference against `memory/active-issues.md`** — verify recent fixes held.

## SSH Procedures

- **Always use aliases.** Never raw IPs. Aliases: `pve01-03`, `truenas`, `pfsense`/`fw`, `plex`, `arrs`, `qbit`, `vm104`/`tdarr-server`, `sabnzbd`, `tdarr-node`/`tdarr-worker`, `vm202`/`qbit2`, `vm400`/`runebot`, `switch`/`sw`.
- **Switch:** Drops connections per command. Pattern: `echo "show running-config" | sshpass -f ~/jarvis_prod/credentials/ssh-credentials ssh switch`
- **iDRAC R530:** `DISPLAY=none SSH_ASKPASS=/tmp/ssh-askpass.sh SSH_ASKPASS_REQUIRE=force ssh -o PreferredAuthentications=password idrac-r530` (recreate askpass script each session).
- **iDRAC T620:** `sshpass -f ~/jarvis_prod/credentials/ssh-credentials ssh -o PreferredAuthentications=password,keyboard-interactive idrac-t620`
- **One SSH per host.** Batch checks: `echo "=== CHECK1 ===" ; cmd1 ; echo "=== CHECK2 ===" ; cmd2` in one call.

## API Access Pattern

1. Load env vars: `eval "$(cat ~/jarvis_prod/credentials/api-keys.env | grep -v '^#')"`
2. Never hardcode IPs — always use `$SERVICE_URL` / `$SERVICE_KEY` env vars.
3. Source env ONCE, then chain API calls with `;` in ONE Bash call.

### Service-Specific Quirks
- **Tdarr:** Auth header required (`-H "x-api-key: $TDARR_KEY"`). Data queries use POST to `/api/v2/cruddb`. `/api/v2/status` returns only version/uptime — use `StatisticsJSONDB` collection for file counts.
- **qBit:** Cookie auth. `POST $QBIT_URL/api/v2/auth/login` with `username=svc-admin`. Anti-brute-force bans IPs after 5 fails. If banned: `sudo docker restart qbittorrent`.
- **SABnzbd:** Query param API, not REST. `mode=queue`, `mode=history&limit=N`.
- **Plex:** Add `Accept: application/json`. Library counts via `/library/sections/X/all?X-Plex-Container-Size=0` (use `size` field). Sections: 1=movies, 2=TV.
- **Prowlarr:** v1 API (not v3). `GET /api/v1/health`, `/api/v1/indexer`.

## Subsystem Diagnostics

### Containers
- `sudo docker ps` on each Docker VM (101-104, 201, 202, 301). Restart/Exited = immediate flag.
- Restart: `sudo docker restart <container>` or `cd /opt/dc01/compose && sudo docker compose up -d`.
- Docker logs: `sudo docker logs --tail 50 <container>`. Red flags: `database is locked`, `no space left`, `connection refused`, `permission denied` on /data/.

### ZFS (TrueNAS)
- `sudo zpool status` (health + errors), `sudo zpool list` (capacity). `zpool` needs sudo (not in user PATH).
- Alerts: `sudo midclt call alert.list` — empty array = healthy, CRITICAL = flag immediately.
- Disk temps: `sudo midclt call disk.temperatures` — flag >45°C.

### NFS Mounts
- `df -h | grep nfs` on all Docker VMs. If it hangs = stale mount.
- Recovery: `umount -f` + remount. Check TrueNAS NFS service: `sudo midclt call service.query`.

### PVE Cluster
- `sudo pvecm status` — Quorate=Yes required. Quorate=No = CRITICAL.
- `sudo qm list` for VMs per node. `sudo pvesh get /cluster/resources --type vm --output-format json` for cluster-wide.

### NTP Chain
- pfSense: `sudo /usr/local/sbin/ntpq -p`. TrueNAS: `sudo chronyc sources`. VMs: `timedatectl` — "synchronized: yes" = chain healthy.

### WireGuard
- `sudo wg show` on pfSense. Healthy: handshake <150s. Dead: no handshake or hours old.

## Common Fixes

- **Container crash:** `sudo docker restart <name>`. If crash-loops, check logs + disk space on host.
- **Stale NFS:** `umount -f /mnt/truenas/nfs-mega-share` then remount. All containers depending on it need restart after.
- **Sonarr indexer warnings:** Cross-check Prowlarr first. If Prowlarr healthy, Sonarr is stale cache — clear with indexer test call.
- **SABnzbd stuck "Queued":** Admin file save failure on NFS. Use Sonarr/Radarr manual import for stuck downloads.
- **Radarr grab/fail loop:** Blocklist the bad release (`DELETE /api/v3/queue/{id}?removeFromClient=true&blocklist=true`). If loop continues, unmonitor.

## Thresholds

- CPU temp: >75°C warn, >85°C crit. Ambient: >35°C warn.
- Disk temp: >45°C flag.
- WireGuard: handshake >150s = stale.
- PVE cluster: Quorate=Yes required.
- Sonarr queue: 1500-2500 normal (Huntarr). Only flag if climbing OR errors dominate.
