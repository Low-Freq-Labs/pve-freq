# API Reference — PVE FREQ

336 REST API endpoints served by `freq serve` at `http://localhost:8888`.

All endpoints return JSON. Most require session authentication via `Authorization: Bearer <token>` header or `freq_session` HttpOnly cookie (both set automatically on login).

---

## Authentication & Sessions

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Authenticate and receive session token |
| POST | `/api/auth/logout` | Invalidate session token + clear cookie |
| POST | `/api/auth/change-password` | Change password for authenticated user |
| GET | `/api/auth/verify` | Verify a session token is still valid |

## User & Access Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/users` | List all users |
| POST | `/api/users/create` | Create a new user |
| POST | `/api/users/promote` | Promote user role |
| POST | `/api/users/demote` | Demote user role |
| GET | `/api/keys` | SSH key management |
| GET | `/api/vault` | Retrieve vault secrets |
| POST | `/api/vault/set` | Set vault secret |
| POST | `/api/vault/delete` | Delete vault secret |

## Fleet Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/fleet/overview` | Master fleet status (hosts, VMs, health) |
| GET | `/api/fleet/ntp` | Fleet NTP status |
| GET | `/api/fleet/updates` | Fleet OS update status |
| GET | `/api/status` | Fleet health (cached) |
| GET | `/api/health` | Comprehensive fleet health |
| GET | `/api/agents` | Agent registry |
| GET | `/api/pool` | List PVE pools |
| GET | `/api/discover` | Discover hosts on network |
| POST | `/api/exec` | Execute command across fleet |

## VM Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/vms` | VM inventory from PVE cluster |
| POST | `/api/vm/create` | Create a new VM |
| POST | `/api/vm/destroy` | Destroy a VM |
| POST | `/api/vm/clone` | Clone a VM |
| POST | `/api/vm/snapshot` | Create snapshot |
| GET | `/api/vm/snapshots` | List snapshots |
| POST | `/api/vm/delete-snapshot` | Delete snapshot |
| POST | `/api/vm/power` | Control power state (start/stop/reboot/shutdown) |
| POST | `/api/vm/resize` | Resize VM resources |
| POST | `/api/vm/rename` | Rename VM |
| POST | `/api/vm/migrate` | Migrate VM to another node |
| POST | `/api/vm/template` | Convert VM to template |
| POST | `/api/vm/tag` | Set PVE tags |
| POST | `/api/vm/add-nic` | Add network interface |
| POST | `/api/vm/clear-nics` | Clear all NICs |
| POST | `/api/vm/change-ip` | Change VM IP |
| POST | `/api/vm/add-disk` | Add disk to VM |
| POST | `/api/vm/change-id` | Change VMID |
| GET | `/api/vm/check-ip` | Check IP availability |
| POST | `/api/vm/push-key` | Push SSH key to VM |

## Storage & Backup

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/backup` | Backup management operations |
| GET | `/api/backup/list` | List snapshots/backups |
| POST | `/api/backup/create` | Create backup |
| POST | `/api/backup/restore` | Restore from backup |
| GET | `/api/zfs` | ZFS pool status |

## Infrastructure

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/infra/overview` | Full infrastructure overview |
| GET | `/api/infra/quick` | Quick infra device summary |
| GET | `/api/infra/pfsense` | pfSense data (rules, interfaces, VPNs) |
| GET | `/api/infra/truenas` | TrueNAS data (pools, shares, replication) |
| GET | `/api/infra/idrac` | iDRAC data (sensors, power, firmware) |
| GET | `/api/host/detail` | Deep host detail |
| GET | `/api/watchdog/health` | Watchdog health proxy |
| POST | `/api/deploy-agent` | Deploy agent to hosts |
| GET | `/api/specialists` | Specialist/agent listing |
| POST | `/api/notify/test` | Test notification delivery |
| GET | `/api/topology` | Network topology for visualization |

## Container Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/containers/registry` | List registered containers |
| POST | `/api/containers/rescan` | Discover running containers |
| POST | `/api/containers/add` | Add container to registry |
| POST | `/api/containers/delete` | Remove container from registry |
| POST | `/api/containers/edit` | Edit container config |
| POST | `/api/containers/compose-up` | Start Docker Compose stack |
| POST | `/api/containers/compose-down` | Stop Docker Compose stack |
| GET | `/api/containers/compose-view` | View docker-compose.yml |

## Media Stack

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/media/status` | All container status across VMs |
| GET | `/api/media/health` | API health for media services |
| GET | `/api/media/downloads` | Active downloads (qBit/SABnzbd) |
| GET | `/api/media/streams` | Active Plex streams |
| GET | `/api/media/dashboard` | Aggregate media dashboard |
| POST | `/api/media/restart` | Restart a media container |
| GET | `/api/media/logs` | Container logs |
| POST | `/api/media/update` | Update container image |

## Policy & Compliance

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/policy/check` | Run compliance check (dry run) |
| POST | `/api/policy/fix` | Apply remediation |
| GET | `/api/policy/diff` | Show policy drift |
| GET | `/api/policies` | List available policies |
| GET | `/api/harden` | Hardening status |
| GET | `/api/sweep` | Full audit + policy sweep |
| GET | `/api/patrol/status` | Continuous monitoring status |

## Monitoring & Metrics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/metrics` | Collect metrics |
| GET | `/api/metrics/prometheus` | Prometheus-format metrics |
| GET | `/api/risk` | Risk analysis data |
| GET | `/api/capacity` | Capacity projections |
| POST | `/api/capacity/snapshot` | Force capacity snapshot |
| GET | `/api/federation/status` | Federation status |
| GET | `/api/lab/status` | Lab fleet status |

## Configuration & Rules

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/config` | Current configuration |
| GET | `/api/distros` | Available cloud images |
| GET | `/api/groups` | Host groups |
| GET | `/api/rules` | Alert rules list |
| POST | `/api/rules/create` | Create alert rule |
| POST | `/api/rules/update` | Update alert rule |
| POST | `/api/rules/delete` | Delete alert rule |
| GET | `/api/rules/history` | Alert history |
| GET | `/api/switch` | Switch config |
| GET | `/api/cost` | Fleet cost estimates |
| GET | `/api/cost/config` | Cost configuration |
| GET | `/api/journal` | Operation journal/logs |
| GET | `/api/lab-tool/config` | Lab tool config |
| POST | `/api/lab-tool/save-config` | Save lab tool config |

## GitOps & Automation

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/gitops/status` | GitOps sync status |
| POST | `/api/gitops/sync` | Trigger sync (git fetch) |
| POST | `/api/gitops/apply` | Apply pending changes |
| GET | `/api/gitops/diff` | Show diff against remote |
| GET | `/api/gitops/log` | Commit history |
| POST | `/api/gitops/rollback` | Rollback to previous commit |
| POST | `/api/gitops/init` | Initialize gitops repo |

## Federation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/federation/register` | Register remote site |
| POST | `/api/federation/unregister` | Unregister site |
| POST | `/api/federation/poll` | Poll remote sites |
| POST | `/api/federation/toggle` | Enable/disable site |

## Playbooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/playbooks` | List playbooks |
| POST | `/api/playbooks/run` | Run playbook |
| POST | `/api/playbooks/create` | Create playbook |
| POST | `/api/playbooks/step` | Run single playbook step |

## Chaos Engineering

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/chaos/types` | Available experiment types |
| POST | `/api/chaos/run` | Run chaos experiment |
| GET | `/api/chaos/log` | Experiment log |

## Agent Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/agent/create` | Create agent |
| POST | `/api/agent/destroy` | Destroy agent |

## Setup & Administration

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/admin/fleet-boundaries` | Fleet boundary config |
| POST | `/api/admin/fleet-boundaries/update` | Update boundaries |
| POST | `/api/admin/hosts/update` | Update hosts config |
| POST | `/api/setup/create-admin` | Create admin account |
| POST | `/api/setup/generate-key` | Generate SSH key |
| POST | `/api/setup/complete` | Mark setup complete |
| POST | `/api/setup/test-ssh` | Test SSH connectivity |
| POST | `/api/setup/reset` | Reset setup wizard |
| POST | `/api/setup/configure` | Save cluster config |
| GET | `/api/setup/status` | Setup state |

## Diagnostics & Info

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/doctor` | Self-diagnostic |
| GET | `/api/diagnose` | Deep diagnostic for a host |
| GET | `/api/log` | View remote logs |
| GET | `/api/info` | FREQ installation info |
| GET | `/api/learn` | Knowledge base search |
| GET | `/api/docs` | API documentation page |
| GET | `/api/openapi.json` | OpenAPI 3.0 spec |
| GET | `/api/update/check` | Check for updates |

## Server-Sent Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/events` | SSE live updates (Content-Type: text/event-stream) |

Event types: `cache_update`, `health_change`, `vm_state`, `alert`

Connect with `EventSource`:

```javascript
const es = new EventSource('/api/events');
es.addEventListener('cache_update', (e) => {
    const data = JSON.parse(e.data);
    // Update dashboard with fresh data
});
```

## Health Probes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe |

## Web UI Routes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Dashboard SPA (or setup wizard on first run) |
| GET | `/dashboard` | Dashboard (alias) |

## WIPE Station

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/gwipe` | WIPE station status |
