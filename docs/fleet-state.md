# Lab Fleet State — Live Reference

> Verified S162 (2026-03-13). All hosts probed. Use this as ground truth for testing.

## Lab Hosts (FREQ hosts.conf)

| IP | Label | OS | Role | SSH User | Notes |
|---|---|---|---|---|---|
| 10.25.10.50 | freq-dev | Debian 13 | FREQ v1.0.0 dev | freq-admin | This VM (999) |
| 10.25.10.52 | lab-pve1 | Debian 13 / PVE 9.1.6 | Nested PVE | freq-admin | API at :8006 |
| 10.25.10.53 | lab-pve2 | Debian 13 / PVE 9.1.6 | Nested PVE | freq-admin | API at :8006 |
| 10.25.10.54 | docker-dev | Debian 13 | 15 Docker containers | freq-admin | Full Plex stack |
| 10.25.10.60 | lab-debian12 | Debian 12 | Distro test | freq-admin | apt |
| 10.25.10.61 | lab-debian13 | Debian 13 | Distro test | freq-admin | apt |
| 10.25.10.62 | lab-ubuntu | Ubuntu 24.04 | Distro test | freq-admin | apt, netplan |
| 10.25.10.63 | lab-rocky9 | Rocky Linux 9.7 | Distro test | freq-admin | dnf |
| 10.25.10.64 | lab-alma9 | AlmaLinux 9.7 | Distro test | freq-admin | dnf |
| 10.25.10.65 | lab-opensuse | openSUSE Leap 15.6 | Distro test | freq-admin | zypper |

## Docker-Dev Containers (10.25.10.54)

| Container | Port | HTTP | API |
|---|---|---|---|
| plex | 32400 | 401 | X-Plex-Token |
| sonarr | 8989 | 200 | /api/v3/ + X-Api-Key |
| radarr | 7878 | 200 | /api/v3/ + X-Api-Key |
| prowlarr | 9696 | 200 | /api/v1/ + X-Api-Key |
| bazarr | 6767 | 200 | /api/ + X-Api-Key |
| overseerr | 5055 | 307 | /api/v1/ + X-Api-Key |
| tautulli | 8181 | 303 | /api/v2?apikey=&cmd= |
| agregarr | 7171 | 307 | WebUI |
| qbittorrent | 8080 | 200 | /api/v2/ (session cookie) |
| flaresolverr | 8191 | 200 | POST /v1 |
| sabnzbd | 8085 | 303 | /api?mode=&apikey= |
| tdarr | 8265 | 200 | /api/v2/ + x-api-key |
| recyclarr | — | — | Config sync only |
| unpackerr | — | — | Event-driven |
| kometa | — | — | Scheduled |

API keys: `/opt/dc01/compose/.env` on docker-dev (read via SSH).

## PVE API (lab-pve1, lab-pve2)

```
# Auth: POST /api2/json/access/ticket (root@pam + password)
# Then: Cookie: PVEAuthCookie=<ticket>, CSRFPreventionToken header
curl -sk https://10.25.10.52:8006/api2/json/version  # → 401 (needs auth)
```

## Network

- VLAN 10 (10.25.10.0/24) — isolated, internet via pfSense NAT
- Gateway: 10.25.10.1, DNS: 1.1.1.1
- Zero access to prod VLANs (verified by isolation test)
- SSH key: `~/.ssh/id_ed25519` (deployed to all 10 hosts as freq-admin)

## FREQ v1.0.0 Reference

- Install: `/opt/pve-freq/`
- Source copy: `~/rick/src/pve-freq/`
- Entry: `freq` (224 lines) → loads conf → loads 41 libs → dispatches
- Key libs: fleet.sh (1650L), hosts.sh (1100L), users.sh (1320L), init.sh (1400L), vm.sh (1580L), pve.sh (1300L)
- Config: `conf/freq.conf` (version, branding, SSH mode, paths)
