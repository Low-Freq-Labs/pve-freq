<!-- INTERNAL — Not for public distribution -->

# GIT READY FOR PUBLIC RELEASE

**The Plan to Make PVE FREQ Run on Every Linux Distribution Under the Sun**

**Author:** Morty (Lead Dev)
**Created:** 2026-04-01
**Scope:** pve-freq + pve-freq-docker — both repos, every file, zero assumptions
**Philosophy:** If Python runs on it, FREQ runs on it. No excuses. No "tested on Ubuntu only." No corporate laziness.

---

## WHY THIS EXISTS

Every infrastructure tool in existence ships with "tested on Ubuntu 22.04" and calls it a day. When someone on Rocky Linux, Arch, Alpine, or NixOS hits an error, the maintainer closes the issue with "unsupported distro."

That is lazy. That is disrespectful. That is exactly what we are NOT doing.

FREQ will work on Debian. On Ubuntu. On RHEL. On Rocky. On Alma. On Fedora. On Arch. On Manjaro. On Alpine. On Void. On Gentoo. On NixOS. On openSUSE. On Slackware. On Raspberry Pi OS. On Proxmox VE. On TrueNAS SCALE. On Clear Linux. On Amazon Linux. It will manage pfSense and OPNsense (FreeBSD). It will manage iDRAC. It will manage Cisco switches that run IOS from 2008.

If it has Python 3.11+ and SSH, FREQ runs on it. Period.

---

## THE CODEBASE AUDIT

A full audit of every file in pve-freq was conducted. Here is every assumption that would break on a non-Debian system, ranked by severity.

### P0 — Ship Blockers (Breaks on any non-Debian distro)

| # | File | Line(s) | Problem | Breaks On | Fix |
|---|---|---|---|---|---|
| 1 | `comply.py` | 48, 72 | Remediation commands use `apt install -y` with no fallback | ALL non-Debian | Detect package manager: `if command -v apt; then apt install; elif command -v dnf; then dnf install; elif command -v pacman; then pacman -S; fi` |
| 2 | `audit.py` | 275-278 | Update check only uses `apt list --upgradable` | ALL non-Debian (always reports 0 updates) | Add dnf/pacman/zypper/apk fallbacks |
| 3 | `init_cmd.py` | 1114, 1140, 1959, 2011 | User-facing message says `Install with: apt install sshpass` | ALL non-Debian (confusing to RHEL/Arch users) | Use existing `preflight.get_install_hint()` which already has multi-distro support |
| 4 | `netmon.py` | 343 | User-facing message says `apt install lldpd` | ALL non-Debian | Use `get_install_hint()` or show multi-distro options |
| 5 | `config.py` | 9 | `import tomllib` — bare import, no try/except | Python <3.11 crashes at import time | Already handled in some modules with try/except — make consistent everywhere |
| 6 | `preflight.py` | 18 | `MIN_PYTHON = (3, 7)` contradicts `pyproject.toml` `>=3.11` and `compat.py` `MIN_PYTHON = (3, 11)` | Confusing — allows startup on 3.7 then crashes on tomllib | Align to `(3, 11)` everywhere |

### P1 — Breaks on RHEL/Rocky/Alma (The Second Most Popular Server Distro Family)

| # | File | Line(s) | Problem | Fix |
|---|---|---|---|---|
| 7 | `patch.py` | 117 | `/var/run/reboot-required` is Debian-only | Add: `needs-restarting -r 2>/dev/null` for RHEL, `zypper needs-rebooting` for SUSE |
| 8 | `patch.py` | 111-114 | Checks `/var/log/yum.log` but Rocky 9+ uses `/var/log/dnf.log` | Add dnf.log check |
| 9 | `comply.py` | 37, 40 | Hardcoded `/boot/grub/grub.cfg` — RHEL uses `/boot/grub2/grub.cfg` | Check both paths |
| 10 | `harden.py`, `comply.py` | various | `systemctl restart sshd` — Ubuntu calls it `ssh` not `sshd` | `systemctl restart sshd 2>/dev/null \|\| systemctl restart ssh 2>/dev/null` |
| 11 | `baseline.py` | 28-29 | Package list uses `dpkg --list` with `rpm -qa` fallback but misses pacman/apk/pkg | Add `pacman -Q`, `apk info`, `pkg info` fallbacks |

### P2 — Architecture Issues (Affects Multiple Distros)

| # | File | Lines | Problem | Scope | Fix |
|---|---|---|---|---|---|
| 12 | **everywhere** | ~40 locations | `systemctl` assumed on ALL managed hosts | Breaks Alpine (OpenRC), Devuan (sysvinit), Void (runit), FreeBSD (rc.d), Gentoo (OpenRC), containers without systemd | Abstract a `ServiceManager` — detect init system with `os.path.isdir('/run/systemd/system')`, fall back to `rc-service`, `sv`, `/etc/init.d/` |
| 13 | `logs.py`, `audit.py`, `fleet.py`, `serve.py` | ~15 locations | `journalctl` is the sole log source | Breaks everything without systemd journal | Fall back to `tail /var/log/syslog` or `tail /var/log/messages` |
| 14 | `vm.py` | 299, 420-422 | Guest network config assumes `/etc/network/interfaces` (ifupdown) | Breaks Ubuntu (netplan), RHEL (NetworkManager), Arch (systemd-networkd) | Detect networking backend in guest or use cloud-init exclusively |
| 15 | `deploy_agent.py` | 35 | `ExecStart=/usr/bin/python3` hardcoded in systemd unit | Breaks FreeBSD (`/usr/local/bin/python3`), NixOS, custom installs | Use `/usr/bin/env python3` or detect at deploy time |
| 16 | `init_cmd.py` | 849, 3972 | `subprocess.Popen(["/usr/sbin/chpasswd"])` — hardcoded path | Breaks if chpasswd is elsewhere | Use `shutil.which("chpasswd")` or let PATH resolve |
| 17 | `init_cmd.py` | 838, 3961; `users.py` 383 | `useradd -m -s /bin/bash` — assumes bash exists on target | Breaks Alpine (no bash), minimal installs | Use `/bin/sh` for service accounts; remote deploy already handles Alpine (line 2078-2081) but local doesn't |

### P3 — FreeBSD / Edge Cases

| # | File | Lines | Problem | Fix |
|---|---|---|---|---|
| 18 | `comply.py`, `patch.py` | various | `stat -c '%a'` is GNU-only | FreeBSD uses `stat -f '%Lp'`. Use Python `os.stat()` instead |
| 19 | `harden.py`, `comply.py` | various | `sed -i 's/...'` without backup extension | FreeBSD requires `sed -i '' 's/...'`. Use `sed -i.bak 's/...' && rm -f file.bak` |
| 20 | `agent_collector.py` | entire file | Reads `/proc/stat`, `/proc/meminfo`, `/proc/diskstats`, `/proc/net/dev` | Linux-only. Completely non-functional on FreeBSD. Needs FreeBSD collector using `sysctl` |
| 21 | `preflight.py` | 57 | `if os_name != "Linux": return (False, ...)` — rejects non-Linux | FREQ itself can't start on FreeBSD. Acceptable (FREQ runs on Linux, manages FreeBSD targets) but should be documented clearly |
| 22 | `chaos.py` | 177 | Default interface `eth0` | Modern Linux uses predictable names (ens18, enp0s3). Detect with `ip route show default` |
| 23 | `ntp_sync.py` | 12, 15 | Hardcoded `systemd-timesyncd` and `2.debian.pool.ntp.org` | Detect NTP provider (chrony, ntpd, timesyncd). Use generic `pool.ntp.org` |

### What's Already Good

These patterns are already correct and should be used as the model for fixes:

- **`patch.py` and `fleet.py`** already have `if command -v apt-get; then ... elif command -v yum; then ... elif command -v dnf; then ...` pattern
- **`init_cmd.py` auto-install** (line 437-441) already checks apt-get, dnf, zypper for sshpass
- **Infrastructure IPs** are config-driven (`cfg.truenas_ip`, etc.) — no DC01 IPs in production code
- **pfSense deployer** correctly uses `pw useradd` (FreeBSD), `/bin/sh`, no sudo
- **SSH transport** has platform-aware config for 6 host types with legacy cipher support
- **Username defaults** are configurable via freq.toml
- **Sudo approach** uses per-user `/etc/sudoers.d/` files (more portable than group-based)
- **`comply.py`** already handles `cron`/`crond` service name difference
- **`comply.py`** already handles `dpkg -s auditd`/`rpm -q audit` package name difference

---

## THE COMPATIBILITY MATRIX

### What FREQ Runs ON (The Management Host)

FREQ itself runs on Linux with Python 3.11+. This is where you install and run `freq` commands from.

| Tier | Distros | Python | Status |
|---|---|---|---|
| **Tier 1 — Must Work** | Debian 12/13, Ubuntu 24.04, Proxmox VE 8, Fedora 40+, Arch | 3.11-3.13 | Primary targets |
| **Tier 2 — Should Work** | RHEL 9/Rocky 9/Alma 9 (with python3.11 from appstream), openSUSE Tumbleweed, Manjaro, Alpine 3.20+ | 3.11-3.12 | Test during release |
| **Tier 3 — Best Effort** | Gentoo, Void, NixOS, Slackware, Amazon Linux 2023, Raspberry Pi OS, Mint, Pop!_OS, Kali | 3.11+ (user installs) | Community-reported |
| **Not Supported as Management Host** | FreeBSD, macOS, Windows, immutable distros (Silverblue), container-optimized (Flatcar, Talos) | — | Use Docker image instead |

### What FREQ Manages (Fleet Targets via SSH)

FREQ manages these systems remotely over SSH. It needs to work with whatever's on the other end.

| Tier | Target Types | Init System | Package Manager | Notes |
|---|---|---|---|---|
| **Tier 1** | Debian, Ubuntu, Proxmox VE, TrueNAS SCALE | systemd | apt/dpkg | Primary. Already works. |
| **Tier 2** | RHEL 9, Rocky, Alma, Fedora, Amazon Linux 2023 | systemd | dnf/rpm | Mostly works. Fix P1 issues. |
| **Tier 3** | Arch, Manjaro, openSUSE | systemd | pacman/zypper | Need package manager detection. |
| **Tier 4** | Alpine | OpenRC | apk | Need init system abstraction. No bash. |
| **Tier 5** | Gentoo, Void, NixOS, Slackware | OpenRC/runit/various | emerge/xbps/nix/pkgtool | Need broad init + pkg abstractions. |
| **Appliance** | pfSense/OPNsense (FreeBSD) | rc.d | pkg | Already has dedicated deployer. Expand. |
| **Appliance** | Cisco/Juniper/Aruba switches | N/A | N/A | Already has dedicated deployer. SSH + vendor CLI. |
| **Appliance** | Dell iDRAC | N/A | N/A | Already has dedicated deployer. Redfish + SSH. |
| **Appliance** | TrueNAS (as appliance) | systemd | apt (limited) | Already has dedicated deployer. midclt over SSH. |

### Python Version Reality Check

| Python Version | Where It Ships | Can Run FREQ? | Notes |
|---|---|---|---|
| **3.13** | Fedora 41, Arch (latest) | YES | Latest and greatest |
| **3.12** | Ubuntu 24.04, Alpine 3.21, Arch, Void, openSUSE TW | YES | Sweet spot |
| **3.11** | Debian 12, Proxmox VE 8, Raspberry Pi OS, TrueNAS SCALE, Gentoo | YES | Our minimum. Has `tomllib`. |
| **3.10** | Ubuntu 22.04, Mint 21 | NO — needs `tomllib` backport or Python upgrade | Document: `apt install python3.11` |
| **3.9** | RHEL 9, Rocky 9, Alma 9, Amazon Linux 2023, Slackware 15 | NO — needs Python upgrade | Document: `dnf install python3.11` |
| **3.6** | RHEL 8, openSUSE Leap 15, SLES 15 | ABSOLUTELY NOT | Ancient. Document: upgrade Python or use Docker. |

**Decision: Python 3.11+ is our minimum.** This gives us `tomllib`, modern asyncio, and every stdlib feature we need. Users on RHEL 9 install `python3.11` from appstream. Users on Ubuntu 22.04 install `python3.11` from deadsnakes PPA. Users who can't upgrade Python use the Docker image.

---

## THE ABSTRACTION LAYERS

To make FREQ work everywhere, we build detection into the core. Not per-module. Not scattered. Centralized.

### 1. Platform Detection (`freq/core/platform.py` — NEW)

Runs once at startup. Detects everything about the local system. Results cached in a `Platform` dataclass.

```python
@dataclasses.dataclass
class Platform:
    # OS identity
    os_id: str              # "debian", "ubuntu", "rhel", "arch", "alpine", "freebsd", ...
    os_version: str         # "12", "24.04", "9.5", ...
    os_family: str          # "debian", "rhel", "arch", "alpine", "suse", "gentoo", "freebsd", "void"
    os_pretty: str          # "Debian GNU/Linux 12 (bookworm)"
    
    # Python
    python_version: tuple   # (3, 11, 2)
    python_path: str        # "/usr/bin/python3"
    
    # Init system
    init_system: str        # "systemd", "openrc", "runit", "sysvinit", "rc.d"
    has_systemd: bool
    
    # Package manager
    pkg_manager: str        # "apt", "dnf", "pacman", "zypper", "apk", "xbps", "emerge", "pkg"
    
    # Privilege
    sudo_group: str         # "sudo" or "wheel"
    has_sudo: bool
    has_doas: bool
    
    # Security
    has_selinux: bool
    has_apparmor: bool
    
    # Shell
    default_shell: str      # "/bin/bash", "/bin/sh", "/bin/ash"
    sh_is_bash: bool        # True if /bin/sh -> bash
    has_bash: bool
    
    # Filesystem
    usr_merged: bool        # True if /bin -> /usr/bin
    
    # Key binaries
    has_ip: bool
    has_docker: bool
    has_podman: bool
    has_zfs: bool
    has_smartctl: bool
    
    # Architecture
    arch: str               # "x86_64", "aarch64", "armv7l"
```

### 2. Remote Platform Detection (`freq/core/remote_platform.py` — NEW)

When SSH-ing to a fleet host, detect what's on the other end. Single SSH command, parse the output:

```bash
# One SSH call, all detection:
cat /etc/os-release 2>/dev/null; echo "---FREQ_SEP---";
which systemctl 2>/dev/null && echo "HAS_SYSTEMD" || echo "NO_SYSTEMD";
which rc-service 2>/dev/null && echo "HAS_OPENRC" || echo "NO_OPENRC";
which apt 2>/dev/null && echo "PKG_APT" || true;
which dnf 2>/dev/null && echo "PKG_DNF" || true;
which pacman 2>/dev/null && echo "PKG_PACMAN" || true;
which apk 2>/dev/null && echo "PKG_APK" || true;
which zypper 2>/dev/null && echo "PKG_ZYPPER" || true;
which bash 2>/dev/null && echo "HAS_BASH" || echo "NO_BASH";
uname -s 2>/dev/null
```

Cache results per host in `conf/fleet-platforms.json`. Re-detect on `freq host add` or `freq fleet discover`.

### 3. Package Manager Abstraction (`freq/core/packages.py` — NEW)

Every module that installs or queries packages goes through this:

```python
def install_command(package: str, platform: RemotePlatform) -> str:
    """Return the correct install command for this platform."""
    mapping = {
        "apt": f"apt-get install -y {package}",
        "dnf": f"dnf install -y {package}",
        "yum": f"yum install -y {package}",
        "pacman": f"pacman -S --noconfirm {package}",
        "zypper": f"zypper install -y {package}",
        "apk": f"apk add {package}",
        "xbps": f"xbps-install -y {package}",
        "pkg": f"pkg install -y {package}",
    }
    return mapping.get(platform.pkg_manager, f"echo 'Unknown package manager for {package}'")

def query_installed(platform: RemotePlatform) -> str:
    """Return command to list installed packages."""
    mapping = {
        "apt": "dpkg-query -W -f '${Package}\\t${Version}\\n'",
        "dnf": "rpm -qa --queryformat '%{NAME}\\t%{VERSION}-%{RELEASE}\\n'",
        "pacman": "pacman -Q",
        "zypper": "rpm -qa --queryformat '%{NAME}\\t%{VERSION}-%{RELEASE}\\n'",
        "apk": "apk info -v",
        "xbps": "xbps-query -l",
        "pkg": "pkg info",
    }
    return mapping.get(platform.pkg_manager, "echo 'Unknown'")

def reboot_required(platform: RemotePlatform) -> str:
    """Return command to check if reboot is needed."""
    mapping = {
        "apt": "[ -f /var/run/reboot-required ] && echo YES || echo NO",
        "dnf": "needs-restarting -r >/dev/null 2>&1 && echo NO || echo YES",
        "pacman": "echo NO",  # Arch doesn't track this
        "zypper": "zypper needs-rebooting && echo YES || echo NO",
        "apk": "echo NO",
    }
    return mapping.get(platform.pkg_manager, "echo UNKNOWN")
```

### 4. Service Manager Abstraction (`freq/core/services.py` — NEW)

Every module that manages services goes through this:

```python
def service_action(name: str, action: str, platform: RemotePlatform) -> str:
    """Return command to start/stop/restart/status a service."""
    if platform.init_system == "systemd":
        return f"systemctl {action} {name}"
    elif platform.init_system == "openrc":
        return f"rc-service {name} {action}"
    elif platform.init_system == "runit":
        runit_map = {"start": "up", "stop": "down", "restart": "restart", "status": "status"}
        return f"sv {runit_map.get(action, action)} {name}"
    elif platform.init_system == "sysvinit":
        return f"/etc/init.d/{name} {action}"
    elif platform.init_system == "rc.d":  # FreeBSD
        return f"service {name} {action}"
    return f"echo 'Unknown init system for service {name}'"

def service_enable(name: str, platform: RemotePlatform) -> str:
    """Return command to enable a service on boot."""
    if platform.init_system == "systemd":
        return f"systemctl enable {name}"
    elif platform.init_system == "openrc":
        return f"rc-update add {name} default"
    elif platform.init_system == "runit":
        return f"ln -sf /etc/sv/{name} /var/service/"
    elif platform.init_system == "rc.d":
        return f"sysrc {name}_enable=YES"
    return f"echo 'Unknown init system'"

def list_services(platform: RemotePlatform) -> str:
    """Return command to list running services."""
    if platform.init_system == "systemd":
        return "systemctl list-units --type=service --state=running --no-pager --plain"
    elif platform.init_system == "openrc":
        return "rc-status --servicelist"
    elif platform.init_system == "runit":
        return "sv status /var/service/*"
    elif platform.init_system == "sysvinit":
        return "service --status-all 2>/dev/null"
    elif platform.init_system == "rc.d":
        return "service -e"
    return "echo 'Unknown init system'"

def query_logs(name: str, lines: int, platform: RemotePlatform) -> str:
    """Return command to get recent logs for a service."""
    if platform.init_system == "systemd":
        return f"journalctl -u {name} -n {lines} --no-pager"
    else:
        # Fall back to grep in log files
        return f"grep -i {name} /var/log/syslog /var/log/messages 2>/dev/null | tail -{lines}"
```

### 5. User Management Abstraction (`freq/core/users.py` — NEW or extend init_cmd.py)

```python
def create_user(username: str, shell: str, platform: RemotePlatform) -> str:
    """Return command to create a system user."""
    if platform.os_family == "freebsd":
        return f"pw useradd {username} -m -s {shell} -G wheel"
    else:
        # Detect if bash exists, fall back to sh
        safe_shell = shell if platform.has_bash else "/bin/sh"
        sudo_group = platform.sudo_group
        return f"useradd -r -m -s {safe_shell} {username}"

def install_hint(package: str, platform: Platform) -> str:
    """Return user-facing install instructions for a package."""
    hints = {
        "apt": f"sudo apt install {package}",
        "dnf": f"sudo dnf install {package}",
        "pacman": f"sudo pacman -S {package}",
        "zypper": f"sudo zypper install {package}",
        "apk": f"sudo apk add {package}",
        "xbps": f"sudo xbps-install {package}",
        "emerge": f"sudo emerge {package}",
        "pkg": f"sudo pkg install {package}",
    }
    return hints.get(platform.pkg_manager, f"Install {package} using your package manager")
```

### 6. Network Abstraction (for remote commands)

```python
def get_default_interface(platform: RemotePlatform) -> str:
    if platform.os_family == "freebsd":
        return "route -n get default 2>/dev/null | awk '/interface:/{print $2}'"
    return "ip route show default 2>/dev/null | awk '{print $5; exit}'"

def get_ip_addresses(platform: RemotePlatform) -> str:
    if platform.os_family == "freebsd":
        return "ifconfig -a | grep 'inet ' | awk '{print $2}'"
    return "ip -4 -o addr show | awk '{print $4}' | cut -d/ -f1"

def get_listening_ports(platform: RemotePlatform) -> str:
    if platform.os_family == "freebsd":
        return "sockstat -4 -l | tail -n +2"
    return "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null"
```

---

## THE FILE-BY-FILE REWRITE PLAN

Every file in both repos gets read. Every hardcoded assumption gets fixed. This is the checklist.

### freq/core/ — The Foundation

| File | Lines | What to Fix |
|---|---|---|
| `config.py` | 694 | **P0:** Align `tomllib` import with try/except pattern used elsewhere. Add `MIN_PYTHON` constant. |
| `ssh.py` | 372 | Already platform-aware. Verify `LEGACY_HTYPES` covers new deployers (Juniper, Aruba, Arista). |
| `preflight.py` | ~85 | **P0:** Fix `MIN_PYTHON` to `(3, 11)`. Expand distro detection to cover Arch, Alpine, Gentoo, Void, NixOS families. Add clear error messages for unsupported platforms with Docker suggestion. |
| `types.py` | 288 | Add `Platform` and `RemotePlatform` dataclasses (or new file). |
| `fmt.py` | 348 | Verify Unicode box drawing works on all terminals. Add ASCII fallback (already has `ascii` config flag). |
| `log.py` | 103 | No distro-specific code. Clean. |
| `personality.py` | 164 | Already has tomllib try/except. Clean. |
| `resolve.py` | 127 | No distro-specific code. Clean. |
| **NEW: `platform.py`** | ~150 | Local platform detection (see abstraction layer 1). |
| **NEW: `remote_platform.py`** | ~100 | Remote platform detection via SSH (see abstraction layer 2). |
| **NEW: `packages.py`** | ~80 | Package manager abstraction (see abstraction layer 3). |
| **NEW: `services.py`** | ~120 | Service manager abstraction (see abstraction layer 4). |

### freq/modules/ — Every Command Module

| File | Lines | What to Fix |
|---|---|---|
| `infrastructure.py` | 289 | Audit all SSH commands sent to pfSense/TrueNAS/switch/iDRAC. Verify FreeBSD-correct commands for pfSense. Verify no assumptions about target OS beyond what the deployer handles. |
| `init_cmd.py` | 4164 | **P0:** Fix `apt install sshpass` messages → use `install_hint()`. **P1:** Fix hardcoded `/usr/sbin/chpasswd` → use PATH resolution. **P2:** Fix `useradd -s /bin/bash` for local accounts → detect bash, fall back to `/bin/sh`. Remote deploy (line 2078-2081) already handles Alpine — make local consistent. |
| `fleet.py` | 1500 | **P1:** Fix `apt list --upgradable` in update check → use `packages.py`. Already has multi-pkg-manager support in some functions — make it consistent everywhere. Fix `systemctl` calls → use `services.py`. |
| `comply.py` | 384 | **P0:** Fix ALL `apt install` remediations → use `packages.py`. **P1:** Fix `/boot/grub/grub.cfg` → check both paths. Fix `stat -c` → use Python `os.stat()` or detect GNU vs BSD. Fix `sed -i` → use `sed -i.bak` pattern. Fix `sshd`/`ssh` service name → try both. |
| `audit.py` | 329 | **P0:** Fix `apt list --upgradable` → use `packages.py`. **P2:** Fix `systemctl` calls → use `services.py`. |
| `harden.py` | 142 | **P1:** Fix `systemctl restart sshd` → try both names. Fix `sed -i` → portable pattern. |
| `patch.py` | 432 | **P1:** Fix `/var/run/reboot-required` → add dnf/zypper fallbacks. Fix `/var/log/yum.log` → add `/var/log/dnf.log`. Already has multi-pkg-manager for apply — make check consistent. |
| `logs.py` | 280 | **P2:** Fix sole `journalctl` dependency → fall back to `/var/log/syslog`, `/var/log/messages`. |
| `baseline.py` | 379 | **P1:** Fix package list to add `pacman -Q`, `apk info`, `pkg info`. Fix `ss -tlnp` → add `netstat` fallback. |
| `serve.py` | 7676 | **P2:** Fix `systemctl` calls in dashboard data collection → use `services.py`. Fix `journalctl` in log view → add syslog fallback. Already has some pfSense-aware code (netstat -rn) — expand pattern. |
| `netmon.py` | 347 | **P0:** Fix `apt install lldpd` message. **P2:** `/sys/class/net/` is Linux-only — fine for Linux fleet hosts but document limitation. |
| `vm.py` | 1650 | **P2:** Fix `/etc/network/interfaces` assumption in clone → detect networking backend or use cloud-init. |
| `deploy_agent.py` | 195 | **P2:** Fix `/usr/bin/python3` in systemd unit → use `/usr/bin/env python3`. Add OpenRC/runit service file alternatives when target is non-systemd. |
| `compare.py` | 261 | Fix `ip -4 addr` → add `ifconfig` fallback for FreeBSD targets. |
| `discover.py` | 276 | Remote host detection reads `/etc/os-release` — add `uname -s` fallback for FreeBSD. |
| `alert.py` | 712 | Fix `systemctl is-active docker` → use `services.py`. |
| `stack.py` | 427 | Already targets Docker hosts specifically. Verify `docker`/`podman` detection. |
| `users.py` | 416 | Fix `useradd -s /bin/bash` → detect bash, fall back to `/bin/sh`. |
| `schedule.py` | 432 | Verify crontab spool path handling. Debian: `/var/spool/cron/crontabs/`, RHEL: `/var/spool/cron/`. Use `crontab -l` command instead of reading files directly. |
| `chaos.py` | 437 | Fix default interface `eth0` → detect at runtime. |
| `cost_analysis.py` | 358 | No distro-specific code. Clean (uses PVE API). |
| `ipam.py` | 374 | No distro-specific code. Clean (uses config + ARP). |
| `webhook.py` | 343 | No distro-specific code. Clean. |
| `vault.py` | 339 | No distro-specific code. Clean (pure Python crypto). |
| `secrets.py` | 356 | Verify SSH commands work on non-Debian targets. |
| `demo.py` | 332 | No remote calls. Clean. |
| `why.py` | 89 | No distro-specific code. Clean. |
| `journal.py` | 102 | No distro-specific code. Clean. |
| `selfupdate.py` | 144 | Verify update mechanism works across distros. |
| All other modules | — | Audit for `apt`, `systemctl`, `journalctl`, hardcoded paths. Fix with abstractions. |

### freq/engine/ — Policy Engine

| File | What to Fix |
|---|---|
| `policies/ntp_sync.py` | Fix `systemd-timesyncd` assumption → detect NTP provider (chrony, ntpd, timesyncd). Fix `2.debian.pool.ntp.org` → `pool.ntp.org`. |
| `policies/ssh_hardening.py` | Fix `systemctl restart sshd` → try both service names. |
| `policies/rpcbind.py` | Already handles "not-found." Clean. |
| `runner.py`, `executor.py` | Verify policy pipeline works with non-systemd hosts. Phase commands may need `services.py` integration. |

### freq/jarvis/ — Smart Operations

| File | What to Fix |
|---|---|
| `chaos.py` | Fix `eth0` default. Fix `systemctl restart` → use `services.py`. |
| `notify.py` | No distro-specific code. Clean (uses urllib/smtp). |
| `capacity.py` | Uses PVE API. Clean. |
| `rules.py` | No distro-specific code. Clean. |
| `gitops.py` | No distro-specific code. Clean. |
| `federation.py` | No distro-specific code. Clean. |
| `patrol.py` | May use `systemctl`. Audit and fix. |
| `playbook.py` | May run commands on hosts. Audit and fix. |
| `risk.py` | No distro-specific code. Clean. |
| `cost.py` | No distro-specific code. Clean. |
| `learn.py` | No distro-specific code. Clean. |
| `sweep.py` | Calls other modules. Fix will cascade from module fixes. |

### freq/deployers/ — Device Deployers

| File | What to Fix |
|---|---|
| `switch/cisco.py` | Extend from deploy/remove to full getter interface. No OS-level changes needed (IOS is IOS). |
| `switch/ubiquiti.py` | Implement getter interface. |
| `switch/juniper.py` | **NEW.** Implement getter interface for JunOS. |
| `switch/aruba.py` | **NEW.** Implement getter interface for AOS-CX. |
| `switch/arista.py` | **NEW.** Implement getter interface for EOS. |
| `firewall/pfsense.py` | Already uses FreeBSD-correct commands. Verify. |
| `firewall/opnsense.py` | Verify or implement. Similar to pfSense but OPNsense has a better REST API. |
| `bmc/idrac.py` | SSH + racadm. No OS dependency. Clean. |
| `server/linux.py` | Verify works on non-Debian. May need package manager detection for deploy. |

### agent_collector.py — The Linux-Only Problem

This entire file reads `/proc/` and `/sys/`. It works on Linux and nothing else.

**Fix:** Keep the Linux collector as-is. Add a `FreeBSDCollector` class that uses `sysctl` for CPU/memory, `gstat` for disk, `netstat` for network. Auto-detect at runtime. For non-Linux, non-FreeBSD: return empty metrics with a warning.

### install.sh — The Installer

| Issue | Fix |
|---|---|
| Uses `#!/usr/bin/env bash` and bashisms | Keep bash as installer dependency (acceptable) OR rewrite in POSIX sh |
| Has `apt install` messages | Already has multi-distro detection (check the file). Verify all paths. |
| Assumes `/usr/local/bin` is writable | May fail on immutable distros. Add `~/.local/bin` fallback with PATH hint. |

### Dockerfiles (both repos)

| Issue | Fix |
|---|---|
| Uses `python:3.13.5-slim-bookworm` (Debian base) | Fine — Docker IS the distro. Consider also publishing Alpine-based image for smaller footprint. |
| Uses `apt-get install` | Correct for Debian base. |
| Uses `useradd -s /bin/bash` | Correct for Debian base. |
| Uses `dbus-uuidgen` with Python fallback | Already portable. Clean. |

### conf/ — Configuration

| File | What to Fix |
|---|---|
| `freq.toml.example` | Add comments about distro-specific settings. Add `[platform]` section for manual overrides when auto-detection fails. |
| `hosts.conf.example` | Document host type values and what each means. |

---

## THE TESTING MATRIX

Before public release, FREQ must be tested on every Tier 1 and Tier 2 distro. This matrix defines the test.

### Management Host Testing (FREQ runs here)

For each distro, install FREQ and run:

| Test | What It Proves |
|---|---|
| `freq version` | Python imports work, CLI loads |
| `freq doctor` | Local system detection works |
| `freq help` | All domains register, help renders |
| `freq init --dry-run` (if available) | Config loading, preflight checks |

| Distro | Method | Priority |
|---|---|---|
| Debian 12 | Native install | Tier 1 |
| Ubuntu 24.04 | Native install | Tier 1 |
| Proxmox VE 8 | Native install (it IS Debian 12) | Tier 1 |
| Fedora 41 | VM or container | Tier 1 |
| Arch Linux | VM or container | Tier 1 |
| Rocky 9 (python3.11) | VM or container | Tier 2 |
| Alpine 3.21 | Container | Tier 2 |
| openSUSE Tumbleweed | VM or container | Tier 2 |
| Docker image | `docker run` | Tier 1 |

### Fleet Target Testing (FREQ manages these)

For each target distro, add a VM/container to the fleet and run basic fleet commands:

| Test | What It Proves |
|---|---|
| `freq fleet exec <host> "hostname"` | SSH works, sudo works |
| `freq fleet info <host>` | OS detection, system info collection |
| `freq fleet health` | All health checks work on this OS |
| `freq secure audit <host>` | Audit commands work on this OS |
| `freq observe logs tail <host>` | Log collection works (journalctl or syslog) |
| `freq secure patch status <host>` | Package manager detection works |

| Target Distro | Method | Priority |
|---|---|---|
| Debian 12 | Already in fleet | Tier 1 |
| Ubuntu 24.04 | Test VM | Tier 1 |
| Rocky 9 | Test VM | Tier 2 |
| Alpine 3.21 | Test container/VM | Tier 2 |
| FreeBSD 14 (standalone) | Test VM | Tier 3 |

---

## THE DOCKER IMAGE STRATEGY

The Docker image is the universal escape hatch. If your distro is too weird, too old, or too locked down — run FREQ in Docker.

### What to Ship

| Image | Base | Purpose |
|---|---|---|
| `ghcr.io/lowfreqlabs/pve-freq:latest` | `python:3.13-slim-bookworm` | Primary image (Debian-based, ~150MB) |
| `ghcr.io/lowfreqlabs/pve-freq:alpine` | `python:3.13-alpine` | Minimal image (~50MB) |

### What the Docker Image Needs

- SSH client + keys mounted from host
- Config mounted from host (`-v /etc/freq:/opt/pve-freq/conf`)
- Network access to fleet (host networking or bridge)
- Non-root user (already implemented)

### Docker Compose (pve-freq-docker repo)

```yaml
services:
  freq:
    image: ghcr.io/lowfreqlabs/pve-freq:latest
    volumes:
      - ./conf:/opt/pve-freq/conf
      - ~/.ssh:/home/freq/.ssh:ro
    ports:
      - "8888:8888"  # Dashboard
    environment:
      - FREQ_DIR=/opt/pve-freq
```

---

## THE DOCUMENTATION REQUIREMENTS

### README.md Must Include

1. **Supported platforms** — the tier matrix from this document
2. **Python 3.11+ requirement** — with per-distro install instructions:
   - Debian/Ubuntu: `apt install python3` (3.11+ on Debian 12+/Ubuntu 24.04+)
   - RHEL 9/Rocky 9: `dnf install python3.11`
   - Fedora: `dnf install python3` (already 3.12+)
   - Arch: `pacman -S python` (already 3.12+)
   - Alpine: `apk add python3` (already 3.12+)
   - SUSE TW: `zypper install python3` (already 3.12+)
   - Docker: `docker pull ghcr.io/lowfreqlabs/pve-freq:latest`
3. **Managed target compatibility** — what devices FREQ can manage
4. **Docker as fallback** — "If your distro isn't listed, use the Docker image"

### Per-Distro Gotchas Page (docs/ or wiki)

Document known issues per distro:
- RHEL 9: default python3 is 3.9, need python3.11 from appstream
- Ubuntu 22.04: default python3 is 3.10, need python3.11 from deadsnakes
- Alpine: no bash, no systemd — service management uses OpenRC
- Immutable distros: install to `~/.local/bin/` or use Docker

---

## EXECUTION ORDER

```
STEP 1: Build abstraction layers
  → freq/core/platform.py
  → freq/core/remote_platform.py  
  → freq/core/packages.py
  → freq/core/services.py
  These are the foundation. Nothing else until these work.

STEP 2: Fix P0 ship blockers
  → comply.py remediations
  → audit.py update check
  → User-facing apt messages
  → tomllib import consistency
  → preflight.py MIN_PYTHON alignment

STEP 3: Fix P1 RHEL/Rocky issues
  → reboot-required detection
  → dnf.log detection
  → grub path detection
  → sshd/ssh service name
  → Package list fallbacks

STEP 4: Fix P2 architecture issues
  → systemd → services.py migration (all 40+ locations)
  → journalctl → log fallback migration
  → VM network config detection
  → Agent deploy for non-systemd

STEP 5: Fix P3 FreeBSD/edge cases
  → stat/sed portability
  → Agent collector FreeBSD support
  → Default interface detection
  → NTP provider detection

STEP 6: Test on every Tier 1 + Tier 2 distro
  → Management host testing matrix
  → Fleet target testing matrix

STEP 7: Docker image polish
  → Alpine variant
  → Docker Compose template
  → Documentation

STEP 8: Documentation
  → README platform matrix
  → Per-distro install instructions
  → Per-distro gotchas

STEP 9: pve-freq-docker repo sync
  → Mirror all changes
  → Verify Docker build
  → Verify Docker Compose
  → Both repos 1:1
```

---

## THE PRINCIPLE

This file exists because most open source projects are lazy about compatibility. They test on their own machine and ship it. When it breaks on someone else's distro, they close the issue.

We are not most projects. FREQ runs on everything. If Python 3.11 exists on it, FREQ works on it. If it can't run Python 3.11, FREQ manages it over SSH from something that can.

Every distro is a user who chose differently than we did. We respect that choice by making our tool work with theirs. Not the other way around.

Corporate America ships tools that only work in their ecosystem because they're lazy and they want lock-in. We ship a tool that works in everyone's ecosystem because that's what good software does.

That's the whole point.
