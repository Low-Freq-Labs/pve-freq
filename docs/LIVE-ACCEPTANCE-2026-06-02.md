# PVE-FREQ Live Acceptance Ledger — 2026-06-02

Purpose: current truth for the VM100/DC01 install. Historical matrix docs remain useful, but this ledger records what was actually proven during the latest live run and what is still blocked or broken.

## Proven Green

- Dashboard auth: `sonny-aif` can log in through `/api/auth/login`.
- Doctor API: `/api/doctor` runs under the service account context and returns `20 passed / 0 failed / 1 warning`.
- PVE API token: `dc01-admin@pam!freq-rw` verifies on all three PVE nodes.
- Fleet SSH from service account: `dc01-admin` doctor path passes fleet connectivity and service-account checks.
- Terminal API contract: GET `/api/terminal/open` is rejected; POST open, resize, and close all work live for VM `103`.
- VM lifecycle safe test: template clone, resize, rename, NIC changes, snapshot, power, ID change, and destroy were verified against test VMIDs `7000/7001`; Jarvis independently confirmed no residue.
- Physical infra quick probe: pfSense, switch, and BMCs return reachable with SSH-backed probe data.
- Infra overview truth: TrueNAS is shown as `degraded` when API keys are missing but ping is reachable; switch and BMCs no longer leak shell error text as hostnames.
- Health state truth: `/api/health` reports all 17 service-account reachable hosts live; stale/degraded/auth-failed legacy device probes are no longer flattened to `status: unreachable`.
- Frontend POST contracts: known dashboard calls for terminal mutations, alert rule writes, backup snapshot, host admin update, playbook create/step, trend snapshot, VM resize, and Docker container action use POST.
- Frontend read contracts: known dashboard read views for switch data and stack info remain GET/read-only.

## Blocked Or Not Green

- TrueNAS API: blocked on missing API key material. Live vault has no `truenas:api_key` or `truenas-lab:api_key`; Jarvis confirmed the existing TrueNAS key secret is not recoverable from his credential store. Fix requires Sonny to provide the captured key or approve rotation.
- TrueNAS action buttons: blocked until the API key is wired. They correctly surface the missing key instead of pretending storage actions are available.
- CLI doctor from deploy-only `freq-ops`: reports fleet SSH failure because `freq-ops` does not own the service-account private key. The service-account/dashboard path is green. This needs clearer operator messaging so the wrong execution identity does not look like infra failure.
- Product-wide dashboard action coverage: improved, but not fully proven. There are 103 POST-enforced backend routes; only the actively used frontend POST mismatches found in this pass were fixed.
- Full API button audit: not complete. Every read/write button still needs an operator-safe live fixture classification.
- TrueNAS pool/usage fields: blocked by the same API-key issue; do not rate this surface green until pools/datasets/shares return live API data.
- VM100 test runner: live install does not include pytest, so test execution remains a development-workstation verification step unless the package intentionally ships test tooling.

## Current Fixes In This Patch

- `freq/data/web/js/app.js`
  - Terminal open/resize/close now call POST.
  - Alert rule create/update/delete now call POST.
  - Backup snapshot now calls POST.
  - Host admin update now calls POST.
  - Trend snapshot now calls POST.
  - Playbook create and playbook step now call POST.
  - VM resize now calls POST.
  - Docker container action now calls POST.
  - Switch and stack read views remain GET/read-only.
- `freq/modules/serve.py`
  - Docker container action now rejects GET and requires POST server-side.
- `freq/core/doctor.py`
  - Imports the logger module it already referenced, so `freq doctor --json` no longer crashes on logger calls.
- `freq/api/fleet.py`
  - `/api/infra/overview` excludes TrueNAS, switch, and iDRAC from Linux shell inventory probes and uses infra quick-probe truth instead.
- `freq/core/health_state.py`
  - `status` preserves stale/degraded/auth_failed truth tokens instead of collapsing them into false `unreachable` values.
- Tests
  - Added dashboard POST contract coverage.
  - Added infra-overview physical-device truth coverage.

## Next Acceptance Work

1. Wire TrueNAS API key by explicit operator-approved path, then prove pools, datasets, shares, alerts, and storage health return live data.
2. Add execution-identity messaging to doctor when run from `freq-ops` without service-key access.
3. Generate a machine-readable API/action inventory from route registration, method requirement, frontend usage, role requirement, and safe-test status.
4. Run non-destructive dashboard smoke tests for every GET/read endpoint used by the UI.
5. Run destructive lifecycle tests only against test-created resources and record cleanup evidence.
6. Mark unsupported or intentionally blocked features in the dashboard, not as broken green cards.
