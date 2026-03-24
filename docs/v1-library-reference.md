# FREQ v1.0.0 Library Architecture

> Extracted from CLAUDE.md for on-demand reference. 41 files, 16,635 lines, 300+ functions.

## Entry Point: `freq` (224 lines)

1. Resolves install directory (follows symlinks)
2. Loads `conf/freq.conf`
3. Overrides paths (FREQ_DIR, DATA_DIR, LOG, etc.)
4. Sets global flags (DRY_RUN, JSON_OUTPUT, FREQ_YES)
5. Loads CW-1 foundation libs: core, fmt, ssh, resolve, validate, personality, vault
6. Loads CW-2+ libs: all remaining 34 lib files
7. Detects SSH key and current user/role
8. Dispatches to `main()` — case statement routing 70+ commands

## Core Foundation (CW-1)

| File | Lines | Key Functions |
|---|---|---|
| core.sh | 570 | `die()`, `log()`, `freq_lock/unlock()`, `freq_detect_ssh_key()`, `require_admin/operator/elevated()`, `require_protected()`, `_freq_bump_version()`, `cmd_version()` |
| fmt.sh | 200 | `freq_header/footer/line/divider()`, `_step_start/ok/fail/warn()`, `menu_item()`, `menu_prompt()` |
| ssh.sh | 210 | `freq_ssh()`, `freq_ssh_pass()`, `freq_ssh_bg()`, `_parallel_ssh()`, `sanitize_ssh_cmd()` |
| resolve.sh | 180 | `freq_resolve()`, `freq_resolve_ip/type/label()`, `load_hosts()`, `hosts_in_group()` |
| validate.sh | 60 | `validate_username/ip/label/ssh_pubkey/vmid/hostname()` |
| personality.sh | 160 | `freq_celebrate()`, `_freq_vibe()`, `_freq_motd()`, `freq_tagline()` |
| vault.sh | 320 | `vault_init/set/get/delete/list()`, `vault_import_legacy()`, `vault_get_credential()`, `cmd_vault()` |

## Fleet & Host Management (CW-2/3)

| File | Lines | Key Functions |
|---|---|---|
| fleet.sh | 1650 | `cmd_dashboard/fleet_status/exec/info/diagnose/docker/log/ssh_vm/keys/bootstrap/onboard/migrate_ip/operator()` |
| hosts.sh | 1100 | `select_host()`, `find_host()`, `cmd_hosts()`, `cmd_discover()`, `cmd_groups()` |
| users.sh | 1320 | `cmd_passwd/users/new_user/install_user/promote/demote/roles()` |
| init.sh | 1400 | `cmd_init()` — full interactive deployment |

## Proxmox & VMs (CW-3b/4)

| File | Lines | Key Functions |
|---|---|---|
| pve.sh | 1300 | `cmd_vm_overview/vmconfig/migrate/rescue()`, `_pve_guest_exec()`, `_migrate_preflight()` |
| vm.sh | 1580 | `_vm_create/clone/resize/destroy/snapshot/change_id/nic/stop/start()`, `cmd_vm/create/clone/list()` |

## Infrastructure Modules (CW-5)

| File | Lines | Key Functions |
|---|---|---|
| pfsense.sh | 630 | `cmd_pfsense()` — 12 subcommands |
| truenas.sh | 1000 | `cmd_truenas()` — 13 subcommands |
| switch.sh | 450 | `cmd_switch()` — 12 subcommands |
| idrac.sh | 500 | `cmd_idrac()` — status, sensors, SEL, power, console |
| media.sh | 380 | `cmd_media()` — doctor, status, containers, disk, activity |
| health.sh | 380 | `cmd_health()` — cluster, storage, network, VMs, containers |
| doctor.sh | 470 | `cmd_doctor()` — self-diagnostic |
| audit.sh | 420 | `cmd_audit()` — 7 security checks |
| watch.sh | 310 | `cmd_watch()` — monitoring daemon |

## TUI (CW-6)

| File | Lines | Key Functions |
|---|---|---|
| menu.sh | 890 | `_interactive_menu()`, `_splash_screen()`, 9 submenus |

## Stubs (v1.1 placeholders)

harden.sh, backup.sh, vpn.sh, journal.sh, zfs.sh, pdm.sh, registry.sh, serial.sh, notify.sh, opnsense.sh, mounts.sh, configure.sh, images.sh, templates.sh, provision.sh

## 55+ Commands

**VM Lifecycle:** create, clone, resize, import, list, destroy, snapshot
**Fleet Management:** exec, status, dashboard, info, diagnose, docker, log
**Host Setup:** discover, onboard, bootstrap, provision, configure, mount
**User Management:** passwd, users, new-user, roles, install-user, promote, demote
**Proxmox:** vm-overview, vmconfig, migrate, rescue, serial
**Infrastructure:** pfsense, truenas, zfs, switch, idrac, vpn
**Monitoring & Security:** audit, harden, wazuh, watch, health, journal, backup
**Utilities:** doctor, init, vault, media, registry, pdm, version, help

## Configuration State

**freq.conf:** v1.0.0, FREQ_BUILD=personal, FREQ_SSH_MODE=sudo, svc-admin (UID 3003), brand color #7B2FBE
**vlans.conf:** 7 VLANs defined including VLAN 10 DEV
**hosts.conf:** Empty (no fleet registered)
**users/roles/groups.conf:** Empty
**distros.conf:** 16 cloud images defined

## Known Issues in v1.0.0

1. SSH key missing — `/opt/pve-freq/data/keys/freq_id_rsa`
2. Vault not initialized
3. Log directory not writable — `/opt/pve-freq/data/log` owned by root:truenas_admin
4. Dispatcher group wrong — owned by root:truenas_admin
5. PVE nodes unreachable from VLAN 10
6. VM 999 in PROTECTED range (900-999)
7. FREQ_SSH_MODE=sudo uses svc-admin
8. TrueNAS REST API deprecation in 26.04 — must migrate `_tn_api()` to `midclt call` over SSH
