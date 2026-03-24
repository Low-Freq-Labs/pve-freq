# Pre-Change Baseline — S031 — TrueNAS svc-admin GID Fix

## Date: 2026-02-20
## System: TrueNAS (10.25.255.25)

## Current State
- svc-admin: uid=3003, gid=3000(svc-admin), groups=3000(svc-admin),544(builtin_administrators),545(builtin_users),950(truenas_admin)
- Middleware user ID: 75
- Primary group: id=114, gid=3000, name=svc-admin
- Target group: id=43, gid=950, name=truenas_admin

## Changes Planned
1. Change svc-admin primary group from 3000(svc-admin) to 950(truenas_admin) via middleware
2. Chown home directory files from gid 3000 to 950

## Rollback
1. `sudo midclt call user.update 75 '{"group": 114}'` (revert to group id 114 = gid 3000)
