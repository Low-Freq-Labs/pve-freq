# Dashboard Surface Triage - 2026-06-22

This records the first UI cleanup pass after operator review found too many
dashboard areas that were empty, stub-backed, redundant, or not trustworthy
enough to keep in normal navigation.

## Kept In Primary Navigation

- Home
- Fleet
- Docker
- Security, currently routed directly to Certs / SSL Manager
- System
- Settings

## Removed Or Hidden From Normal Navigation

- Top-level Media page: folded into Docker as the Media tab.
- Docker Compose tab: hidden until compose management is rebuilt around a clear
  user workflow.
- Fleet Capacity tab: hidden because it requires snapshots/trends and currently
  reads as empty product surface.
- Standalone Fleet Topology tab: folded into Fleet > Network.
- Top-level Lab nav: hidden; lab/device classification now lives in Settings >
  Device Assignment, and lab equipment still appears in Fleet.
- System sub-tabs for Playbooks, Config Sync, Chaos, DNS, DR, Incidents,
  Metrics, Automation, and Plugins: hidden from normal navigation until each
  has a complete UI-backed workflow.
- Security sub-tabs other than Certs: hidden from normal navigation. Security
  now opens SSL Manager first because that is the only pass-worthy surface in
  this group.

## Behavior Changes

- Old deep links for hidden views redirect to the nearest kept surface:
  media -> docker, topology -> network, capacity -> fleet, security/vpn/security
  subviews -> certs, system subviews -> system.
- Settings > Lab Assignment is now Settings > Device Assignment, with Prod,
  Lab, and Template choices.
- Lab-assigned physical devices render as plain node-color lab cards instead of
  privileged core role cards, so a lab TrueNAS no longer looks like prod storage.
- Login/setup nag is suppressed when the only init failure is an acknowledged
  out-of-contract PVE VM list and dashboard credentials exist. The init failure
  remains in setup status and init logs.

## Not Deleted

Backend routes and hidden view code were not deleted in this pass. They remain
available for later rebuilds once each surface has real data, tested actions,
and operator-safe empty states.
