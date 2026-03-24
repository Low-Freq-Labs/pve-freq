# Network Topology

> Extracted from CLAUDE.md for on-demand reference.

## VLAN Layout

| VLAN | Name | Subnet | Gateway | Purpose |
|---|---|---|---|---|
| 0 | LAN | 10.25.0.0/24 | 10.25.0.1 | Default LAN |
| 5 | PUBLIC | 10.25.5.0/24 | 10.25.5.1 | Internet-facing services |
| **10** | **DEV** | **10.25.10.0/24** | **10.25.10.1** | **Your VLAN — isolated, internet only** |
| 25 | STORAGE | 10.25.25.0/24 | — | Storage traffic (NFS/SMB) |
| 66 | DIRTY | 10.25.66.0/24 | 10.25.66.1 | Untrusted/VPN traffic |
| 100 | VPN | 10.25.100.0/24 | 10.25.100.1 | WireGuard VPN |
| 2550 | MGMT | 10.25.255.0/24 | 10.25.255.1 | Management |

## DEV VLAN Firewall Rules

| # | Action | Destination | Purpose |
|---|---|---|---|
| 1 | BLOCK TCP | pfSense self | Protect WebUI |
| 2 | PASS any | pfSense DEV IP (10.25.10.1) | DNS + gateway |
| 3 | BLOCK any | 10.0.0.0/8 | No inter-VLAN |
| 4 | BLOCK any | 172.16.0.0/12 | No inter-VLAN |
| 5 | BLOCK any | 192.168.0.0/16 | No inter-VLAN |
| 6 | PASS any | any | Internet only |

**You cannot reach production hosts directly.** pve02 is reachable via SSH key (when deployed) for VM management only.

## Physical Infrastructure

| Host | Hardware | MGMT IP |
|---|---|---|
| pfsense01 | Netgate 4100, Atom C3338R, 4GB | 10.25.255.1 |
| gigecolo (switch) | Cisco WS-C4948E-F, 48x1G + 4x10G | 10.25.255.5 |
| truenas | Dell R530, 2x E5-2620v3, 86GB, 43.6T ZFS | 10.25.255.25 |
| pve01 | Dell T620, 2x E5-2620, 251GB, 9T HDD | 10.25.255.26 |
| pve02 | Dell Skylake, 2x Gold 6150, 125GB, 1.7T SSD | 10.25.255.27 |
| pve03 | ASUS B550-E, Ryzen 7 3800X, 31GB, 1.7T SSD, RX 580 | 10.25.255.28 |
