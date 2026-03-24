# Sonny's Homework: Out-of-Scope Systems

> **Created:** 2026-02-18 — Jarvis
> **Last updated:** 2026-02-20 — Session 32 (paths updated for post-overhaul architecture)
> **Purpose:** Step-by-step guides for systems Jarvis won't touch. These are learning exercises — Sonny does them himself.
> **Rule:** Complete these AFTER Jarvis finishes the in-scope migration. The NFS path has been renamed and the Docker Infrastructure Overhaul is complete.

---

## Task 1: SABnzbd VM (VMID 100, pve02) — NFS Migration

**What this VM does:** SABnzbd is the Usenet downloader. It's part of the Plex/Arr stack but runs on pve02 (10.25.0.27) instead of pve01. It mounts the same NFS share as all the other VMs.

**Why you need to do this:** The ZFS dataset has been renamed from `zfs-share` to `nfs-mega-share`, NFS has been rebound to the Storage VLAN (`10.25.25.25`), and the media directory is now `media/` (lowercase). This VM's NFS mount still points to the old path/IP. The VM will boot fine, but `/mnt` will be empty — SABnzbd won't be able to write downloads.

**Note:** pve02 doesn't have VLAN 25 (Storage) configured yet — see Task 5 below. Until Task 5 is done, use `10.25.0.25` (LAN) as the NFS server IP. After Task 5, change to `10.25.25.25` (Storage VLAN) for consistency with all other VMs.

**What you'll learn:** Editing fstab, creating mount points, understanding NFS mounts, updating Docker volume paths.

### Prerequisites
- VPN connected (you need SSH access to 10.25.0.150)
- The ZFS rename has already been completed by Jarvis
- You know the SABnzbd VM root password or have sudo access

### Step 1: SSH into the SABnzbd VM

```bash
ssh sonny-aif@10.25.0.150
```

If your SSH key isn't on this VM, you'll need the password. If `sonny-aif` doesn't have sudo on this VM, you'll need to use root.

**What's happening:** You're connecting to the VM over the network. SSH (Secure Shell) gives you a remote terminal session. Port 22 is the default SSH port.

### Step 2: Check the current state

```bash
# See what's currently mounted
mount | grep nfs

# Look at the current fstab entry
cat /etc/fstab

# Check if Docker is running
docker ps
```

**What you should see:**
- The NFS mount will either be showing the old path (if the rename hasn't happened yet) or will be missing/failed (if the rename already happened)
- fstab will have a line like: `10.25.0.25:/mnt/mega-pool/zfs-share /mnt nfs ...`
- Docker containers may or may not be running depending on whether NFS is mounted

**What's happening:** `mount` shows all active filesystem mounts. `/etc/fstab` is the file that tells Linux what to mount at boot. `docker ps` lists running containers.

### Step 3: Stop Docker containers

```bash
# Stop SABnzbd container gracefully
docker compose down
# OR if there's no compose file in the current directory:
docker stop sabnzbd
```

**What's happening:** `docker compose down` stops and removes containers defined in the compose file. `docker stop` sends SIGTERM to the container, giving it time to shut down cleanly. We stop Docker first so no process is writing to the NFS mount when we unmount it.

### Step 4: Unmount the old NFS share

```bash
sudo umount /mnt
```

If it says "target is busy":
```bash
# Find what's using it
sudo lsof +D /mnt

# Force unmount (lazy — detaches immediately, cleans up when processes release)
sudo umount -l /mnt
```

**What's happening:** `umount` detaches the filesystem. `-l` (lazy) is the safe force option — it marks the mount as detached so new access fails, but waits for existing file handles to close naturally. Never use `umount -f` on NFS unless you absolutely must — it can corrupt data.

### Step 5: Create the new mount point

```bash
sudo mkdir -p /mnt/truenas/nfs-mega-share
```

**What's happening:** `mkdir -p` creates the directory and any parent directories that don't exist. This is where the NFS share will mount going forward. The `-p` flag means "no error if it already exists." All other VMs use `/mnt/truenas/nfs-mega-share` — this matches the standard.

### Step 6: Edit fstab

```bash
sudo nano /etc/fstab
```

Find the line that looks like:
```
10.25.0.25:/mnt/mega-pool/zfs-share /mnt nfs nfsvers=3,defaults 0 0
```

Change it to:
```
10.25.0.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0
```

> **Note:** Use `10.25.0.25` for now since pve02 doesn't have VLAN 25. After completing Task 5 (Storage VLAN), change this to `10.25.25.25` to match all other VMs.

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano).

**What changed and why:**
- `/mnt/mega-pool/zfs-share` → `/mnt/mega-pool/nfs-mega-share` — the TrueNAS export path changed because we renamed the ZFS dataset
- `/mnt` → `/mnt/truenas/nfs-mega-share` — the local mount point changed so we're not overloading a system directory (matches all other VMs)
- Added `_netdev` — tells Linux "this mount needs networking, don't try to mount it before the network is up." Without this, if the VM boots and tries to mount NFS before the network interface is ready, it hangs.
- Added `nofail` — tells Linux "if this mount fails, don't stop the boot process." Without this, if TrueNAS is down or NFS is unreachable, your VM gets stuck at boot and never reaches a login prompt. You'd need Proxmox console access to fix it.
- Added `soft,timeo=150,retrans=3,bg` — prevents D-state lockups. `soft` returns an I/O error instead of hanging forever when NFS is unresponsive. `timeo=150` sets 15-second timeout. `retrans=3` retries 3 times before giving up. `bg` retries the mount in the background during boot so the VM doesn't hang. These were added to all VMs in Session 32 after repeated NFS stale mount incidents.

### Step 7: Mount and verify

```bash
# Mount using the new fstab entry
sudo mount /mnt/truenas/nfs-mega-share

# Verify the mount
mount | grep nfs
# Should show: 10.25.0.25:/mnt/mega-pool/nfs-mega-share on /mnt/truenas/nfs-mega-share type nfs ...

# Verify data is visible
ls /mnt/truenas/nfs-mega-share/media/
# Should show: movies, tv, audio, downloads, transcode, config-backups (all lowercase)
```

**What's happening:** `mount /mnt/truenas/nfs-mega-share` reads fstab, finds the entry for that mount point, and executes the mount. This is why fstab must be correct — it's the source of truth for mount commands.

> **Note:** The media directory was renamed from `plex/` to `media/` and all subdirectories are now lowercase (e.g., `movies/` not `Movies/`). Temporary symlinks (`plex→media`, `Movies→movies`, etc.) exist for backward compatibility but will be removed after 2026-02-22.

### Step 8: Update Docker compose volumes

Find the SABnzbd compose file:
```bash
# It might be in the home directory, /opt, or somewhere else
find / -name "docker-compose*" -path "*/sabnzbd*" 2>/dev/null
# OR
find / -name "docker-compose*" 2>/dev/null | head -20
```

Edit it:
```bash
sudo nano /path/to/docker-compose.yml
```

Look for any volume paths that reference `/mnt/` and update them:
- `/mnt/plex/Downloads` → `/mnt/truenas/nfs-mega-share/media/downloads`
- `/mnt/plex/Movies` → `/mnt/truenas/nfs-mega-share/media/movies`
- `/mnt/plex/TV` → `/mnt/truenas/nfs-mega-share/media/tv`
- Any other `/mnt/` path → `/mnt/truenas/nfs-mega-share/media/` equivalent (all lowercase)

**What's happening:** Docker compose files define volume mounts — mappings between paths on the host (your VM) and paths inside the container. If the host path changes but the compose file still references the old path, the container will either mount an empty directory or fail to start.

> **New architecture note (Session 32):** On the other VMs, compose files + service configs have been moved LOCAL to `/opt/dc01/`. NFS is only used for shared media data. You may want to adopt this pattern for SABnzbd too — compose at `/opt/dc01/compose/docker-compose.yml`, SABnzbd config at `/opt/dc01/configs/sabnzbd/`. This prevents the D-state lockup issues that plagued NFS-hosted configs.

### Step 9: Start Docker

```bash
cd /path/to/compose/directory
docker compose up -d

# Verify
docker ps
# SABnzbd should be running

# Check logs for errors
docker logs sabnzbd --tail 20
```

**What's happening:** `docker compose up -d` creates and starts containers in detached mode (background). `-d` means "don't attach my terminal to the container output." `docker logs` shows you what the container is printing to stdout/stderr — this is where you'd see errors.

### Step 10: Verify SABnzbd is working

Open a browser and go to `http://10.25.0.150:8080`

You should see the SABnzbd web UI. Check:
- Can it see its download directory?
- Can it see the completed downloads folder?
- Try downloading a small NZB to verify the full path works

---

## Task 2: Create svc-admin on SABnzbd VM (VMID 100)

**What you'll learn:** Linux user management, understanding UIDs/GIDs, sudo configuration.

### Step 1: SSH into the VM

```bash
ssh sonny-aif@10.25.0.150
```

### Step 2: Create the group and user with the correct IDs

```bash
# Create the truenas_admin group (GID 950) — matches TrueNAS NFS anonuid/anongid
sudo groupadd -g 950 truenas_admin

# Create svc-admin with UID 3003 and primary GID 950
sudo useradd -u 3003 -g 950 -m -s /bin/bash svc-admin
```

**What the flags mean:**
- `groupadd -g 950 truenas_admin` — creates a group called `truenas_admin` with GID 950. This matches the GID used on TrueNAS and all other VMs, so NFS file permissions are consistent. If the group already exists, this will error — that's fine, skip it.
- `-u 3003` — set the UID (user ID) to 3003. Without this, Linux picks the next available number. We want all svc-admin accounts to have UID 3003 across every system for consistency (matches the svc-admin user created on TrueNAS).
- `-g 950` — set the primary group to GID 950 (truenas_admin). This ensures files created by svc-admin have the correct group ownership for NFS.
- `-m` — create a home directory (`/home/svc-admin`)
- `-s /bin/bash` — set the default shell to bash (otherwise it might default to `/bin/sh` or `/usr/sbin/nologin`)

### Step 3: Set the password

```bash
sudo passwd svc-admin
# Enter the password when prompted (you know what it is)
```

**What's happening:** `passwd` sets or changes a user's password. The password is stored as a hash in `/etc/shadow` (not plaintext). Only root can change another user's password, which is why we use `sudo`.

### Step 4: Grant sudo access

```bash
echo 'svc-admin ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/svc-admin
sudo chmod 440 /etc/sudoers.d/svc-admin
```

**What's happening:**
- The sudoers line means: "svc-admin, on ALL hosts, can run commands as ALL users, without a password, for ALL commands"
- We put it in `/etc/sudoers.d/svc-admin` instead of editing `/etc/sudoers` directly. The main sudoers file includes everything in the `.d/` directory. This is cleaner — one file per user, easy to remove.
- `chmod 440` sets the file to read-only for root and the root group. sudo REFUSES to load files with wrong permissions — this is a security feature. If you see "sudo: /etc/sudoers.d/svc-admin is mode 0644, should be 0440" in logs, this is why.

### Step 5: Verify

```bash
id svc-admin
# Expected: uid=3003(svc-admin) gid=950(truenas_admin) groups=950(truenas_admin)

# Test sudo
sudo -u svc-admin sudo whoami
# Expected: root
```

---

## Task 3: Create svc-admin on pve02 (10.25.0.27)

**Same as Task 2** but on the Proxmox host instead of a VM. One extra step — Proxmox PAM realm.

### Step 1: SSH and create user

```bash
ssh sonny-aif@10.25.0.27

# Create the truenas_admin group (GID 950) — matches TrueNAS NFS anonuid/anongid
sudo groupadd -g 950 truenas_admin

# Create svc-admin with UID 3003 and primary GID 950
sudo useradd -u 3003 -g 950 -m -s /bin/bash svc-admin
sudo passwd svc-admin
echo 'svc-admin ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/svc-admin
sudo chmod 440 /etc/sudoers.d/svc-admin
```

### Step 2: Add to Proxmox PAM realm

```bash
sudo pveum user add svc-admin@pam
sudo pveum acl modify / -user svc-admin@pam -role Administrator
```

**What's happening:**
- Proxmox has its own user management layer on top of Linux. `pveum` (Proxmox VE User Manager) manages it.
- `svc-admin@pam` means "the user svc-admin, authenticated via PAM" (PAM = Pluggable Authentication Modules, which reads `/etc/shadow` — i.e., normal Linux passwords)
- The ACL line gives svc-admin full Administrator rights on `/` (the root of the Proxmox object tree — all nodes, VMs, storage, etc.)
- Without this step, svc-admin could SSH in and use sudo, but couldn't use the Proxmox web UI or API.

### Step 3: Verify

```bash
id svc-admin
# uid=3003(svc-admin) gid=950(truenas_admin) groups=950(truenas_admin)

sudo pveum user list | grep svc-admin
# Should show svc-admin@pam
```

---

## Task 4: SABnzbd VM — Add to Docker Group

**Context:** When we checked pve02 last time, sonny-aif was added to the docker group on the SABnzbd VM. svc-admin will need the same.

```bash
ssh sonny-aif@10.25.0.150
sudo usermod -aG docker svc-admin
```

**What's happening:**
- `usermod -aG docker svc-admin` adds svc-admin to the `docker` group
- `-a` means "append" — without it, usermod REPLACES all groups (dangerous!)
- `-G docker` specifies the group to add
- Members of the `docker` group can run `docker` commands without sudo. This is basically root-equivalent access (docker can mount any filesystem, access any network), but it's the standard way Docker is managed.

---

## Task 5: pve02 VLAN 25 Storage Interface (Future — When Ready)

**Context:** pve01 has `vmbr1.25` (dedicated NIC) and pve03 has `vmbr0v25` (Proxmox VLAN bridge) for VLAN 25 storage. pve02 has neither. When you're ready to move pve02's NFS traffic to VLAN 25, here's how.

> **IMPORTANT:** Use the Proxmox GUI (Node → Network) to create this, NOT the command line. Creating it via GUI ensures it uses the correct `vmbr0v25` naming pattern (Proxmox VLAN bridge). Using the old `vmbr0.25` dot-notation causes a split-brain bug where the kernel delivers tagged frames to the wrong interface — see DC01.md Lesson Learned #13. pve01 and pve03 both hit this bug and it caused cluster outages.

### Step 1: Create the VLAN interface via Proxmox GUI

1. Log in to Proxmox web UI: `https://10.25.0.27:8006`
2. Click on `pve02` node → `Network`
3. Click `Create` → `Linux VLAN`
4. Configure:
   - **Name:** `vmbr0v25` (this is the correct Proxmox VLAN bridge pattern)
   - **VLAN raw device:** `vmbr0`
   - **VLAN Tag:** `25`
   - **IPv4/CIDR:** `10.25.25.27/24`
   - **MTU:** `9000`
5. Click `Create`, then click `Apply Configuration`

### Alternative: Create via CLI (if GUI unavailable)

```bash
ssh sonny-aif@10.25.0.27

sudo nano /etc/network/interfaces.d/vlan25-storage.conf
```

Content:
```
auto vmbr0v25
iface vmbr0v25 inet static
    address 10.25.25.27/24
    mtu 9000
    vlan-id 25
    vlan-raw-device vmbr0
```

**What's happening:**
- `vmbr0v25` is a Proxmox VLAN bridge — it tags traffic with VLAN ID 25 on the existing bridge `vmbr0`
- **DO NOT use `vmbr0.25`** (dot notation) — this creates a regular Linux VLAN sub-interface that conflicts with Proxmox's internal `nic0.25` interfaces. The kernel delivers tagged frames to `nic0.25` first, making `vmbr0.25` deaf. Use `vmbr0v25` instead.
- `mtu 9000` enables jumbo frames (matching the switch and TrueNAS config)
- This file goes in `/etc/network/interfaces.d/` because the main interfaces file has `source /etc/network/interfaces.d/*` at the bottom — it automatically includes everything in that directory

### Step 2: Bring it up

```bash
sudo ifreload -a
```

**What's happening:** `ifreload -a` re-reads all interface configuration and applies changes without disrupting existing connections. It's the Proxmox-safe way to apply network changes (vs `systemctl restart networking` which would briefly drop all connections including VM bridges).

### Step 3: Verify

```bash
ip addr show vmbr0.25
# Should show 10.25.25.27/24

ping -c 3 10.25.25.25
# Should reach TrueNAS storage NIC
```

---

## Task 6: pve02 Management VLAN 2550 (Future — When Ready)

Same pattern as Task 5, but for management. **Use Proxmox GUI** (preferred) or CLI.

**GUI:** Node → Network → Create → Linux VLAN → Name: `vmbr0v2550`, Raw device: `vmbr0`, Tag: `2550`, IPv4: `10.25.255.27/24`, MTU: `9000`.

**CLI fallback:**

```bash
sudo nano /etc/network/interfaces.d/vlan2550-mgmt.conf
```

Content:
```
auto vmbr0v2550
iface vmbr0v2550 inet static
    address 10.25.255.27/24
    mtu 9000
    vlan-id 2550
    vlan-raw-device vmbr0
```

> **Remember:** Use `vmbr0v2550` NOT `vmbr0.2550` — same split-brain bug as Task 5. See DC01.md Lesson Learned #13.

```bash
sudo ifreload -a
ping -c 3 10.25.255.1   # pfSense management gateway
```

**After VLAN 2550 is working**, add a VPN return route so VPN clients can reach pve02 on management VLAN:
```bash
# Add to the end of vlan2550-mgmt.conf:
    post-up ip route add 10.25.100.0/24 via 10.25.255.1 || true
```
This matches the routing fix applied on pve01 and pve03 in Session 29.

---

## Concepts to Understand

### Why UIDs matter across systems
When VM 102 writes a file to NFS as UID 3000, TrueNAS stores the file with owner UID 3000. When VM 104 reads that same file, it sees UID 3000 and checks if that UID has permission. If UID 3000 doesn't exist on VM 104, the file shows as owned by a number instead of a name — but permissions still work based on the number.

This is why we standardize UIDs: `sonny-aif` = 3000 everywhere, `svc-admin` = 3003 everywhere (matching the UID created on TrueNAS). If they were different on each system, file permissions would be chaos.

**Note on Docker PUID:** Docker containers in the Plex/Arr stack now use `PUID=3003` (svc-admin) instead of `PUID=3000` (sonny-aif). This means containers write files as svc-admin. The `sonny-aif` UID of 3000 is still correct for the Linux user on VMs — it's the Docker container identity that changed.

TrueNAS adds a twist: NFS `all_squash` maps ALL incoming writes to `anonuid=950` (gid=950). So no matter who writes the file, TrueNAS stores it as uid=950/gid=950. This simplifies permissions but means the UID of the writing user doesn't matter for NFS — what matters is that the PGID (950) matches across systems.

### Why `_netdev,nofail` is critical in fstab
Without `_netdev`: Linux tries to mount NFS during early boot, before networking is up. Mount fails, boot hangs forever. You need Proxmox console to fix it.

Without `nofail`: If the NFS server (TrueNAS) is down when the VM boots, mount fails, and Linux stops the boot process entirely. Again, console-only recovery.

With both: Linux waits for networking, tries to mount NFS, and if it fails, continues booting anyway. You can SSH in and fix it. Always use both on NFS mounts.

### How VLAN sub-interfaces work
Your switch port carries multiple VLANs on a trunk. When pve01 sends a packet on `vmbr0v25`, the Linux kernel adds a VLAN 25 tag (4 extra bytes in the Ethernet header). The switch sees the tag and routes it to VLAN 25. When a reply comes back tagged VLAN 25, the kernel strips the tag and delivers it to the `vmbr0v25` interface.

The physical NIC (`nic0`/`eno3`) only sees raw Ethernet frames. The bridge (`vmbr0`) connects VMs to the physical NIC. VLAN bridges (`vmbr0v25`, `vmbr0v2550`) add/remove VLAN tags. It's all software — no extra cables needed.

**CRITICAL naming note:** On Proxmox, always use `vmbr0v25` (Proxmox VLAN bridge), NEVER `vmbr0.25` (Linux dot-notation VLAN sub-interface). Proxmox internally creates `nic0.25` interfaces for VM VLAN tagging. If you also create `vmbr0.25`, the kernel delivers tagged frames to `nic0.25` first and `vmbr0.25` never sees them — making your host VLAN IP unreachable. This caused cluster outages on pve01 and pve03 before it was diagnosed and fixed.

---

## Checklist

- [ ] Task 1: SABnzbd NFS migration (after Jarvis completes ZFS rename)
- [ ] Task 2: svc-admin on SABnzbd VM
- [ ] Task 3: svc-admin on pve02 + Proxmox PAM
- [ ] Task 4: svc-admin docker group on SABnzbd VM
- [ ] Task 5: pve02 VLAN 25 storage interface (when ready)
- [ ] Task 6: pve02 VLAN 2550 management interface (when ready)
