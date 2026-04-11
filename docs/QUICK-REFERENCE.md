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

## How to test a dashboard change
1. Edit `freq/modules/serve.py`, `freq/data/web/js/app.js`, `freq/data/web/css/app.css`, or `freq/data/web/app.html`.
2. Restart the dashboard server.
3. Hard refresh the browser (`Ctrl+Shift+R`).
4. If `serve.py` changed, run `python3 -c "import freq.modules.serve"` to catch syntax errors fast.

## Key files

| File | What |
|------|------|
| `freq/modules/serve.py` | Dashboard server and API routing |
| `freq/data/web/js/app.js` | Main dashboard client logic |
| `freq/data/web/css/app.css` | Dashboard styling |
| `freq/data/web/app.html` | Dashboard shell and view layout |
| `freq/cli.py` | CLI entrypoint and command registration |
| `freq/tui/menu.py` | Interactive terminal UI |
| `freq/modules/init_cmd.py` | `freq init` bootstrap flow |
| `freq/core/config.py` | Config loading and validation |

## Dashboard/API landmarks

Core surfaces:
```
/                           Main dashboard
/healthz                    Health check
/api/status                 Fleet status summary
/api/health                 Fleet health
/api/vms                    VM list
/api/fleet/overview         Fleet overview
/api/fleet/updates          OS update status
/api/host/detail            Deep host probe
/api/exec                   Fleet command execution
/api/metrics                Metrics data
```

VM management:
```
/api/vm/create              Create VM
/api/vm/destroy             Destroy VM
/api/vm/clone               Clone VM
/api/vm/migrate             Migrate VM
/api/vm/snapshot            Create snapshot
/api/vm/snapshots           List snapshots
/api/vm/delete-snapshot     Delete snapshot
/api/vm/resize              Resize VM disk
/api/vm/power               Start/stop/reboot VM
/api/vm/template            Convert to template
/api/vm/rename              Rename VM
```

Use `docs/API-REFERENCE.md` and the route handlers under `freq/api/` for the full surface.

## Host quirks

**pfSense (FreeBSD):**
- Sudoers can be reset on updates. Re-deploy after upgrades.
- Paths differ from Linux (`/bin/cat`, `/sbin/pfctl`, `/bin/ls`).
- Shell is `/bin/sh` or `/bin/tcsh`, not bash.
- `pfctl -sr` output is huge; filter aggressively.

**TrueNAS:**
- User and sudo behavior is middleware-managed.
- Filesystem edits under `/etc/sudoers.d/` do not persist reliably.
- `midclt call` is the source of truth for system-managed changes.

**Cisco Switch:**
- Password auth is common.
- Some devices require legacy SSH crypto.
- One command per session is often safest.

**iDRAC (7/8):**
- Password auth is common.
- Legacy SSH crypto may be required.
- `racadm` is the CLI.
- Some units sit on separate management networks.

**PVE Nodes:**
- `pvesh get /cluster/resources --type vm --output-format json` from any node returns cluster-wide VM state.
- The FREQ service account (default: `freq-admin`, check `freq.toml [ssh].service_account`) should have passwordless sudo where deployment is healthy.

## Common operations
```bash
# Check dashboard is up
curl -s -o /dev/null -w "%{http_code}" http://localhost:8888/

# Show current command map
PYTHONPATH=/data/projects/pve-freq python3 -m freq help

# Test connectivity to a host
freq fleet test <host>

# Run a command across fleet targets
freq fleet exec all "hostname"

# Validate Python syntax for dashboard code
python3 -c "import freq.modules.serve"

# Run a focused test file
PYTHONPATH=/data/projects/pve-freq python3 tests/test_trust_critical.py
```
