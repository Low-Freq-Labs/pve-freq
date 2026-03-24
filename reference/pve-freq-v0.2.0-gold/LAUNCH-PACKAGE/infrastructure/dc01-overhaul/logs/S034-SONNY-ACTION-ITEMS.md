# Sonny's Action Items — Session 34
**Date:** 2026-02-20
**Session:** S034 — Full Infrastructure Overhaul & Hardening

Everything Jarvis could fix autonomously has been fixed. Below are the items that need your hands.

---

## GUI Changes Required

### 1. pfSense: Fix VLAN Sub-Interface MTU (HIGH)
**Finding:** F-S034-MTU
**Problem:** All VLAN sub-interfaces are MTU 1500 while lagg0 is MTU 9000. Jumbo frames are broken through pfSense for inter-VLAN traffic.
**Where:** pfSense Web UI > Interfaces > each VLAN interface
**Fix:** Set MTU to 9000 on each:
- lagg0.5 (OPT4 / Public)
- lagg0.10 (OPT5 / Compute)
- lagg0.25 (OPT6 / Storage)
- lagg0.66 (OPT7 / Dirty)
- lagg0.2550 (OPT1 / Management)
**Impact:** Without this, jumbo frame pings between VLANs fail. NFS still works via TCP fragmentation but at reduced efficiency.

### 2. TrueNAS: Remove Weak SSH Ciphers (HIGH)
**Finding:** F-S034-CIPHER
**Problem:** SSH allows `AES128-CBC` (deprecated) and `NONE` (UNENCRYPTED sessions possible!)
**Where:** TrueNAS Web UI > System > Services > SSH > Advanced
**Fix:** Remove both `AES128-CBC` and `NONE` from the weak ciphers list. Leave only modern ciphers.

### 3. TrueNAS: Restrict ha-proxmox-disk NFS Export (HIGH)
**Finding:** F-S034-NFS-ACL
**Problem:** The HA Proxmox disk NFS export allows access from ANY host (`*`). Any device on the network can mount this share.
**Where:** TrueNAS Web UI > Shares > NFS > ha-proxmox-disk
**Fix:** Change the allowed hosts from `*` to specific Proxmox node IPs: `10.25.0.26 10.25.0.27 10.25.0.28`

### 4. Proxmox: Add Storage VLAN NIC to VM 103 (MEDIUM)
**Finding:** F-S034-VM103
**Problem:** VM 103 (qBit) has no NIC on VLAN 25 (Storage). NFS traffic goes over management VLAN.
**Where:** Proxmox Web UI > VM 103 > Hardware > Add > Network Device
**Fix:** Add a third NIC bridged to `vmbr0` with VLAN tag `25`. Then inside VM 103:
  1. Configure the new NIC in `/etc/network/interfaces` with `10.25.25.32/24` and `mtu 9000`
  2. Update `/etc/fstab` to use `10.25.25.25` instead of `10.25.255.25`
  3. Remount NFS

---

## Proxmox/Host Changes

### 5. VM 104 GPU Passthrough Fix (HIGH)
**Finding:** F-S034-GPU
**Problem:** RX580 amdgpu driver probe fails with error -22 (interrupt routing failure). No `/dev/dri/renderD128` = no GPU transcoding.
**Fix Options (try in order):**

**Option A — Install vendor-reset module on pve03:**
```bash
ssh svc-admin@10.25.255.28
sudo apt install pve-headers-$(uname -r) dkms git
sudo git clone https://github.com/gnif/vendor-reset.git /opt/vendor-reset
cd /opt/vendor-reset && sudo dkms install .
echo "vendor-reset" | sudo tee -a /etc/modules
sudo reboot
# After reboot, stop and start VM 104 (not just restart — need full power cycle)
```

**Option B — Try rombar=0:**
```bash
sudo qm set 104 --hostpci0 0000:06:00.0;0000:06:00.1,pcie=1,rombar=0
sudo qm stop 104 && sleep 5 && sudo qm start 104
```

**Verify inside VM 104:**
```bash
ls -la /dev/dri/   # Should show renderD128
```

### 6. Mamadou Server NAT Review (MEDIUM)
**Finding:** F-S034-NAT
**Problem:** pfSense NAT rule forwards TCP port 8006 from the INTERNET to 10.25.0.9. This exposes a Proxmox Web UI to the public internet.
**Action:** Is this intentional? If yes, consider restricting source IPs. If no, remove the NAT rule.

---

## Credential Tasks (Already Known)

### 7. SSH Key Deployment (CRITICAL — TICKET-0006)
Still the #1 priority. Generate SSH keypairs for svc-admin, deploy to all 10 systems, then:
- Disable password authentication (`PasswordAuthentication no` in sshd_config)
- Rotate the temporary password
- Nerf sonny-aif to minimal access
- Remove TrueNAS per-user PasswordAuthentication Match blocks

### 8. WireGuard Key Rotation (MEDIUM)
The WireGuard private key was exposed in staging data (now redacted). Generate a new keypair and update ProtonVPN + Gluetun `.env`.

### 9. iDRAC Default Passwords (LOW)
Both iDRACs (10.25.255.10 and 10.25.255.11) still have default credentials. Change them.

---

## Cleanup (Can Wait)

### 10. arr-data-backup-pre-overhaul-S032 (1.1G on NFS root)
Keep until backup cron is verified healthy for a few days (check after 2026-02-23). Then remove:
```bash
ssh svc-admin@10.25.255.25 'sudo rm -rf /mnt/mega-pool/nfs-mega-share/arr-data-backup-pre-overhaul-S032'
```

### 11. PVE Version Mismatch
pve03 has `pve-test.sources` repo enabled (gets newer packages). Either:
- Remove the test repo: `rm /etc/apt/sources.list.d/pve-test.sources` on pve03
- Or update pve01 to match (once 9.1.6 is in the stable repo)

### 12. pve02 Decision (TICKET-0008)
HA LRM dead 15+ days. Either recover the node or remove it from the cluster.

### 13. Switch Config Register (Quick Fix)
Config register is `0x2142` (password recovery / bypass startup-config mode). Should be `0x2102` for production. Fix:
```
ssh svc-admin@10.25.255.5
configure terminal
config-register 0x2102
end
write memory
```

---

## What Was Already Fixed (No Action Needed)

| Category | Details |
|----------|---------|
| Switch passwords | `service password-encryption` applied (F-018) |
| TrueNAS timezone | America/Chicago (F-024) |
| Stale VLANs | Investigated, harmless (F-025) |
| NFS cleanup | All symlinks, archives, .pre-overhaul dirs removed |
| NFS sysctl | 16MB buffers on all 7 systems |
| VM networking | MTU config, DNS, resolv.conf immutable on VMs 102-105 |
| Docker hardening | .env permissions, API key to .env, FlareSolverr volume |
| Backups | All 5 VMs producing NFS + local tarballs |
| NFS VLAN | VMs 101/102 moved to storage VLAN (10.25.25.25) |
| pve03 swap | 8GB ZFS zvol added |
| pve03 ZFS | rpool features upgraded |
| Kernel updates | VMs 102/103 on 6.12.73 |
| SSH hardening | X11Forwarding disabled on 7 systems |
| Plex sudo | plex user removed from sudo group |
| Switch NTP | Configured, synchronized (stratum 4, CST) |
| Staging redacted | All passwords, hashes, private keys scrubbed |

---

*Generated by Jarvis — Session 34 Overhaul Complete*
