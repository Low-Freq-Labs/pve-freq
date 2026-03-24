# Pre-Change Baseline — S031 — pve03 VLAN 10 MTU + Config Fix

## Date: 2026-02-20
## System: pve03 (10.25.255.28)

## Changes Planned
1. Create `/etc/network/interfaces.d/vlan10-compute.conf` — persist VLAN 10 bridge with MTU 9000 + IP 10.25.10.28/24
2. Remove `/etc/network/interfaces.d/vlan2550-mgmt.conf.bak` — duplicate interface definition being sourced by wildcard
3. Apply MTU 9000 to nic0.10 at runtime
4. Add IP 10.25.10.28/24 to vmbr0v10 at runtime

## Pre-Change State
- nic0.10: MTU 1500, UP, master vmbr0v10
- vmbr0v10: MTU 9000, UP, NO IP address, NO config file
- vlan2550-mgmt.conf.bak: Being sourced (duplicate vmbr0v2550 definition)
- interfaces.d/ files: sdn, vlan2550-mgmt.conf, vlan2550-mgmt.conf.bak, vlan25-storage.conf, vlan5-public.conf

## Rollback
1. `sudo ip link set nic0.10 mtu 1500`
2. `sudo ip addr del 10.25.10.28/24 dev vmbr0v10`
3. `sudo rm /etc/network/interfaces.d/vlan10-compute.conf`
4. `sudo mv /root/backup-vlan2550-bak-S031/vlan2550-mgmt.conf.bak /etc/network/interfaces.d/`
