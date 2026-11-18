"""C01 declarative contract for the complete shipped frontend asset policy."""

from __future__ import annotations

import ast
import re
import unittest
from collections.abc import Callable
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from freq.modules import web_ui
from freq.modules.serve import FreqHandler

REPO_ROOT = Path(__file__).parent.parent

UTILITY_CLASSES = (
    "helptext-mb8",
    "helptext-mb12",
    "helptext-mb4-block",
    "helptext-section",
    "helptext-section-tight",
    "helptext-sm-mb8",
    "helptext-mt8",
    "helptext",
    "section-label-pl-mt12",
    "section-label-pl-h3",
    "w-80",
    "w-100",
    "w-120",
    "w-140",
    "w-160",
    "w-180",
    "w-200",
    "w-240",
    "w-260",
    "flex-min-100",
    "flex-min-120",
    "flex-gap-8",
    "flex-gap-8-center-wrap",
    "flex-gap-16-wrap-mb16",
    "flex-row-8-mb12-center-wrap",
    "mt-16",
    "ml-4",
    "ml-8",
    "ml-auto",
    "mr-4",
    "card-block-thick",
    "card-block-bg2",
    "kbd-tag",
    "kbd-mono-10",
    "text-green",
    "text-dim",
    "fs-16",
    "fs-9-px-2-8",
)

CHROME_CLASSES = (
    "pve-freq-wordmark",
    "nav-ver-label",
    "nav-divider",
    "header-time-label",
)

STABLE_IDS = (
    "nav-items",
    "home-empty",
    "fleet-lab-section",
    "container-stats",
    "container-logs",
    "rescan-results",
    "log-out",
    "topo-svg",
    "pb-runner-title",
    "fed-url",
    "about-credits",
    "hd-subtitle",
    "hd-loading",
    "terminal-overlay",
    "terminal-header",
    "terminal-title",
    "terminal-container",
    "search-overlay",
    "search-results",
    "shortcuts-modal",
)

VENDOR_ASSETS = (
    "vendor/xterm/xterm.min.css",
    "vendor/xterm/xterm.min.js",
    "vendor/xterm/addon-fit.min.js",
    "vendor/xterm/addon-clipboard.min.js",
)

VENDOR_MIN_BYTES = {
    "vendor/xterm/xterm.min.css": 500,
    "vendor/xterm/xterm.min.js": 100_000,
    "vendor/xterm/addon-fit.min.js": 1_000,
    "vendor/xterm/addon-clipboard.min.js": 5_000,
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _InventoryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.scripts: list[tuple[dict[str, str | None], list[str]]] = []
        self._active_script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == "script":
            body: list[str] = []
            self.scripts.append((attributes, body))
            self._active_script = body

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._active_script is not None:
            self._active_script.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._active_script = None


def _inventory(html: str) -> _InventoryParser:
    parser = _InventoryParser()
    parser.feed(html)
    return parser


def _static_refs(html: str) -> tuple[str, ...]:
    refs: list[str] = []
    for tag, attrs in _inventory(html).tags:
        if tag == "script" and attrs.get("src"):
            refs.append(str(attrs["src"]))
        if tag == "link" and "stylesheet" in str(attrs.get("rel", "")).split() and attrs.get("href"):
            refs.append(str(attrs["href"]))
    return tuple(refs)


def _asset_name(ref: str) -> str:
    path = urlsplit(ref).path
    _require(path.startswith("/static/"), f"frontend asset reference is not same-origin /static: {ref}")
    return path.removeprefix("/static/")


def _version_tokens(html: str) -> set[str]:
    return {
        token
        for ref in _static_refs(html)
        for token in parse_qs(urlsplit(ref).query, keep_blank_values=True).get("v", [])
    }


def _extract_braced(source: str, opening: int) -> str:
    _require(opening >= 0 and source[opening] == "{", "expected JavaScript opening brace")
    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
        elif block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char == "/" and following == "/":
            line_comment = True
            index += 1
        elif char == "/" and following == "*":
            block_comment = True
            index += 1
        elif char in "'\"`":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
        index += 1
    raise AssertionError("unterminated JavaScript block")


def _js_function(source: str, name: str) -> str:
    match = re.search(rf"\bfunction\s+{re.escape(name)}\s*\(", source)
    _require(match is not None, f"missing JavaScript function {name}")
    opening = source.find("{", match.end())
    return _extract_braced(source, opening)


def _click_delegator(source: str) -> str:
    matches = list(re.finditer(r"document\.addEventListener\(\s*['\"]click['\"]\s*,\s*function\s*\(", source))
    _require(len(matches) == 1, "app.js must expose exactly one document click delegator")
    opening = source.find("{", matches[0].end())
    return _extract_braced(source, opening)


def _runtime_csp() -> str:
    headers: list[tuple[str, str]] = []

    class _HeaderProbe:
        def send_header(self, name: str, value: str) -> None:
            headers.append((name, value))

    with patch("freq.modules.serve._request_is_https", return_value=False):
        FreqHandler._send_security_headers(_HeaderProbe())
    values = [value for name, value in headers if name.lower() == "content-security-policy"]
    _require(len(values) == 1, "security header path must emit exactly one CSP")
    return values[0]


@dataclass(frozen=True)
class AssetSnapshot:
    manifest: tuple[str, ...]
    assets: dict[str, str]
    python_sources: dict[str, str]
    pyproject: str
    csp: str

    @classmethod
    def load(cls) -> AssetSnapshot:
        manifest = tuple(web_ui.FRONTEND_ASSET_MANIFEST)
        assets = {name: web_ui.read_asset(name) for name in manifest}
        python_sources = {
            path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
            for root in (REPO_ROOT / "freq" / "api", REPO_ROOT / "freq" / "modules")
            for path in root.rglob("*.py")
        }
        return cls(
            manifest=manifest,
            assets=assets,
            python_sources=python_sources,
            pyproject=(REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
            csp=_runtime_csp(),
        )

    def asset(self, name: str) -> str:
        _require(name in self.assets, f"manifest does not carry {name}")
        return self.assets[name]


Checker = Callable[[AssetSnapshot], None]
Mutator = Callable[[AssetSnapshot], AssetSnapshot]


@dataclass(frozen=True)
class AssetPolicyRow:
    row_id: str
    title: str
    checker: Checker
    mutator: Mutator


def _check_local_reference_closure(snapshot: AssetSnapshot) -> None:
    for template in ("app.html", "setup.html"):
        refs = _static_refs(snapshot.asset(template))
        _require(refs, f"{template} must link at least one stylesheet or script")
        for ref in refs:
            _require(_asset_name(ref) in snapshot.assets, f"{template} references an unshipped asset: {ref}")
            query = parse_qs(urlsplit(ref).query, keep_blank_values=True)
            _require(query == {"v": ["{{VERSION}}"]}, f"{template} has an unversioned asset reference: {ref}")


def _serve_snapshot(snapshot: AssetSnapshot) -> tuple[str, str]:
    with (
        patch.object(web_ui, "FRONTEND_ASSET_MANIFEST", snapshot.manifest),
        patch.object(web_ui, "read_asset", side_effect=snapshot.asset),
    ):
        return web_ui.load_app_html(), web_ui.load_setup_html()


def _check_cache_identity_closure(snapshot: AssetSnapshot) -> None:
    referenced = {
        _asset_name(ref)
        for template in ("app.html", "setup.html")
        for ref in _static_refs(snapshot.asset(template))
    }
    _require(len(snapshot.manifest) == len(set(snapshot.manifest)), "manifest entries must be unique")
    _require(set(snapshot.manifest) == referenced | {"app.html", "setup.html"}, "manifest must equal template closure")
    app_served, setup_served = _serve_snapshot(snapshot)
    app_tokens = _version_tokens(app_served)
    setup_tokens = _version_tokens(setup_served)
    _require(len(app_tokens) == 1, "app.html must emit one concrete asset token")
    _require(app_tokens == setup_tokens, "app and setup templates must emit the same complete-bundle token")
    _require("{{VERSION}}" not in app_served + setup_served, "served templates must not leak VERSION placeholders")
    baseline = app_tokens
    for name in snapshot.manifest:
        changed_assets = dict(snapshot.assets)
        changed_assets[name] += f"\n/* c01-token-probe:{name} */"
        changed = replace(snapshot, assets=changed_assets)
        changed_app, changed_setup = _serve_snapshot(changed)
        _require(_version_tokens(changed_app) != baseline, f"changing {name} must change the app token")
        _require(_version_tokens(changed_setup) != baseline, f"changing {name} must change the setup token")


def _check_semantic_class_closure(snapshot: AssetSnapshot) -> None:
    html = snapshot.asset("app.html")
    css = snapshot.asset("css/app.css")
    used = {
        class_name
        for _, attrs in _inventory(html).tags
        for class_name in str(attrs.get("class", "")).split()
    }
    for class_name in UTILITY_CLASSES + CHROME_CLASSES:
        declarations = re.findall(rf"(?m)^\s*\.{re.escape(class_name)}\s*\{{", css)
        # The wordmark has one base rule plus two intentional responsive overrides.
        expected_count = {"pve-freq-wordmark": 3}.get(class_name, 1)
        _require(
            len(declarations) == expected_count,
            f"semantic class .{class_name} must preserve its exact declaration count ({expected_count})",
        )
        _require(class_name in used, f"semantic class .{class_name} is not used by app.html")


def _check_stable_id_extraction(snapshot: AssetSnapshot) -> None:
    html = snapshot.asset("app.html")
    css = snapshot.asset("css/app.css")
    tags = _inventory(html).tags
    for stable_id in STABLE_IDS:
        matches = [attrs for _, attrs in tags if attrs.get("id") == stable_id]
        _require(len(matches) == 1, f"stable id #{stable_id} must exist exactly once")
        _require("style" not in matches[0], f"stable id #{stable_id} must not carry an inline style")
        _require(re.search(rf"#{re.escape(stable_id)}(?:\s|,)", css) is not None, f"missing CSS rule for #{stable_id}")


def _check_inline_executable_and_fouc(snapshot: AssetSnapshot) -> None:
    for template in ("app.html", "setup.html"):
        inventory = _inventory(snapshot.asset(template))
        for tag, attrs in inventory.tags:
            _require(not any(name.startswith("on") for name in attrs), f"{template} contains an inline event handler")
            _require(
                not any(str(value).strip().lower().startswith("javascript:") for value in attrs.values()),
                f"{template} contains a javascript URL",
            )
            if tag in {"script", "style"}:
                _require(tag != "style" and bool(attrs.get("src")), f"{template} contains an inline {tag} block")
        for _, body_parts in inventory.scripts:
            _require(not "".join(body_parts).strip(), f"{template} contains executable text inside a script tag")
    app_css = snapshot.asset("css/app.css")
    _require("body { opacity: 0; animation: bodyFadeIn" in app_css, "dashboard FOUC fade must live in app.css")
    _require("@keyframes bodyFadeIn" in app_css, "dashboard FOUC keyframes must live in app.css")


def _csp_directives(value: str) -> dict[str, tuple[str, ...]]:
    directives: dict[str, tuple[str, ...]] = {}
    for chunk in value.split(";"):
        parts = chunk.strip().split()
        if parts:
            _require(parts[0] not in directives, f"CSP carries duplicate {parts[0]} directives")
            directives[parts[0]] = tuple(parts[1:])
    return directives


def _check_emitted_csp(snapshot: AssetSnapshot) -> None:
    directives = _csp_directives(snapshot.csp)
    for name in ("default-src", "script-src", "font-src", "connect-src"):
        _require(directives.get(name) == ("'self'",), f"{name} must be self-only")
    _require(directives.get("style-src") == ("'self'", "'unsafe-inline'"), "style-src must state the runtime limit")
    _require("'unsafe-inline'" not in directives["script-src"], "script-src must prohibit inline execution")
    _require("style-src-attr" not in directives, "CSP must not carry the failed style-src-attr compatibility path")
    csp_owners = {
        **snapshot.python_sources,
        "freq/data/web/css/app.css": snapshot.asset("css/app.css"),
        "freq/data/web/css/setup.css": snapshot.asset("css/setup.css"),
    }
    for owner, source in csp_owners.items():
        for stale_claim in ("unsafe-hashes", "_inline_style_csp_hashes", "drops one hash"):
            _require(stale_claim not in source, f"{owner} carries retired CSP helper/claim: {stale_claim}")


def _check_origin_and_reflection(snapshot: AssetSnapshot) -> None:
    load_attributes = {"src", "srcset", "href", "action", "formaction", "poster", "data"}
    for template in ("app.html", "setup.html"):
        for tag, attrs in _inventory(snapshot.asset(template)).tags:
            for attribute in load_attributes & attrs.keys():
                raw_value = str(attrs[attribute] or "")
                candidates = raw_value.split(",") if attribute == "srcset" else [raw_value]
                for candidate in candidates:
                    normalized = candidate.strip().split()[0] if candidate.strip() else ""
                    _require(
                        re.match(r"(?:https?:)?//", normalized, re.I) is None,
                        f"remote {attribute} load on <{tag}> in {template}",
                    )
        for ref in _static_refs(snapshot.asset(template)):
            _asset_name(ref)
    for css_name in ("css/app.css", "css/setup.css"):
        css = snapshot.asset(css_name)
        _require(
            re.search(r"@import\s+(?:url\()?\s*['\"]?(?:https?:)?//", css, re.I) is None,
            f"remote import in {css_name}",
        )
        _require(
            re.search(r"url\(\s*['\"]?(?:https?:)?//", css, re.I) is None,
            f"remote asset URL in {css_name}",
        )
    executable_remote = re.compile(
        r"\b(?:fetch|importScripts|WebSocket|EventSource|import)\s*\(\s*['\"](?:https?:)?//",
        re.I,
    )
    for js_name in ("js/app.js", "js/setup.js", "js/router.js"):
        _require(executable_remote.search(snapshot.asset(js_name)) is None, f"remote executable load in {js_name}")
    for vendor_name in VENDOR_ASSETS:
        vendor = snapshot.asset(vendor_name)
        _require(re.search(r"https?://", vendor, re.I) is None, f"external-origin metadata in {vendor_name}")
        _require("sourceMappingURL" not in vendor, f"stale source-map advertisement in {vendor_name}")
    for source_name, source in snapshot.python_sources.items():
        for node in ast.walk(ast.parse(source, filename=source_name)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "send_header" or not node.args:
                continue
            _require(
                _literal_string(node.args[0]) != "Access-Control-Allow-Origin",
                f"reflected-origin header path in {source_name}",
            )


def _literal_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_string(node.left)
        right = _literal_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if (
                isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Constant)
                and value.format_spec is None
                and value.conversion in {-1, 115}
            ):
                parts.append(str(value.value.value))
                continue
            return None
        return "".join(parts)
    return None


def _check_vendored_xterm(snapshot: AssetSnapshot) -> None:
    refs = _static_refs(snapshot.asset("app.html"))
    referenced = tuple(_asset_name(ref) for ref in refs)
    _require(set(VENDOR_ASSETS) == {name for name in snapshot.manifest if name.startswith("vendor/xterm/")}, "vendor set")
    for name in VENDOR_ASSETS:
        _require(referenced.count(name) == 1, f"{name} must be referenced exactly once")
        _require(len(snapshot.asset(name).encode()) >= VENDOR_MIN_BYTES[name], f"{name} payload is unexpectedly small")
        _require(web_ui.read_asset(name) == snapshot.asset(name), f"public loader cannot read {name}")
        _require("sourceMappingURL" not in snapshot.asset(name), f"{name} advertises a missing map")
    _require('"web/vendor/xterm/*.css"' in snapshot.pyproject, "package data must include vendored xterm CSS")
    _require('"web/vendor/xterm/*.js"' in snapshot.pyproject, "package data must include vendored xterm JS")
    _require(not any(name.endswith(".map") for name in snapshot.assets), "manifest must not advertise source maps")


def _check_font_closure(snapshot: AssetSnapshot) -> None:
    app_css = snapshot.asset("css/app.css")
    setup_css = snapshot.asset("css/setup.css")
    for name, css in (("app.css", app_css), ("setup.css", setup_css)):
        _require(re.search(r"@import\s+(?:url\()?", css, re.I) is None, f"runtime font import in {name}")
        _require(re.search(r"@font-face\b", css, re.I) is None, f"runtime @font-face load in {name}")
        _require(
            re.search(r"url\([^)]*\.(?:eot|otf|ttf|woff2?)(?:[?#'\"]|\))", css, re.I) is None,
            f"runtime font asset target in {name}",
        )
        definitions = set(re.findall(r"--([\w-]+)\s*:", css))
        canonical_fonts = definitions & {"font-ui", "font-mono"}
        declarations = re.findall(r"\bfont(?:-family)?\s*:\s*([^;{}]+)", css)
        for declaration in declarations:
            references = set(re.findall(r"var\(--([\w-]+)\)", declaration))
            _require(
                references <= canonical_fonts,
                f"{name} font declaration has unresolved/noncanonical variables: {sorted(references - canonical_fonts)}",
            )
    app_definitions = set(re.findall(r"--([\w-]+)\s*:", app_css))
    _require("mono" not in app_definitions and "var(--mono)" not in app_css, "legacy --mono alias must not survive")
    mono_rule = re.search(r"\.mono\s*\{([^}]*)\}", app_css)
    _require(mono_rule is not None and "var(--font-mono)" in mono_rule.group(1), ".mono must use --font-mono")
    ui_value = re.search(r"--font-ui\s*:\s*([^;]+)", app_css)
    mono_value = re.search(r"--font-mono\s*:\s*([^;]+)", app_css)
    _require(ui_value is not None and "sans-serif" in ui_value.group(1), "--font-ui needs a system fallback")
    _require(mono_value is not None and "monospace" in mono_value.group(1), "--font-mono needs a system fallback")
    family_values = re.findall(r"\bfont-family\s*:\s*([^;{}]+)", app_css + "\n" + setup_css)
    for value in family_values:
        lower = value.lower()
        _require(
            "var(--" in value or lower == "inherit" or "sans-serif" in lower or "monospace" in lower,
            f"font-family lacks a generic/system fallback: {value}",
        )


def _check_delegated_pve_create(snapshot: AssetSnapshot) -> None:
    app_js = snapshot.asset("js/app.js")
    producer = _js_function(app_js, "_buildPveNodeData")
    delegator = _click_delegator(app_js)
    handler = _js_function(app_js, "openVmCreateForNode")
    _require(producer.count('data-action="openVmCreateForNode"') == 1, "PVE card must emit the create action once")
    _require(producer.count('data-node="') == 1, "PVE card must emit its node identity once")
    _require(
        "openVmCreateForNode(da.dataset.node||g)" in delegator,
        "document delegator must pass dataset.node to PVE create",
    )
    _require("_pendingVmCreateNode=nodeName||''" in handler, "PVE create handler must record the selected node")
    _require("sel.value=_pendingVmCreateNode" in handler, "PVE create handler must prefill the node selector")
    _require("onclick=" not in producer, "PVE create producer must not restore an inline handler")


def _change_asset(snapshot: AssetSnapshot, name: str, transform: Callable[[str], str]) -> AssetSnapshot:
    assets = dict(snapshot.assets)
    assets[name] = transform(assets[name])
    return replace(snapshot, assets=assets)


def _mutate_reference(snapshot: AssetSnapshot) -> AssetSnapshot:
    return _change_asset(snapshot, "setup.html", lambda value: value.replace("?v={{VERSION}}", "", 1))


def _mutate_manifest(snapshot: AssetSnapshot) -> AssetSnapshot:
    return replace(snapshot, manifest=tuple(name for name in snapshot.manifest if name != "js/router.js"))


def _mutate_semantic_class(snapshot: AssetSnapshot) -> AssetSnapshot:
    return _change_asset(
        snapshot,
        "css/app.css",
        lambda value: re.sub(r"\.helptext-mb8\s*\{[^}]*\}", "", value, count=1),
    )


def _mutate_stable_id(snapshot: AssetSnapshot) -> AssetSnapshot:
    return _change_asset(
        snapshot,
        "app.html",
        lambda value: value.replace('id="nav-items"', 'id="nav-items" style="display:block"', 1),
    )


def _mutate_inline_execution(snapshot: AssetSnapshot) -> AssetSnapshot:
    return _change_asset(snapshot, "app.html", lambda value: value.replace("<body", '<body onclick="doLogin()"', 1))


def _mutate_csp(snapshot: AssetSnapshot) -> AssetSnapshot:
    return replace(snapshot, csp=snapshot.csp.replace("style-src 'self' 'unsafe-inline'", "style-src 'self'", 1))


def _mutate_origin(snapshot: AssetSnapshot) -> AssetSnapshot:
    sources = dict(snapshot.python_sources)
    sources["freq/modules/serve.py"] += (
        "\n\ndef _c01_reflected_origin_mutant(self):\n"
        "    self.send_header('Access-Control-Allow-Origin', '*')\n"
    )
    return replace(snapshot, python_sources=sources)


def _mutate_vendor(snapshot: AssetSnapshot) -> AssetSnapshot:
    return _change_asset(snapshot, "vendor/xterm/addon-clipboard.min.js", lambda value: value[:500])


def _mutate_font(snapshot: AssetSnapshot) -> AssetSnapshot:
    return _change_asset(
        snapshot,
        "css/app.css",
        lambda value: value.replace(".mono { font-family: var(--font-mono); }", ".mono { font-family: var(--mono); }", 1),
    )


def _mutate_pve_create(snapshot: AssetSnapshot) -> AssetSnapshot:
    return _change_asset(
        snapshot,
        "js/app.js",
        lambda value: value.replace("openVmCreateForNode(da.dataset.node||g)", "openVmCreateForNode(da.dataset.arg||g)", 1),
    )


POLICY_ROWS = (
    AssetPolicyRow("C01-01", "local reference closure", _check_local_reference_closure, _mutate_reference),
    AssetPolicyRow("C01-02", "cache identity closure", _check_cache_identity_closure, _mutate_manifest),
    AssetPolicyRow("C01-03", "semantic class closure", _check_semantic_class_closure, _mutate_semantic_class),
    AssetPolicyRow("C01-04", "stable-ID extraction", _check_stable_id_extraction, _mutate_stable_id),
    AssetPolicyRow("C01-05", "inline executable and FOUC", _check_inline_executable_and_fouc, _mutate_inline_execution),
    AssetPolicyRow("C01-06", "emitted CSP", _check_emitted_csp, _mutate_csp),
    AssetPolicyRow("C01-07", "origin and reflection", _check_origin_and_reflection, _mutate_origin),
    AssetPolicyRow("C01-08", "vendored xterm", _check_vendored_xterm, _mutate_vendor),
    AssetPolicyRow("C01-09", "font closure", _check_font_closure, _mutate_font),
    AssetPolicyRow("C01-10", "delegated PVE create", _check_delegated_pve_create, _mutate_pve_create),
)


class TestFrontendAssetPolicyTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = AssetSnapshot.load()

    def test_c01_frontend_asset_policy_table(self) -> None:
        self.assertEqual([row.row_id for row in POLICY_ROWS], [f"C01-{number:02d}" for number in range(1, 11)])
        for row in POLICY_ROWS:
            with self.subTest(row=row.row_id, title=row.title):
                row.checker(self.snapshot)
                with self.assertRaises(AssertionError, msg=f"{row.row_id} must kill its causal mutant"):
                    row.checker(row.mutator(self.snapshot))
