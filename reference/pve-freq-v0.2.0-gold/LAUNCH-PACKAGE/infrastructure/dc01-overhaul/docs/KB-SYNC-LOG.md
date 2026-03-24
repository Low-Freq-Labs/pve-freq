# Knowledge Base Sync Log

> Tracks Obsidian vault (DB_01) synchronization with DC01 infrastructure state

## Vault Location

**Path:** `/mnt/smb-public/DB_01/`
**SMB Source:** TrueNAS public SMB share

## Sync History

| Session | Date | SMB Reachable? | Pages Written | Pages Updated | Pages Skipped | Notes |
|---------|------|----------------|---------------|---------------|---------------|-------|
| S027-20260220 | 2026-02-20 | YES | 34 | 0 | 0 | Initial KB creation. Existing S17 files archived to _archive-pre-audit/. Full vault structure established. |

## Vault Structure

```
DB_01/
├── 00-Overview.md
├── 01-Hardware.md
├── 02-Network/ (5 pages)
├── 03-Storage/ (4 pages)
├── 04-VMs/ (6 pages)
├── 05-Services/ (3 pages)
├── 06-Cluster/ (3 pages)
├── 07-Security/ (4 pages)
├── 08-Backups/ (2 pages)
├── 09-Lessons-Learned.md
├── 10-Runbooks/ (4 pages)
├── _archive-pre-audit/ (S17 files)
└── _audit/ (2 pages)
```

## Page Inventory

| Page | Created | Last Updated | Source |
|------|---------|-------------|--------|
| 00-Overview.md | S027 | S027 | DC01.md + live-pull |
| 01-Hardware.md | S027 | S027 | DC01.md + iDRAC |
| 02-Network/VLAN-Map.md | S027 | S027 | DC01.md + live-pull |
| 02-Network/Switch-Port-Map.md | S027 | S027 | switch running-config |
| 02-Network/Firewall-Rules.md | S027 | S027 | DC01.md |
| 02-Network/WireGuard.md | S027 | S027 | DC01.md (NO private keys) |
| 02-Network/Jumbo-Frames.md | S027 | S027 | live-pull ifconfig/interfaces |
| 03-Storage/ZFS-Pool.md | S027 | S027 | zpool status live-pull |
| 03-Storage/NFS-Exports.md | S027 | S027 | /etc/exports live-pull |
| 03-Storage/NFS-Mount-Table.md | S027 | S027 | VM fstab + mount live-pulls |
| 03-Storage/SMB-Shares.md | S027 | S027 | midclt query live-pull |
| 04-VMs/VM-Inventory.md | S027 | S027 | qm list + DC01.md |
| 04-VMs/VM-101-Plex.md | S027 | S027 | live-pull |
| 04-VMs/VM-102-Arr-Stack.md | S027 | S027 | live-pull |
| 04-VMs/VM-103-qBit.md | S027 | S027 | live-pull |
| 04-VMs/VM-104-Tdarr-Node.md | S027 | S027 | live-pull |
| 04-VMs/VM-105-Tdarr-Server.md | S027 | S027 | live-pull |
| 05-Services/Docker-Compose-Index.md | S027 | S027 | compose files live-pull |
| 05-Services/Service-URLs.md | S027 | S027 | DC01.md |
| 05-Services/Container-Versions.md | S027 | S027 | docker ps live-pull |
| 06-Cluster/HA-Status.md | S027 | S027 | ha-manager status live-pull |
| 06-Cluster/Corosync.md | S027 | S027 | corosync.conf live-pull |
| 06-Cluster/Proxmox-Storage.md | S027 | S027 | pvesm status live-pull |
| 07-Security/SSH-Hardening.md | S027 | S027 | sshd_config live-pull |
| 07-Security/User-Accounts.md | S027 | S027 | /etc/passwd live-pull |
| 07-Security/Sudo-Config.md | S027 | S027 | sudoers live-pull |
| 07-Security/Audit-Logging.md | S027 | S027 | DC01.md (none deployed) |
| 08-Backups/Backup-Manifest.md | S027 | S027 | docs/BACKUP-MANIFEST.md |
| 08-Backups/Rebuild-Guide.md | S027 | S027 | base_config README summary |
| 09-Lessons-Learned.md | S027 | S027 | CLAUDE.md |
| 10-Runbooks/NFS-Troubleshooting.md | S027 | S027 | session history |
| 10-Runbooks/VM-Recovery.md | S027 | S027 | session history |
| 10-Runbooks/Network-Troubleshooting.md | S027 | S027 | session history |
| 10-Runbooks/Emergency-Contacts.md | S027 | S027 | DC01.md |
| _audit/Last-Audit.md | S027 | S027 | this session |
| _audit/Audit-History.md | S027 | S027 | this session |
