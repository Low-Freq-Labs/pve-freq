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
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO_ROOT, "freq", "data", "web")


def _app_js():
    with open(os.path.join(WEB, "js", "app.js")) as f:
        return f.read()


def _serve_py():
    with open(os.path.join(REPO_ROOT, "freq", "modules", "serve.py")) as f:
        return f.read()


def _device_command_py():
    with open(os.path.join(REPO_ROOT, "freq", "services", "device_command.py")) as f:
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


class TestInfraOutputIsHumanReadable(unittest.TestCase):
    """Infrastructure detail panels should summarize raw device output before
    exposing raw payloads. Pre-fix TrueNAS alerts dumped internal JSON fields,
    which made a normal warning look like an emergency."""

    def test_truenas_output_uses_structured_renderer(self):
        body = _fn_body(_app_js(), "tnAction")
        self.assertIn("_renderTrueNasOutput(d)", body)
        self.assertIn("else if(d.reachable){o.innerHTML=_renderTrueNasOutput(d);}", body)

    def test_all_core_device_reads_use_structured_renderers(self):
        expectations = {
            "pfAction": "_renderPfOutput(d)",
            "swAction": "_renderSwitchOutput(d)",
            "idracAction": "_renderIdracOutput(d,action)",
        }
        for fn, expected in expectations.items():
            with self.subTest(fn=fn):
                self.assertIn(expected, _fn_body(_app_js(), fn))

    def test_core_action_map_exposes_complete_read_surface(self):
        src = _app_js()
        for text in (
            "SMART DISKS",
            "SNAPSHOTS",
            "SYSTEM LOG",
            "GATEWAY MONITOR",
            "ARP TABLE",
            "PORT ERRORS",
            "CDP NEIGHBORS",
            "STORAGE / RAID",
            "FIRMWARE",
            "LICENSE",
        ):
            self.assertIn(text, src)

    def test_repeated_api_toasts_are_deduped_and_rate_limited(self):
        src = _app_js()
        self.assertIn("function _shouldToastApiError", src)
        self.assertIn("_apiErrorToastState", src)
        self.assertIn("_toastState", src)
        self.assertIn("toast_deduped", src)
        self.assertIn("api_error_toast_suppressed", src)

    def test_truenas_alert_renderer_explains_meaning_and_action(self):
        body = _fn_body(_app_js(), "_renderTnAlerts")
        for text in ("What it means", "What to do", "Evidence"):
            self.assertIn(text, body)
        self.assertIn("Raw alert payload", body)

    def test_known_truenas_rest_api_alert_has_operator_language(self):
        body = _fn_body(_app_js(), "_tnAlertSummary")
        self.assertIn("RESTAPIUsage", body)
        self.assertIn("Deprecated REST API usage", body)
        self.assertIn("Migrate integrations", body)

    def test_truenas_missing_actions_have_specific_renderers(self):
        src = _app_js()
        for fn in ("_renderTnSmart", "_renderTnSnapshots", "_renderTnNetwork", "_renderTnReplication"):
            self.assertIn("function " + fn + "(", src)
        body = _fn_body(_app_js(), "_renderTrueNasOutput")
        for action in ("smart", "snapshots", "network", "replication", "syslog"):
            self.assertIn("a==='" + action + "'", body)

    def test_core_device_outputs_use_compact_summary_chips(self):
        src = _app_js()
        self.assertIn("function _infraMiniStats", src)
        self.assertIn("function _infraSummaryColor", src)
        self.assertIn("blue:'var(--text)'", src)
        self.assertIn("function _infraSkipSection", src)
        self.assertIn("opts&&opts.summary&&title==='SUMMARY'", src)
        render_section = _fn_body(src, "_infraRenderSection")
        render_text = _fn_body(src, "_infraRenderTextDevice")
        self.assertNotIn("_statCards", render_section)
        self.assertIn("hideTitle", render_section)
        self.assertIn("_infraTitle(sec.title)===_infraTitle(title)", render_text)
        for fn in (
            "_renderTnPools",
            "_renderTnStatus",
            "_renderPfOutput",
            "_renderSwitchOutput",
            "_renderIdracTargetOutput",
        ):
            with self.subTest(fn=fn):
                body = _fn_body(src, fn)
                self.assertIn("_infraMiniStats", body)
                self.assertNotIn("_statCards", body)

    def test_pfsense_interfaces_render_as_one_operator_table(self):
        src = _app_js()
        self.assertIn("function _pfInterfaceRows", src)
        self.assertIn("function _renderPfInterfacesOutput", src)
        self.assertIn("if(d.action==='interfaces')return _renderPfInterfacesOutput(d);", _fn_body(src, "_renderPfOutput"))
        body = _fn_body(src, "_renderPfInterfacesOutput")
        self.assertIn("<th>Interface</th><th>IP Address</th>", body)
        self.assertNotIn("no IP assigned</span>", body)
        self.assertIn("no ip assigned", _fn_body(src, "_pfInterfaceRows").lower())
        self.assertIn("_infraRawDetails('Raw pfSense payload'", body)
        self.assertNotIn("_infraRenderSection", body)

    def test_switch_monitoring_uses_native_switch_commands(self):
        with open(os.path.join(REPO_ROOT, "freq", "api", "net.py")) as f:
            src = f.read()
        self.assertIn('"spanning": "show spanning-tree summary"', src)
        self.assertIn('"log": "show logging"', src)
        self.assertNotIn("show spanning-tree brief", src)
        self.assertNotIn("tail 30", src)

    def test_pfsense_summary_sections_are_promoted_once(self):
        body = _fn_body(_app_js(), "_renderPfOutput")
        self.assertIn("_infraSummaryStatsFromSection(d.output,'SUMMARY')", body)
        for action in ("rules", "nat", "arp"):
            with self.subTest(action=action):
                idx = body.find("d.action==='" + action + "'")
                self.assertNotEqual(idx, -1)
                chunk = body[idx:idx + 450]
                self.assertIn("summary:_infraMiniStats(stats)", chunk)
                self.assertIn("skipSections:['SUMMARY']", chunk)
        states_idx = body.find("d.action==='states'")
        self.assertNotEqual(states_idx, -1)
        self.assertIn("skipDefaultSection:true", body[states_idx:states_idx + 450])

    def test_bmc_summary_rows_are_not_repeated_in_detail_table(self):
        src = _app_js()
        self.assertIn("function _renderIdracTargetOutput", src)
        body = _fn_body(src, "_renderIdracTargetOutput")
        self.assertIn("used[power.index]=true", body)
        self.assertIn("used[model.index]=true", body)
        self.assertIn("used[fw.index]=true", body)
        self.assertIn("detailRows=rows.filter", body)
        self.assertIn("_infraKvTable(detailRows)", body)
        self.assertIn("_infraRawDetails('Raw '+title+' payload'", body)

    def test_pfsense_interfaces_backend_emits_one_curated_section(self):
        src = _device_command_py()
        interfaces_idx = src.find('"interfaces": (')
        self.assertNotEqual(interfaces_idx, -1)
        chunk = src[interfaces_idx:interfaces_idx + 900]
        self.assertIn('=== INTERFACES ===', chunk)
        self.assertIn('no IP assigned', chunk)
        self.assertNotIn('=== INTERFACES WITH IPs ===', chunk)
        self.assertNotIn('=== ALL INTERFACES ===', chunk)

    def test_pfsense_backend_is_target_aware_for_lab_firewalls(self):
        src = _serve_py()
        self.assertIn("def _resolve_pfsense_target", src)
        self.assertIn("target_name = params.get(\"target\", [\"\"])[0]", src)
        self.assertIn("target = _resolve_pfsense_target(cfg, target_name)", src)
        self.assertIn("\"target\": pf_label", src)
        self.assertIn("\"ip\": pf_ip", src)
        serve_body = src.split("def _serve_pfsense", 1)[1].split("\n    def _serve_", 1)[0]
        self.assertNotIn("pf_ip = cfg.pfsense_ip", serve_body)


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
        # ACTIVITY tile click-through to Docker, where Media now lives as a subtab.
        self.assertIn("setAttribute('data-view','docker')", body)

    def test_d_helper_returns_clickable_tile_when_view_present(self):
        body = _fn_body(_app_js(), "_loadHomeFleetStats")
        # The cursor:pointer cue must be threaded so the tile is
        # visibly interactive when a view target exists.
        self.assertIn("cursor:pointer", body)


class TestFleetHostCardFreshness(unittest.TestCase):
    """Per-host card freshness chip — every host card on the fleet
    view must show its own data-age indicator. Pre-densification only
    OFFLINE cards carried any timestamp (the STALE marker from
    c5efe14); fresh cards looked identical regardless of probe age,
    which is the comfort-of-absence problem."""

    def test_decorate_host_card_fresh_helper_exists(self):
        src = _app_js()
        self.assertIn("function _decorateHostCardFresh(", src)
        self.assertIn("function _decorateAllHostCardsFresh(", src)

    def test_decorator_skips_stale_cards(self):
        """A card currently marked STALE must NOT also get the fresh
        chip. Operator should never see both at once — the stale
        marker takes precedence."""
        body = _fn_body(_app_js(), "_decorateHostCardFresh")
        self.assertIn("host-stale", body,
            "_decorateHostCardFresh must short-circuit when the card "
            "is currently marked stale")

    def test_mark_stale_strips_pre_existing_fresh_chip(self):
        """Race between _renderFleetData (which decorates fresh from
        /api/health hosts) and _pveMetricsRefresh (which marks stale
        when n.online===false): without this strip the card ends up
        with BOTH a fresh chip AND a stale badge. Pinning the strip
        so a future refactor can't reintroduce the double-marker."""
        body = _fn_body(_app_js(), "_markHostCardStale")
        self.assertIn("host-fresh-chip", body,
            "_markHostCardStale must strip any pre-existing fresh "
            "chip so the operator never sees both markers at once")

    def test_decorator_field_tolerant_for_per_host_timestamps(self):
        """Field-tolerant: probed_at (Rick's per-host) → last_success_at
        → top-level age_seconds. Without this fallthrough order the
        chip would render '?' on payloads that already carry the
        timestamps, defeating the densification."""
        body = _fn_body(_app_js(), "_decorateAllHostCardsFresh")
        for field in ("probed_at", "last_success_at", "age_seconds"):
            self.assertIn(field, body,
                "_decorateAllHostCardsFresh must inspect " + field)

    def test_render_fleet_data_calls_decorator(self):
        body = _fn_body(_app_js(), "_renderFleetData")
        self.assertIn("_decorateAllHostCardsFresh(hd)", body,
            "_renderFleetData must decorate cards with freshness "
            "after the fleet output is written")

    def test_silent_health_refresh_calls_decorator(self):
        """Decorator must run on every silent tick so the chip counts
        down without requiring a view reload."""
        body = _fn_body(_app_js(), "_silentHealthRefresh")
        self.assertIn("_decorateAllHostCardsFresh(hd)", body,
            "_silentHealthRefresh must refresh the host card chips "
            "on every successful tick")


class TestVmCardFreshness(unittest.TestCase):
    """Per-VM cards on the fleet view. Different rule than host cards:
    'stopped' is intentional (not stale), 'cluster unreachable' IS
    stale because we can't see the VM's real state. Pre-fix the cards
    showed cpu/ram bars with no indication of probe age."""

    def test_vm_card_decorator_exists(self):
        src = _app_js()
        self.assertIn("function _decorateAllVmCardsFresh(", src)

    def test_vm_decorator_marks_stale_when_fleet_degraded(self):
        """When the fleet payload itself is structurally degraded
        (every PVE node offline) every VM card must be marked STALE
        — we can't see the VM's real state through a broken probe."""
        body = _fn_body(_app_js(), "_decorateAllVmCardsFresh")
        self.assertIn("_fleetStructurallyDegraded", body,
            "VM decorator must consult structural-sanity helper")
        self.assertIn("_markHostCardStale", body,
            "VM decorator must mark cards stale when fleet is degraded")

    def test_vm_decorator_field_tolerant(self):
        body = _fn_body(_app_js(), "_decorateAllVmCardsFresh")
        for field in ("probed_at", "last_seen_ts", "age_seconds"):
            self.assertIn(field, body)
        # Field-tolerant for the probe_state names too.
        self.assertIn("fleet_state", body)
        self.assertIn("probe_state", body)

    def test_render_fleet_data_calls_vm_decorator(self):
        body = _fn_body(_app_js(), "_renderFleetData")
        self.assertIn("_decorateAllVmCardsFresh(fo)", body,
            "_renderFleetData must decorate VM cards alongside host cards")

    def test_silent_fleet_refresh_calls_vm_decorator(self):
        body = _fn_body(_app_js(), "_silentFleetRefresh")
        self.assertIn("_decorateAllVmCardsFresh(fo)", body,
            "_silentFleetRefresh must refresh VM card chips on every "
            "successful tick")


class TestSecurityOverviewDensification(unittest.TestCase):
    """loadSecPosture renders four operator-truth tiles (secrets audit,
    compliance status, cert summary, patch status). Pre-fix none of
    them carried a freshness chip — the operator could read a 6-month-
    old 'all green' tile and trust it. None had click-through to drill
    into the relevant tab."""

    def test_load_sec_posture_threads_fresh_chip(self):
        body = _fn_body(_app_js(), "loadSecPosture")
        # Chip must appear at least four times — once per sub-section.
        self.assertGreaterEqual(body.count("_freshChip"), 4,
            "loadSecPosture must render a freshness chip for each "
            "of secrets / compliance / cert / patch sub-sections")
        # Field-tolerant via _ageFromPayload.
        self.assertIn("_ageFromPayload", body)

    def test_load_sec_posture_threads_view_clickthrough(self):
        body = _fn_body(_app_js(), "loadSecPosture")
        # Every tile becomes a button to its detail view.
        self.assertIn("data-view", body,
            "loadSecPosture must thread data-view click-through")
        for view in ("'vault'", "'sec-compliance'", "'certs'"):
            self.assertIn(view, body,
                "loadSecPosture must thread a view click-through for " + view)

    def test_cert_summary_carries_expected_actual_form(self):
        body = _fn_body(_app_js(), "loadSecPosture")
        self.assertIn("valid+'/'+certs.length", body,
            "Cert summary must render valid count as valid/total so "
            "the operator instantly sees the contract")


class TestSmallWidgetDensification(unittest.TestCase):
    """Storage / Tdarr / Deploy widgets carry freshness chip + click-
    through. Pre-fix these were inert and undated."""

    def test_storage_widget_carries_fresh_chip_and_view(self):
        src = _app_js()
        # The widget loader builds with data-view="fleet" wrapper.
        idx = src.find("'w-storage-health'")
        self.assertGreater(idx, 0)
        # Slice forward to find the loader body.
        sub = src[idx:idx+3000]
        self.assertIn('data-view="fleet"', sub,
            "storage widget must click through to fleet view")
        self.assertIn("_freshChip", sub,
            "storage widget must render a freshness chip from payload age")
        self.assertIn("/'+d.pools.length", sub,
            "storage header must encode healthy/total pool count "
            "as expected/actual")

    def test_tdarr_widget_carries_fresh_chip_and_view(self):
        src = _app_js()
        idx = src.find("'w-tdarr'")
        self.assertGreater(idx, 0)
        sub = src[idx:idx+2000]
        self.assertIn('data-view="docker"', sub)
        self.assertIn("_freshChip", sub)

    def test_deploy_log_widget_carries_fresh_chip_without_dead_view(self):
        src = _app_js()
        idx = src.find("'w-deploy-log'")
        self.assertGreater(idx, 0)
        sub = src[idx:idx+2000]
        self.assertNotIn('data-view=', sub)
        self.assertIn("_freshChip", sub)
