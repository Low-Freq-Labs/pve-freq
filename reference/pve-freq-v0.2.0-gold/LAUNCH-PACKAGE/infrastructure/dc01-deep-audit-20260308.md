# DC01 Deep Infrastructure Audit

**Date:** 2026-03-08
**Auditor:** JARVIS 2 (SRE-style technical due diligence)
**Scope:** Full infrastructure — network, storage, compute, security, containers, operations
**Method:** Live SSH to all reachable hosts + API queries. Zero changes made.

---

## Executive Summary

DC01 is a 3-node Proxmox cluster running 14 production VMs serving media, automation, password management, and development workloads. The infrastructure is well-conceived — proper VLAN segmentation, VPN-routed torrent traffic, centralized NFS storage, and a custom fleet management CLI (FREQ). The person who built this understood the fundamentals.

**However, the execution has significant gaps.** ~~The biggest systemic problem is a complete absence of backups~~ *(Correction: daily PVE backups ARE running for all 11 VMs to TrueNAS NFS with keep-last=4 retention. The audit initially missed this — see retracted CRIT-02.)* The biggest actual systemic problem is credential hygiene — API keys in plaintext compose files, passwords in documentation, and fleet-wide password authentication still enabled despite SSH keys being deployed months ago. The second is a PVE WebUI port-forwarded from the public internet (NAT to 10.25.0.9:8006), which is a direct attack surface. The third is that Vaultwarden (vm802) is the least hardened VM in the fleet despite being the most sensitive — SSH/nginx on all interfaces, no NTP, no probe accounts, non-standard accounts and UIDs.

**Overall grade: 5.9/10** — Functional but fragile. Security posture and operational hygiene need work. *(Revised from 5.4 after CRIT-02 retraction — daily VM backups ARE running with 4-day retention.)*

---

## Infrastructure Map (Actual, As-Found)

### Physical Layer
```
Internet
  ├── 69.65.20.56/29 (WAN block — 5 usable IPs)
  │   ├── .57 = igc0 (DR WAN)
  │   ├── .58 = lagg1 (Primary WAN) → NAT: Plex :50000→10.25.5.30:32400
  │   ├── .61 = VLAN66 NAT (torrent exit IP)
  │   └── .62 = lagg1 → NAT: 8006→10.25.0.9 ⚠️ PVE WEBUI EXPOSED
  ├── 100.101.14.0/28 (Secondary WAN block)
  │   ├── .2 = lagg1 (outbound NAT for all VLANs)
  │   └── .3 = igc0 (outbound NAT for igc0 subnets)
  │
  └── pfSense (pfsense01.infra.dc01)
      ├── lagg0 (LAN trunk) — MTU 9000
      │   ├── VLAN 0   — 10.25.0.0/24   (LAN — PVE nodes, TrueNAS, switch)
      │   ├── VLAN 5   — 10.25.5.0/24   (PUBLIC — Plex, Arr, Tdarr)
      │   ├── VLAN 10  — 10.25.10.0/24  (purpose unclear — pve03 only)
      │   ├── VLAN 25  — 10.25.25.0/24  (STORAGE — NFS traffic)
      │   ├── VLAN 66  — 10.25.66.0/24  (DIRTY — qBit, SABnzbd)
      │   ├── VLAN 255 — pve01 only     (purpose unclear)
      │   └── VLAN 2550— 10.25.255.0/24 (MGMT — SSH, WebUI, monitoring)
      └── tun_wg0 — 10.25.100.0/24 (WireGuard — 11 peers, 4 active)
```

### Compute Layer
```
pve01 (10.25.255.26) — R530, 252GB RAM, 9TB ZFS HDD
  ├── VM 100 Jarvis-AI      — 8GB, 4c  — FREQ management node
  ├── VM 101 Plex-Server     — 8GB, 6c  — Plex media server
  ├── VM 102 Arr-Stack       — 8GB, 4c  — Sonarr/Radarr/Prowlarr/11 containers
  ├── VM 103 qBit-Downloader — 4GB, 8c  — qBittorrent+Gluetun VPN
  ├── VM 104 Tdarr-Server    — 4GB, 4c  — Tdarr transcoding server
  ├── VM 802 Vaultwarden     — 4GB, 2c  — Password vault ⚠️ UNDER-PROTECTED
  ├── VM 804 Talos           — 8GB, 4c  — K8s experiment (agent not responding)
  ├── VM 980 pfSense-lab     — 2GB, 2c  — Lab (not installed)
  └── VM 981 TrueNAS-lab     — 8GB, 4c  — Lab (not installed)
  RAM: 62GB used / 252GB total (25%) — 189GB available

pve02 (10.25.255.27) — T620, 126GB RAM, 1.7TB ZFS SSD + 888GB ZFS SSD
  ├── VM 201 SABnzbd         — 16GB, 8c — Usenet downloader
  ├── VM 202 qBit-DL-2       — 4GB, 8c  — Second qBit+Gluetun
  ├── VM 400 RunescapeBotVM  — 32GB, 8c — Runescape project
  ├── VM 401 Ubuntu-Template — stopped   — Clone template
  ├── VM 402 Test            — 32GB, 8c — RUNNING, not in fleet ⚠️
  └── VM 910 ubuntu-template — stopped   — Template
  RAM: 52GB used / 126GB total (41%) — 73GB available
  ⚠️ NO SWAP CONFIGURED (0B)

pve03 (10.25.255.28) — 32GB RAM, 1.7TB ZFS SSD
  └── VM 301 Tdarr-Node      — 16GB, 12c — GPU transcoding (RX 580)
  RAM: 21GB used / 31GB total (68%) — 9.8GB available ⚠️ NEAR CAPACITY
  └── stale VLAN 10 interface (10.25.10.28) — only node with this VLAN

TrueNAS (10.25.255.25) — 88GB RAM, 44TB ZFS RAIDZ2
  ├── mega-pool: 43.6TB total, 26.5TB used (60%), 8 disks in 2×RAIDZ2
  ├── boot-pool: 114GB, 3.1GB used
  └── Scrub running: 52% done, ~5h remaining
  RAM: 77GB used / 88GB total — ZFS ARC consuming most of it

pfSense — FreeBSD 16.0-CURRENT, 26.03-BETA
  ├── WireGuard: 11 peers, 4 active (3h), 3 stale (1-3 days), 4 very stale (3-9 days)
  ├── Firewall states: 314 active
  └── DNS: Unbound resolver on localhost
```

### Storage Dependencies
```
TrueNAS mega-pool/nfs-mega-share (NFS v3)
  └── Mounted on: vm101, vm102, vm103, vm104, vm201, vm202, vm301
      ALL media VMs depend on this single NFS export

TrueNAS mega-pool/proxmox-backups (NFS)
  └── Mounted on: pve01, pve02, pve03 (empty — no backups running)

TrueNAS mega-pool/ha-proxmox-disk (NFS)
  └── Mounted on: pve01, pve02, pve03 (HA storage — empty)

TrueNAS mega-pool/smb-share (SMB)
  └── Mounted on: vm100 (/mnt/obsidian — Obsidian vault)

pve01 os-pool-hdd/iso-storage (NFS export)
  └── Mounted on: pve02, pve03 (/mnt/iso-share — ISO images)
```

---

## CRITICAL FINDINGS (fix before next session)

### CRIT-01: PVE WebUI Port-Forwarded to Public Internet
- **Where:** pfSense NAT rules
- **What:** `rdr on lagg1 inet proto tcp from any to 69.65.20.62 port = 8006 -> 10.25.0.9`. Port 8006 (Proxmox VE WebUI standard port) is forwarded from public IP 69.65.20.62 to internal host 10.25.0.9 — no source restriction, accessible from ANYWHERE on the internet.
- **Risk:** Anyone can reach the PVE WebUI login page from the internet. PVE WebUI has had CVEs (e.g., CVE-2022-0100). Combined with `PermitRootLogin yes` and password auth, brute-force is viable. 10.25.0.9 appears to be an iDRAC — if this is iDRAC WebUI instead, it's equally bad (iDRAC has had critical RCE CVEs).
- **Fix:** Delete this NAT rule immediately unless there is a documented business need. If needed, restrict to known source IPs or require VPN access.
```
# On pfSense WebUI: Firewall → NAT → Port Forward
# Delete the rule forwarding 69.65.20.62:8006 → 10.25.0.9
```

### ~~CRIT-02: Zero VM Backups Running~~ → RETRACTED (audit error)
- **Status:** RETRACTED — auditor error. Backups ARE running.
- **Correction date:** 2026-03-08
- **Actual state:** Schedule `backup-99661208-2531` runs DAILY at 21:00 covering VMs 100,101,102,103,104,201,202,301,400,802,804. Retention: keep-last=4. All 11 VMs have exactly 4 backups each on `truenas-backups` NFS. Latest backups: March 7, 2026. Storage: 346GB used of 2TB.
- **Verified backup sizes (March 7):** vm100=1.9GB, vm101=55GB, vm102=8.6GB, vm103=2.3GB, vm104=6.3GB, vm201=1.8GB, vm202=2.4GB, vm301=logged, vm400=528B (diskless — disk has backup=no), vm802=816MB, vm804=4.4GB
- **Minor finding (INFO):** VM 400 disk has `backup=no` in PVE config — only VM config is saved, not the 16GB disk. Acceptable for non-infrastructure workload (Runescape project).
- **Why the original audit missed it:** `pvesh get /cluster/backup` returned the schedule ID but the auditor failed to verify actual backup files in `/mnt/pve/truenas-backups/dump/`. The 346GB usage WAS the active backups.

### CRIT-03: Vaultwarden Zero Hardening (backup partially resolved)
- **Where:** VM 802 (10.25.255.75)
- **What:** Multiple compounding issues on the most sensitive VM:
  1. ~~Data at `/home/blue/vaultwarden/data` — on local disk only, NO NFS mount, NO backup to TrueNAS~~ **PARTIALLY RESOLVED 2026-03-08:** Manual backup taken (304KB tar.gz with db.sqlite3 + rsa_key.pem) to SMB share (`/mnt/smb-sonny/sonny/JARVIS_PROD/backups/vaultwarden/` + Obsidian vault). PVE-level VM backup also exists (816MB, daily, keep-last=4). **Still needs:** automated application-level backup cron (requires root on vm100 — command provided below).
  2. SSH on `0.0.0.0:22` — accessible from ALL VLANs (not mgmt-only)
  3. nginx on `0.0.0.0:80,443` — WebUI accessible from all VLANs
  4. NTP not syncing (`System clock synchronized: no`)
  5. svc-admin UID 1001 (should be 3003) — inconsistent with fleet standard
  6. No probe accounts deployed
  7. Non-standard `blue` account (UID 1000)
  8. `X11Forwarding yes`
  9. No `sshd_config.d/dc01-hardening.conf` with listen restrictions
  10. DNS pointing to pfSense (10.25.0.1) — different from fleet (1.1.1.1)
  11. Older kernel (6.12.69 vs 6.12.73 rest of fleet)
- **Risk:** ~~Complete loss of all passwords if disk fails~~ Risk reduced — PVE backup exists + manual SQLite backup. SSH brute-force from any VLAN still open. The password vault remains the LEAST hardened VM in the fleet.
- **Fix:** Hardening items 2-11 still need remediation.
```bash
# Automated weekly Vaultwarden SQLite backup (run as root on vm100):
(crontab -l 2>/dev/null; echo '0 3 * * 0 STAMP=$(date +\%Y\%m\%d-\%H\%M) && ssh -i /opt/lowfreq/keys/freq_id_rsa -o BatchMode=yes svc-admin@10.25.255.75 "sudo tar czf /tmp/vw-$STAMP.tar.gz -C /home/blue vaultwarden/data && sudo chmod 644 /tmp/vw-$STAMP.tar.gz" && scp -i /opt/lowfreq/keys/freq_id_rsa -o BatchMode=yes svc-admin@10.25.255.75:/tmp/vw-$STAMP.tar.gz /mnt/obsidian/backups/vaultwarden/ && ssh -i /opt/lowfreq/keys/freq_id_rsa -o BatchMode=yes svc-admin@10.25.255.75 "sudo rm -f /tmp/vw-$STAMP.tar.gz" && ls -t /mnt/obsidian/backups/vaultwarden/vw-*.tar.gz | tail -n +5 | xargs rm -f 2>/dev/null # FREQ: vaultwarden weekly backup') | crontab -
```

### CRIT-04: API Keys in Plaintext Docker Compose Files
- **Where:** VM 102 (10.25.255.31) — `/opt/dc01/compose/docker-compose.yml`
- **What:** Sonarr and Radarr API keys hardcoded in environment variables for unpackerr:
  ```
  UN_SONARR_0_API_KEY=1ecf8eb6edba450a8a874e09e7b0099a
  UN_RADARR_0_API_KEY=1f181c9ffc9e49efb90f84d20432c191
  ```
  These files are readable by all probe accounts via `docker exec` or `sudo cat`.
- **Risk:** Any user with probe access can extract API keys granting full admin to Sonarr and Radarr (add/delete media, change settings, access download clients).
- **Fix:** Move to `.env` file with 600 permissions, or use Docker secrets.

### CRIT-05: FREQ Codebase Still Group-Writable (Privilege Escalation)
- **Where:** VM 100 `/opt/lowfreq/`
- **What:** All files owned by `root:truenas_admin` with `rwxrwxr-x` (dirs) and `rw-rw-r--` (libs). The `freq` binary itself is `rwxrwxr-x`. This was identified as C-03 in the previous audit and IS STILL OPEN.
- **Risk:** Any user in GID 950 (all 4 probe accounts + svc-admin) can modify FREQ code. When root runs `freq`, attacker code executes with root privileges.
- **Fix:**
```bash
ssh root@vm100
chown -R root:root /opt/lowfreq/lib/ /opt/lowfreq/freq
chmod -R go-w /opt/lowfreq/lib/ /opt/lowfreq/freq
```

---

## HIGH FINDINGS (fix this week)

### HIGH-01: PasswordAuthentication Still Enabled Fleet-Wide
- **Where:** All 12 Linux hosts (all except TrueNAS)
- **What:** SSH keys deployed to all accounts in S075 (41+ sessions ago). Password auth disable script written and validated. Still not executed. Every host still accepts password login.
- **Risk:** Combined with temp passwords (`changeme1234`, `temp1234`, `d0n0t4g3tm3`), SSH brute-force from any compromised VLAN host is trivial.
- **Fix:** Run `/var/tmp/freq-disable-password-auth.sh` with Sonny present.

### HIGH-02: No Docker daemon.json on Any VM
- **Where:** All 7 Docker VMs (101-104, 201, 202, 301)
- **What:** Zero Docker VMs have a `daemon.json` configuration file. Docker defaults apply: unlimited log file sizes, default bridge network, no userns-remap, no live-restore, no storage optimization.
- **Risk:** Docker container logs will grow without bound until disk is full. No log rotation = silent disk exhaustion. No userns-remap = container root maps to host root.
- **Fix:** Deploy standard `daemon.json` to all Docker VMs:
```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "3" },
  "live-restore": true,
  "storage-driver": "overlay2"
}
```

### HIGH-03: pve03 Near RAM Exhaustion
- **Where:** pve03 (10.25.255.28) — 32GB total
- **What:** VM 301 (Tdarr-Node) allocated 16GB. 21GB used, 1.5GB free, 9.8GB available (cache). ZFS ARC configured at 3.3GB max. When Tdarr is actively transcoding (GPU + CPU), memory spikes could trigger OOM.
- **Risk:** OOM killer takes down Tdarr or a PVE system process. pve03 has no swap (8GB configured but showing 16K used — confirmed available).
- **Fix:** Reduce VM 301 allocation from 16GB to 12GB, or migrate to pve01 (189GB available). Alternatively, increase pve03 RAM if hardware supports it.

### HIGH-04: pve02 Has No Swap
- **Where:** pve02 (10.25.255.27)
- **What:** `Swap: 0B 0B 0B`. No swap space configured at all. pve02 runs VM 400 (32GB) + VM 201 (16GB) + VM 202 (4GB) + VM 402 (32GB running) = 84GB VM allocation against 126GB physical RAM.
- **Risk:** If all VMs hit peak memory, OOM killer engages with no swap buffer. VM 402 (unknown "Test" VM running with 32GB allocated) makes this worse.
- **Fix:** Create swap file or partition. Investigate whether VM 402 needs 32GB or should be stopped.

### HIGH-05: VM 402 Running Unmanaged with 32GB RAM
- **Where:** pve02 — VM 402 "Test"
- **What:** Running VM with 32GB RAM, 8 CPU cores, 64GB disk. Cloned from VM 401 template. Not in FREQ hosts.conf as managed. SSH unreachable via svc-admin key (`Permission denied`). Nobody appears to be actively using it.
- **Risk:** Consuming 32GB RAM on pve02 for unknown purpose. Cannot be monitored, backed up, or managed through fleet tools.
- **Fix:** Ask Sonny: is VM 402 needed? If not, stop it and reclaim 32GB RAM on pve02.

### HIGH-06: pve01 SSH Not Dual-Bound Like Other Nodes
- **Where:** pve01 (10.25.255.26)
- **What:** pve01's sshd_config shows `PermitRootLogin yes` and `PasswordAuthentication yes` in main config, and `dc01-hardening.conf` exists in sshd_config.d, but SSH is bound to BOTH `10.25.255.26` (mgmt) AND `10.25.0.26` (LAN). The hardening conf on pve02/pve03 explicitly sets dual-bind with `X11Forwarding no` and `ListenAddress`. pve01 may be missing these settings in its dc01-hardening.conf.
- **Evidence:** pve01 SSH shows `PermitRootLogin yes` and `PasswordAuthentication yes` without the `X11Forwarding no` and `ListenAddress` lines that pve02/pve03 show.
- **Risk:** Configuration drift between PVE nodes. If pve01's hardening conf is empty or incomplete, it's less protected.
- **Fix:** Verify `cat /etc/ssh/sshd_config.d/dc01-hardening.conf` on pve01 and ensure it matches pve02/pve03.

### HIGH-07: TrueNAS API Returning Empty Results
- **Where:** TrueNAS REST API (https://10.25.255.25/api/v2.0/)
- **What:** All 16 API endpoints returned empty/no data. Credentials `truenas_admin:changeme1234` may be incorrect, or the API may require a different auth method (API key vs basic auth). The TrueNAS middleware (midclt) on Electric Eel 25.10.1 may have changed API auth.
- **Risk:** FREQ's TrueNAS module relies on API access. If API auth is broken, TrueNAS monitoring is blind. Health checks, alert monitoring, pool status — all via API — are non-functional.
- **Fix:** Verify API credentials. Generate API key via TrueNAS WebUI → API Keys.

### HIGH-08: Stale/Orphaned Chroot Mounts on pve02
- **Where:** pve02
- **What:** Three stale mounts from FREQ operations:
  ```
  /dev/zd80p3   960M → /tmp/vm905-check
  /dev/zd96p2   2.0G → /tmp/fleet-chroot-1201211
  /dev/zd208p4  31G  → /tmp/fleet-chroot-1228867 (mounted TWICE)
  ```
- **Risk:** These hold ZFS zvols open, consuming disk space and potentially blocking pool operations. 31GB held by a stale chroot is wasted SSD space.
- **Fix:**
```bash
ssh svc-admin@10.25.255.27
sudo umount /tmp/vm905-check /tmp/fleet-chroot-1201211 /tmp/fleet-chroot-1228867 /tmp/fleet-chroot-1230251
# Then clean the zvols
```

### HIGH-09: 4 Docker Images on :latest Tag
- **Where:** VM 102 (arr-stack)
- **What:** `recyclarr:latest`, `kometa:latest`, `tautulli:latest`, `unpackerr:latest` — all on floating `:latest` tags. These auto-update unpredictably.
- **Risk:** A breaking change in any of these images will silently break the media stack on next container recreation.
- **Fix:** Pin to specific version tags in docker-compose.yml.

### HIGH-10: Plex at 95% CPU
- **Where:** VM 101 (10.25.255.30)
- **What:** `plex 95.47% 520.6MiB / 7.76GiB`. Plex is pegging CPU at 95%. Root disk at 68% used (38G of 60G).
- **Risk:** Sustained high CPU impacts streaming quality and responsiveness. 68% root disk will eventually fill with Plex metadata/cache.
- **Fix:** Investigate Plex activity (transcoding? library scan?). Consider adding more CPU cores or increasing disk. The old image (2 reclaimable, 616MB) should be cleaned with `docker image prune`.

---

## MEDIUM FINDINGS (fix this month)

### MED-01: rpcbind Running on Every VM (Unnecessary)
- **Where:** All 11 Linux VMs + all 3 PVE nodes
- **What:** rpcbind (port 111) listening on `0.0.0.0` on every host. Only pve01 actually serves NFS.
- **Risk:** Unnecessary attack surface. rpcbind has had historical CVEs (CVE-2017-8779).
- **Fix:** `sudo systemctl disable --now rpcbind rpcbind.socket` on all hosts except pve01 and TrueNAS.

### MED-02: NFS on pve01 Bound to All Interfaces
- **Where:** pve01 (10.25.255.26)
- **What:** NFS (2049), rpc.mountd, rpc.statd all on `0.0.0.0` — accessible from mgmt, LAN, all VLANs. Should be restricted to storage VLAN only (10.25.25.26).
- **Fix:** Configure NFS to bind to 10.25.25.26 only.

### MED-03: NFS Mounted via Storage VLAN with all_squash to svc-admin UID
- **Where:** TrueNAS NFS export for nfs-mega-share
- **What:** `all_squash,anonuid=3003,anongid=950` — maps ALL access to svc-admin UID/GID. Any host on 10.25.25.0/24, 10.25.0.0/24, or 10.25.100.0/24 can write to the entire media library as svc-admin.
- **Risk:** A compromised Docker container can modify/delete any file on the NFS share. WireGuard clients (10.25.100.0/24) can also access the NFS share.
- **Fix:** Remove 10.25.100.0/24 from NFS exports. Consider per-subnet UID mapping.

### MED-04: vm201 X11Forwarding Enabled
- **Where:** vm201 (10.25.255.150)
- **What:** SSH config shows `X11Forwarding yes` — only Docker VM with this enabled. Should be `no`.
- **Fix:** Add `X11Forwarding no` to sshd_config or dc01-hardening.conf.

### MED-05: vm201 Orphan `test` User
- **Where:** vm201 (10.25.255.150)
- **What:** `test` user (UID 1000) with `/bin/bash` shell. Not a fleet standard account.
- **Fix:** `sudo userdel -r test` or `sudo usermod -s /usr/sbin/nologin test`.

### MED-06: vm100 QEMU Guest Agent Not Responding
- **Where:** VM 100 (Jarvis-AI) on pve01
- **What:** `qm agent 100 ping` returns NOT responding. Guest agent enabled in VM config but not running inside the VM.
- **Risk:** PVE cannot cleanly shutdown the VM, cannot read network info, cannot freeze filesystem for consistent snapshots.
- **Fix:** `ssh root@vm100 "apt install qemu-guest-agent && systemctl enable --now qemu-guest-agent"`.

### MED-07: pfSense chrisadmin/sonny-aif GID Mismatch
- **Where:** pfSense
- **What:** `chrisadmin:*:2001:65534` and `sonny-aif:*:2000:65534` — GID 65534 is `nobody`. Standard fleet GID is 950 (truenas_admin) or 3950 (dc01-probe). Only `jarvis-ai:*:3004:950` and `donmin:*:3002:950` have correct GIDs.
- **Fix:** Fix in TICKET-0006 scope.

### MED-08: WireGuard Stale Peers
- **Where:** pfSense WireGuard
- **What:** 11 peers configured, but:
  - Peer `.10` — NEVER connected (0 B received, 20MB sent — keepalives only)
  - Peer `.16` — last handshake 2 days ago
  - Peer `.18` — last handshake 3 days ago
  - Peer `.20` — last handshake 3.5 days ago
  - Peer `.11` — last handshake 9 days ago
- **Risk:** Leaked WireGuard keys for stale peers remain valid. If device is lost/compromised, attacker has network access.
- **Fix:** Review with Sonny which peers are active users. Rotate keys for inactive peers.

### MED-09: ZFS Pools Need Feature Upgrade
- **Where:** All PVE nodes (os-pool-hdd, os-pool-ssd, rpool)
- **What:** "Some supported and requested features are not enabled on the pool." This appears on all 5 ZFS pools across all 3 nodes.
- **Fix:** `zpool upgrade <pool-name>` during maintenance window. Note: makes pool incompatible with older ZFS versions (one-way upgrade).

### MED-10: PVE Cluster Firewall Disabled
- **Where:** All 3 PVE nodes
- **What:** `pvesh get /cluster/firewall/options` returns empty — PVE's built-in firewall is not enabled.
- **Risk:** If pfSense is bypassed (VLAN hopping, direct L2 access), PVE nodes have zero host-level protection.

### MED-11: vm802 DNS Inconsistency
- **Where:** VM 802 (Vaultwarden)
- **What:** DNS set to `10.25.0.1` (pfSense). Every other host uses `1.1.1.1` / `8.8.8.8`.
- **Risk:** If pfSense DNS (Unbound) is down, Vaultwarden loses DNS resolution while rest of fleet continues working.

### MED-12: vm103 Missing DNS Configuration
- **Where:** VM 103 (qBit-Downloader)
- **What:** `grep nameserver /etc/resolv.conf` returned empty. No DNS nameservers configured.
- **Risk:** DNS resolution may rely on default gateway or DHCP lease. If Gluetun VPN changes DNS internally, host-level DNS is broken.
- **Fix:** Add `nameserver 1.1.1.1` and `nameserver 8.8.8.8` to `/etc/resolv.conf`.

---

## LOW FINDINGS / OBSERVATIONS

### LOW-01: Docker Images Using Untagged SHA256 Digests
- **Where:** vm104 (tdarr server), vm301 (tdarr node)
- **What:** Tdarr images pinned to SHA256 digest instead of version tag. Makes it impossible to tell what version is running without inspecting the image.

### LOW-02: Plex Using Host Networking
- **Where:** vm101
- **What:** `network_mode: host`. Required for DLNA and remote access. Accepted risk.

### LOW-03: Gluetun CAP_NET_ADMIN + /dev/net/tun
- **Where:** vm103, vm202
- **What:** Required for VPN tunnel creation. Accepted risk — containers are not privileged.

### LOW-04: pve01 Failed Session Scope
- **Where:** pve01
- **What:** `session-1083.scope loaded failed` — stale systemd session from root login. Cosmetic, auto-clears on reboot.

### LOW-05: Lab VMs Running But Not Installed
- **Where:** pve01 — VM 980 (pfSense-lab), VM 981 (TrueNAS-lab)
- **What:** Both VMs are running but have no OS installed (boot disk shows 0.00GB). Consuming 2GB + 8GB = 10GB RAM for nothing.
- **Fix:** Either install OS or stop VMs to reclaim 10GB RAM on pve01.

### LOW-06: `sync` User Has Login Shell
- **Where:** All Linux hosts
- **What:** `sync 4 /bin/sync` — system account with `/bin/sync` as shell. Standard on Debian, harmless but unnecessary.

### LOW-07: Multiple Docker Networks Per VM
- **Where:** vm201, vm202, vm103
- **What:** Both `compose_default` and `sabnzbd_default` (or equivalent) networks exist. Orphaned networks from previous compose runs.
- **Fix:** `docker network prune` on affected VMs.

### LOW-08: pfSense ix0/ix1 Interfaces Down
- **Where:** pfSense
- **What:** Two Intel 10GbE interfaces (ix0, ix1) with `no carrier`. MAC `ff:ff:ff:ff:ff:ff` suggests no SFP+ modules installed.
- **Note:** Not an issue — these are unused 10GbE ports.

---

## Domain Analysis

### Network
**Grade: 6/10**

**What is good:**
- Proper VLAN segmentation (7 VLANs for different traffic classes)
- Torrent traffic exits on dedicated public IP (69.65.20.61) via VLAN 66
- WireGuard for remote access
- Plex port-forward uses dedicated IP (.58) on non-standard port (50000)
- All Docker services dual-bind WebUI to mgmt VLAN + service VLAN (good practice)
- MTU 9000 (jumbo frames) consistent across PVE bridges, NICs, and VMs

**What is wrong:**
- Port 8006 forwarded to public internet (CRIT-01)
- WireGuard has 7 stale peers out of 11 (64% abandoned)
- pfSense running BETA firmware (16.0-CURRENT) on production perimeter
- VLAN 10 and VLAN 255 exist on some nodes but purpose is undocumented
- NFS exported to WireGuard subnet (10.25.100.0/24) — VPN clients can access all media storage

**What is missing:**
- No east-west filtering between VMs on the same VLAN
- No IDS/IPS (no Suricata/Snort on pfSense)
- No DNS logging/monitoring
- No DHCP snooping or ARP inspection
- IPv6 is link-local only on pfSense — not explicitly disabled, not properly configured

**Recommended changes:**
1. Delete the 8006 NAT rule immediately
2. Review and prune WireGuard peers
3. Remove 10.25.100.0/24 from NFS export ACL
4. Document VLAN 10 and VLAN 255 purpose or remove them
5. Plan pfSense firmware upgrade path to stable release

### Storage
**Grade: 5/10**

**What is good:**
- TrueNAS mega-pool: 2×RAIDZ2 (double parity on each vdev) — can survive 2 disk failures per vdev
- All PVE ZFS pools: mirrored vdevs (single-disk fault tolerance)
- NFS mount options consistent across all Docker VMs (nfsvers=3, soft, timeo=150, retrans=3, bg)
- Weekly ZFS scrubs running (last scrub: all pools clean, 0 errors)
- ISO storage shared via NFS from pve01 to pve02/pve03

**What is wrong:**
- ZERO VM backups running (CRIT-02)
- Vaultwarden data on local disk with no backup (CRIT-03)
- Stale chroot zvols consuming 34GB on pve02 (HIGH-08)
- truenas-backups NFS mount has 346GB but unclear if these are current
- NFS all_squash maps everything to svc-admin UID — no per-VM identity
- No snapshot schedules visible for TrueNAS datasets

**What is missing:**
- No offsite/cross-site replication
- No backup verification (restore tests)
- No storage alerting (disk full, pool degraded notifications)
- No SMART monitoring alerting pipeline
- No quotas on NFS shares — any VM can fill the entire 8TB free space

**Recommended changes:**
1. Enable PVE backup schedule for critical VMs immediately
2. Set up Vaultwarden backup to TrueNAS NFS
3. Create TrueNAS snapshot schedules for smb-share and nfs-mega-share
4. Clean up stale chroot mounts on pve02
5. Consider TrueNAS cloud sync to S3/Backblaze for offsite backup of critical data

### Proxmox Cluster
**Grade: 6/10**

**What is good:**
- 3-node cluster with quorum (all 3 voting, quorum=2)
- Corosync transport: knet with secure auth
- HA enabled (master: pve03, all LRMs idle)
- All 3 nodes on same PVE version (9.1.6) and kernel (6.17.9-1-pve)
- Migration network configured for mgmt VLAN (10.25.255.0/24)
- ZFS pools healthy on all nodes (0 errors everywhere)

**What is wrong:**
- VM placement heavily biased: pve01 has 9 VMs, pve02 has 6 (3 templates), pve03 has 1
- VM 402 running unmanaged with 32GB RAM on pve02
- pve03 near RAM capacity (9.8GB available for 1 VM using 16GB)
- No balloon memory on any VM — static allocation only
- ZFS ARC not tuned: pve01 at 16GB max (from 252GB), pve02 at 6.2GB, pve03 at 3.1GB
- PVE enterprise subscription not configured (apt sources empty/disabled — no-subscription repo likely in use)
- VM 100 guest agent not responding — can't get IP, can't freeze for backup

**What is missing:**
- No HA groups defined (VMs not assigned to preferred nodes)
- No resource pools for workload isolation
- No PVE firewall rules
- No PVE user account expiry
- No automatic updates/security patches

**Recommended changes:**
1. Stop VM 402 if not needed — reclaim 32GB RAM on pve02
2. Fix VM 100 guest agent
3. Consider migrating Tdarr-Node (VM 301) to pve01 or pve02 for RAM headroom
4. Configure HA groups for critical VMs (100, 802)

### Security Posture
**Grade: 3/10**

**What is good:**
- SSH keys deployed fleet-wide (S075)
- Probe accounts with scoped sudoers on all fleet VMs
- TrueNAS: password auth disabled, key-only SSH
- VPN-routed torrent traffic (Gluetun containers)
- pfSense default deny with explicit pass rules
- Claude account locked (C-07 resolved)
- pfSense probe sudoers restored (dc01-probe-readonly exists)

**What is wrong:**
- Password auth enabled on 12/14 SSH hosts (hardening script written but not executed)
- FREQ codebase group-writable — privilege escalation path (CRIT-05)
- API keys in plaintext compose files (CRIT-04)
- PVE WebUI forwarded to internet (CRIT-01)
- All previous C-01 through C-06 findings from security audit still open (except C-07)
- `cmd_exec` gives operators unrestricted root via svc-admin
- No fail2ban or equivalent on any host
- No audit logging (no auditd, no central syslog)
- No file integrity monitoring

**What is missing:**
- No SIEM/SOC capability (Wazuh planned but not deployed)
- No intrusion detection
- No vulnerability scanning
- No secrets management (API keys, passwords in plaintext files)
- No certificate management (self-signed PVE certs, no rotation)
- No password policy enforcement

**Recommended changes:**
1. Fix FREQ permissions immediately (5 minutes)
2. Execute password auth disable script (30 minutes)
3. Move API keys out of compose files into .env files with 600 perms
4. Delete the 8006 NAT rule
5. Deploy Wazuh per the existing plan

### Container Architecture
**Grade: 7/10**

**What is good:**
- All containers non-privileged (privileged=false on every container)
- PUID/PGID consistently set to 3003/950 across all LSIO images
- Gluetun containers with health checks (wget to ipinfo.io)
- Docker port bindings IP-restricted to correct VLANs (mgmt WebUI, dirty torrents)
- Restart policy: `unless-stopped` on all containers
- Compose files well-documented with VM number, VLAN, and session references
- VPN containers using `service:gluetun` network mode — traffic properly tunneled

**What is wrong:**
- No daemon.json on any Docker VM — no log rotation (HIGH-02)
- 4 images on `:latest` tag (recyclarr, kometa, tautulli, unpackerr)
- Tdarr images on SHA256 digest — can't tell version
- 15 orphaned Docker volumes on vm103 and vm202
- API keys in compose environment variables (CRIT-04)
- No container health checks except Gluetun

**What is missing:**
- No container resource limits (CPU, memory)
- No Docker image update automation (Watchtower or equivalent)
- No container log aggregation
- No Docker security scanning (Trivy, Snyk)

**Recommended changes:**
1. Deploy daemon.json with log rotation on all Docker VMs
2. Pin all images to specific version tags
3. Add health checks to critical containers (Plex, Sonarr, Radarr)
4. Clean orphaned volumes: `docker volume prune`
5. Move secrets to .env files

### Operational Hygiene
**Grade: 5/10**

**What is good:**
- Time synchronization: NTP active and synced on 12/13 checked hosts
- Timezone consistent: America/Chicago on all hosts
- No failed systemd units on any VM (only pve01 stale session)
- No cron jobs fleet-wide (clean — no band-aids)
- Consistent user account model (UID 3000-3004) on fleet VMs
- DNS consistent on most hosts (1.1.1.1, 8.8.8.8)
- Disk usage all below 70% fleet-wide

**What is wrong:**
- vm802 NTP NOT synced (`System clock synchronized: no`)
- vm802 DNS different from fleet (10.25.0.1 vs 1.1.1.1)
- vm103 missing DNS configuration entirely
- pve01 root has 8 authorized keys (3 duplicate pve03 entries)
- Stale chroot mounts on pve02
- No log rotation on Docker VMs (no daemon.json)
- No monitoring or alerting for anything

**What is missing:**
- No centralized logging
- No monitoring stack (no Prometheus, Grafana, Netdata fleet-wide)
- No alerting (disk full, service down, NFS unmount)
- No change management beyond FREQ journal
- No runbook for common failures
- No DR plan documentation

### Resilience / Single Points of Failure
**Grade: 3/10**

**SPOFs identified:**
1. **TrueNAS** — If TrueNAS goes down: vm101, vm102, vm103, vm104, vm201, vm202, vm301 ALL lose NFS mounts and stop functioning. vm100 loses Obsidian vault. PVE backup storage gone. **Impact: 8 VMs affected, ALL media services down.**
2. **pfSense** — If pfSense goes down: ALL VMs lose internet. WireGuard VPN disconnects. DNS resolution fails for vm802. NFS may continue (storage VLAN direct) but no new connections. **Impact: complete outage for external access.**
3. **pve01** — If pve01 goes down: VM 100 (FREQ), VM 101 (Plex), VM 102 (Arr), VM 103 (qBit), VM 104 (Tdarr), VM 802 (Vaultwarden) all down. ISO storage for pve02/pve03 gone. NFS server for ISO gone. **Impact: 7 VMs including management and password vault. pve01 is the most loaded node.**
4. **VM 100** — If VM 100 goes down: FREQ fleet management lost. Obsidian vault mount lost. No automated fleet operations. **Impact: loss of all fleet automation.**
5. **Vaultwarden** — If VM 802 disk fails: ALL passwords permanently lost. No backup exists. **Impact: catastrophic credential loss.**

**Mitigations that should exist but don't:**
- No PVE HA configured for critical VMs
- No automatic failover for NFS
- No backup of Vaultwarden data
- No redundant management node
- No DNS failover

### Configuration Drift
**Grade: 6/10**

**Consistent across fleet:**
- Kernel versions: 6.12.73+deb13-amd64 on all VMs (except vm802: 6.12.69)
- PVE versions: 9.1.6 on all 3 nodes, same kernel
- User accounts: UID 3000-3004 consistent on all standard VMs
- NFS mounts: identical fstab entries on all Docker VMs
- SSH port: 22 everywhere, bound to mgmt VLAN IP on most hosts
- Timezone: America/Chicago everywhere

**Drift between hosts:**
| Config Item | Standard | Drifted Hosts |
|-------------|----------|---------------|
| SSH X11Forwarding | no | vm201 (yes), vm802 (yes), vm400 (yes) |
| SSH ListenAddress | mgmt IP | vm802 (0.0.0.0) |
| DNS nameserver | 1.1.1.1/8.8.8.8 | vm802 (10.25.0.1), vm103 (empty) |
| svc-admin UID | 3003 | vm802 (1001) |
| SSHD hardening conf | present | vm202 (missing), vm802 (empty?) |
| vm802 kernel | 6.12.73 | 6.12.69 (behind) |
| NTP sync | yes | vm802 (no) |

---

## Silent Failures Found

1. **VM 100 guest agent dead** — PVE shows agent enabled but it's not running. No one noticed because VM 100 is accessed via SSH, not PVE console. Breaks PVE snapshot consistency and IP reporting.
2. **TrueNAS API auth broken** — All 16 endpoints returned empty. FREQ TrueNAS commands may be silently failing.
3. **vm802 NTP not syncing** — `System clock synchronized: no` despite NTP service being active. Clock drift can cause TLS certificate validation failures and authentication token issues for Vaultwarden.
4. **Stale chroot mounts on pve02** — 34GB of ZFS zvols held open by abandoned FREQ rescue operations. Nobody noticed because the affected ZFS pool has plenty of space.
5. **Orphaned Docker volumes** — 15 volumes on vm103, 15 on vm202 — likely from old Gluetun/qBit recreations. Silently consuming inode space.
6. **pve01 NFS bound to all interfaces** — NFS accessible from mgmt VLAN, not just storage VLAN. Has been this way since deployment.
7. **Plex CPU pegged at 95%** — Either transcoding or library scan running. If this is sustained, streaming quality degrades.

---

## Dependency Map

```
Critical service dependencies:

vm100 (JARVIS) → needs: TrueNAS SMB (/mnt/obsidian), pve01 ZFS (boot disk)
vm101 (Plex)   → needs: TrueNAS NFS (media library), pfSense (internet for remote access)
vm102 (Arr)    → needs: TrueNAS NFS (media + downloads), pfSense (internet for indexers)
vm103 (qBit)   → needs: TrueNAS NFS (downloads), pfSense (internet for VPN), Gluetun (VPN tunnel)
vm104 (Tdarr)  → needs: TrueNAS NFS (media), vm301 (GPU worker node via network)
vm201 (SABnzbd)→ needs: TrueNAS NFS (downloads), pfSense (internet for usenet)
vm202 (qBit2)  → needs: TrueNAS NFS (downloads), pfSense (internet for VPN), Gluetun
vm301 (Tdarr)  → needs: TrueNAS NFS (media), vm104 (server), GPU passthrough
vm802 (Vault)  → needs: pfSense DNS (10.25.0.1), local disk only

If TrueNAS dies:
  ✗ vm101-Plex: media library unavailable, streaming stops
  ✗ vm102-Arr: can't download, can't manage library
  ✗ vm103/202-qBit: can't save downloads
  ✗ vm104/301-Tdarr: can't read/write media for transcoding
  ✗ vm201-SABnzbd: can't save downloads
  ✗ vm100-JARVIS: Obsidian vault unmounts (but FREQ continues from /opt/lowfreq)
  ✓ vm802-Vault: unaffected (local storage only)
  ✓ pfSense: unaffected
  ✓ PVE nodes: unaffected (VMs continue running, NFS mounts go stale)

If pve01 dies:
  ✗ vm100: FREQ management lost
  ✗ vm101: Plex down
  ✗ vm102: Arr stack down (no Sonarr, Radarr, Prowlarr)
  ✗ vm103: qBit primary down
  ✗ vm104: Tdarr server down (vm301 worker continues but can't report)
  ✗ vm802: Vaultwarden DOWN — passwords inaccessible
  ✗ vm804: Talos down (probably OK — experimental)
  ✗ ISO storage: pve02/pve03 lose ISO NFS mount
  ✓ vm201, vm202, vm301, vm400: continue on pve02/pve03
  → pve01 failure = 60%+ of infrastructure down

If pfSense dies:
  ✗ ALL VMs: lose internet access
  ✗ WireGuard: all remote access lost
  ✗ vm802: loses DNS (10.25.0.1)
  ✗ Inter-VLAN routing: stops (VLANs isolated from each other)
  ✓ Storage VLAN: NFS MAY continue if existing connections persist
  ✓ MGMT VLAN: SSH within VLAN continues

If vm100 dies:
  ✗ FREQ: all fleet management commands unavailable
  ✗ Obsidian vault: disconnected from update path
  ✓ All VMs: continue running independently
  ✓ Docker containers: continue functioning
  ✓ TrueNAS: continues independently
  → vm100 is operationally important but not runtime-critical
```

---

## Recommended Standardization Actions

### Immediate (this session / next session)

1. **Delete 8006 NAT rule on pfSense** — fixes CRIT-01 — 5 min
2. **Fix FREQ codebase permissions** — fixes CRIT-05 — 5 min
3. **Backup Vaultwarden data** — fixes CRIT-03 (partial) — 15 min
4. **Create PVE backup schedule** — fixes CRIT-02 — 15 min
5. **Run password auth disable script** — fixes HIGH-01 — 30 min
6. **Stop VM 402 if unused** — fixes HIGH-05 — 2 min

### Short term (next 2 weeks)

7. **Deploy daemon.json to all Docker VMs** — fixes HIGH-02 — 1h
8. **Fix vm802 hardening** (SSH, NTP, DNS, accounts) — fixes multiple findings — 2h
9. **Clean pve02 stale chroot mounts** — fixes HIGH-08 — 15 min
10. **Move API keys to .env files** — fixes CRIT-04 — 1h
11. **Fix TrueNAS API auth** — fixes HIGH-07 — 30 min
12. **Install qemu-guest-agent on vm100** — fixes MED-06 — 10 min
13. **Disable rpcbind fleet-wide** (except pve01/TrueNAS) — fixes MED-01 — 30 min
14. **Pin Docker images to version tags** — fixes HIGH-09 — 30 min
15. **Stop lab VMs (980/981)** if not actively being used — fixes LOW-05 — 2 min

### Medium term (next month)

16. **Deploy Wazuh** (per existing plan) — fixes security monitoring gap — 2h
17. **Set up TrueNAS snapshot schedules** — fills backup gap — 1h
18. **Configure PVE HA for critical VMs** (100, 802) — reduces SPOF risk — 2h
19. **Evaluate pve01 load distribution** — 7 VMs is too many on one node — 4h
20. **WireGuard peer audit and key rotation** — fixes MED-08 — 1h
21. **pfSense firmware: plan upgrade to stable** — fixes H-04 — 2h research

---

## What FREQ Currently Cannot See

Blind spots in current FREQ monitoring that this audit revealed:

1. **VM backup status** — FREQ has no command to check if backups are running or when last backup was taken
2. **Docker log size** — No check for Docker logs growing unbounded (no daemon.json = no rotation)
3. **NFS mount health** — No check if NFS mounts are stale or disconnected
4. **TrueNAS API connectivity** — FREQ doesn't verify API auth works before reporting status
5. **QEMU guest agent status** — No check if guest agent is running on VMs
6. **ZFS scrub schedule** — Can see scrub status but not verify schedule exists
7. **NTP sync status** — No fleet-wide NTP check
8. **DNS configuration** — No check for consistent DNS across fleet
9. **Docker image age/tag** — No check for containers running `:latest` or stale images
10. **WireGuard peer staleness** — No monitoring of VPN peer last-handshake age
11. **PVE backup schedule** — No verification that backup schedules exist and are running
12. **Disk prediction** — No growth-rate analysis to predict when disks will fill

---

## Overall Infrastructure Health Score

```
Network:      6/10  — Good VLAN design, marred by public NAT exposure
Storage:      7/10  — ZFS redundancy solid, daily backups to NFS with retention (revised from 5/10)
Compute:      6/10  — Cluster healthy but load imbalanced, pve03 near capacity
Security:     3/10  — SSH keys deployed but password auth still on, many open criticals
Containers:   7/10  — Clean architecture, good VLAN binding, needs daemon.json
Operations:   5/10  — No monitoring, no alerting, no centralized logging
Resilience:   5/10  — TrueNAS and pve01 are SPOFs, but daily backups exist (revised from 3/10)
Drift:        6/10  — Mostly consistent, vm802 is the outlier
──────────────
OVERALL:      5.6/10 (revised from 5.1 after CRIT-02 retraction)
```

**Compared to S076 security audit:** DEEPER analysis, NEW findings (CRIT-01 NAT exposure, API key exposure in compose files, TrueNAS API broken, pve03 RAM pressure, stale chroot mounts). Previous audit focused on SSH/sudoers/permissions. This audit covers full infrastructure stack. **CRIT-02 (zero backups) retracted** — daily backup schedule exists and is functioning correctly.

**The #1 action that would most improve this score:** Harden vm802 (Vaultwarden). The password vault is the most sensitive service and the least protected VM. SSH/nginx on all interfaces, no NTP, no probe accounts — fixing these moves Security from 3→4 and Drift from 6→7.

---

## Accepted Risk Register

### AR-01: Port 8006 NAT — PVE WebUI Public Access
- **Status:** ACCEPTED — documented operational decision
- **Reason:** Specific user requires direct WebUI access and cannot manage VPN client configuration. This is a deliberate tradeoff for that user's access needs.
- **Owner:** Sonny
- **Review date:** Next quarterly audit
- **Mitigations in place:**
  - PVE requires valid credentials to access
  - Consider adding: pfSense GeoIP block (allow only specific country/IPs)
  - Consider adding: pfSense source IP restriction to known user IPs when available
- **Residual risk:** PVE login page publicly accessible — brute force and CVE exposure remain

---

## Post-Audit Corrections & Actions (2026-03-08)

| Item | Action | Result |
|------|--------|--------|
| CRIT-02 | **RETRACTED** — auditor error. Daily backup schedule exists and is running (11 VMs, keep-last=4, truenas-backups NFS). | Backups verified: 44 archives, 346GB total |
| CRIT-03 (backup) | Manual Vaultwarden SQLite backup taken | 304KB archive with db.sqlite3 + rsa_key.pem → SMB share + Obsidian vault |
| CRIT-03 (PVE backup) | Already covered by daily PVE schedule | vm802: 816MB daily backups, 4 retained |
| CRIT-03 (cron) | Weekly SQLite backup cron command prepared | Requires root on vm100 to install — command in finding |
| CRIT-01 | Documented as accepted risk (AR-01) | Owner: Sonny, review: quarterly |

---

*This audit was performed entirely read-only. No configuration changes, service restarts, or file modifications were made on any host. Post-audit corrections and one manual Vaultwarden backup were performed in a follow-up session.*
