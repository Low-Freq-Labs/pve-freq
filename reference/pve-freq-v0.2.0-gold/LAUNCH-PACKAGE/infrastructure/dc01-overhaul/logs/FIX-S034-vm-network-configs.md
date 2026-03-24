# FIX-S034: VM Network Configuration Fixes
**Date:** 2026-02-20
**Session:** S034
**Operator:** Jarvis (automated via sshpass)

## Summary
Fixed 8 network configuration issues across 4 VMs found during S034 audit.

---

## VM 102 (Arr-Stack) — 10.25.255.31

### Fix 1: Set resolv.conf immutable
**Issue:** `/etc/resolv.conf` was not immutable — could be overwritten by DHCP/resolvconf.
**Pre-change:** `lsattr` showed `--------------e-------` (no immutable flag)
**Action:** `sudo chattr +i /etc/resolv.conf`
**Post-change:** `lsattr` shows `----i---------e-------` (immutable flag set)
**resolv.conf contents:** `nameserver 1.1.1.1` / `nameserver 8.8.8.8` (correct, preserved)

---

## VM 103 (qBit-Downloader) — 10.25.255.32

### Fix 1: ens18 MTU in interfaces file (1500 -> 9000)
**Issue:** `/etc/network/interfaces` had `mtu 1500` on ens18 stanza, but live MTU was already 9000 (set at runtime). Config file would revert to 1500 on reboot.
**Pre-change interfaces (ens18 stanza):**
```
allow-hotplug ens18
iface ens18 inet dhcp
	mtu 1500
```
**Action:** `sudo sed -i 's/mtu 1500/mtu 9000/' /etc/network/interfaces`
**Post-change:** Both ens18 and ens19 now show `mtu 9000` in interfaces file.
**Live MTU:** ens18 = 9000, ens19 = 9000 (both correct, no restart needed)

---

## VM 104 (Tdarr-Node) — 10.25.255.34

### Pre-change interfaces file:
```
allow-hotplug ens18
iface ens18 inet static
	address 10.25.10.34/24
	gateway 10.25.10.5
	# dns-* options are implemented by the resolvconf package, if installed
	dns-nameservers 10.25.0.1

allow-hotplug ens19
iface ens19 inet static
    address 10.25.255.34/24
    mtu 9000
    up ip route add 10.25.100.0/24 via 10.25.255.1
```

### Fix 1: Add mtu 9000 to ens18 stanza
**Issue:** ens18 stanza missing `mtu 9000`. Live MTU was already 9000 but wouldn't persist across reboot.
**Action:** `sudo sed -i` to insert `mtu 9000` after gateway line (required a follow-up fix for tab indentation)
**Post-change:** `mtu 9000` line present after gateway line with proper tab indentation.

### Fix 2: Change dns-nameservers to public DNS
**Issue:** `dns-nameservers 10.25.0.1` (pfSense) — should use public DNS `1.1.1.1 8.8.8.8`.
**Action:** `sudo sed -i 's/dns-nameservers 10.25.0.1/dns-nameservers 1.1.1.1 8.8.8.8/' /etc/network/interfaces`
**Post-change:** `dns-nameservers 1.1.1.1 8.8.8.8` confirmed.

### Fix 3: Set resolv.conf immutable
**Issue:** `/etc/resolv.conf` was not immutable.
**Pre-change:** `lsattr` showed `--------------e-------`
**Action:** `sudo chattr +i /etc/resolv.conf`
**Post-change:** `lsattr` shows `----i---------e-------`
**resolv.conf contents:** `nameserver 1.1.1.1` / `nameserver 8.8.8.8` (correct)

### Post-change interfaces file (VM 104):
```
allow-hotplug ens18
iface ens18 inet static
	address 10.25.10.34/24
	gateway 10.25.10.5
	mtu 9000
	# dns-* options are implemented by the resolvconf package, if installed
	dns-nameservers 1.1.1.1 8.8.8.8

allow-hotplug ens19
iface ens19 inet static
    address 10.25.255.34/24
    mtu 9000
    up ip route add 10.25.100.0/24 via 10.25.255.1
```

---

## VM 105 (Tdarr-Server) — 10.25.255.33

### Pre-change interfaces file:
```
allow-hotplug ens18
iface ens18 inet static
	address 10.25.10.33/24
	gateway 10.25.10.5
	# dns-* options are implemented by the resolvconf package, if installed
	dns-nameservers 10.25.0.1

allow-hotplug ens19
iface ens19 inet static
    address 10.25.255.33/24
    mtu 9000
    up ip route add 10.25.100.0/24 via 10.25.255.1
```

### Fix 1: Add mtu 9000 to ens18 stanza
**Issue:** ens18 stanza missing `mtu 9000`. Live MTU was already 9000 but wouldn't persist across reboot.
**Action:** Same sed approach as VM 104 (with indentation fix).
**Post-change:** `mtu 9000` line present with proper tab indentation.

### Fix 2: Change dns-nameservers to public DNS
**Issue:** `dns-nameservers 10.25.0.1` — should use `1.1.1.1 8.8.8.8`.
**Action:** `sudo sed -i 's/dns-nameservers 10.25.0.1/dns-nameservers 1.1.1.1 8.8.8.8/' /etc/network/interfaces`
**Post-change:** `dns-nameservers 1.1.1.1 8.8.8.8` confirmed.

### Fix 3: Set resolv.conf immutable
**Issue:** `/etc/resolv.conf` was not immutable.
**Pre-change:** `lsattr` showed `--------------e-------`
**Action:** `sudo chattr +i /etc/resolv.conf`
**Post-change:** `lsattr` shows `----i---------e-------`
**resolv.conf contents:** `nameserver 1.1.1.1` / `nameserver 8.8.8.8` (correct)

### Post-change interfaces file (VM 105):
```
allow-hotplug ens18
iface ens18 inet static
	address 10.25.10.33/24
	gateway 10.25.10.5
	mtu 9000
	# dns-* options are implemented by the resolvconf package, if installed
	dns-nameservers 1.1.1.1 8.8.8.8

allow-hotplug ens19
iface ens19 inet static
    address 10.25.255.33/24
    mtu 9000
    up ip route add 10.25.100.0/24 via 10.25.255.1
```

---

## Verification Summary

| VM | Fix | Status |
|----|-----|--------|
| 102 | resolv.conf immutable | PASS |
| 103 | ens18 MTU 1500 -> 9000 in interfaces | PASS |
| 103 | Live MTU ens18 | PASS (9000, no restart needed) |
| 104 | ens18 MTU 9000 added to interfaces | PASS |
| 104 | dns-nameservers -> 1.1.1.1 8.8.8.8 | PASS |
| 104 | resolv.conf immutable | PASS |
| 104 | Live MTU ens18/ens19 | PASS (both 9000) |
| 105 | ens18 MTU 9000 added to interfaces | PASS |
| 105 | dns-nameservers -> 1.1.1.1 8.8.8.8 | PASS |
| 105 | resolv.conf immutable | PASS |
| 105 | Live MTU ens18/ens19 | PASS (both 9000) |

**All 8 fixes applied and verified. No service restarts needed — live state already matched desired MTU values.**
