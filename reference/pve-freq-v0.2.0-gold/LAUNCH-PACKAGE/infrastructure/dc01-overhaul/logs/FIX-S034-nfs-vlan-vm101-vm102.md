# FIX-S034: NFS VLAN Correction — VM 101 & VM 102

**Date:** 2026-02-20
**Session:** S034
**Operator:** Jarvis
**Status:** DONE

## Summary

VMs 101 and 102 were mounting NFS via the management VLAN (`10.25.255.25`) instead of the storage VLAN (`10.25.25.25`). VMs 104 and 105 were already correct. This fix aligns all four VMs to use the storage VLAN for NFS traffic, which is the intended architecture — management VLAN carries SSH/web UI traffic, storage VLAN carries NFS/data traffic.

## Pre-Change State

| VM | Hostname | IP | fstab NFS target | Correct? |
|----|----------|-----|-------------------|----------|
| 101 | Plex-Server | 10.25.255.30 | 10.25.255.25 | NO |
| 102 | Arr-Stack | 10.25.255.31 | 10.25.255.25 | NO |
| 104 | Tdarr-Node | 10.25.255.34 | 10.25.25.25 | YES |
| 105 | Tdarr-Server | 10.25.255.33 | 10.25.25.25 | YES |

## VM 101 — Plex-Server (10.25.255.30)

### Step 1: Pre-change fstab
```
10.25.255.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0
```

### Step 2: Docker compose down
```
Container plex Stopping
Container plex Stopped
Container plex Removing
Container plex Removed
```
Result: SUCCESS — 1 container stopped cleanly.

### Step 3: Unmount NFS
Result: SUCCESS — clean unmount, no errors.

### Step 4: Update fstab (sed 10.25.255.25 -> 10.25.25.25)
Post-change fstab:
```
10.25.25.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0
```
Result: SUCCESS — single substitution, verified.

### Step 5: Remount NFS
Result: SUCCESS — mounted without errors.

### Step 6: Verify mount
```
10.25.25.25:/mnt/mega-pool/nfs-mega-share on /mnt/truenas/nfs-mega-share type nfs (rw,relatime,vers=3,rsize=1048576,wsize=1048576,namlen=255,soft,proto=tcp,timeo=150,retrans=3,sec=sys,mountaddr=10.25.25.25,mountvers=3,mountport=51604,mountproto=udp,local_lock=none,addr=10.25.25.25,_netdev)
```
Result: SUCCESS — NFS mounted via storage VLAN (10.25.25.25).

### Step 7: Docker compose up -d
```
Container plex Created
Container plex Started
```
Result: SUCCESS — 1 container started.

### Step 8: Verify containers (after 15s wait)
```
CONTAINER ID   IMAGE                                                   STATUS          NAMES
f805b50a7221   lscr.io/linuxserver/plex:1.43.0.10492-121068a07-ls293   Up 19 seconds   plex
```
Result: SUCCESS — Plex running, healthy.

---

## VM 102 — Arr-Stack (10.25.255.31)

### Step 1: Pre-change fstab
```
10.25.255.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0
```

### Step 2: Docker compose down
```
Container prowlarr Stopped/Removed
Container agregarr Stopped/Removed
Container radarr Stopped/Removed
Container bazarr Stopped/Removed
Container sonarr Stopped/Removed
Container huntarr Stopped/Removed
Container overseerr Stopped/Removed
Network compose_default Removed
```
Result: SUCCESS — 7 containers stopped cleanly.

### Step 3: Unmount NFS
Result: SUCCESS — clean unmount, no errors.

### Step 4: Update fstab (sed 10.25.255.25 -> 10.25.25.25)
Post-change fstab:
```
10.25.25.25:/mnt/mega-pool/nfs-mega-share /mnt/truenas/nfs-mega-share nfs nfsvers=3,_netdev,nofail,soft,timeo=150,retrans=3,bg 0 0
```
Result: SUCCESS — single substitution, verified.

### Step 5: Remount NFS
Result: SUCCESS — mounted without errors.

### Step 6: Verify mount
```
10.25.25.25:/mnt/mega-pool/nfs-mega-share on /mnt/truenas/nfs-mega-share type nfs (rw,relatime,vers=3,rsize=1048576,wsize=1048576,namlen=255,soft,proto=tcp,timeo=150,retrans=3,sec=sys,mountaddr=10.25.25.25,mountvers=3,mountport=51604,mountproto=udp,local_lock=none,addr=10.25.25.25,_netdev)
```
Result: SUCCESS — NFS mounted via storage VLAN (10.25.25.25).

### Step 7: Docker compose up -d
```
Network compose_default Created
Container bazarr Created/Started
Container agregarr Created/Started
Container prowlarr Created/Started
Container overseerr Created/Started
Container sonarr Created/Started
Container radarr Created/Started
Container huntarr Created/Started
```
Result: SUCCESS — 7 containers started.

### Step 8: Verify containers (after 15s wait)
```
CONTAINER ID   IMAGE                                            STATUS          NAMES
6a253d02baf9   lscr.io/linuxserver/bazarr:v1.5.5-ls337          Up 21 seconds   bazarr
7514bf16b3d8   lscr.io/linuxserver/radarr:6.0.4.10291-ls292     Up 21 seconds   radarr
72f07b95528a   lscr.io/linuxserver/sonarr:4.0.16.2944-ls302     Up 21 seconds   sonarr
9dd488d49256   lscr.io/linuxserver/overseerr:v1.34.0-ls157      Up 21 seconds   overseerr
943da47ef5fb   huntarr/huntarr:9.3.7                            Up 21 seconds   huntarr
f65870d68bf5   agregarr/agregarr:v2.4.0                         Up 21 seconds   agregarr
dde6106e1a3f   lscr.io/linuxserver/prowlarr:2.3.0.5236-ls137    Up 21 seconds   prowlarr
```
Result: SUCCESS — All 7 containers running. Huntarr health check initializing (normal).

---

## Post-Change State

| VM | Hostname | IP | fstab NFS target | Correct? |
|----|----------|-----|-------------------|----------|
| 101 | Plex-Server | 10.25.255.30 | 10.25.25.25 | YES |
| 102 | Arr-Stack | 10.25.255.31 | 10.25.25.25 | YES |
| 104 | Tdarr-Node | 10.25.255.34 | 10.25.25.25 | YES |
| 105 | Tdarr-Server | 10.25.255.33 | 10.25.25.25 | YES |

All 4 NFS-mounting VMs now consistently use the storage VLAN (10.25.25.25) for NFS traffic.

## Failures
None. All 16 steps (8 per VM) completed successfully.

## Rollback
If needed, reverse the fstab change on either VM:
```
sudo sed -i "s/10.25.25.25/10.25.255.25/" /etc/fstab
sudo umount /mnt/truenas/nfs-mega-share
sudo mount /mnt/truenas/nfs-mega-share
```
