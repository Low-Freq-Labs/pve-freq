# SOC Compliance Review: Worker #2 Tickets (Slop Detector)

> **Reviewer:** Worker #3 (SOC Compliance Engineer)
> **Ticket directory reviewed:** `/home/sonny-aif/dc01-overhaul/tickets/slop-detector/`
> **Date:** 2026-02-19

---

## Status: No Tickets Found

As of this review, the `/home/sonny-aif/dc01-overhaul/tickets/slop-detector/` directory is **empty**. Worker #2 has not yet produced tickets (workers are running in parallel). This document provides:

1. A framework for reviewing Worker #2's tickets when they appear.
2. Security-focused areas that tickets MUST address.
3. Criteria for evaluating ticket quality from a compliance perspective.

---

## Part A: Ticket Quality Assessment Framework

When Worker #2's tickets appear, each should be evaluated against these criteria:

### Mandatory Fields (Per Ticket)

| Field | Why It Matters (SOC perspective) |
|---|---|
| Clear title | Enables triage and prioritization |
| Description of current state | Establishes baseline for change |
| Description of desired state | Defines success criteria |
| Affected systems/VMs | Scopes blast radius |
| Risk if not addressed | Enables prioritization |
| Rollback procedure | Required for change management compliance |
| Security implications | Ensures security is not an afterthought |
| Dependencies on other tickets | Prevents out-of-order execution that could break things |
| Acceptance criteria | Defines how to verify the change worked |

### Quality Red Flags to Watch For

- **Generic/vague descriptions:** "Harden SSH" without specifying which hosts, what settings, and how to verify.
- **Missing rollback:** Any ticket that changes network config, NFS exports, or firewall rules WITHOUT a rollback procedure is non-compliant.
- **No security impact assessment:** Every ticket should state whether the change increases, decreases, or has no effect on the security posture.
- **Incorrect scope:** Tickets that reference out-of-scope systems (pve02, VM 100, VMs 800-899) violate the defined boundaries.
- **Missing dependencies:** For example, a ticket to restrict Proxmox API to VLAN 2550 depends on VPN-to-VLAN-2550 connectivity working first. If dependencies are not stated, execution order errors will cause outages.
- **"Slop" indicators:** Filler text, generic boilerplate, recommendations that contradict the documented infrastructure (e.g., suggesting a technology not in the stack), or copy-paste from templates without customization to this specific environment.

---

## Part B: Security Topics That Tickets MUST Cover

Based on the compliance review of ARCHITECTURE.md (see WORKER1-NOTES.md), Worker #2's tickets should address at minimum the following security-critical areas. If any of these are missing from the ticket set, that is a compliance gap in the ticket system itself.

### Critical Priority (Must Have Tickets)

#### 1. VM Backup Deployment (PBS)

- **Why:** No recovery capability exists. This is the #1 operational risk.
- **Expected ticket scope:** PBS deployment target, storage allocation, retention policy, backup schedule, restore test procedure.
- **Security angle:** Backups must cover local-only configs (Bazarr on VM 102, Gluetun on VM 103). Backup storage should be access-restricted (not world-readable NFS).

#### 2. Monitoring Deployment

- **Why:** No detection capability for hardware failures, service outages, or security incidents.
- **Expected ticket scope:** Tool selection (Uptime Kuma recommended in DC01.md), deployment VM, checks to configure, alerting targets (email, webhook).
- **Security angle:** Must include iDRAC IPMI sensor monitoring (PSU/fan/temp), SSH auth failure alerting, NFS mount health checks.

#### 3. iDRAC Password Change

- **Why:** Default passwords on out-of-band management interfaces = full server compromise risk.
- **Expected ticket scope:** Both iDRACs (10.25.255.10, 10.25.255.11), racadm commands, verification steps.
- **Security angle:** New passwords must be strong (16+ chars), unique per device, stored in password vault (VM 802).

### High Priority (Should Have Tickets)

#### 4. SSH Hardening + Fail2ban

- **Why:** Password auth + no brute-force protection = unnecessarily large attack surface.
- **Expected ticket scope:** Key generation, key distribution to pve01/pve03/TrueNAS, sshd_config changes, Fail2ban installation and jail configuration.
- **Security angle:** Must include a rollback procedure (keep one session open during sshd restart), and must test key-based auth BEFORE disabling passwords.

#### 5. Proxmox API Restriction

- **Why:** Hypervisor management plane is accessible from all VLANs.
- **Expected ticket scope:** pveproxy configuration or iptables rules on pve01/pve03 to restrict port 8006 to VLAN 2550 + VPN.
- **Security angle:** Must depend on ticket for pfSense VPN-to-2550 firewall rules being completed first. Otherwise, restricting API to VLAN 2550 while VPN cannot reach VLAN 2550 = lockout.

#### 6. NFS Export Hardening

- **Why:** ha-proxmox-disk is world-accessible (`*`), nfs-mega-share allows 7 networks including WSL Docker bridge.
- **Expected ticket scope:** Audit current mount usage, reduce allowed networks, restrict ha-proxmox-disk to specific IPs.
- **Security angle:** Must verify all existing mounts still work after restriction. Include rollback (re-add network to export if a mount breaks).

#### 7. pfSense Management VLAN Firewall Rules

- **Why:** Management VLAN access control is incomplete (Sonny GUI task).
- **Expected ticket scope:** Exact pfSense rules to add (documented in DC01.md Session 16), verification steps.
- **Security angle:** This is a dependency for multiple other hardening tasks (API restriction, monitoring access).

### Medium Priority (Should Have Tickets)

#### 8. PSU Replacement Parts Procurement

- **Why:** Hardware redundancy is zero on 2 of 3 critical servers.
- **Expected ticket scope:** Part numbers (already documented), ordering action, installation verification.
- **Security angle:** Availability is a pillar of security. This is a procurement ticket, not a technical one, but it must exist in the tracking system.

#### 9. Docker Image Version Audit and Pinning

- **Why:** `:latest` tags create uncontrolled change and potential vulnerability introduction.
- **Expected ticket scope:** Audit all 5 compose files, document current versions, replace `:latest` with pinned versions.
- **Security angle:** Include a process for monthly version review.

#### 10. pve03 Split-Brain VLAN Preemptive Fix

- **Why:** Known bug that will break storage/public VLAN connectivity if triggered.
- **Expected ticket scope:** Rename vmbr0.25 to vmbr0v25, vmbr0.5 to vmbr0v5 on pve03, with pre-change backup and post-change verification.
- **Security angle:** Network disruptions can mask security incidents and prevent management access.

#### 11. Dirty VLAN NFS Path Redesign

- **Why:** VM 103 (untrusted) has network adjacency to management VLAN via NFS.
- **Expected ticket scope:** Evaluate alternatives (local downloads, dedicated NFS interface), implement chosen approach.
- **Security angle:** This violates the isolation principle of the dirty VLAN. The current design creates a lateral movement path from compromised torrent client to management network.

#### 12. Centralized Log Aggregation

- **Why:** No audit trail for admin actions across distributed hosts.
- **Expected ticket scope:** Syslog forwarding from all hosts to central collector, retention policy, search capability.
- **Security angle:** Required for incident response. Without logs, a breach cannot be investigated.

---

## Part C: Additional Security-Focused Review Areas

These are topics that may not be obvious from the infrastructure documentation but should be considered in any complete ticket set:

### 1. Credential Rotation Policy

- No documented policy for rotating SSH keys, Proxmox passwords, or service API keys.
- Arr stack services (Prowlarr, Sonarr, Radarr) have inter-service API keys that may be static since initial deployment.
- Plex token and PLEX_CLAIM process is documented but other service credentials are not inventoried.

### 2. Container Privilege Audit

- The standard says "no privileged unless required" but no audit has been performed.
- Specifically check: Does the Tdarr Node container (VM 104) run privileged for GPU access? Does Gluetun (VM 103) require NET_ADMIN capability?
- Each privileged container should have documented justification.

### 3. Incident Response Plan

- No documented procedure for: compromised VM, ransomware on NFS, failed ZFS pool, WireGuard key compromise.
- At minimum, document: (a) who to contact, (b) immediate containment steps, (c) evidence preservation, (d) recovery procedure.
- This does not need to be enterprise-grade, but "what do we do if X happens" for the top 5 failure scenarios should exist.

### 4. Network Segmentation Verification

- VLAN segmentation is designed but pfSense rules have gaps (management VLAN incomplete).
- A penetration-test-style verification should confirm: (a) VLAN 66 truly cannot reach RFC1918 addresses (except documented NFS path), (b) VLAN 10 truly has no internet, (c) VLAN 25 is truly isolated.
- This can be as simple as `ping` and `curl` tests from each VLAN to destinations that should be blocked.

### 5. Orphaned VLAN Cleanup

- VLANs 113 and 715 exist on the switch with no ports assigned and no documentation.
- These should be investigated and either documented or removed. Orphaned VLANs can be reactivated by anyone with switch access.

### 6. SMB Share Security

- The SMB share (`smb-share`) is used for Jarvis memory logs and was found to contain a **Vaultwarden master password in plaintext** (removed in Session 17 per DC01.md).
- A full audit of SMB share contents for residual secrets should be performed.
- SMB authentication and access control should be documented.

### 7. Backup Integrity Testing

- When PBS is deployed, a quarterly restore test should be scheduled.
- The restore test should include: (a) restoring a VM to a test ID, (b) verifying services start, (c) verifying NFS mounts reconnect.
- Document expected RTO (Recovery Time Objective) and RPO (Recovery Point Objective).

---

## Review Cadence

This document should be updated when:

1. Worker #2's tickets appear in `/home/sonny-aif/dc01-overhaul/tickets/slop-detector/` -- perform initial quality assessment.
2. Any hardening task from the remediation roadmap is completed -- verify and close the corresponding finding.
3. New infrastructure changes are made -- assess for new compliance gaps.

---

*End of SOC compliance review for Worker #2 tickets. This document will be updated when tickets are available for review.*
