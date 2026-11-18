#!/usr/bin/env python3
"""Capture and diff the operator-visible contract of two exact Git revisions.

The refactor safety net intentionally reports drift instead of deciding whether
the drift is good.  Reviewers get one deterministic artifact covering command
help, documentation, browser consumers, HTTP dispatch/security/error behavior,
SSE, OpenAPI, and the authenticated public-module contract.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import inspect
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import textwrap
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
REQUIRED_DIFF_SECTIONS = (
    "cli_help_docs",
    "frontend_consumers",
    "http_contract",
    "openapi",
    "authenticated_modules",
)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
RESPONSE_CALLS = {
    "_json_response",
    "json_response",
    "_setup_error",
    "send_error",
    "send_response",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest()


def _tracked_files(repo: Path, *pathspecs: str) -> list[Path]:
    if (repo / ".git").exists():
        output = subprocess.check_output(
            ["git", "-c", f"safe.directory={repo}", "ls-files", "-z", "--", *pathspecs],
            cwd=repo,
        )
        return [repo / raw.decode() for raw in output.split(b"\0") if raw]
    paths: set[Path] = set()
    for pathspec in pathspecs:
        path = repo / pathspec
        if path.is_file():
            paths.add(path)
        elif path.is_dir():
            paths.update(candidate for candidate in path.rglob("*") if candidate.is_file())
    return sorted(paths)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda row: str(row[0]))}
    return f"{type(value).__module__}.{type(value).__qualname__}"


def _action_contract(action: argparse.Action) -> dict[str, Any]:
    choices = action.choices
    if isinstance(action, argparse._SubParsersAction):
        choices = list(action.choices)
    elif choices is not None:
        choices = list(choices)
    return {
        "type": type(action).__name__,
        "option_strings": list(action.option_strings),
        "dest": action.dest,
        "required": bool(getattr(action, "required", False)),
        "nargs": _json_value(action.nargs),
        "choices": _json_value(choices),
        "default": _json_value(action.default),
        "metavar": _json_value(action.metavar),
        "help": action.help,
    }


def _cli_contract() -> dict[str, dict[str, Any]]:
    from freq.cli import _build_parser

    result: dict[str, dict[str, Any]] = {}

    def visit(parser: argparse.ArgumentParser, scope: tuple[str, ...]) -> None:
        name = " ".join(scope) or "<root>"
        result[name] = {
            "prog": parser.prog,
            "usage": parser.usage,
            "description": parser.description,
            "epilog": parser.epilog,
            "help": parser.format_help(),
            "actions": [_action_contract(action) for action in parser._actions],
        }
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for child_name, child in sorted(action.choices.items()):
                    visit(child, (*scope, child_name))

    visit(_build_parser(), ())
    return result


def _docs_contract(repo: Path) -> dict[str, dict[str, Any]]:
    paths = _tracked_files(repo, "README.md", "docs", "freq/data/conf-templates")
    result = {}
    for path in sorted(paths):
        if path.name != "README.md" and path.suffix != ".md" and "example" not in path.name:
            continue
        relative = path.relative_to(repo).as_posix()
        data = path.read_bytes()
        result[relative] = {"sha256": _sha256(data), "bytes": len(data)}
    return result


def _frontend_contract(repo: Path, surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    kinds = {"ui-api-consumer", "ui-asset", "ui-navigation", "ui-router", "ui-setup-step"}
    consumers = {
        f"{row['kind']}:{row['name']}": row
        for row in surfaces
        if row["kind"] in kinds
    }
    assets = {}
    for path in sorted(_tracked_files(repo, "freq/data/web")):
        if not path.is_file():
            continue
        relative = path.relative_to(repo).as_posix()
        data = path.read_bytes()
        assets[relative] = {"sha256": _sha256(data), "bytes": len(data)}
    return {"consumers": consumers, "assets": assets}


def _openapi_spec() -> dict[str, Any]:
    from freq.modules.serve import FreqHandler

    handler = FreqHandler.__new__(FreqHandler)
    handler.path = "/api/openapi.json"
    handler.command = "GET"
    handler.wfile = io.BytesIO()
    handler.rfile = io.BytesIO()
    handler.requestline = "GET /api/openapi.json HTTP/1.1"
    handler.client_address = ("127.0.0.1", 9999)
    handler.request_version = "HTTP/1.1"
    handler.headers = {}
    handler._headers_buffer = []
    handler.send_response = lambda code, msg=None: None
    handler.send_header = lambda key, value: None
    handler.end_headers = lambda: None
    handler._serve_openapi_json()
    return json.loads(handler.wfile.getvalue().decode())


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return "<dynamic>"


def _delegated_response_expression(node: ast.Call) -> ast.AST | None:
    """Inline explicitly supported pure response builders for contract capture."""
    if _call_name(node) != "build_config_projection" or node.keywords:
        return None

    from freq.services.dashboard_state import build_config_projection

    tree = ast.parse(textwrap.dedent(inspect.getsource(build_config_projection)))
    function = next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef)),
        None,
    )
    if function is None or len(node.args) != len(function.args.args):
        return None
    returned = next(
        (item for item in function.body if isinstance(item, ast.Return)),
        None,
    )
    if returned is None or returned.value is None:
        return None
    replacements = {
        parameter.arg: argument
        for parameter, argument in zip(function.args.args, node.args)
    }

    class BindArguments(ast.NodeTransformer):
        def visit_Name(self, current: ast.Name) -> ast.AST:
            if isinstance(current.ctx, ast.Load) and current.id in replacements:
                return copy.deepcopy(replacements[current.id])
            return current

    return ast.fix_missing_locations(
        BindArguments().visit(copy.deepcopy(returned.value))
    )


def _expr_contract(node: ast.AST | None) -> Any:
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        return {
            str(_expr_contract(key)): _expr_contract(value)
            for key, value in zip(node.keys, node.values)
            if key is not None
        }
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_expr_contract(item) for item in node.elts]
    if isinstance(node, ast.Name):
        return {"expression": node.id}
    if isinstance(node, ast.Attribute):
        return {"expression": ast.unparse(node)}
    if isinstance(node, ast.Call):
        delegated = _delegated_response_expression(node)
        if delegated is not None:
            return _expr_contract(delegated)
        return {"call": _call_name(node)}
    return {"expression": ast.dump(node, include_attributes=False)}


def _literal_int(node: ast.AST | None) -> int | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, int) else None


def _response_contract(source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return {"responses": [], "headers": []}
    responses = []
    headers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name == "send_header" and len(node.args) >= 2:
            headers.append({"name": _expr_contract(node.args[0]), "value": _expr_contract(node.args[1])})
            continue
        if name not in RESPONSE_CALLS:
            continue
        data_node = None
        status_node = None
        if name == "json_response":
            data_node = node.args[1] if len(node.args) > 1 else None
            status_node = node.args[2] if len(node.args) > 2 else None
        elif name == "_json_response":
            data_node = node.args[0] if node.args else None
            status_node = node.args[1] if len(node.args) > 1 else None
        elif name == "_setup_error":
            status_node = node.args[1] if len(node.args) > 1 else None
            data_node = ast.Dict(
                keys=[ast.Constant("code"), ast.Constant("message")],
                values=[
                    node.args[2] if len(node.args) > 2 else ast.Constant(None),
                    node.args[3] if len(node.args) > 3 else ast.Constant(None),
                ],
            )
        else:
            status_node = node.args[0] if node.args else None
        responses.append(
            {
                "call": name,
                "status": _literal_int(status_node) or _expr_contract(status_node),
                "envelope": _expr_contract(data_node),
            }
        )
    responses.sort(key=lambda row: json.dumps(row, sort_keys=True))
    headers.sort(key=lambda row: json.dumps(row, sort_keys=True))
    return {"responses": responses, "headers": headers}


def _handler_source(handler: Any) -> str:
    try:
        return inspect.getsource(handler)
    except (OSError, TypeError):
        return ""


def _http_contract(
    surface_rows: list[dict[str, Any]], openapi: dict[str, Any]
) -> dict[str, Any]:
    from freq.api import build_routes
    from freq.modules.serve import FreqHandler

    try:
        from freq.api.auth import send_security_headers
    except ImportError:
        security_handler = FreqHandler._send_security_headers
    else:
        security_handler = send_security_headers

    inventory_rows = {
        (row["kind"], row["name"]): row
        for row in surface_rows
        if row["kind"] in {"http-legacy", "http-v1"}
    }
    route_handlers: dict[tuple[str, str], Any] = {}
    for path, handler_name in FreqHandler._ROUTES.items():
        route_handlers[("http-legacy", path)] = getattr(FreqHandler, handler_name)
    for path, handler in build_routes().items():
        route_handlers[("http-v1", path)] = handler

    openapi_methods = {
        path: sorted(method.upper() for method in methods if method.lower() in {"get", "post", "put", "patch", "delete"})
        for path, methods in openapi.get("paths", {}).items()
    }
    routes = {}
    for (kind, path), handler in sorted(route_handlers.items()):
        source = _handler_source(handler)
        inventory = inventory_rows[(kind, path)]
        methods = openapi_methods.get(path, inventory.get("methods", ["UNKNOWN"]))
        writes = bool(set(methods) & WRITE_METHODS)
        if writes and path in FreqHandler._CSRF_EXEMPT:
            csrf = "exempt"
        elif writes and path.startswith("/api/"):
            csrf = "required"
        elif methods == ["UNKNOWN"]:
            csrf = "unknown"
        else:
            csrf = "not-applicable"
        if path in FreqHandler._AUTH_WHITELIST or any(
            path.startswith(prefix) for prefix in FreqHandler._AUTH_WHITELIST_PREFIXES
        ):
            dispatch_auth = "public-or-bootstrap"
        elif path.startswith("/api/"):
            dispatch_auth = "viewer"
        else:
            dispatch_auth = "public-non-api"
        routes[f"{kind}:{path}"] = {
            "kind": kind,
            "path": path,
            "handler": inventory["handler"],
            "methods": methods,
            "dispatch_auth": dispatch_auth,
            "handler_rbac": inventory.get("access", "UNKNOWN"),
            "handler_rbac_status": inventory.get("access_status", "UNKNOWN_KEEP"),
            "csrf": csrf,
            "source_sha256": _sha256(source),
            **_response_contract(source),
        }

    security_source = _handler_source(security_handler)
    json_source = _handler_source(FreqHandler._json_response)
    dispatch_source = _handler_source(FreqHandler._dispatch)
    sse_source = _handler_source(FreqHandler._serve_events)
    return {
        "routes": routes,
        "global": {
            "auth_whitelist": sorted(FreqHandler._AUTH_WHITELIST),
            "auth_whitelist_prefixes": list(FreqHandler._AUTH_WHITELIST_PREFIXES),
            "csrf_exempt": sorted(FreqHandler._CSRF_EXEMPT),
            "dispatch_404_and_500": {
                "source_sha256": _sha256(dispatch_source),
                **_response_contract(dispatch_source),
            },
            "json_error_and_cache": {
                "source_sha256": _sha256(json_source),
                **_response_contract(json_source),
            },
            "security_headers": {
                "source_sha256": _sha256(security_source),
                **_response_contract(security_source),
            },
            "sse": {
                "path": "/api/events",
                "source_sha256": _sha256(sse_source),
                **_response_contract(sse_source),
            },
        },
    }


def _authenticated_modules(repo: Path, live_contract: list[dict[str, Any]]) -> dict[str, Any]:
    from scripts import test_health

    additions, authenticated = test_health.authenticated_effective_module_contract(repo)
    live_by_path = {row["path"]: row for row in live_contract}
    authenticated_by_path = {row["path"]: row for row in authenticated}
    if live_by_path != authenticated_by_path:
        missing = sorted(live_by_path.keys() - authenticated_by_path.keys())
        stale = sorted(authenticated_by_path.keys() - live_by_path.keys())
        changed = sorted(
            path
            for path in live_by_path.keys() & authenticated_by_path.keys()
            if live_by_path[path] != authenticated_by_path[path]
        )
        raise ValueError(
            "live public modules differ from authenticated manifest: "
            f"missing={missing} stale={stale} changed={changed}"
        )
    return {
        "manifest_sha256": _sha256(_canonical_bytes(additions)),
        "contract_sha256": _sha256(_canonical_bytes(authenticated)),
        "modules": authenticated_by_path,
    }


def snapshot(repo: Path, source_sha: str, source_tree: str) -> dict[str, Any]:
    repo = repo.resolve()
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from scripts import surface_inventory

    if not (repo / ".git").exists():
        surface_inventory._tracked_files = lambda root, pathspec: _tracked_files(root, pathspec)

    inventory = surface_inventory.inventory(repo, source_sha=source_sha)
    openapi = _openapi_spec()
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "source_tree": source_tree,
        "cli_help_docs": {"cli": _cli_contract(), "docs": _docs_contract(repo)},
        "frontend_consumers": _frontend_contract(repo, inventory["surfaces"]),
        "http_contract": _http_contract(inventory["surfaces"], openapi),
        "openapi": openapi,
        "authenticated_modules": _authenticated_modules(repo, inventory["module_contract"]),
    }


def _pointer(path: tuple[str, ...]) -> str:
    if not path:
        return "/"
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in path)


def _walk_diff(before: Any, after: Any, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            child = (*path, str(key))
            if key not in before:
                changes.append({"path": _pointer(child), "change": "added", "after": after[key]})
            elif key not in after:
                changes.append({"path": _pointer(child), "change": "removed", "before": before[key]})
            else:
                changes.extend(_walk_diff(before[key], after[key], child))
        return changes
    if before != after:
        return [{"path": _pointer(path), "change": "changed", "before": before, "after": after}]
    return []


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    if before.get("schema_version") != SCHEMA_VERSION or after.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported refactor surface schema")
    sections = {
        section: _walk_diff(before[section], after[section])
        for section in REQUIRED_DIFF_SECTIONS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "base": {"sha": before["source_sha"], "tree": before["source_tree"]},
        "head": {"sha": after["source_sha"], "tree": after["source_tree"]},
        "clean": not any(sections.values()),
        "summary": {section: len(changes) for section, changes in sections.items()},
        "sections": sections,
    }


def _resolve(repo: Path, ref: str) -> tuple[str, str]:
    sha = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "rev-parse", f"{ref}^{{commit}}"],
        cwd=repo,
        text=True,
    ).strip()
    tree = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "rev-parse", f"{sha}^{{tree}}"],
        cwd=repo,
        text=True,
    ).strip()
    return sha, tree


def _extract(repo: Path, sha: str, destination: Path) -> None:
    archive = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "archive", "--format=tar", sha],
        cwd=repo,
    )
    destination.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
        bundle.extractall(destination, filter="data")


def _snapshot_ref(repo: Path, ref: str, root: Path, label: str) -> dict[str, Any]:
    sha, tree = _resolve(repo, ref)
    source = root / label
    runtime = root / f"{label}-runtime"
    _extract(repo, sha, source)
    runtime.mkdir()
    env = dict(os.environ)
    env["FREQ_DIR"] = str(runtime)
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "snapshot",
            "--repo",
            str(source),
            "--source-sha",
            sha,
            "--source-tree",
            tree,
        ],
        cwd=source,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"surface snapshot failed for {label} {sha}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def _write_json(data: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("snapshot", help="capture one extracted source tree")
    capture.add_argument("--repo", type=Path, required=True)
    capture.add_argument("--source-sha", required=True)
    capture.add_argument("--source-tree", required=True)
    capture.add_argument("--output", type=Path)

    diff = subparsers.add_parser("diff", help="diff two exact committed revisions")
    diff.add_argument("--repo", type=Path, default=Path.cwd())
    diff.add_argument("--base-ref", required=True)
    diff.add_argument("--head-ref", required=True)
    diff.add_argument("--output", type=Path)
    diff.add_argument("--require-no-drift", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "snapshot":
        data = snapshot(args.repo, args.source_sha, args.source_tree)
        _write_json(data, args.output)
        return 0

    repo = args.repo.resolve()
    with tempfile.TemporaryDirectory(prefix="freq-refactor-surface-") as tmp:
        root = Path(tmp)
        before = _snapshot_ref(repo, args.base_ref, root, "base")
        after = _snapshot_ref(repo, args.head_ref, root, "head")
    result = compare(before, after)
    _write_json(result, args.output)
    if args.require_no_drift and not result["clean"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
