# FIX-S034: Security Updates & SSH Hardening
**Session:** S034
**Date:** 2026-02-20
**Operator:** Jarvis (automated via svc-admin)

---

## Task 1: Security Updates — VM 102 & VM 103

### VM 102 (Arr-Stack — 10.25.255.31)
**Command:** `sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y`

**Packages upgraded (3):**
| Package | From | To |
|---------|------|----|
| inetutils-telnet | 2:2.6-3+deb13u1 | 2:2.6-3+deb13u2 |
| libgnutls30t64 | 3.8.9-3+deb13u1 | 3.8.9-3+deb13u2 |
| libpng16-16t64 | 1.6.48-1+deb13u1 | 1.6.48-1+deb13u3 |

**Held back (1):**
- linux-image-amd64: 6.12.69-1 -> 6.12.73-1 (requires reboot to take effect)

**Running kernel:** 6.12.69+deb13-amd64
**Result:** SUCCESS

### VM 103 (qBit-Downloader — 10.25.255.32)
**Command:** `sudo apt-get update && sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y`

**Packages upgraded (3):**
| Package | From | To |
|---------|------|----|
| inetutils-telnet | 2:2.6-3+deb13u1 | 2:2.6-3+deb13u2 |
| libgnutls30t64 | 3.8.9-3+deb13u1 | 3.8.9-3+deb13u2 |
| libpng16-16t64 | 1.6.48-1+deb13u1 | 1.6.48-1+deb13u3 |

**Held back (1):**
- linux-image-amd64: 6.12.69-1 -> 6.12.73-1 (requires reboot to take effect)

**Running kernel:** 6.12.69+deb13-amd64
**Result:** SUCCESS

**Note:** Both VMs need a reboot to activate the new kernel (6.12.73). Reboot planned after all session changes are complete.

---

## Task 2: Remove plex from sudo Group — VM 101

**System:** VM 101 (Plex-Server — 10.25.255.30)
**Command:** `sudo deluser plex sudo`

**Before:** `sudo:x:27:plex,sonny-aif,svc-admin`
**After:** `sudo:x:27:sonny-aif,svc-admin`

**Result:** SUCCESS — plex system user removed from sudo group.

---

## Task 3: Disable X11Forwarding — All 7 Linux Systems

All systems had `X11Forwarding yes` on line 92 of `/etc/ssh/sshd_config`.
Changed to `X11Forwarding no` via sed, then `systemctl reload sshd`.

| System | IP | Before | After | sshd Reload | Result |
|--------|-----|--------|-------|-------------|--------|
| pve01 | 10.25.255.26 | X11Forwarding yes | X11Forwarding no | OK | SUCCESS |
| pve03 | 10.25.255.28 | X11Forwarding yes | X11Forwarding no | OK | SUCCESS |
| VM 101 (Plex-Server) | 10.25.255.30 | X11Forwarding yes | X11Forwarding no | OK | SUCCESS |
| VM 102 (Arr-Stack) | 10.25.255.31 | X11Forwarding yes | X11Forwarding no | OK | SUCCESS |
| VM 103 (qBit-Downloader) | 10.25.255.32 | X11Forwarding yes | X11Forwarding no | OK | SUCCESS |
| VM 104 (Tdarr-Node) | 10.25.255.34 | X11Forwarding yes | X11Forwarding no | OK | SUCCESS |
| VM 105 (Tdarr-Server) | 10.25.255.33 | X11Forwarding yes | X11Forwarding no | OK | SUCCESS |

**Verification:** All 7 systems confirmed `X11Forwarding no` in sshd_config after reload. SSH sessions remained active (reload, not restart).

---

## Summary

| Task | Scope | Status |
|------|-------|--------|
| Security updates (VM 102) | 3 packages upgraded, 1 held (kernel) | DONE |
| Security updates (VM 103) | 3 packages upgraded, 1 held (kernel) | DONE |
| Remove plex from sudo (VM 101) | plex removed from sudo group | DONE |
| Disable X11Forwarding (7 systems) | All 7 changed from yes to no | DONE |

**Pending:** Reboot VM 102 and VM 103 to activate kernel 6.12.73-1 (scheduled after all session work completes).
