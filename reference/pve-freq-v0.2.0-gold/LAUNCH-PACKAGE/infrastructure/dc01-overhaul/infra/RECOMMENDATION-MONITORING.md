# DC01 Monitoring Recommendation

> Generated: S035-20260220
> Priority: P3
> Status: Recommendation — Awaiting Sonny Review

---

## Current State

- **No monitoring whatsoever.** Zero alerting, zero dashboards.
- PSU failures and fan deaths were discovered manually (probably by walking into the room or checking iDRAC on a whim).
- **Known hardware alerts right now:**
  - R530 (TrueNAS): PSU 1 FAILED, Fan 6 DEAD — running on single PSU with degraded cooling
  - T620 (pve01): PSU 2 FAILED — running on single PSU, hosts ALL production VMs
- No visibility into: NFS mount health, Docker container restarts, ZFS pool status, disk SMART errors, service availability, network connectivity.
- If a container crashes at 2 AM, nobody knows until someone tries to use Plex and it doesn't work.

---

## 1. Monitoring Solution

**Recommendation: Uptime Kuma.**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Uptime Kuma** | Simple web UI, Docker-native, built-in notifications, covers HTTP/TCP/ping/Docker, low resource usage, active community | No metrics graphing, no log aggregation | **Yes — start here** |
| Prometheus + Grafana | Industry standard, powerful dashboards, flexible alerting | Complex setup (exporters, PromQL, multiple containers), steep learning curve | Overkill for now |
| Zabbix | Enterprise-grade, SNMP native, auto-discovery | Heavy (needs database), complex UI, enterprise-oriented | Too heavy |
| Checkmk | Good middle ground, SNMP support | Still complex compared to Uptime Kuma | Maybe later |
| Netdata | Beautiful dashboards, auto-detects everything | Agent on every host, cloud-oriented push model | Privacy concerns |

**Why Uptime Kuma:** Sonny is comfortable with Docker Compose and is learning fast. Uptime Kuma is a single container with a web UI. You add monitors through the UI — no config files, no query languages, no exporters. It covers 80% of what DC01 needs right now. When the environment grows and Sonny wants dashboards with historical metrics, Prometheus + Grafana can be added alongside it (not replacing it — Uptime Kuma stays as the alerting layer).

**For iDRAC hardware monitoring:** Uptime Kuma alone cannot pull SNMP/Redfish data from iDRAC. Two approaches:

- **Simple (recommended first):** iDRAC has built-in email alerting. Configure iDRAC to send email alerts on PSU, fan, temperature, and disk events. This requires SMTP relay setup (see Section 4).
- **Advanced (later):** Add a small script or container that polls iDRAC Redfish API and exposes health status as an HTTP endpoint. Uptime Kuma monitors that endpoint. This is a future enhancement.

---

## 2. Where to Deploy

**Recommendation: On VM 102 (Arr-Stack), alongside the existing services.**

| Option | Pros | Cons |
|--------|------|------|
| New VM (107) | Clean separation | Another VM to maintain, more RAM consumed on pve01 |
| On a Proxmox host directly | Survives VM issues | Clutters the hypervisor, not containerized |
| **On VM 102 (Arr-Stack)** | Already runs 7 Docker services, has Docker + compose, accessible on .255.31 | If VM 102 dies, monitoring dies with it |
| On VM 105 (Tdarr-Server) | Lighter VM | On pve03, further from production VMs |

VM 102 is the natural home. It already runs supporting services (Prowlarr, Overseerr, etc.) and is on the Management VLAN. Uptime Kuma uses minimal resources (~50MB RAM, negligible CPU). Adding it to an existing compose file is a 5-minute job.

**The "monitoring dies if the host dies" problem:** This is real but acceptable at this scale. If VM 102 goes down, you'll know because your arr services stop working too. The iDRAC email alerts (configured separately) cover the hardware layer independently.

### Access

- **Web UI:** `http://10.25.255.31:3001` (Management VLAN, consistent with all other web UIs on .255.X)
- Port 3001 is Uptime Kuma's default

---

## 3. What to Monitor

### Tier 1 — Set Up Immediately

These are the monitors that would have caught the problems you've already experienced.

| Monitor | Type | Target | Interval | Notes |
|---------|------|--------|----------|-------|
| Plex Web UI | HTTP(S) | `http://10.25.5.30:32400/web` | 60s | Responds = Plex is up |
| Prowlarr | HTTP | `http://10.25.5.31:9696` | 120s | |
| Sonarr | HTTP | `http://10.25.5.31:8989` | 120s | |
| Radarr | HTTP | `http://10.25.5.31:7878` | 120s | |
| Bazarr | HTTP | `http://10.25.5.31:6767` | 120s | |
| Overseerr | HTTP | `http://10.25.5.31:5055` | 120s | |
| Huntarr | HTTP | `http://10.25.5.31:9705` | 120s | |
| Agregarr | HTTP | `http://10.25.5.31:7171` | 120s | |
| qBittorrent | HTTP | `http://10.25.66.10:8080` | 120s | Dirty VLAN — VM 102 may need a route |
| Tdarr Server | HTTP | `http://10.25.10.33:8265` | 120s | |
| TrueNAS Web UI | HTTP(S) | `https://10.25.255.25` | 120s | If this goes down, NFS is probably gone too |
| Proxmox pve01 | HTTP(S) | `https://10.25.255.26:8006` | 120s | |
| Proxmox pve03 | HTTP(S) | `https://10.25.255.28:8006` | 120s | |
| pfSense | HTTP(S) | `https://10.25.255.1:4443` | 300s | |

### Tier 2 — Set Up Within First Week

| Monitor | Type | Target | Interval | Notes |
|---------|------|--------|----------|-------|
| Ping pve01 | Ping | `10.25.255.26` | 60s | Catches network/host outage |
| Ping pve03 | Ping | `10.25.255.28` | 60s | |
| Ping TrueNAS | Ping | `10.25.255.25` | 60s | |
| Ping pfSense | Ping | `10.25.255.1` | 60s | |
| Ping VM 101 | Ping | `10.25.255.30` | 60s | |
| Ping VM 102 | Ping | `10.25.255.31` | 60s | |
| Ping VM 103 | Ping | `10.25.255.32` | 60s | |
| Ping VM 104 | Ping | `10.25.255.34` | 60s | |
| Ping VM 105 | Ping | `10.25.255.33` | 60s | |
| NFS mount (VM 101) | Keyword HTTP or Push | See note below | 300s | |
| NFS mount (VM 102) | Keyword HTTP or Push | See note below | 300s | |

**NFS Mount Monitoring Note:** Uptime Kuma can't directly check if an NFS mount is healthy inside another VM. Two practical approaches:

**Option A — Push Monitor (recommended):** Uptime Kuma supports "Push" type monitors. Set up a small cron job on each VM that checks `mountpoint -q /mnt/truenas/nfs-mega-share && curl -s "http://10.25.255.31:3001/api/push/<token>?status=up"`. If the cron stops pushing (NFS stale, VM down, anything), Uptime Kuma alerts after the heartbeat timeout.

Example cron entry (add to each VM):
```
*/5 * * * * mountpoint -q /mnt/truenas/nfs-mega-share && curl -s "http://10.25.255.31:3001/api/push/UNIQUE_TOKEN?status=up&msg=nfs-ok" > /dev/null 2>&1
```

**Option B — TCP Check:** Monitor NFS port on TrueNAS (`10.25.25.25:2049`, TCP). Confirms NFS service is running but doesn't prove clients have healthy mounts.

Use both: TCP check on NFS port for service-level, push monitors for mount-level.

### Tier 3 — Future Enhancements

These require additional tooling beyond Uptime Kuma:

| What | How | When |
|------|-----|------|
| iDRAC hardware health (PSU, fans, temps) | iDRAC built-in email alerts (configure via iDRAC GUI) | After SMTP relay is set up |
| ZFS pool status | Script on TrueNAS that checks `zpool status` and pushes to Uptime Kuma | After Tier 2 is stable |
| Disk SMART errors | TrueNAS has built-in SMART alerts (configure in GUI) | Alongside iDRAC setup |
| Docker container restart counts | Script or Prometheus + cAdvisor | When ready for Prometheus |
| Historical metrics / dashboards | Prometheus + Grafana | Future project |
| Log aggregation | Loki + Grafana | Future project |

---

## 4. Alerting

**Recommendation: Discord webhook (primary) + email (secondary for iDRAC).**

| Method | Setup Difficulty | Reliability | Real-time | Cost |
|--------|-----------------|-------------|-----------|------|
| **Discord webhook** | Easy — create channel, copy URL | High | Instant push notification on phone | Free |
| Email (SMTP) | Medium — need SMTP relay | High | Depends on phone email settings | Free (Gmail app password) |
| Pushover | Easy — install app, get API key | High | Instant push | $5 one-time per platform |
| Telegram bot | Medium — create bot via BotFather | High | Instant push | Free |
| Slack webhook | Easy | High | Instant push | Free tier limited |

### Discord (Primary — For Uptime Kuma)

Why Discord: Sonny likely already has Discord. Setup is 2 minutes. Uptime Kuma has native Discord notification support. You get instant push notifications on your phone.

Setup:
1. Create a Discord server (or use existing one)
2. Create a channel: `#dc01-alerts`
3. Channel Settings > Integrations > Webhooks > New Webhook
4. Copy webhook URL
5. In Uptime Kuma: Settings > Notifications > Add > Discord > paste webhook URL
6. Enable notifications on all monitors

**Alert behavior in Uptime Kuma:**
- Sends alert when a monitor goes DOWN
- Sends recovery alert when it comes back UP
- Configurable retry count before alerting (recommend: 3 retries = avoids false positives from momentary blips)

### Email (Secondary — For iDRAC)

iDRAC's built-in alerting uses SMTP email. Options for SMTP relay:
- **Gmail App Password:** Create a Google account for DC01 alerts, generate an app password, configure iDRAC SMTP to use `smtp.gmail.com:587`
- **Mailgun/SendGrid free tier:** More reliable for automated alerts, 100 emails/day free

Configure iDRAC email alerts for: PSU failure, fan failure, temperature warning/critical, disk predictive failure, memory errors.

---

## 5. Implementation Steps

### Phase A: Deploy Uptime Kuma (15 min)

1. SSH to VM 102 (Arr-Stack)
2. Add Uptime Kuma to the existing compose file at `/opt/dc01/compose/docker-compose.yml`
3. Create config directory: `mkdir -p /opt/dc01/configs/uptime-kuma`
4. Run `docker compose up -d uptime-kuma`
5. Access `http://10.25.255.31:3001`
6. Create admin account (first-time setup wizard)

### Phase B: Configure Discord Notifications (10 min)

1. Create Discord server and `#dc01-alerts` channel
2. Create webhook, copy URL
3. In Uptime Kuma: Settings > Notifications > Setup > Discord
4. Test notification
5. Set as default notification for all new monitors

### Phase C: Add Tier 1 Monitors (20 min)

1. Add all HTTP monitors from the Tier 1 table above
2. For each monitor:
   - Set heartbeat interval (60s for Plex, 120s for others)
   - Set retry count: 3
   - Set accepted status codes: 200-299 (or 200-401 for services with auth)
   - Enable Discord notification
3. Verify all monitors show green
4. Test by stopping a container on VM 102, confirm Discord alert fires, restart container, confirm recovery alert

### Phase D: Add Tier 2 Monitors (30 min)

1. Add ping monitors for all infrastructure
2. Create push monitors for NFS health on each VM
3. Add cron jobs on each VM for NFS push monitoring
4. Add TCP monitor for NFS port (`10.25.25.25:2049`)

### Phase E: iDRAC Email Alerts (30 min — when ready)

1. Set up SMTP relay (Gmail app password or Mailgun)
2. iDRAC GUI on R530 (`https://10.25.255.10`): Configuration > System Settings > Alert Configuration
   - Enable email alerts
   - Configure SMTP server
   - Set alert recipients
   - Enable alerts for: PSU, Fan, Temperature, Disk, Memory
3. Repeat on T620 (`https://10.25.255.11`)
4. Test by sending test alert from iDRAC GUI

**Total estimated time: ~1.5 hours** for Phases A-D. Phase E is separate and can be done anytime.

---

## 6. Docker Compose Addition

Add this service block to `/opt/dc01/compose/docker-compose.yml` on VM 102:

```yaml
  # ============================================================
  # Uptime Kuma — Infrastructure Monitoring
  # DC01 | VM 102 (Arr-Stack) | 10.25.255.31:3001
  # ============================================================
  uptime-kuma:
    image: louislam/uptime-kuma:1.23.16
    container_name: uptime-kuma
    environment:
      - PUID=3003
      - PGID=950
      - TZ=America/Chicago
    volumes:
      - /opt/dc01/configs/uptime-kuma:/app/data
    ports:
      - "3001:3001"
    restart: unless-stopped
```

**Note on image version:** Check https://github.com/louislam/uptime-kuma/releases for the latest stable version before deploying. The version above (1.23.16) should be verified and updated to current. Pin the exact version — no `:latest` tag per DC01 standards.

**Note on PUID/PGID:** Uptime Kuma is not an LSIO image, so it doesn't use PUID/PGID environment variables in the same way. The container runs as `node` user internally. The environment variables are included for documentation consistency but won't change container behavior. File ownership on the volume will be handled by Docker. If permissions become an issue, add `user: "3003:950"` to the service definition instead.

### NFS Push Monitor Cron (add to each VM)

After creating push monitors in Uptime Kuma (one per VM), add this cron job on each VM:

```bash
# /etc/cron.d/dc01-nfs-monitor
# NFS mount health push to Uptime Kuma
*/5 * * * * root mountpoint -q /mnt/truenas/nfs-mega-share && curl -sf "http://10.25.255.31:3001/api/push/REPLACE_WITH_TOKEN?status=up&msg=nfs-healthy" > /dev/null 2>&1 || curl -sf "http://10.25.255.31:3001/api/push/REPLACE_WITH_TOKEN?status=down&msg=nfs-failed" > /dev/null 2>&1
```

Replace `REPLACE_WITH_TOKEN` with the unique push token Uptime Kuma generates for each push monitor.

---

## Monitor Count Summary

| Tier | Count | Type |
|------|-------|------|
| Tier 1 | 14 | HTTP checks on all service web UIs |
| Tier 2 | 9+5 | Ping (infrastructure) + Push (NFS mounts) |
| Tier 3 | TBD | iDRAC email (separate), ZFS scripts, future Prometheus |
| **Total initial** | **~28** | Well within Uptime Kuma's capacity (handles hundreds) |

---

## Future Growth Path

```
NOW                    SOON                   LATER
Uptime Kuma     -->    + iDRAC email    -->    + Prometheus + Grafana
(service checks)       (hardware alerts)       (metrics & dashboards)
Discord alerts         Gmail/Mailgun           + Loki (log aggregation)
                                               + cAdvisor (container metrics)
```

Start simple. Uptime Kuma + Discord gives you "is it up?" visibility and instant phone notifications. That alone would have caught every outage scenario you've faced so far. Build from there as the environment matures.
