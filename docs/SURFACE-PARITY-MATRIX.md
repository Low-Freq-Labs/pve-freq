# Surface Parity Matrix

Purpose:
- prove CLI, API, Web UI, and TUI tell the same story about the same underlying system state

## Core Invariants

For each item below, compare:
- CLI
- API
- Web UI
- TUI

If a surface does not exist, mark it explicitly rather than assuming parity.

### Fleet
- host count
- per-host health state
- reachable vs unreachable counts
- setup/init truth
- freshness/staleness indicators

### VMs
- VM count
- names / IDs
- power state
- node placement
- tags / pool / NIC summary where displayed

### Docker / Media
- container count
- per-container status
- logs parity
- missing/not running behavior

### Setup / Init / Doctor
- `init --check` state
- `/api/setup/status`
- dashboard setup banner
- TUI setup/admin indicators if present
- `doctor` check count / fail-warn-pass split

### Storage / Network / Security
- TrueNAS/store status
- switch/network summaries
- cert counts / expiry state
- DNS counts / errors
- firewall summary state

## API-Only / Surface Gap Inventory

Explicitly note surfaces with no parity peer:
- LXC/CT API lifecycle with no CLI/TUI equivalent
- any dashboard-only feature
- any CLI-only feature

These are not parity failures by default, but they must be documented as:
- intentional gap
- candidate product gap

## Event Visibility

For state-changing actions in sandbox scope, verify:
- backend state changes
- CLI sees the change
- API sees the change
- Web reflects the change
- TUI reflects the change if applicable
- SSE/event bus emits the change where applicable

## Exit Criteria

Parity is complete only when:
- every core invariant above has been checked across all available surfaces
- Docker/media log parity is explicitly checked
- all one-surface-only features are documented as intentional or gap
