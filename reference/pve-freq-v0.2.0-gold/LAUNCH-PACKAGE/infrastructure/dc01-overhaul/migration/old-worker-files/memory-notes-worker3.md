# Worker #3 — SOC Compliance Engineer — Memory Notes
> Session 25 (2026-02-20) — FRESH REBUILD
> Source: All memory files read (LOCAL-FIRST, SMB-FALLBACK)

---

## SECTION 1 — What I Read (LOCAL vs SMB)

| File | Source | Found |
|------|--------|-------|
| CLAUDE.md | SMB (symlink) | YES |
| DC01.md | SMB | YES |
| GigeNet.md | SMB | YES |
| Sonny-Homework-OutOfScope.md | SMB | YES |
| TASKBOARD.md | LOCAL | YES |
| compliance/WORKER1-NOTES.md | LOCAL | YES |
| compliance/WORKER2-NOTES.md | LOCAL | YES |
| CONSOLIDATED-FINDINGS.md | LOCAL | YES |
| INC-001-LAGG-VLAN1-OUTAGE.md | LOCAL | YES |

SMB Status: MOUNTED and accessible.

---

## SECTION 2 — Current DC01 State (Compliance Focus)

### Critical Compliance Gaps (from CONSOLIDATED-FINDINGS.md)
1. **AC-03 (CRITICAL): iDRAC default passwords.** Both servers (10.25.255.10 R530, 10.25.255.11 T620) running default Dell iDRAC passwords. Full out-of-band management exposure. Remediation: racadm password change + disable unused features.
2. **DP-01 (CRITICAL): No VM backup strategy.** Zero automated backups. No PBS. No snapshots. No offsite replication. Total loss scenario on any catastrophic failure.
3. **ML-01 (CRITICAL): No monitoring or alerting.** Zero monitoring deployed. PSU failures, NFS hangs, service outages go undetected.
4. **PA-01 (CRITICAL): Dual single-PSU failure.** Both production servers on single PSUs. Replacement parts documented but NOT ordered.

### Access Control State
- sonny-aif: NOPASSWD sudo on pve01, pve03, and all VMs. To be revoked after SSH key exchange (future project).
- svc-admin (UID 3003, GID 950): NOPASSWD sudo everywhere. Docker group on all VMs. Proxmox PAM admin.
- TrueNAS: sonny-aif has sudo (password required via -S, not NOPASSWD).
- SSH: Password auth enabled everywhere. Key-only auth is a future project.
- Root passwords: Same default across VMs (d0n0t4g3tm3!). pfSense, pve01, pve03, TrueNAS have separate passwords.

### Credential Exposure History
- **Session 23:** WireGuard private key exposed in chat. Keypair regeneration pending.
- **Session 24:** pfSense root, pve01 root, pve03 root, TrueNAS admin, VMs root passwords exposed in chat.
- **Session 25:** Same 5 passwords exposed AGAIN in chat. NOT written to disk. **3rd consecutive session with credential exposure.**
- Tdarr API key found in Phase 5 base_config compose backup (Session 24) — redacted.

### Change Management
- Phase 5 base_config created (92 files, 1.1MB on NFS). This is the first repeatable backup.
- INC-001 (LAGG) has formal incident record. Contributing factors documented.
- Pre-change checkpoint protocol (IMP-001) proposed but not yet enforced.
- High-risk operation gate (IMP-002) proposed but not yet enforced.

### Network Security
- pfSense: Firewall rules in place for all VLANs. WireGuard VPN rules pass to all VLANs.
- Management VLAN (2550): Access from VPN (10.25.100.0/24) and LAN. Block-all-else.
- VLAN isolation rules not yet hardened (future project: VLAN 5 only to storage, VLAN 10 local-only).
- No IDS/IPS deployed.

---

## SECTION 3 — Open Risks / Known Issues (Compliance)

1. **CRITICAL: Credential rotation overdue.** 5 system passwords + 1 WG keypair need immediate rotation. Exposure in 3 consecutive chat sessions.
2. **CRITICAL: No backup = no recovery.** DP-01 remains the #1 risk to the entire infrastructure.
3. **CRITICAL: No monitoring = blind operations.** ML-01 means failures are discovered by user impact, not proactive detection.
4. **HIGH: iDRAC default passwords.** AC-03 is a direct compromise vector for anyone on VLAN 2550 or with inter-VLAN routing access.
5. **HIGH: LACP cutover is a high-risk operation.** INC-001 documents previous outage. Compliance requires: pre-change checkpoint (IMP-001), human approval gate (IMP-002), incident file update.
6. **MEDIUM: SSH password auth everywhere.** Future hardening project. Key-only auth not yet deployed.
7. **MEDIUM: NOPASSWD sudo for sonny-aif.** Overly permissive. To be revoked after SSH key exchange.

---

## SECTION 4 — Out-of-Scope Areas

- pve02 (10.25.0.27) — entirely out of scope
- VM 100 (SABnzbd) — Sonny's homework
- VMs 800-899 — not ours
- GigeNet client systems — only when explicitly client-scoped
- Worker #3 writes to compliance/ directory ONLY. No infra changes. No tickets.

---

## SECTION 5 — My Immediate Responsibilities This Session

1. **Monitor credential hygiene.** Flag any new credential exposures immediately. Continue recommending rotation for the 5+1 exposed credentials.
2. **Compliance gate for LACP cutover.** If LACP is attempted this session, ensure: incident file updated pre-change, checkpoint file created (per IMP-001), human approval obtained (per IMP-002).
3. **Audit any new files** created this session for credential content before they're finalized.
4. **Update compliance/WORKER1-NOTES.md** with any new findings about Worker #1's infrastructure changes.
5. **Track IMP-001 and IMP-002 enforcement status.** These are proposed P1 improvements that would significantly reduce risk.

---

## SESSION LOG

Session 19 – Planned: Initial compliance audit / Done: compliance/WORKER1-NOTES.md and WORKER2-NOTES.md written (AC-01 through AC-05, DP-01, ML-01, PA-01)
Session 21 – Planned: LACP compliance review / Done: errdisable auto-recovery recommendation implemented
Session 22 – Planned: Phase 0-4 compliance / Done: Memory rebuilt
Session 24 – Planned: Phase 5 credential scan / Done: 1 finding (Tdarr API key), 91 files clean
Session 25 – Planned: Startup, credential tracking, LACP compliance prep / Done: Memory rebuilt. Creds exposed 3rd session running. IMP-001 checkpoint created. IMP-002 gate exercised (Sonny deferred LACP). / Next: Ensure LACP follows checkpoint file. Credential rotation still overdue (5 pw + 1 WG keypair).
