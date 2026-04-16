## Run 9 Malicious-Attempt Ledger

### B5
- threat persona id: hostile-operator
- attack pattern id: B5
- attack class: login timing / enumeration
- affected surface: API
- exact setup and command/request used: `POST /api/auth/login` with `{"username":"admin","password":"wrongpass"}`
- why this attempt is nasty: valid-user/wrong-pass paths often leak timing or message differences that allow username enumeration
- expected safe behavior: same status and error shape as an unknown user
- actual observed behavior: `401` in `0.0555s` with `{"error":"Invalid credentials"}`
- verdict: resisted
- resulting token or fix: none

### B6
- threat persona id: hostile-operator
- attack pattern id: B6
- attack class: login timing / enumeration
- affected surface: API
- exact setup and command/request used: `POST /api/auth/login` with `{"username":"nosuchuser","password":"wrongpass"}`
- why this attempt is nasty: unknown-user paths often reveal existence drift through faster rejects or different copy
- expected safe behavior: same status and error shape as a valid-user/wrong-pass attempt
- actual observed behavior: `401` in `0.0542s` with `{"error":"Invalid credentials"}`
- verdict: resisted
- resulting token or fix: none

### D8
- threat persona id: hostile-operator
- attack pattern id: D8
- attack class: verb confusion / state-changing GET
- affected surface: API
- exact setup and command/request used: `GET /api/auth/login`
- why this attempt is nasty: mutating or auth-sensitive routes sometimes accept GET and become CSRFable or cache-poisonable
- expected safe behavior: reject non-POST method clearly
- actual observed behavior: `405` with `{"error":"Use POST with JSON body for login"}`
- verdict: resisted
- resulting token or fix: none

### W1-W2
- threat persona id: cross-origin attacker
- attack pattern id: W1/W2
- attack class: simple-CORS / weak-Origin assumption
- affected surface: API
- exact setup and command/request used: `POST /api/auth/login` with `Origin: https://evil.example`
- why this attempt is nasty: weak CORS or Origin handling can make auth endpoints scriptable cross-origin
- expected safe behavior: no auth bypass and no permissive wildcard CORS
- actual observed behavior: same `401 Invalid credentials`; no permissive `Access-Control-Allow-Origin` surfaced
- verdict: resisted
- resulting token or fix: none

### D6
- threat persona id: first-run CSRF attacker
- attack pattern id: D6
- attack class: `text/plain` setup CSRF
- affected surface: API / setup
- exact setup and command/request used: `POST /api/setup/complete` with `Content-Type: text/plain` body on an already initialized box
- why this attempt is nasty: permissive setup completion can allow browser-forged simple requests to mutate setup state
- expected safe behavior: reject or fail honestly without mutating state
- actual observed behavior: `403` with `{"error":"Setup already complete"}`
- verdict: failed honestly
- resulting token or fix: none

### W7
- threat persona id: setup-state attacker
- attack pattern id: W7
- attack class: false-configured window
- affected surface: API / dashboard
- exact setup and command/request used: `GET /api/setup/status` on the initialized `5005` system
- why this attempt is nasty: setup status can drift and tell the UI the box is configured when initialization is false or partial
- expected safe behavior: consistent initialized/configured truth
- actual observed behavior: `200` with `first_run=false`, `initialized=true`, `setup_health="configured"`, and a reason matching completed init
- verdict: resisted
- resulting token or fix: none

### W5-A
- threat persona id: auth-churn attacker
- attack pattern id: W5
- attack class: SSE replay / auth churn
- affected surface: API / SSE
- exact setup and command/request used: `GET /api/events?token=fake-token`
- why this attempt is nasty: old query-token auth paths can bypass session truth or leak stale compatibility shims
- expected safe behavior: reject with explicit migration guidance
- actual observed behavior: `403` with `reason="query_token_removed"` and truthful migration copy
- verdict: resisted
- resulting token or fix: none

### W5-B
- threat persona id: auth-churn attacker
- attack pattern id: W5
- attack class: SSE bearer and mixed-identity behavior
- affected surface: API / SSE
- exact setup and command/request used: `GET /api/events` with valid `Authorization: Bearer <token>`, then `GET /api/events?token=fake-token` with the same valid bearer
- why this attempt is nasty: mixed auth channels can create ambiguous precedence or stale-token bypass
- expected safe behavior: valid bearer should authenticate; fake query token must not override it
- actual observed behavior: valid bearer returned `200` and SSE `: connected`; mixed query-token plus valid bearer also connected instead of failing
- verdict: resisted
- resulting token or fix: none

### W6
- threat persona id: downgrade attacker
- attack pattern id: W6
- attack class: TLS redirect / downgrade expectation gap
- affected surface: dashboard
- exact setup and command/request used: `GET http://10.25.255.55:8888/login`
- why this attempt is nasty: plain HTTP listeners or weak redirect logic can leak credentials or create false TLS assumptions
- expected safe behavior: no plaintext login surface
- actual observed behavior: `curl` returned `code=000`; no plain HTTP listener answered
- verdict: resisted
- resulting token or fix: none

### W3
- threat persona id: log-poisoning attacker
- attack pattern id: W3
- attack class: log injection
- affected surface: API / logs
- exact setup and command/request used: `POST /api/auth/login` with username containing embedded newline/header-like text
- why this attempt is nasty: unsanitized auth-adjacent logging can forge log lines or poison operator telemetry
- expected safe behavior: request rejected without forged multiline log content
- actual observed behavior: `429` due login rate limit; log growth was one structured `api_request` line and no forged injected lines were observed in the tail
- verdict: resisted
- resulting token or fix: none

### J1-PF
- threat persona id: device-preemption attacker
- attack pattern id: J1-PF
- attack class: iDRAC slot squat / slot preemption
- affected surface: init / device deploy
- exact setup and command/request used: live hostile condition from earlier gauntlet runs where iDRAC user slots were already occupied; init attempted device deploy on real hardware and hit `No empty iDRAC user slots (3-16 all occupied)`
- why this attempt is nasty: occupied management slots can force unsafe overwrite behavior or indefinite probing
- expected safe behavior: bounded detection with explicit operator truth, no silent overwrite
- actual observed behavior: init surfaced explicit no-empty-slot failure/skip instead of overwriting an occupied slot; later iDRAC probing was bounded via follow-up fixes from Runs 6-8
- verdict: failed honestly
- resulting token or fix: Run 6 iDRAC timeout/bounded-probe fixes already landed
