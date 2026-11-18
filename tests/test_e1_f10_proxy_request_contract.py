"""Derived inventory owner for the E1 F10 browser request boundary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_JS = REPO_ROOT / "freq/data/web/js/app.js"
HERMETIC_SPEC = REPO_ROOT / "tests/e2e/hermetic-dashboard.spec.js"
TEST_HEALTH = REPO_ROOT / "scripts/test_health.py"
REDESIGN_MANIFEST = REPO_ROOT / "tests/support/frontend_test_redesign_manifest.py"


@dataclass(frozen=True)
class FunctionSpan:
    name: str
    start: int
    body_start: int
    end: int


def _mask_javascript(source: str) -> str:
    """Mask comments/string bodies but retain executable template expressions."""

    chars = list(source)
    index = 0
    contexts: list[dict[str, object]] = [{"kind": "code"}]
    while index < len(chars):
        char = chars[index]
        nxt = chars[index + 1] if index + 1 < len(chars) else ""
        context = contexts[-1]
        kind = context["kind"]
        if kind in {"code", "template_expression"}:
            if char == "/" and nxt == "/":
                chars[index] = chars[index + 1] = " "
                index += 2
                contexts.append({"kind": "line_comment"})
                continue
            if char == "/" and nxt == "*":
                chars[index] = chars[index + 1] = " "
                index += 2
                contexts.append({"kind": "block_comment"})
                continue
            if char in {"'", '"'}:
                chars[index] = " "
                index += 1
                contexts.append({"kind": "string", "quote": char, "escaped": False})
                continue
            if char == "`":
                chars[index] = " "
                index += 1
                contexts.append({"kind": "template", "escaped": False})
                continue
            if kind == "template_expression":
                if char == "{":
                    context["depth"] = int(context["depth"]) + 1
                elif char == "}":
                    context["depth"] = int(context["depth"]) - 1
                    if context["depth"] == 0:
                        contexts.pop()
        elif kind == "line_comment":
            if char == "\n":
                contexts.pop()
            else:
                chars[index] = " "
        elif kind == "block_comment":
            chars[index] = " "
            if char == "*" and nxt == "/":
                chars[index + 1] = " "
                index += 2
                contexts.pop()
                continue
        elif kind == "string":
            chars[index] = " "
            if context["escaped"]:
                context["escaped"] = False
            elif char == "\\":
                context["escaped"] = True
            elif char == context["quote"]:
                contexts.pop()
        else:
            chars[index] = " "
            if context["escaped"]:
                context["escaped"] = False
            elif char == "\\":
                context["escaped"] = True
            elif char == "`":
                contexts.pop()
            elif char == "$" and nxt == "{":
                chars[index + 1] = "{"
                index += 2
                contexts.append({"kind": "template_expression", "depth": 1})
                continue
        index += 1
    if contexts[-1]["kind"] == "line_comment":
        contexts.pop()
    if len(contexts) != 1 or contexts[0]["kind"] != "code":
        states = ", ".join(str(context["kind"]) for context in contexts[1:])
        raise AssertionError(f"unterminated JavaScript lexical state: {states}")
    return "".join(chars)


def _balanced_end(masked: str, opening: int, left: str, right: str) -> int:
    depth = 0
    for index in range(opening, len(masked)):
        char = masked[index]
        if char == left:
            depth += 1
        elif char == right:
            depth -= 1
            if depth == 0:
                return index + 1
    raise AssertionError(f"unbalanced JavaScript delimiter {left}{right} at {opening}")


def _function_spans(masked: str) -> list[FunctionSpan]:
    spans: list[FunctionSpan] = []
    for match in re.finditer(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", masked):
        body_start = masked.find("{", match.end())
        if body_start < 0:
            raise AssertionError(f"function {match.group(1)} has no body")
        spans.append(
            FunctionSpan(
                name=match.group(1),
                start=match.start(),
                body_start=body_start,
                end=_balanced_end(masked, body_start, "{", "}"),
            )
        )
    return spans


def _first_argument(source: str, masked: str, opening: int, end: int) -> str:
    paren = bracket = brace = 0
    for index in range(opening + 1, end - 1):
        char = masked[index]
        if char == "(":
            paren += 1
        elif char == ")":
            if paren:
                paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]":
            bracket -= 1
        elif char == "{":
            brace += 1
        elif char == "}":
            brace -= 1
        elif char == "," and paren == bracket == brace == 0:
            return source[opening + 1 : index].strip()
    return source[opening + 1 : end - 1].strip()


def _derived_proxy_invocations(source: str) -> tuple[str, ...]:
    masked = _mask_javascript(source)
    spans = _function_spans(masked)
    call_ordinals: dict[str, int] = {}
    invocations: list[str] = []
    for match in re.finditer(r"\b_authFetch\s*\(", masked):
        opening = masked.find("(", match.start())
        end = _balanced_end(masked, opening, "(", ")")
        first_argument = _first_argument(source, masked, opening, end)
        containing = [span for span in spans if span.start < match.start() < span.end]
        if not containing:
            function = FunctionSpan("<top-level>", 0, 0, len(source))
        else:
            function = max(containing, key=lambda span: span.start)
        proxy_expression = "API.LAB_TOOL_PROXY" in first_argument or "/api/lab-tool/proxy" in first_argument
        if not proxy_expression and re.fullmatch(r"[A-Za-z_$][\w$]*", first_argument):
            assignments = re.findall(
                rf"\b(?:var|let|const)\s+{re.escape(first_argument)}\s*=\s*([^;]+);",
                source[function.body_start : match.start()],
            )
            if len(assignments) > 1:
                raise AssertionError(f"multiple initializers for request variable {first_argument}")
            proxy_expression = bool(assignments) and (
                "API.LAB_TOOL_PROXY" in assignments[0] or "/api/lab-tool/proxy" in assignments[0]
            )
        if not proxy_expression:
            continue
        call_ordinals[function.name] = call_ordinals.get(function.name, 0) + 1
        callsite = f"{function.name}#{call_ordinals[function.name]}"
        body_mask = masked[function.body_start : function.end]
        if re.search(r"\bif\s*\(\s*confirm\s*\)\s*url\s*\+=\s*", body_mask):
            if first_argument != "url":
                raise AssertionError(f"unsupported request-mutating confirm branch at {callsite}")
            invocations.extend((f"{callsite}/confirm-absent", f"{callsite}/confirm-YES"))
        elif "confirmAction(" in source[function.body_start : match.start()]:
            invocations.append(f"{callsite}/confirmAction-accepted")
        else:
            invocations.append(f"{callsite}/direct")
    if not invocations:
        raise AssertionError("no lab-tool proxy _authFetch callsites were derived")
    if len(invocations) != len(set(invocations)):
        raise AssertionError(f"duplicate derived invocation identities: {invocations}")
    return tuple(sorted(invocations))


def _derived_persistence_roots(source: str) -> tuple[str, ...]:
    masked = _mask_javascript(source)
    computed_method = re.search(
        r"\b(localStorage|sessionStorage|indexedDB|caches)\s*"
        r"\[\s*[^\]]+\s*\]\s*\(",
        masked,
    )
    if computed_method:
        raise AssertionError(
            f"computed persistence method name is not attributable: {computed_method.group(1)}"
        )
    unsupported_alias = re.search(
        r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*"
        r"(?:localStorage|sessionStorage|indexedDB|caches)\s*;",
        masked,
    )
    if unsupported_alias:
        raise AssertionError("aliased persistence root is not attributable")

    roots: set[str] = set()
    web_storage_write = re.compile(
        r"\b(localStorage|sessionStorage)\s*(?:\.\s*"
        r"(?:setItem|removeItem|clear)\s*\(|\[\s*[^\]]+\s*\]\s*=)"
    )
    roots.update(match.group(1) for match in web_storage_write.finditer(masked))
    if re.search(r"\bdocument\s*(?:\.\s*cookie|\[\s*[^\]]+\s*\])\s*=", masked):
        roots.add("cookie")
    if re.search(r"\bindexedDB\s*\.", masked):
        roots.add("indexedDB")
    if re.search(r"\bcaches\s*\.", masked):
        roots.add("caches")
    return tuple(sorted(roots))


def test_f10_inventory_observes_executable_template_interpolation() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    injected = (
        '\nfunction f10TemplateProbe(){return `literal _authFetch(API.LAB_TOOL_PROXY) '
        '${_authFetch(API.LAB_TOOL_PROXY)}`;}\n'
    )
    derived = _derived_proxy_invocations(source + injected)
    assert "f10TemplateProbe#1/direct" in derived
    assert len(derived) == len(_derived_proxy_invocations(source)) + 1


def test_f10_inventory_rejects_computed_persistence_method_names() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    try:
        _derived_persistence_roots(source + '\nindexedDB["open"]("f10");\n')
    except AssertionError as exc:
        assert "computed persistence method name is not attributable: indexedDB" in str(exc)
    else:
        raise AssertionError("computed indexedDB method call did not fail owner setup")


def _json_array_constant(source: str, name: str) -> tuple[str, ...]:
    pattern = rf"const\s+{re.escape(name)}\s*=\s*Object\.freeze\(\s*(\[[\s\S]*?\])\s*\);"
    matches = re.findall(pattern, source)
    if len(matches) != 1:
        raise AssertionError(f"expected one {name} array, found {len(matches)}")
    value = json.loads(matches[0])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AssertionError(f"{name} must be a JSON string array")
    if len(value) != len(set(value)):
        raise AssertionError(f"{name} contains duplicate identities")
    return tuple(sorted(value))


def test_f10_proxy_request_inventory_matches_browser_adapters() -> None:
    app_source = APP_JS.read_text(encoding="utf-8")
    spec_source = HERMETIC_SPEC.read_text(encoding="utf-8")
    derived_invocations = _derived_proxy_invocations(app_source)
    registered_invocations = _json_array_constant(spec_source, "F10_PROXY_INVOCATION_IDS")
    assert registered_invocations == derived_invocations

    active_persistence = _derived_persistence_roots(app_source)
    supported_enumerators = _json_array_constant(spec_source, "F10_PERSISTENCE_ENUMERATOR_IDS")
    assert set(active_persistence) <= set(supported_enumerators)
    assert active_persistence

    health = TEST_HEALTH.read_text(encoding="utf-8")
    assert '"H13": ("hermetic-dashboard.spec.js", "H13 lab-tool proxy requests keep vault credentials out of browser request surfaces")' in health
    assert '"hermetic-dashboard.spec.js": 9' in health

    redesign = REDESIGN_MANIFEST.read_text(encoding="utf-8")
    assert '{"id": "H13", "kind": "hermetic", "name": "lab-tool proxy credential boundary"}' in redesign
    assert 'title.startswith("H13 lab-tool proxy requests keep vault credentials out of browser request surfaces")' in redesign
