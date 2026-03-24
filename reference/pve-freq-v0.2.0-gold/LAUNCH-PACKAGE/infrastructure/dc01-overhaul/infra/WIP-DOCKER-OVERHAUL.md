# WIP: Docker Infrastructure Overhaul — Local + NFS Restructure

**Session:** S032-20260220
**Status:** COMPLETE
**Plan:** ~/Jarvis & Sonny's Memory/DC01-Docker-Infrastructure-Overhaul-Plan.md

## What Was Changed
- All 5 VMs: compose files + service configs moved from NFS to local `/opt/dc01/`
- TrueNAS NFS: `plex/` directory renamed to `media/`, subdirs to lowercase (with backward symlinks)
- All 5 VMs: NFS mount options hardened (`soft,timeo=150,retrans=3,bg`)
- Old NFS config dirs archived (not deleted)
- Daily backup cron installed on all 5 VMs (03:00, tar to NFS)

## Execution Order (Completed)
VM 104 (Tdarr-Node) → VM 105 (Tdarr-Server) → VM 103 (qBit) → VM 102 (Arr-Stack) → VM 101 (Plex)

## Phases Completed
| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Pre-Flight (backup + health check) | DONE |
| 1 | NFS Restructure (plex→media, lowercase) | DONE |
| 2 | VM 104 — Tdarr-Node migration | DONE |
| 3 | VM 105 — Tdarr-Server migration | DONE |
| 4 | VM 103 — qBit-Downloader migration | DONE |
| 5 | VM 102 — Arr-Stack migration | DONE (VM rebooted due to NFS D-state) |
| 6 | VM 101 — Plex-Server migration | DONE (VM rebooted due to NFS D-state) |
| 7 | NFS Mount Hardening (soft,timeo,retrans,bg) | DONE |
| 8 | Backup Cron + Cleanup | DONE |
| 9 | Documentation | DONE |

## Issues Encountered
- VM 102: docker compose down hung (NFS D-state). Required Proxmox force stop + reboot. Lock file conflict resolved by killing hung qm process.
- VM 101: Plex in D-state, compose file corrupted by null bytes. Rewritten via Python. Required Proxmox force stop + reboot.
- NFS config copy: Direct cp over NFS unreliable for large dirs. Used tar-over-SSH pipe (TrueNAS→WSL→VM).
- rsync not available and compute VLAN VMs can't reach internet. Backup script uses tar instead.

## Rollback Procedure
Per-VM rollback:
1. Stop local compose: `cd /opt/dc01/compose && docker compose down`
2. NFS symlink `plex → media` keeps old paths working
3. Archived configs at `media/arr-data-archived/`
4. Restart from old NFS compose path

Full rollback:
1. On TrueNAS: `mv media/arr-data-archived media/arr-data` + restore compose files
2. Rename back: `mv media plex` (if renamed)
3. Each VM: restart from NFS compose paths

## Out-of-Band Access
- All VMs reachable via Proxmox console (pve01: 10.25.255.26, pve03: 10.25.255.28)
- TrueNAS: SSH via 10.25.255.25 or iDRAC 10.25.255.10
- svc-admin SSH to all 5 VMs on .255.X IPs

## Verification
- All 13 containers running across 5 VMs
- Plex: web UI loads, libraries visible
- Arr services: all 7 web UIs respond
- qBit: Gluetun VPN connected, WebUI responds
- Tdarr: server UI loads, node connected
