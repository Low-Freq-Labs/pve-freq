"""Declarative ownership for the shipped dense operations layout.

C05 replaces fragmented string-membership tests with eight semantic rows.
Each review mutation is exact-anchored and must fail only the row that owns
the changed behavior.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Callable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AH_CLASSES = (
    "term-shell-col",
    "term-shell-title-row",
    "term-shell-btn-row",
    "term-shell-tag",
    "term-shell-close",
    "search-overlay-card",
    "search-overlay-input-row",
    "search-overlay-input",
    "search-overlay-footer",
    "shortcuts-card",
    "shortcuts-heading",
    "shortcuts-grid",
    "destructive-banner",
    "view-toolbar",
    "view-toolbar-row",
)
Q_CLASSES = ("pve-freq-wordmark", "nav-ver-label", "nav-divider", "header-time-label")
FORBIDDEN_INLINE = (
    'style="display:flex;flex-direction:column;height:100%;max-width:1400px;margin:0 auto"',
    'style="color:var(--green);font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;font-family:var(--font-ui)"',
    'style="font-size:9px;padding:2px 8px;color:var(--red)"',
    'style="max-width:560px;margin:0 auto;background:var(--bg);border:1px solid var(--border);border-radius:12px;overflow:hidden"',
    'style="padding:12px 16px;border-bottom:1px solid var(--border)"',
    'style="width:100%;background:transparent;border:none;outline:none;color:var(--text);font-size:16px;font-family:var(--font-ui)"',
    'style="padding:8px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);display:flex;gap:16px"',
    'style="max-width:400px;margin:0 auto;background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:24px"',
    'style="margin:0 0 16px;color:var(--purple-light)"',
    'style="display:grid;grid-template-columns:auto 1fr;gap:8px 16px;font-size:13px"',
    'style="background:rgba(255,60,60,0.08);border:1px solid rgba(255,60,60,0.3);border-radius:6px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:var(--text-dim)"',
    'style="border-bottom:1px solid var(--border);padding:6px 0;margin-bottom:12px"',
    'style="display:flex;gap:4px;align-items:center;min-height:32px;flex-wrap:wrap"',
)


class _ClassCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.classes: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for name, value in attrs:
            if name == "class" and value:
                self.classes.extend(value.split())


@dataclass(frozen=True)
class LayoutSnapshot:
    html: str
    css: str
    js: str
    classes: tuple[str, ...]

    @classmethod
    def load(cls) -> LayoutSnapshot:
        html = (ROOT / "freq/data/web/app.html").read_text(encoding="utf-8")
        parser = _ClassCollector()
        parser.feed(html)
        parser.close()
        return cls(
            html=html,
            css=(ROOT / "freq/data/web/css/app.css").read_text(encoding="utf-8"),
            js=(ROOT / "freq/data/web/js/app.js").read_text(encoding="utf-8"),
            classes=tuple(parser.classes),
        )


def _balanced_block(source: str, marker: str) -> str:
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
        elif pair == "/*":
            index = source.index("*/", index + 2) + 1
        elif pair == "//":
            newline = source.find("\n", index + 2)
            if newline == -1:
                break
            index = newline
        elif char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unclosed block: {marker}")


def _js_function(source: str, name: str) -> str:
    return _balanced_block(source, f"function {name}(")


def _rule_bodies(css: str, selector: str, *, base_only: bool = True) -> tuple[str, ...]:
    media_spans = tuple(
        (match.start(), match.start() + len(_balanced_block(css[match.start() :], "@media")))
        for match in re.finditer(r"(?m)^@media\s*\(", css)
    )
    pattern = re.compile(rf"(?m)^\s*{re.escape(selector)}\s*\{{")
    bodies: list[str] = []
    for match in pattern.finditer(css):
        if base_only and any(start <= match.start() < end for start, end in media_spans):
            continue
        block = _balanced_block(css[match.start() :], selector)
        bodies.append(block[block.index("{") + 1 : -1])
    return tuple(bodies)


def _one_rule(css: str, selector: str) -> str:
    bodies = _rule_bodies(css, selector)
    if len(bodies) != 1:
        raise AssertionError(f"expected one base rule for {selector}, got {len(bodies)}")
    return bodies[0]


def _property(rule: str, name: str) -> str:
    match = re.search(rf"(?:^|;)\s*{re.escape(name)}\s*:\s*([^;]+)", rule)
    if not match:
        raise AssertionError(f"missing {name}")
    return match.group(1).strip()


def _padding(rule: str) -> tuple[int, int]:
    values = [int(value) for value in re.findall(r"(\d+)px", _property(rule, "padding"))]
    if not values:
        raise AssertionError("padding must use pixel values")
    return values[0], values[1] if len(values) > 1 else values[0]


def _small_margin(case: unittest.TestCase, rule: str, maximum: int) -> None:
    value = _property(rule, "margin-bottom")
    if value.endswith("px"):
        case.assertLessEqual(int(value.removesuffix("px")), maximum)
    else:
        case.assertRegex(value, r"var\(--gap-(?:xs|sm)\)")


def _selector_group(css: str, selectors: tuple[str, ...]) -> str:
    joined = r"\s*,\s*".join(re.escape(selector) for selector in selectors)
    matches = list(re.finditer(rf"(?m)^\s*{joined}\s*\{{", css))
    if len(matches) != 1:
        raise AssertionError(f"expected one selector group {selectors}, got {len(matches)}")
    block = _balanced_block(css[matches[0].start() :], selectors[0])
    return block[block.index("{") + 1 : -1]


def _media_blocks(css: str, width: int) -> tuple[str, ...]:
    pattern = re.compile(rf"(?m)^@media\s*\(max-width:\s*{width}px\)\s*\{{")
    return tuple(_balanced_block(css[match.start() :], "@media") for match in pattern.finditer(css))


def _check_semantic_composition(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    ah_begin = "20260413AH SEMANTIC COMPOSITION CLASSES"
    ah_end = "20260413AH-semantic-block-end"
    q_begin = "20260413Q-id-rules-begin"
    q_end = "20260413Q-id-rules-end"
    for marker in (ah_begin, ah_end, q_begin, q_end):
        case.assertIn(marker, snapshot.css)
    case.assertLess(snapshot.css.index(q_begin), snapshot.css.index(q_end))
    case.assertLess(snapshot.css.index(q_end), snapshot.css.index(ah_begin))
    case.assertLess(snapshot.css.index(ah_begin), snapshot.css.index(ah_end))
    ah = snapshot.css[snapshot.css.index(ah_begin) : snapshot.css.index(ah_end)]
    q = snapshot.css[snapshot.css.index(q_begin) : snapshot.css.index(q_end)]
    for name in AH_CLASSES:
        case.assertEqual(len(re.findall(rf"(?m)^\.{re.escape(name)}\s*\{{", ah)), 1, name)
        case.assertIn(name, snapshot.classes, name)
    for fingerprint in FORBIDDEN_INLINE:
        case.assertNotIn(fingerprint, snapshot.html)
    for name in Q_CLASSES:
        case.assertEqual(len(re.findall(rf"(?m)^\.{re.escape(name)}\s*\{{", q)), 1, name)
        case.assertIn(name, snapshot.classes, name)


def _check_base_shell(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    heights = []
    for rule in _rule_bodies(snapshot.css, "body"):
        match = re.search(r"(?:^|;)\s*line-height\s*:\s*([\d.]+)", rule)
        if match:
            heights.append(float(match.group(1)))
    case.assertTrue(heights)
    case.assertLessEqual(max(heights), 1.55)
    case.assertLessEqual(_padding(_one_rule(snapshot.css, ".mn-header"))[0], 8)
    case.assertLessEqual(_padding(_one_rule(snapshot.css, ".mn-header"))[1], 28)
    case.assertLessEqual(_padding(_one_rule(snapshot.css, ".mn-body"))[0], 16)
    case.assertLessEqual(_padding(_one_rule(snapshot.css, ".mn-body"))[1], 32)


def _check_operational_blocks(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    _small_margin(case, _one_rule(snapshot.css, ".stats"), 12)
    y, x = _padding(_one_rule(snapshot.css, ".st"))
    case.assertLessEqual(y, 6)
    case.assertLessEqual(x, 12)
    _small_margin(case, _one_rule(snapshot.css, ".section"), 16)
    y, x = _padding(_one_rule(snapshot.css, ".section-header"))
    case.assertLessEqual(y, 8)
    case.assertLessEqual(x, 16)
    _small_margin(case, _one_rule(snapshot.css, ".sub-tabs"), 10)


def _check_card_density(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    for selector, limit in ((".crd", 10), (".host-card", 8), (".infra-role-card", 12)):
        case.assertLessEqual(_padding(_one_rule(snapshot.css, selector))[0], limit, selector)


def _check_drilldown(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    host = (".host-card[onclick]", ".host-card.cursor-ptr", ".host-card[data-action]")
    host_after = tuple(f"{selector}::after" for selector in host)
    host_hover = tuple(f"{selector}:hover::after" for selector in host)
    case.assertEqual(_property(_selector_group(snapshot.css, host), "cursor"), "pointer")
    host_after_rule = _selector_group(snapshot.css, host_after)
    case.assertEqual(_property(host_after_rule, "content"), "'\\203A'")
    case.assertEqual(float(_property(host_after_rule, "opacity")), 0)
    case.assertEqual(_property(host_after_rule, "pointer-events"), "none")
    case.assertGreater(float(_property(_selector_group(snapshot.css, host_hover), "opacity")), 0)

    infra = _one_rule(snapshot.css, ".infra-role-card")
    infra_after = _one_rule(snapshot.css, ".infra-role-card::after")
    infra_hover = _one_rule(snapshot.css, ".infra-role-card:hover::after")
    case.assertEqual(_property(infra, "cursor"), "pointer")
    case.assertEqual(_property(infra_after, "content"), _property(host_after_rule, "content"))
    case.assertEqual(float(_property(infra_after, "opacity")), 0)
    case.assertEqual(_property(infra_after, "pointer-events"), "none")
    case.assertGreater(float(_property(infra_hover, "opacity")), 0)


def _check_pve_actions(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    case.assertEqual(_property(_one_rule(snapshot.css, ".pve-node-card-actions"), "align-items"), "center")


def _check_containment(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    sub_tabs = _one_rule(snapshot.css, ".sub-tabs")
    case.assertEqual(_property(sub_tabs, "display"), "flex")
    case.assertEqual(_property(sub_tabs, "flex-wrap"), "wrap")
    lab = _js_function(snapshot.js, "_ltGenerateHTML")
    offline = lab[lab.index("lt-offline") :]
    case.assertNotIn("font-size:48px;opacity:0.15", offline)
    case.assertNotIn("-webkit-background-clip:text", offline)


def _check_cert_responsive(case: unittest.TestCase, snapshot: LayoutSnapshot) -> None:
    targets = _js_function(snapshot.js, "_renderCertTargets")
    case.assertEqual(targets.count('class="cert-target-table-wrap"'), 1)
    case.assertEqual(targets.count('class="cert-target-table"'), 1)
    headings = re.findall(r"<th>([^<]+)</th>", targets)
    case.assertEqual(headings, ["Target", "Scope", "Endpoint", "Hostname", "Driver", "Cert", "Notes"])
    for scope in ("proxy route", "direct mgmt", "legacy direct"):
        case.assertIn(scope, targets)
    case.assertNotIn("cert-target-card", targets)

    wrapper = _one_rule(snapshot.css, ".cert-target-table-wrap")
    table = _one_rule(snapshot.css, ".cert-target-table")
    case.assertEqual(_property(wrapper, "overflow"), "auto")
    case.assertTrue(_property(table, "min-width"))
    case.assertEqual(_property(table, "width"), "100%")
    case.assertEqual(_property(table, "border-collapse"), "collapse")

    setup = _js_function(snapshot.js, "_renderCertSetup")
    providers = _js_function(snapshot.js, "_certProviderCards")
    defaults = _js_function(snapshot.js, "_certProxyDefaultsCard")
    for token in ("cert-onboarding", "cert-choice-grid", "cert-onboarding-grid"):
        case.assertIn(token, setup)
    case.assertIn("cert-provider-card", providers)
    case.assertIn("cert-defaults-card", defaults)
    for selector in (
        ".cert-onboarding",
        ".cert-dashboard-state",
        ".cert-onboarding-grid",
        ".cert-choice-grid",
        ".cert-empty-state",
        ".cert-provider-card",
        ".cert-defaults-card",
    ):
        case.assertRegex(snapshot.css, rf"(?m)^\s*{re.escape(selector)}(?:\s*,|\s*\{{)")

    cert_1200 = [block for block in _media_blocks(snapshot.css, 1200) if ".cert-dashboard-state" in block]
    cert_900 = [block for block in _media_blocks(snapshot.css, 900) if ".cert-choice-grid" in block]
    cert_720 = [block for block in _media_blocks(snapshot.css, 720) if ".cert-choice-grid" in block]
    case.assertEqual(len(cert_1200), 1)
    case.assertIn(".cert-onboarding-grid", cert_1200[0])
    case.assertIn("grid-template-columns: 1fr", cert_1200[0])
    case.assertEqual(len(cert_900), 1)
    case.assertIn("grid-template-columns: 1fr", cert_900[0])
    case.assertEqual(len(cert_720), 1)
    case.assertIn("grid-template-columns: 1fr", cert_720[0])


Checker = Callable[[unittest.TestCase, LayoutSnapshot], None]
Mutator = Callable[[LayoutSnapshot], LayoutSnapshot]


@dataclass(frozen=True)
class LayoutRow:
    id: str
    title: str
    predecessor_count: int
    checker: Checker


@dataclass(frozen=True)
class ReviewMutation:
    title: str
    row_id: str
    mutator: Mutator


def _mutate(
    snapshot: LayoutSnapshot,
    field: str,
    old: str,
    new: str,
    *,
    anchor: str | None = None,
    end: str | None = None,
) -> LayoutSnapshot:
    source = getattr(snapshot, field)
    start = 0 if anchor is None else source.index(anchor)
    stop = len(source) if end is None else source.index(end, start)
    window = source[start:stop]
    if window.count(old) != 1:
        raise AssertionError(f"mutation anchor must be unique: {field} {old!r}")
    changed = source[:start] + window.replace(old, new, 1) + source[stop:]
    if field == "html":
        parser = _ClassCollector()
        parser.feed(changed)
        parser.close()
        return replace(snapshot, html=changed, classes=tuple(parser.classes))
    return replace(snapshot, **{field: changed})


ROWS = (
    LayoutRow("C05-01", "semantic composition", 6, _check_semantic_composition),
    LayoutRow("C05-02", "dense base shell", 3, _check_base_shell),
    LayoutRow("C05-03", "dense operational blocks", 5, _check_operational_blocks),
    LayoutRow("C05-04", "dense cards", 3, _check_card_density),
    LayoutRow("C05-05", "consistent drilldown affordance", 9, _check_drilldown),
    LayoutRow("C05-06", "PVE action alignment", 1, _check_pve_actions),
    LayoutRow("C05-07", "narrow containment and decorative restraint", 3, _check_containment),
    LayoutRow("C05-08", "responsive certificate truth", 2, _check_cert_responsive),
)


MUTATIONS = (
    ReviewMutation(
        "AH marker",
        "C05-01",
        lambda s: _mutate(
            s, "css", "20260413AH SEMANTIC COMPOSITION CLASSES", "20260413AX SEMANTIC COMPOSITION CLASSES"
        ),
    ),
    ReviewMutation(
        "AH class definition",
        "C05-01",
        lambda s: _mutate(
            s,
            "css",
            ".term-shell-col {",
            ".term-shell-col-x {",
            anchor="20260413AH SEMANTIC COMPOSITION CLASSES",
            end="20260413AH-semantic-block-end",
        ),
    ),
    ReviewMutation("AH class consumer", "C05-01", lambda s: _mutate(s, "html", "term-shell-col", "term-shell-col-x")),
    ReviewMutation("retired inline fingerprint", "C05-01", lambda s: replace(s, html=s.html + FORBIDDEN_INLINE[0])),
    ReviewMutation(
        "Q marker", "C05-01", lambda s: _mutate(s, "css", "20260413Q-id-rules-begin", "20260413Q-id-rules-gone")
    ),
    ReviewMutation(
        "Q chrome definition",
        "C05-01",
        lambda s: _mutate(
            s,
            "css",
            ".pve-freq-wordmark {",
            ".pve-freq-wordmark-x {",
            anchor="20260413Q-id-rules-begin",
            end="20260413Q-id-rules-end",
        ),
    ),
    ReviewMutation(
        "body prose spacing",
        "C05-02",
        lambda s: _mutate(s, "css", "line-height: 1.5;", "line-height: 1.60;", anchor="body {", end="body::before"),
    ),
    ReviewMutation(
        "header vertical padding",
        "C05-02",
        lambda s: _mutate(s, "css", "padding: 6px 24px;", "padding: 9px 24px;", anchor=".mn-header {"),
    ),
    ReviewMutation(
        "body vertical padding",
        "C05-02",
        lambda s: _mutate(s, "css", ".mn-body { padding: 14px 28px;", ".mn-body { padding: 17px 28px;"),
    ),
    ReviewMutation(
        "stats gap",
        "C05-03",
        lambda s: _mutate(
            s,
            "css",
            "margin-bottom: var(--gap-sm);",
            "margin-bottom: var(--gap-lg);",
            anchor=".stats {",
            end=".stats .st",
        ),
    ),
    ReviewMutation(
        "stat padding",
        "C05-03",
        lambda s: _mutate(s, "css", "padding: 5px 10px;", "padding: 7px 10px;", anchor=".st {", end=".st:hover"),
    ),
    ReviewMutation(
        "section margin",
        "C05-03",
        lambda s: _mutate(
            s, "css", "margin-bottom: 14px;", "margin-bottom: 20px;", anchor=".section {", end=".section-header"
        ),
    ),
    ReviewMutation(
        "section header padding",
        "C05-03",
        lambda s: _mutate(
            s, "css", "padding: 7px 14px;", "padding: 9px 14px;", anchor=".section-header {", end=".section-header h3"
        ),
    ),
    ReviewMutation(
        "sub-tab gap",
        "C05-03",
        lambda s: _mutate(
            s,
            "css",
            "margin-bottom: var(--gap-sm);",
            "margin-bottom: var(--gap-lg);",
            anchor=".sub-tabs {",
            end=".sub-tab {",
        ),
    ),
    ReviewMutation(
        "card padding",
        "C05-04",
        lambda s: _mutate(s, "css", "padding: 8px 12px;", "padding: 11px 12px;", anchor=".crd {", end=".crd::before"),
    ),
    ReviewMutation(
        "host-card padding",
        "C05-04",
        lambda s: _mutate(
            s, "css", "padding: 7px 11px;", "padding: 9px 11px;", anchor=".host-card {", end=".host-card:hover"
        ),
    ),
    ReviewMutation(
        "infra-card padding",
        "C05-04",
        lambda s: _mutate(
            s,
            "css",
            "padding: 10px 12px;",
            "padding: 13px 12px;",
            anchor=".infra-role-card {",
            end=".core-systems-grid",
        ),
    ),
    ReviewMutation(
        "host selector group",
        "C05-05",
        lambda s: _mutate(
            s, "css", ".host-card[data-action] {", ".host-card[data-act] {", anchor=".host-card[onclick],"
        ),
    ),
    ReviewMutation(
        "host chevron glyph",
        "C05-05",
        lambda s: _mutate(
            s,
            "css",
            "content: '\\203A';",
            "content: '\\2192';",
            anchor=".host-card[onclick]::after",
            end=".host-card[onclick]:hover::after",
        ),
    ),
    ReviewMutation(
        "host chevron visibility",
        "C05-05",
        lambda s: _mutate(
            s,
            "css",
            "opacity: 0;",
            "opacity: 0.1;",
            anchor=".host-card[onclick]::after",
            end=".host-card[onclick]:hover::after",
        ),
    ),
    ReviewMutation(
        "host hover reveal",
        "C05-05",
        lambda s: _mutate(
            s,
            "css",
            "opacity: 0.85;",
            "opacity: 0;",
            anchor=".host-card[onclick]:hover::after",
            end=".host-card .host-head",
        ),
    ),
    ReviewMutation(
        "infra pointer",
        "C05-05",
        lambda s: _mutate(
            s, "css", "cursor: pointer;", "cursor: default;", anchor=".infra-role-card {", end=".core-systems-grid"
        ),
    ),
    ReviewMutation(
        "infra glyph",
        "C05-05",
        lambda s: _mutate(
            s,
            "css",
            "content: '\\203A';",
            "content: '\\2192';",
            anchor=".infra-role-card::after",
            end=".infra-role-card:hover::after",
        ),
    ),
    ReviewMutation(
        "PVE action alignment",
        "C05-06",
        lambda s: _mutate(
            s,
            "css",
            "align-items: center;",
            "align-items: flex-start;",
            anchor=".pve-node-card-actions {",
            end=".pve-node-card-actions .host-fresh-chip",
        ),
    ),
    ReviewMutation(
        "sub-tabs nowrap",
        "C05-07",
        lambda s: _mutate(s, "css", "flex-wrap: wrap;", "flex-wrap: nowrap;", anchor=".sub-tabs {", end=".sub-tab {"),
    ),
    ReviewMutation(
        "offline ghost hero",
        "C05-07",
        lambda s: _mutate(
            s,
            "js",
            'lt-offline" style="padding:24px',
            'lt-offline" style="font-size:48px;opacity:0.15;-webkit-background-clip:text;padding:24px',
            anchor="function _ltGenerateHTML(",
        ),
    ),
    ReviewMutation(
        "certificate table to cards",
        "C05-08",
        lambda s: _mutate(
            s, "js", 'class="cert-target-table"', 'class="cert-target-card"', anchor="function _renderCertTargets("
        ),
    ),
    ReviewMutation(
        "certificate wrapper clips",
        "C05-08",
        lambda s: _mutate(
            s,
            "css",
            "overflow: auto;",
            "overflow: hidden;",
            anchor=".cert-target-table-wrap {",
            end=".cert-target-table {",
        ),
    ),
    ReviewMutation(
        "certificate heading",
        "C05-08",
        lambda s: _mutate(s, "js", "<th>Scope</th>", "<th>Mode</th>", anchor="function _renderCertTargets("),
    ),
    ReviewMutation(
        "certificate 900 grid",
        "C05-08",
        lambda s: _mutate(
            s,
            "css",
            ".cert-choice-grid { grid-template-columns: 1fr; }",
            ".cert-choice-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }",
            anchor="@media(max-width: 900px) {",
        ),
    ),
    ReviewMutation(
        "certificate provider card",
        "C05-08",
        lambda s: _mutate(
            s,
            "js",
            "cert-provider-card",
            "cert-provider-panel",
            anchor="function _certProviderCards(",
            end="function _certProxyDefaultsCard(",
        ),
    ),
)

SNAPSHOT = LayoutSnapshot.load()


class TestFrontendLayoutTable(unittest.TestCase):
    def test_c05_shipped_layout_rows_and_review_mutants(self) -> None:
        self.assertEqual(tuple(row.id for row in ROWS), tuple(f"C05-{number:02d}" for number in range(1, 9)))
        self.assertEqual(sum(row.predecessor_count for row in ROWS), 32)
        self.assertEqual(len(MUTATIONS), 31)
        for row in ROWS:
            with self.subTest(row=row.id, title=row.title):
                row.checker(self, SNAPSHOT)

        for mutation in MUTATIONS:
            mutated = mutation.mutator(SNAPSHOT)
            failures: list[str] = []
            for row in ROWS:
                try:
                    row.checker(self, mutated)
                except AssertionError:
                    failures.append(row.id)
            with self.subTest(mutation=mutation.title):
                self.assertEqual(failures, [mutation.row_id])


if __name__ == "__main__":
    unittest.main()
