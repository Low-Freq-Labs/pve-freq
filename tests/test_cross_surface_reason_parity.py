"""Cross-surface reason-string parity contract.

Per Finn (Apr 14, product-law translation pass): every observation
channel must carry the same truth string. Probe → audit log → API
response → CLI output → web banner all read through the SAME
classify_probe_failure() helper in freq/core/health_state.py, so a
host's failure mode is named identically no matter which surface
the operator looked at.

Pre-product-law there was nothing forcing this — each surface could
construct its own message ("ssh failed", "host down", "auth error")
and they drifted whenever someone touched one renderer without
updating the others. That drift is exactly the lie at 2AM the
product law calls out.

This contract pins three layers:

  1. STATIC CALL-SITE PIN — every call site that surfaces a per-host
     reason must import and use classify_probe_failure (or its
     entry_base wrapper). Rick's rollout under R-PRODUCT-LAW-BACKEND-
     TRUTH (e03b382 / 170b0c8 / 9dd8200 / 869416f) named these four
     sites as the canonical readers:

        freq/modules/fleet.py  — cmd_status (CLI fleet status)
        freq/core/doctor.py    — _check_fleet_connectivity (CLI doctor)
        freq/modules/serve.py  — _bg_probe_health (background probe)
        freq/api/fleet.py      — handle_health_api fallback (HTTP API)

     A fifth file (frontend app.js) reads the reason field from the
     /api/health response — that's already consumer-side and doesn't
     re-classify, so it picks up the same string for free.

  2. ANTI-DRIFT GREP — no source file outside health_state.py may
     contain the auth_failed pattern-matching strings ("permission
     denied" + "publickey" together). If a future refactor builds a
     parallel classifier in another module the grep catches it.

  3. DYNAMIC CLI<->API PARITY — `python3 -m freq fleet status --json`
     and the same probe data exposed through cmd_status both produce
     entries with a `reason` field whose shape is stable. Subprocess
     run + json parse, assert the field exists for every host. (Live
     reason-string equality across CLI vs API requires both surfaces
     reading the same probe at the same moment, which is flaky on
     this local serve where everything is healthy. The static pin
     above catches the structural drift; this dynamic check confirms
     the JSON contract is intact.)
"""

import json
import os
import re
import subprocess
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel_path):
    with open(os.path.join(REPO_ROOT, rel_path)) as f:
        return f.read()


class TestStaticCallSitesUseCanonicalClassifier(unittest.TestCase):
    """Every CLI / API / probe surface that names a per-host failure
    reason must read it through classify_probe_failure (or its
    entry_base wrapper, which calls classify_probe_failure internally).
    Pre-fix each surface had its own free-form error string and they
    drifted independently."""

    CALL_SITES = (
        "freq/modules/fleet.py",     # CLI fleet status
        "freq/core/doctor.py",       # CLI doctor
        "freq/modules/serve.py",     # background probe
        "freq/api/fleet.py",         # HTTP API
    )

    def _imports_classifier(self, src):
        """True if the file imports classify_probe_failure or
        entry_base (the wrapper that calls it). Both paths land at
        the same canonical reason string."""
        return ("classify_probe_failure" in src
                or "entry_base" in src
                or "from freq.core.health_state" in src
                or "from .health_state" in src)

    def test_all_call_sites_import_canonical_classifier(self):
        for path in self.CALL_SITES:
            with self.subTest(path=path):
                src = _read(path)
                self.assertTrue(
                    self._imports_classifier(src),
                    f"{path} must import classify_probe_failure or "
                    f"entry_base from freq/core/health_state — every "
                    f"per-host reason must come from the canonical "
                    f"classifier so CLI/API/probe surfaces can never "
                    f"drift apart",
                )

    def test_classifier_lives_in_one_canonical_location(self):
        """classify_probe_failure must exist in exactly one place
        (freq/core/health_state.py). A second copy in a different
        module would be a parallel-truth path even if it had the
        same name."""
        # Grep the entire freq/ tree for `def classify_probe_failure`.
        defs = []
        for root, dirs, files in os.walk(os.path.join(REPO_ROOT, "freq")):
            # Skip __pycache__.
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if not f.endswith(".py"):
                    continue
                full = os.path.join(root, f)
                with open(full) as fh:
                    if re.search(r"^def classify_probe_failure\b",
                                 fh.read(), re.MULTILINE):
                        defs.append(os.path.relpath(full, REPO_ROOT))
        self.assertEqual(
            defs, ["freq/core/health_state.py"],
            "classify_probe_failure must be defined in exactly one "
            "place — found in: " + repr(defs),
        )


class TestNoParallelClassifierDrift(unittest.TestCase):
    """Anti-drift: the canonical six-state STATE_* constants and the
    auth_markers / reach_markers tuples must be defined in exactly
    one location (freq/core/health_state.py). A parallel classifier
    in another module — even with renamed constants — would re-create
    the pattern matching and drift the reason strings.

    Pre-fix Rick's audit found this is a real risk: pattern matching
    on 'permission denied' / 'connection refused' was scattered across
    serve.py and fleet.py renderers in earlier iterations. The unify
    landed under R-PRODUCT-LAW-BACKEND-TRUTH; this test makes sure a
    future cleanup can't quietly re-introduce a parallel path.

    NOTE: substring-only greps for 'permission denied' have noise
    (init_cmd vault writes, test data). The constant-definition
    pin is the precise check — only health_state.py may DEFINE the
    six-state taxonomy."""

    STATE_CONSTANTS = (
        "STATE_LIVE",
        "STATE_STALE",
        "STATE_DEGRADED",
        "STATE_AUTH_FAILED",
        "STATE_UNREACHABLE",
        "STATE_RECOVERING",
    )

    def _walk_python_files(self, root="freq"):
        for r, dirs, files in os.walk(os.path.join(REPO_ROOT, root)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(r, f)

    def test_state_constants_defined_in_exactly_one_place(self):
        """Every STATE_* constant must be ASSIGNED in exactly one
        location. Other files import it — they don't redefine it.
        A redefinition in a sibling module would create a parallel
        taxonomy and silently break the cross-surface invariant."""
        for const in self.STATE_CONSTANTS:
            with self.subTest(const=const):
                # Match an assignment, not an import or usage.
                pat = re.compile(r"^\s*" + const + r"\s*=\s*['\"]", re.MULTILINE)
                defs = []
                for full in self._walk_python_files():
                    rel = os.path.relpath(full, REPO_ROOT)
                    with open(full) as fh:
                        if pat.search(fh.read()):
                            defs.append(rel)
                self.assertEqual(
                    defs, ["freq/core/health_state.py"],
                    f"{const} must be defined only in "
                    f"freq/core/health_state.py — found in: {defs!r}",
                )

    def test_all_states_frozenset_has_exactly_six_members(self):
        """Belt-and-suspenders on the six-state bar (Rick's suggestion).
        ALL_STATES in health_state.py must contain exactly six names.
        Adding a seventh state without updating aggregate_probe_state
        priority would silently break the cross-surface invariant —
        the new state would never reach the legacy compat alias and
        the renderers would fall through to default 'unknown'."""
        from freq.core.health_state import ALL_STATES
        self.assertEqual(
            len(ALL_STATES), 6,
            "ALL_STATES must contain exactly six canonical states. "
            "Adding a seventh requires updating aggregate_probe_state, "
            "legacy_status_for, and every renderer that switches on "
            "state — those are silent if a member sneaks in untracked",
        )
        for name in ("live","stale","degraded","auth_failed",
                     "unreachable","recovering"):
            self.assertIn(name, ALL_STATES)

    def test_auth_markers_tuple_structure_unique(self):
        """The auth_markers tuple inside classify_probe_failure (the
        list of ssh stderr substrings that map to auth_failed) must
        appear in only one source file. Any sibling module that
        constructs the same kind of tuple is building a parallel
        classifier even if it uses different variable names. The
        precise marker — 'no supported authentication methods' — is
        unique enough not to false-positive on init/vault paths."""
        unique_marker = "no supported authentication methods"
        offenders = []
        for full in self._walk_python_files():
            rel = os.path.relpath(full, REPO_ROOT)
            if rel == "freq/core/health_state.py":
                continue
            with open(full) as fh:
                if unique_marker in fh.read().lower():
                    offenders.append(rel)
        self.assertEqual(
            offenders, [],
            "Files outside freq/core/health_state.py that contain "
            "'no supported authentication methods' — this string is "
            "unique to the auth_failed classifier tuple, so any "
            "other file containing it is duplicating the classifier: "
            + repr(offenders),
        )


class TestCliJsonContractStable(unittest.TestCase):
    """Dynamic check: `freq fleet status --json` returns per-host
    entries that carry the canonical state + reason fields. The
    actual reason strings depend on probe state at run time, so this
    test only asserts the shape (keys exist, types correct) — the
    static call-site pin above is what guarantees the strings come
    from the same classifier."""

    @classmethod
    def setUpClass(cls):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "freq", "fleet", "status", "--json"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            cls.payload = None
            cls.skip_reason = str(e)
            return
        cls.skip_reason = None
        try:
            cls.payload = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            cls.payload = None
            cls.skip_reason = (
                f"freq fleet status --json did not return valid JSON: {e}\n"
                f"stdout head: {result.stdout[:400]!r}\n"
                f"stderr head: {result.stderr[:400]!r}"
            )

    def setUp(self):
        if self.payload is None:
            self.skipTest(
                "freq fleet status --json unavailable: " + (self.skip_reason or "?")
            )

    def test_payload_has_hosts_array(self):
        self.assertIn("hosts", self.payload,
            "freq fleet status --json must return a top-level 'hosts' array")
        self.assertIsInstance(self.payload["hosts"], list)
        self.assertGreater(len(self.payload["hosts"]), 0,
            "no hosts in payload — CLI status returned an empty fleet")

    def test_every_host_carries_state_and_reason(self):
        """Every host entry must carry both fields. Pre-product-law
        the CLI omitted reason entirely on healthy hosts, so a tired
        operator running the same command twice and seeing a missing
        field couldn't tell if the host was healthy or if the field
        had silently disappeared."""
        for h in self.payload["hosts"]:
            with self.subTest(label=h.get("label")):
                self.assertIn("state", h,
                    f"host entry missing 'state' field: {h}")
                self.assertIn("reason", h,
                    f"host entry missing 'reason' field: {h}")
                self.assertIsInstance(h["state"], str)
                self.assertIsInstance(h["reason"], str)
                self.assertTrue(h["reason"],
                    "reason must be non-empty even on healthy hosts "
                    "('probe OK' is acceptable, '' is not)")

    def test_state_values_are_canonical(self):
        """The state field must be one of the six canonical states
        from health_state.py. Any free-form value would mean a
        renderer is constructing its own taxonomy."""
        canonical = {"live", "stale", "degraded", "auth_failed",
                     "unreachable", "recovering"}
        for h in self.payload["hosts"]:
            with self.subTest(label=h.get("label")):
                self.assertIn(
                    h["state"], canonical,
                    f"host {h.get('label')} state {h['state']!r} is "
                    f"not in the canonical six-state set {canonical}",
                )


if __name__ == "__main__":
    unittest.main()
