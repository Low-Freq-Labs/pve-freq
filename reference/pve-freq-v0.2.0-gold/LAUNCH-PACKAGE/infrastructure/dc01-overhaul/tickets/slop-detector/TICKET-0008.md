Title: pve02 HA LRM dead for 15 days — quorum risk
Session: S027-20260220
Context: Audit Phase A — `ha-manager status` on both pve01 and pve03 shows `lrm pve02 (old timestamp - dead?, Thu Feb 5 19:21:30 2026)`. pve02 is OUT OF SCOPE but its cluster membership affects quorum.
Diagnosis: pve02 has been unreachable by the cluster since Feb 5. With 3-node cluster and 1 node dead, quorum requires BOTH remaining nodes. If pve01 OR pve03 goes down, quorum is lost and HA stops working. This is a 2-of-3 single point of failure. [PROBABLE]
Exact Fix: Either (1) bring pve02 back online, or (2) remove pve02 from the cluster to convert to 2-node quorum with QDevice or `pvecm expected 1`. Decision required from Sonny.
Priority: P2
