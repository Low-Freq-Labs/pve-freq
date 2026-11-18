"""C03 declarative ownership for the browser and programmatic setup schema.

The real zero-state journeys own browser/server behavior.  This table owns the
shipped source topology around them: every step and dormant control, the API
transport seams, value-only payload construction, recovery gates, and honest
operator-facing transport copy.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEP_ORDER = ("operator", "connect", "discover", "credentials", "launch", "progress")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


@dataclass
class HtmlNode:
    tag: str
    attrs: tuple[tuple[str, str], ...]
    parent: HtmlNode | None
    children: list[HtmlNode | str]

    def attr(self, name: str) -> str | None:
        return dict(self.attrs).get(name)

    def has_attr(self, name: str) -> bool:
        return name in dict(self.attrs)

    def classes(self) -> tuple[str, ...]:
        return tuple((self.attr("class") or "").split())

    def text(self) -> str:
        parts: list[str] = []

        def visit(item: HtmlNode | str) -> None:
            if isinstance(item, str):
                parts.append(item)
                return
            for child in item.children:
                visit(child)

        visit(self)
        return " ".join(" ".join(parts).split())

    def ancestors(self) -> Iterator[HtmlNode]:
        current = self.parent
        while current is not None:
            yield current
            current = current.parent


class _SetupParser(HTMLParser):
    _VOID = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document", (), None, [])
        self.nodes: list[HtmlNode] = []
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(
            tag,
            tuple((name, value or "") for name, value in attrs),
            self._stack[-1],
            [],
        )
        self._stack[-1].children.append(node)
        self.nodes.append(node)
        if tag not in self._VOID:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


@dataclass(frozen=True)
class SetupSnapshot:
    html: str
    js: str
    nodes: tuple[HtmlNode, ...]

    @classmethod
    def load(cls) -> SetupSnapshot:
        return cls.from_sources(
            (ROOT / "freq/data/web/setup.html").read_text(encoding="utf-8"),
            (ROOT / "freq/data/web/js/setup.js").read_text(encoding="utf-8"),
        )

    @classmethod
    def from_sources(cls, html: str, js: str) -> SetupSnapshot:
        parser = _SetupParser()
        parser.feed(html)
        return cls(html, js, tuple(parser.nodes))

    def with_html(self, html: str) -> SetupSnapshot:
        return self.from_sources(html, self.js)

    def with_js(self, js: str) -> SetupSnapshot:
        return self.from_sources(self.html, js)


Checker = Callable[[SetupSnapshot], None]
Mutator = Callable[[SetupSnapshot], SetupSnapshot]


@dataclass(frozen=True)
class SetupSchemaRow:
    row_id: str
    title: str
    checker: Checker
    mutator: Mutator


def _nodes(
    snapshot: SetupSnapshot,
    *,
    tag: str | None = None,
    node_id: str | None = None,
    attr: str | None = None,
    value: str | None = None,
) -> list[HtmlNode]:
    matches = []
    for node in snapshot.nodes:
        if tag is not None and node.tag != tag:
            continue
        if node_id is not None and node.attr("id") != node_id:
            continue
        if attr is not None and not node.has_attr(attr):
            continue
        if value is not None and node.attr(attr or "") != value:
            continue
        matches.append(node)
    return matches


def _one(snapshot: SetupSnapshot, *, tag: str | None = None, node_id: str | None = None) -> HtmlNode:
    matches = _nodes(snapshot, tag=tag, node_id=node_id)
    _require(len(matches) == 1, f"expected one {tag or 'element'} {node_id or ''}, found {len(matches)}")
    return matches[0]


def _inside(node: HtmlNode, ancestor_id: str) -> bool:
    return any(ancestor.attr("id") == ancestor_id for ancestor in node.ancestors())


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
    return source[match.start() : opening] + _extract_braced(source, opening)


def _js_listener(source: str, marker: str) -> str:
    start = source.find(marker)
    _require(start >= 0, f"missing JavaScript listener {marker}")
    opening = source.find("{", start + len(marker))
    return source[start:opening] + _extract_braced(source, opening)


def _js_object(source: str, name: str) -> str:
    match = re.search(rf"\bvar\s+{re.escape(name)}\s*=\s*\{{", source)
    _require(match is not None, f"missing JavaScript object {name}")
    opening = source.find("{", match.start())
    return _extract_braced(source, opening)


def _js_branch(source: str, marker: str) -> str:
    start = source.find(marker)
    _require(start >= 0, f"missing JavaScript branch {marker}")
    opening = source.find("{", start + len(marker))
    return source[start:opening] + _extract_braced(source, opening)


def _extract_parenthesized(source: str, opening: int) -> str:
    _require(opening >= 0 and source[opening] == "(", "expected JavaScript opening parenthesis")
    depth = 0
    quote = ""
    escaped = False
    index = opening
    while index < len(source):
        char = source[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return source[opening : index + 1]
        index += 1
    raise AssertionError("unterminated JavaScript call")


def _split_top_level(source: str, delimiter: str = ",") -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    stack: list[str] = []
    pairs = {")": "(", "}": "{", "]": "["}
    quote = ""
    escaped = False
    for index, char in enumerate(source):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "'\"`":
            quote = char
        elif char in "({[":
            stack.append(char)
        elif char in ")}]":
            _require(bool(stack) and stack[-1] == pairs[char], "unbalanced JavaScript expression")
            stack.pop()
        elif char == delimiter and not stack:
            parts.append(source[start:index].strip())
            start = index + 1
    _require(not quote and not stack, "unbalanced JavaScript expression")
    parts.append(source[start:].strip())
    return tuple(parts)


def _call_arguments_at(source: str, opening: int) -> tuple[str, ...]:
    call = _extract_parenthesized(source, opening)
    inner = call[1:-1].strip()
    return _split_top_level(inner) if inner else ()


def _calls(source: str, name: str) -> tuple[tuple[str, ...], ...]:
    found = []
    for match in re.finditer(rf"\b{re.escape(name)}\s*\(", source):
        opening = source.find("(", match.start())
        found.append(_call_arguments_at(source, opening))
    return tuple(found)


def _object_entries(source: str) -> dict[str, str]:
    value = source.strip()
    _require(value.startswith("{") and value.endswith("}"), f"expected object literal, got {value}")
    inner = value[1:-1].strip()
    if not inner:
        return {}
    entries: dict[str, str] = {}
    for entry in _split_top_level(inner):
        key_value = _split_top_level(entry, ":")
        _require(len(key_value) == 2, f"expected one key/value pair: {entry}")
        key = key_value[0].strip().strip("'\"")
        _require(key not in entries, f"duplicate object key: {key}")
        entries[key] = key_value[1].strip()
    return entries


def _require_object_shape(source: str, keys: tuple[str, ...], label: str) -> dict[str, str]:
    entries = _object_entries(source)
    _require(tuple(entries) == keys, f"{label} keys drifted: {tuple(entries)}")
    return entries


def _post_call(source: str, api_key: str) -> tuple[str, ...]:
    matches = [args for args in _calls(source, "postJson") if args and args[0] == f"API.{api_key}"]
    _require(len(matches) == 1, f"expected one postJson owner for API.{api_key}")
    _require(len(matches[0]) == 3, f"API.{api_key} postJson arity drifted")
    return matches[0]


def _replace_once(source: str, old: str, new: str) -> str:
    _require(source.count(old) == 1, f"causal mutant target must occur once: {old}")
    return source.replace(old, new, 1)


def _check_wizard_topology(snapshot: SetupSnapshot) -> None:
    order_match = re.search(r"var STEP_ORDER\s*=\s*\[([^]]+)\]", snapshot.js)
    _require(order_match is not None, "missing STEP_ORDER")
    source_order = tuple(re.findall(r"['\"]([^'\"]+)['\"]", order_match.group(1)))
    _require(source_order == STEP_ORDER, f"unexpected STEP_ORDER: {source_order}")

    panels = _nodes(snapshot, tag="section", attr="data-step")
    _require(tuple(panel.attr("data-step") for panel in panels) == STEP_ORDER, "panel order drifted")
    for index, panel in enumerate(panels):
        step = STEP_ORDER[index]
        _require(panel.attr("id") == f"step-{step}", f"{step} panel id mismatch")
        _require(panel.has_attr("hidden") == (index > 0), f"{step} initial visibility mismatch")

    rail = _nodes(snapshot, tag="button", attr="data-step-target")
    _require(tuple(button.attr("data-step-target") for button in rail) == STEP_ORDER, "rail order drifted")
    for index, button in enumerate(rail):
        _require(button.attr("type") == "button", "rail controls must not submit forms")
        _require(button.has_attr("disabled") == (index > 0), "rail unlock topology drifted")
        _require(
            (button.attr("aria-current") == "step") == (index == 0),
            "only the operator rail control may start current",
        )

    expected_forms = {
        "operator-form": ("step-operator", "create-operator"),
        "discovery-form": ("step-connect", "start-discovery"),
        "credentials-form": ("step-credentials", "save-credentials"),
        "launch-form": ("step-launch", "start-init"),
    }
    forms = _nodes(snapshot, tag="form")
    _require({form.attr("id") for form in forms} == set(expected_forms), "setup form inventory drifted")
    for form_id, (panel_id, submit_id) in expected_forms.items():
        form = _one(snapshot, tag="form", node_id=form_id)
        _require(_inside(form, panel_id), f"{form_id} left {panel_id}")
        submits = [
            node
            for node in snapshot.nodes
            if node.tag == "button" and node.attr("type") == "submit" and _inside(node, form_id)
        ]
        _require([node.attr("id") for node in submits] == [submit_id], f"{form_id} submit owner drifted")


def _check_control_action_closure(snapshot: SetupSnapshot) -> None:
    direct_button_ids = {
        "save-contract",
        "retry-session",
        "retry-init",
        "cancel-init",
        "refresh-logs",
        "refresh-status",
    }
    exact_bindings = (
        "$('operator-form').addEventListener('submit',createOperator);",
        "$('discovery-form').addEventListener('submit',startDiscovery);",
        "$('credentials-form').addEventListener('submit',saveCredentials);",
        "$('launch-form').addEventListener('submit',startInit);",
        "$('save-contract').addEventListener('click',saveContract);",
        "$('retry-session').addEventListener('click',checkSession);",
        "$('retry-init').addEventListener('click',prepareInitRetry);",
        "$('cancel-init').addEventListener('click',requestInitCancellation);",
        "$('refresh-logs').addEventListener('click',refreshLogs);",
        "$('refresh-status').addEventListener('click',function(){refreshStatus(false).catch(function(){});});",
    )
    for binding in exact_bindings:
        _require(snapshot.js.count(binding) == 1, f"missing or duplicate binding: {binding}")

    buttons = _nodes(snapshot, tag="button")
    actual_direct_ids = {
        button.attr("id")
        for button in buttons
        if button.attr("type") == "button" and button.attr("id")
    }
    _require(actual_direct_ids == direct_button_ids, f"direct button inventory drifted: {actual_direct_ids}")
    for button in buttons:
        if button.attr("type") != "button":
            continue
        owners = (
            button.has_attr("data-step-target"),
            button.has_attr("data-action"),
            "filter-btn" in button.classes(),
            button.attr("id") in direct_button_ids,
        )
        _require(sum(owners) == 1, f"unowned or multiply owned button: {button.attr('id') or button.text()}")

    row_change = _js_listener(snapshot.js, "$('resource-rows').addEventListener('change',function(event)")
    for token in ("selectionChanged(event.target)", "placementChanged(event.target)"):
        _require(row_change.count(token) == 1, f"resource-row dispatch lost {token}")

    click = _js_listener(snapshot.js, "document.addEventListener('click',function(event)")
    for token in (
        "target.dataset.stepTarget",
        "showStep(target.dataset.stepTarget)",
        "target.classList.contains('filter-btn')",
        "filterRows(target.dataset.filter)",
    ):
        _require(token in click, f"click delegator lost {token}")
    branches = tuple(re.findall(r"if\(action==='([^']+)'\)", click))
    _require(branches == ("add-node", "remove-node", "back", "rediscover"), "action branches drifted")

    html_actions = {node.attr("data-action") for node in snapshot.nodes if node.has_attr("data-action")}
    add_node = _js_function(snapshot.js, "addNode")
    _require("remove.dataset.action='remove-node'" in add_node, "remove-node producer is missing")
    _require(html_actions | {"remove-node"} == set(branches), "control/action inventory is not closed")
    _require("if(rows.length>1)" in click, "the final declared node must not be removable")


def _check_endpoint_transport(snapshot: SetupSnapshot) -> None:
    expected = {
        "status": "/api/setup/status",
        "verify": "/api/auth/verify",
        "createAdmin": "/api/setup/create-admin",
        "discoveryStart": "/api/setup/discovery/start",
        "discoveryStatus": "/api/setup/discovery/status",
        "contract": "/api/setup/contract",
        "credentials": "/api/setup/device-credentials",
        "initStart": "/api/setup/init/start",
        "initCancel": "/api/setup/init/cancel",
        "initStatus": "/api/setup/init/status",
        "initLogs": "/api/setup/init/logs",
    }
    api = _js_object(snapshot.js, "API")
    actual = dict(re.findall(r"\b([A-Za-z][A-Za-z0-9]*):\s*'([^']+)'", api))
    _require(actual == expected, f"setup API registry drifted: {actual}")
    _require(sorted(re.findall(r"['\"](/api/[^'\"]+)['\"]", snapshot.js)) == sorted(expected.values()), "literal API bypass or dead registry path")

    expected_calls = {
        "createOperator": (("postJson", "createAdmin", "false"),),
        "verifySession": (("getJson", "verify", ""),),
        "startDiscovery": (("postJson", "discoveryStart", "true"),),
        "pollDiscovery": (("getJson", "discoveryStatus", ""),),
        "saveContract": (("postJson", "contract", "true"),),
        "saveCredentials": (("postJson", "credentials", "true"),),
        "startInit": (("postJson", "initStart", "true"),),
        "requestInitCancellation": (("postJson", "initCancel", "true"),),
        "pollInit": (("getJson", "initStatus", ""), ("getJson", "status", "")),
        "refreshLogs": (("getJson", "initLogs", ""),),
        "confirmCompletion": (("getJson", "status", ""),),
        "loadDiscovery": (("getJson", "discoveryStatus", ""),),
        "loadContract": (("getJson", "contract", ""),),
        "refreshStatus": (("getJson", "status", ""),),
    }
    function_names = re.findall(r"(?m)^  function ([A-Za-z][A-Za-z0-9_]*)\(", snapshot.js)
    for function_name in function_names:
        if function_name in {"getJson", "postJson"}:
            continue
        block = _js_function(snapshot.js, function_name)
        observed = []
        for match in re.finditer(r"\b(getJson|postJson)\s*\(", block):
            kind = match.group(1)
            args = _call_arguments_at(block, block.find("(", match.start()))
            _require(args, f"{function_name} has an empty {kind} call")
            api_match = re.match(r"API\.([A-Za-z][A-Za-z0-9_]*)", args[0])
            _require(api_match is not None, f"{function_name} bypasses the API registry")
            if kind == "postJson":
                _require(len(args) == 3 and args[2] in {"true", "false"}, f"{function_name} POST auth shape drifted")
                authenticated = args[2]
            else:
                _require(len(args) == 1, f"{function_name} GET shape drifted")
                authenticated = ""
            observed.append((kind, api_match.group(1), authenticated))
        _require(tuple(observed) == expected_calls.get(function_name, ()), f"{function_name} request ownership drifted: {observed}")
    expected_call_count = sum(len(calls) for calls in expected_calls.values())
    global_call_count = len(
        re.findall(r"(?<!function )\b(?:getJson|postJson)\s*\(", snapshot.js)
    )
    _require(
        global_call_count == expected_call_count,
        "getJson/postJson call exists outside its declared function owner",
    )

    request = _js_function(snapshot.js, "request")
    timer_calls = _calls(request, "window.setTimeout")
    _require(
        timer_calls == (("function(){controller.abort();}", "timeoutMs || 20000"),),
        "request timeout must schedule a real bounded abort",
    )
    post_json = _js_function(snapshot.js, "postJson")
    for token in ("AbortController", "opts.credentials='same-origin'", "'Accept':'application/json'", "controller.abort()"):
        _require(token in request, f"request transport lost {token}")
    for token in ("if(!model.csrf)", "Promise.reject", "headers['X-Freq-CSRF']=model.csrf"):
        _require(token in post_json, f"authenticated mutation transport lost {token}")
    headers = _require_object_shape(_js_object(post_json, "headers"), ("Content-Type",), "POST headers")
    _require(headers["Content-Type"] == "'application/json'", "POST content type must be JSON")
    post_request = _calls(post_json, "request")
    _require(len(post_request) == 1 and len(post_request[0]) == 3, "postJson must have one request call")
    _require(post_request[0][0] == "url" and post_request[0][2] == "30000", "postJson request/timeout drifted")
    options = _require_object_shape(post_request[0][1], ("method", "headers", "body"), "POST request")
    _require(options == {"method": "'POST'", "headers": "headers", "body": "JSON.stringify(payload)"}, "POST must serialize JSON exactly")
    get_json = _js_function(snapshot.js, "getJson")
    get_request = _calls(get_json, "request")
    _require(len(get_request) == 1 and get_request[0][0] == "url" and get_request[0][2] == "15000", "getJson request/timeout drifted")
    _require(
        _require_object_shape(get_request[0][1], ("method",), "GET request") == {"method": "'GET'"},
        "getJson must issue GET",
    )


def _check_operator_session(snapshot: SetupSnapshot) -> None:
    form = _one(snapshot, tag="form", node_id="operator-form")
    _require(
        form.attr("method") == "post" and form.attr("action") is None and form.has_attr("novalidate"),
        "operator form transport semantics drifted",
    )
    claim = _one(snapshot, tag="input", node_id="operator-claim")
    _require(_inside(claim, "operator-form"), "first-boot claim control left the operator form")
    _require(
        claim.attr("type") == "password"
        and claim.attr("name") is None
        and claim.attr("autocomplete") == "off"
        and claim.attr("autocapitalize") == "none"
        and claim.attr("spellcheck") == "false"
        and claim.attr("aria-describedby") == "operator-claim-help"
        and claim.attr("data-api-field") == "claim_secret"
        and claim.has_attr("required"),
        "first-boot claim control lost its secret-safe form contract",
    )
    create = _js_function(snapshot.js, "createOperator")
    create_call = _post_call(create, "createAdmin")
    create_payload = _require_object_shape(
        create_call[1],
        ("schema", "username", "password", "claim_secret", "client_request_id"),
        "create-admin payload",
    )
    _require(
        create_payload
        == {
            "schema": "SCHEMA",
            "username": "trim('operator-user').toLowerCase()",
            "password": "$('operator-pass').value",
            "claim_secret": "$('operator-claim').value",
            "client_request_id": "uuid()",
        },
        "create-admin payload values drifted",
    )
    _require(create.index("validateOperator()") < create.index("postJson(API.createAdmin"), "operator validation must precede mutation")
    for token in (
        "schema:SCHEMA",
        "username:trim('operator-user').toLowerCase()",
        "password:$('operator-pass').value",
        "claim_secret:$('operator-claim').value",
        "client_request_id:uuid()",
    ):
        _require(token in create, f"create operator payload lost {token}")
    guard = "if(!data.session_started || !data.csrf_token)"
    for token in (guard, "rememberSession(data)", "advance('connect')"):
        _require(token in create, f"operator handoff lost {token}")
    _require(create.index(guard) < create.index("rememberSession(data)") < create.index("advance('connect')"), "unproved operator session can advance")
    _require("trim('operator-claim')" not in create, "first-boot claim must retain its exact submitted bytes")
    _require(
        create.index("$('operator-claim').value=''") < create.index("advance('connect')"),
        "first-boot claim must clear before the setup advances",
    )
    for token in ("error.code==='operator_exists'", "$('resume-session').hidden=false", "setError(error.message,'',error.details)"):
        _require(token in create, f"operator failure path lost {token}")
    _require("startDiscovery" not in create and "startInit" not in create, "operator failure may not continue setup")

    remember = _js_function(snapshot.js, "rememberSession")
    _require("model.csrf=text(data.csrf_token)" in remember, "session handoff must retain CSRF")
    verify = _js_function(snapshot.js, "verifySession")
    _require("!data.valid || data.role!=='admin'" in verify, "setup resume must require a valid admin")
    check = _js_function(snapshot.js, "checkSession")
    _require("verifySession().then(function(){return refreshStatus(true);})" in check, "retry session must verify before resume")


def _check_discovery_contract(snapshot: SetupSnapshot) -> None:
    validate = _js_function(snapshot.js, "validateDiscovery")
    for token in (
        "nodes.length<1 || nodes.length>16",
        "if(unique[nodes[i].host])",
        "unique[nodes[i].host]=true",
    ):
        _require(token in validate, f"discovery validation lost {token}")

    start = _js_function(snapshot.js, "startDiscovery")
    discovery_call = _post_call(start, "discoveryStart")
    discovery_payload = _require_object_shape(
        discovery_call[1],
        ("schema", "setup_id", "client_request_id", "cluster", "bootstrap"),
        "discovery payload",
    )
    _require(
        _require_object_shape(discovery_payload["cluster"], ("name", "nodes"), "discovery cluster")
        == {"name": "trim('cluster-name')", "nodes": "collectNodes()"},
        "discovery cluster values drifted",
    )
    _require(
        _require_object_shape(discovery_payload["bootstrap"], ("username", "password"), "discovery bootstrap")
        == {
            "username": "trim('bootstrap-user')",
            "password": "$('bootstrap-pass').value",
        },
        "discovery bootstrap values drifted",
    )
    for token in (
        "schema:SCHEMA,setup_id:model.setupId,client_request_id:uuid()",
        "cluster:{name:trim('cluster-name'),nodes:collectNodes()}",
        "bootstrap:{username:trim('bootstrap-user'),password:$('bootstrap-pass').value}",
        "model.discoveryId=text(data.discovery && data.discovery.id)",
        "$('bootstrap-pass').value=''",
    ):
        _require(token in start, f"discovery request lost {token}")

    poll = _js_function(snapshot.js, "pollDiscovery")
    _require("encodeURIComponent(model.discoveryId)" in poll, "discovery poll must carry the returned ID")
    _require("if(discovery.state==='succeeded')" in poll and "renderDiscovery(discovery)" in poll, "only succeeded discovery may render")
    _require("if(discovery.state==='failed')" in poll and "scheduleDiscovery" in poll, "discovery terminal branches are incomplete")
    _require(poll.count("renderDiscovery(discovery)") == 1, "pollDiscovery must have one succeeded render")
    poll_success = _js_branch(poll, "if(discovery.state==='succeeded')")
    _require("renderDiscovery(discovery)" in poll_success, "pollDiscovery rendered outside succeeded state")

    load = _js_function(snapshot.js, "loadDiscovery")
    _require(load.count("renderDiscovery(discovery)") == 1, "loadDiscovery must have one succeeded render")
    load_success = _js_branch(load, "if(discovery.state==='succeeded')")
    _require("renderDiscovery(discovery)" in load_success, "loadDiscovery rendered outside succeeded state")

    row = _js_function(snapshot.js, "renderResourceRow")
    for token in (
        "var unknown=group==='device' && item.kind==='unknown'",
        "input.disabled=unknown && value==='owned'",
        "model.selections[id]={resource_id:id,disposition:target.value}",
    ):
        _require(token in row + _js_function(snapshot.js, "selectionChanged"), f"explicit selection law lost {token}")

    count = _js_function(snapshot.js, "updateReviewCount")
    _require("choice.disposition==='acknowledged'" in count, "acknowledgement must complete a decision")
    _require("choice.disposition==='owned' && choice.placement" in count, "owned rows require placement")
    _require("!model.discovery || complete!==rows.length" in count, "save must require succeeded discovery and complete rows")

    save = _js_function(snapshot.js, "saveContract")
    contract_call = _post_call(save, "contract")
    contract_payload = _require_object_shape(
        contract_call[1],
        ("schema", "setup_id", "discovery_id", "client_request_id", "selections"),
        "contract payload",
    )
    _require(
        contract_payload
        == {
            "schema": "SCHEMA",
            "setup_id": "model.setupId",
            "discovery_id": "model.discoveryId",
            "client_request_id": "uuid()",
            "selections": "Object.keys(model.selections).map(function(id){return model.selections[id];})",
        },
        "contract payload values drifted",
    )
    for token in (
        "schema:SCHEMA",
        "setup_id:model.setupId",
        "discovery_id:model.discoveryId",
        "client_request_id:uuid()",
        "selections:Object.keys(model.selections).map",
    ):
        _require(token in save, f"contract payload lost {token}")
    render = _js_function(snapshot.js, "renderDiscovery")
    _require("if(!rows.length)" in render and "empty-resource-row" in render, "explicit empty discovery surface is missing")


def _check_credentials(snapshot: SetupSnapshot) -> None:
    card = _js_function(snapshot.js, "credentialCard")
    for token in (
        "requirement.required_any",
        "requirement.stored_fields",
        "device.credential_fields",
        "input.dataset.credentialField=name",
    ):
        _require(token in card, f"server-shaped credential controls lost {token}")

    collect = _js_function(snapshot.js, "collectCredentials")
    for token in (
        "var item={resource_id:card.dataset.resourceId,secrets:{}}",
        "if(field==='username'){item.username=value.trim();}else{item.secrets[field]=value;}",
        "card.dataset.apiField='credentials['+index+'].resource_id'",
        "field==='username'?'username':'secrets.'+field",
    ):
        _require(token in collect, f"credential request/error schema lost {token}")

    save = _js_function(snapshot.js, "saveCredentials")
    credential_call = _post_call(save, "credentials")
    credential_payload = _require_object_shape(
        credential_call[1],
        ("schema", "setup_id", "contract_id", "client_request_id", "credentials"),
        "credential payload",
    )
    _require(
        credential_payload
        == {
            "schema": "SCHEMA",
            "setup_id": "model.setupId",
            "contract_id": "model.contractId",
            "client_request_id": "uuid()",
            "credentials": "collectCredentials()",
        },
        "credential payload values drifted",
    )
    _require("if(!requirements.length){renderContractSummary();advance('launch');return;}" in save, "empty requirements must bypass credential POST")
    for token in (
        "schema:SCHEMA",
        "setup_id:model.setupId",
        "contract_id:model.contractId",
        "client_request_id:uuid()",
        "credentials:collectCredentials()",
        "clearCredentialInputs();mergeCredentialPresence(data.credentials);model.contract.ready=!!data.ready",
        ".catch(function(error){clearCredentialInputs();setError(error.message,error.field,error.details);}",
    ):
        _require(token in save, f"credential storage path lost {token}")

    merge = _js_function(snapshot.js, "mergeCredentialPresence")
    _require("requirement.stored_fields=Array.isArray(update.stored_fields)?update.stored_fields.slice():[]" in merge, "stored presence must merge")
    _require("requirement.complete=!!update.complete" in merge, "credential completeness must merge")
    request = _js_function(snapshot.js, "request")
    error = _js_function(snapshot.js, "setError")
    _require("failure.details=detail.details" in request, "structured API details must survive transport")
    _require("[data-api-field=\"'+CSS.escape(field)+'\"]" in error, "structured errors must focus generated fields")


def _check_init_recovery(snapshot: SetupSnapshot) -> None:
    _require("var DEFAULT_SERVICE_ACCOUNT = 'freq-admin';" in snapshot.js, "service identity default drifted")
    start = _js_function(snapshot.js, "startInit")
    init_call = _post_call(start, "initStart")
    init_payload = _require_object_shape(
        init_call[1],
        (
            "schema",
            "setup_id",
            "discovery_id",
            "contract_id",
            "client_request_id",
            "service_account",
            "options",
        ),
        "init payload",
    )
    _require(
        _require_object_shape(init_payload["service_account"], ("username", "password"), "service account")
        == {
            "username": "trim('service-account')",
            "password": "$('service-pass').value",
        },
        "service-account values drifted",
    )
    options = _require_object_shape(init_payload["options"], ("ssh_mode", "pdm", "ssl"), "init options")
    _require(options["ssh_mode"] == "'sudo'", "init SSH mode drifted")
    _require(_require_object_shape(options["pdm"], ("mode",), "PDM option") == {"mode": "'skip'"}, "PDM mode drifted")
    _require(_require_object_shape(options["ssl"], ("mode",), "SSL option") == {"mode": "'defer'"}, "SSL mode drifted")
    for token in (
        "schema:SCHEMA",
        "setup_id:model.setupId",
        "discovery_id:model.discoveryId",
        "contract_id:model.contractId",
        "client_request_id:uuid()",
        "service_account:{username:trim('service-account'),password:$('service-pass').value}",
        "options:{ssh_mode:'sudo',pdm:{mode:'skip'},ssl:{mode:'defer'}}",
        "model.initJobId=text(data.job && data.job.id)",
        "advance('progress')",
        "scheduleInit(data.job && data.job.poll_after_ms)",
    ):
        _require(token in start, f"init launch lost {token}")
    _require(start.count("$('service-pass').value=''") == 2, "service password must clear on both outcomes")
    _require(start.count("$('service-pass2').value=''") == 2, "service confirmation must clear on both outcomes")

    poll = _js_function(snapshot.js, "pollInit")
    logs = _js_function(snapshot.js, "refreshLogs")
    _require("encodeURIComponent(model.initJobId)" in poll, "init status must use accepted job ID")
    _require("encodeURIComponent(model.initJobId)" in logs, "init logs must use accepted job ID")
    failure = _js_function(snapshot.js, "showInitFailure")
    _require("$('retry-init').hidden=false" in failure and "$('completion-card').hidden=true" in failure, "failed init must expose retry without completion")

    retry = _js_function(snapshot.js, "prepareInitRetry")
    chain = "verifySession().then(function(){return loadDiscovery();}).then(loadContract)"
    _require(chain in retry, "retry must verify session, then reload discovery and contract")
    _require("renderCredentials()" in retry and "advance('launch')" in retry, "retry must rebuild readiness before launch")
    _require("startInit" not in retry and "API.initStart" not in retry, "bounded recovery must not auto-start init")


def _check_completion_state(snapshot: SetupSnapshot) -> None:
    poll = _js_function(snapshot.js, "pollInit")
    marker_gate = "if(!job.initialized || !job.web_setup_complete)"
    _require(marker_gate in poll, "succeeded jobs require both durable markers")
    _require(poll.index(marker_gate) < poll.index("confirmCompletion()"), "job markers must precede final verification")

    confirm = _js_function(snapshot.js, "confirmCompletion")
    final_gate = "status.state!=='complete' || !status.initialized || !status.web_setup_complete"
    _require(final_gate in confirm, "setup/status must prove state and both markers")
    _require(confirm.index(final_gate) < confirm.index("$('completion-card').hidden=false"), "completion card revealed before final truth")

    verified = _js_function(snapshot.js, "statusVerifiedComplete")
    for token in ("status.state==='complete'", "status.initialized===true", "status.web_setup_complete===true"):
        _require(token in verified, f"resumed completion lost {token}")
    resume = _js_function(snapshot.js, "resumeFromStatus")
    _require("if(!statusVerifiedComplete(status))" in resume, "resumed complete state must use durable marker predicate")
    for state in ("collecting", "discovering", "selecting", "credentials", "ready", "initializing", "blocked"):
        _require(f"state==='{state}'" in resume, f"resume state missing {state}")
    discovering = _js_branch(resume, "if(state==='discovering')")
    _require(
        "model.discoveryId=text(status.active_discovery_id)" in discovering
        and "model.contractId=" not in discovering
        and "model.initJobId=" not in discovering,
        "discovering must consume only active_discovery_id",
    )
    selecting = _js_branch(resume, "if(state==='selecting')")
    _require(
        "model.discoveryId=text(status.active_discovery_id)" in selecting,
        "selecting must consume active_discovery_id",
    )
    credentials = _js_branch(resume, "if(state==='credentials' || state==='ready')")
    _require(
        "model.discoveryId=text(status.active_discovery_id)" in credentials
        and "model.contractId=text(status.active_contract_id)" in credentials,
        "credential/ready recovery must consume discovery and contract IDs",
    )
    initializing = _js_branch(resume, "if(state==='initializing')")
    _require(
        "model.initJobId=text(status.active_init_job_id)" in initializing
        and "model.discoveryId=" not in initializing
        and "model.contractId=" not in initializing,
        "initializing must consume only active_init_job_id",
    )
    blocked = _js_branch(resume, "if(state==='blocked')")
    active_init = _js_branch(blocked, "if(status.active_init_job_id)")
    active_discovery = _js_branch(blocked, "else if(status.active_discovery_id)")
    _require(
        "model.initJobId=text(status.active_init_job_id)" in active_init,
        "blocked init recovery must consume active_init_job_id",
    )
    _require(
        "model.discoveryId=text(status.active_discovery_id)" in active_discovery,
        "blocked discovery recovery must consume active_discovery_id",
    )


def _check_init_cancellation_consumer(snapshot: SetupSnapshot) -> None:
    button = _one(snapshot, tag="button", node_id="cancel-init")
    _require(_inside(button, "step-progress"), "cancellation control must stay in progress panel")
    _require(button.attr("type") == "button", "cancellation control must not submit a form")
    _require(button.attr("aria-describedby") == "cancellation-status", "cancellation control lost status description")
    _require(button.has_attr("hidden") and button.has_attr("disabled"), "cancellation control must start inert")

    status = _one(snapshot, node_id="cancellation-status")
    _require(_inside(status, "step-progress"), "cancellation status must stay in progress panel")
    _require(status.attr("role") == "status", "cancellation status must expose status semantics")
    _require(status.attr("aria-live") == "polite" and status.attr("aria-atomic") == "true", "cancellation status must be polite and atomic")

    renderer = _js_function(snapshot.js, "renderInitCancellation")
    for token in (
        "active=state==='queued' || state==='running'",
        "if(!active)",
        "if(!requested && delivery==='not_requested')",
        "if(requested && delivery==='pending')",
        "if(requested && delivery==='delivered')",
        "if(requested && delivery==='failed' && retryable)",
        "if(requested && delivery==='failed')",
        "button.textContent='Retry cancellation';button.disabled=false",
        "button.textContent='Cancellation requested'",
        "button.textContent='Cancellation delivered'",
        "button.hidden=true",
    ):
        _require(token in renderer, f"cancellation truth table lost {token}")
    _require(renderer.index("button.disabled=true") < renderer.index("if(!active)"), "cancellation renderer must fail closed before state branches")
    for forbidden in ("confirmCompletion", "showInitFailure", "completion-card", "progress-state"):
        _require(forbidden not in renderer, f"cancellation status must not mutate ordinary job truth: {forbidden}")
    for copy in (
        "Init has not been assumed stopped.",
        "Waiting for authoritative job status; init has not been assumed stopped.",
        "The terminal job state is authoritative.",
    ):
        _require(copy in renderer, f"cancellation truth copy lost: {copy}")

    request = _js_function(snapshot.js, "requestInitCancellation")
    cancel_call = _post_call(request, "initCancel")
    _require(cancel_call[2] == "true", "cancellation mutation must use authenticated CSRF transport")
    _require(
        _require_object_shape(cancel_call[1], ("id",), "cancellation payload") == {"id": "model.initJobId"},
        "cancellation payload must contain only the accepted init job ID",
    )
    for token in (
        "cancellation.job_id!==model.initJobId",
        "cancellation.state!=='requested'",
        "scheduleInit(cancellation.poll_after_ms || 250)",
        "error.status===409 && error.code==='init_not_running'",
        "error.status===503 && error.code==='init_cancel_delivery_failed'",
        "setError(error.message,error.field,error.details)",
    ):
        _require(token in request, f"cancellation request handling lost {token}")
    for forbidden in ("confirmCompletion", "showInitFailure", "completion-card", "initialized", "web_setup_complete"):
        _require(forbidden not in request, f"cancellation request made an optimistic terminal claim: {forbidden}")
    accepted = _js_branch(request, "if(cancellation.job_id!==model.initJobId || cancellation.state!=='requested')")
    _require("No stop was assumed" in accepted, "invalid cancellation acceptance must remain nonterminal")
    terminal_race = _js_branch(request, "if(error.status===409 && error.code==='init_not_running')")
    _require("scheduleInit(0)" in terminal_race and "button.hidden=true" in terminal_race, "terminal cancellation race must refresh authoritative status")
    delivery_failure = _js_branch(request, "if(error.status===503 && error.code==='init_cancel_delivery_failed')")
    _require(
        "button.disabled=false" in delivery_failure
        and "button.textContent='Retry cancellation'" in delivery_failure
        and "scheduleInit(0)" in delivery_failure,
        "retryable cancellation failure must stay visible and refresh status",
    )
    _require(
        "setError(error.message,error.field,error.details);\n      scheduleInit(0);" in request,
        "other cancellation errors must use the existing transport and resume authoritative polling",
    )

    poll = _js_function(snapshot.js, "pollInit")
    _require(poll.count("renderInitCancellation(job)") == 1, "init polling must consume cancellation exactly once")
    _require(
        poll.index("renderInitCancellation(job)") < poll.index("if(job.state==='succeeded')")
        and poll.index("renderInitCancellation(job)") < poll.index("if(job.state==='failed')"),
        "terminal job branches must consume authoritative cancellation first",
    )
    start = _js_function(snapshot.js, "startInit")
    _require(
        "$('cancel-init').hidden=true" in start
        and "$('cancel-init').disabled=true" in start,
        "a new init must reset stale cancellation controls",
    )


def _check_transport_truth(snapshot: SetupSnapshot) -> None:
    heroes = [node for node in snapshot.nodes if node.tag == "header" and "setup-hero" in node.classes()]
    _require(len(heroes) == 1, "setup must have one hero")
    hero_copy = [
        node
        for node in snapshot.nodes
        if node.tag == "p" and "hero-copy" in node.classes() and heroes[0] in tuple(node.ancestors())
    ]
    _require(len(hero_copy) == 1, "setup hero must have one transport summary")
    hero = hero_copy[0].text()
    for fact in ("without opening a shell", "hand-editing config files", "typing VMID ranges"):
        _require(fact.lower() in hero.lower(), f"hero lost setup transport fact: {fact}")
    _require("browser and programmatic" in hero.lower(), "hero lost shared first-admin transport truth")
    _require(re.search(r"\bwithout\s+(?:using\s+)?ssh\b", hero, re.IGNORECASE) is None, "hero falsely claims setup avoids backend SSH")

    connect = _one(snapshot, tag="section", node_id="step-connect")
    connect_copy = connect.text()
    for fact in (
        "operator's existing SSH login",
        "used only to reach the declared nodes",
        "service identity is created separately",
    ):
        _require(fact in connect_copy, f"Connect lost bootstrap/service transport truth: {fact}")
    expected_fields = {
        "bootstrap-user": ("Bootstrap SSH user", "bootstrap_user"),
        "bootstrap-pass": ("Bootstrap SSH password", "bootstrap_password"),
    }
    for field_id, (label_text, field_name) in expected_fields.items():
        labels = [node for node in snapshot.nodes if node.tag == "label" and node.attr("for") == field_id]
        _require(len(labels) == 1 and label_text in labels[0].text(), f"missing explicit {label_text} label")
        field = _one(snapshot, tag="input", node_id=field_id)
        _require(field.attr("name") == field_name and _inside(field, "step-connect"), f"{field_id} transport field drifted")
    start = _js_function(snapshot.js, "startDiscovery")
    _require(
        "bootstrap:{username:trim('bootstrap-user'),password:$('bootstrap-pass').value}" in start,
        "operator copy no longer matches discovery transport",
    )


def _mutate_topology(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_html(
        _replace_once(snapshot.html, 'data-step-target="credentials"', 'data-step-target="credential"')
    )


def _mutate_action_binding(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "$('refresh-logs').addEventListener('click',refreshLogs);",
            "$('refresh-logs').addEventListener('click',refreshStatus);",
        )
    )


def _mutate_endpoint(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(snapshot.js, "initLogs: '/api/setup/init/logs'", "initLogs: '/api/setup/init/status'")
    )


def _mutate_operator_guard(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "if(!data.session_started || !data.csrf_token){throw new Error('The operator was not given an authenticated setup session.');}",
            "if(false){throw new Error('The operator was not given an authenticated setup session.');}",
        )
    )


def _mutate_unknown_ownership(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "input.disabled=unknown && value==='owned'",
            "input.disabled=false",
        )
    )


def _mutate_credential_path(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(snapshot.js, "'username':'secrets.'+field", "'username':'secret.'+field")
    )


def _mutate_retry_session(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "verifySession().then(function(){return loadDiscovery();}).then(loadContract)",
            "Promise.resolve().then(function(){return loadDiscovery();}).then(loadContract)",
        )
    )


def _mutate_completion_gate(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "if(!job.initialized || !job.web_setup_complete)",
            "if(!job.initialized && !job.web_setup_complete)",
        )
    )


def _mutate_transport_copy(snapshot: SetupSnapshot) -> SetupSnapshot:
    corrected = "without opening a shell, hand-editing config files, or typing VMID ranges"
    return snapshot.with_html(_replace_once(snapshot.html, corrected, "without SSH, config files, or typed VMID ranges"))


def _mutate_cancellation_terminal_gate(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "active=state==='queued' || state==='running'",
            "active=true",
        )
    )


def _review_inert_timeout(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "window.setTimeout(function(){controller.abort();},timeoutMs || 20000)",
            "(function(){controller.abort();},0)",
        )
    )


def _review_missing_content_type(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(snapshot.js, "var headers={'Content-Type':'application/json'}", "var headers={}")
    )


def _review_raw_post_body(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(snapshot.js, "body:JSON.stringify(payload)", "body:payload")
    )


def _review_extra_unauthenticated_post(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "function createOperator(event){\n    event.preventDefault();setError('');",
            "function createOperator(event){\n    event.preventDefault();setError('');postJson(API.contract,{},false);",
        )
    )


def _review_create_extra_key(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "claim_secret:$('operator-claim').value,client_request_id:uuid()",
            "claim_secret:$('operator-claim').value,legacy_role:'admin',client_request_id:uuid()",
        )
    )


def _review_discovery_extra_key(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "cluster:{name:trim('cluster-name'),nodes:collectNodes()},\n      bootstrap:",
            "cluster:{name:trim('cluster-name'),nodes:collectNodes()},vmids:[],\n      bootstrap:",
        )
    )


def _review_contract_extra_key(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "client_request_id:uuid(),selections:Object.keys(model.selections)",
            "client_request_id:uuid(),legacy_vmids:[],selections:Object.keys(model.selections)",
        )
    )


def _review_credentials_extra_key(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "client_request_id:uuid(),credentials:collectCredentials()",
            "client_request_id:uuid(),legacy_secrets:{},credentials:collectCredentials()",
        )
    )


def _review_init_extra_key(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "client_request_id:uuid(),service_account:",
            "client_request_id:uuid(),legacy_mode:'manual',service_account:",
        )
    )


def _review_dead_button(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_html(
        _replace_once(snapshot.html, "  </nav>", '    <button id="dead-control" type="button">Dead</button>\n  </nav>')
    )


def _review_missing_direct_button(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_html(
        _replace_once(
            snapshot.html,
            '<button id="refresh-logs" class="text-btn" type="button">Refresh</button>',
            "",
        )
    )


def _review_early_discovery_render(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "model.discovery=discovery;if(discovery.state==='succeeded')",
            "model.discovery=discovery;renderDiscovery(discovery);if(discovery.state==='succeeded')",
        )
    )


def _review_initializing_wrong_id(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "if(state==='initializing'){model.initJobId=text(status.active_init_job_id);",
            "if(state==='initializing'){model.discoveryId=text(status.active_init_job_id);",
        )
    )


def _review_discovering_wrong_id(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "if(state==='discovering'){model.discoveryId=text(status.active_discovery_id);",
            "if(state==='discovering'){model.contractId=text(status.active_discovery_id);",
        )
    )


def _review_cancel_extra_key(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(snapshot.js, "{id:model.initJobId},true", "{id:model.initJobId,pid:0},true")
    )


def _review_cancel_optimistic_completion(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "scheduleInit(cancellation.poll_after_ms || 250);",
            "confirmCompletion();",
        )
    )


def _review_cancel_false_stop_copy(snapshot: SetupSnapshot) -> SetupSnapshot:
    return snapshot.with_js(
        _replace_once(
            snapshot.js,
            "The cancellation request reached the init child. Waiting for authoritative job status; init has not been assumed stopped.",
            "The cancellation request stopped init.",
        )
    )


SCHEMA_ROWS = (
    SetupSchemaRow("C03-01", "six-step wizard topology", _check_wizard_topology, _mutate_topology),
    SetupSchemaRow("C03-02", "control and action closure", _check_control_action_closure, _mutate_action_binding),
    SetupSchemaRow("C03-03", "endpoint verb and auth closure", _check_endpoint_transport, _mutate_endpoint),
    SetupSchemaRow("C03-04", "operator session handoff", _check_operator_session, _mutate_operator_guard),
    SetupSchemaRow("C03-05", "discovery and explicit contract", _check_discovery_contract, _mutate_unknown_ownership),
    SetupSchemaRow("C03-06", "server-shaped credentials", _check_credentials, _mutate_credential_path),
    SetupSchemaRow("C03-07", "init launch and bounded recovery", _check_init_recovery, _mutate_retry_session),
    SetupSchemaRow("C03-08", "durable completion and resume truth", _check_completion_state, _mutate_completion_gate),
    SetupSchemaRow("C03-09", "browser and programmatic transport truth", _check_transport_truth, _mutate_transport_copy),
    SetupSchemaRow("C03-10", "init cancellation consumer truth", _check_init_cancellation_consumer, _mutate_cancellation_terminal_gate),
)

REVIEW_MUTANTS = (
    ("inert abort timer", "C03-03", _review_inert_timeout),
    ("missing JSON content type", "C03-03", _review_missing_content_type),
    ("raw POST body", "C03-03", _review_raw_post_body),
    ("second unauthenticated POST", "C03-03", _review_extra_unauthenticated_post),
    ("extra create-admin key", "C03-04", _review_create_extra_key),
    ("extra discovery key", "C03-05", _review_discovery_extra_key),
    ("extra contract key", "C03-05", _review_contract_extra_key),
    ("extra credential key", "C03-06", _review_credentials_extra_key),
    ("extra init key", "C03-07", _review_init_extra_key),
    ("unowned button", "C03-02", _review_dead_button),
    ("missing direct button", "C03-02", _review_missing_direct_button),
    ("early discovery render", "C03-05", _review_early_discovery_render),
    ("initializing consumes wrong ID", "C03-08", _review_initializing_wrong_id),
    ("discovering consumes wrong ID", "C03-08", _review_discovering_wrong_id),
    ("cancellation payload extra key", "C03-10", _review_cancel_extra_key),
    ("optimistic cancellation completion", "C03-10", _review_cancel_optimistic_completion),
    ("false cancellation stop copy", "C03-10", _review_cancel_false_stop_copy),
)


def _failed_rows(snapshot: SetupSnapshot) -> list[str]:
    failures = []
    for row in SCHEMA_ROWS:
        try:
            row.checker(snapshot)
        except AssertionError:
            failures.append(row.row_id)
    return failures


class TestSetupSchemaTable(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = SetupSnapshot.load()

    def test_c03_setup_schema_table(self) -> None:
        self.assertEqual(
            [row.row_id for row in SCHEMA_ROWS],
            [f"C03-{number:02d}" for number in range(1, 11)],
        )
        for row in SCHEMA_ROWS:
            with self.subTest(row=row.row_id, title=row.title, phase="baseline"):
                row.checker(self.snapshot)

        for target in SCHEMA_ROWS:
            mutant = target.mutator(self.snapshot)
            with self.subTest(row=target.row_id, title=target.title, phase="causal-mutant"):
                self.assertEqual(_failed_rows(mutant), [target.row_id])

        for title, expected_row, mutator in REVIEW_MUTANTS:
            with self.subTest(row=expected_row, title=title, phase="review-mutant"):
                self.assertEqual(_failed_rows(mutator(self.snapshot)), [expected_row])


if __name__ == "__main__":
    unittest.main()
