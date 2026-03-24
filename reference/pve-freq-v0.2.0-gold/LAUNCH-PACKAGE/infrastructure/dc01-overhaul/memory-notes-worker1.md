# Worker #1 — Infrastructure Architect — Memory Notes

## S1 — What I Read
- CLAUDE.md, TASKBOARD.md (full state through S041)
- DC01.md (updated through S041 — VM 103 static IP, pfSense svc-admin cleanup)

## S2 — Current DC01 State
- **LAN LAG (lagg0):** LACP active, igc2+igc3, Po2(SU), MTU 9000. Errdisable recovery 30s.
- **WAN LAG (lagg1):** LACP active, ix2+ix3, Po3 upstream. IP 100.101.14.2/28.
- **WANDR (igc0):** Active, 100.101.14.3/28. VPN failover tested. WANDRGW monitoring "Unknown" (GUI fix pending).
- **LANDR (igc1):** Standby, failover script deployed.
- **Default route (S038):** Policy routing via route-to on opt5/opt6. All VMs have internet.
- **VLAN traffic segregation (S039):** ALL 5 PHASES COMPLETE.
- **NFS routing fix (S040):** VMs 101/102 route NFS via switch L3 (static route in /etc/network/interfaces).
- **VM 103 static IP (S041):** Changed from DHCP 10.25.66.10 → static 10.25.66.25. Docker ports (8080/6881/8191) bound to 10.25.66.25 (dirty VLAN only). dhcpcd disabled but lingering from boot — clean on next reboot. Backups: interfaces.backup-S041, docker-compose.yml.backup-S041.
- **pfSense svc-admin (S041):** config.xml cleaned — added `<groupname>admins</groupname>`, removed 2 stale `<item>` bcrypt hashes. Backup: config.xml.backup-s041-user-cleanup.
- **All 5 VMs:** Running, NFS mounted, 16/16 containers healthy (13 original + 3 on VM 103 re-verified).
- **IP binding audit (S041):** All 5 VMs verified. VM 102 all 7 ports on .255.31. VM 105 Web UI on .255.33, server on .10.33. VM 103 now dirty VLAN only. VM 101 host net exception. VM 104 no published ports.

## S3 — Open Risks / Known Issues
- TICKET-0006: Temp password on ALL 10 systems — CRITICAL, 11th session
- F-018: Switch plaintext passwords (P1)
- F-S034-CIPHER: TrueNAS SSH weak ciphers (HIGH, GUI)
- F-S034-NFS-ACL: ha-proxmox-disk NFS export open to * (HIGH, GUI)
- F-S034-GPU: VM 104 vendor-reset needed (HIGH, host reboot required)
- WANDRGW monitoring broken — GUI fix pending
- DR Phase 5b: Gateway group PENDING
- VM 103: dhcpcd lingering from boot — cosmetic, clean on reboot

## S4 — Out-of-Scope Areas
- pve02, VM 100, VMs 800-899, GigeNet

## S5 — Immediate Responsibilities (Next Session)
1. Credential rotation (TICKET-0006) — 11 sessions, CRITICAL
2. F-018 switch plaintext passwords — needs `service password-encryption` + password change
3. Verify VM 103 clean after reboot (static IP, no dhcpcd, ports bound correctly)
4. Cleanup candidates: interfaces.backup-S041 on VM 103, config.xml.backup-s041-user-cleanup on pfSense
5. Dead pfSense rules on opt5/opt6 — remove when next config.xml edit is done

## SESSION LOG
S039-20260223 — Planned: Health check, VLAN traffic segregation / Done: Full health check (10/10 green), pfSense change audit (clean), VLAN segregation 5/5 phases COMPLETE, Lesson #34 added / Next: NFS write failures, credential rotation
S040-20260223 — Planned: NFS audit, fix NFS write failures / Done: NFS share cleaned (1.1GB stale + artifacts removed, backward compat symlinks removed), NFS write failure root-caused (pfSense TCP forwarding) and fixed (static route via switch on VMs 101/102), backup cron fixed (mountpoint→/proc/mounts on 5 VMs), Windows SMB confirmed working, pfSense config backup, Lessons #35-36 added / Next: Credential rotation (TICKET-0006), monitoring, PBS
S041-20260224 — Planned: Continue DC01 overhaul / Done: pfSense svc-admin config.xml cleanup (groupname+stale items), IP binding audit (5/5 VMs), VM 103 DHCP→static 10.25.66.25 + ports bound to dirty VLAN only, all memory files updated / Next: Credential rotation (TICKET-0006), F-018 switch passwords, VM 103 reboot verification
