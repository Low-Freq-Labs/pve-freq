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

## Web UI file structure (web_ui.py ~4990 lines)
```
Lines 1-9       Python docstring
Lines 10-770    HTML (CSS + page structure + overlay shell)
Lines 770-845   JS: Utilities (badge, stat, ramGB, quotes, taglines)
Lines 846-1580  JS: AUTH — Login, Sessions, Per-user Storage
Lines 1580-1760 JS: HOME — Widget dashboard
Lines 1760-2200 JS: FLEET — Fleet page, host cards, INFRA_ROLES, INFRA_ACTIONS
Lines 2200-3530 JS: VMs, MEDIA, INFRA, SECURITY, SYSTEM pages
Lines 3530-3620 JS: VM ACTIONS — toast/modal (create, destroy, power, snapshot, resize, migrate, rename, NIC)
Lines 3620-3910 JS: INFRA ACTIONS — pfAction, tnAction, swAction, idracAction
Lines 3910-4010 JS: VM ACTIONS continued (resize, migrate, NIC combo, snapshots)
Lines 4010-4270 JS: More VM controls
Lines 4270-4730 JS: HOST OVERLAY — Card Dispatch System (openCard, closeCard, 4 renderers)
Lines 4730-4990 JS: LAB TOOLS — Plugin Framework (FREQ WIPE etc.)
Lines 4990-end  JS: INIT — keyboard handlers, page load
```

## API endpoints (serve.py — 72 endpoints)
```
/                       Main page (web UI)
/api/status             Fleet status summary
/api/health             Fleet health (background cache, instant)
/api/vms                VM list from PVE API
/api/fleet/overview     Fleet overview (VMs + physical + nodes)
/api/fleet/ntp          NTP status across fleet
/api/fleet/updates      OS update status across fleet
/api/host/detail        Deep SSH probe of single host
/api/exec               Run command on fleet host(s)
/api/info               Host info
/api/metrics            Metrics data
/api/vm/create          Create VM
/api/vm/destroy         Destroy VM
/api/vm/snapshot        Take snapshot
/api/vm/snapshots       List snapshots
/api/vm/delete-snapshot Delete snapshot
/api/vm/resize          Resize VM disk
/api/vm/power           Start/stop/reboot VM
/api/vm/template        Convert to template
/api/vm/rename          Rename VM
/api/vm/change-id       Change VMID
/api/vm/check-ip        Check if IP is available
/api/vm/add-nic         Add NIC to VM
/api/vm/clear-nics      Remove all NICs
/api/vm/change-ip       Change VM IP
/api/pool               Storage pool info
/api/vault              List vault entries
/api/vault/set          Set vault entry
/api/vault/delete       Delete vault entry
/api/users              List users
/api/users/create       Create user
/api/users/promote      Promote user tier
/api/users/demote       Demote user tier
/api/keys               SSH keys
/api/journal            Journal entries
/api/config             Configuration
/api/distros            Cloud image list
/api/groups             Host groups
/api/harden             Hardening scan
/api/agents             Agent list
/api/agent/create       Create agent
/api/agent/destroy      Destroy agent
/api/deploy-agent       Deploy agent to VM
/api/specialists        Specialist agent list
/api/switch             Switch operations
/api/notify/test        Test notifications
/api/infra/pfsense      pfSense operations (17 actions)
/api/infra/truenas      TrueNAS operations (12 actions)
/api/infra/idrac        iDRAC operations (7 actions)
/api/infra/overview     Infrastructure overview
/api/infra/quick        Quick infra probe (background cache)
/api/media/status       Container status (all VMs)
/api/media/health       Media stack health
/api/media/downloads    Active downloads (qBit + SABnzbd)
/api/media/streams      Active Plex streams
/api/media/dashboard    Media dashboard data
/api/media/restart      Restart container
/api/media/logs         Container logs
/api/media/update       Pull + restart container
/api/learn              Knowledge base
/api/risk               Risk assessment
/api/policies           Policy engine
/api/lab/status         Lab tool status
/api/lab-tool/proxy     Proxy to lab tool API
/api/lab-tool/config    Lab tool config
/api/lab-tool/save-config  Save lab tool config
/api/auth/login         Login
/api/auth/verify        Verify session
/api/auth/change-password  Change password
```

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

# Check JS brace balance
python3 -c "
import re
with open('freq/modules/web_ui.py') as f: content = f.read()
js = re.search(r'<script>(.*?)</script>', content, re.DOTALL).group(1)
print(f'Braces: {js.count(chr(123))} open, {js.count(chr(125))} close')
"
```
