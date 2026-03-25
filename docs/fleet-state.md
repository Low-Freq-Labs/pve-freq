# Fleet State — Reference

> After running `freq init`, your fleet state is tracked in `conf/hosts.conf`.
> Use `freq hosts list` to view the current fleet, or `freq doctor` to verify connectivity.

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
| sabnzbd | 8085 | apikey parameter |
| tdarr | 8265 | x-api-key header |

## PVE API

```
# Auth: POST /api2/json/access/ticket (root@pam + password)
# Then: Cookie: PVEAuthCookie=<ticket>, CSRFPreventionToken header
curl -sk https://<pve-ip>:8006/api2/json/version
```

## Useful Commands

```bash
freq hosts list          # Show all fleet hosts
freq doctor              # Verify fleet connectivity
freq hosts sync          # Sync hosts.conf from PVE
freq exec all "hostname" # Run command across fleet
```
