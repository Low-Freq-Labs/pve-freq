# Identity Contract

This file is the canonical identity contract for `pve-freq`. If code, docs,
tests, or operator copy disagree with it, they are wrong.

## Core rules

1. The bootstrap identity is operator-provided ingress only. It is the existing
   SSH login used to reach declared hosts before deployment. `freq init` does
   not create, modify, rename, chown, sudoers-write, or manage that account.
2. `cfg.ssh_service_account` names the distinct account that PVE-FREQ creates
   and manages across the fleet. It must be a valid non-root Linux account name
   and must not equal the normalized bootstrap identity for the init run.
3. `freq-admin` is the visible, editable product default for the managed
   service account. Runtime consumers use the validated configured value and
   never silently invent the default when a persisted value is empty or
   invalid.
4. Fresh Web Init runs temporarily as the product-owned internal
   `pve-freq-setup` account. The installer creates it without login access;
   successful handoff removes it and its temporary sudo authority. The
   invoking sudo/bootstrap operator never owns the setup or runtime service.
5. The runtime PVE API identity is
   `cfg.ssh_service_account@pam!freq-rw`. Init creates or updates only that
   selected identity and leaves every unrelated PVE principal untouched.
6. Explicit physical-device credentials remain valid for their selected
   device. Post-bootstrap Linux, PVE, Docker, and TrueNAS service-account paths
   otherwise use the shared validated configured identity.
6. Site-specific automatic host exclusions are explicit configuration in
   `[fleet].operator_exclude_labels`, whose portable default is empty. All
   exclusion consumers share the same normalized policy owner.

## Init lifecycle

### Before `freq init`

Before deployment, bootstrap credentials may be supplied for any existing root
or sudo-capable operator account. The setup UI and CLI describe this account as
temporary ingress, not as the fleet service identity.

### During `freq init`

During init, the service-account name is checked against the actual bootstrap
identity before account, password, sudoers, ownership, key, token, or fleet
mutation. Interactive, headless, and Web/API admission apply the same rule. Web
equality rejection is HTTP 422 on `service_account.username`; no init job or
secret materialization starts.

### After `freq init`

After init, fleet SSH, terminal, doctor, storage, syslog, deployment
verification, and PVE token behavior use the validated configured service
identity unless an explicit device credential selects another supported
identity. The bootstrap account remains exactly as the operator maintained it.

## Container-run credential transport

Container-run CLI/headless init may load host-authored device-credentials TOML.
Stage referenced files through the `FREQ_INIT_INPUTS_DIR` Compose bind and write
only `/freq-init-inputs/<relative-path>` in container-consumed TOML. Browser
setup rejects all path-valued inputs and does not use this transport.

This is a breaking correction for operators whose host-authored TOML referred
to files through the former optional operator-home SSH mounts. Account-home
paths are no longer inferred or translated. An unresolved file-valued entry now
fails before identity, configuration, or deployment mutation. Direct native
headless execution may still use an exact existing runner-visible path.

The default host-layout alias retained in code is internal legacy
compatibility, not a portable input format and not a path operators should copy
into TOML.

## Historical migration

Older DC01 installs used `freq-ops` as their bootstrap account and may also
have a `freq-ops@pam` PVE principal. Those are historical site identities, not
PVE-FREQ defaults or reserved product names. Current init leaves them untouched.
After verifying the configured managed identity and its `freq-rw` token,
operators may remove unrelated legacy principals under their own site change
control.

## Forbidden drift

- treating a bootstrap login as the managed fleet service account;
- hardcoding an organizational account, host label, home path, or PVE
  principal in shipped runtime behavior;
- allowing root or bootstrap/service equality as a managed identity;
- substituting a default for an explicitly empty or invalid runtime identity;
- using bootstrap device credentials for post-init service-account behavior;
- duplicating site-exclusion policy outside the shared config-owned helper;
- teaching host-side staging paths inside container-consumed TOML; or
- deleting or modifying unrelated legacy accounts as an automatic migration.
