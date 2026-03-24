# Worker #2 — Quality & Compliance Engineer — Memory Notes

## S1 — What I Read
- CLAUDE.md, TASKBOARD.md (full state through S041)
- DC01.md (updated through S041)

## S2 — Current DC01 State
- LACP stable since S036, WAN LAG operational, DR Phases 1-4 COMPLETE
- S039 VLAN traffic segregation COMPLETE — all data traffic on correct VLANs
- S040 NFS write failure fixed, backup cron reliability fixed
- S041 pfSense svc-admin config.xml cleaned — was missing groupname, had stale item tags
- S041 VM 103: DHCP→static 10.25.66.25. Docker ports bound to dirty VLAN only. Verified: .66.25:8080=200, .255.32:8080=000
- S041 IP binding audit: 5/5 VMs verified correct. All Web UIs on management VLAN (.255.X) except approved exceptions (VM 101 host net, VM 103 dirty VLAN)
- All 16/16 containers running across 5 VMs

## S3 — Open Risks / Known Issues
- **CRITICAL:** TICKET-0006 temp password on ALL 10 systems (11th session since exposure)
- **P1:** F-018 switch plaintext passwords — `service password-encryption` + password change needed
- **HIGH:** F-S034-CIPHER TrueNAS SSH weak ciphers (GUI fix)
- **HIGH:** F-S034-NFS-ACL ha-proxmox-disk NFS export open to * (GUI fix)
- **HIGH:** F-S034-GPU VM 104 vendor-reset needed (host reboot required)
- **MEDIUM:** WANDRGW monitoring broken (GUI fix — set Monitor IP)
- **LOW:** F-021 TrueNAS IPv6 web listeners (cannot fix via middleware, no IPv6 routing)
- **S039 persistence checks still pending:** pfSense STORAGE rule, TrueNAS post-init script (id=2)
- **S040 persistence pending:** Static routes on VMs 101/102 — verify persist across VM reboot
- **S041:** VM 103 dhcpcd lingering — cosmetic, clean on reboot. Verify after reboot.

## S4 — Out-of-Scope Areas
- pve02, VM 100, VMs 800-899, GigeNet

## S5 — Immediate Responsibilities
1. Track TICKET-0006 aging — 11 sessions is CRITICAL
2. Validate S041: VM 103 reboot cleans dhcpcd, static IP takes over, ports stay bound to .66.25
3. Validate S040: static routes persist on VMs 101/102 after reboot
4. Validate S039: pfSense STORAGE rule and TrueNAS post-init script survive reboot
5. Compliance gate for any new work next session

## SESSION LOG
S039-20260223 — Planned: Compliance monitoring, finding aging / Done: Validated VLAN segregation changes, exceptions documented, S039 findings tracked / Next: TICKET-0006 escalation, validate persistence of new rules
S040-20260223 — Planned: NFS audit compliance / Done: NFS write failure resolved (switch L3 routing), backup cron reliability fixed, NFS share cleaned, dead pfSense rules assessed, Lessons #35-36 tracked / Next: TICKET-0006 escalation, persistence validation
S041-20260224 — Planned: Compliance monitoring / Done: IP binding audit (5/5 VMs verified), VM 103 finding resolved (ports now dirty VLAN only), pfSense svc-admin config.xml validated / Next: TICKET-0006 (11 sessions), reboot verification backlog (VM 103, VMs 101/102, pfSense STORAGE rule, TrueNAS post-init)
