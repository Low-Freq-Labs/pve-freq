# Web E2E Testing

`pve-freq` stays zero-dependency on the shipped client side: no frontend
framework, no bundled client package manager, and no runtime browser dependency.

The single exception is a development-only browser test dependency:
`@playwright/test`.

## Install

```bash
npm install
npm run test:e2e:install
```

The browser payload is installed into the ignored repo-local `.playwright/`
directory so the harness does not depend on a host-global browser cache.

## Safe Live Run

These tests use only read-only dashboard actions plus terminal open/close. They
must not power-cycle, reboot, delete, resize, rename, or reconfigure production
resources.

```bash
PVE_FREQ_BASE_URL=https://10.25.255.50:8888 \
PVE_FREQ_USER=<admin-user> \
PVE_FREQ_PASS=<password> \
npm run test:e2e:live
```

## Guardrail

Destructive lifecycle tests must require an explicit opt-in flag and generated
test resources only. Do not add destructive browser tests that can touch core
devices or production VMIDs by accident.
