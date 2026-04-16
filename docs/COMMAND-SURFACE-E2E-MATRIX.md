# Command Surface E2E Matrix

This campaign expands beyond destructive testing.

Goal:
- test every `freq` command we can safely exercise
- use destructive lifecycles where the sandbox allows it
- use non-destructive live validation where mutation would exceed the allowed blast radius
- explicitly mark excluded commands so omission is intentional, not accidental

Safety boundary is defined by Jarvis in:
- `J-PVEFREQ-DESTRUCTIVE-BOUNDARY-20260416AM`

Hard sandbox:
- VMID range: `6000-6099`
- VLAN range: `3900-3999`
- VM name prefix: `e2e-`
- allowed nodes: `pve01`, `pve02`, `pve03`
- allowed storage: local ZFS only
- special destructive targets: `5005`, iDRAC slot `8`, Cisco service-account user only

## Buckets

### A. Destructive In Scope
These should get full lifecycle validation: create, verify, mutate if supported, destroy, verify cleanup.

#### VM
- `vm create`
- `vm clone`
- `vm destroy`
- `vm resize`
- `vm snapshot`
- `vm power`
- `vm nic`
- `vm import`
- `vm migrate`
- `vm template`
- `vm rename`
- `vm disk`
- `vm tag`
- `vm pool`
- `vm sandbox`
- `vm rollback`
- `vm provision`
- `vm file`

Dependencies:
- `vm rollback` only after `vm snapshot create`
- `vm migrate` must verify landing and cleanup within sandbox storage
- `vm provision` cleanup is destroy of the provisioned sandbox VM
- `vm import` requires an explicit safe import source; if none exists, classify blocked instead of silently skipping

#### Host / Fleet bootstrap on test targets
- `init`
- `configure`
- `fleet deploy-agent`
- `host bootstrap`
- `host onboard`
- `host add`
- `host remove`
- `host sync`
- `user dashboard-passwd`
- `agent` create/destroy
- `specialist` create
- `lab` deploy/resize/rebuild
- `dr backup create`

Cleanup verification:
- `host remove` / `user install` must verify user, sudoers, keys, agent, and residue are actually gone
- `agent`, `specialist`, and `lab` must stay inside VMID `6000-6099` with `e2e-` naming

#### Network / event lifecycle inside boundary
- `event create`
- `event deploy`
- `event verify`
- `event wipe`
- `event archive`
- `event delete`
- `net switch profile apply`
- `net switch profile create`
- `net switch profile delete`
- `net port configure`
- `net port desc`
- `net port poe`
- `net port flap`
- `dns internal add`
- `dns internal remove`
- `proxy add`
- `proxy remove`
- `user create`
- `user passwd`
- `user promote`
- `user demote`
- `user install`

Cleanup verification:
- `event create/deploy/.../delete` must verify zero residue in PVE and switch config after wipe/delete

### B. Live Safe / Non-Destructive
These should be tested live on the allowed environment but without destructive mutation.

#### Core
- `version`
- `help`
- `doctor`
- `perf`
- `menu`
- `demo`
- `serve`
- `update`
- `learn`
- `docs`
- `distros`
- `notify`
- `agent` list/status/templates
- `specialist` status/list/roles/health
- `lab` status/media
- `ops oncall whoami/schedule/history`
- `ops risk`
- `ops incident list`
- `ops change list`

#### VM / fleet read surfaces
- `vm list`
- `vm overview`
- `vm config`
- `vm rescue`
- `vm why`
- `fleet status`
- `fleet dashboard`
- `fleet info`
- `fleet detail`
- `fleet boundaries`
- `fleet diagnose`
- `fleet ssh`
- `fleet docker`
- `fleet log`
- `fleet compare`
- `fleet health`
- `fleet report`
- `fleet ntp`
- `fleet inventory`
- `fleet federation`
- `fleet agent-status`
- `fleet test`
- `fleet update --check`
- `fleet comms check/read`
- `host list`
- `host discover`
- `host groups`
- `host keys`

#### Docker / security / observe / state
- `docker containers`
- `docker fleet`
- `docker stack`
- `docker monitor`
- `docker list`
- `docker images`
- `docker update-check`
- `net switch profile list`
- `net switch profile show`
- `secure vault`
- `secure audit`
- `secure patch` status/check-only
- `secure comply`
- `auto patrol` read-only mode
- `auto react list`
- `auto workflow list`
- `secure secrets`
- `secure sweep`
- `secure vuln scan`
- `secure vuln results`
- `secure fim baseline`
- `secure fim check`
- `secure fim status`
- `observe alert`
- `observe logs`
- `observe trend`
- `observe capacity`
- `observe sla`
- `observe watch`
- `observe db`
- `observe metrics collect/show/top`
- `observe monitor list/run`
- `state baseline`
- `state plan`
- `state check`
- `state diff`
- `state policies`
- `state gitops`
- `state export`
- `state drift`
- `state history`

#### Infra read surfaces
- `hw idrac`
- `hw cost`
- `hw cost-analysis`
- `hw smart`
- `hw ups`
- `hw power`
- `hw inventory`
- `store status`
- `store pools`
- `store datasets`
- `store snapshots`
- `store smart`
- `store shares`
- `store alerts`
- `store nas`
- `dr backup` list/status
- `dr backup export`
- `dr policy`
- `dr journal`
- `dr migrate-plan`
- `dr migrate-vmware`
- `dr status`
- `dr verify`
- `dr sla list`
- `dr runbook list/show`
- `net switch show/facts/interfaces/vlans/mac/arp/neighbors/config/environment/exec`
- `net port status/find`
- `net config backup/history/diff/search`
- `net snmp poll/interfaces/errors/cpu`
- `net topology discover/show/export/diff`
- `net find-mac`
- `net find-ip`
- `net troubleshoot`
- `net ip-util`
- `net ip-conflict`
- `net netmon`
- `net map`
- `net ip`
- `fw status`
- `fw rules`
- `fw nat`
- `fw states`
- `fw interfaces`
- `fw gateways`
- `fw dhcp`
- `cert scan/list/check/inspect/fleet-check/acme/issued`
- `dns scan/check/list/internal list/sync/audit`
- `proxy status/hosts/health/list`
- `media` read-only/status surfaces only:
  - `status`
  - `health`
  - `dashboard`
  - `logs`
  - `stats`
  - `streams`
  - `activity`
  - `wanted`
  - `indexers`
  - `downloads`
  - `transcode`
  - `subtitles`
  - `requests`
  - `scan`
  - `search`
  - `missing`
  - `queue`
  - `disk`
  - `tags`
  - `export`
  - `report`
  - `mounts`
  - `gpu`
- `user list`
- `user roles`
- `vpn wg status/peers/audit`
- `vpn ovpn status`
- `event list/show/plan`
- `plugin list/info/search/update/types`
- `config validate`

#### API-only live-safe surfaces
These have no equivalent CLI but are operator-visible and safe to validate read-only.

- `/api/v1/ct/*`
- `/api/v1/opnsense/*`
- `/api/v1/ipmi/*`
- `/api/v1/bench/*`
- `/api/v1/synology/*`
- `/api/v1/terminal/*` read-only/session listing only
- `/api/v1/redfish/*`
- `/api/v1/backup_verify/*`
- read-only legacy compatibility stubs under `/api/v1/*`

Cross-surface parity checks required where applicable:
- CLI ↔ API ↔ dashboard for:
  - `fleet status`
  - `fleet dashboard`
  - `vm list`
  - `docker containers`
  - `host list`
  - `secure audit`
  - `observe metrics`
- SSE event visibility for state-changing actions that should surface live updates

### C. Destructive But Deferred / Boundary-Limited
These mutate real infrastructure but need a narrower per-command cleanup story before execution.

- `state apply`
- `state fix`
- `secure harden`
- `observe alert create/delete/silence`
- `observe monitor add/remove`
- `auto rules`
- `auto schedule`
- `auto playbook`
- `auto webhook`
- `auto react add/disable`
- `auto workflow create`
- `auto job`
- `auto chaos`
- `plugin install`
- `plugin remove`
- `plugin create`
- `secure patch apply/hold`
- `secure secrets rotate/destructive lifecycle`
- `fleet exec`
- `fleet update` apply mode
- `fleet comms` setup/send
- `docker prune`
- `net config restore`
- `ops oncall` alert/ack/escalate/resolve
- `ops incident` create/update
- `ops change` create
- `dr backup prune`
- `dr runbook create`
- `dr sla set`
- `media` mutating/destructive actions:
  - `restart`
  - `stop`
  - `start`
  - `update`
  - `prune`
  - `compose`
  - `cleanup`
  - `backup`
  - `restore`
  - `nuke`

### D. Excluded By Boundary
These are intentionally out for this campaign.

- any action touching VMs outside `6000-6099`
- any action touching production VLANs or host-level bridge/network config
- pfSense firewall / NAT / interface mutation
- TrueNAS dataset / pool / share / zvol mutation
- PVE datacenter/storage/global cluster config mutation
- shared backup target writes outside the proven test path
- templates `9000-9009` except read-only cloning
- anything under `freq/jarvis/*` that is agent/meta tooling rather than product command surface
- `hw gwipe`
- destructive `fleet update` outside explicitly approved sandbox targets

## Execution Order

1. Core read-only smoke:
- `version`, `help`, `doctor`, `init --check`, `fleet status`, dashboard/setup status

2. VM lifecycle slice:
- create -> inspect -> power -> snapshot -> rollback -> clone -> rename/tag/pool/nic/disk/resize -> migrate -> template/provision where applicable -> destroy -> verify cleanup

3. VLAN/tag lifecycle slice:
- attach sandbox VLAN `3900-3999` to `e2e-*` VM NICs -> verify in PVE/freq surfaces -> remove/destroy -> verify cleanup

4. Host/fleet lifecycle slice on test targets:
- bootstrap/onboard/add/remove/sync/deploy-agent on `5005` and sandbox VMs only

5. Device bounded lifecycle slice:
- iDRAC slot `8`
- Cisco service-account user only
- concrete commands:
  - `hw idrac ...`
  - `net switch show/facts/interfaces/vlans/mac/arp/neighbors/config/environment/exec`
  - `net switch profile ...`
  - `net port ...`

6. Safe live command sweep:
- all Bucket B commands, prioritized:
  - core
  - fleet read/parity
  - VM read/parity
  - docker read
  - infra read
  - security/observe/state
  - API-only safe read surfaces

7. Deferred destructive commands:
- only after each one has a cleanup story written down and approved against Jarvis's boundary

## Pass Standard

Each command tested must be classified as:
- `pass`
- `fail honestly`
- `blocked by boundary`
- `deferred pending cleanup story`

Any command that mutates state must also prove:
- create worked
- state became visible in both backend and operator surfaces where applicable
- cleanup worked
- no residue remained outside the sandbox
