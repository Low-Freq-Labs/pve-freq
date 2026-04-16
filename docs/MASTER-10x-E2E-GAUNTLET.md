# MASTER-10x-E2E-GAUNTLET

Status: controlling document for the 10-run `pve-freq` destructive/recleaned E2E campaign.

Owner model:
- Finn runs the campaign and owns pass/fail calls.
- Jarvis owns pre-run reclean and post-failure reset verification.
- Rick owns backend/runtime/init/auth/token/device failures.
- Morty owns operator-surface/UI/docs/truth/recovery failures.

Non-negotiable rules:
- No run starts until Jarvis confirms the target set and `5005` are 100% clean for that run's assumptions.
- Every run is judged against its own explicit proof criteria, not vibes.
- Every failure gets tokenized immediately to Rick or Morty unless it is already understood, fixed, and reverified in the same run.
- No silent carry-over from one run to the next. Reset boundaries are explicit.
- If a run exposes a new class of ambiguity, update this document before the next run.

## Why This Exists
The product already passed one clean end-to-end gauntlet, but one green run is not enough. The point of this 10x campaign is to force:
- destructive resets
- repeated clean installs
- hostile reruns
- auth and token drift
- recovery from partial state
- operator-truth verification after each lifecycle edge

The product should survive not only the happy path, but the ugly paths that expose fake contracts.

## Research Principles
This gauntlet is informed by:
- Google testing guidance on minimizing shallow E2E and making each E2E carry a distinct system-level purpose
- Google SRE release and emergency-response doctrine: game-day style drills, explicit proof criteria, real rollback/recovery boundaries
- AWS chaos/game-day guidance: inject failure deliberately, classify blast radius, prove recovery rather than merely observing failure
- community lessons from auth drift, stale caches, idempotency failures, and partial-install contradictions

Operational takeaway:
- each run must have a unique failure class it is trying to expose
- each run must produce concrete evidence, not "seemed fine"
- cleanup and rerun discipline matters as much as the run itself

Additional malicious-training input now folded into this master:
- joint Rick + Morty v2 appendix at `/opt/freq-devs/rick/findings/R-PVEFREQ-MALICIOUS-TRAINING-20260415H-v2.md`
- 8-persona threat model
- 30 unified attack patterns across 21 categories
- backend/runtime and web/operator abuse merged into one matrix

## Global Reset Contract
Jarvis must confirm the reset state before each run.

Required reset proof unless the run explicitly says otherwise:
- `freq-admin` absent across the in-scope fleet where that run requires pre-init cleanliness
- `5005` has no `/opt/pve-freq`, no `.initialized`, no runtime unit residue, and no stale service-account/runtime artifacts
- prior generated credentials, systemd units, vault/config/data residue, and old runtime state are removed if the run requires a true clean slate
- exclusions are listed explicitly; nothing is silently "close enough"

Jarvis deliverable before each run:
- `GO` or `NO-GO`
- scope cleaned
- residuals, if any
- whether residuals are acceptable for that specific run

## Token Routing
Token Rick when the defect is about:
- `freq init`
- install/uninstall/update/bootstrap mechanics
- auth/session/token/runtime/backend behavior
- PVE API identity/token/ACL/bootstrap drift
- device deployers: iDRAC, switch, pfSense, TrueNAS
- service account, SSH, sudo, verification, doctor backend logic

Token Morty when the defect is about:
- README/help/setup/dashboard/operator copy
- UI parity, stale data, surface truth, wrong messaging
- recovery usability
- operator-facing contradictions between CLI/API/dashboard/docs
- proof artifacts and human-facing release trust

If a bug crosses both:
- token Rick first for runtime truth
- token Morty second for operator-surface correction

## Stop / Continue Rules
Continue same run if:
- the failure is understood
- the fix is bounded
- the clean-state assumptions of the run are still intact after reclean

Stop and revise the matrix if:
- the failure invalidates the run's premise
- the cleanup boundary is no longer trustworthy
- a new hidden dependency makes later runs redundant or unsafe

## Common Proof Artifacts
Capture after every run, unless not applicable:
- `sudo python3 -m freq doctor`
- `sudo python3 -m freq fleet status --json`
- relevant init output
- dashboard reachability check
- targeted API/auth proof when the run touches auth or token behavior
- exact failure text and exact phase if the run fails

## The 10 Runs

### Run 1: Clean Baseline
Purpose:
- prove the clean headless install/init path on a fully wiped `5005`
- prove the default service-account contract with default `freq-admin`
- prove the configured PVE runtime token path and device deployment path

Preconditions:
- full Jarvis clean reset
- no `freq-admin` on in-scope fleet
- `5005` blank

Execution:
1. deploy current tree to `5005`
2. install from local source
3. headless init using default service-account name
4. run doctor, fleet status, dashboard reachability checks

Must catch:
- bootstrap drift
- token/bootstrap contradictions
- device deploy failures
- dashboard/doctor contradictions on a first-run system

Pass criteria:
- init ends green
- doctor green
- fleet status green
- dashboard reachable

### Run 2: Immediate Idempotency Rerun
Purpose:
- prove rerunning `freq init` on a green system heals and reasserts instead of duplicating or breaking

Preconditions:
- successful Run 1 state
- no cleanup between first and second init

Execution:
1. rerun `freq init --headless` on the already initialized `5005`
2. compare service-account, token, device, RBAC, and doctor state before/after

Must catch:
- duplicate user/token creation
- non-idempotent ACL or sudo writes
- stale verification contradictions after rerun

Pass criteria:
- rerun succeeds or truthfully no-ops
- no duplicate drift
- doctor remains green

### Run 3: Password-First Bootstrap
Purpose:
- prove bootstrap auth mode is not secretly key-dependent

Preconditions:
- full Jarvis reclean
- key and password sources explicitly controlled

Execution:
1. run clean install
2. headless init using bootstrap password-first path, not bootstrap key-first

Must catch:
- hidden key auto-detect dependence
- password precedence drift
- misleading auth error handling

Pass criteria:
- init succeeds with password-first bootstrap
- resulting runtime state matches key-first baseline

### Run 4: Custom Service Account Name
Purpose:
- prove `freq-admin` is truly a default, not a hardcoded sacred identity

Preconditions:
- full Jarvis reclean
- chosen non-default service account name

Execution:
1. run clean install
2. init with custom `cfg.ssh_service_account`
3. verify fleet SSH, doctor, token id, and surface copy all follow the custom name

Must catch:
- hardcoded `freq-admin`
- hidden `freq-ops` misuse
- token/user/systemd/runtime assumptions tied to the wrong identity

Pass criteria:
- runtime token id uses the chosen service account
- doctor and runtime surfaces reflect the chosen name
- no fallback to `freq-admin` except where explicitly documented as default only

### Run 5: Partial-Init Recovery
Purpose:
- prove the product recovers honestly from an interrupted or partially completed init

Preconditions:
- full Jarvis reclean

Execution:
1. start headless init
2. intentionally interrupt at a chosen mid-phase boundary
3. inspect partial state
4. rerun init or `--fix` as appropriate

Must catch:
- false initialized marker
- partial RBAC/service-account drift
- impossible-to-recover intermediate states
- misleading "already done" behavior

Pass criteria:
- recovery path is truthful
- rerun or fix converges to a healthy state
- no fake-clean doctor/readiness after partial failure

### Run 6: Uninstall Then Reinstall
Purpose:
- prove uninstall leaves a known-enough state and reinstall works from that state

Preconditions:
- initialized system

Execution:
1. run uninstall path
2. verify claimed cleanup actually happened
3. reinstall and reinit

Must catch:
- stale units
- stale `.pth` or editable shadow residue
- leftover service accounts or runtime files that poison reinstall
- uninstall copy that overclaims cleanup

Pass criteria:
- reinstall succeeds
- no stale uninstall residue blocks or contaminates the second install

### Run 7: PVE Token Drift / Regeneration
Purpose:
- prove runtime can recover when the service-account-owned PVE token is missing, stale, or invalid

Preconditions:
- initialized healthy system

Execution:
1. invalidate or remove the runtime token state deliberately
2. run the supported recovery path
3. verify token id, secret path, ACLs, and doctor behavior

Must catch:
- token path drift
- stale doctor checks
- hidden dependence on legacy Jarvis-only tokens
- false success logging when token verification failed

Pass criteria:
- runtime token is recreated for the chosen service account
- doctor reports the real service-account-owned token and goes green after recovery

### Run 8: Device-Credentials Stress
Purpose:
- prove device deploy and verify logic remains truthful across imperfect device credential conditions

Preconditions:
- full Jarvis reclean or clean enough device state for the chosen scenario

Execution:
1. run with valid switch/pfSense/iDRAC credentials
2. rerun with one deliberate device-credential fault or mismatch
3. verify the failure is bounded and honestly reported

Must catch:
- hidden hardcoded password-file paths
- wrong device type auth fallback
- timeout bugs
- bad recovery copy for device-specific failures

Pass criteria:
- valid case succeeds
- invalid case fails honestly and specifically
- no hang, no fake pass, no wrong host blamed

### Run 9: Adversarial Abuse / Malicious Training Run
Purpose:
- prove `pve-freq` resists nasty but realistic abuse attempts and fails honestly when pushed outside the happy path
- train the team against the kinds of hostile behavior that expose fake trust, auth drift, stale state lies, and hidden coupling

Preconditions:
- successful initialized system

Execution:
1. run a predeclared malicious-attempt matrix against the initialized system
2. attack auth/session/token/state assumptions, operator-truth surfaces, and recovery affordances without changing the rules mid-run
3. capture exact observed behavior for every attempt

Malicious-attempt matrix must include:
- bad auth and stale-session replay attempts
- header/cookie/query mismatch attempts
- wrong-method and destructive-endpoint abuse attempts
- token tampering, missing-token, stale-token, and mixed-identity attempts
- service-account naming drift attempts, including custom-name versus default-name assumptions
- malformed or conflicting config/input attempts
- attempts to make doctor, fleet status, dashboard, or setup/recovery copy disagree with reality
- attempts to force hidden manual-step dependence or operator confusion

Required named attack themes for Run 9:
- D6: first-run `text/plain` setup CSRF path
- W7: setup wizard `.initialized` false-configured window
- B5/B6: login timing / user-enumeration attack against `/api/auth/login`
- D8 / W8: handler verb confusion and state-changing `GET` paths
- W1/W2: simple-CORS and weak Origin validation assumptions
- W3: log injection through auth-adjacent surfaces
- W5: SSE replay / regression behavior under auth churn
- W6: TLS redirect / downgrade expectation gaps
- J1-PF: iDRAC slot squat / slot-preemption hostile behavior
- cross-cutting attempts to make the UI say "configured" or "healthy" while the backend state is false

Must catch:
- auth/session lies
- false success after token or identity tampering
- destructive endpoint method drift
- stale-data or parity contradictions under hostile use
- misleading setup, recovery, or error text that hides the real state
- security-adjacent behavior that depends on obscurity instead of explicit checks

Pass criteria:
- every malicious attempt is logged with expected versus actual behavior
- the system either resists cleanly or fails honestly and specifically
- no attack produces fake-clean operator state
- no attack reveals a new hidden manual step
- the Run 9 matrix explicitly records verdicts for D6, W7, B5/B6, D8/W8, and J1-PF

### Run 10: Hostile Dirty-State Recovery
Purpose:
- prove the product can recover from ugly but plausible field state instead of only from curated clean scenarios

Preconditions:
- partially dirty or conflicting state prepared deliberately

Execution:
1. seed a known-bad combination:
   - stale runtime files
   - token drift
   - partial service-account presence
   - leftover config/data/unit state
2. run supported recovery path
3. verify convergence or explicit failure

Must catch:
- reliance on perfect cleanup
- brittle assumptions about file ownership or prior token state
- "works from clean only" bugs

Pass criteria:
- recovery either converges cleanly or fails with precise, operator-usable truth
- no silent corruption

## Per-Run Checklist
For each run, record:
- Jarvis reset verdict
- git/tree version under test
- exact command line used
- whether install, init, rerun, recovery, uninstall, or fix was exercised
- final status: pass/fail
- proof artifacts captured
- malicious attempts tried, if any
- malicious-attempt ledger updated, if applicable
- tokens opened, if any
- whether the master needs amendment before next run

## Malicious-Attempt Ledger
When a run includes hostile or abusive behavior, record each attempt explicitly:
- attempt id
- attack class
- exact setup and command/request used
- why this attempt is nasty
- expected safe behavior
- actual observed behavior
- verdict: resisted / failed honestly / failed dangerously
- resulting token or fix, if any

This is mandatory for Run 9 and recommended for any other run where we deliberately do ugly things.

Minimum fields for Run 9 ledger rows:
- threat persona id, if applicable
- attack pattern id
- affected surface: CLI / API / dashboard / init / device deploy / doctor

## Failure Classification
Class A:
- hidden manual step
- fake-clean doctor
- false initialized state
- wrong identity/token contract
- auth/session lies
- adversarial attempt that succeeds in creating false operator truth or unsafe silent state

Class B:
- recoverable backend/runtime failure with honest reporting
- bounded device or deploy failure
- service/account/token drift that recovery can heal

Class C:
- operator-surface contradiction
- stale copy/docs/help
- parity/freshness ambiguity

## Campaign Exit Criteria
The 10x gauntlet is complete only when:
- all 10 runs have been executed
- each run has explicit pass/fail evidence
- the malicious-attempt ledger exists for every applicable run and captures the nastiest attempts made
- every defect found has either been fixed and reverified or explicitly classified as accepted risk
- the final clean post-run system still passes:
  - `freq init` relevant scenario proof
  - `freq doctor`
  - `freq fleet status --json`
  - dashboard reachability

## Deferred Extension
The joint v2 appendix proposes a stronger `Run 11` in two forms:
- `11-Storm`: 12 parallel adversaries during one init
- `11-Curated`: 6 story-driven hostile sub-runs

That is intentionally out of scope for the base 10x campaign. If the 10x pass survives cleanly, this is the next escalation path rather than a substitute for any run above.

## Current Baseline
Known proven live baseline before the 10x campaign:
- clean `5005` headless init green
- service-account-owned PVE token green
- fleet `21/21` online
- doctor `20/20` green
- iDRAC deploy path required a larger real-world budget and now passes live
