# FIX-S034: Docker Hardening
**Date:** 2026-02-20
**Session:** S034
**Pre-change baseline:** `PRECHANGE-S034-docker-hardening.md`

---

## Fix 1: Harden .env File Permissions on VM 103

**VM:** 103 (qBit-Downloader) at 10.25.255.32
**Issue:** `/opt/dc01/compose/.env` containing WireGuard VPN private key was world-readable (644, owned by svc-admin:truenas_admin).

### Pre-Change
```
-rw-r--r-- 1 svc-admin truenas_admin 472 Feb 20 14:49 /opt/dc01/compose/.env
```

### Commands Executed
```bash
sudo chmod 600 /opt/dc01/compose/.env
sudo chown root:root /opt/dc01/compose/.env
```

### Post-Change
```
-rw------- 1 root root 472 Feb 20 14:49 /opt/dc01/compose/.env
```

### Result: SUCCESS
File is now readable only by root. Docker Compose reads .env as root via sudo, so all containers remain unaffected. No container restart required.

---

## Fix 2: Move Tdarr API Key to .env on VM 104

**VM:** 104 (Tdarr-Node) at 10.25.255.34
**Issue:** Tdarr API key `tapi_BmuGjjRCb` was hardcoded in plaintext in `docker-compose.yml`.

### Pre-Change
Compose file line 23:
```yaml
      - apiKey=tapi_BmuGjjRCb
```
No `.env` file existed.

### Commands Executed
```bash
# Create .env with API key
echo "TDARR_API_KEY=tapi_BmuGjjRCb" | sudo tee /opt/dc01/compose/.env
sudo chmod 600 /opt/dc01/compose/.env
sudo chown root:root /opt/dc01/compose/.env

# Update compose to use variable
sudo sed -i 's/- apiKey=tapi_BmuGjjRCb/- apiKey=${TDARR_API_KEY}/' /opt/dc01/compose/docker-compose.yml

# Force recreate container
cd /opt/dc01/compose && sudo docker compose up -d --force-recreate
```

### Post-Change
`.env` file:
```
-rw------- 1 root root 29 Feb 20 19:41 /opt/dc01/compose/.env
```

Compose file line 23:
```yaml
      - apiKey=${TDARR_API_KEY}
```

Container verification:
```
NAMES        STATUS              IMAGE
tdarr-node   Up About a minute   ghcr.io/haveagitgat/tdarr_node:latest
```

Environment variable inside container resolves correctly:
```
apiKey=tapi_BmuGjjRCb
```

### Result: SUCCESS
API key moved from compose file to protected .env. Container recreated and running with correct variable resolution.

---

## Fix 3: Add FlareSolverr Config Volume on VM 103

**VM:** 103 (qBit-Downloader) at 10.25.255.32
**Issue:** FlareSolverr service had no persistent volume mount. Config stored in anonymous Docker volume (lost on container recreation).

### Pre-Change
FlareSolverr service in compose:
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
No `/opt/dc01/configs/flaresolverr/` directory existed.

### Commands Executed
```bash
# Create config directory
sudo mkdir -p /opt/dc01/configs/flaresolverr
sudo chown 3003:950 /opt/dc01/configs/flaresolverr

# Add volumes to compose
sudo sed -i '/- LOG_LEVEL=info/a\    volumes:\n      - /opt/dc01/configs/flaresolverr:/config' /opt/dc01/compose/docker-compose.yml

# Recreate container
cd /opt/dc01/compose && sudo docker compose up -d flaresolverr
```

### Post-Change
FlareSolverr service in compose:
```yaml
  flaresolverr:
    image: ghcr.io/flaresolverr/flaresolverr:v3.4.6
    container_name: flaresolverr
    restart: unless-stopped
    network_mode: "service:gluetun"
    environment:
      - TZ=${TZ}
      - LOG_LEVEL=info
    volumes:
      - /opt/dc01/configs/flaresolverr:/config
```

Config directory:
```
drwxr-xr-x 2 svc-admin truenas_admin 4096 Feb 20 19:41 /opt/dc01/configs/flaresolverr
```

Volume mount verified via `docker inspect`:
```
/opt/dc01/configs/flaresolverr -> /config
```

Container status:
```
NAMES          STATUS                 IMAGE
flaresolverr   Up 21 seconds          ghcr.io/flaresolverr/flaresolverr:v3.4.6
qbittorrent    Up 4 hours             lscr.io/linuxserver/qbittorrent:5.1.4-r2-ls440
gluetun        Up 3 hours (healthy)   qmcgaw/gluetun:v3.41.1
```

### Result: SUCCESS
FlareSolverr now has persistent config storage at `/opt/dc01/configs/flaresolverr` following DC01 standards. Container recreated with volume mount confirmed.

---

## Summary

| Fix | VM | Target | Status |
|-----|-----|--------|--------|
| 1 — .env permissions | 103 | `/opt/dc01/compose/.env` | SUCCESS |
| 2 — API key to .env | 104 | `docker-compose.yml` + new `.env` | SUCCESS |
| 3 — FlareSolverr volume | 103 | `docker-compose.yml` + new config dir | SUCCESS |

**All containers verified running post-change. No service disruption.**

### Note
The `SERVER_REGIONS` warning on VM 103 is pre-existing (blank in .env) and does not affect Gluetun operation -- it uses `SERVER_COUNTRIES` for server selection.

### Rollback Instructions
See `PRECHANGE-S034-docker-hardening.md` for full rollback commands.
