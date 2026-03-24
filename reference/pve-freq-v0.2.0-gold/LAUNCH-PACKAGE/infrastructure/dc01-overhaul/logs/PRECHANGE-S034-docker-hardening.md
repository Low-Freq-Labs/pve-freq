# Pre-Change Baseline: S034 Docker Hardening
**Date:** 2026-02-20
**Scope:** VM 103 (10.25.255.32), VM 104 (10.25.255.34)

## VM 103 — .env permissions (Fix 1)
```
-rw-r--r-- 1 svc-admin truenas_admin 472 Feb 20 14:49 /opt/dc01/compose/.env
```
**Issue:** World-readable file containing WireGuard private key.

## VM 103 — FlareSolverr volumes (Fix 3)
FlareSolverr service has NO volume mounts — uses anonymous Docker volume:
```yaml
  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:v3.4.6
    container_name: flaresolverr
    restart: unless-stopped
    network_mode: "service:gluetun"
    environment:
      - TZ=${TZ}
      - LOG_LEVEL=info
```
No `/opt/dc01/configs/flaresolverr` directory exists.

## VM 103 — Running containers
```
NAMES          STATUS                 IMAGE
qbittorrent    Up 4 hours             lscr.io/linuxserver/qbittorrent:5.1.4-r2-ls440
flaresolverr   Up 3 hours             ghcr.io/flaresolverr/flaresolverr:v3.4.6
gluetun        Up 3 hours (healthy)   qmcgaw/gluetun:v3.41.1
```

## VM 104 — Compose file (Fix 2)
API key hardcoded in environment block:
```yaml
      - apiKey=tapi_BmuGjjRCb
```
No .env file exists at `/opt/dc01/compose/.env`.

## VM 104 — Running containers
```
NAMES        STATUS       IMAGE
tdarr-node   Up 4 hours   ghcr.io/haveagitgat/tdarr_node:latest
```

## Rollback
- VM 103 .env: `sudo chmod 644 /opt/dc01/compose/.env && sudo chown svc-admin:truenas_admin /opt/dc01/compose/.env`
- VM 104: Delete .env, restore hardcoded apiKey in compose, `sudo docker compose up -d`
- VM 103 FlareSolverr: Remove volumes section from compose, delete `/opt/dc01/configs/flaresolverr`, `sudo docker compose up -d flaresolverr`
