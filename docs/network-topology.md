# Network Topology — Example

> Example VLAN layout for a FREQ-managed cluster. Replace with your own network details.

## VLAN Layout

| VLAN | Name | Subnet | Gateway | Purpose |
|---|---|---|---|---|
| 10 | MGMT | 192.168.10.0/24 | 192.168.10.1 | Management — PVE nodes, NAS, firewall |
| 20 | SERVICES | 192.168.20.0/24 | 192.168.20.1 | Application VMs and Docker hosts |
| 30 | STORAGE | 192.168.30.0/24 | — | Storage traffic (NFS/SMB) |
| 50 | PUBLIC | 192.168.50.0/24 | 192.168.50.1 | Internet-facing services |
| 100 | LAB | 192.168.100.0/24 | 192.168.100.1 | Lab / sandbox VMs |

## Firewall Considerations

- Management VLAN should be restricted — only SSH and HTTPS from trusted sources
- Storage VLAN typically has no gateway (isolated L2)
- Lab VLAN should be isolated from production VLANs
- Use FREQ's VLAN config (`conf/vlans.toml`) to define your layout

## Physical Infrastructure Example

| Host | Type | MGMT IP |
|---|---|---|
| firewall | pfSense/OPNsense | 192.168.10.1 |
| switch | Managed switch | 192.168.10.5 |
| nas | TrueNAS | 192.168.10.25 |
| pve01 | Proxmox VE node | 192.168.10.26 |
| pve02 | Proxmox VE node | 192.168.10.27 |
| pve03 | Proxmox VE node | 192.168.10.28 |
