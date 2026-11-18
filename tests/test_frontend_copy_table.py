"""Declarative ownership for factual operator-facing frontend copy.

C04 replaces fragmented literal-membership tests with seven bounded semantic
rows.  The checks stay inside the Python handler, named JavaScript functions
or registry entries, and the two shipped DOM nodes that actually own the copy.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Callable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CopySnapshot:
    css: str
    fleet: str
    html: str
    js: str

    @classmethod
    def load(cls) -> "CopySnapshot":
        return cls(
            css=(ROOT / "freq/data/web/css/app.css").read_text(encoding="utf-8"),
            fleet=(ROOT / "freq/api/fleet.py").read_text(encoding="utf-8"),
            html=(ROOT / "freq/data/web/app.html").read_text(encoding="utf-8"),
            js=(ROOT / "freq/data/web/js/app.js").read_text(encoding="utf-8"),
        )


def _python_function(source: str, name: str) -> str:
    marker = f"def {name}("
    start = source.index(marker)
    match = re.search(r"^def [A-Za-z_]\w*\(", source[start + len(marker) :], re.MULTILINE)
    return source[start:] if match is None else source[start : start + len(marker) + match.start()]


def _js_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    quote = ""
    escaped = False
    index = opening
    while index < len(source):
        char = source[index]
        pair = source[index : index + 2]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif pair == "//":
            newline = source.find("\n", index + 2)
            if newline == -1:
                break
            index = newline
        elif pair == "/*":
            index = source.index("*/", index + 2) + 1
        elif char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unclosed JavaScript function: {name}")


def _top_level_js_functions(source: str) -> tuple[str, ...]:
    """Parse the shipped column-zero grammar for top-level declarations."""
    return tuple(re.findall(r"^function ([A-Za-z_$][\w$]*)\(", source, re.MULTILINE))


class _IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for name, value in attrs:
            if name == "id" and value is not None:
                self.ids.append(value)


def _html_ids(source: str) -> tuple[str, ...]:
    parser = _IdCollector()
    parser.feed(source)
    parser.close()
    return tuple(parser.ids)


def _div_block(source: str, element_id: str) -> str:
    marker = f'id="{element_id}"'
    marker_at = source.index(marker)
    start = source.rfind("<div", 0, marker_at)
    depth = 0
    for token in re.finditer(r"<div\b|</div>", source[start:], re.IGNORECASE):
        if token.group(0).lower().startswith("<div"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return source[start : start + token.end()]
    raise AssertionError(f"unclosed div: {element_id}")


def _registry(source: str) -> str:
    start = source.index("var WIDGET_REGISTRY=[")
    end = source.index("var QUICK_START_WIDGETS=", start)
    return source[start:end]


def _registry_entry(source: str, widget_id: str) -> str:
    registry = _registry(source)
    marker = f"{{id:'{widget_id}'"
    start = registry.index(marker)
    next_entry = registry.find("\n  {id:'", start + len(marker))
    return registry[start:] if next_entry == -1 else registry[start:next_entry]


def _cert_slice(source: str) -> str:
    start = source.index("function _certText")
    end = source.index("function loadDnsPage", start)
    return source[start:end]


def _branch(source: str, marker: str, before: int = 180, after: int = 180) -> str:
    position = source.index(marker)
    return source[max(0, position - before) : position + len(marker) + after]


Checker = Callable[[unittest.TestCase, CopySnapshot], None]
Mutator = Callable[[CopySnapshot], CopySnapshot]


@dataclass(frozen=True)
class CopyRow:
    id: str
    title: str
    predecessor_count: int
    checker: Checker


@dataclass(frozen=True)
class ReviewMutation:
    title: str
    row_id: str
    mutator: Mutator


def _check_identity(case: unittest.TestCase, snapshot: CopySnapshot) -> None:
    handler = _python_function(snapshot.fleet, "handle_info")
    case.assertIn(
        'default_header = f"{cfg.brand} \\u00b7 {cluster}" if cluster else f"{cfg.brand} \\u00b7 operator console"',
        handler,
    )
    case.assertIn('default_subtitle = f"{host_count} hosts \\u00b7 {node_count} pve nodes"', handler)
    case.assertIn('if pack_header and pack_header != "PVE FREQ Dashboard":', handler)
    case.assertIn("dashboard_header = pack_header", handler)
    case.assertIn("if pack_subtitle and pack_subtitle != cfg.brand:", handler)
    case.assertIn("subtitle = pack_subtitle", handler)
    case.assertIn('"dashboard_header": dashboard_header', handler)
    case.assertIn('"subtitle": subtitle', handler)

    login = _div_block(snapshot.html, "login-overlay")
    case.assertEqual(login.count('<div class="login-tagline">operator console</div>'), 1)
    case.assertNotIn("FLEET DASHBOARD", login)
    case.assertNotIn("OPERATOR CONSOLE", login)

    home = _js_function(snapshot.js, "loadHome")
    case.assertIn("document.title=d.dashboard_header||d.brand||'PVE FREQ'", home)
    case.assertIn("if(d.dashboard_header)", home)
    case.assertIn("nv.textContent='V'+d.version+' \\u00b7 '+d.dashboard_header.replace", home)
    case.assertNotIn("+' Dashboard'", home)


def _check_operational_home(case: unittest.TestCase, snapshot: CopySnapshot) -> None:
    empty = _div_block(snapshot.html, "home-empty")
    case.assertIn("no widgets configured", empty)
    case.assertIn("QUICK START loads the default operator set", empty)
    case.assertIn("LAYOUT selects", empty)
    for phrase in (
        "Your Dashboard",
        "ready-made",
        "ready made",
        "hit Quick",
        "Simply ",
        "just click",
        "easy",
        "easily",
    ):
        case.assertNotIn(phrase, empty)

    show_app = _js_function(snapshot.js, "_showApp")
    case.assertIn("operator console", show_app)
    case.assertNotIn("FLEET DASHBOARD", show_app)


def _check_empty_evidence(case: unittest.TestCase, snapshot: CopySnapshot) -> None:
    entries = {
        "w-docker-containers": ("0 containers", ("No containers.", "No containers found.")),
        "w-vlan-topology": ("0 VLANs configured", ("No VLANs configured",)),
        "w-ntp-status": ("NTP probe returned 0 hosts", ("No NTP data",)),
        "w-resource-heatmap": ("0 hosts in heatmap", ("No data",)),
        "w-storage-health": ("0 storage pools detected", ("No storage pools detected",)),
        "w-deploy-log": ("0 deploys recorded", ("No deploy history",)),
    }
    for widget_id, (required, forbidden) in entries.items():
        branch = _registry_entry(snapshot.js, widget_id)
        case.assertIn(required, branch, widget_id)
        for phrase in forbidden:
            case.assertNotIn(phrase, branch, widget_id)

    functions = {
        "loadUsers": ("0 users in users.conf", "No users registered."),
        "renderVaultCredentials": ("0 vault entries · 0 API keys in vault", "Vault is empty."),
        "loadVMs": ("0 VMs on cluster", "No VMs found on cluster."),
        "loadJournal": ("0 journal entries", "No journal entries yet."),
        "loadLabTools": ("0 lab tools visible", "No lab tools visible."),
        "_loadActivityFeed": ("0 recent events", "No recent activity"),
        "_loadMonitorsWidget": ("0 monitors configured", "No monitors configured"),
    }
    for function_name, (required, forbidden) in functions.items():
        body = _js_function(snapshot.js, function_name)
        case.assertIn(required, body, function_name)
        case.assertNotIn(forbidden, body, function_name)

    case.assertIn("Create a user above.", _js_function(snapshot.js, "loadUsers"))
    case.assertNotIn("loadAgents", _top_level_js_functions(snapshot.js))
    app_ids = _html_ids(snapshot.html)
    case.assertNotIn("agent-list", app_ids)
    case.assertNotIn("agents-view", app_ids)

    for function_name, phrase in (
        ("loadUsers", "0 users in users.conf"),
        ("renderVaultCredentials", "0 vault entries"),
        ("renderVaultCredentials", "0 API keys in vault"),
        ("loadVMs", "0 VMs on cluster"),
        ("loadJournal", "0 journal entries"),
    ):
        body = _js_function(snapshot.js, function_name)
        window = _branch(body, phrase, before=220, after=80)
        case.assertNotIn("es-icon", window, function_name)


def _check_collection_failure(case: unittest.TestCase, snapshot: CopySnapshot) -> None:
    truth_label = _js_function(snapshot.js, "_probeTruthLabel")
    case.assertIn("if(!truth)return 'PROBE FAILED'", truth_label)
    case.assertIn("if(truth.state==='warming')return 'CACHE WARMING'", truth_label)
    case.assertIn("return 'PROBE FAILED'", truth_label)

    stream = _js_function(snapshot.js, "_renderStreamStatus")
    case.assertIn("var map={live:'LIVE',cached:'CACHED',dead:'STREAM DEAD'}", stream)
    case.assertIn("var lbl=map[s]||'CACHED'", stream)

    warming = _js_function(snapshot.js, "_enrichInfraCards")
    warming_branch = warming[
        warming.index("if(d.warming)") : warming.index("setTimeout", warming.index("if(d.warming)"))
    ]
    case.assertIn("ageEl.textContent='CACHE WARMING'", warming_branch)
    case.assertIn("ageEl.style.color='var(--yellow)'", warming_branch)

    probe_branches = {
        "w-ntp-status": "NTP probe failed \\u2014 check /api/fleet/ntp",
        "w-resource-heatmap": "heatmap probe failed \\u2014 check /api/fleet/heatmap",
        "w-stale-snapshots": "snapshot probe failed \\u2014 check /api/snapshots/stale",
        "w-storage-health": "storage probe failed \\u2014 check /api/storage/health",
    }
    for widget_id, phrase in probe_branches.items():
        case.assertIn(phrase, _registry_entry(snapshot.js, widget_id), widget_id)
    case.assertIn(
        "activity probe failed \\u2014 check /api/activity",
        _js_function(snapshot.js, "_loadActivityFeed"),
    )
    case.assertIn(
        "monitor probe failed \\u2014 check /api/monitors",
        _js_function(snapshot.js, "_loadMonitorsWidget"),
    )

    lxc = _js_function(snapshot.js, "loadLxcContainers")
    case.assertIn("_authFetch(API.CT_LIST,{silent:true}", lxc)
    case.assertIn("if(!r.ok){if(section)section.style.display='none';return null;}", lxc)


def _check_neutral_truth(case: unittest.TestCase, snapshot: CopySnapshot) -> None:
    truth_label = _js_function(snapshot.js, "_probeTruthLabel")
    stream = _js_function(snapshot.js, "_renderStreamStatus")
    for phrase in ("'PROBE ERROR'", '"PROBE ERROR"', "'WARMING'", '"WARMING"'):
        case.assertNotIn(phrase, truth_label)
    case.assertNotIn("'SSE'", stream)
    case.assertNotIn("'POLL'", stream)

    capacity = _js_function(snapshot.js, "loadCapRecommend")
    case.assertIn("0 recommendations at current thresholds", capacity)
    case.assertNotIn("Fleet is balanced", capacity)
    case.assertNotIn("No optimization recommendations.", capacity)
    capacity_empty = _branch(capacity, "0 recommendations at current thresholds")
    case.assertIn("color:var(--text-dim)", capacity_empty)
    case.assertNotIn("color:var(--green)", capacity_empty)

    migration = _js_function(snapshot.js, "loadMigratePlan")
    case.assertIn("0 migration candidates at current mem thresholds", migration)
    case.assertNotIn("Fleet is balanced", migration)
    migration_empty = _branch(migration, "0 migration candidates at current mem thresholds")
    case.assertIn("color:var(--text-dim)", migration_empty)
    case.assertNotIn("color:var(--green)", migration_empty)

    snapshots = _registry_entry(snapshot.js, "w-stale-snapshots")
    case.assertIn("0 snapshots older than 30d", snapshots)
    case.assertNotIn("No stale snapshots", snapshots)
    case.assertNotIn("✅", _branch(snapshots, "0 snapshots older than 30d"))
    snapshot_empty = _branch(snapshots, "0 snapshots older than 30d")
    case.assertIn("color:var(--text-dim)", snapshot_empty)
    case.assertNotIn("color:var(--green)", snapshot_empty)


def _check_actionable_results(case: unittest.TestCase, snapshot: CopySnapshot) -> None:
    tdarr = _registry_entry(snapshot.js, "w-tdarr")
    case.assertIn("tdarr not installed", tdarr)
    case.assertNotIn("Tdarr not detected", tdarr)
    case.assertIn("tdarr '+(statusOk?'up':'down')", tdarr)
    case.assertIn("_freshChip(_ageFromPayload(d))", tdarr)
    case.assertNotIn("✅", tdarr)

    quick_start = _js_function(snapshot.js, "quickStartHome")
    case.assertIn("QUICK_START_WIDGETS.length+' widgets loaded'", quick_start)
    case.assertNotIn("Quick Start dashboard loaded", quick_start)

    certs = _cert_slice(snapshot.js)
    for phrase in (
        "served certificate truth",
        "dashboard_https",
        "trusted_proxy",
        "This is separate from certificate serving truth.",
        "SETUP NEEDED",
        "Setup gap",
        "No DNS preview yet",
        "No certificate inventory yet",
        "Base domain is needed before direct certificate provisioning.",
    ):
        case.assertIn(phrase, certs)
    for phrase in (
        "No cert deploy targets configured or inferred yet",
        "No DNS records planned yet",
        "No certificate inventory data yet",
        "Configured</span>",
    ):
        case.assertNotIn(phrase, certs)

    offline = _js_function(snapshot.js, "_ltGenerateHTML")
    case.assertIn(">STATION OFFLINE</span>", offline)
    case.assertIn("font-family:\\'Courier New\\',monospace", offline)
    case.assertIn("t.offlineHint||'Enter the IP and API key above to connect.'", offline)

def _check_calm_shell_and_state_vocabulary(case: unittest.TestCase, snapshot: CopySnapshot) -> None:
    """Keep first-load language deterministic and operationally distinct."""
    for phrase in ("var quotes=", "function rq(", "home-quote-footer", "var taglines="):
        case.assertNotIn(phrase, snapshot.js)
    case.assertIn("var _viewLabels={", snapshot.js)

    for phrase in (
        "All systems reporting",
        "Fleet health summary",
        "Container status",
        "Operational status",
        "Current state",
        "v3.0.0",
        "INITIALIZING",
        "FLEET ONLINE",
        "MEDIA STACK",
        "Welcome,",
        "\\u2588\\u2588\\u2588",
    ):
        case.assertNotIn(phrase, snapshot.js)

    for phrase in ("home-quote-footer", "MEDIA STACK", "██████╗", "╚══════╝", 'id="home-subtitle"'):
        case.assertNotIn(phrase, snapshot.html)

    home = snapshot.html.split('id="dashboard-root"', 1)[1].split('<!-- close home-view -->', 1)[0]
    before_toolbar = home.split("<!-- Toolbar -->", 1)[0]
    case.assertNotIn("<!-- Hero -->", home)
    case.assertNotIn("PVE FREQ", before_toolbar)

    favicon = snapshot.html[:2000]
    case.assertNotIn("linearGradient", favicon)
    case.assertNotIn("9B4FDE", favicon)

    login = _div_block(snapshot.html, "login-overlay")
    case.assertNotIn("background:var(--purple)", login)

    css_header = snapshot.css[:300]
    case.assertNotIn("v3.0.0", css_header)
    case.assertNotIn("MISSION CONTROL", css_header)
    case.assertNotIn("logoBreath", snapshot.css)
    case.assertNotIn("ASCII Logo", snapshot.css)
    case.assertNotIn("Dark cockpit", snapshot.css)
    case.assertNotIn("cockpit alerts", snapshot.css.lower())
    tagline_rule = next(
        line for line in snapshot.css.splitlines() if ".mn-header .tagline" in line and "{" in line
    )
    case.assertNotIn("italic", tagline_rule)

    badge = _js_function(snapshot.js, "badge")
    for mapping in (
        "unreachable:'unreachable'",
        "auth_failed:'warn'",
        "stale:'warn'",
        "probe_error:'warn'",
    ):
        case.assertIn(mapping, badge)


COPY_ROWS = (
    CopyRow("C04-01", "factual product and cluster identity", 12, _check_identity),
    CopyRow("C04-02", "operational login and home copy", 8, _check_operational_home),
    CopyRow("C04-03", "explicit empty-state evidence", 20, _check_empty_evidence),
    CopyRow("C04-04", "collection and failure presentation", 13, _check_collection_failure),
    CopyRow("C04-05", "neutral non-green state truth", 13, _check_neutral_truth),
    CopyRow("C04-06", "actionable result and offline copy", 10, _check_actionable_results),
    CopyRow("C04-07", "calm shell and distinct state vocabulary", 18, _check_calm_shell_and_state_vocabulary),
)


def _mutate(
    snapshot: CopySnapshot,
    field: str,
    old: str,
    new: str,
    *,
    anchor: str = "",
) -> CopySnapshot:
    source = getattr(snapshot, field)
    start = source.index(anchor) if anchor else 0
    position = source.index(old, start)
    changed = source[:position] + new + source[position + len(old) :]
    return replace(snapshot, **{field: changed})


def _restore_legacy_agents_surface(snapshot: CopySnapshot) -> CopySnapshot:
    with_function = _mutate(
        snapshot,
        "js",
        "function loadUsers()",
        "function loadAgents(){document.getElementById('agent-list').innerHTML="
        "'<p>No agents registered.</p>';}\nfunction loadUsers()",
    )
    return _mutate(
        with_function,
        "html",
        '<div id="home-empty">',
        '<div id="agents-view"><div id="agent-list"></div></div>\n<div id="home-empty">',
    )


REVIEW_MUTATIONS = (
    ReviewMutation(
        "cluster fallback",
        "C04-01",
        lambda s: _mutate(
            s, "fleet", 'f"{cfg.brand} \\u00b7 operator console"', 'f"{cfg.brand} Dashboard"', anchor="def handle_info("
        ),
    ),
    ReviewMutation(
        "factual subtitle",
        "C04-01",
        lambda s: _mutate(s, "fleet", "{host_count} hosts", "hosts ready", anchor="def handle_info("),
    ),
    ReviewMutation(
        "generic pack rejection",
        "C04-01",
        lambda s: _mutate(s, "fleet", 'pack_header != "PVE FREQ Dashboard"', "True", anchor="def handle_info("),
    ),
    ReviewMutation(
        "title destination",
        "C04-01",
        lambda s: _mutate(
            s, "js", "document.title=d.dashboard_header", "document.title=d.brand", anchor="function loadHome("
        ),
    ),
    ReviewMutation(
        "cluster nav destination",
        "C04-01",
        lambda s: _mutate(
            s,
            "js",
            "nv.textContent='V'+d.version+' \\u00b7 '+d.dashboard_header.replace",
            "document.title='V'+d.version+' \\u00b7 '+d.dashboard_header.replace",
            anchor="function loadHome(",
        ),
    ),
    ReviewMutation(
        "login identity",
        "C04-01",
        lambda s: _mutate(s, "html", "operator console", "FLEET DASHBOARD", anchor='id="login-overlay"'),
    ),
    ReviewMutation(
        "home fact",
        "C04-02",
        lambda s: _mutate(s, "html", "no widgets configured", "Your Dashboard is Empty", anchor='id="home-empty"'),
    ),
    ReviewMutation(
        "quick-start action",
        "C04-02",
        lambda s: _mutate(s, "html", "QUICK START", "EASY START", anchor='id="home-empty"'),
    ),
    ReviewMutation(
        "layout action",
        "C04-02",
        lambda s: _mutate(s, "html", "LAYOUT selects", "A ready-made view selects", anchor='id="home-empty"'),
    ),
    ReviewMutation(
        "loading identity",
        "C04-02",
        lambda s: _mutate(s, "js", "operator console", "FLEET DASHBOARD", anchor="function _showApp("),
    ),
    ReviewMutation(
        "explicit empty count",
        "C04-03",
        lambda s: _mutate(s, "js", "0 containers", "No containers.", anchor="{id:'w-docker-containers'"),
    ),
    ReviewMutation(
        "empty action", "C04-03", lambda s: _mutate(s, "js", "Create a user above.", "", anchor="function loadUsers(")
    ),
    ReviewMutation(
        "old empty copy",
        "C04-03",
        lambda s: _mutate(s, "js", "0 journal entries", "No journal entries yet.", anchor="function loadJournal("),
    ),
    ReviewMutation(
        "decorative empty glyph",
        "C04-03",
        lambda s: _mutate(
            s, "js", "0 VMs on cluster", '<span class="es-icon">✅</span>0 VMs on cluster', anchor="function loadVMs("
        ),
    ),
    ReviewMutation("retired agents surface", "C04-03", _restore_legacy_agents_surface),
    ReviewMutation(
        "heatmap old empty copy",
        "C04-03",
        lambda s: _mutate(s, "js", "0 hosts in heatmap", "No data", anchor="{id:'w-resource-heatmap'"),
    ),
    ReviewMutation(
        "probe failure label",
        "C04-04",
        lambda s: _mutate(s, "js", "PROBE FAILED", "REFRESH FAILED", anchor="function _probeTruthLabel("),
    ),
    ReviewMutation(
        "warming label",
        "C04-04",
        lambda s: _mutate(s, "js", "CACHE WARMING", "CACHE PREPARING", anchor="function _probeTruthLabel("),
    ),
    ReviewMutation(
        "live stream label",
        "C04-04",
        lambda s: _mutate(s, "js", "live:'LIVE'", "live:'CURRENT'", anchor="function _renderStreamStatus("),
    ),
    ReviewMutation(
        "cached stream label",
        "C04-04",
        lambda s: _mutate(s, "js", "cached:'CACHED'", "cached:'FALLBACK'", anchor="function _renderStreamStatus("),
    ),
    ReviewMutation(
        "warming destination",
        "C04-04",
        lambda s: _mutate(
            s,
            "js",
            "ageEl.textContent='CACHE WARMING'",
            "console.log('CACHE WARMING')",
            anchor="function _enrichInfraCards(",
        ),
    ),
    ReviewMutation(
        "probe endpoint guidance",
        "C04-04",
        lambda s: _mutate(
            s,
            "js",
            "storage probe failed \\u2014 check /api/storage/health",
            "storage probe failed \\u2014 check /api/unknown",
            anchor="{id:'w-storage-health'",
        ),
    ),
    ReviewMutation(
        "silent containment",
        "C04-04",
        lambda s: _mutate(s, "js", "{silent:true}", "{}", anchor="function loadLxcContainers("),
    ),
    ReviewMutation(
        "non-ok containment",
        "C04-04",
        lambda s: _mutate(s, "js", "if(!r.ok)", "if(false)", anchor="function loadLxcContainers("),
    ),
    ReviewMutation(
        "transport jargon",
        "C04-05",
        lambda s: _mutate(s, "js", "var cls=", "var forbidden='POLL';var cls=", anchor="function _renderStreamStatus("),
    ),
    ReviewMutation(
        "capacity fact",
        "C04-05",
        lambda s: _mutate(
            s, "js", "0 recommendations at current thresholds", "Fleet is balanced", anchor="function loadCapRecommend("
        ),
    ),
    ReviewMutation(
        "capacity green theater",
        "C04-05",
        lambda s: _mutate(
            s,
            "js",
            'style="color:var(--text-dim);font-size:11px">0 recommendations at current thresholds',
            'style="color:var(--green);font-size:11px">0 recommendations at current thresholds',
            anchor="function loadCapRecommend(",
        ),
    ),
    ReviewMutation(
        "migration threshold",
        "C04-05",
        lambda s: _mutate(
            s,
            "js",
            "0 migration candidates at current mem thresholds",
            "No optimization recommendations.",
            anchor="function loadMigratePlan(",
        ),
    ),
    ReviewMutation(
        "migration green theater",
        "C04-05",
        lambda s: _mutate(
            s,
            "js",
            'style="color:var(--text-dim);margin-top:12px;font-size:11px">0 migration candidates at current mem thresholds',
            'style="color:var(--green);margin-top:12px;font-size:11px">0 migration candidates at current mem thresholds',
            anchor="function loadMigratePlan(",
        ),
    ),
    ReviewMutation(
        "snapshot fact",
        "C04-05",
        lambda s: _mutate(
            s, "js", "0 snapshots older than 30d", "✅ No stale snapshots", anchor="{id:'w-stale-snapshots'"
        ),
    ),
    ReviewMutation(
        "snapshot green theater",
        "C04-05",
        lambda s: _mutate(s, "js", "color:var(--text-dim)", "color:var(--green)", anchor="{id:'w-stale-snapshots'"),
    ),
    ReviewMutation(
        "tdarr not-installed copy",
        "C04-06",
        lambda s: _mutate(s, "js", "tdarr not installed", "Tdarr not detected", anchor="{id:'w-tdarr'"),
    ),
    ReviewMutation(
        "tdarr lowercase result",
        "C04-06",
        lambda s: _mutate(
            s, "js", "tdarr '+(statusOk?'up':'down')", "Tdarr '+(statusOk?'Up':'Down')", anchor="{id:'w-tdarr'"
        ),
    ),
    ReviewMutation(
        "tdarr decorative checkmark",
        "C04-06",
        lambda s: _mutate(
            s, "js", "tdarr '+(statusOk?'up':'down')", "✅ tdarr '+(statusOk?'up':'down')", anchor="{id:'w-tdarr'"
        ),
    ),
    ReviewMutation(
        "tdarr freshness",
        "C04-06",
        lambda s: _mutate(s, "js", "_freshChip(_ageFromPayload(d))", "''", anchor="{id:'w-tdarr'"),
    ),
    ReviewMutation(
        "quick-start result",
        "C04-06",
        lambda s: _mutate(
            s,
            "js",
            "QUICK_START_WIDGETS.length+' widgets loaded'",
            "'Quick Start dashboard loaded'",
            anchor="function quickStartHome(",
        ),
    ),
    ReviewMutation(
        "certificate truth split",
        "C04-06",
        lambda s: _mutate(
            s, "js", "This is separate from certificate serving truth.", "Configured", anchor="function _certText"
        ),
    ),
    ReviewMutation(
        "certificate actionable gap",
        "C04-06",
        lambda s: _mutate(s, "js", "SETUP NEEDED", "Configured", anchor="function _certText"),
    ),
    ReviewMutation(
        "offline status",
        "C04-06",
        lambda s: _mutate(s, "js", ">STATION OFFLINE</span>", ">OFFLINE</span>", anchor="function _ltGenerateHTML("),
    ),
    ReviewMutation(
        "offline action hint",
        "C04-06",
        lambda s: _mutate(s, "js", "t.offlineHint||", "''||", anchor="function _ltGenerateHTML("),
    ),
    ReviewMutation(
        "quote roulette",
        "C04-07",
        lambda s: replace(s, js=s.js + "\nfunction rq(){return 'legacy';}\n"),
    ),
    ReviewMutation(
        "collapsed unreachable badge",
        "C04-07",
        lambda s: _mutate(
            s,
            "js",
            "unreachable:'unreachable'",
            "unreachable:'down'",
            anchor="function badge(s)",
        ),
    ),
)


SNAPSHOT = CopySnapshot.load()


class TestFrontendCopyTable(unittest.TestCase):
    def test_c04_factual_copy_table_and_review_mutants(self) -> None:
        self.assertEqual(tuple(row.id for row in COPY_ROWS), tuple(f"C04-{n:02d}" for n in range(1, 8)))
        self.assertEqual(sum(row.predecessor_count for row in COPY_ROWS), 94)
        for row in COPY_ROWS:
            with self.subTest(row=row.id, title=row.title):
                row.checker(self, SNAPSHOT)

        for mutation in REVIEW_MUTATIONS:
            mutated = mutation.mutator(SNAPSHOT)
            failures: list[str] = []
            for row in COPY_ROWS:
                try:
                    row.checker(self, mutated)
                except AssertionError:
                    failures.append(row.id)
            with self.subTest(mutation=mutation.title):
                self.assertEqual(failures, [mutation.row_id])


if __name__ == "__main__":
    unittest.main()
