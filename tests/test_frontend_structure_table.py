"""Declarative structural ownership for the shipped frontend shell.

C02 keeps related HTML, JavaScript, and CSS placement laws together without
turning the test runner into a second implementation of the product.  Each row
names one operator-visible contract and delegates to a small semantic checker.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Element:
    tag: str
    attrs: tuple[tuple[str, str], ...]
    ancestor_ids: tuple[str, ...]

    def attr(self, name: str) -> str | None:
        return dict(self.attrs).get(name)


class _SurfaceParser(HTMLParser):
    _VOID = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[Element] = []
        self._stack: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tuple((name, value or "") for name, value in attrs)
        ancestor_ids = tuple(value for _, value in self._stack if value)
        element = Element(tag, normalized, ancestor_ids)
        self.elements.append(element)
        if tag not in self._VOID:
            self._stack.append((tag, element.attr("id")))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                return


@dataclass(frozen=True)
class SurfaceSnapshot:
    html: str
    js: str
    css: str
    elements: tuple[Element, ...]

    @classmethod
    def load(cls) -> SurfaceSnapshot:
        html = (ROOT / "freq/data/web/app.html").read_text(encoding="utf-8")
        # Inspect both shipped owners after the pure helper extraction.
        js = "\n".join((ROOT / "freq/data/web/js" / name).read_text(encoding="utf-8")
                       for name in ("presentation.js", "app.js"))
        css = (ROOT / "freq/data/web/css/app.css").read_text(encoding="utf-8")
        parser = _SurfaceParser()
        parser.feed(html)
        return cls(html, js, css, tuple(parser.elements))


Checker = Callable[[unittest.TestCase, SurfaceSnapshot], None]


@dataclass(frozen=True)
class StructuralRow:
    id: str
    title: str
    sources: tuple[str, ...]
    checker: Checker


def _balanced_js_block(source: str, marker: str) -> str:
    if marker.startswith("function "):
        name = marker.removeprefix("function ")
        declaration = re.search(
            rf"(?<![A-Za-z0-9_$])function\s+{re.escape(name)}\s*\(",
            source,
        )
        if declaration is None:
            raise AssertionError(f"missing JavaScript function declaration: {name}")
        start = declaration.start()
    else:
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
            index = source.find("\n", index + 2)
            if index == -1:
                break
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
    raise AssertionError(f"unclosed JavaScript block: {marker}")


def _view_block(html: str, view: str) -> str:
    marker = f'id="{view}-view"'
    marker_at = html.index(marker)
    start = html.rfind("<div", 0, marker_at)
    depth = 0
    position = start
    while position < len(html):
        opening = html.find("<div", position + 1)
        closing = html.find("</div>", position + 1)
        if closing == -1:
            break
        if opening != -1 and opening < closing:
            depth += 1
            position = opening
        elif depth:
            depth -= 1
            position = closing
        else:
            return html[start : closing + len("</div>")]
    raise AssertionError(f"unclosed view block: {view}")


def _registry_views(js: str, group: str) -> list[str]:
    registry = js.split("var SUBNAV_GROUPS={", 1)[1].split("\n};", 1)[0]
    match = re.search(rf"\n  {re.escape(group)}:\[(.*?)\n  \]", registry, re.DOTALL)
    if not match:
        raise AssertionError(f"missing SUBNAV_GROUPS.{group}")
    return re.findall(r"\{view:'([^']+)'", match.group(1))


def _view_loader_bindings(js: str) -> tuple[list[str], dict[str, str]]:
    view_source = js.split("var VIEW_IDS=[", 1)[1].split("];", 1)[0]
    view_ids = re.findall(r"'([^']+)'", view_source)
    loader_source = js.split("var VIEW_LOADERS={", 1)[1].split("};", 1)[0]
    bindings: dict[str, str] = {}
    for quoted, bare, loader in re.findall(
        r"(?:'([^']+)'|([a-z][a-z0-9-]*)):function\(\)\{([A-Za-z_$][A-Za-z0-9_$]*)\(\)\}",
        loader_source,
    ):
        view = quoted or bare
        if view in bindings:
            raise AssertionError(f"duplicate VIEW_LOADERS binding: {view}")
        bindings[view] = loader
    return view_ids, bindings


def _elements_in(snapshot: SurfaceSnapshot, ancestor_id: str) -> list[Element]:
    return [element for element in snapshot.elements if ancestor_id in element.ancestor_ids]


def _check_login_form(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    forms = [item for item in snapshot.elements if item.tag == "form" and item.attr("id") == "login-form"]
    case.assertEqual(len(forms), 1, "login-form must be one real form")
    case.assertEqual(forms[0].attr("method"), "post")
    case.assertIsNotNone(forms[0].attr("action"))
    descendants = _elements_in(snapshot, "login-form")
    named = {(item.tag, item.attr("name")) for item in descendants}
    case.assertIn(("input", "username"), named)
    case.assertIn(("input", "password"), named)
    submits = [item for item in descendants if item.attr("id") == "login-submit-btn"]
    case.assertEqual(len(submits), 1)
    case.assertEqual(submits[0].tag, "button")
    case.assertEqual(submits[0].attr("type"), "submit")


def _check_login_binding(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    binding = _balanced_js_block(snapshot.js, "function registerLoginBindings")
    login = _balanced_js_block(snapshot.js, "function doLogin")
    for token in (
        "login-form",
        "preventDefault()",
        "doLogin()",
    ):
        case.assertIn(token, binding)
    case.assertEqual(binding.count("if(f&&!f._freqBound)"), 1)
    case.assertEqual(binding.count("addEventListener('submit'"), 1)
    case.assertEqual(binding.count("doLogin()"), 1)
    case.assertEqual(binding.count("f._freqBound=true;"), 1)
    case.assertNotIn("userEl.dispatchEvent(new Event('input'", login)
    case.assertNotIn("passEl.dispatchEvent(new Event('input'", login)


def _check_login_handoff(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    show_app = _balanced_js_block(snapshot.js, "function _showApp")
    promise_at = show_app.index("Promise.all([p1,p2,p3])")
    then_at = show_app.index(".then(function(){", promise_at)
    pointer_at = show_app.index("login.style.pointerEvents='none'", promise_at)
    timeout_at = show_app.index("setTimeout", promise_at)
    case.assertLess(then_at, pointer_at)
    case.assertLess(pointer_at, timeout_at)


def _check_assignment_location(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    device_at = snapshot.html.index("<h3>Device Assignment</h3>")
    mount_at = snapshot.html.index('id="device-admin-mount"')
    api_at = snapshot.html.index("<h3>API</h3>")
    assignment = snapshot.html[device_at:api_at]
    case.assertLess(device_at, mount_at)
    case.assertLess(mount_at, api_at)
    case.assertIn("Classify hosts and existing VMs", assignment)
    case.assertIn("out of contract", assignment)
    case.assertIn("mount.appendChild(sec)", snapshot.js)
    case.assertNotIn("insertAdjacentElement('afterend',sec)", snapshot.js)
    case.assertIn(".device-assignment-admin > .section-header { display: none; }", snapshot.css)


def _check_assignment_table(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    loader = _balanced_js_block(snapshot.js, "function _loadLabAssignments")
    group_assignment = _balanced_js_block(snapshot.js, "function _deviceAssignmentFromGroups")
    assignment_select = _balanced_js_block(snapshot.js, "function _deviceAssignmentSelect")
    assignment_save = _balanced_js_block(snapshot.js, "function saveDeviceAssignmentRow")
    options = snapshot.js.split("var DEVICE_ASSIGNMENT_OPTIONS=", 1)[1].split("];", 1)[0]
    for choice in ("{value:'prod',label:'PROD'}", "{value:'lab',label:'LAB'}", "{value:'template',label:'TEMP'}", "{value:'ooc',label:'OOC'}"):
        case.assertIn(choice, options)
    case.assertNotIn("sandbox", options.lower())
    case.assertEqual(loader.count("<table class=\"device-assignment-table\""), 1)
    for heading in ("Identity", "Kind", "Address", "Status", "Assignment"):
        case.assertIn(f"<th>{heading}</th>", loader)
    role_columns = (
        "(canEditAssignments?'<th>Host Properties</th><th>Management</th>"
        "<th>Permissions</th><th>Save</th>':'<th>Access</th>')"
    )
    case.assertIn(role_columns, loader)
    case.assertIn("_currentRole==='admin'||_currentRole==='protected'", loader)
    admin_fetch = re.compile(
        r"canEditAssignments\s*\?\s*_authFetch\(API\.ADMIN_BOUNDARIES\).*?"
        r":Promise\.resolve\(\{\}\)",
        re.DOTALL,
    )
    case.assertRegex(loader, admin_fetch)
    case.assertIn("if(!canEditAssignments){", loader)
    case.assertIn("device-assignment-readonly", loader)
    case.assertIn("An admin role is required to change assignment", loader)
    case.assertIn("ADMIN REQUIRED TO EDIT", loader)
    case.assertIn("saveDeviceAssignmentRow", loader)
    case.assertIn("if(!groupsText)return '';", group_assignment)
    case.assertEqual(loader.count("_deviceAssignmentFromGroups("), 2)
    case.assertIn("<option value=\"\" selected disabled>CHOOSE</option>", assignment_select)
    case.assertIn("data-initial=", assignment_select)
    case.assertIn("assignment?assignment.toUpperCase():'UNDECIDED'", loader)
    case.assertIn("if(assignment&&assignment!==initialAssignment)", assignment_save)
    case.assertNotIn("assignmentEl?assignmentEl.value:'prod'", assignment_save)


def _check_device_assignment(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    _check_assignment_location(case, snapshot)
    _check_assignment_table(case, snapshot)
    for legacy in (
        "device-admin-panel",
        "HOST PROPERTIES</h4>",
        "VM CATEGORIES</h4>",
        "PERMISSIONS</h4>",
        "VM CATEGORIES & PERMISSIONS",
        "VM CATEGORIES AND PERMISSIONS",
        "PERMISSION TIERS",
    ):
        case.assertNotIn(legacy, snapshot.js)
    case.assertIn(".device-assignment-table", snapshot.css)


def _check_cost_placement(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    settings = _view_block(snapshot.html, "settings")
    tools = _view_block(snapshot.html, "tools")
    case.assertNotIn("<h3>Fleet Costs</h3>", settings)
    case.assertNotIn("<h3>Cost Analysis</h3>", settings)
    case.assertLess(tools.index("<h3>Host Compare</h3>"), tools.index("<h3>Fleet Costs</h3>"))
    case.assertLess(tools.index("<h3>Fleet Costs</h3>"), tools.index("<h3>Cost Analysis</h3>"))
    tools_loader = _balanced_js_block(snapshot.js, "function loadToolsPage")
    settings_loader = _balanced_js_block(snapshot.js, "function loadSettingsPage")
    case.assertIn("loadCosts()", tools_loader)
    case.assertNotIn("loadCosts()", settings_loader)


def _check_subnav(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    expected = {
        "fleet": ["fleet", "network"],
        "security": ["security", "sec-hardening", "sec-access", "sec-compliance", "firewall", "certs", "vpn"],
        "system": ["tools", "playbooks", "chaos", "dns", "dr", "incidents", "metrics", "automation", "plugins"],
    }
    for group, views in expected.items():
        case.assertEqual(_registry_views(snapshot.js, group), views)
        for view in views:
            block = _view_block(snapshot.html, view)
            case.assertIn(f'data-subnav-group="{group}"', block)
            case.assertIn(f'data-subnav-active="{view}"', block)
            mount = re.search(r'<div class="sub-tabs"[^>]*data-subnav-group="[^"]+"[^>]*>(.*?)</div>', block, re.DOTALL)
            case.assertIsNotNone(mount, f"missing subnav mount for {view}")
            case.assertNotIn("<button", mount.group(1))
    renderer = _balanced_js_block(snapshot.js, "function _renderSubnavMount")
    case.assertIn("button.dataset.view=item.view", renderer)
    case.assertIn("item.view===active?' active-sub':''", renderer)
    case.assertIn("{view:'chaos',label:'Chaos',className:'c-red'}", snapshot.js)


def _check_network_identity(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    ids = [item.attr("id") for item in snapshot.elements if item.attr("id")]
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    case.assertFalse(duplicates, f"duplicate global IDs: {duplicates}")
    for legacy in ("netmon-out", "snmp-setup-section", "snmp-setup-stats", "snmp-setup-main"):
        case.assertNotIn(legacy, ids)
    case.assertIn("function _networkSurfaceRoot()", snapshot.js)
    case.assertIn("_networkSurfaceElement('netmon-out')", snapshot.js)
    case.assertNotIn("getElementById('netmon-out')", snapshot.js)


def _check_snmp_onboarding(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    for prefix in ("fleet", "network"):
        for suffix in ("section", "stats", "main"):
            case.assertIn(f'id="{prefix}-snmp-setup-{suffix}"', snapshot.html)
    for role in ("section", "stats", "main"):
        token = f'data-network-role="snmp-setup-{role}"'
        case.assertEqual(snapshot.html.count(token), 2)
    case.assertIn('data-action="snmpSetupProbe"', snapshot.html)


def _check_certificate_onboarding(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    html = _view_block(snapshot.html, "certs")
    js = snapshot.js[snapshot.js.index("function _certText") : snapshot.js.index("function loadDnsPage")]
    for token in ("Onboarding Choices", "Preview / Apply"):
        case.assertIn(token, html)
    for token in ("Dashboard HTTPS", "App Trust", "Adopt Existing SSL", "Provision Direct Target Certs"):
        case.assertIn(token, js)
    for token in ("Config path", "config_block", "[cert_management]", "PREVIEW BOOTSTRAP", "APPLY BOOTSTRAP"):
        case.assertNotIn(token, html + js)


def _check_guided_onboarding(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    _check_snmp_onboarding(case, snapshot)
    _check_certificate_onboarding(case, snapshot)


def _check_docker_subsurfaces(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    expected = ("all", "services", "media", "registry", "fleet-inv")
    buttons = {
        item.attr("data-arg"): item
        for item in snapshot.elements
        if item.tag == "button" and "docker-sub" in (item.attr("class") or "").split()
    }
    case.assertEqual(tuple(buttons), expected)
    for name, button in buttons.items():
        case.assertEqual(button.attr("data-dsub"), f"docker-{name}")
        case.assertEqual(button.attr("data-action"), "switchDockerSub")
    case.assertIn("active-view", (buttons["all"].attr("class") or "").split())
    for name in expected[1:]:
        case.assertNotIn("active-view", (buttons[name].attr("class") or "").split())

    for name in expected:
        panes = [item for item in snapshot.elements if item.attr("id") == f"docker-sub-{name}"]
        case.assertEqual(len(panes), 1, f"docker sub-surface {name} must exist exactly once")
        hidden = "d-none" in (panes[0].attr("class") or "").split()
        case.assertEqual(hidden, name != "all")

    switcher = _balanced_js_block(snapshot.js, "function switchDockerSub")
    case.assertIn("_dockerSub=sub", switcher)
    case.assertIn("['all','services','media','registry','fleet-inv']", switcher)
    case.assertIn(".docker-sub[data-dsub=\"docker-'+sub+'\"]", switcher)
    case.assertIn("if(sub==='services')loadServiceContainers()", switcher)
    case.assertIn("if(sub==='media'){loadMediaContainers();loadDownloads();loadStreams();}", switcher)
    case.assertIn("if(sub==='registry')loadContainerRegistry()", switcher)
    case.assertIn("if(sub==='fleet-inv')loadDockerFleet()", switcher)


def _check_shared_render_primitives(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    view_ids, bindings = _view_loader_bindings(snapshot.js)
    case.assertEqual(list(bindings), view_ids)
    case.assertEqual(len(bindings), 25)
    for view, loader in bindings.items():
        with case.subTest(view=view, loader=loader):
            case.assertTrue(
                _balanced_js_block(snapshot.js, f"function {loader}"),
                f"missing loader declaration for {view}: {loader}",
            )

    fetch = _balanced_js_block(snapshot.js, "function _fetchAndRender")
    for token in (
        "document.getElementById(statsId)",
        "<div class=\"skeleton h-40\"></div>",
        "_authFetch(url)",
        "return r.json()",
        "renderFn(d)",
        "Failed to load: ",
        "_esc(e.toString())",
    ):
        case.assertIn(token, fetch)

    cards = _balanced_js_block(snapshot.js, "function _statCards")
    for token in (
        "items.map(function(i)",
        "i.c?'color:var(--'+i.c+')':''",
        "'+i.v+'",
        "'+i.l+'",
        ".join('')",
    ):
        case.assertIn(token, cards)

    badge = _balanced_js_block(snapshot.js, "function _statusBadge")
    case.assertIn("(status||'unknown').toLowerCase()", badge)
    for token in (
        "s==='up'",
        "s==='down'",
        "s==='warning'",
        "'text-dim'",
        "_esc(s)",
    ):
        case.assertIn(token, badge)

    escape = _balanced_js_block(snapshot.js, "function _esc")
    replacements = (
        ".replace(/&/g,'&amp;')",
        ".replace(/</g,'&lt;')",
        ".replace(/>/g,'&gt;')",
        ".replace(/\"/g,'&quot;')",
        ".replace(/'/g,'&#39;')",
    )
    positions = [escape.index(replacement) for replacement in replacements]
    case.assertEqual(positions, sorted(positions), "escape order must protect ampersands first")

    write_result = _balanced_js_block(snapshot.js, "function _writeResultHtml")
    for token in (
        "_esc(String(label",
        "_esc(String(d.message",
        "_esc(String(d.error",
        "_esc(String(error",
        "_infraPre('OUTPUT',d.output)",
    ):
        case.assertIn(token, write_result)

    write_post = _balanced_js_block(snapshot.js, "function _writePost")
    case.assertEqual(write_post.count("o.innerHTML=_writeResultHtml("), 3)
    for unsafe in ("+label+", "+d.message+", "+(d.error", "+e+"):
        case.assertNotIn(unsafe, write_post)

    raw_output = _balanced_js_block(snapshot.js, "function _infraPre")
    case.assertIn("_esc(String(title", raw_output)
    case.assertIn("_esc(String(output", raw_output)
    case.assertNotIn("output.replace(/</g", raw_output)


def _check_lab_tool_save_contract(case: unittest.TestCase, snapshot: SurfaceSnapshot) -> None:
    save = _balanced_js_block(snapshot.js, "function ltSaveConfig")
    case.assertIn("return _authFetch(API.LAB_TOOL_SAVE,{method:'POST'", save)
    case.assertIn("headers:{'Content-Type':'application/json'}", save)
    case.assertIn("body:JSON.stringify({tool:toolId,host:host,key:key})", save)
    case.assertNotIn("LAB_TOOL_SAVE+'?", save)
    case.assertNotIn("encodeURIComponent(key)", save)
    case.assertIn("if(!r.ok)", save)
    case.assertIn("d.ok!==true", save)
    case.assertIn("Tool config save was not confirmed", save)


STRUCTURAL_ROWS = (
    StructuralRow("C02-01", "real login form", ("app.html",), _check_login_form),
    StructuralRow("C02-02", "single guarded login submit path", ("app.js",), _check_login_binding),
    StructuralRow("C02-03", "non-intercepting login handoff", ("app.js",), _check_login_handoff),
    StructuralRow("C02-04", "device assignment ownership", ("app.html", "app.js", "app.css"), _check_device_assignment),
    StructuralRow("C02-05", "system cost placement", ("app.html", "app.js"), _check_cost_placement),
    StructuralRow("C02-06", "canonical generated subnavigation", ("app.html", "app.js"), _check_subnav),
    StructuralRow("C02-07", "unique scoped network identities", ("app.html", "app.js"), _check_network_identity),
    StructuralRow("C02-08", "guided SNMP and certificate onboarding", ("app.html", "app.js"), _check_guided_onboarding),
    StructuralRow("C02-09", "canonical Docker sub-surfaces", ("app.html", "app.js"), _check_docker_subsurfaces),
    StructuralRow("C02-10", "canonical loaders and shared render primitives", ("app.js",), _check_shared_render_primitives),
    StructuralRow("C02-11", "lab tool save request contract", ("app.js",), _check_lab_tool_save_contract),
)
EXPECTED_ROW_IDS = tuple(f"C02-{number:02d}" for number in range(1, 12))

SNAPSHOT = SurfaceSnapshot.load()


class TestFrontendStructureTable(unittest.TestCase):
    def test_c02_frontend_structure_table(self) -> None:
        from tests.test_truenas_nfs_scope_ui_contract import (
            assert_truenas_nfs_scope_ui_contract,
        )

        self.assertEqual(tuple(row.id for row in STRUCTURAL_ROWS), EXPECTED_ROW_IDS)
        for row in STRUCTURAL_ROWS:
            with self.subTest(row=row.id, title=row.title, sources=row.sources):
                row.checker(self, SNAPSHOT)
        with self.subTest(row="E1-a/b", title="explicit TrueNAS NFS client scope"):
            assert_truenas_nfs_scope_ui_contract()


if __name__ == "__main__":
    unittest.main()
