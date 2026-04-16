# TUI UX Matrix

Purpose:
- validate the TUI as a real operator surface with its own navigation, actions, and degraded-state behavior

## Core Expectations

For each reachable TUI panel/menu path, test:
- render
- empty state
- error state
- degraded/partial state
- back navigation
- repeated entry / exit without stale state

## Required TUI Areas

At minimum cover:
- main menu
- fleet panels
- VM panels
- docker/media panels
- monitoring/observe panels
- security panels
- infra/storage/network panels
- lab/sandbox panels
- settings / admin panels

## Interaction Scenarios

1. deep navigation
- enter nested menu paths
- back out completely
- verify no dead-end or stale selection state

2. rapid switching
- change sections quickly
- verify no stale content or action bleed-through

3. degraded-host behavior
- verify unreachable/auth-failed hosts surface as degraded, not fake-clean

4. action invocation
- for actions the TUI exposes, verify:
  - correct dispatch
  - honest error on failure
  - visible result on success

5. command parity
- for shared features, compare TUI output to CLI/API/Web truth

## High-Priority TUI Parity Targets

- fleet status / health
- VM inventory
- docker/media status
- alerts / metrics / trends
- security / access / vault views
- network / firewall / certs / dns views
- lab / sandbox status

## Exit Criteria

TUI UX is complete only when:
- every reachable menu path has been exercised
- no dead items remain unexplained
- degraded/error states are honest
- shared-data surfaces match CLI/API/Web truth
