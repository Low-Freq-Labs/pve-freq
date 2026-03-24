# Pre-Change Baseline: F-024 TrueNAS Timezone Mismatch
- **Session:** S034
- **Date:** 2026-02-20
- **System:** TrueNAS (10.25.255.25)
- **Finding:** F-024

## Current State
- **midclt timezone:** America/Los_Angeles
- **timedatectl:** America/Los_Angeles (PST, -0800)
- **date output:** Fri Feb 20 17:32:07 PST 2026
- **NTP:** active, system clock synchronized

## Planned Change
- Set timezone to America/Chicago via `midclt call system.general.update '{"timezone": "America/Chicago"}'`

## Rollback
```bash
sudo midclt call system.general.update '{"timezone": "America/Los_Angeles"}'
```
