# SOC Compliance Review: ARCHITECTURE.md (Worker #1 Output)

> **Reviewer:** Worker #3 (SOC Compliance Engineer)
> **Document reviewed:** `/home/sonny-aif/dc01-overhaul/infra/ARCHITECTURE.md`
> **Baseline:** `DC01.md.bak` (Session 18 rewrite, ground truth)
> **Date:** 2026-02-19

---

## Review Summary

Worker #1 produced a thorough, well-structured architecture document that accurately reflects the DC01 infrastructure as documented in DC01.md. The document is honest about security gaps and does not paper over them. However, the infrastructure it describes has **significant security and operational deficiencies** that represent real risk to production data and services.

**Overall risk posture: HIGH.** Two critical-severity findings (no backups, no monitoring) combined with multiple high-severity access control gaps create a compounding risk where a single hardware failure or security incident could result in undetectable, unrecoverable data loss.

---

## Findings by SOC Control Domain

### 1. ACCESS CONTROL (AC)

#### AC-01: SSH Password Authentication Enabled on All Nodes

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, "Security Posture" table row 1; DC01.md "Cluster Hardening" task 1
- **Description:** All Proxmox nodes (pve01, pve03) and TrueNAS still accept SSH password authentication. Combined with 4 admin accounts (sonny-aif, chrisadmin, donmin, jonnybegood), this creates a brute-force attack surface on every SSH-exposed host. No Fail2ban or equivalent is deployed.
- **Remediation:**
  1. Generate SSH key pairs for each admin. Distribute public keys to `/home/<user>/.ssh/authorized_keys` on pve01, pve03, TrueNAS.
  2. Set `PasswordAuthentication no` and `ChallengeResponseAuthentication no` in `/etc/ssh/sshd_config` on each host.
  3. Restart sshd. Test key-based login BEFORE closing existing sessions.
  4. Deploy Fail2ban on pve01 and pve03 with SSH jail enabled (default 5 retries, 10-minute ban).
  5. Verify: `ssh -o PreferredAuthentications=password <host>` should be rejected.

#### AC-02: NOPASSWD Sudo Without Scope Restriction

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 3, "Admins" note; DC01.md "Proxmox Cluster" section
- **Description:** sonny-aif has NOPASSWD sudo on pve01 and pve03. The DC01.md notes that svc-admin (UID 3003) has NOPASSWD sudo "everywhere" as the intended power user. Neither account's sudo privileges are scoped to specific commands. Any compromised session with these credentials has full root access.
- **Remediation:**
  1. Audit `/etc/sudoers.d/` on pve01 and pve03 for all NOPASSWD entries.
  2. Scope sudo to specific commands needed for operations (e.g., `systemctl`, `docker`, `qm`, `pvesh`) rather than blanket `ALL`.
  3. If blanket NOPASSWD is required for automation, document the justification and ensure the account's SSH key is passphrase-protected.
  4. Remove NOPASSWD from sonny-aif once svc-admin standardization is complete (as planned in DC01.md).

#### AC-03: iDRAC Default Passwords on Both Servers

- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 9, "Security Posture" table row 8; DC01.md "Cluster Hardening" task 6
- **Description:** Both iDRAC interfaces (10.25.255.10 on R530/TrueNAS, 10.25.255.11 on T620/pve01) are running with default Dell passwords. iDRAC provides full out-of-band management: virtual console, power control, firmware updates, and boot device selection. An attacker on VLAN 2550 (or with inter-VLAN routing access) could fully compromise either server, including injecting firmware-level rootkits.
- **Remediation:**
  1. Change iDRAC passwords via `racadm set iDRAC.Users.2.Password <new-password>` on both servers.
  2. Use a strong, unique password for each iDRAC (minimum 16 characters, stored in VM 802 password vault).
  3. Verify access after change: `racadm -r <ip> -u root -p <new> getinfo`.
  4. Consider disabling unused iDRAC features (virtual media, IPMI over LAN) to reduce attack surface.
  5. Verify: Default credentials should no longer authenticate.

#### AC-04: Four Admin Accounts With No Role Differentiation

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 3; DC01.md "Proxmox Cluster" section
- **Description:** Four accounts have admin-level Proxmox access: sonny-aif, chrisadmin, donmin, jonnybegood. There is no documented role differentiation, no evidence of which accounts are actively used, and no access review policy. The DC01.md notes VMs 800-899 are "NOT ours" and donmin has VMs, suggesting shared-tenancy with unclear boundaries.
- **Remediation:**
  1. Audit last-login times for all four accounts on pve01 and pve03 (`lastlog`, `last`).
  2. Disable accounts that have not been used in 90+ days.
  3. Document each account's purpose and access scope.
  4. Consider implementing Proxmox permission pools to restrict non-primary admins to their own VMs only.
  5. Establish a quarterly access review cadence.

#### AC-05: Proxmox API Accessible From All VLANs

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, table row 3; DC01.md "Cluster Hardening" task 2
- **Description:** The Proxmox web UI and REST API (port 8006) are accessible from any VLAN, not restricted to the management VLAN (2550). This means any VM or compromised container on VLANs 1, 5, 10, or 66 can attempt to authenticate to the hypervisor management plane.
- **Remediation:**
  1. On pve01 and pve03, configure `pveproxy` to bind only to management VLAN addresses. Edit `/etc/default/pveproxy` and set `LISTEN_IP=10.25.255.X`.
  2. Alternatively, use iptables/nftables on each Proxmox host to restrict port 8006 to source IPs in 10.25.255.0/24 and 10.25.100.0/24 (VPN).
  3. Test access from management VLAN and VPN before applying. Ensure no operational workflows depend on LAN access to the API.
  4. Verify: `curl -k https://10.25.0.26:8006` from VLAN 1 should be refused.

---

### 2. DATA PROTECTION (DP)

#### DP-01: No VM Backup Strategy -- Zero Recovery Capability

- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 10; DC01.md "Cluster Hardening" task 9; ARCHITECTURE.md Section 11, "Application Risks" row 1
- **Description:** There are **zero** automated VM backups. No Proxmox Backup Server, no snapshots, no offsite replication. The document explicitly states: "Any catastrophic failure = full rebuild from scratch." This is the single largest risk in the entire infrastructure. A ZFS pool failure, accidental `zfs destroy`, ransomware, or simultaneous PSU failure would result in total, irrecoverable data loss for all VM configs, application state, and media.
- **Remediation:**
  1. **Immediate (24 hours):** Take manual vzdump backups of all in-scope VMs (101-105) to local storage on pve01. This provides at least one recovery point: `vzdump <vmid> --storage local --mode snapshot`.
  2. **Short-term (1 week):** Deploy Proxmox Backup Server on pve01 or pve03. Allocate a dedicated ZFS dataset for backup storage. Configure nightly automated backups with 7-day retention.
  3. **Medium-term (1 month):** Test restore procedure. Document expected restore time (RTO) and acceptable data loss window (RPO). Consider offsite replication to a second location.
  4. **Verify:** After PBS deployment, perform a test restore of at least one VM to confirm backup integrity.

#### DP-02: NFS Export Overly Permissive (7 Networks)

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 5, "NFS Export Configuration"; DC01.md "Cluster Hardening" task 4
- **Description:** The primary NFS share (`nfs-mega-share`) is exported to 7 networks including 172.28.16.0/20 (WSL Docker bridge?) and all operational VLANs. The `ha-proxmox-disk` NFS export uses `*` (world-accessible) with rw access and no squash. Any device on any allowed network can read/write all production data.
- **Remediation:**
  1. Audit which networks actually mount `nfs-mega-share`. Remove 172.28.16.0/20 if no longer needed (WSL Docker network is ephemeral).
  2. Restrict `ha-proxmox-disk` from `*` to specific Proxmox node IPs: `10.25.25.26/32, 10.25.25.28/32` (storage VLAN addresses only).
  3. Add `root_squash` to `ha-proxmox-disk` if Proxmox does not require root-level NFS access.
  4. Document minimum required network access for each export.
  5. Verify: Attempt NFS mount from a network not in the allowed list; should fail.

#### DP-03: HA Shared Storage World-Accessible

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 5, NFS Exports; Section 8, "Shared Storage for HA"
- **Description:** The `ha-proxmox-disk` export (20 TB, used for Proxmox HA shared storage) is exported with `Networks: *` -- meaning any IP address on any network can mount it read-write. This is the storage backing HA VM disk images. A malicious or misconfigured host could mount this share and corrupt or exfiltrate VM disk data.
- **Remediation:**
  1. Restrict the NFS export to only the Proxmox nodes that participate in HA: `10.25.25.26` (pve01) and `10.25.25.28` (pve03), or their storage VLAN IPs.
  2. Add `all_squash` or at minimum `root_squash` to prevent root-level file manipulation.
  3. Verify Proxmox HA still functions after restricting the export.

#### DP-04: No Encryption at Rest or In Transit

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Sections 5 and 6 (NFS configuration); DC01.md storage section
- **Description:** NFS traffic uses NFSv3 with no encryption (no Kerberos/GSSAPI). Data on the ZFS pool is not encrypted at rest (no ZFS native encryption or LUKS). At a colocation facility where physical access is shared, this means: (a) anyone with access to the network segment can sniff NFS traffic, and (b) physical disk theft would expose all data.
- **Remediation:**
  1. **In-transit (medium-term):** Evaluate migration to NFSv4 with Kerberos for authenticated, encrypted NFS. This is a significant effort given the number of mount points.
  2. **At-rest (low priority for colocation):** ZFS native encryption on new datasets. Existing data would require pool recreation.
  3. **Pragmatic alternative:** Ensure VLAN 25 (storage) remains strictly isolated. The VLAN segmentation provides a degree of network-level protection. Document this as an accepted risk with compensating controls.

#### DP-05: Local-Only Configs Without Backup (Bazarr, Gluetun)

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 7, Bazarr and qBittorrent details; Section 10, "Recovery Gaps"
- **Description:** Bazarr config at `/opt/bazarr-config` (VM 102) and Gluetun VPN state at `/home/sonny-aif/qbit-stack/config` (VM 103) are on local VM disks only. These are not covered by NFS/ZFS redundancy. If either VM's disk fails, these configs are lost.
- **Remediation:**
  1. Include these paths in the PBS backup scope when deployed (covered by full VM backup).
  2. In the interim, create a cron job to rsync these directories to a location on the NFS share (e.g., `/mnt/truenas/nfs-mega-share/plex/backups/local-configs/`).
  3. Verify: After cron setup, confirm backup files are present and recent.

---

### 3. NETWORK SECURITY (NS)

#### NS-01: Management VLAN Firewall Rules Incomplete

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, table row 6; Section 4, "WireGuard VPN" reachability table; DC01.md remaining tasks
- **Description:** VLAN 2550 (Management) has a block rule in pfSense but no granular allow rules. The intended design is SSH/HTTPS access from VPN (10.25.100.0/24) and LAN (10.25.0.0/24) only. This is documented as a "Sonny GUI task" and has been pending since Session 16. Until completed, either (a) all management traffic is blocked by pfSense (limiting remote management), or (b) inter-VLAN routing via switch SVIs bypasses pfSense entirely (removing firewall oversight).
- **Remediation:**
  1. Complete the pfSense GUI configuration per the steps documented in DC01.md (Session 16, "pfSense GUI Steps").
  2. Specifically: add Pass rules on MANAGEMENT interface for VPN (10.25.100.0/24) and LAN (10.25.0.0/24) sources ABOVE the block rule.
  3. Add matching rules on WG0 interface for management VLAN destination.
  4. After rules are applied, verify: VPN client can SSH to 10.25.255.26; random VLAN 5 host cannot.

#### NS-02: NFS Traffic Traverses Non-Storage VLANs

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 5, "NFS Mount Strategy Per VLAN"; TrueNAS NIC Inventory
- **Description:** VMs on VLANs 1, 5, and 10 mount NFS via TrueNAS's VLAN 1 IP (10.25.0.25/eno1), not through the dedicated storage VLAN (25). Only Proxmox host-level mounts use VLAN 25 (10.25.25.25/bond0). This means production NFS traffic shares the LAN VLAN with general server traffic, reducing the isolation benefit of having a dedicated storage network.
- **Remediation:**
  1. This is a design constraint documented in ARCHITECTURE.md -- VMs cannot directly reach VLAN 25 without additional network configuration.
  2. Accept as a known risk with documentation, OR plan a migration where each VM gets a VLAN 25 NIC for storage traffic (requires Proxmox net2 on each VM + guest OS config).
  3. The existing TrueNAS static routes and switch SVI routing are correctly configured as compensating controls for asymmetric routing.

#### NS-03: VLAN 66 (Dirty) NFS Access Via Management NIC

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 5, NFS mount row for VLAN 66; VM 103 fstab
- **Description:** VM 103 (qBittorrent, on the isolated "Dirty" VLAN 66) accesses NFS via 10.25.255.25 (TrueNAS management NIC on VLAN 2550). This creates a Layer 2 path between the dirty/untrusted network segment and the management network, undermining the isolation purpose of both VLANs. If VM 103 is compromised (it runs a torrent client with VPN, touching untrusted internet traffic), it has network adjacency to the management plane.
- **Remediation:**
  1. Evaluate whether VM 103 truly needs NFS access. If downloads can be written to a local disk and later moved, remove the NFS mount entirely.
  2. If NFS access is required, create a dedicated TrueNAS interface/IP on VLAN 66 (or a new restricted VLAN) with a narrowly-scoped NFS export that only allows the `/Downloads/` subdirectory.
  3. At minimum, restrict the NFS export for nfs-mega-share to exclude 10.25.255.0/24 as a source network for the dirty VM, using IP-specific export rules.
  4. Document the risk if the current configuration is accepted.

#### NS-04: pve03 Split-Brain VLAN Risk Unresolved

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 11, "Network Risks" row 1; DC01.md "Medium-Term" tasks
- **Description:** pve03 has the same split-brain VLAN bug that previously broke VLAN 2550, but for VLANs 25 and 5. If any VM is added to pve03 using VLAN 25 or VLAN 5 on vmbr0, host-level connectivity on those VLANs will break. This is a documented known issue with a known fix but it has not been applied preemptively.
- **Remediation:**
  1. Apply the same fix that resolved VLAN 2550: rename `vmbr0.25` to `vmbr0v25` and `vmbr0.5` to `vmbr0v5` on pve03.
  2. Test storage connectivity after the rename.
  3. This should be completed BEFORE any new VMs are deployed on pve03.

---

### 4. MONITORING AND LOGGING (ML)

#### ML-01: No Infrastructure Monitoring or Alerting

- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 9, table row 9; Section 11, "Application Risks" row 2; DC01.md "Cluster Hardening" task 8
- **Description:** There is **zero** monitoring deployed. No Uptime Kuma, no Prometheus, no Zabbix, no Nagios, nothing. The document explicitly states: "PSU/fan failures, NFS hangs, service outages go undetected. No alerting." The only way to detect a problem is manual observation or service failure reported by end users. Given that PSU 1 on TrueNAS and PSU 2 on pve01 have already failed, the remaining single PSUs could fail at any time with no automated alert.
- **Remediation:**
  1. **Immediate (48 hours):** Deploy Uptime Kuma (lightweight, Docker-based) on any running VM. Add HTTP/TCP checks for: Proxmox API (8006), Plex (32400), all Arr services, NFS mount health (TCP 2049 on TrueNAS).
  2. **Short-term (1 week):** Add IPMI/iDRAC sensor monitoring. iDRAC SNMP traps or `ipmitool sensor` polling for PSU status, fan RPM, and temperatures. Alert on any degradation.
  3. **Medium-term:** Deploy node-exporter + Prometheus on Proxmox hosts for CPU, memory, disk, and network metrics. Add Grafana dashboards for operational visibility.
  4. **Configure alerting:** Email or webhook (Discord, Slack) notifications for all critical alerts. Do not deploy monitoring without alerting -- silent dashboards are useless.
  5. **Verify:** Simulate a failure (stop a Docker container) and confirm an alert fires within the expected time window.

#### ML-02: No Audit Trail for Administrative Actions

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9; DC01.md change log
- **Description:** There is no centralized logging or audit trail for administrative actions. SSH logins, sudo usage, Proxmox API calls, and Docker operations are logged locally on each host (syslog, auth.log) but there is no aggregation, no retention policy, and no review process. If an admin account is compromised, there would be no practical way to determine what actions were taken without manually parsing logs on each individual host.
- **Remediation:**
  1. Configure rsyslog or journald forwarding from pve01, pve03, and TrueNAS to a central log collector.
  2. Retain auth.log and syslog for a minimum of 90 days.
  3. Enable Proxmox task logging (already exists by default) and ensure `/var/log/pve/tasks/` is included in backup scope.
  4. Consider deploying a lightweight SIEM (e.g., Grafana Loki) for searchable log aggregation.

#### ML-03: No NFS Health Monitoring

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 11, "Application Risks" row 2; Lessons Learned #3, #4, #8
- **Description:** NFS is the backbone of the entire service stack (all Docker configs, media, compose files). The lessons learned section documents multiple NFS failure modes (boot hangs, asymmetric routing, MTU mismatches) but there is no automated check for NFS mount health. A stale NFS mount can cause Docker containers to hang indefinitely, and the only detection method is manual.
- **Remediation:**
  1. Create a simple health check script on each VM that touches a canary file on the NFS mount and verifies it within a timeout.
  2. Example: `timeout 5 stat /mnt/truenas/nfs-mega-share/plex/.healthcheck || alert "NFS stale on $(hostname)"`.
  3. Run via cron every 5 minutes. Alert on failure.
  4. Add NFS mount status to Uptime Kuma (when deployed) using a script-based check.

---

### 5. PHYSICAL SECURITY AND AVAILABILITY (PA)

#### PA-01: Dual Single-PSU Failure -- Imminent Availability Risk

- **Risk Level:** CRITICAL
- **Reference:** ARCHITECTURE.md Section 2, "Active Alerts"; Section 11, "Hardware Risks"; DC01.md "Medium-Term" tasks
- **Description:** Both the TrueNAS storage server (R530) and the primary hypervisor (pve01/T620) are running on single PSUs after hardware failures. The replacement parts are documented but NOT ordered. This is not a theoretical risk -- the failures have already occurred. A second PSU failure on either server means: (a) R530: total storage loss, all NFS mounts fail, all services down, ZFS pool import required on recovery; (b) T620: all VMs on pve01 stop (101, 102, 103, 105), only VM 104 on pve03 survives.
- **Remediation:**
  1. **Order replacement parts IMMEDIATELY.** Dell 05RHVVA00 for R530, Dell 06W2PWA00 for T620. This is a procurement action, not a technical one.
  2. Also order R530 Fan 6 replacement (by Service Tag B065ND2).
  3. Until parts arrive and are installed, document this as an accepted critical risk with an estimated remediation date.
  4. Verify: After installation, check iDRAC for "Redundancy Regained" on PSU and Fan status.

#### PA-02: pve03 Consumer-Grade Hardware With No Out-of-Band Management

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 2, pve03; Section 3, pve03 "no IPMI"
- **Description:** pve03 (Asus B550-E) is a consumer motherboard with no IPMI/iDRAC. If it becomes unresponsive, recovery requires physical console access at the colocation facility. This node is the current HA master and hosts VM 104 (Tdarr Node with GPU passthrough). It also has only a single 1 GbE NIC carrying all traffic.
- **Remediation:**
  1. Document this as an accepted risk for the current deployment.
  2. Ensure HA fencing (watchdog) is configured correctly so that if pve03 becomes unresponsive, pve01 can assume HA master role and VMs can failover (though VM 104 cannot migrate due to GPU passthrough).
  3. Long-term: plan replacement with server-grade hardware that includes IPMI.

---

### 6. CHANGE MANAGEMENT (CM)

#### CM-01: No Formal Change Approval Process

- **Risk Level:** MEDIUM
- **Reference:** DC01.md change log; ARCHITECTURE.md (no mention of approval process)
- **Description:** Changes are documented after the fact in DC01.md change log entries. There is no pre-change approval, no peer review, and no scheduled maintenance windows. The backup-before-change rule (from CLAUDE.md) is a good practice but is not enforced by any tool or process.
- **Remediation:**
  1. For changes that affect production services (network configuration, NFS exports, firewall rules, VM settings), require documentation of: (a) what will change, (b) expected impact, (c) rollback procedure BEFORE the change is made.
  2. Use Worker #2's ticket system to formalize this -- each change should have a ticket with these fields.
  3. For emergency changes, document within 24 hours with a post-incident note.

#### CM-02: Lessons Learned Document Is Excellent -- But Not Automated

- **Risk Level:** LOW
- **Reference:** ARCHITECTURE.md Section 12 (16 lessons learned)
- **Description:** The 16 lessons learned are comprehensive, specific, and actionable. However, they depend on humans reading and remembering them. Several lessons (e.g., #3 `_netdev,nofail`, #8 jumbo frames, #6 SQLite on NFS) describe failure modes that could be detected by automated checks before they cause outages.
- **Remediation:**
  1. Create automated pre-flight checks for high-impact lessons:
     - Script to verify all fstab NFS entries contain `_netdev,nofail`.
     - Script to verify MTU consistency across all interfaces.
     - Script to verify no SQLite databases exist on NFS mounts.
  2. Run these checks after any configuration change and include them in a future CI/CD or cron-based validation pipeline.

#### CM-03: Rollback Procedures Are Ad-Hoc

- **Risk Level:** MEDIUM
- **Reference:** DC01.md Session 17 (backup dirs before changes); ARCHITECTURE.md (no rollback section)
- **Description:** Rollback relies on manually-created backup directories (e.g., `~/backup-pve01-network-session17/`). There is no standardized rollback procedure, no tested restore path, and backup dirs are created inconsistently across hosts.
- **Remediation:**
  1. Standardize pre-change backup location (e.g., `/var/backups/changes/<date>/`).
  2. Include rollback commands in change documentation (the ticket system could enforce this field).
  3. Test rollback of at least one configuration change per quarter.

---

### 7. VULNERABILITY MANAGEMENT (VM)

#### VM-01: No Fail2ban or Brute-Force Protection

- **Risk Level:** HIGH
- **Reference:** ARCHITECTURE.md Section 9, table row 2; DC01.md "Cluster Hardening" task 1
- **Description:** No brute-force protection on any SSH-exposed host. With password authentication still enabled (AC-01), this is compounded. Even after SSH keys are deployed, Fail2ban provides defense-in-depth against key enumeration and SSH resource exhaustion attacks.
- **Remediation:**
  1. Install Fail2ban on pve01 and pve03: `apt install fail2ban`.
  2. Enable the `[sshd]` jail (enabled by default on Debian).
  3. Configure ban time (600s default is reasonable), max retries (5), and find time (600s).
  4. Also add a jail for Proxmox web UI (port 8006) if a filter exists, or write a custom filter for `/var/log/pveproxy/access.log`.
  5. Verify: `fail2ban-client status sshd` should show active jail.

#### VM-02: Cisco IOS Switch -- Patch Status Unknown

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 4, "Network Devices"; switch model WS-C4948E-F, IOS 15.2(4)E10a
- **Description:** The Cisco 4948E-F is running IOS 15.2(4)E10a. This hardware platform reached End-of-Sale in 2016 and End-of-Support in 2021. IOS 15.2E is no longer receiving security patches. Known CVEs for this version may exist. The switch is the core of all VLAN segmentation and L3 routing.
- **Remediation:**
  1. Check Cisco's Security Advisory page for CVEs affecting IOS 15.2(4)E on the 4948E-F platform.
  2. If critical CVEs exist (particularly in SSH, SNMP, or L3 routing), evaluate whether compensating controls (ACLs, disabling unused features) mitigate the risk.
  3. Long-term: plan replacement with a supported switch platform.
  4. Immediate: ensure switch management is restricted to SSH via pve01 jump host only (already in place per documentation).

#### VM-03: pfSense on FreeBSD 16.0 -- Verify Patch Currency

- **Risk Level:** LOW
- **Reference:** ARCHITECTURE.md Section 4, "Network Devices"; pfSense Plus (FreeBSD 16.0)
- **Description:** pfSense Plus is the perimeter firewall and VPN endpoint. The version running FreeBSD 16.0 should be verified as current. pfSense handles WAN exposure (public VIPs), WireGuard termination, and all inter-VLAN firewall policy.
- **Remediation:**
  1. Verify pfSense version is current via GUI: System > Update.
  2. Subscribe to pfSense security advisories.
  3. Schedule quarterly pfSense updates during maintenance windows.

#### VM-04: Docker Image Version Pinning Not Audited

- **Risk Level:** MEDIUM
- **Reference:** ARCHITECTURE.md Section 7, "Container Standard"; DC01.md "Cluster Hardening" task 3
- **Description:** The policy states "Pin specific versions, no `:latest`" and LSIO images are preferred. However, ARCHITECTURE.md notes this is "not audited." Running `:latest` tags means containers can silently update to versions with new vulnerabilities or breaking changes on any `docker compose pull`.
- **Remediation:**
  1. Audit all 5 compose files for `:latest` tags: `grep -r ':latest' /mnt/truenas/nfs-mega-share/plex/docker-compose*.yml /mnt/truenas/nfs-mega-share/plex/downloader-data/docker-compose*.yml`.
  2. Replace any `:latest` tags with specific version strings (e.g., `lscr.io/linuxserver/sonarr:4.0.11`).
  3. Establish a monthly update cadence: review release notes, update version pins, test in a non-production context first.
  4. Consider Watchtower or Diun for update notifications (notify only, not auto-update).

#### VM-05: TrueNAS SSH Permanently Enabled

- **Risk Level:** LOW
- **Reference:** ARCHITECTURE.md Section 9, table row 8; DC01.md "Cluster Hardening" task 7
- **Description:** TrueNAS SSH remains enabled at all times. The hardening plan calls for disabling it when not in active use. While TrueNAS is on the LAN VLAN and not directly internet-exposed, leaving SSH enabled increases the attack surface if the LAN is compromised.
- **Remediation:**
  1. After completing all pending TrueNAS configuration tasks, disable SSH via the TrueNAS GUI.
  2. Document a procedure to re-enable SSH when needed (GUI or physical console).
  3. This is low priority relative to other findings but should be part of the final hardening sweep.

---

## Findings Summary Table

| ID | Domain | Finding | Risk | DC01.md Task Ref |
|---|---|---|---|---|
| AC-01 | Access Control | SSH password auth enabled | HIGH | Hardening #1 |
| AC-02 | Access Control | NOPASSWD sudo unscoped | MEDIUM | Hardening (svc-admin) |
| AC-03 | Access Control | iDRAC default passwords | CRITICAL | Hardening #6 |
| AC-04 | Access Control | 4 admin accounts, no role differentiation | MEDIUM | -- |
| AC-05 | Access Control | Proxmox API unrestricted | HIGH | Hardening #2 |
| DP-01 | Data Protection | No VM backup strategy | CRITICAL | Hardening #9 |
| DP-02 | Data Protection | NFS export over-permissive (7 networks) | MEDIUM | Hardening #4 |
| DP-03 | Data Protection | HA storage world-accessible NFS | HIGH | -- |
| DP-04 | Data Protection | No encryption at rest or in transit | MEDIUM | -- |
| DP-05 | Data Protection | Local configs without backup | MEDIUM | -- |
| NS-01 | Network Security | Management VLAN firewall incomplete | HIGH | Remaining tasks |
| NS-02 | Network Security | NFS traffic on non-storage VLANs | MEDIUM | -- |
| NS-03 | Network Security | Dirty VLAN NFS via management NIC | HIGH | -- |
| NS-04 | Network Security | pve03 split-brain VLAN unresolved | MEDIUM | Medium-term tasks |
| ML-01 | Monitoring | No infrastructure monitoring | CRITICAL | Hardening #8 |
| ML-02 | Monitoring | No audit trail for admin actions | HIGH | -- |
| ML-03 | Monitoring | No NFS health monitoring | HIGH | -- |
| PA-01 | Physical/Availability | Dual single-PSU failure | CRITICAL | Medium-term tasks |
| PA-02 | Physical/Availability | pve03 consumer hardware, no IPMI | MEDIUM | -- |
| CM-01 | Change Management | No formal approval process | MEDIUM | -- |
| CM-02 | Change Management | Lessons learned not automated | LOW | -- |
| CM-03 | Change Management | Rollback procedures ad-hoc | MEDIUM | -- |
| VM-01 | Vulnerability Mgmt | No Fail2ban/brute-force protection | HIGH | Hardening #1 |
| VM-02 | Vulnerability Mgmt | Switch IOS EOL, unpatched | MEDIUM | -- |
| VM-03 | Vulnerability Mgmt | pfSense patch currency unverified | LOW | -- |
| VM-04 | Vulnerability Mgmt | Docker image pinning not audited | MEDIUM | Hardening #3 |
| VM-05 | Vulnerability Mgmt | TrueNAS SSH always enabled | LOW | Hardening #7 |

---

## Prioritized Remediation Roadmap

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

## Positive Observations

Worker #1's ARCHITECTURE.md deserves recognition for several security-positive attributes:

1. **Radical transparency:** The document does not hide problems. PSU failures, missing backups, default passwords, and incomplete hardening are all documented openly. This is the foundation of good security culture.
2. **VLAN segmentation is well-designed:** Six VLANs with distinct security policies, purpose-built for different trust levels. The dirty VLAN (66) with separate NAT VIP is particularly good.
3. **Lessons learned are operationally valuable:** 16 specific, incident-driven lessons that prevent repeat failures. This exceeds what most SOC audits find in small-team environments.
4. **NFS squash configuration:** `all_squash` to a single gid prevents privilege escalation via NFS, which is a common misconfiguration.
5. **WireGuard for remote access:** Not exposing SSH directly to the internet is a strong baseline decision.
6. **DNS hardening on VLAN 5:** `chattr +i` on resolv.conf prevents DNS hijacking in the public-facing VLAN.

---

*End of SOC compliance review for ARCHITECTURE.md.*
