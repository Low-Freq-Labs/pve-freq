# Cluster Status product adapter — draft R1

This is the implementation contract for the first product integration slice. It is not an accepted runtime or a deployment instruction. Existing fictional capture/recipient owners remain unchanged and are not production transport adapters.

## User entry and observation meaning

The original PVE node card exposes an explicit Cluster Status gesture. It bypasses `/api/exec`. Opening a card does not fetch cluster data. The result is a literal report, with unknown values preserved and empty distinct from unavailable; it grants no quorum, management or mutation authority.

The initial offline package uses the exact supplied-only decoder/display contract. A harness supplies immutable fictional configuration, an ordinary authenticated test session, and fixed upstream bytes. It must exercise the actual registered handler and HTTP response writer, not intercept the frontend result. No fixture registration route or fixture switch is shipped in the production API. A provider-backed observation needs a separately named provenance contract; neither `supplied_only` nor all-false capability flags may silently change.

## Proposed HTTP contract for the offline integrated journey

1. `POST /api/pve/cluster-report/bind` accepts only `{"selection_ref":"<server-issued opaque selection reference>"}`. Existing global authentication and cookie CSRF policy apply. The selection reference is added by the server to a configured node inventory record, scoped to the original session and inventory snapshot. Browser label, IP, command, endpoint, credential and role fields are never accepted. A cached row without a reference shows unavailable rather than falling back to raw execution.
2. A successful bind returns exactly `{"schema":"cluster-report-binding-v1","binding_ref":"<opaque reference>","expires_in_ms":<remaining integer milliseconds>}` with HTTP200 and no-store. It captures the original session record, configured selection snapshot and one recipient lifetime. It neither acquires provider data nor asserts node incarnation identity.
3. `POST /api/pve/cluster-report/read` accepts only `{"binding_ref":"<opaque reference>"}`. It consumes that binding once before acquisition. A fresh gesture requires a fresh binding. One request has a total 10-second monotonic budget, a 1MiB upstream cap and a 2MiB public body cap. No retries, redirect following, alternate-node selection or SSH fallback.
4. Successful offline output is the exact `cluster-status-browser-v1` supplied-only body, HTTP200 `application/json; charset=utf-8`, exact Content-Length and `Cache-Control: no-store`. It is not wrapped in a second arbitrary success envelope.
5. Refusal uses a fixed bounded JSON object `{"error":"cluster_report_unavailable"}` and status400 for invalid input,403 for invalid/expired session,409 for spent/foreign/stale selection,503 for unavailable acquisition/validation and504 for deadline. No raw provider body, exception text, address, credential or stack is disclosed. The frontend status gate rejects these before the report decoder.

## Inventory and role fields

The sole public inventory property is `pve_nodes[].cluster_report_selection_ref`, an optional string of exactly32 lowercase ASCII hexadecimal characters (`^[0-9a-f]{32}$`). It is issued per authenticated inventory response, never persisted in the shared background cache. Missing or malformed means unavailable. The frontend retains it from the exact original node row through card creation; it must not recover it with a later label/IP search or from a replacement cache row.

Both POST routes require an existing application `viewer`, `operator`, `admin` or `protected` session. Unknown role strings are denied. This is application read disclosure policy, not a claim of upstream provider permission. Binding responses permit exactly the three named fields: schema literal, reference using the same32-hex grammar, and integer `expires_in_ms` from1 through30000. Expiry starts on the server and cannot be extended by frontend parsing or a repeated request. Browser cancellation/deadline remains independent of server expiry.

## Server ownership and bounds

Selections and bindings are generated server-side with independent random128-bit references, bounded to64 outstanding selections and16 outstanding bindings per session, plus a process-wide cap of1,024 combined outstanding records. Refusal on capacity exhaustion does not evict a live reference. Expired references are removed without enabling reuse. Session termination invalidates associated references. Bindings cannot outlive the selected inventory reference; a zero remaining lifetime is refused.

The original session record is captured under the auth store lock and checked by object identity, role and expiry before acquisition and immediately before response publication. A new session with the same username does not inherit ownership. Capturing credentials or transport policy must not be inferred from mutable handler fields. This task does not redefine provider ACLs: viewer application access alone cannot prove upstream effective permissions or visibility completeness.

The configured target is resolved only from a server-owned snapshot. The inventory publisher and request adapter must share the reference issuer; matching a cached label/IP is insufficient. An endpoint/configuration change invalidates the snapshot. Because endpoint equality cannot prove node incarnation or detect all configuration ABA history, no such identity claim appears in the result.

The response writer marks its attempt consumed before headers, body or cleanup. A post-header failure closes the original connection; outer dispatch must not append an error JSON or send a second status line. All acquisition resources close on success, failure, cancellation and setup failure. Ordinary cleanup failure yields unavailable before publication; cancellation is preserved after cleanup. No reentrant callback may reopen a consumed invocation.

## Provider boundary still to implement and qualify

A genuine provider adapter must use exactly the configured endpoint and verified TLS trust, one fixed `/api2/json/cluster/status` GET and bounded response reading. Existing generic `_pve_call`/`_pve_api_call` cannot substitute: they allow fallback or do not supply the required response limits. Credentials remain server-owned and must never enter public bindings or evidence. Source implementation is routine authorized development; credential use, live qualification and deployment require their existing explicit authorization.

The positive offline demonstration does not close this provider boundary. Its report must say offline supplied data. Product release must not advertise current cluster health until the named provider provenance contract and approved environment demonstration are complete.

## Acceptance on one source package

The package must contain the real route registry, auth integration, inventory reference issuer, bounded adapter, once-only writer, frontend entry and accepted decoder/display. Demonstrate positive, empty, unavailable, wrong-profile and oversized results; consumed reference reuse; forged label/IP; changed session/configuration; deadline; writer failure; and held response across Back/Forward, card replacement and logout. Verify no `/api/exec` fallback and no request on passive card creation.

Rick owns backend and package correspondence. Morty owns original frontend lifetime and entry. Jake reviews producer/response semantics and Finn reviews ownership and the whole journey. Review should identify missing implementation boundaries directly rather than adding unrelated component families.

## R2 clarification: dispatch, locking and publication

Reference consume is atomic under the reference store mutex. Lock order is auth store then reference store; no code acquires auth while holding reference store. No auth or reference mutex is held across provider I/O, browser socket writes, arbitrary callbacks or resource cleanup. Capture and revalidation read the exact session dictionary identity and permitted role under the auth mutex; mutable handler fields are not admission evidence.

Publication linearizes when the still-current authenticated request is marked admitted/consumed under the auth mutex. The mutex is then released before the one response write. Logout before that point rejects disclosure. Logout after that point cannot retract already-admitted/in-flight network bytes; the frontend original-session retirement prevents their publication into a stale UI. Do not claim stronger socket revocation. A once-only writer and the actual serve._dispatch consumed-response guard prevent generic500 append after any write attempt. The admission transition must occur in the same request record as the writer guard, with no user callback between validation and marking.

Selection TTL is30 seconds from server issue. Binding TTL is at most30 seconds and never later than selection expiry. Exact lowercase32-hex grammar applies to both references. POST bodies are at most256 UTF-8 bytes, exactly one required member, no duplicate JSON keys, no Transfer-Encoding, and exactly one canonical positive decimal Content-Length. The handler closes the connection on framing refusal rather than consuming an unknown remainder.

The fixed error object above applies to errors from the dedicated cluster handlers. Earlier shared authentication/CSRF/media-type gates retain their existing non200 shapes; the browser rejects status before decoding and never depends on their content. This slice does not claim to normalize every global dispatcher error. All cluster body reads and writes require socket timeouts within the remaining request budget; helper source alone does not enforce that overall budget.

Inventory references are added only to a copied response row after matching it to the current server-owned configured selection snapshot. The shared background cache is never modified. The original card must retain that response row’s reference, not refind it by display name. Current endpoint/snapshot equality is not incarnation or effective-permission evidence.


Inventory refresh capacity: a refresh does not revoke already-issued original-card references. New references are issued only while the64 per-session and1,024 process caps allow them. Rows above the cap omit the optional property and show unavailable. Repeated refresh may temporarily exhaust capacity until the30-second expiry; it must not silently reuse or overwrite a prior reference. More than64 configured rows are not claimed as a complete selectable set in this slice. This conservative policy is explicit and must appear in the UI qualification evidence; a later usability policy may replace it with its own lifecycle tests.
