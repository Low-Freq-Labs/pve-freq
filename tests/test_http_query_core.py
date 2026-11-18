"""Phase-3 contracts for dependency-clean HTTP query parsing."""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from freq.api import auto, docker_api, dr, fleet, helpers, hw, net, state, store, user, vm
from freq.core import http_query
from freq.modules import serve

REPO_ROOT = Path(__file__).parent.parent
QUERY_HELPER_NAMES = {"get_params", "_parse_query", "_parse_query_flat", "_get_params_flat"}
UPWARD_QUERY_PATHS = {
    "freq.modules.serve._parse_query",
    "freq.modules.serve._parse_query_flat",
}


def _handler(path):
    return SimpleNamespace(path=path)


def _dotted_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def _upward_query_references(source):
    tree = ast.parse(source)
    aliases = {}
    violations = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                local_name = imported.asname or imported.name.split(".", 1)[0]
                aliases[local_name] = imported.name if imported.asname else local_name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for imported in node.names:
                imported_path = f"{module}.{imported.name}" if module else imported.name
                aliases[imported.asname or imported.name] = imported_path
                if imported_path in UPWARD_QUERY_PATHS:
                    violations.add(imported_path)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        dotted = _dotted_name(node)
        root, separator, remainder = dotted.partition(".")
        resolved = aliases.get(root, root)
        if separator:
            resolved = f"{resolved}.{remainder}"
        if resolved in UPWARD_QUERY_PATHS:
            violations.add(resolved)

    return violations


def test_handler_list_parser_identities_are_exact():
    consumers = (
        serve._parse_query,
        helpers.get_params,
        dr._parse_query,
        fleet._parse_query,
        hw._parse_query,
        net._parse_query,
        state._parse_query,
        store._parse_query,
        user._parse_query,
    )

    assert all(consumer is http_query.parse_query for consumer in consumers)


def test_path_flat_parser_identities_are_exact():
    consumers = (
        serve._parse_query_flat,
        docker_api._parse_query_flat,
        dr._parse_query_flat,
        fleet._parse_query_flat,
        vm._parse_query_flat,
    )

    assert all(consumer is http_query.parse_query_flat for consumer in consumers)


def test_handler_flat_parser_identity_is_exact():
    assert auto._get_params_flat is http_query.parse_query_handler_flat


def test_list_parser_preserves_urllib_semantics():
    parsed = http_query.parse_query(
        _handler("/api/test?repeat=one&repeat=two&plus=hello+world&encoded=%2Fapi%2Fv1&blank=&bare")
    )

    assert parsed == {
        "repeat": ["one", "two"],
        "plus": ["hello world"],
        "encoded": ["/api/v1"],
    }


def test_flat_parsers_preserve_first_value_and_tolerant_escapes():
    path = "/api/test?repeat=one&repeat=two&malformed=%ZZ&blank="
    expected = {"repeat": "one", "malformed": "%ZZ"}

    assert http_query.parse_query_flat(path) == expected
    assert http_query.parse_query_handler_flat(_handler(path)) == expected


def test_invalid_input_exceptions_remain_visible():
    with pytest.raises(AttributeError):
        http_query.parse_query(object())
    with pytest.raises(AttributeError):
        http_query.parse_query_flat(object())
    with pytest.raises(AttributeError):
        http_query.parse_query_handler_flat(object())


def test_core_module_has_only_frozen_stdlib_dependency():
    tree = ast.parse((REPO_ROOT / "freq" / "core" / "http_query.py").read_text())
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]

    assert len(imports) == 1
    assert isinstance(imports[0], ast.ImportFrom)
    assert imports[0].module == "urllib.parse"
    assert {alias.name for alias in imports[0].names} == {"parse_qs", "urlparse"}


def test_legacy_and_duplicate_function_owners_are_removed():
    serve_tree = ast.parse((REPO_ROOT / "freq" / "modules" / "serve.py").read_text())
    serve_owned = {
        node.name
        for node in ast.walk(serve_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"_parse_query", "_parse_query_flat"}.isdisjoint(serve_owned)

    for api_path in (REPO_ROOT / "freq" / "api").glob("*.py"):
        tree = ast.parse(api_path.read_text())
        owned = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert QUERY_HELPER_NAMES.isdisjoint(owned), api_path


def test_api_consumers_do_not_import_query_helpers_upward_from_serve():
    for api_path in (REPO_ROOT / "freq" / "api").glob("*.py"):
        assert not _upward_query_references(api_path.read_text()), api_path


@pytest.mark.parametrize(
    "source",
    (
        "from freq.modules.serve import _parse_query",
        "from freq.modules.serve import _parse_query_flat as query_flat",
        "import freq.modules.serve as serve\nserve._parse_query(handler)",
        "from freq.modules import serve as legacy\nlegacy._parse_query_flat(path)",
        "import freq.modules.serve\nfreq.modules.serve._parse_query(handler)",
        "freq.modules.serve._parse_query_flat(path)",
    ),
)
def test_architecture_guard_detects_upward_import_bypass_shapes(source):
    assert _upward_query_references(source)


def test_inline_behavior_duplicates_are_removed():
    serve_source = (REPO_ROOT / "freq" / "modules" / "serve.py").read_text()
    vm_source = (REPO_ROOT / "freq" / "api" / "vm.py").read_text()

    assert "parse_qs(urlparse(self.path).query)" not in serve_source
    assert "raw = parse_qs(urlparse(handler.path).query)" not in vm_source
