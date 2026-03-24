# FIX: pve03 Swap + ZPool Upgrade
**Session:** S034
**Target:** pve03 (10.25.255.28)
**Date:** 2026-02-20
**Operator:** Jarvis
**Status:** DONE

---

## Task 1: Add 8GB Swap (OOM Prevention)

### Problem
pve03 has 31GB RAM, no swap configured, and runs a 16GB VM (Tdarr-Node VM 104). A single memory spike could trigger the OOM killer and crash the VM or Proxmox host.

### Pre-Change State
- **Swap:** 0B total, 0B used
- **RAM:** 31Gi total, 21Gi used, 9.6Gi free
- **rpool:** 857GB available on mirrored Micron SSDs

### Actions Taken

**Step 1: Created 8GB ZFS zvol on rpool**
```
sudo zfs create -V 8G rpool/swap
```
Result: zvol created successfully.

**Step 2: Formatted as swap**
```
sudo mkswap /dev/zvol/rpool/swap
```
Result: `UUID=f7524e50-4b80-4979-baa0-90f60cd77437`, size 8 GiB

**Step 3: Activated swap**
```
sudo /usr/sbin/swapon /dev/zvol/rpool/swap
```
Result: Swap active, device `/dev/zd32`, priority -2

**Step 4: Added to fstab for boot persistence**
```
echo "/dev/zvol/rpool/swap none swap sw 0 0" | sudo tee -a /etc/fstab
```

### Post-Change Verification
```
               total        used        free      shared  buff/cache   available
Mem:            31Gi        21Gi       9.6Gi        65Mi       1.1Gi        10Gi
Swap:          8.0Gi          0B       8.0Gi

NAME      TYPE      SIZE USED PRIO
/dev/zd32 partition   8G   0B   -2
```

fstab now contains:
```
/dev/zvol/rpool/swap none swap sw 0 0
```

ZFS dataset:
```
NAME         USED  AVAIL  REFER  MOUNTPOINT
rpool/swap  8.13G   857G    60K  -
```

### Result: SUCCESS
- 8GB swap active on ZFS zvol (SSD-backed, mirrored)
- Persistent across reboots via fstab
- pve03 now has OOM protection

---

## Task 2: Upgrade rpool ZFS Features

### Problem
`zpool status` reported: "Some supported and requested features are not enabled on the pool." This is a non-destructive upgrade that enables newer ZFS features available in the running kernel.

### Pre-Change State
- rpool state: ONLINE with feature warning
- Some features not yet enabled

### Action Taken
```
sudo zpool upgrade rpool
```

### Result
Enabled 2 new features:
- `block_cloning_endian`
- `physical_rewrite`

### Post-Change Verification
```
pool: rpool
state: ONLINE
config:
    NAME                                                  STATE     READ WRITE CKSUM
    rpool                                                 ONLINE       0     0     0
      mirror-0                                            ONLINE       0     0     0
        ata-Micron_5100_MTFDDAK960TCC_17321AD779DA-part3  ONLINE       0     0     0
        ata-Micron_5200_MTFDDAK960TDD_195225A6A263-part3  ONLINE       0     0     0

errors: No known data errors
```

- Feature warning **GONE** from zpool status
- All features now enabled/active
- Pool ONLINE, 0 errors

### Result: SUCCESS

---

## Rollback Instructions

### Remove Swap
```bash
sudo /usr/sbin/swapoff /dev/zvol/rpool/swap
sudo zfs destroy rpool/swap
sudo sed -i '/\/dev\/zvol\/rpool\/swap/d' /etc/fstab
```

### ZPool Feature Upgrade
- Non-reversible (by design). No rollback needed or possible.
- Safe for Proxmox VE 9.x with kernel 6.17.9-1-pve.
