# DC01 Docker Infrastructure Analysis Report
**Session:** S034 | **Date:** 2026-02-20 | **Analyst:** Jarvis

---

## Executive Summary

All 12 expected containers are running across 5 VMs. The infrastructure is in solid operational shape. However, the analysis uncovered **5 CRITICAL findings**, **4 MEDIUM findings**, and **5 LOW/INFO findings** that require attention.

| VM | Expected Containers | Running | Status |
|----|---------------------|---------|--------|
| 101 (Plex-Server) | 1 | 1 | ALL UP |
| 102 (Arr-Stack) | 7 | 7 | ALL UP |
| 103 (qBit-Downloader) | 3 | 3 | ALL UP |
| 104 (Tdarr-Node) | 1 | 1 | ALL UP |
| 105 (Tdarr-Server) | 1 | 1 | ALL UP |

---

## CRITICAL Findings

### CRIT-001: Plaintext VPN Private Key in .env (VM 103)
**File:** `/opt/dc01/compose/.env` on VM 103
**Finding:** The WireGuard private key `EOjj1MTk7VPcK6rpnnM222JokjVCPrEUIlzG2gO4w3Q=` is stored in plaintext in the `.env` file. This is a WireGuard private key for the ProtonVPN connection.
**Risk:** If the VM or backup tarballs are ever compromised, the VPN identity is fully exposed. The backup cron also tars up everything under `/opt/dc01/configs/` and copies to NFS -- the `.env` is in `/opt/dc01/compose/` so it is NOT in the backup tarball (configs only), but it is still plaintext on disk with no encryption at rest.
**Recommendation:** File permissions should be hardened (chmod 600, owned by root). Consider Docker secrets or an encrypted vault for sensitive values. This should be tracked as part of the credentials lockdown (TICKET-0006 or a new ticket).

### CRIT-002: Tdarr API Key in Plaintext Compose File (VM 104)
**File:** `/opt/dc01/compose/docker-compose.yml` on VM 104
**Finding:** The Tdarr API key `tapi_BmuGjjRCb` is hardcoded directly in the compose file as an environment variable (`apiKey=tapi_BmuGjjRCb`).
**Risk:** This key authenticates the node to the Tdarr server. Anyone with read access to the compose file or the NFS backup tarballs can impersonate a worker node. The compose file itself is NOT inside `/opt/dc01/configs/` (it is in `/opt/dc01/compose/`), so it is not in the backup tar, but it is still plaintext on disk.
**Note:** This aligns with the existing TICKET-0010 (Tdarr API key). Should be moved to an `.env` file or Docker secret.

### CRIT-003: Agregarr Missing PUID/PGID Environment Variables (VM 102)
**File:** `/opt/dc01/compose/docker-compose.yml` on VM 102
**Finding:** The `agregarr` service uses `user: "3003:950"` instead of `PUID=3003` / `PGID=950` environment variables. While this achieves the same UID/GID mapping at the Docker level, it is **not the DC01 standard pattern**. All other services use PUID/PGID environment variables.
**Impact:** The `user:` directive runs the process as UID 3003 directly, but the LSIO init system (used by LSIO images) does not apply -- Agregarr is NOT an LSIO image, so `user:` is actually the correct approach for this image. However, the `TZ` variable is present, but `PUID` and `PGID` environment variables are absent from the env block. Non-LSIO images that use `user:` should still be documented.
**Revised Assessment:** This is correct behavior for a non-LSIO image. Downgrade to **INFO** -- document in DC01.md that Agregarr uses `user:` directive rather than PUID/PGID because it is not an LSIO image.

### CRIT-004: VM 105 Tdarr Server -- NFS Backup Directory Does Not Exist
**File:** `backup-check.txt` on VM 105
**Finding:** The backup check shows: `ls: cannot access '/mnt/truenas/nfs-mega-share/media/config-backups/tdarr/': No such file or directory`. The NFS backup directory for VM 105 (Tdarr-Server) does not exist on the NFS share. The backup script runs and creates local backups, but the NFS copy step will fail silently because the `mkdir -p` command in the script should create it -- yet it has not been created.
**Root Cause:** The VM hostname resolves to `tdarr` (lowercase), and the NFS backup directory `/mnt/truenas/nfs-mega-share/media/config-backups/tdarr/` has never been created. Either the backup cron has never successfully fired (the backup dir on VM 105 shows NO local backup tarballs either, only `backup.sh`), or the NFS mount was not available when the cron ran.
**Risk:** VM 105 config data is NOT being backed up to NFS. No backup history exists.
**Recommendation:** Manually trigger `backup.sh` to create the directory and verify the cron fires correctly at 03:00.

### CRIT-005: VM 101 and VM 102 NFS Backup Directories Are Empty
**File:** `backup-check.txt` on VM 101 and VM 102
**Finding:** Both VM 101 and VM 102 show `=== NFS BACKUPS ===` followed by either empty output or `total 0`. This means the NFS backup directories exist but contain no backup files.
**Root Cause:** The backup script appears to be newly deployed (cron file dated `Feb 20 15:44`). The first cron run at 03:00 has not yet occurred (data was collected the same day the cron was deployed). The backup script itself is correct.
**Risk:** Until the first 03:00 cron fires, there are no NFS-side backups for VM 101 or VM 102. VM 103 also shows empty NFS backups.
**Recommendation:** Monitor after the first 03:00 run (2026-02-21 03:00) to confirm all 5 VMs produce NFS backups. Consider running `backup.sh` manually on each VM once to seed the first backup.

---

## MEDIUM Findings

### MED-001: FlareSolverr Using Anonymous Docker Volume (VM 103)
**File:** `docker-inspect.txt` on VM 103
**Finding:** FlareSolverr's mount shows: `/var/lib/docker/volumes/37fc681380e9.../_data->/config`. This is an anonymous Docker volume, not a named volume or bind mount to `/opt/dc01/configs/flaresolverr`. The compose file does not define any volumes for FlareSolverr.
**Impact:** FlareSolverr config is ephemeral and not backed up. If the container is recreated with `docker compose up -d`, it gets a NEW anonymous volume and loses any prior state. This data is also not included in the daily backup tarball.
**Recommendation:** Add a volume mount: `/opt/dc01/configs/flaresolverr:/config` to the FlareSolverr service definition. FlareSolverr is relatively stateless (it is a browser proxy), so this is MEDIUM not CRITICAL -- but it should be standardized.

### MED-002: FlareSolverr and Gluetun Missing PUID/PGID (VM 103)
**File:** `/opt/dc01/compose/docker-compose.yml` on VM 103
**Finding:** Neither FlareSolverr nor Gluetun have PUID/PGID environment variables set. They only have TZ set (via `${TZ}` variable reference).
- **FlareSolverr:** Not an LSIO image (ghcr.io/flaresolverr). Does not support PUID/PGID. Runs as root by design (needs browser control). Acceptable.
- **Gluetun:** Not an LSIO image (qmcgaw/gluetun). Does not support PUID/PGID. Runs as root by design (needs NET_ADMIN for VPN tunneling). Acceptable.
**Assessment:** Both are non-LSIO images that require root. The only service on VM 103 that uses PUID/PGID is qBittorrent, and it correctly has them set via `${PUID}` and `${PGID}` from the `.env` file. **This is correct behavior, not a true violation.** However, DC01.md should note the exceptions.

### MED-003: Plex Media Volumes Mounted Read-Only (VM 101)
**File:** `/opt/dc01/compose/docker-compose.yml` on VM 101
**Finding:** The media volumes are mounted as `:ro` (read-only):
```
- /mnt/truenas/nfs-mega-share/media/movies:/movies:ro
- /mnt/truenas/nfs-mega-share/media/tv:/tv:ro
```
**Assessment:** This is actually **good practice** for Plex -- it should only read media, never write to it. Plex write operations (metadata, thumbnails) go to `/config`. However, this differs from the other media services (Radarr, Sonarr, Bazarr on VM 102) which mount media as read-write. This is by design but worth confirming: if Plex ever needs to perform "Optimize" (creating optimized versions), it would need write access. Currently, transcoding goes to `/tmp/plex-transcode` (local), which is correct.
**Recommendation:** No change needed. Document that Plex intentionally uses `:ro` for media.

### MED-004: Plex Transcode Using /tmp (VM 101)
**File:** `/opt/dc01/compose/docker-compose.yml` on VM 101
**Finding:** Transcode directory is mapped to `/tmp/plex-transcode` on the host.
**Assessment:** This is the documented standard per DC01.md: "transcode on local `/tmp/plex-transcode`". Using local disk for transcode is correct (avoids NFS latency for transcode I/O). However, `/tmp` is typically cleared on reboot. Since transcodes are temporary by nature, this is acceptable.
**Recommendation:** No change needed. Already documented and intentional.

---

## LOW / INFO Findings

### LOW-001: VM 104 Missing /dev/kfd and /dev/dri/renderD128
**File:** `gpu.txt` on VM 104
**Finding:** The compose file passes `/dev/dri:/dev/dri` and `/dev/kfd:/dev/kfd`. The `gpu.txt` shows `/dev/dri/` contains only `card0` -- there is no `renderD128` device. The RX580 GPU is detected via `lspci` but the render node is missing. The compose file also passes `/dev/kfd` for ROCm, but we cannot confirm if `/dev/kfd` exists from the collected data.
**Impact:** Without `renderD128`, VAAPI hardware transcoding may not work. The `vainfo` command is also not installed (`command not found`), so HW encode capability cannot be verified.
**Recommendation:** Install `vainfo` (`sudo apt install vainfo`) and check if `renderD128` exists. If missing, the GPU passthrough configuration in Proxmox may need adjustment (ensure the VirtIO GPU is not consuming the only render slot).

### LOW-002: VM 105 Has GPU Device but No Passthrough in Compose
**File:** `gpu.txt` on VM 105
**Finding:** VM 105 shows `/dev/dri/card0` and a VGA device, but the Tdarr Server compose file does NOT pass any GPU devices. This is correct -- the server role does not do transcoding (that is the node's job on VM 104). The GPU visible in lspci is just the QEMU default VGA, not a real GPU.
**Assessment:** Correct. No action needed.

### LOW-003: Huntarr Is the Only Container With a Healthcheck (VM 102)
**File:** `docker-ps.txt` on VM 102
**Finding:** Out of 7 containers on VM 102, only Huntarr shows `(healthy)` status. The other 6 (Sonarr, Overseerr, Agregarr, Bazarr, Radarr, Prowlarr) show `Up` without health status. On VM 103, Gluetun has a healthcheck (defined in compose, confirmed `(healthy)` in docker-ps).
**Assessment:** Healthchecks are defined by the image or compose file. LSIO images do not include healthchecks by default. The Gluetun healthcheck is explicitly defined in the compose file (VPN connectivity test). This is acceptable current state but adding healthchecks to critical services would improve monitoring.
**Recommendation:** Consider adding healthchecks to Plex, Sonarr, Radarr, and Prowlarr compose definitions for better operational visibility.

### LOW-004: Tdarr Media Volume Mount Paths Use Title Case (VM 104, VM 105)
**File:** `docker-compose.yml` on VM 104 and VM 105
**Finding:** The NFS media is mounted with Title Case container paths:
```
/mnt/truenas/nfs-mega-share/media/movies:/media/Movies
/mnt/truenas/nfs-mega-share/media/tv:/media/TV
/mnt/truenas/nfs-mega-share/media/audio:/media/Audio
```
The host paths correctly use lowercase (`media/movies`, `media/tv`, `media/audio`), which matches the DC01 standard. The container-side mount points (`/media/Movies`, `/media/TV`, `/media/Audio`) use Title Case. This is fine -- these are internal container paths that Tdarr expects. The critical thing is the NFS host-side paths are lowercase, and they are.
**Assessment:** Correct. No action needed.

### LOW-005: SERVER_REGIONS Commented Out in .env (VM 103)
**File:** `/opt/dc01/compose/.env` on VM 103
**Finding:** The `.env` file has `#SERVER_REGIONS=Illinois` commented out, while `SERVER_COUNTRIES=Netherlands` is active. The compose file references `${SERVER_REGIONS}` which will resolve to an empty string.
**Assessment:** This is intentional -- Gluetun uses either countries or regions, not both. The commented-out line serves as documentation of an alternative config. Empty `SERVER_REGIONS` is handled gracefully by Gluetun. No issue.

---

## Per-VM Detailed Compliance Matrix

### VM 101 -- Plex-Server

| Check | Status | Details |
|-------|--------|---------|
| Container running | PASS | `plex` -- Up 4 hours |
| Image pinned | PASS | `lscr.io/linuxserver/plex:1.43.0.10492-121068a07-ls293` |
| PUID=3003 | PASS | Set in compose |
| PGID=950 | PASS | Set in compose |
| TZ=America/Chicago | PASS | Set in compose |
| Config on local disk | PASS | `/opt/dc01/configs/plex:/config` |
| Media on NFS | PASS | `/mnt/truenas/nfs-mega-share/media/movies`, `/media/tv` |
| NFS paths lowercase | PASS | `media/movies`, `media/tv` |
| Restart policy | PASS | `unless-stopped` |
| Network mode | PASS | `host` (required for Plex) |
| GPU passthrough | PASS | `/dev/dri:/dev/dri` |
| Compose header | PASS | Standard DC01 header present |
| Compose location | PASS | `/opt/dc01/compose/docker-compose.yml` |
| Backup cron | PASS | `0 3 * * * root /opt/dc01/backups/backup.sh` |
| Backup script | PASS | Correct content, 7-day NFS / 3-day local retention |
| NFS backups exist | **WARN** | Directory empty -- cron not yet fired (deployed same day) |
| No .env file | PASS | Not required for this VM |
| Failed services | PASS | 0 failed systemd units |

### VM 102 -- Arr-Stack

| Check | Status | Details |
|-------|--------|---------|
| All 7 containers running | PASS | agregarr, bazarr, huntarr, overseerr, prowlarr, radarr, sonarr |
| All images pinned | PASS | All 7 have specific version tags |
| PUID=3003 on all | PASS* | 6 services via env var; Agregarr via `user: "3003:950"` (non-LSIO) |
| PGID=950 on all | PASS* | Same as above |
| TZ=America/Chicago on all | PASS | All 7 services |
| Configs on local disk | PASS | All 7 at `/opt/dc01/configs/<service>/` |
| Media on NFS | PASS | movies, tv, downloads all on NFS |
| NFS paths lowercase | PASS | All paths use lowercase |
| Restart policy | PASS | All `unless-stopped` |
| Compose header | PASS | Standard DC01 header present |
| Compose location | PASS | `/opt/dc01/compose/docker-compose.yml` |
| Services alphabetical | PASS | agregarr, bazarr, huntarr, overseerr, prowlarr, radarr, sonarr |
| Backup cron | PASS | Correct |
| Backup script | PASS | Correct |
| NFS backups exist | **WARN** | `total 0` -- cron not yet fired |
| No .env file | PASS | Not required |
| Failed services | PASS | 0 failed systemd units |

**Image versions (VM 102):**
| Service | Image | Version Pinned |
|---------|-------|----------------|
| Agregarr | `agregarr/agregarr:v2.4.0` | YES |
| Bazarr | `lscr.io/linuxserver/bazarr:v1.5.5-ls337` | YES |
| Huntarr | `huntarr/huntarr:9.3.7` | YES |
| Overseerr | `lscr.io/linuxserver/overseerr:v1.34.0-ls157` | YES |
| Prowlarr | `lscr.io/linuxserver/prowlarr:2.3.0.5236-ls137` | YES |
| Radarr | `lscr.io/linuxserver/radarr:6.0.4.10291-ls292` | YES |
| Sonarr | `lscr.io/linuxserver/sonarr:4.0.16.2944-ls302` | YES |

### VM 103 -- qBit-Downloader

| Check | Status | Details |
|-------|--------|---------|
| All 3 containers running | PASS | gluetun, qbittorrent, flaresolverr |
| All images pinned | PASS | All 3 have specific version tags |
| PUID=3003 (qBit) | PASS | Via `${PUID}` from .env = 3003 |
| PGID=950 (qBit) | PASS | Via `${PGID}` from .env = 950 |
| TZ=America/Chicago | PASS | Via `${TZ}` from .env on all 3 |
| Configs on local disk | PASS* | qBit + Gluetun at `/opt/dc01/configs/`. FlareSolverr uses anonymous volume (MED-001) |
| Media on NFS | PASS | `/mnt/truenas/nfs-mega-share/media/downloads:/downloads` |
| NFS paths lowercase | PASS | `media/downloads` |
| Restart policy | PASS | All `unless-stopped` |
| Network mode | PASS | qBit + FlareSolverr via `service:gluetun`; Gluetun is bridge with ports |
| .env file exists | PASS | `/opt/dc01/compose/.env` |
| .env PUID/PGID/TZ correct | PASS | `PUID=3003`, `PGID=950`, `TZ=America/Chicago` |
| VPN key in .env | **CRIT** | Plaintext WireGuard key (CRIT-001) |
| depends_on healthcheck | PASS | qBit depends on gluetun:service_healthy |
| Gluetun healthcheck | PASS | Custom wget-based check defined, container shows `(healthy)` |
| Compose header | PASS | Standard DC01 header present |
| Compose location | PASS | `/opt/dc01/compose/docker-compose.yml` |
| Backup cron | PASS | Correct |
| Backup script | PASS | Correct |
| NFS backups exist | **WARN** | Empty -- cron not yet fired |
| Failed services | PASS | 0 failed systemd units |

**Image versions (VM 103):**
| Service | Image | Version Pinned |
|---------|-------|----------------|
| FlareSolverr | `ghcr.io/flaresolverr/flaresolverr:v3.4.6` | YES |
| Gluetun | `qmcgaw/gluetun:v3.41.1` | YES |
| qBittorrent | `lscr.io/linuxserver/qbittorrent:5.1.4-r2-ls440` | YES |

### VM 104 -- Tdarr-Node

| Check | Status | Details |
|-------|--------|---------|
| Container running | PASS | `tdarr-node` -- Up 4 hours |
| Image tag | PASS* | `:latest` -- acceptable per DC01 standard (no semver on ghcr.io) |
| PUID=3003 | PASS | Set in compose |
| PGID=950 | PASS | Set in compose |
| TZ=America/Chicago | PASS | Set in compose |
| Config on local disk | PASS | `/opt/dc01/configs/tdarr-node/configs`, `/logs` |
| Media on NFS | PASS | movies, tv, audio, transcode |
| NFS paths lowercase | PASS | Host-side all lowercase |
| Restart policy | PASS | `unless-stopped` |
| GPU passthrough | PASS | `/dev/dri:/dev/dri` + `/dev/kfd:/dev/kfd` |
| group_add video | PASS | `video` + GID `992` |
| Server connection | PASS | `serverIP=10.25.10.33`, `serverPort=8266` |
| API key in compose | **CRIT** | Plaintext `tapi_BmuGjjRCb` (CRIT-002 / TICKET-0010) |
| Compose header | PASS | Standard DC01 header with version note |
| Compose location | PASS | `/opt/dc01/compose/docker-compose.yml` |
| Backup cron | PASS | Correct |
| Backup script | PASS | Correct |
| NFS backups exist | PASS | `dc01-configs-20260220-1543.tar.gz` (14KB) present on NFS |
| Local backup exists | PASS | Same tarball present locally |
| Failed services | PASS | 0 failed systemd units |

### VM 105 -- Tdarr-Server

| Check | Status | Details |
|-------|--------|---------|
| Container running | PASS | `tdarr` -- Up 4 hours |
| Image tag | PASS* | `:latest` -- acceptable per DC01 standard (no semver on ghcr.io) |
| PUID=3003 | PASS | Set in compose |
| PGID=950 | PASS | Set in compose |
| TZ=America/Chicago | PASS | Set in compose |
| Config on local disk | PASS | `/opt/dc01/configs/tdarr/server`, `/configs`, `/logs` |
| Media on NFS | PASS | movies, tv, audio, transcode |
| NFS paths lowercase | PASS | Host-side all lowercase |
| Restart policy | PASS | `unless-stopped` |
| Auth enabled | PASS | `auth=true` |
| Internal node disabled | PASS | `internalNode=false` |
| Ports | PASS | 8265 (WebUI) + 8266 (server) exposed |
| No GPU (intentional) | PASS | Server does not need GPU |
| Compose header | PASS | Standard DC01 header with version note |
| Compose location | PASS | `/opt/dc01/compose/docker-compose.yml` |
| Backup cron | PASS | Correct |
| Backup script | PASS | Correct |
| NFS backups exist | **CRIT** | Directory does not exist on NFS (CRIT-004) |
| Local backup exists | **CRIT** | No local backup tarballs found either |
| Failed services | PASS | 0 failed systemd units |

---

## Port Exposure Summary

| VM | Container | Ports Exposed | Expected | Status |
|----|-----------|---------------|----------|--------|
| 101 | plex | None (host networking) | host mode | PASS |
| 102 | agregarr | 7171/tcp | 7171 | PASS |
| 102 | bazarr | 6767/tcp | 6767 | PASS |
| 102 | huntarr | 9705/tcp | 9705 | PASS |
| 102 | overseerr | 5055/tcp | 5055 | PASS |
| 102 | prowlarr | 9696/tcp | 9696 | PASS |
| 102 | radarr | 7878/tcp | 7878 | PASS |
| 102 | sonarr | 8989/tcp | 8989 | PASS |
| 103 | gluetun | 8080, 6881/tcp+udp, 8191 | 8080, 6881, 8191 | PASS |
| 103 | qbittorrent | via gluetun | service:gluetun | PASS |
| 103 | flaresolverr | via gluetun | service:gluetun | PASS |
| 104 | tdarr-node | 8265-8267 (EXPOSE, not published) | bridge, no -p | PASS |
| 105 | tdarr | 8265-8266/tcp | 8265, 8266 | PASS |

No unexpected ports found.

---

## Backup Infrastructure Summary

| VM | Cron | Script | Local Backups | NFS Backups | Status |
|----|------|--------|---------------|-------------|--------|
| 101 | PASS | PASS | None yet | Empty dir | WARN -- not yet fired |
| 102 | PASS | PASS | None yet | Empty dir | WARN -- not yet fired |
| 103 | PASS | PASS | None yet | Empty dir | WARN -- not yet fired |
| 104 | PASS | PASS | 1 tarball (14KB) | 1 tarball (14KB) | PASS |
| 105 | PASS | PASS | **None** | **Dir missing** | **CRIT** |

All 5 VMs have identical backup scripts and cron entries. The cron is set to `0 3 * * *` (03:00 daily) running as root. Backup script is well-written with `set -euo pipefail`, proper NFS availability checking, and dual retention (7-day NFS, 3-day local).

**VM 104 is the only VM with confirmed working backups.** VMs 101-103 appear to have had the cron deployed on 2026-02-20 (same day as audit) and have not yet had a 03:00 run. VM 105 has a more serious issue -- no backups at all and the NFS target directory was never created.

---

## Action Items (Prioritized)

### Immediate (Do Now)
1. **Run `backup.sh` manually on VM 105** to create the NFS directory and seed the first backup:
   ```
   ssh svc-admin@10.25.255.33 'sudo /opt/dc01/backups/backup.sh'
   ```
2. **Run `backup.sh` manually on VMs 101, 102, 103** to seed first backups before waiting for the 03:00 cron.

### Short-Term (This Week)
3. **Harden .env file permissions on VM 103:**
   ```
   ssh svc-admin@10.25.255.32 'sudo chmod 600 /opt/dc01/compose/.env && sudo chown root:root /opt/dc01/compose/.env'
   ```
4. **Move Tdarr API key (VM 104) to .env file** (TICKET-0010):
   - Create `/opt/dc01/compose/.env` on VM 104 with `TDARR_API_KEY=tapi_BmuGjjRCb`
   - Update compose to use `apiKey=${TDARR_API_KEY}`
   - Harden permissions on the new .env file

5. **Add FlareSolverr config volume (VM 103):**
   ```yaml
   flaresolverr:
     volumes:
       - /opt/dc01/configs/flaresolverr:/config
   ```

### Medium-Term (Credentials Lockdown)
6. **Rotate VPN key** after .env hardening is confirmed (part of TICKET-0006 scope).
7. **Add healthchecks** to Plex, Sonarr, Radarr, Prowlarr compose definitions.
8. **Install vainfo on VM 104** to verify GPU transcoding capability.

### Documentation
9. **Update DC01.md** to note:
   - Agregarr uses `user:` directive (non-LSIO image, no PUID/PGID support)
   - FlareSolverr and Gluetun run as root by design (non-LSIO, require elevated privileges)
   - Plex media mounts are intentionally `:ro`

---

## Verification Checklist (Post-03:00 on 2026-02-21)

- [ ] VM 101: NFS backup directory has at least 1 tarball
- [ ] VM 102: NFS backup directory has at least 1 tarball
- [ ] VM 103: NFS backup directory has at least 1 tarball
- [ ] VM 104: NFS backup directory has 2+ tarballs
- [ ] VM 105: NFS backup directory exists and has at least 1 tarball
- [ ] All containers still running (`docker ps` on each VM)

---

*Report generated by Jarvis -- S034 Docker Infrastructure Audit*
