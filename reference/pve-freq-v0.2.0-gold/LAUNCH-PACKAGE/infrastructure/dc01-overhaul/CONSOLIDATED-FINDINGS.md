# DC01 Overhaul -- Consolidated Findings

> **Generated:** 2026-02-19
> **Sources:** Slop Detector (5 tickets), Compliance (2 reviews), Tuning (notes + playbook), Workflow (notes + backlog)
> **Scope:** DC01 cluster -- pve01, pve03, TrueNAS R530, Cisco 4948E-F, pfSense fw01, VMs 101-105

This is the master reference document. ALL findings from all workers are included without abbreviation.

---

## CRITICAL (P1) -- Must Fix Now

---

### Compliance: AC-03 -- iDRAC Default Passwords on Both Servers

- **Source:** Compliance WORKER1-NOTES.md (AC-03)
- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 9, "Security Posture" table row 8; DC01.md "Cluster Hardening" task 6
- **Description:** Both iDRAC interfaces (10.25.255.10 on R530/TrueNAS, 10.25.255.11 on T620/pve01) are running with default Dell passwords. iDRAC provides full out-of-band management: virtual console, power control, firmware updates, and boot device selection. An attacker on VLAN 2550 (or with inter-VLAN routing access) could fully compromise either server, including injecting firmware-level rootkits.
- **Remediation:**
  1. Change iDRAC passwords via `racadm set iDRAC.Users.2.Password <new-password>` on both servers.
  2. Use a strong, unique password for each iDRAC (minimum 16 characters, stored in VM 802 password vault).
  3. Verify access after change: `racadm -r <ip> -u root -p <new> getinfo`.
  4. Consider disabling unused iDRAC features (virtual media, IPMI over LAN) to reduce attack surface.
  5. Verify: Default credentials should no longer authenticate.

---

### Compliance: DP-01 -- No VM Backup Strategy -- Zero Recovery Capability

- **Source:** Compliance WORKER1-NOTES.md (DP-01)
- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 10; DC01.md "Cluster Hardening" task 9; ARCHITECTURE.md Section 11, "Application Risks" row 1
- **Description:** There are **zero** automated VM backups. No Proxmox Backup Server, no snapshots, no offsite replication. The document explicitly states: "Any catastrophic failure = full rebuild from scratch." This is the single largest risk in the entire infrastructure. A ZFS pool failure, accidental `zfs destroy`, ransomware, or simultaneous PSU failure would result in total, irrecoverable data loss for all VM configs, application state, and media.
- **Remediation:**
  1. **Immediate (24 hours):** Take manual vzdump backups of all in-scope VMs (101-105) to local storage on pve01: `vzdump <vmid> --storage local --mode snapshot`.
  2. **Short-term (1 week):** Deploy Proxmox Backup Server on pve01 or pve03. Allocate a dedicated ZFS dataset for backup storage. Configure nightly automated backups with 7-day retention.
  3. **Medium-term (1 month):** Test restore procedure. Document expected restore time (RTO) and acceptable data loss window (RPO). Consider offsite replication to a second location.
  4. **Verify:** After PBS deployment, perform a test restore of at least one VM to confirm backup integrity.

---

### Compliance: ML-01 -- No Infrastructure Monitoring or Alerting

- **Source:** Compliance WORKER1-NOTES.md (ML-01)
- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 9, table row 9; Section 11, "Application Risks" row 2; DC01.md "Cluster Hardening" task 8
- **Description:** There is **zero** monitoring deployed. No Uptime Kuma, no Prometheus, no Zabbix, no Nagios, nothing. The document explicitly states: "PSU/fan failures, NFS hangs, service outages go undetected. No alerting." The only way to detect a problem is manual observation or service failure reported by end users. Given that PSU 1 on TrueNAS and PSU 2 on pve01 have already failed, the remaining single PSUs could fail at any time with no automated alert.
- **Remediation:**
  1. **Immediate (48 hours):** Deploy Uptime Kuma (lightweight, Docker-based) on any running VM. Add HTTP/TCP checks for: Proxmox API (8006), Plex (32400), all Arr services, NFS mount health (TCP 2049 on TrueNAS).
  2. **Short-term (1 week):** Add IPMI/iDRAC sensor monitoring. iDRAC SNMP traps or `ipmitool sensor` polling for PSU status, fan RPM, and temperatures. Alert on any degradation.
  3. **Medium-term:** Deploy node-exporter + Prometheus on Proxmox hosts for CPU, memory, disk, and network metrics. Add Grafana dashboards for operational visibility.
  4. **Configure alerting:** Email or webhook (Discord, Slack) notifications for all critical alerts. Do not deploy monitoring without alerting -- silent dashboards are useless.
  5. **Verify:** Simulate a failure (stop a Docker container) and confirm an alert fires within the expected time window.

---

### Compliance: PA-01 -- Dual Single-PSU Failure -- Imminent Availability Risk

- **Source:** Compliance WORKER1-NOTES.md (PA-01)
- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 2, "Active Alerts"; Section 11, "Hardware Risks"; DC01.md "Medium-Term" tasks
- **Description:** Both the TrueNAS storage server (R530) and the primary hypervisor (pve01/T620) are running on single PSUs after hardware failures. The replacement parts are documented but NOT ordered. This is not a theoretical risk -- the failures have already occurred. A second PSU failure on either server means: (a) R530: total storage loss, all NFS mounts fail, all services down, ZFS pool import required on recovery; (b) T620: all VMs on pve01 stop (101, 102, 103, 105), only VM 104 on pve03 survives.
- **Remediation:**
  1. **Order replacement parts IMMEDIATELY.** Dell 05RHVVA00 for R530, Dell 06W2PWA00 for T620. This is a procurement action, not a technical one.
  2. Also order R530 Fan 6 replacement (by Service Tag B065ND2).
  3. Until parts arrive and are installed, document this as an accepted critical risk with an estimated remediation date.
  4. Verify: After installation, check iDRAC for "Redundancy Regained" on PSU and Fan status.

---

### Slop Detector: TICKET-0001 -- Lesson #2 Contradicts Lessons #13/#14 (Stale vmbr0.2550 Reference)

- **Source:** Slop Detector TICKET-0001
- **Priority:** P1 (critical)
- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 12, Lesson #2 (line 748)
- **Description:** ARCHITECTURE.md Lesson #2 states: "Management VLAN belongs on sub-interface `vmbr0.2550`, NEVER on vmbr0 itself." Lessons #13 and #14 state: "Fix: assign host IPs to the Proxmox VLAN bridge (e.g., `vmbr0v2550`) instead." An operator following Lesson #2 would recreate the exact failure that Session 17 fixed. The Node Interface Table (Section 3) correctly shows `vmbr0v2550`, so the table and the lesson directly contradict each other within the same document.
- **Recommended Fix:** Amend Lesson #2 to read:
  ```
  Management VLAN belongs on the Proxmox VLAN bridge `vmbr0v2550`, NEVER on
  vmbr0 itself and NEVER on a dot sub-interface like `vmbr0.2550` (see Lessons
  #13/#14 for the split-brain bug that makes dot sub-interfaces unreliable).
  ```
- **Additional Actions:**
  1. Add a cross-reference from Lesson #2 to Lessons #13/#14 so operators cannot read one in isolation.
  2. Consider adding a "DANGER" callout box to Lesson #2 since following the stale wording caused a corosync outage historically.

---

### Workflow: IMP-001 -- Pre-Change Checkpoint Files

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-001)
- **Priority:** P1
- **Affected Workers:** Worker #1 (primary), Master Orchestrator (enforcement)
- **Description:** Any infrastructure change (network, storage, firewall, cluster) must produce a checkpoint file on disk BEFORE the change is applied. This file documents the change intent, the expected before/after state, the rollback procedure, and the out-of-band access path if the change goes wrong. The file is deleted only after the change is verified successful. If a session crashes mid-change, the checkpoint file guides recovery.
- **Suggested Prompt Addition:**
  ```
  RULE: Before executing any infrastructure change, you MUST write a file
  to infra/WIP-<short-name>.md containing:
    - What is being changed (exact device, interface, config file)
    - Current state (exact values before change)
    - Target state (exact values after change)
    - Rollback procedure (step-by-step to restore current state)
    - Out-of-band access path (how to reach the device if the change breaks connectivity)
    - Verification command (how to confirm the change worked)
  Delete this file ONLY after running the verification command successfully.
  If you are starting a session and find an existing WIP-*.md file, STOP.
  Read it, assess the situation, and report to the Orchestrator before proceeding.
  ```

---

### Workflow: IMP-002 -- High-Risk Operation Gate

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-002)
- **Priority:** P1
- **Affected Workers:** Worker #1, Master Orchestrator
- **Description:** Certain operations have caused outages historically (LAGG, vmbr0, corosync, pfSense WAN). These must require explicit human confirmation before execution.
- **Gated Operations List:**
  - Any change to pfSense LAN interface (lagg0, igc3)
  - Any change to vmbr0 address on any Proxmox node
  - Any change to corosync configuration
  - Any change to ZFS pool topology (add/remove vdev, replace disk)
  - Any change to WireGuard VPN endpoint IP
  - Any change to TrueNAS bond0 (LACP configuration)
  - Any change to switch trunk port configuration (Gi1/1, Gi1/2, Gi1/48)
- **Protocol:** Worker writes `workflow/BLOCKED-ON-HUMAN.md`, halts, and reports to the Orchestrator. Does NOT proceed until Sonny explicitly approves.

---

### Workflow: IMP-003 -- Dependency-Ordered Worker Scheduling

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-003)
- **Priority:** P1
- **Description:** The current approach launches all 5 workers in parallel. Workers #2-4 depend on Worker #1's ARCHITECTURE.md, and Worker #5 depends on all outputs. If Worker #1 has not finished when #2-4 start reading, they either block or operate on incomplete data.
- **Suggested Scheduling Protocol:**
  - Phase A: Launch Worker #1 only. Wait for `infra/ARCHITECTURE.md` to appear on disk.
  - Phase B: Launch Workers #2, #3, #4 in parallel. All read Worker #1 output. Wait for all three to write their primary output files.
  - Phase C: Launch Worker #5. Reads all artifacts from Phases A and B.
  - Phase D: Re-launch Worker #1 with instructions to read and address all tickets, compliance notes, and tuning notes. This closes the feedback loop.
  - Phase E: (Optional) Re-launch Worker #5 to assess the quality of the feedback integration.

---

### Workflow: IMP-004 -- Feedback Loop Closure

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-004)
- **Priority:** P1
- **Description:** Worker #2 has filed tickets, but there is no scheduled mechanism for Worker #1 to read and respond to them. Without a response round, tickets accumulate without resolution. The feedback loop is the core value proposition of the multi-worker system.
- **Protocol:**
  1. After Workers #2-4 complete their review pass, re-invoke Worker #1 with instruction to read all files in `tickets/slop-detector/`, `compliance/`, and `tuning/`. For each ticket or note, either apply the fix or write a rebuttal. Update ARCHITECTURE.md and increment version marker.
  2. Re-invoke Worker #2 to verify fixes. Close resolved tickets by renaming to `TICKET-XXXX-RESOLVED.md`. File new tickets for remaining issues.

---

### Workflow: Recommendation #1 -- Schedule Workers in Dependency Order

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #1)
- **Priority:** P1
- **Description:** Same as IMP-003 above. Schedule: A (#1), B (#2-4 parallel), C (#5), D (#1 again).

---

### Workflow: Recommendation #2 -- Require Pre-Change Checkpoint Files

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #2)
- **Priority:** P1
- **Description:** Same as IMP-001 above. Require checkpoint files for any infrastructure modification.

---

### Workflow: Recommendation #3 -- Gate High-Risk Operations on Human Confirmation

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #3)
- **Priority:** P1
- **Description:** Same as IMP-002 above. Certain operations must require Sonny's explicit approval.

---

### Workflow: Recommendation #4 -- Close the Feedback Loop

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #4)
- **Priority:** P1
- **Description:** Same as IMP-004 above. Schedule Worker #1 re-pass to address all tickets.

---

## HIGH (P2) -- Fix Soon

---

### Slop Detector: TICKET-0002 -- Container Image Pinning Stated as Standard but Is Only a TODO

- **Source:** Slop Detector TICKET-0002
- **Priority:** P2 (high)
- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 7, Container Standard table (line 494)
- **Description:** Worker #1 promoted an aspirational hardening task to the status of an established operational standard. The DC01.md Container Standard mentions LSIO images preferred, with no mention of version pinning as a current standard. DC01.md "Cluster Hardening" (line 607) lists "pin image versions" as an unchecked TODO. ARCHITECTURE.md presents it as a plain fact in the Container Standard table. The Security Posture section partially acknowledges it is "not audited," but the Container Standard table presents it without qualification.
- **Recommended Fix:** Remove the `Image pinning` row from the Container Standard table, or change it to:
  ```
  | Image pinning | **NOT YET ENFORCED** -- Pin specific versions, no `:latest` (hardening TODO) |
  ```
- **Additional Actions:**
  1. Ensure Section 9 (Security Posture) and Section 7 (Container Standard) are consistent.
  2. File a separate task for an actual audit of all compose files for `:latest` tags.

---

### Slop Detector: TICKET-0005 -- VLAN 5 NFS Exception IP Discrepancy

- **Source:** Slop Detector TICKET-0005
- **Priority:** P2 (high)
- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 4 (VLAN Map, line 140) and Section 5 (NFS Mount Strategy, lines 312-313)
- **Description:** The VLAN Map row for VLAN 5 says the pfSense NFS exception is for `10.25.25.25` (the VLAN 25 storage IP on bond0). But VLAN 5 VMs actually mount NFS via `10.25.0.25` (the VLAN 1 LAN IP on eno1), using a static route `10.25.0.0/24 via 10.25.5.5` to reach it through the switch SVI. Either: (a) the pfSense exception should be for `10.25.0.25`, (b) there is an additional undocumented exception, or (c) the NFS traffic bypasses pfSense entirely (via the switch SVI static route) and the exception is belt-and-suspenders.
- **Recommended Fix:** Add a clarifying note to the VLAN 5 row:
  ```
  NFS exception (10.25.25.25) allows VLAN 5 VMs to reach TrueNAS storage IP if
  routed through pfSense. In practice, VLAN 5 VMs mount NFS via 10.25.0.25 using
  a static route through the switch SVI (10.25.5.5), bypassing pfSense entirely.
  ```
- **Additional Action:** Verify on pfSense whether the exception is actually for 10.25.25.25 or 10.25.0.25. If the NFS traffic never hits pfSense, the exception may be irrelevant.

---

### Compliance: AC-01 -- SSH Password Authentication Enabled on All Nodes

- **Source:** Compliance WORKER1-NOTES.md (AC-01)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, "Security Posture" table row 1; DC01.md "Cluster Hardening" task 1
- **Description:** All Proxmox nodes (pve01, pve03) and TrueNAS still accept SSH password authentication. Combined with 4 admin accounts (sonny-aif, chrisadmin, donmin, jonnybegood), this creates a brute-force attack surface on every SSH-exposed host. No Fail2ban or equivalent is deployed.
- **Remediation:**
  1. Generate SSH key pairs for each admin. Distribute public keys to `/home/<user>/.ssh/authorized_keys` on pve01, pve03, TrueNAS.
  2. Set `PasswordAuthentication no` and `ChallengeResponseAuthentication no` in `/etc/ssh/sshd_config` on each host.
  3. Restart sshd. Test key-based login BEFORE closing existing sessions.
  4. Deploy Fail2ban on pve01 and pve03 with SSH jail enabled (default 5 retries, 10-minute ban).
  5. Verify: `ssh -o PreferredAuthentications=password <host>` should be rejected.

---

### Compliance: AC-05 -- Proxmox API Accessible From All VLANs

- **Source:** Compliance WORKER1-NOTES.md (AC-05)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, table row 3; DC01.md "Cluster Hardening" task 2
- **Description:** The Proxmox web UI and REST API (port 8006) are accessible from any VLAN, not restricted to the management VLAN (2550). Any VM or compromised container on VLANs 1, 5, 10, or 66 can attempt to authenticate to the hypervisor management plane.
- **Remediation:**
  1. Configure `pveproxy` to bind only to management VLAN addresses. Edit `/etc/default/pveproxy` and set `LISTEN_IP=10.25.255.X`.
  2. Alternatively, use iptables/nftables on each Proxmox host to restrict port 8006 to source IPs in 10.25.255.0/24 and 10.25.100.0/24 (VPN).
  3. Test access from management VLAN and VPN before applying.
  4. Verify: `curl -k https://10.25.0.26:8006` from VLAN 1 should be refused.

---

### Compliance: DP-03 -- HA Shared Storage World-Accessible

- **Source:** Compliance WORKER1-NOTES.md (DP-03)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 5, NFS Exports; Section 8, "Shared Storage for HA"
- **Description:** The `ha-proxmox-disk` export (20 TB, used for Proxmox HA shared storage) is exported with `Networks: *` -- meaning any IP address on any network can mount it read-write. A malicious or misconfigured host could mount this share and corrupt or exfiltrate VM disk data.
- **Remediation:**
  1. Restrict the NFS export to only the Proxmox nodes that participate in HA: `10.25.25.26` (pve01) and `10.25.25.28` (pve03), or their storage VLAN IPs.
  2. Add `all_squash` or at minimum `root_squash` to prevent root-level file manipulation.
  3. Verify Proxmox HA still functions after restricting the export.

---

### Compliance: NS-01 -- Management VLAN Firewall Rules Incomplete

- **Source:** Compliance WORKER1-NOTES.md (NS-01)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, table row 6; Section 4, "WireGuard VPN" reachability table; DC01.md remaining tasks
- **Description:** VLAN 2550 (Management) has a block rule in pfSense but no granular allow rules. The intended design is SSH/HTTPS access from VPN (10.25.100.0/24) and LAN (10.25.0.0/24) only. This is documented as a "Sonny GUI task" and has been pending since Session 16. Until completed, either all management traffic is blocked or inter-VLAN routing via switch SVIs bypasses pfSense entirely.
- **Remediation:**
  1. Complete the pfSense GUI configuration per DC01.md Session 16 "pfSense GUI Steps."
  2. Add Pass rules on MANAGEMENT interface for VPN (10.25.100.0/24) and LAN (10.25.0.0/24) sources ABOVE the block rule.
  3. Add matching rules on WG0 interface for management VLAN destination.
  4. Verify: VPN client can SSH to 10.25.255.26; random VLAN 5 host cannot.

---

### Compliance: NS-03 -- VLAN 66 (Dirty) NFS Access Via Management NIC

- **Source:** Compliance WORKER1-NOTES.md (NS-03)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 5, NFS mount row for VLAN 66; VM 103 fstab
- **Description:** VM 103 (qBittorrent, on the isolated "Dirty" VLAN 66) accesses NFS via 10.25.255.25 (TrueNAS management NIC on VLAN 2550). This creates a Layer 2 path between the dirty/untrusted network segment and the management network. If VM 103 is compromised (it runs a torrent client with VPN, touching untrusted internet traffic), it has network adjacency to the management plane.
- **Remediation:**
  1. Evaluate whether VM 103 truly needs NFS access. If downloads can be written to a local disk and later moved, remove the NFS mount entirely.
  2. If NFS access is required, create a dedicated TrueNAS interface/IP on VLAN 66 (or a new restricted VLAN) with a narrowly-scoped NFS export that only allows the `/Downloads/` subdirectory.
  3. At minimum, restrict the NFS export for nfs-mega-share to exclude 10.25.255.0/24 as a source network for the dirty VM.
  4. Document the risk if the current configuration is accepted.

---

### Compliance: ML-02 -- No Audit Trail for Administrative Actions

- **Source:** Compliance WORKER1-NOTES.md (ML-02)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9; DC01.md change log
- **Description:** No centralized logging or audit trail for administrative actions. SSH logins, sudo usage, Proxmox API calls, and Docker operations are logged locally on each host but there is no aggregation, no retention policy, and no review process. If an admin account is compromised, there would be no practical way to determine what actions were taken.
- **Remediation:**
  1. Configure rsyslog or journald forwarding from pve01, pve03, and TrueNAS to a central log collector.
  2. Retain auth.log and syslog for a minimum of 90 days.
  3. Enable Proxmox task logging and ensure `/var/log/pve/tasks/` is included in backup scope.
  4. Consider deploying Grafana Loki for searchable log aggregation.

---

### Compliance: ML-03 -- No NFS Health Monitoring

- **Source:** Compliance WORKER1-NOTES.md (ML-03)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 11, "Application Risks" row 2; Lessons Learned #3, #4, #8
- **Description:** NFS is the backbone of the entire service stack. The lessons learned section documents multiple NFS failure modes (boot hangs, asymmetric routing, MTU mismatches) but there is no automated check for NFS mount health. A stale NFS mount can cause Docker containers to hang indefinitely.
- **Remediation:**
  1. Create a health check script on each VM: `timeout 5 stat /mnt/truenas/nfs-mega-share/plex/.healthcheck || alert "NFS stale on $(hostname)"`.
  2. Run via cron every 5 minutes. Alert on failure.
  3. Add NFS mount status to Uptime Kuma (when deployed) using a script-based check.

---

### Compliance: VM-01 -- No Fail2ban or Brute-Force Protection

- **Source:** Compliance WORKER1-NOTES.md (VM-01)
- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, table row 2; DC01.md "Cluster Hardening" task 1
- **Description:** No brute-force protection on any SSH-exposed host. With password authentication still enabled (AC-01), this is compounded. Even after SSH keys are deployed, Fail2ban provides defense-in-depth.
- **Remediation:**
  1. Install Fail2ban on pve01 and pve03: `apt install fail2ban`.
  2. Enable the `[sshd]` jail (enabled by default on Debian).
  3. Configure ban time (600s), max retries (5), find time (600s).
  4. Add a jail for Proxmox web UI (port 8006) if a filter exists.
  5. Verify: `fail2ban-client status sshd` should show active jail.

---

### Compliance: Ticket Quality Framework (for Worker #2)

- **Source:** Compliance WORKER2-NOTES.md (Part A)
- **Risk Level:** HIGH (framework -- ensures ticket quality)
- **Description:** Worker #3 defined mandatory ticket fields and quality red flags for evaluating Worker #2's slop detector tickets:
  - **Mandatory fields:** Clear title, description of current/desired state, affected systems/VMs, risk if not addressed, rollback procedure, security implications, dependencies, acceptance criteria.
  - **Red flags:** Generic/vague descriptions, missing rollback, no security impact assessment, incorrect scope (pve02, VM 100, VMs 800-899), missing dependencies, slop indicators (filler text, boilerplate).

---

### Compliance: Security Topics That Must Have Tickets (from WORKER2-NOTES.md Part B)

Worker #3 identified these critical security topics that Worker #2's ticket set must cover. If any are missing from the final ticket set, that is a compliance gap:

1. **VM Backup Deployment (PBS):** No recovery capability exists. Expected scope: PBS deployment target, storage allocation, retention policy, backup schedule, restore test procedure. Must cover local-only configs (Bazarr VM 102, Gluetun VM 103).
2. **Monitoring Deployment:** No detection capability. Expected scope: tool selection, deployment VM, checks to configure, alerting targets. Must include iDRAC IPMI sensor monitoring, SSH auth failure alerting, NFS mount health checks.
3. **iDRAC Password Change:** Default passwords on OOB management. Expected scope: both iDRACs, racadm commands, verification steps. New passwords 16+ chars, unique per device, stored in VM 802.
4. **SSH Hardening + Fail2ban:** Expected scope: key generation, distribution, sshd_config changes, Fail2ban installation and jail configuration. Must include rollback procedure.
5. **Proxmox API Restriction:** Expected scope: pveproxy configuration or iptables on pve01/pve03. Must depend on VPN-to-VLAN-2550 connectivity working first.
6. **NFS Export Hardening:** ha-proxmox-disk is world-accessible (`*`). Expected scope: audit current mount usage, reduce allowed networks, restrict to specific IPs.
7. **pfSense Management VLAN Firewall Rules:** Expected scope: exact pfSense rules, verification steps. This is a dependency for multiple other hardening tasks.

---

### Tuning: NFS Mount Options (Priority 1 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Items 1a-1d), TUNING-PLAYBOOK.md (Phase 1)
- **Expected Gain:** 10-30% NFS throughput
- **Risk Level:** Low
- **Downtime:** Per-VM remount (<1 min each)

#### 1a. Explicit rsize/wsize (1 MB)

On every VM (101-105), update `/etc/fstab`:
```
# Before
10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,defaults 0 0

# After
10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,_netdev,nofail 0 0
```
Apply: `sudo umount /mnt/truenas/nfs-mega-share && sudo mount /mnt/truenas/nfs-mega-share`
Verify: `nfsstat -m` or `mount | grep nfs` -- confirm rsize/wsize show 1048576.
Rollback: Remove `rsize=1048576,wsize=1048576` from fstab. Remount.

#### 1b. nconnect=4 for Multi-Stream NFS

On VMs 101, 104, and 105 (heaviest NFS users), update `/etc/fstab`:
```
10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,nconnect=4,_netdev,nofail 0 0
```
Prerequisite: Kernel >= 5.3 (all VMs run 6.x). TrueNAS needs no config change.
Verify: `cat /proc/mounts | grep nfs` should show `nconnect=4`.
Rollback: Remove `nconnect=4` from fstab. Remount.

#### 1c. Hard Mount with Explicit Timeouts

On all VMs (101-105):
```
10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,nconnect=4,hard,timeo=50,retrans=5,_netdev,nofail 0 0
```
**WARNING:** Do NOT use `soft` mounts. Soft mounts return EIO on timeout, which corrupts Docker container data and can destroy SQLite databases (Lesson #6).
Rollback: Replace `hard,timeo=50,retrans=5` with `defaults` in fstab. Remount.

#### 1d. VM 103 (qBit) Special Case

VM 103 reaches TrueNAS via management NIC (10.25.255.25, eno4, MTU 1500). Same options apply:
```
10.25.255.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,rsize=1048576,wsize=1048576,nconnect=4,hard,timeo=50,retrans=5,_netdev,nofail 0 0
```
The TrueNAS IP stays at 10.25.255.25 per the VLAN 66 isolation design.
Rollback: Revert fstab. Remount.

---

### Tuning: ZFS ARC Maximum Size (Priority 2 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 2a), TUNING-PLAYBOOK.md (Phase 2)
- **Expected Gain:** Significant for Plex reads
- **Risk Level:** Low
- **Downtime:** TrueNAS reboot for persistent setting

**Concrete Commands:**

If TrueNAS SCALE (Linux-based):
```bash
# Check current ARC settings
cat /proc/spl/kstat/zfs/arcstats | grep -E "c_max|c_min|size"
arc_summary

# Set ARC max to 70 GB via GUI: System Settings -> Advanced -> Sysctl
# Add: vfs.zfs.arc_max = 75161927680

# Or immediate (non-persistent):
echo 75161927680 > /sys/module/zfs/parameters/zfs_arc_max
```

If TrueNAS CORE (FreeBSD-based):
```bash
# Via GUI: System -> Tunables -> add vfs.zfs.arc.max = 75161927680
```

70 GB ARC leaves 18 GB for OS, NFS server, SMB, and kernel. TrueNAS manages ARC dynamically.
Rollback: Remove the sysctl entry. Reboot TrueNAS (ARC returns to auto-sizing).

**Also set atime=off:**
```bash
zfs get atime mega-pool/nfs-mega-share
zfs set atime=off mega-pool/nfs-mega-share
# Takes effect immediately for new reads. No downtime.
```
Rollback: `zfs set atime=on mega-pool/nfs-mega-share`

---

### Workflow: Recommendation #5 -- Codify TICKET-0001 Format as Standard Template

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #5)
- **Priority:** P2
- **Description:** TICKET-0001 demonstrates the right format for inter-worker communication: exact file paths and line numbers, verbatim quotes, concrete replacement text, priority level. This format should be codified as the template for all future tickets.

---

### Workflow: IMP-005 -- Context Window Budget Management

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-005)
- **Priority:** P2
- **Description:** DC01.md is 920+ lines, ARCHITECTURE.md is 808 lines, memory notes are 50-75 lines each. Workers spending most context on reference material have limited reasoning capacity.
- **Suggested Change:** Workers should read memory-notes first, read ARCHITECTURE.md section-by-section using line offsets, and grep for specific facts rather than re-reading entire files.

---

### Workflow: IMP-006 -- Scope Enforcement Prompt Hardening

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-006)
- **Priority:** P2
- **Description:** Three distinct scopes exist (DC01, GigeNet, Sonny Homework). Current scope definitions rely on workers reading and respecting them. Need hard-stop triggers when workers start writing about out-of-scope items (10.25.0.27, VM 100, VMs 800-899, GigeNet in non-colocation context, WordPress/cPanel, SABnzbd).

---

### Workflow: IMP-007 -- Standardized File Naming Conventions

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-007)
- **Priority:** P2
- **Description:** File naming is mostly consistent but not codified. Consistent naming makes it easier for workers to discover each other's output via glob patterns.
- **Convention:**
  - `infra/ARCHITECTURE.md` (Worker #1)
  - `infra/WIP-*.md` (checkpoint files)
  - `infra/.READY` (signal file)
  - `tickets/slop-detector/TICKET-XXXX.md` (open tickets)
  - `tickets/slop-detector/TICKET-XXXX-RESOLVED.md` (resolved tickets)
  - `compliance/WORKER1-NOTES.md`, `compliance/WORKER2-NOTES.md` (Worker #3)
  - `tuning/WORKER1-NOTES.md`, `tuning/TUNING-PLAYBOOK.md` (Worker #4)
  - `workflow/WORKFLOW-NOTES.md`, `workflow/IMPROVEMENT-BACKLOG.md` (Worker #5)
  - Workers MUST NOT create files outside their designated directories.

---

### Workflow: IMP-008 -- Reduce Duplication Between Memory Notes and ARCHITECTURE.md

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-008)
- **Priority:** P2
- **Description:** Memory notes are bootstrap artifacts. Once ARCHITECTURE.md is complete, memory notes should be frozen. Workers #2-5 should treat ARCHITECTURE.md as the source of truth and memory notes as supplementary context only.

---

### Workflow: Recommendation #6 -- Add .READY Signal Files for Inter-Worker Handoff

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #6)
- **Priority:** P2
- **Description:** When Worker #1 finishes, it should write `infra/.READY` containing a checksum or line count so reviewers can verify they are reading the complete document.

---

### Workflow: Recommendation #7 -- Introduce BLOCKED-ON-HUMAN.md Protocol

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #7)
- **Priority:** P2
- **Description:** Define protocol for human decision points. Workers write `workflow/BLOCKED-ON-HUMAN.md` and stop when they encounter operations requiring Sonny's input.

---

### Workflow: Recommendation #8 -- Restore Access to Original Source Documents

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #8)
- **Priority:** P2
- **Description:** Original CLAUDE.md and DC01.md files are not present in the working directory. Memory notes are lossy compressions (920 lines to ~63 lines). Worker #2 needs ground truth for verification. Source documents must remain accessible.

---

## MEDIUM (P3) -- Should Fix

---

### Slop Detector: TICKET-0003 -- Lesson #12 Uses Vague "switch port" Instead of Correct Gi1/10

- **Source:** Slop Detector TICKET-0003
- **Priority:** P3 (medium)
- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`, Section 12, Lesson #12 (line 778)
- **Description:** DC01.md Lesson #12 references old port `Gi1/25`, which is stale after Session 17 cable move to `Gi1/10`. ARCHITECTURE.md attempted to fix by making the reference generic ("switch port"), introducing vagueness into an operational lesson. The switch port map in Section 4 correctly identifies Gi1/10.
- **Recommended Fix:** Update Lesson #12 to:
  ```
  R530 has no dedicated iDRAC port -- iDRAC shares eno1's physical port (LOM1).
  To isolate iDRAC to VLAN 2550: configure Gi1/10 as trunk (native VLAN 1,
  allowed 2550), enable iDRAC VLAN tagging via `racadm set iDRAC.NIC.VLanID 2550`
  + `VLanEnable Enabled`.
  ```
- **Additional Action:** Add a note that this was originally Gi1/25 and moved to Gi1/10 in Session 17.

---

### Slop Detector: TICKET-0004 -- Missing WSL Workstation Section, svc-admin UID, and Lesson #10 Detail

- **Source:** Slop Detector TICKET-0004
- **Priority:** P3 (medium)
- **File:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md` -- multiple sections

#### 4a. WSL Workstation Section (Omitted Entirely)

DC01.md includes a full section documenting the WSL workstation: hostname `wsl-debian`, user uid=3000/gid=950, SMB mount at `/mnt/smb-sonny` with credentials file, auto-mount via `.bashrc`, and symlinks. This is the operator's primary admin interface. Omitting it means ARCHITECTURE.md is incomplete as an operational reference.
**Fix:** Add a WSL Workstation section covering: hostname, user, VPN config path, SMB mount point, and `.bashrc` auto-mount behavior.

#### 4b. svc-admin UID 3003

DC01.md line 273: `svc-admin | UID 3003 (created via GUI, standardization to 2550 deprioritized)`. ARCHITECTURE.md mentions `sonny-aif` UID 3000 and `truenas_admin` gid 950 but never documents the `svc-admin` service account on TrueNAS.
**Fix:** Add `svc-admin (UID 3003)` to the TrueNAS section or a user accounts reference table.

#### 4c. Lesson #10 Detail Truncated

DC01.md Lesson #10: "`allFunctions=1` is rejected by pvesh schema -- edit the config file directly or use semicolon-separated function list in the host field." ARCHITECTURE.md Lesson #10 omits this detail entirely.
**Fix:** Append the truncated text to Lesson #10.

---

### Compliance: AC-02 -- NOPASSWD Sudo Without Scope Restriction

- **Source:** Compliance WORKER1-NOTES.md (AC-02)
- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 3; DC01.md "Proxmox Cluster" section
- **Description:** sonny-aif has NOPASSWD sudo on pve01 and pve03. svc-admin (UID 3003) has NOPASSWD sudo "everywhere." Neither account's sudo privileges are scoped to specific commands. Any compromised session has full root access.
- **Remediation:**
  1. Audit `/etc/sudoers.d/` on pve01 and pve03 for all NOPASSWD entries.
  2. Scope sudo to specific commands (e.g., `systemctl`, `docker`, `qm`, `pvesh`) rather than blanket `ALL`.
  3. If blanket NOPASSWD is required for automation, document justification and ensure SSH key is passphrase-protected.
  4. Remove NOPASSWD from sonny-aif once svc-admin standardization is complete.

---

### Compliance: AC-04 -- Four Admin Accounts With No Role Differentiation

- **Source:** Compliance WORKER1-NOTES.md (AC-04)
- **Risk Level:** MEDIUM
- **Description:** Four accounts have admin-level Proxmox access: sonny-aif, chrisadmin, donmin, jonnybegood. No documented role differentiation, no evidence of which are actively used, no access review policy. VMs 800-899 are "NOT ours" and donmin has VMs, suggesting shared-tenancy with unclear boundaries.
- **Remediation:**
  1. Audit last-login times for all four accounts (`lastlog`, `last`).
  2. Disable accounts not used in 90+ days.
  3. Document each account's purpose and access scope.
  4. Consider Proxmox permission pools to restrict non-primary admins.
  5. Establish quarterly access review cadence.

---

### Compliance: DP-02 -- NFS Export Overly Permissive (7 Networks)

- **Source:** Compliance WORKER1-NOTES.md (DP-02)
- **Risk Level:** MEDIUM
- **Description:** `nfs-mega-share` is exported to 7 networks including 172.28.16.0/20 (WSL Docker bridge?). `ha-proxmox-disk` uses `*` with rw access and no squash. Any device on any allowed network can read/write all production data.
- **Remediation:**
  1. Audit which networks actually mount `nfs-mega-share`. Remove 172.28.16.0/20 if no longer needed.
  2. Restrict `ha-proxmox-disk` from `*` to specific Proxmox node IPs: `10.25.25.26/32, 10.25.25.28/32`.
  3. Add `root_squash` to `ha-proxmox-disk` if Proxmox does not require root-level NFS access.
  4. Document minimum required network access for each export.
  5. Verify: NFS mount from unlisted network should fail.

---

### Compliance: DP-04 -- No Encryption at Rest or In Transit

- **Source:** Compliance WORKER1-NOTES.md (DP-04)
- **Risk Level:** MEDIUM
- **Description:** NFS traffic uses NFSv3 with no encryption. Data on ZFS pool is not encrypted at rest. At a colocation facility with shared physical access, network sniffing and physical disk theft are risks.
- **Remediation:**
  1. **In-transit (medium-term):** Evaluate migration to NFSv4 with Kerberos.
  2. **At-rest (low priority):** ZFS native encryption on new datasets.
  3. **Pragmatic alternative:** Ensure VLAN 25 remains strictly isolated. Document as accepted risk with compensating controls.

---

### Compliance: DP-05 -- Local-Only Configs Without Backup (Bazarr, Gluetun)

- **Source:** Compliance WORKER1-NOTES.md (DP-05)
- **Risk Level:** MEDIUM
- **Description:** Bazarr config at `/opt/bazarr-config` (VM 102) and Gluetun VPN state at `/home/sonny-aif/qbit-stack/config` (VM 103) are on local VM disks only. Not covered by NFS/ZFS redundancy.
- **Remediation:**
  1. Include these paths in PBS backup scope when deployed.
  2. Interim: cron job to rsync to NFS share (e.g., `/mnt/truenas/nfs-mega-share/plex/backups/local-configs/`).
  3. Verify: After cron setup, confirm backup files are present and recent.

---

### Compliance: NS-02 -- NFS Traffic Traverses Non-Storage VLANs

- **Source:** Compliance WORKER1-NOTES.md (NS-02)
- **Risk Level:** MEDIUM
- **Description:** VMs on VLANs 1, 5, and 10 mount NFS via TrueNAS's VLAN 1 IP (10.25.0.25/eno1), not through the dedicated storage VLAN (25). Production NFS traffic shares the LAN VLAN with general server traffic.
- **Remediation:**
  1. Accept as a known risk with documentation, OR plan a migration where each VM gets a VLAN 25 NIC for storage traffic.
  2. Existing TrueNAS static routes and switch SVI routing are correctly configured as compensating controls.

---

### Compliance: NS-04 -- pve03 Split-Brain VLAN Risk Unresolved

- **Source:** Compliance WORKER1-NOTES.md (NS-04)
- **Risk Level:** MEDIUM
- **Description:** pve03 has the same split-brain VLAN bug that broke VLAN 2550, but for VLANs 25 and 5. If any VM is added to pve03 using VLAN 25 or 5 on vmbr0, host-level connectivity on those VLANs will break.
- **Remediation:**
  1. Rename `vmbr0.25` to `vmbr0v25` and `vmbr0.5` to `vmbr0v5` on pve03.
  2. Test storage connectivity after rename.
  3. Complete BEFORE any new VMs are deployed on pve03.

---

### Compliance: PA-02 -- pve03 Consumer-Grade Hardware With No Out-of-Band Management

- **Source:** Compliance WORKER1-NOTES.md (PA-02)
- **Risk Level:** MEDIUM
- **Description:** pve03 (Asus B550-E) is consumer hardware with no IPMI/iDRAC. Recovery requires physical console access at colocation. This node is the current HA master and hosts VM 104 (Tdarr with GPU passthrough). Single 1 GbE NIC carries all traffic.
- **Remediation:**
  1. Document as accepted risk.
  2. Ensure HA fencing (watchdog) is configured so pve01 can assume HA master role if pve03 becomes unresponsive (VM 104 cannot migrate due to GPU passthrough).
  3. Long-term: replace with server-grade hardware with IPMI.

---

### Compliance: CM-01 -- No Formal Change Approval Process

- **Source:** Compliance WORKER1-NOTES.md (CM-01)
- **Risk Level:** MEDIUM
- **Description:** Changes are documented after the fact. No pre-change approval, no peer review, no scheduled maintenance windows.
- **Remediation:**
  1. For production-affecting changes, require documentation of: what will change, expected impact, rollback procedure BEFORE the change.
  2. Use ticket system to formalize -- each change should have a ticket with these fields.
  3. For emergency changes, document within 24 hours with a post-incident note.

---

### Compliance: CM-03 -- Rollback Procedures Are Ad-Hoc

- **Source:** Compliance WORKER1-NOTES.md (CM-03)
- **Risk Level:** MEDIUM
- **Description:** Rollback relies on manually-created backup directories (e.g., `~/backup-pve01-network-session17/`). No standardized rollback procedure, no tested restore path.
- **Remediation:**
  1. Standardize pre-change backup location (e.g., `/var/backups/changes/<date>/`).
  2. Include rollback commands in change documentation.
  3. Test rollback of at least one configuration change per quarter.

---

### Compliance: VM-02 -- Cisco IOS Switch -- Patch Status Unknown

- **Source:** Compliance WORKER1-NOTES.md (VM-02)
- **Risk Level:** MEDIUM
- **Description:** Cisco 4948E-F running IOS 15.2(4)E10a. End-of-Sale 2016, End-of-Support 2021. No longer receiving security patches. The switch is the core of all VLAN segmentation and L3 routing.
- **Remediation:**
  1. Check Cisco Security Advisory page for CVEs affecting IOS 15.2(4)E on 4948E-F.
  2. Evaluate compensating controls (ACLs, disabling unused features).
  3. Long-term: plan replacement with supported switch platform.
  4. Immediate: ensure switch management restricted to SSH via pve01 jump host only.

---

### Compliance: VM-04 -- Docker Image Version Pinning Not Audited

- **Source:** Compliance WORKER1-NOTES.md (VM-04)
- **Risk Level:** MEDIUM
- **Reference:** DC01.md "Cluster Hardening" task 3
- **Description:** Policy states "Pin specific versions, no `:latest`" and LSIO preferred, but this is "not audited." Running `:latest` means silent updates with potential vulnerabilities or breaking changes.
- **Remediation:**
  1. Audit all 5 compose files: `grep -r ':latest' /mnt/truenas/nfs-mega-share/plex/docker-compose*.yml /mnt/truenas/nfs-mega-share/plex/downloader-data/docker-compose*.yml`.
  2. Replace `:latest` tags with specific version strings (e.g., `lscr.io/linuxserver/sonarr:4.0.11`).
  3. Establish monthly update cadence: review release notes, update pins, test.
  4. Consider Watchtower or Diun for update notifications (notify only, not auto-update).

---

### Compliance: Additional Security Review Areas (from WORKER2-NOTES.md Part C)

1. **Credential Rotation Policy:** No documented policy for rotating SSH keys, Proxmox passwords, or service API keys. Arr stack inter-service API keys may be static since initial deployment.
2. **Container Privilege Audit:** No audit performed. Specifically check: Does Tdarr Node (VM 104) run privileged for GPU access? Does Gluetun (VM 103) require NET_ADMIN? Each privileged container should have documented justification.
3. **Incident Response Plan:** No documented procedure for: compromised VM, ransomware on NFS, failed ZFS pool, WireGuard key compromise. At minimum document who to contact, containment steps, evidence preservation, recovery procedure.
4. **Network Segmentation Verification:** VLAN segmentation is designed but pfSense rules have gaps. A ping/curl test from each VLAN to destinations that should be blocked would confirm isolation.
5. **Orphaned VLAN Cleanup:** VLANs 113 and 715 exist on the switch with no ports assigned and no documentation. Investigate and either document or remove.
6. **SMB Share Security:** SMB share was found to contain a Vaultwarden master password in plaintext (removed in Session 17). A full audit of SMB share contents for residual secrets should be performed. SMB authentication and access control should be documented.
7. **Backup Integrity Testing:** When PBS is deployed, schedule quarterly restore tests. Include: restoring VM to test ID, verifying services start, verifying NFS mounts reconnect. Document expected RTO and RPO.

---

### Tuning: TCP Buffer Sizes on Proxmox Hosts and VMs (Priority 3 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Items 3a-3b), TUNING-PLAYBOOK.md (Phase 3)
- **Expected Gain:** 5-10% concurrent I/O
- **Risk Level:** Low
- **Downtime:** None (sysctl -p)

On pve01, pve03, and VMs 101-105, create `/etc/sysctl.d/99-nfs-tuning.conf`:
```bash
# TCP buffer sizes: min, default, max (bytes)
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 1048576 16777216
net.ipv4.tcp_wmem = 4096 1048576 16777216

# NFS-specific: increase socket backlog
net.core.netdev_max_backlog = 5000
```
Apply: `sysctl -p /etc/sysctl.d/99-nfs-tuning.conf`
Verify: `sysctl net.core.rmem_max net.core.wmem_max`
Rollback: Delete `/etc/sysctl.d/99-nfs-tuning.conf` and run `sysctl --system`.

---

### Tuning: NIC Offload Verification (Priority 4 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 3c)
- **Expected Gain:** 0-30% if offloads are disabled
- **Risk Level:** Low
- **Downtime:** None

```bash
# On pve01:
ethtool -k nic0 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"
ethtool -k nic1 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"

# On TrueNAS:
ethtool -k eno1 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"
ethtool -k eno2 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"
ethtool -k eno3 | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksum"

# If any are off, enable:
ethtool -K nic0 tso on gso on gro on
```
Persist via `/etc/network/interfaces` post-up script or TrueNAS GUI tunable.
Rollback: `ethtool -K nic0 tso off gso off gro off`

---

### Tuning: Disable Memory Ballooning (Priority 5 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 4d), TUNING-PLAYBOOK.md (Phase 4)
- **Expected Gain:** Stability improvement (eliminates latency spikes)
- **Risk Level:** Low
- **Downtime:** VM restart

```bash
# On pve01:
qm set 101 --balloon 0
qm set 102 --balloon 0
qm set 103 --balloon 0
qm set 105 --balloon 0
# Do NOT touch VM 802 (Sonny only)
```
With 256 GB on pve01 and <40 GB allocated, there is zero risk of memory pressure.
Rollback: `qm set 101 --balloon 1024` (or original value).

---

### Tuning: Tdarr Worker Limit for pve03 Stability (Priority 6 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 5b)
- **Expected Gain:** pve03 NIC stability
- **Risk Level:** Low
- **Downtime:** None

In Tdarr Web UI (http://10.25.10.33:8265):
- Navigate to node "Radeon-RX580|6Core"
- Set GPU workers to 1
- Set CPU workers to 0 (GPU-only transcoding)
- Enable "Limit concurrent file moves" if available

Rollback: Increase GPU workers back to previous value.

---

### Tuning: NUMA Pinning (Priority 7 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 4c), TUNING-PLAYBOOK.md (Phase 4)
- **Expected Gain:** 5-15% NFS latency reduction
- **Risk Level:** Medium
- **Downtime:** VM restart

```bash
# On pve01, identify NUMA topology:
numactl --hardware
# Expect: 2 nodes (2x E5-2620 v0), 12 CPUs each

# Identify which NUMA node owns the storage NIC:
cat /sys/class/net/nic1/device/numa_node

# Pin Plex (VM 101) to the NUMA node that owns nic1:
qm set 101 --numa 1
# In /etc/pve/qemu-server/101.conf:
# numa0: cpus=0-5,hostnodes=0,memory=8192,policy=preferred
```
Start with VM 101 only. Incorrect pinning can cause CPU contention.
Rollback: `qm set 101 --numa 0`

---

### Tuning: Interrupt Coalescing on Storage NICs (Priority 8 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 3d)
- **Expected Gain:** CPU overhead reduction (30-50% interrupt rate reduction)
- **Risk Level:** Low
- **Downtime:** None

```bash
# On pve01 storage NIC:
ethtool -c nic1  # Record current values first
ethtool -C nic1 rx-usecs 50 tx-usecs 50

# On TrueNAS bond0 members:
ethtool -C eno2 rx-usecs 50 tx-usecs 50
ethtool -C eno3 rx-usecs 50 tx-usecs 50
```
Persist on Proxmox via `/etc/network/interfaces`:
```
post-up ethtool -C nic1 rx-usecs 50 tx-usecs 50
```
Rollback: `ethtool -C nic1 rx-usecs 3 tx-usecs 3` (capture defaults before changing).

---

### Tuning: LACP Bond Hash Policy Optimization (Priority 9 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Items 6a-6b)
- **Expected Gain:** Better bond member distribution
- **Risk Level:** Medium
- **Downtime:** Brief NFS interruption (bond0 restart)

**First: Measure current distribution (diagnostic, read-only):**
```bash
# On TrueNAS:
cat /proc/net/bonding/bond0
cat /sys/class/net/eno2/statistics/rx_bytes
cat /sys/class/net/eno3/statistics/rx_bytes
cat /sys/class/net/eno2/statistics/tx_bytes
cat /sys/class/net/eno3/statistics/tx_bytes
```
If one member carries >70% of traffic, change is worthwhile.

**Then: Change hash policy (maintenance window required):**
- TrueNAS GUI: Network -> Interfaces -> bond0 -> Edit -> Change from LAYER2+3 to LAYER3+4
- Cisco switch must match: `(config)# port-channel load-balance src-dst-ip`
- **CRITICAL:** Switch and TrueNAS MUST use compatible hash policies.

Rollback: Change hash back to LAYER2+3 via TrueNAS GUI. Switch: `port-channel load-balance src-dst-mac`.

---

### Tuning: pve03 QoS Traffic Prioritization (Priority 10 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 5a)
- **Expected Gain:** Corosync heartbeat protection against NIC saturation
- **Risk Level:** Medium
- **Downtime:** None (additive)

Create `/etc/network/if-up.d/qos-pve03` on pve03:
```bash
#!/bin/bash
if [ "$IFACE" != "nic0" ]; then exit 0; fi

tc qdisc add dev nic0 root handle 1: htb default 30
tc class add dev nic0 parent 1: classid 1:1 htb rate 1000mbit
tc class add dev nic0 parent 1:1 classid 1:10 htb rate 100mbit ceil 200mbit prio 1
tc class add dev nic0 parent 1:1 classid 1:20 htb rate 700mbit ceil 900mbit prio 2
tc class add dev nic0 parent 1:1 classid 1:30 htb rate 200mbit ceil 500mbit prio 3

tc filter add dev nic0 parent 1:0 protocol 802.1Q prio 1 u32 \
    match u16 0x09F6 0x0FFF at -4 flowid 1:10
tc filter add dev nic0 parent 1:0 protocol 802.1Q prio 2 u32 \
    match u16 0x0019 0x0FFF at -4 flowid 1:20
```
`chmod +x /etc/network/if-up.d/qos-pve03`
Rollback: `tc qdisc del dev nic0 root`

---

### Tuning: ZFS Recordsize Alignment (Priority 11 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 2b)
- **Expected Gain:** 5-10% sequential reads for new files
- **Risk Level:** Medium (small files waste space at 1 MB recordsize)
- **Downtime:** None (new writes only)

**Simpler approach (change existing dataset -- only affects new writes):**
```bash
zfs get recordsize mega-pool/nfs-mega-share
zfs set recordsize=1M mega-pool/nfs-mega-share
```

**Ideal approach (separate media dataset):**
```bash
zfs create -o recordsize=1M mega-pool/nfs-mega-share/media
# Then move Movies/, TV/, Audio/ into this sub-dataset
```
Rollback: `zfs set recordsize=128K mega-pool/nfs-mega-share` (only affects future writes).

---

### Tuning: pve03 Second NIC via USB 3.0 (Priority 12 tuning item)

- **Source:** Tuning WORKER1-NOTES.md (Item 5c)
- **Expected Gain:** Eliminates single-NIC bottleneck
- **Risk Level:** Medium
- **Downtime:** Hardware purchase + configuration

1. Purchase USB 3.0 Gigabit Ethernet adapter (Realtek RTL8153 chipset).
2. Connect to VLAN 25 access port (e.g., Gi1/12, already configured as Storage-VLAN25).
3. Configure on pve03 in `/etc/network/interfaces`:
   ```
   auto enx<mac>
   iface enx<mac> inet manual
       mtu 9000

   auto vmbr1
   iface vmbr1 inet manual
       bridge-ports enx<mac>
       bridge-stp off
       bridge-fd 0
       mtu 9000

   auto vmbr1.25
   iface vmbr1.25 inet static
       address 10.25.25.29/24
       mtu 9000
   ```
4. Migrate VM 104's NFS mount to use 10.25.25.25 over VLAN 25 on new NIC.

Rollback: Unplug USB adapter, revert `/etc/network/interfaces`, remount NFS to old path.

---

### Tuning: Plex RAM Increase (from RAM Allocation Review)

- **Source:** Tuning WORKER1-NOTES.md (Item 4b)
- **Expected Gain:** Better metadata indexing and transcoder cache
- **Risk Level:** Low
- **Downtime:** VM restart

```bash
# On pve01:
qm set 101 --memory 16384
# Requires VM restart
```
16 GB is recommended minimum for large Plex libraries. pve01 has abundant RAM.
Rollback: `qm set 101 --memory 8192` and restart VM.

---

### Tuning: ZFS Prefetch Verification (Priority check)

- **Source:** Tuning WORKER1-NOTES.md (Item 2c)
- **Risk Level:** Low

```bash
# On TrueNAS:
sysctl vfs.zfs.prefetch_disable    # FreeBSD CORE
cat /sys/module/zfs/parameters/zfs_prefetch_disable  # Linux SCALE
# Should be 0 (prefetch enabled). If 1, fix it:
echo 0 > /sys/module/zfs/parameters/zfs_prefetch_disable  # SCALE
```
If prefetch was disabled (unlikely), enabling it dramatically improves sequential read throughput.

---

### Tuning: VM 103 TCP Window Scaling Verification (Priority check)

- **Source:** Tuning WORKER1-NOTES.md (Item 3e)
- **Risk Level:** Low

```bash
# On VM 103:
sysctl net.ipv4.tcp_window_scaling   # Should be 1
sysctl net.ipv4.tcp_timestamps       # Should be 1
sysctl net.ipv4.tcp_sack             # Should be 1
```
If any are 0, set to 1 via `/etc/sysctl.d/99-nfs-tuning.conf`.

---

### Workflow: IMP-009 -- Ticket Actionability Standard

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-009)
- **Priority:** P3
- **Description:** No formal standard for what makes a ticket "actionable." A template ensures consistent quality.
- **Suggested Template:** Priority, File, Section, Line(s), What ARCHITECTURE.md Says, What DC01.md Says, Diagnosis, Recommended Fix, Verification.

---

### Workflow: IMP-010 -- Human (Sonny) Integration Points

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-010)
- **Priority:** P3
- **Description:** No explicit protocol for when to pause and wait for human input.
- **Sonny-Only Actions:** pfSense GUI configuration, hardware ordering, Bazarr UI reconfiguration, scope decisions, iDRAC password changes (requires physical/console access), root SSH on pfSense, budget/purchasing decisions.
- **Format:** When a worker encounters a dependency, write `> **BLOCKED ON SONNY:** <description>` and continue with other work.

---

### Workflow: IMP-011 -- Session Observability and Logging

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-011)
- **Priority:** P3
- **Description:** No record of what an agent was doing when a session crashes. Add lightweight session markers: `> **Session started:** <timestamp> | Task: <description>` at start, `> **Session ended:** <timestamp> | Completed: <done>` at end, and progress markers during high-risk operations.

---

### Workflow: IMP-012 -- Source Document Preservation

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-012)
- **Priority:** P3
- **Description:** Same as Recommendation #8 above. Keep copies of CLAUDE.md, DC01.md in `dc01-overhaul/source/` as read-only reference. Never delete source documents until workflow is complete.

---

### Workflow: Recommendation #9 -- Schedule Periodic Worker #5 Re-Assessments

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #9)
- **Priority:** P3
- **Description:** Worker #5's analysis is necessarily incomplete (can only evaluate artifacts that exist at read time). Schedule follow-up Worker #5 passes after each full round.

---

### Workflow: Recommendation #10 -- Define Update Protocol for ARCHITECTURE.md

- **Source:** Workflow WORKFLOW-NOTES.md (Section 9, Recommendation #10)
- **Priority:** P3
- **Description:** At 808 lines, ARCHITECTURE.md will be difficult to keep current. Any infrastructure change should trigger an update. Without a defined update protocol, the document will drift from reality within weeks.

---

## LOW (P4) -- Nice to Have

---

### Compliance: CM-02 -- Lessons Learned Document Is Excellent But Not Automated

- **Source:** Compliance WORKER1-NOTES.md (CM-02)
- **Risk Level:** LOW
- **Description:** The 16 lessons learned are comprehensive, specific, and actionable, but they depend on humans reading and remembering them. Several describe failure modes that could be detected by automated checks.
- **Remediation:**
  1. Create automated pre-flight checks:
     - Script to verify all fstab NFS entries contain `_netdev,nofail`.
     - Script to verify MTU consistency across all interfaces.
     - Script to verify no SQLite databases exist on NFS mounts.
  2. Run after any configuration change. Include in a future CI/CD or cron-based validation pipeline.

---

### Compliance: VM-03 -- pfSense on FreeBSD 16.0 -- Verify Patch Currency

- **Source:** Compliance WORKER1-NOTES.md (VM-03)
- **Risk Level:** LOW
- **Description:** pfSense Plus on FreeBSD 16.0 should be verified as current. pfSense handles WAN exposure, WireGuard, and all inter-VLAN firewall policy.
- **Remediation:**
  1. Verify pfSense version via GUI: System > Update.
  2. Subscribe to pfSense security advisories.
  3. Schedule quarterly updates during maintenance windows.

---

### Compliance: VM-05 -- TrueNAS SSH Permanently Enabled

- **Source:** Compliance WORKER1-NOTES.md (VM-05)
- **Risk Level:** LOW
- **Description:** TrueNAS SSH remains enabled at all times. The hardening plan calls for disabling it when not in active use.
- **Remediation:**
  1. After completing all pending TrueNAS configuration tasks, disable SSH via TrueNAS GUI.
  2. Document a procedure to re-enable SSH when needed.
  3. Low priority relative to other findings but should be part of final hardening sweep.

---

### Workflow: IMP-013 -- Architecture Document Versioning

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-013)
- **Priority:** P4
- **Description:** ARCHITECTURE.md will be updated multiple times across feedback rounds. Without version markers, reviewers cannot know which version they assessed.
- **Suggested Change:** Add a version header with changelog:
  ```
  > **Version:** 1.0 (initial draft)
  > **Changelog:**
  > - v1.0 (2026-02-19): Initial architecture document from DC01.md
  > - v1.1 (2026-02-19): Applied TICKET-0001 fix (Lesson #2 correction)
  ```

---

### Workflow: IMP-014 -- Automated Consistency Checks

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-014)
- **Priority:** P4
- **Description:** Some of Worker #2's checks could be automated with scripts. Example patterns to search for:
  - `vmbr0.2550` (should be vmbr0v2550)
  - `vmbr0.25` (should be vmbr0v25 on pve03 if used as host IP)
  - `:latest` in Docker image references
  - Any IP in 10.25.0.27 range (pve02, out of scope)
  - "VM 100" or "SABnzbd" outside Out of Scope section

---

### Workflow: IMP-015 -- Multi-Round Convergence Metric

- **Source:** Workflow IMPROVEMENT-BACKLOG.md (IMP-015)
- **Priority:** P4
- **Description:** No defined convergence criterion. The review-fix cycle stops when: Worker #2 has zero open P1/P2 tickets, Worker #3 has no new CRITICAL/HIGH findings, Worker #4's recommendations are applied or explicitly deferred, and Worker #5 confirms no systemic workflow issues. If after 3 rounds criteria are not met, escalate to Sonny.

---

## Tuning: Important Warnings (Apply to ALL Tuning Items)

1. **Never change multiple tunables simultaneously.** Always: baseline -> change one -> measure -> decide -> rollback or keep.
2. **TrueNAS PSU 1 is FAILED. Fan 6 is DEAD.** Any tuning that increases TrueNAS workload should be accompanied by thermal monitoring. Order replacement parts FIRST.
3. **pve01 PSU 2 is FAILED.** Increased compute load = higher power draw on single remaining PSU.
4. **Do not use `soft` NFS mounts.** Ever. Lesson #6 (SQLite corruption). `hard` mounts are the only safe option.
5. **Jumbo frames are fragile.** Any MTU change must be verified end-to-end (Lesson #8). Do not touch MTU values.
6. **VM 103 NFS path (eno4, MTU 1500) is inherently slower.** By design (VLAN 66 isolation). Do not route VM 103 NFS traffic over bond0/VLAN 25.

---

## Tuning: Baseline Measurement Protocol (Run BEFORE Any Changes)

From the TUNING-PLAYBOOK.md, run ALL baselines before tuning:

| Metric | Tool | Run On | Duration |
|---|---|---|---|
| NFS sequential read throughput | `fio --rw=read --bs=1M` | VM 101 | 60 sec |
| NFS sequential write throughput | `fio --rw=write --bs=1M` | VM 103 | 60 sec |
| NFS concurrent read throughput | `fio --rw=read --numjobs=4` | VM 101 | 60 sec |
| NFS latency (avg + p99) | `nfsiostat 5 12` | VM 101, VM 104 | 60 sec |
| ZFS ARC hit rate | `arc_summary` | TrueNAS | Snapshot |
| ZFS pool IOPS | `zpool iostat -v mega-pool 5 12` | TrueNAS | 60 sec |
| Network throughput (raw) | `iperf3 -c <ip> -t 30` | pve01, pve03 | 30 sec |
| Host CPU utilization | `mpstat -P ALL 5 6` | pve01, pve03 | 30 sec |

---

## Tuning: Priority Implementation Order Summary

| Priority | Item | Expected Gain | Risk | Downtime |
|---|---|---|---|---|
| 1 | NFS mount options (1a-1d) | 10-30% NFS throughput | Low | Per-VM remount (<1 min each) |
| 2 | ZFS ARC tuning (2a) | Significant for Plex reads | Low | TrueNAS reboot for persistent |
| 3 | TCP buffer sizes (3a-3b) | 5-10% concurrent I/O | Low | None (sysctl -p) |
| 4 | NIC offload verification (3c) | 0-30% if disabled | Low | None |
| 5 | Disable ballooning (4d) | Stability improvement | Low | VM restart |
| 6 | Tdarr worker limit (5b) | pve03 stability | Low | None |
| 7 | NUMA pinning (4c) | 5-15% NFS latency | Medium | VM restart |
| 8 | Interrupt coalescing (3d) | CPU overhead reduction | Low | None |
| 9 | LACP hash policy (6a) | Better bond distribution | Medium | Brief NFS interruption |
| 10 | pve03 QoS (5a) | Corosync protection | Medium | None (additive) |
| 11 | ZFS recordsize (2b) | 5-10% sequential reads | Medium | None (new writes only) |
| 12 | USB NIC for pve03 (5c) | Eliminates bottleneck | Medium | Hardware purchase + config |

---

## Compliance: Prioritized Remediation Roadmap

### Phase 1: Immediate (0-48 hours) -- Stop the Bleeding

1. **PA-01:** Order PSU and fan replacement parts (procurement, zero downtime risk).
2. **DP-01:** Take manual vzdump backups of VMs 101-105 RIGHT NOW.
3. **AC-03:** Change iDRAC passwords on both servers (15-minute task via racadm).
4. **ML-01:** Deploy Uptime Kuma with basic HTTP/TCP checks (1-2 hours).

### Phase 2: Short-Term (1-2 weeks) -- Core Hardening

5. **AC-01 + VM-01:** Deploy SSH key-only auth + Fail2ban on all hosts.
6. **AC-05:** Restrict Proxmox API to management VLAN.
7. **NS-01:** Complete pfSense management VLAN firewall rules (Sonny GUI task).
8. **DP-01:** Deploy PBS with automated nightly backups.
9. **DP-03:** Restrict HA NFS export from `*` to specific node IPs.

### Phase 3: Medium-Term (1 month) -- Operational Maturity

10. **ML-02:** Deploy centralized log aggregation.
11. **ML-03:** Implement NFS health monitoring with alerting.
12. **DP-02:** Audit and reduce NFS export network list.
13. **NS-03:** Redesign dirty VLAN NFS access path.
14. **NS-04:** Preemptive VLAN fix on pve03.
15. **VM-04:** Audit and pin all Docker image versions.
16. **AC-02 + AC-04:** Scope sudo privileges, audit admin accounts.

### Phase 4: Long-Term (Quarterly) -- Continuous Improvement

17. **CM-01:** Formalize change management with ticket-based approval.
18. **CM-02:** Automate lessons-learned validation checks.
19. **VM-02:** Plan switch replacement (EOL hardware).
20. **DP-04:** Evaluate NFSv4 + Kerberos for encrypted NFS.

---

## Workflow: Overall Assessment Summary

- **Overall grade from Worker #5: B+.** Architecture is solid, review loop has started, but no completed feedback cycle yet.
- **Key strengths:** Clear role separation, file-based communication, explicit scope boundaries, exemplary ticket format, grounded architecture document, TASKBOARD provides global state.
- **Key weaknesses:** No completed feedback loop, context window pressure, no checkpoint/resume protocol, duplication between memory notes and ARCHITECTURE.md, parallel workers cannot see each other's in-progress work, no structured error escalation path, source documents not accessible.
- **LAGG disaster root causes:** No pre-flight safety gate, no documented rollback plan, session crash = total context loss, no WIP marker file.

---

## Compliance: Positive Observations

Worker #1's ARCHITECTURE.md deserves recognition:

1. **Radical transparency:** PSU failures, missing backups, default passwords, and incomplete hardening are all documented openly.
2. **VLAN segmentation is well-designed:** Six VLANs with distinct security policies, purpose-built for different trust levels. Dirty VLAN (66) with separate NAT VIP is particularly good.
3. **Lessons learned are operationally valuable:** 16 specific, incident-driven lessons that prevent repeat failures.
4. **NFS squash configuration:** `all_squash` to a single gid prevents privilege escalation via NFS.
5. **WireGuard for remote access:** Not exposing SSH directly to the internet.
6. **DNS hardening on VLAN 5:** `chattr +i` on resolv.conf prevents DNS hijacking.

---

## Master Findings Count

| Priority | Infra/Compliance | Slop Detector | Tuning | Workflow | Total |
|---|---|---|---|---|---|
| P1 (Critical) | 4 | 1 | 0 | 4 | **9** |
| P2 (High) | 8 | 2 | 2 | 4 | **16** |
| P3 (Medium) | 13 | 2 | 10 | 4 | **29** |
| P4 (Low) | 3 | 0 | 0 | 3 | **6** |
| **Total** | **28** | **5** | **12** | **11** | **60** |

---

*End of consolidated findings. This document incorporates ALL findings from: 5 slop detector tickets, 2 compliance reviews, tuning notes + playbook, and workflow notes + improvement backlog.*
