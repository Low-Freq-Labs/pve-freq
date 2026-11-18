# Standard QEMU read request ownership — R3

This is the backend source contract for the ordinary four-route QEMU read
slice. It supersedes the initial request-ownership draft and adopts the exact
schema3 field sets in Morty's reviewed consumer WIRE-R4/CONTRACT-R4. It does
not issue an installation, source, view, target or provider grant. Rick owns
backend implementation and Morty owns original frontend correspondence.

Sonny approved ordinary bounded application resource management instead of the
retired custom worker guarantees. Original session/CSRF, TLS, secret ownership,
source and target incarnation, writer exclusion, recipient, lifetime and
once-only requirements remain. A separate proposal to weaken absolute
incarnation/external-writer guarantees is pending; this contract does not adopt
that proposal. Source work proceeds while affected positive admission refuses.

## Original request and HTTP boundary

The original `FreqHandler` dispatches these paths before its legacy generic
auth/error wrappers. There is no parallel server, executor or fallback route.
Every request is a direct-TLS, same-origin, cookie-session POST with mandatory
`X-Freq-CSRF`, strict UTF-8 JSON and at most2048 body bytes. Query parameters,
duplicate/extra keys, nested structures, transfer/content encoding, redirects,
retries, automatic refresh, alternate targets, proxy auth and SSH are refused.

| Path | Exact body keys |
| --- | --- |
| `/api/observe/v1/open` | `previous_view_ref` |
| `/api/observe/v1/node` | `view_ref,node_ref,read_ref` |
| `/api/observe/v1/qemu` | `view_ref,node_ref,vm_ref,read_ref` |
| `/api/observe/v1/retire` | `view_ref` |

Only open permits null: `previous_view_ref:null` creates an independent mount;
otherwise it names that mount's exact prior owned view. Every reference is
exactly64 lowercase hex characters from an original256-bit server issuance.
It is neither a URL, target selector supplied by the browser, secret credential
nor proof of issuance merely because its bytes match a stored value.

Capture the original auth registry, lock, session dictionary, user, role and
CSRF value; recheck their original identities and current membership before
final release. Do not renew activity/session/view lifetime while reading.
Logout, replacement, expiry, privilege or credential changes revoke affected
admission and recipients. Returning to the same-looking values cannot revive
a retired view or consumed attempt. Original TLS, cookie and Origin checks
are required; forwarded headers cannot supply their authority.

HTTP200 is reserved for an originally admitted complete route message. Refusal
is exactly `{schema:3,kind:"refusal",error}` with no refs or details:
401/authentication-required;400,403,409/read-refused;429,503/read-unavailable.
Other pairs fail closed. Every emitted message uses
`application/json; charset=utf-8`, exact Content-Length, no-store, nosniff and
Connection:close, without compression, redirects, retry or session-refresh
headers. Consume the response attempt before fallible header/body IO. A send
failure never enters a second generic JSON error or success path.

## Server-owned view, selection and attempt

The original installation owns its configuration/trust/principal snapshot and
finite retained tables. A caller-created object, dataclass, callback, digest,
UUID, supplied transport or old pilot installation cannot create that owner.
The source gate, auth gate and view gate always follow that order. Acquire
without a waiting queue; refuse before dispatch when admission is unavailable.
Reserve and retain each original operation before fallible acquisition or
reference consumption. No socket, credential or provider operation precedes it.

Open captures a maximum30-second monotonic view lifetime. Its configured rows
have exactly `label,node_ref,read_ref`. References bind original configured
rows, not display labels. Node selection consumes its read_ref once and
retires previous node/VM descendants before acquisition. Its response echoes
the original view_ref,node_ref,read_ref and includes source_label, collection
and sections exactly cluster/inventory. Inventory rows are exactly
`node,guest_kind,vmid,name,vm_ref,read_ref`, with guest_kind=qemu. Unknown or
unqualified rows may be literal visible data but have both refs null and are
unselectable; never construct a usable selection from VMID/name/IP.

QEMU selection consumes the exact inventory-issued read_ref once, captures
the original selected row/incarnation/source/view generation and retires its
predecessor recipient before acquisition. It echoes the four request refs,
source_label, target, collection and sections exactly
status/configured_network/guest_network. Target is exactly
`node,guest_kind,vmid,name` from that original row. Equal display fields do
not authorize a replacement guest. Each configured or inventory row has both
usable original refs or both null; mixed pairs are invalid.

Open's response is exactly schema,kind,view_ref,collection,sections(nodes).
Retire's response is exactly schema,kind,view_ref,state=retired and confirms
only logical revocation after exact original correlation. Unknown opening or
retirement returns do not authorize retry or capacity refund. Refresh first
retires the old local view, then independently opens with its previous ref;
even refusal of the replacement does not resurrect the old view. Repeated
retirement cannot alter another session/view or replay cleanup.

Bounds are16 views per session,128 process-wide, two entered provider-read
attempts process-wide and one per view. Unentered expired references may be
retired. Entered or uncertain work retains original capacity until its own
independent duties settle; no eviction, replacement, guessed unlock or refund
on timeout/logout/retirement. Table admission must itself remain bounded.
References are never reused within the original owner; exhaustion refuses.

## Original source, writer and target prerequisites

Participating source changes enter the original writer transaction before
source read/modify/write and before effects. Invalidate the prior generation
and affected read admission/recipients before mutation. A failed write does
not restore the former generation. Source → auth → view ordering also applies
to relevant credential, TLS, role/session and setup/enrollment changes. Do not
hold those state gates across provider requests or HTTP response IO.

The current process source epoch is a necessary negative filter only.
Partial helper coverage is not all-writer participation. Original source
capture, private approved credential/trust ownership, view registration and
invalidation/final release remain implementation work. Other processes,
administrators, system trust changes and provider writers are outside a
Python gate and require the retained exclusion/provenance mechanism.

Configured endpoint and verified TLS identify a transport recipient, not a
never-reused node/guest incarnation. VMID/name, digest, SMBIOS UUID, vmgenid,
MAC, IP, successful JSON and a fresh random application reference do not fill
that gap. Before positive selection, the producer must establish authenticated
issuer/lifecycle fields, allowed mutation, clone/restore/recreate/migrate
semantics, node binding and original pre/post revalidation. Missing mandatory
identity or writer evidence refuses the whole attempt, not merely a section.
The separately reviewed A-or-B PM proposal changes none of this until approved.

## Cooperative deadline and provider path

Capture one original request end from the original handler request start,
at most10 seconds and always capped by view/source/selection expiry. Node's
cluster/inventory siblings and QEMU's status/current-config/agent siblings
share that same end. No parser, sibling, successful response, new phase or
event reentry renews it. Expiry stops new acquisition/publication, without
claiming an entered blocking/native call stopped or resources physically closed.

Use the fixed numeric-IP:8006 verifying TLS client, approved original CA/token
source and enumerated GETs: `/api2/json/cluster/status`, `/api2/json/nodes/{node}/qemu`,
`/api2/json/nodes/{node}/qemu/{vmid}/status/current`,
`/api2/json/nodes/{node}/qemu/{vmid}/config?current=1` and
`/api2/json/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces`. Required identity
revalidation calls must be separately enumerated before admission; they are
not invented from these display reads. Provider node names are1..63 ASCII
matching `[A-Za-z0-9][A-Za-z0-9-]{0,62}`; VMIDs are exact integers100..999999999.
Configured source_label is separate literal display text1..256 UTF-8 bytes.

One accepted-provider-body counter includes every sibling and required
identity read, maximum4194304 bytes. Cluster/status bodies are at most262144
each; inventory/current-config/agent bodies at most1048576 each. No sibling
resets the counter. A separate emitted application-response cap is4194304
UTF-8 bytes. Existing stricter nested transport/decoder bounds remain intact;
these are application caps, not hard parser/RSS/OpenSSL guarantees.

Retain original raw/TLS/response/stream and credential duties before acquiring
or closing calls. Attempt independent cleanup once even after a sibling fails;
a wrapper return does not prove an independent socket duty settled. Preserve
first Control, then Memory, then ordinary failure identity/priority and retain
unknown stages. Never log raw provider bodies, URLs, authorization or secrets.

## Emitted DATA and final recipient

Schema3 sections are exactly state,reason,source_observed_at,collection,data.
Complete/none means only the fully validated credential-visible response;
empty is empty for that query. Partial has a validated subset and reason
incomplete/deadline/capacity, with unknown total. Unavailable and unsupported
have null data/times and only the fixed reviewed reasons. Generic transport
failure does not prove agent-disabled, permission-denied or not-supported.
Malformed framing/JSON or identity/correlation refuses the envelope. Valid
status/config data must not be erased merely because the independent agent
section is unavailable. Partial cannot be released after the original deadline.

Provider source time and collector intervals are nullable provenance metadata,
never invented from one another or used to renew lifetime. Known timestamps
use valid-calendar UTC milliseconds; completed>=started. Sibling sections are
not an atomic provider snapshot. Unknown/zero/empty remain distinct.

The exact reviewed wire limits are depth16,131072 structural punctuation,
4096-byte string tokens,256-byte labels,1024 configured/Cluster rows,256 QEMU
rows,32 configured NICs,64 guest interfaces,16 addresses/interface and two
gateways/configured NIC. No silent complete truncation. Exact safe nonnegative
integer counters exclude booleans; CPU is nullable finite0..1 with range
checked before lossy conversion. Retain the decoder's stricter numeric lexeme
and nested Cluster limits. Configured IPv4 modes are null/static/dhcp; IPv6
adds auto. `current=1` excludes pending settings and proves no guest application.
Raw passwords, SSH keys, hooks and arbitrary config fields are never projected.

Final release re-enters the same source → auth → view gates and rechecks the
original owner, source/trust/credential generation, session/principal,
incarnation, view/selection, consumed attempt, current recipient and deadline.
Prepare a bounded detached exact envelope before releasing eligible bytes;
no caller-supplied eligibility flag can replace that original check. Logical
publication is before IO; logout after bytes are admitted cannot retract them.
The original frontend must independently compare its mount/selection/modal,
pending attempt and monotonic cutoff immediately before literal DOM insertion.
Late results may settle only their own cleanup, never change successor refs,
values, spinner/error state or capacity. No previous-data panel or automatic
polling/refresh is included. All mutation/edit/power/console/SSH controls remain
unavailable in this read-only slice.

## Current implementation and next work

The original backend entry implements strict request/auth/refusal handling
only and currently sends503 for otherwise valid requests. Transport and
status/network projection are separately reviewed source leaves. Covered
host/Vault/local init/setup/fleet writer prefixes do not complete the writer
census or read-side ownership. The old pilot/nativeFalse/CLI78 and historical
Product R29 remain unchanged. No live credential/provider/browser/TLS or
installed product qualification follows from local fictional checks.

Rick next completes remaining participating writer hooks, original read-source
and secret/trust capture, finite original view/reference/attempt tables and
final source/auth/view recipient checks. Strong identity/external-writer
mechanism or the separate explicit PM decision remains a positive-admission
gate. Morty continues the exact original Fleet row/modal/session/lifetime
composition. Each original join needs source correspondence and meaningful
new scoped checks; old passing component suites are not replayed or summed as
whole-product proof. Operational demonstration still requires a separately
selected nonproduction target, service, credential and trust scope. This
contract selects none.
