# DC01 Backup Manifest

> Tracks backup currency and audit history for DC01_v1.1_base_config

## Current Backup Location

**Path:** `/mnt/truenas/nfs-mega-share/DC01_v1.1_base_config/`
**Created:** Session 24 (2026-02-19)
**File Count:** 92 files
**Size:** ~1.1MB
**Version:** v1.1

## Audit History

| Session | Date | Systems Checked | Diffs Found | Files Updated | Notes |
|---------|------|-----------------|-------------|---------------|-------|
| S027-20260220 | 2026-02-20 | 10/10 | 4 | 0 (baseline only) | First audit. 1 EXPECTED, 1 STALE, 2 NEW. |
| S029-20260220 | 2026-02-20 | N/A | N/A | 13 | NFS mount migration: updated all fstab, compose, README, template files. 57 path refs changed. |
| S029-20260220 | 2026-02-20 | 10/10 | N/A | 7 | NFS/SMB binding to Storage + Mgmt VLANs. 4 VM fstabs updated. Proxmox storage.cfg updated. |

## Backup Currency by System

### Docker Compose Files
| File | Backup Date | Live Match? | Notes |
|------|-------------|-------------|-------|
| docker-compose.arr.yml | S24 | YES | 7 services, all pinned |
| docker-compose.plex.yml | S24 | YES | Plex 1.43.0 |
| docker-compose.tdarr.yml | S24 | YES | Server, :latest |
| docker-compose.tdarr-node.yml | S24 | PARTIAL | Backup has `<TDARR_API_KEY>`, live has plaintext |
| docker-compose.qbit.yml | S24 | YES | 3 services via .env |

### Proxmox Configs
| System | Backup Date | Live Match? | Notes |
|--------|-------------|-------------|-------|
| pve01 interfaces | S24 | YES | MTU 9000, vmbr0 |
| pve01 corosync | S24 | YES | Config v8 |
| pve01 sudoers | S24 | YES | svc-admin NOPASSWD |
| pve01 sshd_config | S24 | YES | PermitRootLogin no |
| pve01 VM configs | S24 | NOT CHECKED | Need qm config pull |
| pve03 interfaces | S24 | YES | MTU 9000, vmbr0 |
| pve03 corosync | S24 | YES | Config v8 (shared) |
| pve03 sudoers | S24 | YES | svc-admin NOPASSWD |
| pve03 sshd_config | S24 | YES | PermitRootLogin no |
| pve03 VM config | S24 | NOT CHECKED | Need qm config pull |

### TrueNAS
| Config | Backup Date | Live Match? | Notes |
|--------|-------------|-------------|-------|
| users.txt | S24 | **STALE** | Query failed during S24 capture. Needs repull. |
| zpool-status.txt | S24 | YES | mega-pool ONLINE, 0 errors |
| nfs-exports.txt | S24 | YES | 7 networks, mapall correct |
| smb-shares.txt | S24 | YES | 1 SMB share |
| network-interfaces.txt | S24 | YES | bond0 MTU 9000 |
| dataset-properties.txt | S24 | NOT CHECKED | |

### Switch
| Config | Backup Date | Live Match? | Notes |
|--------|-------------|-------------|-------|
| running-config | S24 | **OUTDATED** | svc-admin user added S26 (+72 bytes) |

### pfSense
| Config | Backup Date | Live Match? | Notes |
|--------|-------------|-------------|-------|
| config-xml-backup-instructions.md | S24 | YES | Documentation only |
| interface-assignments.md | S24 | YES | lagg0 FAILOVER documented |
| firewall-rules-summary.md | S24 | NOT CHECKED | Need live rules pull |
| wireguard-config.md | S24 | NOT CHECKED | |
| lagg-config.md | S24 | YES | FAILOVER mode confirmed |
| vips-and-nat.md | S24 | NOT CHECKED | |

### VM Configs
| VM | Backup Date | Live Match? | Notes |
|----|-------------|-------------|-------|
| vm101-plex | S24 | YES | interfaces, fstab match |
| vm102-arr-stack | S24 | YES | interfaces, fstab match |
| vm103-qbit-downloader | S24 | YES | interfaces, fstab match |
| vm104-tdarr-node | S24 | YES | interfaces, fstab match |
| vm105-tdarr-server | S24 | YES | interfaces, fstab match |

## Items Needing Backup Update

1. **TrueNAS users.txt** — Repull user data (was empty due to S24 query failure)
2. **Switch running-config** — Repull with svc-admin user added
3. **VM sudoers** — Add svc-admin NOPASSWD rule to VM templates (not in current backup)
4. **pfSense svc-admin** — Document svc-admin user creation (S26)
5. **Proxmox svc-admin@pam** — Document PAM user + Administrator role (S26)

## Next Backup Refresh

After LACP cutover completion OR at next audit, whichever comes first. Last refresh: S029 (NFS migration).
