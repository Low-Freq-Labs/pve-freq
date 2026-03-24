# DC01 Safety & Permissions

Procedural knowledge for safe operations across DC01. What you can do, what you can't, and how to avoid breaking things.

## Permission Model

jarvis-ai (UID 3004) uses a **default-deny sudoers whitelist**. You can READ anything. Write ops are scoped.

### What Works Everywhere (All Linux Hosts)
- `sudo cat /any/file` — read ANY file on the system. Your most powerful tool.
- `sudo df -h`, `sudo free -h`, `sudo uptime`, `sudo ps aux` — system state.
- `sudo ss -tlnp`, `sudo ip addr show`, `sudo ip route show` — network state.
- `sudo journalctl --no-pager -u <service>` — logs. **Always include `--no-pager`** (sudoers enforces it).
- `sudo systemctl status <service>` — service state (read-only).
- `sudo chronyc sources` — NTP status.

### Docker VMs Only (101-104, 201, 202, 301)
- **READ:** `sudo docker ps`, `sudo docker logs`, `sudo docker inspect`, `sudo docker stats --no-stream`, `sudo docker compose ps`.
- **MANAGE:** `sudo docker restart/stop/start/kill <container>`, `sudo docker exec <container> <cmd>`.
- **COMPOSE:** `sudo docker compose up -d/down/pull` (must be in compose directory).
- **WRITE:** `sudo tee /opt/dc01/*` — ONLY `/opt/dc01/` paths. Cannot write elsewhere.
- **BLOCKED:** `docker rm/create/run/pull/build`. Use `docker compose pull` to update images.

### PVE Nodes Only (pve01-03)
- **READ:** `sudo pvecm status/nodes`, `sudo qm list/config/status`, `sudo pvesh get /...`.
- **ZFS:** `sudo zpool status/list`, `sudo zfs list` — READ-ONLY. No `zpool scrub` or `zfs set`.
- `/etc/pve/` files are root:www-data 640 — need `sudo cat`.

### TrueNAS
- **midclt:** `sudo midclt call alert.list`, `system.info`, `pool.query`, `disk.query`, etc.
- **ZFS:** `sudo zpool status/list`, `sudo zfs list` — `zpool` not in user PATH, must use sudo.
- **Sudoers are in middleware DB** (not a file). To verify: `sudo midclt call user.query '[[\"username\",\"=\",\"jarvis-ai\"]]'` — check `sudo_commands_nopasswd`.
- **No:** journalctl, systemctl, iptables, docker. Services managed via middleware.

### pfSense (FreeBSD — Different!)
- **Shell is tcsh** for user accounts. `2>/dev/null` INSIDE SSH command strings breaks stdout — always redirect OUTSIDE the SSH command.
- `ifconfig` works WITHOUT sudo. Everything else needs sudo.
- **Packet filter:** `sudo pfctl -s rules/nat/states/info/all` — show only, no flush/kill.
- **WireGuard:** `sudo wg show` or `sudo /usr/bin/wg show`. Two `wg` binaries exist — `/usr/bin/wg` is correct, `/usr/local/bin/wg` is broken.
- **NTP:** `sudo /usr/local/sbin/ntpq -p` — full path required.
- **ARP:** `sudo arp -an`. **Ping:** `sudo ping -c N <target>` — `-c` flag mandatory, flood blocked.
- **Config:** `sudo cat /cf/conf/config.xml`. Filter log: `sudo cat /var/log/filter.log | strings | tail -N` (binary clog format).
- **Sudoers wipe on reboot/update.** Verify after pfSense updates.

## Credential Access Patterns

1. **SSH password file:** `~/jarvis_prod/credentials/ssh-credentials` — used with `sshpass -f`.
2. **jarvis-ai password:** `~/jarvis_prod/credentials/jarvis-ai-pass` — used with `su - jarvis-ai -c "cmd" < file`.
3. **Root password:** `~/jarvis_prod/credentials/root-pass` — used with `su - root -c "cmd" < file`.
4. **API keys:** `~/jarvis_prod/credentials/api-keys.env` — load with `eval "$(cat file | grep -v '^#')"`.
5. **SMB credentials:** `~/jarvis_prod/credentials/smb-credentials` — used in mount command.
6. **NEVER read credential files with cat/echo.** Never print contents. Never embed in commands.
7. **stdin conflict:** `su` consumes stdin for the password. For multi-line scripts, write to `/var/tmp/` first, then `su -c "python3 /var/tmp/script.py"`.

## The Never-Do List

- `pfctl -d` — disables the firewall entirely.
- `zpool destroy` — destroys storage pool.
- `docker system prune` without `--filter` — deletes everything.
- `rc.reload_interfaces` on pfSense — bounces ALL interfaces including LACP.
- Modify indexer configs anywhere except Prowlarr.
- Delete series/movies from library with `deleteFiles=true`.
- Change quality profiles or custom formats.
- Change download client configs.
- Touch VMs 800-899.

## Risk Assessment

| Risk Level | Examples | Action |
|---|---|---|
| **Free** | `docker ps`, health APIs, read operations | Execute immediately |
| **Standard** | Container restart, queue management | Execute, verify result |
| **Elevated** | VM migration, config changes | Ask Sonny first |
| **Critical** | Firewall rules, VPN changes, storage mods | Explicit Sonny approval |
| **Forbidden** | `pfctl -d`, `zpool destroy`, VM 800-899 | NEVER. Period. |

## Shell Gotchas

- Bash tool runs non-interactive shells. `.bashrc` NOT sourced.
- `((var++))` with var=0 returns exit code 1 — kills `set -e` scripts. Use `var=$((var + 1))`.
- `ssh` inside `while read` loops eats stdin. Add `-n` to ssh calls.
- `sudo -n true` ALWAYS fails — `true` is not whitelisted. By design.
- Never use `hostname -I` for mgmt IPs — read `memory/topics/ip-allocation.md` instead.

## Infrastructure Paths

- **Docker compose:** `/opt/dc01/compose/` on each Docker VM (world-readable).
- **Docker configs:** `/opt/dc01/configs/<service>/` (local disk, NOT NFS — SQLite breaks).
- **Media NFS:** `/mnt/truenas/nfs-mega-share/media/` on Docker VMs.
- **Sonarr container path:** `/data/` — incomplete downloads at `/data/downloads/incomplete/RELEASE_NAME`.
