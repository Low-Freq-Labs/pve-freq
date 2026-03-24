# Pre-Change Baseline — S031 — pfSense svc-admin UID/GID Fix

## Date: 2026-02-20
## System: pfSense (10.25.255.1)

## Current State
- svc-admin: uid=2002, gid=0(wheel), groups=0(wheel),1999(admins)
- config.xml: `<uid>2002</uid>`, `<nextuid>2003</nextuid>`
- No group with GID 950 exists on this system

## Changes Planned
1. Backup config.xml to /cf/conf/config.xml.backup-session31
2. Create group truenas_admin with GID 950
3. Change svc-admin UID 2002 → 3003
4. Change svc-admin primary GID 0 → 950
5. Keep svc-admin in admins group (1999)
6. Update config.xml: uid 2002 → 3003, nextuid 2003 → 3004
7. Chown any files from old UID 2002 → 3003

## Rollback
1. Restore config.xml: `cp /cf/conf/config.xml.backup-session31 /cf/conf/config.xml`
2. Revert BSD user: `pw usermod svc-admin -u 2002 -g 0`
3. Remove group: `pw groupdel truenas_admin`
