"""Operator-truth product law contract.

Pins the frontend invariants required by pve-freq-product-law.md:

  - freq must not lie to a tired operator.
  - freq must not say "healthy" unless it can explain what that means.
  - status output must be actionable without forcing a tired operator
    to dig through logs.

These are translation rules into code:

  - Missing required setup artifacts (ssh_key_exists / pve_nodes_configured
    / hosts_configured) must surface in the operator-truth banner even
    when backend omits the `setup_health` field. Pre-fix the banner
    rendered "Healthy — hide" on a payload that said
    `ssh_key_exists: false` because `setup_health` was missing — the
    one field that gates the entire fleet path was a silent lie.

  - Doctor degradation (status:"unhealthy" / failed>0 / warnings>0) must
    surface in the operator-truth banner alongside setup truth. Pre-fix
    the home page never called /api/doctor and never told the operator
    the doctor said the system was unhealthy.

  - The silent health/fleet refreshers must run structural sanity on
    HTTP 200 responses, not just trust them. Pre-fix a /api/fleet/overview
    that said `vms:[]` with every PVE node `online:false` reset the
    failure streak and "all good" banners stayed up.

  - The PVE metrics refresher must mark host cards STALE when the node
    goes offline, not silently skip the update. Pre-fix the card kept
    rendering pre-disconnect numbers minutes after the cluster died.

  - monRunDoctor must render the structured doctor response (status /
    passed / failed / warnings / checks[]). Pre-fix it only knew
    d.output and printed "(no output)" for the structured shape — a
    blank box where the truth lived.

  - The stream-status badge must show last-event freshness, not just
    "LIVE" the moment the socket opened. A 2AM operator can't
    distinguish a healthy quiet stream from a producer that died 12
    minutes ago.

  - All readers must be field-tolerant for Rick's incoming
    state/probe_state/reason/last_seen_ts/checked_at fields so the
    backend lane can land independently.
"""

import os
import re
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO_ROOT, "freq", "data", "web")


def _app_js():
    with open(os.path.join(WEB, "js", "app.js")) as f:
        return f.read()


def _fn_body(src, name):
    idx = src.find("function " + name + "(")
    if idx == -1:
        return ""
    start = src.find("{", idx)
    if start == -1:
        return ""
    depth = 0
    i = start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return src[start:]


class TestSetupTruthMissingArtifactsSurface(unittest.TestCase):
    """Missing required artifacts must surface even when backend omits
    setup_health entirely. The pre-fix code only inspected
    ssh_key_exists / pve_nodes_configured / hosts_configured INSIDE
    the _isDegradedSetupHealth(setup_health) branch, so a payload like
        {first_run:false, ssh_key_exists:false, pve_nodes_configured:true}
    rendered "Healthy — hide banner" because setup_health was undefined.
    SSH key absence is catastrophic for the fleet path; that is not a
    thing to hide behind a green absence."""

    def test_missing_artifacts_helper_exists(self):
        src = _app_js()
        self.assertIn("function _missingSetupArtifacts(", src,
            "_missingSetupArtifacts(d) must exist as a single source of "
            "truth for which required artifacts are missing")

    def test_missing_artifacts_inspects_three_required_fields(self):
        body = _fn_body(_app_js(), "_missingSetupArtifacts")
        self.assertIn("pve_nodes_configured", body)
        self.assertIn("hosts_configured", body)
        self.assertIn("ssh_key_exists", body)

    def test_setup_truth_summary_helper_exists(self):
        """A shared summary builder so pre-auth and post-auth banners
        cannot disagree about whether the system is degraded."""
        src = _app_js()
        self.assertIn("function _setupTruthSummary(", src)

    def test_summary_fires_on_missing_artifacts_without_setup_health(self):
        """The summary must return a degraded result when any required
        artifact is missing, even if setup_health is undefined. This is
        the core fix — pre-fix the missing-artifact branch was nested
        inside the _isDegradedSetupHealth branch and could never fire
        on its own."""
        body = _fn_body(_app_js(), "_setupTruthSummary")
        self.assertIn("_missingSetupArtifacts", body,
            "_setupTruthSummary must call _missingSetupArtifacts so "
            "missing required fields surface even when setup_health "
            "is undefined")
        # The branch must combine setup_health degraded OR missing
        # artifacts as a single OR predicate, not a nested if.
        self.assertRegex(
            body,
            r"degraded\s*\|\|\s*missing\.length",
            "_setupTruthSummary must treat missing artifacts as "
            "degraded independently of setup_health",
        )

    def test_setup_truth_summary_returns_null_only_when_fully_clean(self):
        body = _fn_body(_app_js(), "_setupTruthSummary")
        # The healthy fall-through must be the LAST branch (no nested
        # else swallowing the missing-artifact path).
        self.assertIn("return null", body)

    def test_summary_prefers_backend_setup_reason_when_present(self):
        """Rick's 170b0c8 ships /api/setup/status with setup_reason
        carrying the actionable detail verbatim ('partial setup: init
        incomplete; ssh key missing or unreadable; ...'). When that
        field is present the banner must use it as-is — locally
        constructed strings can never be as accurate as the backend's
        own reason. Pre-fix the renderer always rebuilt the detail
        line locally, throwing away the backend's authoritative form."""
        body = _fn_body(_app_js(), "_setupTruthSummary")
        self.assertIn("d.setup_reason", body,
                      "_setupTruthSummary must consume backend-provided "
                      "setup_reason verbatim when present")
        # Local-construct fallback must remain so older payloads still
        # render something honest.
        self.assertIn("missing.join", body,
                      "fallback path must still construct a detail line "
                      "from missing artifacts when setup_reason is absent")

    def test_post_auth_banner_consumes_summary(self):
        body = _fn_body(_app_js(), "_renderPostAuthTruthBanner")
        self.assertIn("_setupTruthSummary", body,
            "_renderPostAuthTruthBanner must consume _setupTruthSummary "
            "so it can never disagree with the pre-auth banner")

    def test_login_banner_consumes_summary(self):
        body = _fn_body(_app_js(), "_renderSetupTruthBanner")
        self.assertIn("_setupTruthSummary", body)


class TestDoctorTruthSurfaces(unittest.TestCase):
    """The /api/doctor structured response must reach the operator-truth
    banner. Pre-fix the home page never called /api/doctor and the
    only place that did (monRunDoctor) printed (no output) for the
    structured shape."""

    def test_doctor_truth_summary_helper_exists(self):
        src = _app_js()
        self.assertIn("function _doctorTruthSummary(", src)

    def test_doctor_summary_inspects_status_failed_warnings_checks(self):
        body = _fn_body(_app_js(), "_doctorTruthSummary")
        for field in ("d.failed", "d.warnings", "d.status", "d.checks"):
            self.assertIn(field, body,
                "_doctorTruthSummary must read " + field + " so the "
                "operator gets actionable doctor truth, not a generic "
                "comfort string")

    def test_doctor_summary_lists_failing_check_names(self):
        """Operator must see WHICH check is failing without digging
        through /api/doctor output. Names go into the body line."""
        body = _fn_body(_app_js(), "_doctorTruthSummary")
        self.assertIn("failNames", body)
        self.assertIn("warnNames", body)

    def test_doctor_probe_helper_exists(self):
        src = _app_js()
        self.assertIn("function _probeDoctorTruth(", src)
        self.assertIn("function _startDoctorProbe(", src)

    def test_doctor_probe_uses_doctor_endpoint(self):
        body = _fn_body(_app_js(), "_probeDoctorTruth")
        self.assertIn("API.DOCTOR", body)

    def test_doctor_probe_started_post_auth(self):
        body = _fn_body(_app_js(), "_showApp")
        self.assertIn("_startDoctorProbe()", body,
            "_showApp must start the doctor probe so the operator-truth "
            "banner reflects doctor degradation immediately after login")

    def test_post_auth_banner_merges_doctor_into_setup_truth(self):
        body = _fn_body(_app_js(), "_renderPostAuthTruthBanner")
        self.assertIn("_doctorTruthSummary", body,
            "_renderPostAuthTruthBanner must merge the doctor summary "
            "into the same banner so doctor degradation cannot hide "
            "behind a 'setup looks fine' payload")

    def test_doctor_probe_torn_down_on_logout(self):
        body = _fn_body(_app_js(), "doLogout")
        self.assertIn("_doctorProbeTimer", body)


class TestSilentRefreshStructuralSanity(unittest.TestCase):
    """A 200 response without probe_status doesn't mean the data is
    fresh — it can also mean the backend has no idea. Treat
    structurally-empty responses as degraded so the UI never paints
    "0 hosts" or "every PVE offline + zero VMs" as truth."""

    def test_health_structural_helper_exists(self):
        src = _app_js()
        self.assertIn("function _healthStructurallyDegraded(", src)

    def test_fleet_structural_helper_exists(self):
        src = _app_js()
        self.assertIn("function _fleetStructurallyDegraded(", src)

    def test_health_structural_flags_no_hosts(self):
        body = _fn_body(_app_js(), "_healthStructurallyDegraded")
        self.assertIn("no hosts in payload", body)
        self.assertIn("every host unhealthy", body)

    def test_fleet_structural_flags_all_pve_offline(self):
        body = _fn_body(_app_js(), "_fleetStructurallyDegraded")
        self.assertIn("every PVE node offline", body)

    def test_silent_health_consumes_structural_check(self):
        body = _fn_body(_app_js(), "_silentHealthRefresh")
        self.assertIn("_healthStructurallyDegraded", body,
            "_silentHealthRefresh must call the structural sanity "
            "helper so a 200 with empty hosts still ticks the streak")

    def test_silent_fleet_consumes_structural_check(self):
        body = _fn_body(_app_js(), "_silentFleetRefresh")
        self.assertIn("_fleetStructurallyDegraded", body)

    def test_silent_health_field_tolerant_for_new_state_fields(self):
        """Frontend must read state / probe_state / probe_status as
        equivalent so Rick's backend lane can ship the new field set
        independently without breaking the frontend contract."""
        body = _fn_body(_app_js(), "_silentHealthRefresh")
        self.assertIn("probe_status", body)
        self.assertIn("probe_state", body)
        self.assertIn(".state", body)
        self.assertIn("hd.reason", body)

    def test_silent_fleet_field_tolerant_for_new_state_fields(self):
        body = _fn_body(_app_js(), "_silentFleetRefresh")
        self.assertIn("probe_status", body)
        self.assertIn("probe_state", body)
        self.assertIn(".state", body)
        self.assertIn("fo.reason", body)


class TestPveMetricsStaleMarker(unittest.TestCase):
    """An offline PVE node must mark its host card STALE, not silently
    skip the update and let the pre-disconnect numbers freeze on screen."""

    def test_stale_marker_helpers_exist(self):
        src = _app_js()
        self.assertIn("function _markHostCardStale(", src)
        self.assertIn("function _clearHostCardStale(", src)

    def test_pve_metrics_marks_stale_when_offline(self):
        body = _fn_body(_app_js(), "_pveMetricsRefresh")
        self.assertIn("_markHostCardStale(card,n)", body,
            "_pveMetricsRefresh must mark offline nodes STALE rather "
            "than the pre-fix `if(!n.online)return;` silent skip")
        self.assertIn("_clearHostCardStale(card)", body,
            "_pveMetricsRefresh must clear the STALE marker once a "
            "node comes back online")

    def test_stale_marker_uses_last_seen_ts_when_present(self):
        """Field-tolerant: if Rick's last_seen_ts lands later, the
        badge shows 'STALE 47s' instead of just 'STALE'."""
        body = _fn_body(_app_js(), "_markHostCardStale")
        self.assertIn("last_seen_ts", body)


class TestMonRunDoctorStructuredRenderer(unittest.TestCase):
    """monRunDoctor must render the structured doctor JSON, not just
    d.output. Pre-fix it printed (no output) for the structured shape."""

    def test_renders_status_passed_failed(self):
        body = _fn_body(_app_js(), "monRunDoctor")
        for field in ("d.status", "d.passed", "d.failed", "d.warnings"):
            self.assertIn(field, body,
                "monRunDoctor must read " + field + " so the structured "
                "doctor response is rendered, not silently dropped")

    def test_lists_failing_check_names(self):
        body = _fn_body(_app_js(), "monRunDoctor")
        self.assertIn("FAILING / WARNING CHECKS", body,
            "monRunDoctor must enumerate failing/warning check names "
            "so the operator doesn't have to dig through raw json")

    def test_falls_back_to_legacy_output_field(self):
        """Legacy d.output / d.error path must remain so older backends
        and dump-style endpoints still render."""
        body = _fn_body(_app_js(), "monRunDoctor")
        self.assertIn("d.output", body)
        self.assertIn("d.error", body)


class TestStreamStatusFreshness(unittest.TestCase):
    """The stream-status header badge must show last-event freshness.
    Pre-fix it said LIVE the moment EventSource onopen fired even if
    zero events came through afterward — a 2AM operator could not
    distinguish a healthy quiet stream from a producer that died 12
    minutes ago."""

    def test_last_stream_event_state_exists(self):
        src = _app_js()
        self.assertIn("_lastStreamEventTs", src)
        self.assertIn("STREAM_STALE_AFTER_MS", src)

    def test_mark_stream_event_helper_exists(self):
        src = _app_js()
        self.assertIn("function _markStreamEvent(", src)

    def test_render_includes_freshness_label(self):
        body = _fn_body(_app_js(), "_renderStreamStatus")
        # Either "LIVE WAITING" or "LIVE STALE" or "LIVE <age>"
        self.assertIn("LIVE WAITING", body)
        self.assertIn("LIVE STALE", body)
        self.assertIn("_formatStreamAge", body)

    def test_stale_demotes_dot_color(self):
        body = _fn_body(_app_js(), "_renderStreamStatus")
        # When age > STREAM_STALE_AFTER_MS, the visual class drops
        # from s-live to s-cached so the dot turns yellow.
        self.assertIn("STREAM_STALE_AFTER_MS", body)
        self.assertIn("s-cached", body)

    def test_sse_listener_wrapping_marks_event_ts(self):
        """startSSE must wrap addEventListener so every received event
        bumps _lastStreamEventTs. Without this, the freshness counter
        would only advance for the unnamed message channel."""
        body = _fn_body(_app_js(), "startSSE")
        self.assertIn("_markStreamEvent", body,
            "startSSE must call _markStreamEvent on incoming events")
        self.assertIn("onmessage", body)


class TestHomeTileDensification(unittest.TestCase):
    """Per Finn's command-deck direction (Apr 14): every tile carries
    expected-vs-actual, freshness, and a next-useful-path. Pre-fix the
    home fleet-stats tiles showed raw counts side by side with no
    expected total, no data age, and no click-through — the operator
    had to mentally derive 5/5 from "5 UP / 0 DOWN" and had no way to
    drill down without using the side nav."""

    def test_fresh_chip_helper_exists(self):
        src = _app_js()
        self.assertIn("function _freshChip(", src)
        body = _fn_body(src, "_freshChip")
        # Must thread color through age thresholds (green/yellow/red).
        self.assertIn("var(--green)", body)
        self.assertIn("var(--yellow)", body)
        self.assertIn("var(--red)", body)

    def test_age_from_payload_helper_handles_all_field_names(self):
        """Field-tolerant: the helper must consume any of the freshness
        field names the backend lane has shipped under Rick's product-
        law rollout — age_seconds (legacy), checked_at, probed_at, and
        last_seen_ts. No silent fallthrough to 'fresh forever'."""
        src = _app_js()
        self.assertIn("function _ageFromPayload(", src)
        body = _fn_body(src, "_ageFromPayload")
        for field in ("age_seconds", "checked_at", "probed_at", "last_seen_ts"):
            self.assertIn(field, body,
                "_ageFromPayload must inspect " + field)
        # Returns null (not 0, not 'now') when no freshness info exists,
        # so the chip can render '?' instead of pretending the data is
        # current.
        self.assertIn("return null", body)

    def test_home_fleet_stats_uses_fresh_chip(self):
        body = _fn_body(_app_js(), "_loadHomeFleetStats")
        self.assertIn("_freshChip", body,
            "_loadHomeFleetStats must render a freshness chip per tile "
            "so the operator can see how recent the data is")
        # Field-tolerant: must read probe_state before falling back to
        # legacy probe_status.
        self.assertIn("probe_state", body)

    def test_home_fleet_stats_carries_expected_vs_actual(self):
        """Tiles must encode actual-vs-expected (e.g. "5/5 UP") not
        bare counts. Pre-fix the operator had to read two columns and
        infer the relationship."""
        body = _fn_body(_app_js(), "_loadHomeFleetStats")
        # The _d helper must accept an `exp` opt that renders v1 as
        # "v1/exp" — not just two raw columns.
        self.assertRegex(
            body,
            r"v1\+'/'\+opts\.exp",
            "_d helper must thread an expected total so tiles can "
            "render in actual/expected form",
        )
        # And it's actually used by the SSH PROBE / PVE NODES tiles.
        self.assertRegex(
            body,
            r"exp\s*:\s*totalAll",
            "SSH PROBE tile must encode totalAll as the expected count",
        )
        self.assertRegex(
            body,
            r"exp\s*:\s*pveCount",
            "PVE NODES tile must encode pveCount as the expected count",
        )
        # VMs tile rebuilds with x/y form too.
        self.assertIn("run+'/'+total", body,
            "VMs tile must show running/total, not bare running count")
        # Containers tile rebuilds with x/y form.
        self.assertIn("_cup+'/'+_ctot", body,
            "CONTAINERS tile must show up/total")

    def test_home_fleet_stats_threads_view_clickthrough(self):
        """Each tile must carry a data-view target so clicking it
        navigates to the relevant page — the next-useful-path Finn
        called for. Pre-fix tiles were inert."""
        body = _fn_body(_app_js(), "_loadHomeFleetStats")
        # The _d helper builds the data-view attribute when opts.view
        # is set.
        self.assertIn("data-view=\"'+opts.view", body,
            "_d helper must thread opts.view into a data-view attribute")
        # SSH PROBE / FLEET / PVE NODES tiles carry the fleet view.
        self.assertRegex(
            body,
            r"view\s*:\s*'fleet'",
            "fleet-related tiles must click through to the fleet view",
        )
        # CONTAINERS tile click-through to docker.
        self.assertIn("setAttribute('data-view','docker')", body)
        # ACTIVITY tile click-through to media.
        self.assertIn("setAttribute('data-view','media')", body)

    def test_d_helper_returns_clickable_tile_when_view_present(self):
        body = _fn_body(_app_js(), "_loadHomeFleetStats")
        # The cursor:pointer cue must be threaded so the tile is
        # visibly interactive when a view target exists.
        self.assertIn("cursor:pointer", body)


class TestPriorContractsStillGreen(unittest.TestCase):
    """The product-law fixes must not regress AI/AJ/AK/AL contracts."""

    def _run(self, module_name):
        import unittest as _ut
        loader = _ut.TestLoader()
        suite = loader.loadTestsFromName(module_name)
        runner = _ut.TextTestRunner(verbosity=0, stream=open(os.devnull, "w"))
        result = runner.run(suite)
        return len(result.failures) + len(result.errors)

    def test_al_release_qa_contract_still_green(self):
        self.assertEqual(self._run("tests.test_release_ux_qa_contract"), 0)

    def test_ak_ux_contract_still_green(self):
        self.assertEqual(self._run("tests.test_blueteam_ux_contract"), 0)

    def test_aj_hardening_contract_still_green(self):
        self.assertEqual(self._run("tests.test_blueteam_hardening_contract"), 0)

    def test_ai_operator_truth_contract_still_green(self):
        self.assertEqual(self._run("tests.test_operator_truth_contract"), 0)


if __name__ == "__main__":
    unittest.main()
