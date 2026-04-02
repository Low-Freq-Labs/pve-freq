<!-- INTERNAL — Not for public distribution -->

# THE CONVERGENCE OF PVE FREQ

**The Command Taxonomy: How 810 Actions Fit Into 25 Domains That Last Forever**

**Author:** Morty (Lead Dev)
**Created:** 2026-04-01
**Purpose:** Before we build, we condense. This document maps every planned feature into a command tree that won't bloat, won't confuse, and won't need renaming in 10 years.

---

## The Problem

FEATURE-PLAN.md describes ~810 actions across 21 workstreams. If we build them all as top-level commands, the help screen becomes a novel. Users won't find anything. The tool becomes its own enemy.

But the research is right — every one of those features is real, solves a real problem, and belongs in FREQ. The answer isn't fewer features. The answer is **better organization.**

## The Insight

Most of the "commands" in the plan are actually **subcommands** or **flags** of a smaller set of root commands. Look at the overlaps:

- `freq audit`, `freq comply scan`, `freq cis scan`, `freq harden`, `freq sweep` → all "scan this host for security problems"
- `freq alert`, `freq rules`, `freq oncall`, `freq incident` → all "something went wrong, manage it"
- `freq backup`, `freq backup-policy`, `freq rollback`, `freq snapshot`, `freq dr backup` → all "protect my data"
- `freq netmon`, `freq snmp`, `freq topology`, `freq flow`, `freq net health` → all "what's happening on my network"
- `freq baseline`, `freq drift`, `freq gitops`, `freq plan`, `freq apply`, `freq state` → all "desired state vs reality"
- `freq config backup`, `freq config compliance`, `freq config search` (network) vs `freq config push/pull` (fleet) → both "manage configuration"
- `freq logs`, `freq metrics`, `freq trend`, `freq report`, `freq monitor` → all "observe my infrastructure"

The pattern: **one noun, many verbs.** Not many nouns with one verb each.

## The Rule

```
freq <DOMAIN> <ACTION> [TARGET] [--flags]
```

Every command follows this grammar. Domains are permanent. Actions grow over time. The domain name should be a word that will still make sense in 10 years.

---

## THE COMMAND TREE

### How to Read This

- **DOMAIN** = the top-level command (`freq vm`, `freq net`, `freq secure`, etc.)
- **Existing** = commands that already exist today (126 total), shown with their current name and where they move
- **New** = commands from FEATURE-PLAN.md workstreams
- **Converged From** = multiple planned commands that merge into one action with flags

---

## 1. `freq vm` — Virtual Machine Lifecycle

Everything about creating, configuring, running, and destroying VMs. One noun for the full lifecycle.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq vm list` | List VMs across cluster | **Replaces** current `freq list` | — |
| `freq vm create` | Create a new VM | **Replaces** current `freq create` | — |
| `freq vm clone` | Clone a VM | **Replaces** current `freq clone` | — |
| `freq vm destroy` | Destroy a VM | **Replaces** current `freq destroy` | — |
| `freq vm resize` | Resize cores/RAM/disk | **Replaces** current `freq resize` | — |
| `freq vm power <start/stop/reboot>` | Power control | **Replaces** current `freq power` | — |
| `freq vm snapshot <create/list/delete>` | Snapshot management | **Replaces** current `freq snapshot` | — |
| `freq vm rollback` | Restore from snapshot | **Replaces** current `freq rollback` | — |
| `freq vm migrate` | Move between nodes | **Replaces** current `freq migrate` | — |
| `freq vm nic <add/clear/change>` | NIC management | **Replaces** current `freq nic` | — |
| `freq vm import` | Import from backup | **Replaces** current `freq import` | — |
| `freq vm template` | Convert to template | **Replaces** current `freq template` | — |
| `freq vm rename` | Rename | **Replaces** current `freq rename` | — |
| `freq vm disk add` | Add disk | **Replaces** current `freq add-disk` | — |
| `freq vm tag` | PVE tags | **Replaces** current `freq tag` | — |
| `freq vm pool` | Pool management | **Replaces** current `freq pool` | — |
| `freq vm sandbox` | Spawn from template | **Replaces** current `freq sandbox` | — |
| `freq vm config` | View/edit VM config | **Replaces** current `freq vmconfig` | — |
| `freq vm overview` | Inventory across cluster | **Replaces** current `freq vm-overview` | — |
| `freq vm rescue` | Rescue stuck VM | **Replaces** current `freq rescue` | — |
| `freq vm why` | Explain protections | **Replaces** current `freq why` | — |

**Consolidation:** 21 current top-level commands → 1 domain. No functionality lost. `freq create` is deleted. `freq vm create` is the only way. Clean slate.

---

## 2. `freq fleet` — Fleet Operations

Everything about the fleet as a whole. Host management, execution, health, groups.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq fleet status` | Fleet health summary | **Replaces** current `freq status` | — |
| `freq fleet dashboard` | Dashboard overview | **Replaces** current `freq dashboard` | — |
| `freq fleet exec <target> <cmd>` | Run command across fleet | **Replaces** current `freq exec` | — |
| `freq fleet info <host>` | System info | **Replaces** current `freq info` | — |
| `freq fleet diagnose <host>` | Deep diagnostic | **Replaces** current `freq diagnose` | — |
| `freq fleet ssh <host>` | SSH to host | **Replaces** current `freq ssh` | — |
| `freq fleet log <host>` | View host logs | **Replaces** current `freq log` | — |
| `freq fleet compare <a> <b>` | Side-by-side compare | **Replaces** current `freq compare` | — |
| `freq fleet health` | Comprehensive health | **Replaces** current `freq health` | — |
| `freq fleet report` | Fleet health report | **Replaces** current `freq report` | — |
| `freq fleet ntp [check/fix]` | NTP management | **Replaces** current `freq ntp` | — |
| `freq fleet update [check/apply]` | OS updates | **Replaces** current `freq fleet-update` | — |
| `freq fleet comms [setup/send/check]` | Inter-VM mailbox | **Replaces** current `freq comms` | — |
| `freq fleet file send` | SCP file | **Replaces** current `freq file send` | — |
| `freq fleet service <list/start/stop> <host>` | **New** | WS17 `freq service` | systemd management |
| `freq fleet session <list/kill>` | **New** | WS17 `freq session` | Active SSH sessions |
| `freq fleet bandwidth <host-a> <host-b>` | **New** | WS17 `freq bandwidth test` | iperf3 test |
| `freq fleet traceroute <target>` | **New** | WS17 `freq traceroute` | — |

---

## 3. `freq host` — Host Registry

Adding, removing, discovering, grouping hosts.

| Action | What It Does | Origin |
|---|---|---|
| `freq host list` | List fleet hosts | **Replaces** current `freq hosts list` |
| `freq host add` | Add a host | **Replaces** current `freq hosts add` |
| `freq host remove` | Remove a host | **Replaces** current `freq hosts remove` |
| `freq host discover` | Discover on network | **Replaces** current `freq discover` |
| `freq host groups` | Manage groups | **Replaces** current `freq groups` |
| `freq host bootstrap` | Bootstrap new host | **Replaces** current `freq bootstrap` |
| `freq host onboard` | Onboard to fleet | **Replaces** current `freq onboard` |
| `freq host keys` | SSH key management | **Replaces** current `freq keys` |
| `freq host test <host>` | Test connectivity | **Replaces** current `freq test-connection` |

---

## 4. `freq net` — Network Intelligence & Switch Management

**This is the big convergence.** Currently `freq switch`, `freq netmon`, `freq map`, `freq ip` are all separate. They're all "the network." One domain.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| **Switch Core** | | | |
| `freq net switch show <target>` | Switch overview | **Replaces** current `freq switch status` | — |
| `freq net switch interfaces <target>` | Interface table | **Replaces** current `freq switch interfaces` | — |
| `freq net switch vlans <target>` | VLAN table | **Replaces** current `freq switch vlans` | — |
| `freq net switch mac <target>` | MAC table | **Replaces** current `freq switch mac` | — |
| `freq net switch arp <target>` | ARP table | **Replaces** current `freq switch arp` | — |
| `freq net switch facts <target>` | Device facts | **New** | WS1 |
| `freq net switch counters <target>` | Error counters | **New** | WS1 |
| `freq net switch neighbors <target>` | LLDP/CDP | **New** | WS1 |
| `freq net switch environment <target>` | Temp/fans/PSU | **New** | WS1 |
| `freq net switch config <target>` | Running config | **New** | WS1 |
| `freq net switch exec <target> "cmd"` | Raw command | **New** | WS1 |
| **Port Management** | | | |
| `freq net port status <target>` | Per-port detail | **New** | WS1 |
| `freq net port configure <target> <port>` | Configure port | **New** | WS1 `freq port configure` |
| `freq net port poe <target>` | PoE management | **New** | WS1 `freq port poe` |
| `freq net port find --mac XX:XX` | Find MAC on port | **New** | WS1 `freq port find` |
| `freq net port flap <target> <port>` | Bounce port | **New** | WS1 |
| `freq net port mirror` | Port mirroring | **New** | WS1 |
| `freq net port security` | Port security | **New** | WS1 |
| **Port Profiles** | | | |
| `freq net profile create/apply/list/show` | Port profiles | **New** | WS1 `freq switch profile` |
| **Network Config** | | | |
| `freq net config backup <target>` | Backup device config | **New** | WS1 `freq config backup` |
| `freq net config diff <target>` | Diff running vs backup | **New** | WS1 `freq config diff` |
| `freq net config history <target>` | Change history | **New** | WS1 |
| `freq net config search "pattern"` | Search all configs | **New** | WS1 |
| `freq net config restore <target>` | Push old config back | **New** | WS1 |
| `freq net config compliance` | Check against rules | **New** | WS1 — uses policy engine |
| **Protocols** | | | |
| `freq net stp status/root/topology` | Spanning tree | **New** | WS1 |
| `freq net qos status/policy/apply` | QoS management | **New** | WS1 |
| `freq net acl list/create/apply/test` | ACL management | **New** | WS1 |
| `freq net dot1x status/sessions/enable` | 802.1X | **New** | WS1 |
| **Intelligence** | | | |
| `freq net health` | Network health score | **New** | WS2 `freq net health` |
| `freq net topology [discover/show/diff/verify]` | Topology mapping | **Replaces partial** current `freq netmon topology`, `freq map discover` | Merges `netmon topology` + `map discover/impact/export` |
| `freq net find <mac-or-ip>` | Find device on network | **New** | WS2 `freq net find-mac`, `freq net find-ip` merged |
| `freq net trace <src> <dst>` | L2/L3 path trace | **New** | WS2 |
| `freq net rogue` | Unknown MACs | **New** | WS2 |
| `freq net troubleshoot <target>` | Guided debug | **New** | WS2 |
| **Monitoring** | | | |
| `freq net interfaces` | Fleet interface status | **Replaces** current `freq netmon interfaces` | — |
| `freq net bandwidth` | Bandwidth rates | **Replaces** current `freq netmon bandwidth` | merges `freq netmon poll` + `freq netmon bandwidth` |
| `freq net snmp poll/interfaces/errors/optics/cpu` | SNMP polling | **New** | WS2 |
| `freq net flow top-talkers/protocols/anomaly` | Traffic analysis | **New** | WS2 |
| **IPAM** | | | |
| `freq net ip next/list/check` | IP management | **Replaces** current `freq ip next/list/check` | — |
| `freq net ip utilization/conflict/scan/map` | Enhanced IPAM | **New** | WS2 |
| `freq net arp scan [--vlan N]` | ARP scan | **New** | WS17 |

**Consolidation:** `freq switch` + `freq netmon` + `freq map` + `freq ip` + all WS1/WS2 new commands → one `freq net` domain. This is the biggest win. It goes from 5 separate islands to one cohesive network management domain.

---

## 5. `freq fw` — Firewall & Gateway

Everything pfSense/OPNsense. Currently `freq pfsense` with 7 actions → expands massively but stays one domain.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq fw status` | Firewall overview | **Replaces** current `freq pfsense status` | — |
| `freq fw rules <list/create/delete/move/audit/test>` | Rule management | **Replaces partial** current `freq pfsense rules` | WS3 deep expansion |
| `freq fw nat <list/forward/test>` | NAT/port forwards | **Replaces partial** current `freq pfsense nat` | WS3 |
| `freq fw states` | Connection states | **Replaces** current `freq pfsense states` | — |
| `freq fw interfaces` | Interface status | **Replaces** current `freq pfsense interfaces` | — |
| `freq fw gateways [status/monitor/groups]` | Gateway management | **Replaces** current `freq pfsense gateways` | WS3 expansion |
| `freq fw services` | Service management | **Replaces** current `freq pfsense services` | — |
| `freq fw dhcp <pools/leases/static>` | DHCP management | **New** | WS3 |
| `freq fw dns <status/overrides/cache>` | DNS on firewall | **New** | WS3 |
| `freq fw shaper <list/limiter/profile/status>` | QoS/traffic shaping | **New** | WS3 |
| `freq fw blocker <status/feeds/whitelist/alerts>` | pfBlockerNG | **New** | WS3 |
| `freq fw ids <status/alerts/rules/passlist>` | Suricata IDS | **New** | WS3 |
| `freq fw ha <status/sync/maintenance>` | HA/CARP | **New** | WS3 |
| `freq fw portal <status/vouchers/users>` | Captive portal | **New** | WS3 |

**Why `fw` not `pfsense`:** The domain name should describe WHAT it manages, not the vendor. Supports OPNsense too. `fw` is short, clear, forever.

---

## 6. `freq dns` — DNS Management

Already exists current `freq dns scan/check`. Expands with backend management.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq dns scan` | Fleet-wide DNS validation | **Replaces** | — |
| `freq dns check <host>` | Single DNS check | **Replaces** | — |
| `freq dns list` | DNS inventory | **Replaces** | — |
| `freq dns sync [--dry-run]` | Sync fleet → DNS records | **New** | WS4 `freq dns internal sync` |
| `freq dns audit` | Find stale/missing records | **New** | WS4 `freq dns internal audit` |
| `freq dns add/remove --fqdn X --ip Y` | Manage records | **New** | WS4 |
| `freq dns pihole <status/blocking/lists/test>` | Pi-hole management | **New** | WS4 |
| `freq dns adguard <status/rewrites/clients>` | AdGuard management | **New** | WS4 |
| `freq dns unbound <local-data/cache/forward>` | Unbound management | **New** | WS4 |

**Note:** `freq dns internal sync/audit/add/remove` from the plan collapse into `freq dns sync/audit/add/remove` — the "internal" qualifier is unnecessary since FREQ only manages your internal DNS anyway.

---

## 7. `freq vpn` — VPN Management

Brand new domain. No existing commands.

| Action | What It Does | Converged From |
|---|---|---|
| `freq vpn wg <peers/status/provision/audit>` | WireGuard | WS5 — all `freq vpn wg` commands |
| `freq vpn ovpn <servers/clients/certs/export>` | OpenVPN | WS5 |
| `freq vpn tailscale <devices/routes/dns/keys/acl>` | Tailscale/Headscale | WS5 |
| `freq vpn ipsec <tunnels/status/logs/audit>` | IPsec | WS5 |

---

## 8. `freq cert` — Certificate & PKI

Already exists current `freq cert scan/check`. Expands into full lifecycle.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq cert scan` | Scan fleet for TLS certs | **Replaces** | — |
| `freq cert check <host:port>` | Single endpoint check | **Replaces** | — |
| `freq cert inventory [--expiring 30d]` | All certs everywhere | **New** | WS6 — absorbs existing `freq cert scan` as the default |
| `freq cert inspect <file-or-host:port>` | Parse cert details | **New** | WS6 `freq certs inspect` + `freq certs inspect --remote` merged |
| `freq cert issue --domain X` | ACME/Let's Encrypt | **New** | WS6 `freq certs acme issue` |
| `freq cert renew [--all]` | Renewal | **New** | WS6 `freq certs acme renew/renew-all` merged |
| `freq cert deploy --target nginx/proxmox/pfsense` | Deploy to service | **New** | WS6 |
| `freq cert ca <issue/revoke/distribute/ssh-cert>` | Private CA | **New** | WS6 |
| `freq cert audit` | Comprehensive cert health | **New** | WS6 `freq certs audit` + `freq certs acme audit` merged |
| `freq cert convert` | Format conversion | **New** | WS6 |

**Convergence:** `freq certs acme issue`, `freq certs acme renew`, `freq certs acme deploy`, `freq certs acme audit` all flatten. The `acme` qualifier goes away — `freq cert issue` uses ACME by default, `--provider ca` for private CA. One command, provider is a flag.

---

## 9. `freq proxy` — Reverse Proxy

Already exists. Expands with backend-specific APIs.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq proxy status` | Proxy detection | **Replaces** | — |
| `freq proxy list` | Managed routes | **Replaces** | — |
| `freq proxy add --domain X --upstream Y` | Add route | **Replaces** | — |
| `freq proxy remove` | Remove route | **Replaces** | — |
| `freq proxy certs` | Cert status for routes | **Replaces** | — |
| `freq proxy drain <backend>` | Graceful backend removal | **New** | WS7 `freq proxy haproxy servers drain` |
| `freq proxy health` | Check all backends | **New** | WS7 `freq proxy traefik health` |
| `freq proxy access <list/create>` | IP whitelists | **New** | WS7 `freq proxy npm access-lists` |
| `freq proxy streams <list/create>` | TCP/UDP forwarding | **New** | WS7 |

**Convergence:** `freq proxy npm hosts create`, `freq proxy caddy hosts create`, `freq proxy traefik routers create` all become just `freq proxy add`. FREQ auto-detects which proxy backend is running (already does this in `proxy status`) and uses the right API. The backend is an implementation detail, not a user concern.

---

## 10. `freq store` — Storage Management

Converges TrueNAS + ZFS + shares + Ceph + MinIO under one roof.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| **TrueNAS** | | | |
| `freq store nas status` | TrueNAS overview | **Replaces** current `freq truenas status` | — |
| `freq store nas dataset <list/create/quota>` | Dataset management | **New** | WS8 `freq truenas dataset` |
| `freq store nas snap <list/create/prune/hold>` | Snapshot management | **New** | WS8 `freq truenas snap` |
| `freq store nas repl <list/status/run>` | Replication | **New** | WS8 `freq truenas repl` |
| `freq store nas smart <status/test/results>` | SMART monitoring | **New** | WS8 `freq truenas smart` |
| `freq store nas share <list/smb/nfs>` | Share management | **New** | WS8 `freq truenas share` |
| **ZFS (any host)** | | | |
| `freq store zfs pool <list/status/iostat/scrub>` | Pool operations | **Replaces partial** current `freq zfs` | WS8 expansion |
| `freq store zfs snap <create/list/diff/send>` | ZFS snapshots | **New** | WS8 |
| `freq store zfs ds <list/create/set>` | Dataset operations | **New** | WS8 |
| **Fleet Shares** | | | |
| `freq store share <list/audit/mount test>` | Fleet-wide shares | **New** | WS8 `freq share` |
| **Ceph / MinIO** | | | |
| `freq store ceph <status/osd/pool/health>` | Ceph management | **New** | WS8 |
| `freq store s3 <bucket list/create/policy>` | S3/MinIO | **New** | WS8 — `s3` not `minio` because the API is S3 |

---

## 11. `freq dr` — Disaster Recovery & Backup

**This is the big one.** Currently spread across `freq backup`, `freq backup-policy`, `freq rollback`, `freq sla`, `freq snapshot`. All converge.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq dr status` | Backup coverage overview | **Replaces** current `freq backup status` | — |
| `freq dr backup <list/create/verify/restore>` | Backup management | **New** | WS9 — absorbs `freq backup` |
| `freq dr backup instant <backup-id>` | Boot VM from backup | **New** | WS9 |
| `freq dr policy <list/create/apply>` | Declarative backup rules | **Replaces** current `freq backup-policy` | moves here |
| `freq dr sla <list/set/status/report/alert>` | RTO/RPO tracking | **Replaces partial** current `freq sla` | WS9 extends |
| `freq dr prune` | Remove old backups | **Replaces** current `freq backup prune` | moves here |
| `freq dr replicate <vmid>/status` | VM replication | **New** | WS9 |
| `freq dr failover/failback` | Failover management | **New** | WS9 |
| `freq dr runbook <list/create/execute/test>` | DR runbooks | **New** | WS9 |
| `freq dr test <tabletop/simulation/failover>` | DR testing | **New** | WS9 |
| `freq dr pbs <status/verify/prune/gc/sync>` | PBS management | **New** | WS9 |

**Convergence:** `freq backup status` + `freq backup prune` + `freq backup-policy` + `freq sla` + `freq rollback` (for DR context) all live under `freq dr`. VM-level snapshots stay in `freq vm snapshot` — that's VM lifecycle, not DR.

---

## 12. `freq observe` — Observability Platform

**Another big convergence.** Metrics, logs, monitors, trends, alerts, status — all "watching your infrastructure."

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| **Metrics** | | | |
| `freq observe metrics <collect/show/top/query>` | Time-series metrics | **New** | WS10 `freq metrics` |
| `freq observe metrics predict <host> <metric>` | Predictive analytics | **New** | WS10 — absorbs `freq trend` |
| `freq observe metrics anomaly` | Anomaly detection | **New** | WS10/WS16 |
| **Logs** | | | |
| `freq observe logs <tail/search/errors/stats>` | Log management | **Replaces** current `freq logs tail/search/stats` | WS10 extends |
| `freq observe logs rate <pattern>` | Error rate | **New** | WS10 |
| `freq observe logs pattern <host>` | Pattern detection | **New** | WS10 |
| **Monitors** | | | |
| `freq observe monitor <list/add/remove/status>` | Synthetic checks | **Replaces partial** current `freq monitor` | WS10 extends |
| `freq observe monitor http/ssl/dns/port/ping` | Check types | **New** | WS10 |
| **Trends & Capacity** | | | |
| `freq observe trend <show/snapshot>` | Capacity sparklines | **Replaces** current `freq trend show/snapshot` | — |
| `freq observe capacity <show/forecast/simulate>` | Capacity planning | **Replaces** current `freq capacity` | WS10 extends |
| **Alerts** | | | |
| `freq observe alert <list/create/delete/check>` | Alert rules | **Replaces** current `freq alert` | — |
| `freq observe alert test/silence/history` | Alert management | **Replaces** | — |
| **Uptime** | | | |
| `freq observe uptime <report/sla/mttr/mttf>` | Uptime analytics | **New** | WS10 — absorbs `freq sla` for uptime context |
| **Status Page** | | | |
| `freq observe status-page <create/show/incident>` | Status pages | **New** | WS10 |
| **Cron Monitoring** | | | |
| `freq observe cron <list/register/ping/wrap/audit>` | Cron job monitoring | **New** | WS10 |

**Convergence:** `freq alert` + `freq logs` + `freq trend` + `freq capacity` + `freq monitor` + `freq report` + `freq sla` (uptime context) + all WS10 features → one domain. `freq report` becomes `freq observe report`. `freq trend` becomes `freq observe trend`.

**Note on `freq sla`:** SLA appears in TWO domains — that's the overlap you predicted. Uptime SLA lives in `freq observe uptime sla`. Backup RPO/RTO SLA lives in `freq dr sla`. They're different concepts with the same word.

---

## 13. `freq secure` — Security & Compliance

Converges everything "is my stuff safe?"

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| **Auditing** | | | |
| `freq secure audit [--fix] [--category X]` | Security audit | **Replaces** current `freq audit` | Absorbs `freq sweep`, adds categories |
| `freq secure audit score <host>` | Hardening score (0-100) | **New** | WS11 Lynis-style scoring |
| **Compliance** | | | |
| `freq secure comply <scan/report> [--level 1/2] [--section N]` | CIS/STIG compliance | **Replaces** current `freq comply scan/report` | WS11 extends massively |
| `freq secure comply fix [--preview] [--safe]` | Auto-remediate | **New** | WS11 `freq cis fix` |
| `freq secure comply exceptions` | Accepted risks | **New** | WS11 |
| **Hardening** | | | |
| `freq secure harden [--auto/--preview] [ssh/kernel/network]` | Apply hardening | **Replaces** current `freq harden` | WS11 extends |
| **Vulnerabilities** | | | |
| `freq secure vuln <scan/results/cves/trend/sla>` | Vulnerability scanning | **New** | WS11 `freq vuln` |
| `freq secure vuln exploitable` | Known exploits | **New** | WS11 |
| **Patching** | | | |
| `freq secure patch <status/check/apply/compliance>` | Patch management | **Replaces** current `freq patch` | — |
| **File Integrity** | | | |
| `freq secure fim <status/changes/baseline/watch>` | FIM | **New** | WS11 `freq fim` |
| **Secrets** | | | |
| `freq secure secrets <scan/audit/generate/lease>` | Secret management | **Replaces** current `freq secrets` | — |
| `freq secure vault <encrypt/decrypt/list>` | Credential store | **Replaces** current `freq vault` | — |
| **Container Security** | | | |
| `freq secure container <scan/images/sbom>` | Image scanning | **New** | WS11 `freq container scan` |
| **Intrusion Prevention** | | | |
| `freq secure ban <status/list/add/remove/top>` | Fail2ban/CrowdSec | **New** | WS11 `freq ban` |

**Convergence:** `freq audit` + `freq comply` + `freq harden` + `freq patch` + `freq secrets` + `freq vault` + `freq sweep` + all WS11 → one domain. `freq sweep` becomes `freq secure audit --full` (sweep was already "run all audits").

---

## 14. `freq ops` — Incident, Change & Problem Management

Everything about "something happened" or "something is about to happen."

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| **Incidents** | | | |
| `freq ops incident <create/list/update/close/timeline>` | Incident tracking | **New** | WS12 — absorbs `freq oncall alert/ack/resolve` |
| `freq ops incident stats` | MTTR analytics | **New** | WS12 |
| **Oncall** | | | |
| `freq ops oncall <whoami/schedule>` | On-call management | **Replaces** current `freq oncall` | — |
| **Changes** | | | |
| `freq ops change <create/approve/implement/rollback>` | Change management | **New** | WS12 |
| `freq ops change window <list/create/active>` | Maintenance windows | **New** | WS12 |
| `freq ops change freeze` | Change freeze | **New** | WS12 |
| **Problems** | | | |
| `freq ops problem <create/rca/workaround/close>` | Problem management | **New** | WS12 |
| **Postmortems** | | | |
| `freq ops postmortem <create/list/show>` | Post-mortem generation | **New** | WS12 |
| **Risk** | | | |
| `freq ops risk <target>` | Blast radius analysis | **Replaces** current `freq risk` | — |

---

## 15. `freq docker` — Container Fleet Management

Converges `freq docker`, `freq docker-fleet`, `freq stack` into one domain.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq docker ps [--host/--all]` | Container list | **Replaces** current `freq docker <host>` + `freq docker-fleet ps` | merged |
| `freq docker logs <container> [--host]` | Container logs | **Replaces partial** | merged |
| `freq docker stats [--host/--all]` | Resource usage | **Replaces partial** | merged |
| `freq docker stack <status/update/deploy/destroy>` | Stack management | **Replaces** current `freq stack status/update/health` | WS13 extends |
| `freq docker stack health` | Container health | **Replaces** current `freq stack health` | — |
| `freq docker volume <list/prune/backup>` | Volume management | **New** | WS13 |
| `freq docker image <list/prune/pull>` | Image management | **New** | WS13 |
| `freq docker update <check/apply/rollback/schedule>` | Auto-update | **New** | WS13 Watchtower replacement |
| `freq docker deploy <rolling/blue-green/canary>` | Deploy strategies | **New** | WS13 |
| `freq docker secrets <list/create/rotate>` | Secret management | **New** | WS13 |

**Convergence:** `freq docker <host>` + `freq docker-fleet` + `freq stack` → all `freq docker`. The `--host` flag targets a specific host; no flag = fleet-wide. `freq stack status` becomes `freq docker stack status`.

---

## 16. `freq hw` — Hardware Management

Converges iDRAC, IPMI, SMART, UPS, PDU, cost.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq hw idrac <status/power/thermal/storage/firmware/sel/bios>` | Dell iDRAC | **Replaces** current `freq idrac` | WS14 extends |
| `freq hw ipmi <power/sensor/sel/boot/sol>` | Generic BMC | **New** | WS14 |
| `freq hw smart <status/test/failing/predict>` | Disk health | **New** | WS14 |
| `freq hw ups <status/battery/load/runtime/test>` | UPS monitoring | **New** | WS14 |
| `freq hw pdu <status/outlet on/off/cycle>` | PDU management | **New** | WS14 |
| `freq hw cost` | Power cost estimates | **Replaces** current `freq cost` + `freq cost-analysis` | converges both |
| `freq hw inventory` | Full hardware inventory | **New** | WS14 `freq idrac inventory` |
| `freq hw asset <list/warranty/lifecycle>` | Asset tracking | **New** | WS12 `freq asset` |

**Convergence:** `freq idrac` + `freq cost` + `freq cost-analysis` + all WS14 → one domain. `freq cost-analysis waste/density/compare` becomes `freq hw cost waste/density/compare`.

---

## 17. `freq state` — Infrastructure as Code

Converges baseline, plan/apply, gitops, drift detection.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq state export [--format toml]` | Export infrastructure state | **New** | WS15 |
| `freq state snapshot --tag X` | Point-in-time snapshot | **New** | WS15 — absorbs `freq baseline capture` |
| `freq state compare [--tag X]` | Diff vs snapshot | **Replaces** current `freq baseline compare` | — |
| `freq state history` | List snapshots | **New** | WS15 |
| `freq state rollback --tag X` | Revert to snapshot | **New** | WS15 |
| `freq state plan [--file X]` | Diff desired vs actual | **Replaces** current `freq plan` | WS15 extends |
| `freq state apply [--file X]` | Execute plan | **Replaces** current `freq apply` | WS15 extends |
| `freq state drift [detect/fix]` | Drift detection | **New** | WS15 — absorbs `freq patrol` drift mode |
| `freq state import <vm/switch/all>` | Bring under management | **New** | WS15 |
| `freq state gitops <status/sync/diff>` | GitOps sync | **Replaces** current `freq gitops` | — |
| `freq state policy <list/check/fix/diff>` | Policy compliance | **Replaces** current `freq check/fix/diff/policies` | converges into domain |

**Convergence:** `freq baseline` + `freq plan` + `freq apply` + `freq gitops` + `freq check/fix/diff/policies` + `freq patrol` (drift mode) → one domain. This is FREQ's Terraform.

---

## 18. `freq auto` — Automation Engine

Converges rules, reactions, workflows, playbooks, schedules, remediation.

| Action | What It Does | Origin | Converged From |
|---|---|---|---|
| `freq auto events <tail/history>` | Event stream | **New** | WS16 |
| `freq auto react <add/list/disable/test>` | Reactor rules | **New** | WS16 — absorbs `freq rules` |
| `freq auto workflow <create/run/status/resume>` | DAG orchestration | **New** | WS16 |
| `freq auto job <list/run/create/schedule>` | Named operations | **New** | WS16 — absorbs `freq schedule` |
| `freq auto playbook <list/run>` | Incident playbooks | **Replaces** current `freq playbook` | — |
| `freq auto runbook <capture/replay>` | Record + replay CLI | **New** | WS16 |
| `freq auto remediate <configure/test/history>` | Self-healing | **New** | WS16 |
| `freq auto webhook <list/create/delete/test>` | Inbound triggers | **Replaces** current `freq webhook` | — |
| `freq auto chaos <list/run/log>` | Chaos experiments | **Replaces** current `freq chaos` | — |

**Convergence:** `freq rules` + `freq schedule` + `freq playbook` + `freq webhook` + `freq chaos` + `freq patrol` (monitoring mode) → one domain. This is FREQ's StackStorm.

---

## 19. `freq event` — Live Event Networking

Brand new domain. Sonny's killer feature. Separate from `freq net` because events are a workflow, not a device type.

| Action | What It Does |
|---|---|
| `freq event create "<name>"` | Create event project |
| `freq event plan` | Generate IP/VLAN plan |
| `freq event deploy --site X` | Push configs to all switches |
| `freq event verify --site X` | Validate everything matches |
| `freq event preflight --report` | Pre-event checklist |
| `freq event dashboard` | Live event NOC view |
| `freq event find <mac-or-ip>` | Find any device |
| `freq event troubleshoot` | Guided debug |
| `freq event timeline apply` | Scheduled config changes |
| `freq event wipe --confirm` | Factory reset all switches |
| `freq event archive` | Save everything |

---

## 20. Utility Commands (Stay Top-Level)

Some commands are so fundamental they don't need a domain. They stay at root.

| Command | What It Does | Origin |
|---|---|---|
| `freq init` | First-run setup wizard | **Replaces** |
| `freq configure` | Reconfigure settings | **Replaces** |
| `freq version` | Version and branding | **Replaces** |
| `freq help` | Command reference | **Replaces** |
| `freq doctor` | Self-diagnostic | **Replaces** |
| `freq menu` | Interactive TUI | **Replaces** |
| `freq demo` | Interactive demo | **Replaces** |
| `freq learn <query>` | Knowledge base search | **Replaces** |
| `freq serve` | Start web dashboard + API | **Replaces** |
| `freq docs <generate/verify/runbook>` | Documentation | **Replaces** |
| `freq publish <setup/status/teardown>` | Public access wizard | **New** (WS18) |
| `freq plugin <list/install/create>` | Plugin management | **New** (WS19) |

---

## Additional Domains

| Domain | What It Contains |
|---|---|
| `freq user <list/create/passwd/roles/promote/demote/install>` | User management (exists, consolidates 7 top-level commands) |
| `freq media <action> [svc]` | Media stack — already well-organized with 40+ subcommands |
| `freq specialist <create/health/roles>` | AI specialist VMs |
| `freq lab <status/deploy/resize/rebuild>` | Lab fleet |
| `freq agent <templates/create/list/start/stop/destroy>` | Agent platform |
| `freq federation <list/register/poll>` | Multi-site (may merge into `freq state` eventually) |
| `freq cmdb <list/detail/impact/scan>` | Config management DB — new |
| `freq inventory <hosts/vms/containers>` | Fleet CMDB export — exists |

---

## THE FINAL COUNT

| Domain | Top-Level Command | Subcommand Groups | Est. Actions |
|---|---|---|---|
| `freq vm` | Virtual machines | 21 | ~40 |
| `freq fleet` | Fleet operations | 18 | ~30 |
| `freq host` | Host registry | 9 | ~15 |
| `freq net` | Network & switches | 12 groups | ~80 |
| `freq fw` | Firewall & gateway | 14 groups | ~55 |
| `freq dns` | DNS management | 6 | ~25 |
| `freq vpn` | VPN management | 4 | ~30 |
| `freq cert` | Certificates & PKI | 10 | ~20 |
| `freq proxy` | Reverse proxy | 8 | ~15 |
| `freq store` | Storage | 3 subsystems | ~55 |
| `freq dr` | Disaster recovery | 8 | ~35 |
| `freq observe` | Observability | 7 groups | ~60 |
| `freq secure` | Security & compliance | 8 groups | ~55 |
| `freq ops` | Incident/change mgmt | 5 groups | ~25 |
| `freq docker` | Container fleet | 8 | ~35 |
| `freq hw` | Hardware | 7 | ~35 |
| `freq state` | Infrastructure as code | 10 | ~25 |
| `freq auto` | Automation engine | 8 | ~30 |
| `freq event` | Live event networking | 11 | ~15 |
| `freq user` | User management | 7 | ~10 |
| `freq media` | Media stack | 1 (existing) | ~40 |
| Utilities | Top-level | 12 | ~12 |
| Smaller domains | specialist, lab, agent, etc. | 5 | ~25 |
| **TOTAL** | **~25 domains** | | **~810 actions** |

From **126 top-level commands** (confusing, flat) to **~25 domains with ~810 actions** (organized, discoverable).

The help screen shows 25 domains. `freq net --help` shows the network subcommands. `freq net switch --help` shows switch actions. Three levels deep maximum. A user can always find what they need in 2-3 steps.

---

## THE OVERLAP MAP

You asked about commands that feel like they belong in two places. Here they are:

| Feature | Domain A | Domain B | Resolution |
|---|---|---|---|
| SLA tracking | `freq dr sla` (backup RPO/RTO) | `freq observe uptime sla` (uptime %) | **Both exist.** Different concepts. DR SLA = "is my data protected?" Uptime SLA = "is my service available?" |
| Drift detection | `freq state drift` (infra-wide) | `freq secure comply` (security-specific) | **Both exist.** State drift = "did someone change the config?" Compliance = "does it meet the standard?" Drift detects change, compliance judges it. |
| Config backup | `freq net config backup` (switch configs) | `freq state snapshot` (infra-wide state) | **Both exist.** Net config = device config files. State snapshot = abstract desired state. |
| Vulnerability patching | `freq secure patch` (apply patches) | `freq secure vuln` (scan for vulns) | **Both exist.** Scan finds problems, patch fixes them. Different verbs. |
| Health checks | `freq fleet health` (host health) | `freq net health` (network health) | **Both exist.** Different layers. Host health = CPU/RAM/disk. Network health = links/errors/topology. |
| Alert rules | `freq observe alert` (threshold alerts) | `freq auto react` (event-driven actions) | **Both exist.** Alerts notify humans. Reactors take automated action. Alert fires → human reads it. Reactor fires → automation handles it. |
| Container scanning | `freq secure container scan` (security) | `freq docker image list` (inventory) | **Both exist.** Security scans for CVEs. Docker lists what's running. Different intent. |
| DNS management | `freq dns` (record management) | `freq fw dns` (pfSense resolver config) | **Both exist.** `freq dns` = what records exist. `freq fw dns` = how the resolver is configured. Content vs plumbing. |
| Playbooks | `freq auto playbook` (automated) | `freq dr runbook` (DR-specific) | **Both exist.** Playbooks are general automation. DR runbooks are specifically ordered recovery procedures with different data (RTO targets, verify steps). |
| Topology | `freq net topology` (LLDP/CDP physical) | `freq observe` (service dependency map) | **Both exist.** Network topology = physical/L2 connections. Service map = application dependencies. Could live together but are conceptually different. |

**The rule:** If the same WORD appears in two domains but the INTENT is different, both exist. If the same WORD appears in two domains with the SAME intent, one absorbs the other.

---

## NO LEGACY. NO ALIASES. NO BAGGAGE.

There are no users. There is no backwards compatibility. Nobody has memorized the current 126 commands — not even us. The current top-level commands (`freq create`, `freq status`, `freq audit`, etc.) are **pre-release structure** that gets replaced wholesale by the converged domains.

When we build, we build the converged structure from day one. `freq vm create`, not `freq create`. `freq fleet status`, not `freq status`. The current flat command list was a prototype. This document is the real architecture.

Every module file, every CLI parser registration, every API endpoint, every test — built to the converged spec. There is nothing to migrate from.

---

## WHAT THIS DOCUMENT IS FOR

1. **Before building:** Review each domain. Does the grouping make sense? Are the names right? Will they make sense in 10 years?
2. **During building:** When adding a new command, check which domain it belongs in. Don't create a new top-level command if it fits in an existing domain.
3. **After building:** This is the spec for the help screen, the API endpoint structure (`/api/v1/net/switch/vlans`), and the dashboard navigation.

Build the features using FEATURE-PLAN.md. Organize them using this document. The Conquest is the plan. The Convergence is the architecture.
