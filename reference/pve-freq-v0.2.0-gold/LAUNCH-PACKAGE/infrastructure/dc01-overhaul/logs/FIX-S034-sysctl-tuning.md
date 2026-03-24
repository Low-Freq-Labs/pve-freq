# FIX-S034: NFS Performance Sysctl Tuning

**Date:** 2026-02-20
**Session:** S034
**Scope:** All 7 in-scope Linux systems (2 Proxmox hosts + 5 VMs)
**Config file deployed:** `/etc/sysctl.d/99-dc01-nfs-tuning.conf`

## Purpose

Increase NFS socket buffer sizes and TCP tuning parameters to properly support jumbo frames (MTU 9000) on 1GbE links. Default kernel values (212992 bytes / ~208KB) are far too small for NFS with 9000-byte MTU. Additionally, reduce swappiness on Proxmox hypervisors so they prefer keeping VM memory pages in RAM rather than swapping.

---

## Pre-Change Baseline (ALL 7 SYSTEMS IDENTICAL)

Every system had the exact same default values before this change:

```
net.core.rmem_max = 212992
net.core.wmem_max = 212992
net.core.rmem_default = 212992
net.core.wmem_default = 212992
net.ipv4.tcp_rmem = 4096  131072  6291456
net.ipv4.tcp_wmem = 4096  16384   4194304
vm.swappiness = 60
```

No existing custom sysctl configs existed in `/etc/sysctl.d/` on any system (only `README.sysctl`).

---

## Changes Applied

### All 7 Systems — NFS/TCP Tuning

| Parameter | Old Value | New Value | Multiplier |
|-----------|-----------|-----------|------------|
| `net.core.rmem_max` | 212992 (208KB) | 16777216 (16MB) | 79x |
| `net.core.wmem_max` | 212992 (208KB) | 16777216 (16MB) | 79x |
| `net.core.rmem_default` | 212992 (208KB) | 1048576 (1MB) | 5x |
| `net.core.wmem_default` | 212992 (208KB) | 1048576 (1MB) | 5x |
| `net.ipv4.tcp_rmem` (min/default/max) | 4096 / 131072 / 6291456 | 4096 / 1048576 / 16777216 | default 8x, max 2.7x |
| `net.ipv4.tcp_wmem` (min/default/max) | 4096 / 16384 / 4194304 | 4096 / 1048576 / 16777216 | default 64x, max 4x |

### Proxmox Hosts Only (pve01, pve03) — Swappiness

| Parameter | Old Value | New Value |
|-----------|-----------|-----------|
| `vm.swappiness` | 60 | 10 |

---

## Post-Change Verification

### pve01 (10.25.255.26) — VERIFIED
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096  1048576  16777216
net.ipv4.tcp_wmem = 4096  1048576  16777216
vm.swappiness = 10
```

### pve03 (10.25.255.28) — VERIFIED
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096  1048576  16777216
net.ipv4.tcp_wmem = 4096  1048576  16777216
vm.swappiness = 10
```

### VM 101 — Plex-Server (10.25.255.30) — VERIFIED
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096  1048576  16777216
net.ipv4.tcp_wmem = 4096  1048576  16777216
vm.swappiness = 60 (unchanged — VM, not hypervisor)
```

### VM 102 — Arr-Stack (10.25.255.31) — VERIFIED
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096  1048576  16777216
net.ipv4.tcp_wmem = 4096  1048576  16777216
vm.swappiness = 60 (unchanged — VM, not hypervisor)
```

### VM 103 — qBit-Downloader (10.25.255.32) — VERIFIED
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096  1048576  16777216
net.ipv4.tcp_wmem = 4096  1048576  16777216
vm.swappiness = 60 (unchanged — VM, not hypervisor)
```

### VM 104 — Tdarr-Node (10.25.255.34) — VERIFIED
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096  1048576  16777216
net.ipv4.tcp_wmem = 4096  1048576  16777216
vm.swappiness = 60 (unchanged — VM, not hypervisor)
```

### VM 105 — Tdarr-Server (10.25.255.33) — VERIFIED
```
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096  1048576  16777216
net.ipv4.tcp_wmem = 4096  1048576  16777216
vm.swappiness = 60 (unchanged — VM, not hypervisor)
```

---

## Rollback Instructions

To revert any system, remove the config file and reload defaults:

```bash
sudo rm /etc/sysctl.d/99-dc01-nfs-tuning.conf
sudo sysctl --system
```

This restores all values to kernel defaults (rmem/wmem 212992, swappiness 60).

---

## Result: DONE

All 7 systems tuned successfully. Config is persistent via `/etc/sysctl.d/99-dc01-nfs-tuning.conf` and will survive reboots. Zero failures.
