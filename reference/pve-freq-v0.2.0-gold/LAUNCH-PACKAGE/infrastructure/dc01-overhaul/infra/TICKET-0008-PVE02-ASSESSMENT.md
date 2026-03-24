# TICKET-0008: pve02 HA LRM Assessment

> Generated: S035-20260220
> Priority: P2 (HIGH)
> Status: Assessment Complete -- Awaiting Sonny Decision

---

## 1. Background

pve02 (`10.25.0.27`) is the third node in the `dc01-cluster` Proxmox cluster. It has been unreachable by the cluster since **February 5, 2026** -- over 15 days. The HA Local Resource Manager (LRM) on pve02 is reported as **DEAD** by both pve01 and pve03.

pve02 is marked **OUT OF SCOPE** for our infrastructure work. It hosts only VM 100 (SABnzbd at `10.25.0.150:8080`), which is also out of scope. pve02 has no VLAN 25 (Storage) or VLAN 2550 (Management) configured, its corosync ring0 address is on VLAN 1 (`10.25.0.27`) rather than the management VLAN used by pve01/pve03, and it uses its own `os-pool-ssd` storage separate from the shared TrueNAS infrastructure.

Despite being out of scope operationally, pve02's continued membership in the cluster has real implications for quorum, HA behavior, and cluster configuration cleanliness.

---

## 2. Current State Summary

| Component | Value |
|---|---|
| Cluster name | dc01-cluster |
| Corosync config version | 8 |
| Transport | knet, secauth enabled |
| Active nodes | pve01 (`10.25.255.26`) + pve03 (`10.25.255.28`) |
| Expected votes | 2 (already adjusted from 3) |
| Total votes | 2 |
| Quorum | Yes |
| HA Master | pve03 (idle) |
| pve01 LRM | idle, current (Feb 20 22:45:53) |
| pve02 LRM | **DEAD** -- last seen Thu Feb 5 19:21:30 2026 |
| pve03 LRM | idle, current |
| pve02 in corosync nodelist | Yes (nodeid 2, `10.25.0.27`, 1 vote) |
| pve02 node dir in pmxcfs | Exists (`/etc/pve/nodes/pve02/`) |
| pve02 qemu-server configs | Empty (no VM configs in pmxcfs) |
| pve02 certificates | Stale (Feb 5) |

---

## 3. Impact Analysis

### What is currently broken

1. **pve02 LRM is DEAD.** The HA subsystem on pve01/pve03 continuously reports pve02 as unreachable. This is a persistent error condition in cluster logs and the HA status output.

2. **Stale cluster metadata.** pve02's node directory (`/etc/pve/nodes/pve02/`) still exists in pmxcfs with stale certificates and an outdated `lrm_status` file from Feb 5. This is dead weight in the cluster filesystem.

3. **Corosync nodelist mismatch.** pve02 is still defined in the corosync nodelist (nodeid 2, 1 vote) but `expected_votes` has already been manually reduced to 2. This is a workaround, not a clean configuration -- the nodelist says 3 nodes but the vote count says 2.

### What is NOT broken (currently)

1. **Quorum is stable.** With `expected_votes=2` and both active nodes voting, quorum holds as long as both pve01 AND pve03 remain up.

2. **HA resources are unaffected.** pve02 has no HA-managed resources. The HA master (pve03) is idle and functional.

3. **No VM configs are orphaned.** pve02's `qemu-server/` directory in pmxcfs is empty -- VM 100 (SABnzbd) is configured locally on pve02 and does not appear in the shared cluster filesystem.

4. **No storage dependencies.** pve02 uses `os-pool-ssd` (local to pve02), not the shared TrueNAS NFS infrastructure.

### What is at risk

1. **Single-node-failure quorum loss.** With a 2-of-3 cluster running on 2 nodes and `expected_votes=2`, if EITHER pve01 OR pve03 goes down, quorum is lost. HA stops. This is the same risk as a true 2-node cluster without a QDevice, but the configuration is messier because corosync still believes it is a 3-node cluster.

2. **Surprise reconnection.** If pve02 comes back online unexpectedly (e.g., someone reboots it), it will attempt to rejoin the cluster with its stale state. Depending on corosync version deltas and pmxcfs state, this could cause split-brain scenarios or configuration conflicts.

3. **Cluster operations may fail.** Certain `pvecm` and HA management operations may behave unpredictably with a ghost node in the nodelist. Future cluster maintenance (adding a new node, changing quorum settings) will be complicated by pve02's phantom presence.

---

## 4. Options

### Option A: RECOVER pve02

Bring pve02 back into the cluster as a fully participating member.

**What this requires:**
- Physical/network access to pve02 to diagnose why it went offline
- Restart corosync on pve02 and verify it rejoins cleanly
- Configure VLAN 25 (Storage) and VLAN 2550 (Management) on pve02
- Move pve02's corosync ring0 address from `10.25.0.27` (VLAN 1) to a `.255.X` address (VLAN 2550) to match pve01/pve03
- Revert `expected_votes` back to 3
- Verify HA LRM comes up healthy
- Bring pve02 up to the same Proxmox/kernel version as the other nodes

**Pros:**
- Restores true 3-node quorum -- any single node can fail without losing quorum
- pve02 becomes available for future VM workloads (125 GB RAM is significant capacity)
- Preserves the original cluster topology

**Cons:**
- Significant work scope -- pve02 is currently out of scope for a reason
- Requires VLAN 25 and VLAN 2550 configuration on pve02 (networking homework)
- Unknown hardware platform -- no documentation on pve02's physical specs beyond 125 GB RAM
- pve02's iDRAC cable is not plugged in (`10.25.0.12` unreachable) -- no out-of-band recovery option
- Risk of configuration drift causing issues during rejoin
- Does not solve the fundamental problem that pve02 is architecturally different (no storage VLAN, different ring0 VLAN, separate storage pool)

### Option B: REMOVE pve02 from the cluster

Permanently remove pve02 from the Proxmox cluster using `pvecm delnode`, converting dc01-cluster to a clean 2-node cluster.

**What this requires:**
- Ensure pve02 is powered off or network-isolated (it must NOT be running corosync during removal)
- Run `pvecm delnode pve02` from pve01 or pve03
- Clean up residual pmxcfs entries (`/etc/pve/nodes/pve02/`)
- Update corosync configuration (nodelist reduced to 2 nodes)
- Optionally configure a QDevice for 2-node quorum resilience
- Optionally reinstall pve02 standalone if SABnzbd needs to keep running

**Pros:**
- Eliminates the ghost node and all associated risks (surprise reconnection, stale metadata, confusing HA status)
- Clean corosync configuration -- nodelist matches reality
- Simplifies future cluster operations
- pve02 can be reinstalled as a standalone Proxmox host if SABnzbd needs to keep running -- it does not need to be in the cluster for that
- Matches the operational reality (pve02 has been effectively out of the cluster for 15+ days with no impact)

**Cons:**
- **Destructive operation** -- `pvecm delnode` cannot be easily undone. Re-adding pve02 later requires a fresh Proxmox install on pve02 and `pvecm add` from scratch.
- Reduces to a true 2-node cluster -- still vulnerable to single-node-failure quorum loss unless a QDevice is deployed
- Loses pve02's 125 GB RAM as potential cluster capacity
- VM 100 (SABnzbd) would need to either run on a standalone pve02 or be migrated elsewhere

---

## 5. Recommendation: Option B -- REMOVE pve02

**Reasoning:**

1. **pve02 has been dead for 15+ days with zero operational impact.** Nothing we manage depends on it. No HA resources, no shared storage, no managed VMs. The cluster has been operating as a 2-node cluster this entire time.

2. **Recovery is a large, unbounded project.** Bringing pve02 back properly means configuring VLANs 25 and 2550, changing its corosync ring0 address, verifying NFS access, documenting its hardware, and validating HA -- essentially onboarding a new node. This is significant work for a machine whose only workload (SABnzbd) does not require cluster membership.

3. **A ghost node is worse than no node.** The current state (3-node nodelist, 2-node operation, manually adjusted votes) is a configuration smell. It will confuse future troubleshooting and complicates any cluster maintenance. A clean 2-node cluster is better than a dirty 3-node cluster with a dead member.

4. **SABnzbd does not need the cluster.** VM 100 runs locally on pve02 with local storage. It gains nothing from cluster membership. If pve02 is removed from the cluster, it can continue running SABnzbd as a standalone Proxmox host (or even be reinstalled clean).

5. **Re-adding later is straightforward.** If Sonny decides to bring pve02 back into the fold in the future, a fresh `pvecm add` after proper VLAN configuration is cleaner than trying to recover a 15-day-stale node.

6. **Quorum risk is identical either way.** Whether pve02 is a ghost node or removed, the cluster is functionally 2-node. Removing it just makes the configuration honest. A QDevice can be evaluated separately as a future hardening item.

---

## 6. Step-by-Step Procedure (Option B -- Remove pve02)

> **DESTRUCTIVE OPERATION.** Follow every step. Do not skip the pre-checks or backup steps.

### Phase 1: Pre-Checks and Backup

**Step 1.** Verify pve02 is not running corosync (it should be offline, but confirm):
```bash
# From pve01 or pve03:
pvecm status
# Confirm: Only pve01 and pve03 are listed as active members.
# pve02 must NOT appear in the "Membership information" active list.
```

**Step 2.** Capture pre-change baseline:
```bash
# From pve01 (SSH as svc-admin):

# Save current corosync config
cat /etc/pve/corosync.conf > ~/pve02-removal-backup/corosync.conf.pre

# Save current HA status
ha-manager status > ~/pve02-removal-backup/ha-status.pre

# Save pvecm status
pvecm status > ~/pve02-removal-backup/pvecm-status.pre

# Save pve02 node directory listing
ls -laR /etc/pve/nodes/pve02/ > ~/pve02-removal-backup/pve02-node-dir.pre

# Save full node list
pvecm nodes > ~/pve02-removal-backup/pvecm-nodes.pre
```

**Step 3.** Verify no HA resources are assigned to pve02:
```bash
ha-manager status
# Confirm: No resources show pve02 as their current or target node.
```

**Step 4.** Verify pve02 has no VM configs in pmxcfs:
```bash
ls /etc/pve/nodes/pve02/qemu-server/
# Expected: empty directory
```

### Phase 2: Remove pve02 from the Cluster

**Step 5.** Remove pve02 from the cluster (run from pve01 OR pve03 -- NOT from pve02):
```bash
pvecm delnode pve02
```

**Step 6.** If `pvecm delnode` refuses because of the node directory, manually clean pmxcfs:
```bash
# Only if Step 5 fails with an error about /etc/pve/nodes/pve02:
rm -rf /etc/pve/nodes/pve02
# Then retry:
pvecm delnode pve02
```

**Step 7.** Verify corosync nodelist is updated:
```bash
cat /etc/pve/corosync.conf
# Confirm: Only pve01 and pve03 in the nodelist.
# Confirm: expected_votes = 2 (or absent, which defaults correctly for 2 nodes).
```

### Phase 3: Post-Removal Verification

**Step 8.** Verify cluster status:
```bash
pvecm status
# Expected: 2 nodes, 2 expected votes, 2 total votes, quorum achieved.
# pve02 should NOT appear anywhere.
```

**Step 9.** Verify HA status:
```bash
ha-manager status
# Expected: pve03 master (idle), pve01 LRM (idle).
# pve02 LRM should no longer appear.
```

**Step 10.** Verify pmxcfs is clean:
```bash
ls /etc/pve/nodes/
# Expected: pve01/ and pve03/ only. No pve02/.
```

**Step 11.** Verify both active nodes see the same cluster state:
```bash
# From pve03:
pvecm status
ha-manager status
cat /etc/pve/corosync.conf
# Should match pve01's output.
```

**Step 12.** Save post-change state:
```bash
# From pve01:
pvecm status > ~/pve02-removal-backup/pvecm-status.post
ha-manager status > ~/pve02-removal-backup/ha-status.post
cat /etc/pve/corosync.conf > ~/pve02-removal-backup/corosync.conf.post
```

### Phase 4: pve02 Standalone (Optional -- Only if SABnzbd Must Keep Running)

If pve02 needs to continue running SABnzbd, it should be converted to a standalone Proxmox host. This is done ON pve02 itself after it is removed from the cluster:

**Step 13.** SSH to pve02 and stop cluster services:
```bash
systemctl stop pve-cluster corosync
```

**Step 14.** Force pmxcfs to local mode:
```bash
pmxcfs -l
```

**Step 15.** Remove corosync config on pve02:
```bash
rm /etc/pve/corosync.conf
rm -rf /etc/corosync/*
```

**Step 16.** Restart pve-cluster in standalone mode:
```bash
killall pmxcfs
systemctl start pve-cluster
```

**Step 17.** Verify pve02 works standalone:
```bash
# Access pve02 web UI at https://10.25.0.27:8006
# VM 100 (SABnzbd) should be visible and manageable
```

> **Note:** Steps 13-17 are optional and only needed if Sonny wants pve02 to continue operating as a standalone Proxmox host. If pve02 is being decommissioned entirely, skip this phase.

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `pvecm delnode` causes unexpected cluster disruption | LOW | HIGH | Pre-change backup captured. Both nodes verified healthy before operation. Can restore corosync.conf from backup if needed. |
| pve02 comes online during removal and causes split-brain | LOW | CRITICAL | Verify pve02 is offline before starting. If possible, ensure pve02 is powered off or network cable disconnected. |
| Quorum loss after removal (single node failure) | MEDIUM | HIGH | Same risk as current state. Not introduced by this change. Mitigate with QDevice evaluation (future project). |
| SABnzbd (VM 100) becomes inaccessible | LOW | LOW | VM 100 runs on pve02's local storage. Cluster removal does not affect local VMs. pve02 can be converted to standalone (Phase 4). |
| Need to re-add pve02 later | LOW | MEDIUM | Fresh install + `pvecm add` is the supported path. More reliable than recovering a stale node. Document this as a future option. |

### Rollback Plan

If the removal causes unexpected issues on the remaining cluster:

1. **Restore corosync.conf** from the pre-change backup:
   ```bash
   cp ~/pve02-removal-backup/corosync.conf.pre /etc/pve/corosync.conf
   ```
2. **Restart corosync** on both active nodes:
   ```bash
   systemctl restart corosync
   ```
3. **Verify quorum and HA** return to pre-change state (ghost pve02 is better than a broken cluster).

> **Important:** Rollback restores pve02 to the corosync nodelist but does NOT bring pve02 back online. It simply returns to the current "ghost node" state, which is functional if imperfect.

---

## 8. Post-Removal Follow-Up Items

| Item | Priority | Notes |
|---|---|---|
| Evaluate QDevice for 2-node quorum | MEDIUM | A Corosync QDevice (qdevice-net) on a lightweight VM or LXC can provide a tie-breaking vote, preventing quorum loss if one of the two remaining nodes goes down. |
| Update DC01.md cluster documentation | HIGH | Remove pve02 from cluster topology, update node count, update corosync section. |
| Update CLAUDE.md | HIGH | Reflect 2-node cluster status. Remove "pve02 LRM dead" references. |
| Update ARCHITECTURE.md | HIGH | Remove pve02 from node tables and corosync config. |
| Decide on pve02 hardware fate | LOW | Keep as standalone for SABnzbd? Repurpose? Decommission? Sonny's call. |
| Clean up switch port config for pve02 | LOW | Gi1/3 and Gi1/4 are trunk ports for pve02. If decommissioning, reclaim these ports. |

---

## 9. Decision Required

Sonny, the recommendation is **Option B: Remove pve02 from the cluster**. The cluster has been running without pve02 for 15+ days with no issues. Removing it makes the configuration match reality and eliminates the risk of a stale node causing problems down the road.

**Your call:**
- **[ ] Option A -- RECOVER:** Bring pve02 back into the cluster (significant work, requires VLAN homework completion)
- **[ ] Option B -- REMOVE:** Clean removal via `pvecm delnode` (recommended, procedure above)
- **[ ] Option C -- DO NOTHING:** Leave as-is (not recommended -- ghost node is a liability)

Once you decide, we execute. No rush, but this should not stay in limbo indefinitely.
