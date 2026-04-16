# Identity Contract

This file is the canonical identity contract for `pve-freq`.

If code, docs, tests, or operator copy disagree with this file, they are wrong.

## Core Rules

1. `freq-ops` is the bootstrap/sudo identity.
It is the install-time or break-glass operator account used to run and complete `freq init`. **`freq init` MUST pass through `freq-ops` untouched** — no `useradd`, no `chpasswd`, no sudoers write, no chmod/chown, no SSH key management, no PVE token creation, nothing. `freq-ops` is bootstrap ingress only.

2. `cfg.ssh_service_account` is the deployed fleet service account.
This is the account `freq init` creates, configures, and deploys across managed hosts. The value `freq-ops` is RESERVED and may NOT be used as a managed service-account name — `cfg.ssh_service_account` is rejected at config-load time and at the Phase 3 prompt if it equals any name in the reserved set.

3. `freq-admin` is only the default deployed service-account name.
If the user does not choose another name, `cfg.ssh_service_account` defaults to `freq-admin`.

4. The runtime PVE API identity is `cfg.ssh_service_account@pam!freq-rw`.
By default this resolves to `freq-admin@pam!freq-rw`. The legacy `freq-ops@pam!freq-rw` token is an infrastructure-only construct and must not be presented as the FREQ runtime PVE API identity.

## Init Lifecycle Checkpoints

These checkpoints are release-gate rules and must be verified.

### Before `freq init`

- `freq-ops` may exist as the bootstrap/sudo operator account.
- No code or UI may imply that `freq-ops` is the fleet service account.
- Setup UI must distinguish the first web operator from the later deployed fleet service account.

### During `freq init`

- Bootstrap auth is the credential path used to reach hosts before deployment.
- Phase 3 creates the deployed service account named by `cfg.ssh_service_account`.
- If the user does nothing, that deployed account name is `freq-admin`.
- Every deployment/verification step must use the configured service account, not a hardcoded account name.
- **Phase 3 must reject `cfg.ssh_service_account == "freq-ops"` (or any other RESERVED_SERVICE_ACCOUNT_NAMES value) with an explicit contract error before invoking `useradd`, `chpasswd`, or `_setup_sudoers`.** The rejection happens both at config-load time (config.py overrides to default with a stderr warning) and at the Phase 3 interactive prompt (`_phase_service_account` returns 1 with `fmt.step_fail`).

### After `freq init`

- Fleet SSH and runtime verification use `cfg.ssh_service_account`.
- Dashboard login remains a human/operator identity concern, not a service-account concern.
- PVE API token creation uses `cfg.ssh_service_account@pam!freq-rw` (default `freq-admin@pam!freq-rw`).
- The `freq-ops` account on the install host is unchanged from its pre-init state. Its password, sudoers entry, SSH keys, home directory ownership, and PVE @pam record (if any) are exactly as the operator left them before running `freq init`.

## Forbidden Drift

The following are contract violations:

- treating `freq-ops` as the deployed fleet SSH service account
- treating `freq-admin` as a fixed sacred identity instead of a default
- hardcoding `freq-admin` in runtime deployment paths when `cfg.ssh_service_account` is available
- using `freq-ops` where the deployed service account should be used
- presenting `freq-ops@pam!freq-rw` as the runtime PVE API identity (it is now Jarvis-only infra; runtime is `cfg.ssh_service_account@pam!freq-rw`)
- any `freq init` code path that creates, modifies, chowns, chmods, sudoers-writes, ssh-key-manages, or otherwise touches the local `freq-ops` user, its home directory, or its credentials
- any `freq init` code path that creates the `freq-ops@pam` user on a PVE cluster as part of the runtime contract (legacy migration: pre-existing `freq-ops@pam` users from older installs are left untouched and the operator may delete them manually via `pveum user delete freq-ops@pam` once the new identity is verified)
