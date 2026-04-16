# Web UX Matrix

Purpose:
- validate the full web dashboard as an operator surface, not just the API behind it
- catch DOM/state/timer/modal/SSE/navigation bugs that command coverage will miss

## Required Test Modes For Every View

For each view below, test:
- golden path
- empty state
- error state
- loading state
- degraded / partial state
- live refresh / SSE update behavior

## View Inventory

Dashboard views to cover:
- `home`
- `fleet`
- `topology`
- `capacity`
- `network`
- `docker`
- `media`
- `security`
- `sec-hardening`
- `sec-access`
- `sec-vault`
- `sec-compliance`
- `firewall`
- `certs`
- `vpn`
- `tools`
- `playbooks`
- `gitops`
- `chaos`
- `dns`
- `dr`
- `incidents`
- `metrics`
- `automation`
- `plugins`
- `lab`
- `settings`

Setup wizard views to cover:
- create-admin
- cluster-identity
- ssh-key
- completion

## Navigation Interaction Matrix

These are first-class scenarios, not optional smoke:

1. Rapid sequential nav
- `home -> fleet -> docker -> security -> home`
- click each before previous loads finish
- verify only final view remains active

2. Modal orphan prevention
- open confirm modal on one view
- navigate to another view
- verify modal is dismissed and does not overlay the new page

3. Timer leak prevention
- visit 5 views in sequence
- verify only current view timers remain active

4. Docker sub-tab persistence
- switch Docker sub-tabs
- navigate away and back
- verify correct sub-tab state and no stale timer/data writes

5. Terminal orphan
- open terminal
- navigate away
- verify websocket closes

6. Browser back button
- navigate across 3 views
- use browser back
- verify cleanup and correct restore

7. Keyboard nav
- press `1-8` or equivalent rapid shortcuts
- verify only final view active

8. Command palette nav
- open search palette
- jump to a different view
- verify same cleanup behavior as click-nav

9. SSE during nav
- trigger live event while on a non-owning view
- verify no DOM errors and no writes into stale view containers

10. Login/logout cleanup
- verify timers, SSE, and web terminal state are cleared on logout

## Home Widget Matrix

Home widgets must be treated as independent probes.

For each widget, verify:
- successful render
- empty render
- API error render
- stale/live refresh behavior

At minimum:
- Fleet Stats
- Containers
- Activity Feed
- Doctor / health summary
- Tdarr
- NTP
- Certs
- DNS
- Docker
- Storage / TrueNAS
- Firewall / VPN if shown

## Web Action Matrix

Every visible button/modal/action in sandbox scope must be tested for:
- success path
- honest failure path
- disabled state when action is unavailable
- residue cleanup where destructive

Priority actions:
- VM create / clone / destroy / snapshot / power / rename / resize / NIC / disk / migrate / rollback
- Docker/log modal actions
- Host add/remove/bootstrap/onboard
- User create/password/promote/demote/dashboard-passwd
- Event create/deploy/verify/wipe/archive/delete
- Proxy add/remove
- DNS internal add/remove
- Switch profile apply/create/delete
- Port configure/desc/poe/flap

## Docker Logs Matrix

Every Docker log access path must agree:
- dashboard Docker page logs
- dashboard Media page logs
- API `/api/containers/logs`
- API `/api/media/logs`

Check:
- same container, same timeframe
- line counts match
- ordering matches
- non-running container gives honest message
- missing docker gives honest message
- wrong host attribution never happens

## Web-Only UX Features

These are web-specific and must be explicitly tested:
- command palette
- widget drag/drop customization
- view layout customization
- websocket terminal
- dashboard sparklines / heatmaps
- pagination/filter/sort/search behavior

## Exit Criteria

Web UX is complete only when:
- all views above have passed all required test modes
- navigation interaction matrix is green
- sandbox-scoped actions are verified
- Docker log parity is green
- no stale-view DOM writes are observed
