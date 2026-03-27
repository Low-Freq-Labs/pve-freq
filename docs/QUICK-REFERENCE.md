# FREQ Developer Quick Reference

## How to restart the dashboard server
```bash
kill $(pgrep -f 'python3 -m freq serve' | head -1) 2>/dev/null
sleep 1
python3 -m freq serve --port 8888 &
sleep 2
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/
# Should print: 200
```

## How to test a change
1. Edit `freq/modules/web_ui.py` or `freq/modules/serve.py`
2. Restart server (above)
3. Hard refresh browser (Ctrl+Shift+R)
4. If serve.py syntax is bad: `python3 -c "import freq.modules.serve"` to check

## Key files

| File | Lines | What |
|------|-------|------|
| `freq/modules/web_ui.py` | 7,234 | Single-file SPA (HTML/CSS/JS) |
| `freq/modules/serve.py` | 6,323 | HTTP server, 100+ API endpoints |
| `freq/cli.py` | 1,148 | Argparse dispatcher, 88 commands |
| `freq/tui/menu.py` | 1,315 | Interactive TUI, 168 entries, 15 submenus |
| `freq/modules/init_cmd.py` | ~3,800 | 10-phase deployment wizard |
| `freq/core/config.py` | ~580 | Config loader, bootstrap, FreqConfig dataclass |

## API endpoints (serve.py — 100+ endpoints)

Core endpoints:
```
/                           Main page (web UI)
/healthz                    Health check (for Docker/orchestrators)
/api/status                 Fleet status summary
/api/health                 Fleet health (background cache, instant)
/api/vms                    VM list from PVE API
/api/fleet/overview         Fleet overview (VMs + physical + nodes)
/api/fleet/ntp              NTP status across fleet
/api/fleet/updates          OS update status across fleet
/api/host/detail            Deep SSH probe of single host
/api/exec                   Run command on fleet host(s)
/api/info                   Host info
/api/metrics                Metrics data
```

VM management:
```
/api/vm/create              Create VM
/api/vm/destroy             Destroy VM
/api/vm/clone               Clone VM (dedicated endpoint)
/api/vm/migrate             Migrate VM (with live migration option)
/api/vm/snapshot            Take snapshot
/api/vm/snapshots           List snapshots
/api/vm/delete-snapshot     Delete snapshot
/api/vm/resize              Resize VM disk
/api/vm/power               Start/stop/reboot VM
/api/vm/template            Convert to template
/api/vm/rename              Rename VM
/api/vm/change-id           Change VMID
/api/vm/check-ip            Check if IP is available
/api/vm/add-nic             Add NIC to VM
/api/vm/clear-nics          Remove all NICs
/api/vm/change-ip           Change VM IP
/api/vm/add-disk            Add disk to VM
/api/vm/tag                 Set VM tags
```

Docker & Compose:
```
/api/containers/compose-up      Compose up for a Docker VM
/api/containers/compose-down    Compose down for a Docker VM
/api/containers/compose-view    View compose.yml content
```

Backup:
```
/api/backup/list            List snapshots and exports
/api/backup/create          Create backup/snapshot
/api/backup/restore         Restore from backup/snapshot
```

Setup:
```
/api/setup/test-ssh         Test SSH connectivity to a host
/api/setup/reset            Reset setup wizard
```

Infrastructure, media, security, vault, users, and more — see `serve.py` for the full list.

## Host quirks (things that WILL bite you)

**pfSense (FreeBSD):**
- Sudoers get WIPED on pfSense updates. Must re-deploy after every upgrade.
- FreeBSD paths differ: `/bin/cat`, `/sbin/pfctl`, `/bin/ls` (not `/usr/bin/`)
- Shell is `/bin/sh` or `/bin/tcsh`, NOT bash
- `pfctl -sr` output is HUGE — always pipe through grep/head
- sshguard/PerSourcePenalties can lock you out if you SSH as wrong user repeatedly

**TrueNAS:**
- Sudoers stored in middleware DB, NOT filesystem. Changes via `midclt call user.update` only.
- `/etc/sudoers.d/` changes get OVERWRITTEN on reboot
- `midclt call` is the primary API — not REST, not CLI tools
- ZFS commands need sudo: `zpool`, `zfs`
- System logs are verbose JSON blobs — truncate with `cut -c1-200`

**Cisco Switch:**
- Password auth only (no SSH keys on IOS)
- Uses `sshpass -f <password-file>` for authentication
- Legacy crypto required: `KexAlgorithms=+diffie-hellman-group14-sha1`
- One command per session works best
- `show` commands don't need enable mode if user has privilege 15

**iDRAC (7/8):**
- Password auth only (same sshpass as switch)
- Legacy crypto required (same as switch)
- ONE command per SSH session — multi-command strings FAIL
- `racadm` is the CLI: `getversion`, `getsysinfo`, `getsensorinfo`
- Some iDRAC units may be unreachable if on a separate management network.
- ControlMaster must be disabled (`-o ControlMaster=no`)

**PVE Nodes:**
- `pvesh get /cluster/resources --type vm --output-format json` from ANY node returns ALL VMs cluster-wide
- No need to query each node separately
- freq-admin has NOPASSWD:ALL sudo

## Design tokens (the Diamond Standard look)
```css
--purple: #7B2FBE       /* brand color */
--purple-light: #9B4FDE /* accents */
--bg: #0a0d12           /* page background */
--card: #141920         /* card background */
--border: #1e2530       /* subtle borders */
Card border: 2px solid #384450
Border radius: 8px
Font: Inter / system-ui
Mono: Fira Code / Cascadia Code / JetBrains Mono
Min font: 12px (nothing smaller)
Stats: .st cards with .lb label + .vl value
```

## Common operations
```bash
# Check server is up
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/

# Test SSH to a fleet host
ssh -o ConnectTimeout=5 freq-admin@<host-ip> "hostname"

# Test a pfSense command raw
ssh -o ConnectTimeout=5 freq-admin@<pfsense-ip> "sudo pfctl -sr | head -10"

# Test a TrueNAS command raw
ssh -o ConnectTimeout=5 freq-admin@<truenas-ip> "sudo zpool list"

# Validate Python syntax
python3 -c "import freq.modules.serve; import freq.modules.web_ui"

# Run test suite
python3 -m pytest tests/ -v --tb=short
```
