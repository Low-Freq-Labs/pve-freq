# Pre-Change Baseline: pve03 Swap + ZPool Upgrade
**Session:** S034
**Target:** pve03 (10.25.255.28)
**Date:** 2026-02-20
**Operator:** Jarvis

## Pre-Change State

### Memory (free -h)
```
               total        used        free      shared  buff/cache   available
Mem:            31Gi        21Gi       9.6Gi        65Mi       1.1Gi        10Gi
Swap:             0B          0B          0B
```

### Swap: NONE configured

### fstab
```
# <file system> <mount point> <type> <options> <dump> <pass>
proc /proc proc defaults 0 0
10.25.0.26:/os-pool-hdd/iso-storage  /mnt/iso-share  nfs  defaults,_netdev  0  0
```

### ZFS Datasets (rpool)
```
NAME               USED  AVAIL  REFER  MOUNTPOINT
rpool             3.19G   857G    96K  /rpool
rpool/ROOT        3.18G   857G    96K  /rpool/ROOT
rpool/ROOT/pve-1  3.18G   857G  3.18G  /
rpool/data          96K   857G    96K  /rpool/data
rpool/var-lib-vz    96K   857G    96K  /var/lib/vz
```

### ZPool Status
```
pool: rpool
state: ONLINE
status: Some supported and requested features are not enabled on the pool.
config: mirror-0 (2x Micron SSDs) - ONLINE, 0 errors
```

## Rollback Instructions

### Remove Swap ZVol
```bash
sudo /usr/sbin/swapoff /dev/zvol/rpool/swap
sudo zfs destroy rpool/swap
# Remove the fstab line: /dev/zvol/rpool/swap none swap sw 0 0
sudo sed -i '/\/dev\/zvol\/rpool\/swap/d' /etc/fstab
```

### ZPool Upgrade
- ZPool upgrade is NON-REVERSIBLE (one-way feature enable)
- No rollback possible, but this is expected and safe for Proxmox 9.x
