# Fleet State — Reference

> After running `freq init`, your fleet state lives in `conf/hosts.conf` and related config under `conf/`.
> Use `freq host list` to review registered hosts, or `freq doctor` to verify local setup and connectivity.

## Example Fleet Layout

| IP | Label | OS | Role | Notes |
|---|---|---|---|---|
| 192.168.10.26 | pve01 | Proxmox VE | Hypervisor node | API at :8006 |
| 192.168.10.27 | pve02 | Proxmox VE | Hypervisor node | API at :8006 |
| 192.168.10.28 | pve03 | Proxmox VE | Hypervisor node | API at :8006 |
| 192.168.10.25 | truenas | TrueNAS | Storage | NFS/SMB |
| 192.168.10.1 | pfsense | pfSense | Firewall | FreeBSD-based |
| 192.168.20.50 | docker-host | Debian 13 | Docker containers | Media stack |

## Docker Containers (example)

| Container | Port | Auth |
|---|---|---|
| plex | 32400 | X-Plex-Token |
| sonarr | 8989 | X-Api-Key header |
| radarr | 7878 | X-Api-Key header |
| prowlarr | 9696 | X-Api-Key header |
| qbittorrent | 8080 | Session cookie |
| sabnzbd | 8085 | `apikey` query parameter |
| tdarr | 8265 | X-Api-Key header |

## PVE API

```bash
# Auth: POST /api2/json/access/ticket (root@pam + password)
# Then: Cookie: PVEAuthCookie=<ticket>, CSRFPreventionToken header
curl -sk https://<pve-ip>:8006/api2/json/version
```

## Useful Commands

```bash
freq host list                  # Show registered fleet hosts
freq doctor                     # Verify local install and connectivity
freq fleet test <host>          # Test connectivity to a specific host
freq fleet exec all "hostname" # Run a command across fleet targets
```
