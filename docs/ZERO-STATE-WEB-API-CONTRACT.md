# Zero-State Browser Setup API Contract

Contract version: `zero-state-web-v1`

Status: frozen for backend and frontend implementation

## Goal

A new installation can be configured entirely in a browser. The browser never
asks for, sends, or displays a server-side path, TOML, a VMID range, or a
manually written host record.

The flow is:

1. Create the first operator and establish an authenticated admin session.
2. Submit PVE node IPs and bootstrap SSH credentials as normal form values.
3. Discover PVE resources and reachable infrastructure.
4. Select every discovered resource as owned or acknowledged.
5. Store credentials for owned devices directly in the vault.
6. Start init from the frozen discovery and selection contract.
7. Poll live progress until init and browser setup are honestly complete.

The first operator is created before any network probe or secret intake is
sent. The page may collect fields earlier, but discovery and all later calls
require the newly-created admin cookie and CSRF token. This preserves the
existing fail-closed setup security boundary.

## Common rules

- All bodies and responses use JSON and UTF-8.
- Every response sets `Cache-Control: no-store`.
- Mutating authenticated calls require the session cookie and
  `X-Freq-CSRF`.
- `setup_id`, `discovery_id`, `contract_id`, and job IDs are opaque. The
  browser must not parse them.
- A caller may supply `client_request_id`, a UUID generated once per user
  action. Repeating the same action with the same ID returns the existing job
  or result instead of starting another mutation.
- Passwords, API keys, private keys, and sudo passwords are write-only. They
  never appear in a response, progress message, log line, exception, audit
  field, URL, or process argument.
- New setup endpoints reject keys ending in `_file` or `_path`, raw TOML,
  `hosts_file`, `vm_contract`, typed VMID lists/ranges, and arbitrary scan
  subnets with `400 path_input_not_allowed` or
  `400 manual_contract_not_allowed`.
- File-based init flags remain supported by the CLI as a legacy/operator
  interface. They are not part of `zero-state-web-v1`.
- The PVE API token remains product-minted during init from the submitted PVE
  bootstrap identity. The browser does not accept or upload a PVE API token.
- The base browser flow defers optional certificate lifecycle configuration.
  It does not ask for certificate paths or a Cloudflare token path. Those are
  authenticated post-init workflows.

### Error envelope

New endpoints return:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_node_ip",
    "message": "PVE node 2 must be an IPv4 or IPv6 address.",
    "field": "cluster.nodes[1].host",
    "retryable": false
  },
  "request_id": "server-request-id"
}
```

HTTP meanings:

| Status | Meaning |
| --- | --- |
| `400` | Malformed or forbidden input. |
| `401` | No valid setup session. |
| `403` | Wrong role, CSRF failure, or setup window closed. |
| `404` | Opaque setup/job/resource identifier is unknown. |
| `409` | Another job is running, stale discovery/contract, or init already complete. |
| `410` | A setup/discovery job expired after service restart or retention. |
| `422` | Valid JSON, but selections or required credentials are incomplete. |
| `429` | Setup probe rate limit reached. |
| `500` | Internal persistence or state failure. |
| `502` | All declared PVE bootstrap targets failed. |

Validation errors should identify one field. Aggregate selection errors may
also include a bounded `details` list containing only resource IDs and error
codes.

## State machine

`GET /api/setup/status` exposes one `state` value:

| State | Truth |
| --- | --- |
| `needs_operator` | No dashboard users and no completion marker. |
| `collecting` | First admin exists; no successful discovery is frozen. |
| `discovering` | A discovery job is queued or running. |
| `selecting` | Discovery succeeded; no complete resource contract exists. |
| `credentials` | Contract exists; owned devices still require credentials. |
| `ready` | Contract and required secrets are complete; init may start. |
| `initializing` | Browser-launched init is running. |
| `blocked` | Latest discovery/init failed and may be retried in the setup window. |
| `complete` | `.initialized` and `.web-setup-complete` both exist. |

The setup window remains reachable to the authenticated first admin after a
failed discovery or init. It closes only at `complete`, or through the existing
authenticated reset/recovery policy. `/setup` redirects to the dashboard only
at `complete`.

The status response retains the existing truth fields (`initialized`,
`web_setup_complete`, `setup_health`, and `setup_reason`) and adds:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "state": "selecting",
  "setup_id": "opaque-setup-id",
  "initialized": false,
  "web_setup_complete": false,
  "active_discovery_id": "opaque-discovery-id",
  "active_contract_id": null,
  "active_init_job_id": null,
  "next": "build_contract"
}
```

For an unauthenticated `needs_operator` response, opaque IDs are `null`.

## 1. First operator

### `POST /api/setup/create-admin`

This existing endpoint becomes the only unauthenticated setup mutation.

Request:

```json
{
  "schema": "zero-state-web-v1",
  "username": "sonny-aif",
  "password": "write-only-value",
  "client_request_id": "uuid"
}
```

`password_file` is rejected. Success remains HTTP 200 and establishes the
cookie session:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "setup_id": "opaque-setup-id",
  "user": "sonny-aif",
  "role": "admin",
  "session_started": true,
  "csrf_token": "csrf-value",
  "auth_mode": "cookie",
  "state": "collecting"
}
```

The password is hashed into the vault and verified before `users.conf` is
changed. A partial write fails closed. A retry with the same username and
password during the open setup window resumes the same setup session.

## 2. Discovery

### `POST /api/setup/discovery/start`

Requires admin session and CSRF. Starts one bounded discovery job.

Request:

```json
{
  "schema": "zero-state-web-v1",
  "setup_id": "opaque-setup-id",
  "client_request_id": "uuid",
  "cluster": {
    "name": "dc01",
    "nodes": [
      {"host": "10.25.255.26", "name": "pve01"},
      {"host": "10.25.255.27", "name": "pve02"}
    ]
  },
  "bootstrap": {
    "username": "freq-ops",
    "password": "write-only-value"
  }
}
```

Rules:

- `nodes` contains 1-16 unique literal IP addresses. Names are optional and
  may be replaced by discovered PVE node names.
- The bootstrap password is stored in a setup-scoped vault namespace for the
  discovery/init lifecycle. It is never returned.
- Discovery first proves SSH on a declared PVE node, queries
  `/cluster/resources?type=vm`, resolves guest addresses where available, and
  derives bounded management networks from declared nodes and PVE truth.
- It must not accept a caller-provided arbitrary scan subnet or probe outside
  declared/derived scope.
- Device identification may be credential-free. Authentication to a
  discovered device happens only after explicit selection and credential
  submission.

Success is HTTP 202:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "setup_id": "opaque-setup-id",
  "discovery": {
    "id": "opaque-discovery-id",
    "state": "queued",
    "poll_after_ms": 1000
  }
}
```

Only one discovery may run per setup. A new successful discovery invalidates
the previous contract and credential requirements.

### `GET /api/setup/discovery/status?id=<discovery_id>`

Requires the bound admin session. It returns HTTP 200 for all known job
states:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "discovery": {
    "id": "opaque-discovery-id",
    "state": "succeeded",
    "started_at": "2026-07-12T05:00:00Z",
    "updated_at": "2026-07-12T05:00:09Z",
    "finished_at": "2026-07-12T05:00:09Z",
    "poll_after_ms": 0,
    "progress": {
      "phase": "complete",
      "current": 36,
      "total": 36,
      "message": "Discovered 26 virtual machines and 10 templates."
    },
    "results": {
      "pve_nodes": [],
      "resources": [],
      "devices": [],
      "warnings": []
    }
  }
}
```

`state` is `queued`, `running`, `succeeded`, or `failed`. Results appear only
for `succeeded`. Progress messages are allowlisted summaries, not raw command
output.

PVE node rows contain `id`, `host`, `name`, `reachable`, and `version`.

Virtual resource rows contain:

```json
{
  "id": "pve:pve01:qemu:100",
  "kind": "vm",
  "vmid": 100,
  "name": "pve-freq",
  "node": "pve01",
  "status": "running",
  "ips": ["10.25.255.50"],
  "suggested_disposition": "owned",
  "suggested_placement": "production"
}
```

`kind` is `vm`, `container`, or `template`. Suggestions are advisory and are
never silently accepted by the backend.

Device rows contain:

```json
{
  "id": "device:truenas:10.25.255.10",
  "kind": "truenas",
  "label": "storage-01",
  "host": "10.25.255.10",
  "source": "network-probe",
  "reachable": true,
  "credential_fields": ["username", "password", "api_key"],
  "suggested_disposition": "owned",
  "suggested_placement": "production"
}
```

Device `kind` is an allowlisted product type such as `pfsense`, `truenas`,
`switch`, `idrac`, or `unknown`. Unknown devices may be acknowledged but
cannot be owned until assigned a supported kind.

## 3. Contract from selections

### `POST /api/setup/contract`

Requires admin session and CSRF. Replaces the current draft atomically.

```json
{
  "schema": "zero-state-web-v1",
  "setup_id": "opaque-setup-id",
  "discovery_id": "opaque-discovery-id",
  "client_request_id": "uuid",
  "selections": [
    {
      "resource_id": "pve:pve01:qemu:100",
      "disposition": "owned",
      "placement": "production"
    },
    {
      "resource_id": "pve:pve01:qemu:999",
      "disposition": "acknowledged"
    },
    {
      "resource_id": "device:truenas:10.25.255.10",
      "disposition": "owned",
      "placement": "production"
    }
  ]
}
```

Rules:

- Every discovered virtual resource and device appears exactly once.
- `disposition` is `owned` or `acknowledged`.
- `placement` is `production` or `lab` for owned resources and is omitted for
  acknowledged resources.
- Owned templates normalize to `template_vmids`; owned VMs/containers
  normalize to `owned_vmids`; acknowledged virtual resources normalize to
  `acknowledged_out_of_contract_vmids`.
- Owned devices become managed physical inventory in their selected scope.
  Acknowledged devices remain visible inventory-only and require no secret.
- PVE nodes are infrastructure roots declared by the cluster request and are
  not repeated as selectable resources.
- Unknown, missing, duplicate, or stale resource IDs fail the entire request.

Success is HTTP 200:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "contract": {
    "id": "opaque-contract-id",
    "discovery_id": "opaque-discovery-id",
    "revision": 1,
    "sha256": "normalized-contract-sha256",
    "counts": {
      "owned_virtual": 18,
      "templates": 10,
      "acknowledged_virtual": 8,
      "owned_devices": 4,
      "acknowledged_devices": 1
    },
    "credential_requirements": [
      {
        "resource_id": "device:truenas:10.25.255.10",
        "required_any": [["username", "password"], ["api_key"]],
        "stored_fields": []
      }
    ],
    "ready": false
  }
}
```

The normalized object, not TOML, is the source consumed by web-launched init.
Its hash is stable for identical discovery IDs and selections.

### `GET /api/setup/contract`

Returns the current normalized contract and credential-presence metadata for
the bound setup. It never returns secrets or vault keys.

## 4. Device credentials

### `POST /api/setup/device-credentials`

Requires admin session and CSRF. Secrets are values, never paths.

```json
{
  "schema": "zero-state-web-v1",
  "setup_id": "opaque-setup-id",
  "contract_id": "opaque-contract-id",
  "client_request_id": "uuid",
  "credentials": [
    {
      "resource_id": "device:truenas:10.25.255.10",
      "username": "root",
      "secrets": {
        "password": "write-only-value",
        "api_key": "write-only-value"
      }
    }
  ]
}
```

Allowed secret field names are `password`, `api_key`, `ssh_private_key`, and
`sudo_password`. Allowed fields are constrained by device kind. At least one
server-returned `required_any` alternative must be satisfied for every owned
device before init may start.

Values are stored directly in a setup-scoped vault namespace with restrictive
ownership. Updating a credential replaces only fields present in the request.
Empty strings are rejected and never mean delete.

Response:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "contract_id": "opaque-contract-id",
  "credentials": [
    {
      "resource_id": "device:truenas:10.25.255.10",
      "stored_fields": ["username", "password", "api_key"],
      "complete": true
    }
  ],
  "ready": true
}
```

Responses expose presence only. They never expose length, prefix, hash, last
characters, encrypted bytes, internal vault key names, or filesystem paths.

## 5. Init

### `POST /api/setup/init/start`

Requires admin session and CSRF. It consumes only opaque frozen objects plus
remaining value inputs:

```json
{
  "schema": "zero-state-web-v1",
  "setup_id": "opaque-setup-id",
  "discovery_id": "opaque-discovery-id",
  "contract_id": "opaque-contract-id",
  "client_request_id": "uuid",
  "service_account": {
    "username": "freq-admin",
    "password": "write-only-value"
  },
  "options": {
    "ssh_mode": "sudo",
    "pdm": {"mode": "skip"},
    "ssl": {"mode": "defer"}
  }
}
```

For PDM modes requiring a credential, `options.pdm.password` is a write-only
value. No path variant exists.

The backend verifies that discovery and contract IDs are current, all
selections are complete, required device secrets exist, and no init is already
running. It then launches the existing bounded headless init runner. Internal
adapters may materialize short-lived 0600 files where legacy subprocess
boundaries still require them; those paths are never accepted from or exposed
to the browser and are removed at terminal job state.

Success is HTTP 202:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "job": {
    "id": "opaque-init-job-id",
    "state": "queued",
    "poll_after_ms": 1000
  }
}
```

### `GET /api/setup/init/status?id=<job_id>`

Returns `queued`, `running`, `succeeded`, or `failed`, bounded progress, and
honest completion fields:

```json
{
  "ok": true,
  "schema": "zero-state-web-v1",
  "job": {
    "id": "opaque-init-job-id",
    "state": "succeeded",
    "returncode": 0,
    "initialized": true,
    "web_setup_complete": true,
    "poll_after_ms": 0,
    "progress": {
      "phase": 12,
      "phase_name": "Verification",
      "current": 39,
      "total": 39,
      "message": "All verification checks passed."
    },
    "log_tail": []
  }
}
```

`log_tail` contains only redacted operator-safe lines. The separate existing
`GET /api/setup/init/logs?id=<job_id>` may return a longer bounded redacted
tail but follows the same secret rules.

The frontend polls after `poll_after_ms` (minimum 500 ms, maximum 5000 ms),
stops at a terminal state, and tolerates one service handoff disconnect by
reloading `GET /api/setup/status` and resuming with the same job ID.

## Completion and markers

Browser setup is complete only when init exits zero, `.initialized` exists,
and `_write_web_setup_markers()` successfully writes
`.web-setup-complete`. The terminal job reports `succeeded` only after all
three facts are true.

`POST /api/setup/complete` is not called by `zero-state-web-v1`. It becomes a
legacy/recovery endpoint and cannot create a false web-only success state.
Neither creating the first operator nor freezing a contract writes a
completion marker.

On failure:

- `.web-setup-complete` is absent.
- The init job reports `failed` with a redacted blocker.
- The authenticated setup window remains reachable.
- Stored selections and credential-presence metadata remain available for a
  bounded retry; bootstrap/device secret values never return to the browser.

## Polling and retention

- Discovery: begin at 1000 ms and honor each `poll_after_ms`; no faster than
  500 ms.
- Init: begin at 1000 ms, settle at 2000 ms during long phases, and honor the
  server hint.
- Only one active discovery and one active init are allowed per setup.
- Completed job metadata and non-secret results remain available for at least
  one hour or until setup completes.
- If process restart loses an in-memory job, the endpoint returns 410 rather
  than claiming idle or success. Durable `.initialized` and marker truth still
  wins in `/api/setup/status`.

## Legacy boundaries

The following are explicitly outside the browser contract and must disappear
from `setup.html` and `setup.js`:

- bootstrap password/private-key paths;
- service/dashboard password paths;
- VM contract and device credential paths;
- owned/template/acknowledged VMID text or range inputs;
- hosts import/TOML text;
- certificate/key/Cloudflare token paths;
- arbitrary core/lab device text lists.

CLI compatibility for those inputs remains until a separate deprecation
decision. A CLI init may warn when staged credential inputs are present but
unconsumed. Browser setup cannot trigger that warning because it never accepts
a server path.

The installer hardening companion in this arc must also prevent local-source
root permissions from propagating to the install root: the destination root
must finish traversable by the configured runtime account regardless of a
mode-700 staging directory.
