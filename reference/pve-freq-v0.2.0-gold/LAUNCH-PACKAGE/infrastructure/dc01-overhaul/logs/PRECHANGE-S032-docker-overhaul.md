# Pre-Change Baseline — Docker Infrastructure Overhaul
# Session: S032-20260220

## Container State (all 13 running)
| VM | Container | Image | Status |
|----|-----------|-------|--------|
| 101 | plex | lscr.io/linuxserver/plex:1.43.0.10492-121068a07-ls293 | Up 41min (NFS stale) |
| 102 | agregarr | agregarr/agregarr:v2.4.0 | Up 4h |
| 102 | bazarr | lscr.io/linuxserver/bazarr:v1.5.5-ls337 | Up 4h |
| 102 | huntarr | huntarr/huntarr:9.3.7 | Up 4h (healthy) |
| 102 | overseerr | lscr.io/linuxserver/overseerr:v1.34.0-ls157 | Up 4h |
| 102 | prowlarr | lscr.io/linuxserver/prowlarr:2.3.0.5236-ls137 | Up 4h |
| 102 | radarr | lscr.io/linuxserver/radarr:6.0.4.10291-ls292 | Up 4h |
| 102 | sonarr | lscr.io/linuxserver/sonarr:4.0.16.2944-ls302 | Up 4h |
| 103 | flaresolverr | ghcr.io/flaresolverr/flaresolverr:v3.4.6 | Up 5h |
| 103 | gluetun | qmcgaw/gluetun:v3.41.1 | Up 5h (healthy) |
| 103 | qbittorrent | lscr.io/linuxserver/qbittorrent:5.1.4-r2-ls440 | Up 5h |
| 104 | tdarr-node | ghcr.io/haveagitgat/tdarr_node:latest | Up 4h |
| 105 | tdarr | ghcr.io/haveagitgat/tdarr:latest | Up 4h |

## NFS Mount State
- VM 101: 10.25.25.25 — TIMEOUT (stale NFS, known)
- VM 102: 10.25.25.25 — mounted, 21T/744G used (df timed out during check but containers working)
- VM 103: 10.25.255.25 — mounted, 21T/744G used
- VM 104: 10.25.25.25 — mounted, 21T/744G used
- VM 105: 10.25.25.25 — mounted, 21T/744G used

## NFS Directory Structure (pre-change)
```
/mnt/mega-pool/nfs-mega-share/plex/
├── .backup-nfs-migration-S029/
├── arr-data/
│   ├── bazarr/ (383K)
│   ├── overseerr/ (634K)
│   ├── overseerr-backup/ (510K)
│   ├── plex/ (269M)
│   ├── plex.backup.20260216/ (728M)
│   ├── prowlarr/ (8.8M)
│   ├── qbittorrent/ (7.4M)
│   ├── radarr/ (41M)
│   ├── sabnzbd/ (178K — OUT OF SCOPE)
│   ├── sonarr/ (20M)
│   ├── tdarr/ (19M)
│   └── tdarr-node/ (96K)
├── Audio/
├── Downloads/
├── Movies/
├── Transcode/
├── TV/
├── docker-compose.*.yml (5 compose files + .bak files)
└── downloader-data/ (qBit compose + .env)
```

## Compose File Locations (current)
- VM 101: /mnt/truenas/nfs-mega-share/plex/docker-compose.plex.yml
- VM 102: /mnt/truenas/nfs-mega-share/plex/docker-compose.arr.yml
- VM 103: /mnt/truenas/nfs-mega-share/plex/downloader-data/docker-compose.qbit.yml
- VM 104: /mnt/truenas/nfs-mega-share/plex/docker-compose.tdarr-node.yml
- VM 105: /mnt/truenas/nfs-mega-share/plex/docker-compose.tdarr.yml

## Local Config State (VM 102)
- /opt/agregarr-config/ — Agregarr (already local)
- /opt/bazarr-config/ — Bazarr (already local)
- /opt/huntarr-config/ — Huntarr (already local)

## Local Config State (VM 103)
- /home/sonny-aif/qbit-stack/config/gluetun/ — Gluetun (already local)
- CONFIG_DIR=/home/sonny-aif/qbit-stack/config (from .env)
