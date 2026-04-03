<!-- INTERNAL — Not for public distribution -->

# DC01 Fleet Reference — Expected State

**Purpose:** This is what the fleet SHOULD look like after `freq init` runs correctly. Compare init's output against this. If they don't match, init has a bug.

**This is NOT a config file.** Do not copy this to conf/. Do not use it to pre-fill anything. This is a test reference — the expected output.

---

## PVE Cluster (3 nodes)

| Node | IP (MGMT) | Hardware |
|---|---|---|
| pve01 | 10.25.255.26 | Dell T620 · 2x E5-2430 · 252GB RAM |
| pve02 | 10.25.255.27 | Dell Skylake · Xeon Gold 6110 · 125GB RAM |
| pve03 | 10.25.255.28 | ASUS B650E-E · Ryzen 7 9800X · 32GB RAM |

## Physical Infrastructure

| Device | Type | IP | Hardware | Notes |
|---|---|---|---|---|
| pfsense01 | pfsense | 10.25.255.1 | Netgate 4100 · C3338R | Gateway / firewall. freq-ops has NOPASSWD sudo. |
| truenas | truenas | 10.25.255.25 | Dell R530 · 2x E5-2620v3 · 43.6TB ZFS | TrueNAS SCALE (Debian-based). |
| gigecolo | switch | 10.25.255.5 | Cisco WS-C4948E-F · 48x1G + 4x10G | IOS 15.2. Legacy SSH (KexAlgorithms SHA1). Password auth for freq-ops. |
| iDRAC - PVE01 | idrac | 10.25.255.11 | Dell T620 | Legacy SSH. Responds to racadm. |
| iDRAC - TRUENAS | idrac | 10.25.255.10 | Dell R530 | Legacy SSH. Responds to racadm. |
| iDRAC - PVE02 | idrac | 10.25.255.12 | Dell Skylake | KNOWN DOWN — no route to host. Expected OFFLINE on dashboard. |

## Fleet VMs (Production)

| VMID | Name | Node | Type | IP (MGMT) | Groups |
|---|---|---|---|---|---|
| 100 | pve-freq | pve01 | linux | 10.25.255.50 | prod — future FREQ production install target |
| 101 | pdm-manager | pve01 | linux | 10.25.255.40 | prod |
| 102 | arr-stack | pve01 | docker | 10.25.255.31 | prod, media |
| 103 | qbit | pve01 | docker | 10.25.255.32 | prod, media |
| 104 | tdarr | pve01 | docker | 10.25.255.33 | prod, media |
| 201 | plex | pve02 | docker | 10.25.255.30 | prod, media |
| 202 | sabnzbd | pve02 | linux | 10.25.255.150 | prod, media |
| 203 | qbit2 | pve02 | docker | 10.25.255.35 | prod, media |
| 204 | Tdarr-Node-CPU-1 | pve02 | docker | 10.25.255.34 | prod, media |
| 301 | Tdarr-Node-CPU-2 | pve03 | docker | 10.25.255.34 | prod, media |
| 400 | RunescapeBotVM | pve02 | linux | 10.25.255.69 | prod |
| 404 | email-server | pve02 | linux | — | prod |
| 666 | Jarvis-AI | pve01 | linux | 10.25.255.3 | prod |
| 802 | Blue | pve01 | linux | 10.25.255.75 | prod |
| 804 | Talos | pve01 | linux | — | prod |
| 900 | Nexus-new | pve02 | linux | 10.25.255.2 | prod |
| 999 | Nexus | pve01 | linux | 10.25.255.8 | prod — current dev/build box |

## Fleet VMs (Lab)

| VMID | Name | Node | Type | IP (Dev/Lab VLAN) | Notes |
|---|---|---|---|---|---|
| 5000 | pfsense-lab | pve01 | pfsense | — | Lab firewall |
| 5001 | truenas-lab | pve01 | truenas | 10.25.10.201 | Lab NAS |
| 5002 | lab-pve1 | pve01 | pve | 10.25.10.202 | Lab PVE node — multi-site testing |
| 5003 | lab-pve2 | pve01 | pve | 10.25.10.203 | Lab PVE node — multi-site testing |
| 5005 | freq-test | pve01 | linux | 10.25.255.55 | E2E test box |

## Templates (pve03, stopped)

| VMID | Name | Distro |
|---|---|---|
| 9000 | tpl-debian-13 | Debian 13 |
| 9001 | tpl-debian-12 | Debian 12 |
| 9002 | tpl-ubuntu-2404 | Ubuntu 24.04 |
| 9003 | tpl-ubuntu-2204 | Ubuntu 22.04 |
| 9004 | tpl-rocky-9 | Rocky Linux 9 |
| 9005 | tpl-alma-9 | AlmaLinux 9 |
| 9006 | tpl-fedora-42 | Fedora 42 |
| 9007 | tpl-centos-stream-9 | CentOS Stream 9 |
| 9008 | tpl-arch | Arch Linux |
| 9009 | tpl-opensuse-15 | openSUSE Leap 15 |

## Docker Container Inventory (what should be running)

| Host | Containers |
|---|---|
| plex (.30) | plex |
| arr-stack (.31) | flaresolverr, huntarr, recyclarr, bazarr, overseerr, prowlarr, sonarr, tautulli, radarr, kometa |
| qbit (.32) | gluetun |
| tdarr (.33) | tdarr |
| tdarr-node-cpu-2 (.34) | tdarr-node |
| qbit2 (.35) | gluetun |

## VLANs

| VLAN ID | Name | Subnet | Purpose |
|---|---|---|---|
| 5 | Public | 10.25.5.0/24 | Internet-facing (gateway) |
| 10 | Dev/Lab | 10.25.10.0/24 | Development and lab VMs |
| 25 | Storage | 10.25.25.0/24 | NFS/SMB/iSCSI storage traffic |
| 2550 | Management | 10.25.255.0/24 | Fleet management (SSH, API, dashboard) |

## freq-ops Status (as of 2026-04-02)

freq-ops deployed with SSH + NOPASSWD sudo on ALL hosts:
- 3 PVE nodes
- 6 Docker VMs
- 5 Linux VMs (sabnzbd, freq-test, jarvis-ai, pdm-manager, runescapebotvm, blue)
- 1 TrueNAS
- 1 pfSense (sudo fixed 2026-04-02)
- 1 Switch (password auth, legacy KexAlgorithms)
- 2 Lab PVE nodes (deployed 2026-04-02 via guest agent)
- 2 iDRACs responding (.10, .11), 1 known down (.12)

freq-admin exists NOWHERE. Slate is clean for freq init.
