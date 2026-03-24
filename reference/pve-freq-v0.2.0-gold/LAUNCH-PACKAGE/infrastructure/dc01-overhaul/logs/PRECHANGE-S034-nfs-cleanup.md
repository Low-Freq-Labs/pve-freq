# Pre-Change Baseline — S034 NFS Post-Overhaul Cleanup
**Date:** 2026-02-20
**Session:** S034
**Operator:** Jarvis (automated via Claude Code)

## Scope
1. Remove backward-compat NFS symlinks on TrueNAS
2. Remove .pre-overhaul dirs on VMs 102 and 103
3. Remove arr-data-archived and archived-compose on NFS (if backups confirmed)

---

## TrueNAS NFS Root — `/mnt/mega-pool/nfs-mega-share/`
```
drwxrwxr-x+ 13 svc-admin truenas_admin 14 Feb 20 08:05 DC01_v1.1_base_config
drwxrwxr-x+ 14 sonny-aif truenas_admin 14 Feb 17 16:38 arr-data-backup-pre-overhaul-S032  (1.1G)
drwxrwxr-x+ 11 sonny-aif truenas_admin 16 Feb 20 13:44 media
lrwxrwxrwx   1 root      root           5 Feb 20 12:45 plex -> media  [SYMLINK - TO REMOVE]
```

## TrueNAS Media Dir — `/mnt/mega-pool/nfs-mega-share/media/`
```
drwxrwxr-x+  2 svc-admin truenas_admin  8 Feb 20 07:59 .backup-nfs-migration-S029
lrwxrwxrwx   1 root      root           5 Feb 20 12:45 Audio -> audio       [SYMLINK - TO REMOVE]
lrwxrwxrwx   1 root      root           9 Feb 20 12:45 Downloads -> downloads [SYMLINK - TO REMOVE]
lrwxrwxrwx   1 root      root           6 Feb 20 12:45 Movies -> movies     [SYMLINK - TO REMOVE]
lrwxrwxrwx   1 root      root           2 Feb 20 12:45 TV -> tv             [SYMLINK - TO REMOVE]
lrwxrwxrwx   1 root      root           9 Feb 20 12:45 Transcode -> transcode [SYMLINK - TO REMOVE]
drwxrwxr-x+  2 svc-admin truenas_admin 13 Feb 20 13:44 archived-compose     (84K) [TO REMOVE]
drwxrwxr-x+ 14 sonny-aif truenas_admin 14 Feb 17 16:38 arr-data-archived    (1.1G) [TO REMOVE]
drwxrwxr-x+  2 sonny-aif truenas_admin  2 Feb 12 18:27 audio
drwxrwxr-x+  7 svc-admin truenas_admin  7 Feb 20 13:43 config-backups
drwxrwxr-x+  4 sonny-aif truenas_admin  5 Feb 12 19:14 downloads
drwxrwxr-x+ 11 sonny-aif truenas_admin 11 Feb 14 11:29 movies
drwxrwxr-x+  2 sonny-aif truenas_admin  2 Feb 15 09:44 transcode
drwxrwxr-x+  4 sonny-aif truenas_admin  4 Feb 14 00:45 tv
```

## Config Backup Status (cron health check)
```
config-backups/arr-stack/       — EMPTY (no backups yet)
config-backups/plex-server/     — EMPTY (no backups yet)
config-backups/qbit-downloader/ — EMPTY (no backups yet)
config-backups/tdarr-node/      — 1 backup: dc01-configs-20260220-1543.tar.gz (14KB)
config-backups/tdarr-server/    — EMPTY (no backups yet)
```
**NOTE:** Only tdarr-node has produced a backup. 4 of 5 VMs have empty backup dirs.

## VM 102 (10.25.255.31) — `/opt/`
```
drwxrwxr-x 12 svc-admin truenas_admin 4096 Feb 19 22:53 agregarr-config.pre-overhaul  (3.1M) [TO REMOVE]
drwxr-xr-x  8 sonny-aif truenas_admin 4096 Feb 19 00:14 bazarr-config.bak             (656K) [NOT IN SCOPE]
drwxr-xr-x  8 svc-admin truenas_admin 4096 Feb 19 00:18 bazarr-config.pre-docker-migration (388K) [NOT IN SCOPE]
drwxr-xr-x  8 svc-admin truenas_admin 4096 Feb 19 00:18 bazarr-config.pre-overhaul    (400K) [TO REMOVE]
drwx--x--x  4 root      root          4096 Feb 19 13:18 containerd
drwxr-xr-x  5 svc-admin truenas_admin 4096 Feb 20 15:00 dc01
drwxrwxr-x  5 svc-admin truenas_admin 4096 Feb 20 14:54 huntarr-config.pre-overhaul   (5.4M) [TO REMOVE]
```

## VM 103 (10.25.255.32) — `/home/sonny-aif/`
```
drwxr-xr-x 3 root root 4096 Feb 13 02:18 qbit-stack.pre-overhaul  (15M) [TO REMOVE]
```
Also present (not in scope): backup-docker-migration-vm103/, docker-compose.qbit.yml.bak, .env

---

## Rollback Instructions
- **Symlinks:** Re-create with `ln -s media plex`, `ln -s movies Movies`, etc. on TrueNAS
- **Pre-overhaul dirs:** Gone permanently — data also exists in arr-data-backup-pre-overhaul-S032 (1.1G) and DC01_v1.1_base_config on NFS
- **arr-data-archived:** Also backed up as arr-data-backup-pre-overhaul-S032 on NFS root (same data, different copy)
- **archived-compose:** Old compose files, also captured in DC01_v1.1_base_config
