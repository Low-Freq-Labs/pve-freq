Title: Proxmox version drift — pve03 at 9.1.6, pve01 at 9.1.5
Session: S027-20260220
Context: Audit Phase A — pveversion output shows pve01 at pve-manager 9.1.5, pve03 at 9.1.6. pve03 also has newer proxmox-backup-client (4.1.4 vs 4.1.2), pve-container (6.1.2 vs 6.1.1), proxmox-widget-toolkit (5.1.6 vs 5.1.5), and kernel 6.17.13-1 available (not booted).
Diagnosis: Cluster nodes should be at the same PVE version for consistency and to avoid migration compatibility issues. pve03 was updated independently. [CONFIRMED]
Exact Fix: Run `apt update && apt dist-upgrade` on pve01 to bring it to 9.1.6. Then reboot to pick up any kernel updates. Coordinate with Sonny for maintenance window.
Priority: P3
