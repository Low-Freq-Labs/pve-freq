#!/usr/bin/env python3
"""Generate the fail-closed public-surface baseline used by retirement review."""

from __future__ import annotations

import argparse
import argparse as argparse_module
import ast
import inspect
import json
import re
import subprocess
import sys
import textwrap
import tomllib
from dataclasses import MISSING, fields
from pathlib import Path

SCHEMA_VERSION = 2
CRITICAL_MODULES = {
    "freq/api/auth.py",
    "freq/api/fleet.py",
    "freq/api/terminal.py",
    "freq/api/vm.py",
    "freq/core/service_units.py",
    "freq/core/services.py",
    "freq/core/setup_contract.py",
    "freq/core/setup_discovery.py",
    "freq/core/setup_state.py",
    "freq/modules/agent_deployment.py",
    "freq/modules/fleet.py",
    "freq/modules/init_cmd.py",
    "freq/modules/selfupdate.py",
    "freq/modules/serve.py",
    "freq/modules/vm.py",
}
REQUIRED_CATEGORIES = {
    "cli-command",
    "cli-option",
    "cli-positional",
    "config-field",
    "config-template",
    "cross-repo-consumer",
    "docs-example",
    "entry-point",
    "http-legacy",
    "http-v1",
    "lifecycle",
    "migration",
    "runtime-state",
    "systemd-unit",
    "tui-command",
    "ui-api-consumer",
    "ui-asset",
    "ui-navigation",
    "ui-router",
    "ui-setup-step",
}


def _identity(value) -> str:
    if isinstance(value, str):
        return value
    module = getattr(value, "__module__", type(value).__module__)
    qualname = getattr(value, "__qualname__", type(value).__qualname__)
    return f"{module}.{qualname}"


def _row(kind: str, name: str, handler=None, evidence=None, **extra) -> dict:
    row = {
        "kind": kind,
        "name": name,
        "handler": _identity(handler) if handler else None,
        "classification": "UNKNOWN",
        "evidence": evidence or [],
    }
    row.update(extra)
    return row


def _role_requirements(source: str) -> set[str]:
    return set(
        re.findall(
            r"_?check_session_role\(\s*(?:self|handler)\s*,\s*(?:min_role\s*=\s*)?[\"'](viewer|operator|admin)[\"']",
            source,
        )
    )


def _local_role_guard_requirements(handler, source: str) -> tuple[set[str], bool]:
    """Resolve one direct local role-guard call without guessing through indirection."""
    try:
        tree = ast.parse(textwrap.dedent(source))
    except SyntaxError:
        return set(), False
    module = inspect.getmodule(handler)
    if module is None:
        return set(), False
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    roles: set[str] = set()
    unresolved = False
    for name in called_names:
        if not re.search(
            r"(?:(?:require|check).*(?:admin|auth|role|session)|(?:admin|auth|role|session).*(?:require|check))",
            name,
            re.IGNORECASE,
        ):
            continue
        helper = getattr(module, name, None)
        if not inspect.isfunction(helper) or helper.__module__ != handler.__module__:
            continue
        try:
            helper_source = inspect.getsource(helper)
        except (OSError, TypeError):
            unresolved = True
            continue
        helper_roles = _role_requirements(helper_source)
        if helper_roles:
            roles.update(helper_roles)
        else:
            unresolved = True
    return roles, unresolved


def _walk_parser(parser: argparse_module.ArgumentParser, prefix: tuple[str, ...] = ()) -> list[dict]:
    rows = []
    scope = " ".join(prefix) or "<root>"
    for action in parser._actions:
        if isinstance(action, argparse_module._SubParsersAction):
            for name, child in sorted(action.choices.items()):
                command = (*prefix, name)
                handler = child.get_default("func")
                rows.append(
                    _row(
                        "cli-command",
                        " ".join(command),
                        handler,
                        ["freq/cli.py:_build_parser"],
                    )
                )
                rows.extend(_walk_parser(child, command))
            continue
        if action.option_strings:
            if action.dest != "help":
                for spelling in action.option_strings:
                    rows.append(
                        _row(
                            "cli-option",
                            f"{scope} {spelling}",
                            evidence=["freq/cli.py:_build_parser"],
                            destination=action.dest,
                        )
                    )
            continue
        if action.dest not in {argparse_module.SUPPRESS, "==SUPPRESS=="}:
            rows.append(
                _row(
                    "cli-positional",
                    f"{scope} {action.dest}",
                    evidence=["freq/cli.py:_build_parser"],
                    required=bool(getattr(action, "required", False)),
                )
            )
    return rows


def _http_semantics(path: str, handler) -> dict:
    source = ""
    try:
        source = inspect.getsource(handler)
    except (OSError, TypeError):
        pass
    doc = inspect.getdoc(handler) or ""
    methods = set(re.findall(r"\b(GET|POST|PUT|PATCH|DELETE)\b", doc.splitlines()[0] if doc else ""))
    for match in re.finditer(
        r"(?:self|handler)\.command\s*(?:!=|not\s+in)\s*(\{[^}]+\}|\([^)]*\)|[\"'][A-Z]+[\"'])",
        source,
    ):
        methods.update(re.findall(r"[\"'](GET|POST|PUT|PATCH|DELETE)[\"']", match.group(1)))
    methods = sorted(methods)
    if not methods:
        methods = ["UNKNOWN"]
    writes = set(methods) - {"GET"}
    mutation = "unknown" if methods == ["UNKNOWN"] else "mixed" if writes and "GET" in methods else "mutation" if writes else "read"
    direct_roles = _role_requirements(source)
    helper_roles, unresolved_helper = _local_role_guard_requirements(handler, source)
    proven_roles = direct_roles | helper_roles
    if len(proven_roles) == 1 and not unresolved_helper:
        access = next(iter(proven_roles))
        access_status = "RESOLVED"
    elif proven_roles or unresolved_helper:
        access = "UNKNOWN"
        access_status = "UNKNOWN_KEEP"
    elif path == "/healthz":
        access = "public-health"
        access_status = "RESOLVED"
    elif path.startswith("/api/setup/") or path == "/api/auth/login":
        access = "bootstrap-or-public-guarded"
        access_status = "RESOLVED"
    else:
        access = "authenticated-dispatch"
        access_status = "RESOLVED"
    semantics_status = (
        "UNKNOWN_KEEP" if methods == ["UNKNOWN"] or access_status == "UNKNOWN_KEEP" else "RESOLVED"
    )
    return {
        "methods": methods,
        "mutation": mutation,
        "access": access,
        "access_status": access_status,
        "semantics_status": semantics_status,
    }


def _tracked_files(repo: Path, pathspec: str) -> list[Path]:
    output = subprocess.check_output(
        ["git", "-c", f"safe.directory={repo}", "ls-files", "-z", "--", pathspec], cwd=repo
    )
    relative_paths = [raw.decode() for raw in output.split(b"\0") if raw]
    ignored_result = subprocess.run(
        ["git", "-c", f"safe.directory={repo}", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=repo,
        input="".join(f"{path}\0" for path in relative_paths),
        text=True,
        capture_output=True,
        check=False,
    )
    if ignored_result.returncode not in {0, 1}:
        raise RuntimeError(f"git check-ignore failed ({ignored_result.returncode}): {ignored_result.stderr}")
    ignored = {path for path in ignored_result.stdout.split("\0") if path}
    paths = [repo / path for path in relative_paths if path not in ignored]
    forbidden = {"__pycache__", ".pytest_cache", ".ruff_cache", "build", "dist"}
    return [
        path
        for path in paths
        if path.is_file()
        and not forbidden.intersection(path.parts)
        and path.suffix not in {".pyc", ".pyo"}
    ]


def _api_surfaces() -> list[dict]:
    from freq.api import build_routes
    from freq.modules.serve import FreqHandler

    rows = []
    for path, handler_name in sorted(FreqHandler._ROUTES.items()):
        handler = getattr(FreqHandler, handler_name)
        rows.append(
            _row(
                "http-legacy",
                path,
                handler,
                ["freq/modules/serve.py:FreqHandler._ROUTES"],
                **_http_semantics(path, handler),
            )
        )
    for path, handler in sorted(build_routes().items()):
        rows.append(
            _row(
                "http-v1",
                path,
                handler,
                ["freq/api/__init__.py:build_routes"],
                **_http_semantics(path, handler),
            )
        )
    return rows


def _web_surfaces(repo: Path) -> list[dict]:
    rows = []
    api_pattern = re.compile(r"/api/[A-Za-z0-9_./{}?=&-]+")
    nav_pattern = re.compile(r"data-view=[\"']([^\"']+)")
    setup_pattern = re.compile(r"data-step-target=[\"']([^\"']+)")
    for path in sorted(_tracked_files(repo, "freq/data/web")):
        rel = path.relative_to(repo).as_posix()
        rows.append(_row("ui-asset", rel, evidence=[rel]))
        if path.suffix not in {".js", ".html"}:
            continue
        text = path.read_text(errors="replace")
        for api_path in sorted(set(api_pattern.findall(text))):
            rows.append(_row("ui-api-consumer", f"{rel}:{api_path}", evidence=[rel], endpoint=api_path))
        for target in sorted(set(nav_pattern.findall(text))):
            rows.append(_row("ui-navigation", f"{rel}:{target}", evidence=[rel], target=target))
        for target in sorted(set(setup_pattern.findall(text))):
            rows.append(_row("ui-setup-step", f"{rel}:{target}", evidence=[rel], target=target))
        if path.name == "app.js":
            view_ids = re.search(r"var VIEW_IDS=\[([^]]+)]", text)
            if view_ids:
                for target in re.findall(r"[\"']([^\"']+)[\"']", view_ids.group(1)):
                    rows.append(_row("ui-router", target, evidence=[rel, "freq/data/web/js/router.js"]))
    return rows


def _tui_surfaces(repo: Path, cli_roots: set[str]) -> list[dict]:
    path = repo / "freq/tui/menu.py"
    tree = ast.parse(path.read_text())
    commands = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if value and value.split()[0] in cli_roots and len(value) < 100:
                commands.add(value)
    return [_row("tui-command", command, evidence=["freq/tui/menu.py"]) for command in sorted(commands)]


def _config_surfaces(repo: Path) -> list[dict]:
    from freq.core.config import FreqConfig

    rows = []
    for field in fields(FreqConfig):
        default_kind = "required"
        if field.default is not MISSING:
            default_kind = "literal"
        elif field.default_factory is not MISSING:
            default_kind = "factory"
        rows.append(
            _row(
                "config-field",
                field.name,
                evidence=["freq/core/config.py:FreqConfig"],
                default_kind=default_kind,
                schema_type=str(field.type),
            )
        )
    for path in sorted(_tracked_files(repo, "freq/data/conf-templates")):
        rel = path.relative_to(repo).as_posix()
        rows.append(_row("config-template", rel, evidence=[rel]))
    return rows


def _non_python_surfaces(repo: Path) -> list[dict]:
    rows = []
    install_text = (repo / "install.sh").read_text()
    for unit in sorted(set(re.findall(r"[A-Za-z0-9@_.-]+\.(?:service|timer)(?![A-Za-z0-9_])", install_text))):
        rows.append(
            _row(
                "systemd-unit",
                unit,
                evidence=["install.sh", "freq/core/service_units.py"],
                unit_type=unit.rsplit(".", 1)[-1],
            )
        )
    lifecycle = {
        "install": ["install.sh:do_install", "install.sh:post_install"],
        "update": ["freq/modules/selfupdate.py", "freq/cli.py:_cmd_update"],
        "doctor": ["freq/core/doctor.py", "freq/cli.py:cmd_doctor"],
        "init": ["freq/modules/init_cmd.py", "freq/cli.py:_cmd_init"],
        "uninstall": ["install.sh:do_uninstall", "freq/modules/init_cmd.py"],
        "backup": ["freq/modules/backup.py", "freq/api/dr.py"],
        "restore": ["freq/modules/backup.py", "freq/api/dr.py"],
    }
    rows.extend(_row("lifecycle", name, evidence=evidence) for name, evidence in lifecycle.items())
    runtime_owners = [
        "freq/core/config.py",
        "freq/core/health_state.py",
        "freq/core/setup_state.py",
        "freq/modules/init_cmd.py",
        "freq/modules/serve.py",
    ]
    rows.extend(_row("runtime-state", path, evidence=[path]) for path in runtime_owners)
    rows.append(
        _row(
            "migration",
            "config-and-runtime-compatibility",
            evidence=["freq/core/compat.py", "freq/core/config.py", "freq/core/setup_state.py"],
        )
    )
    docs = [repo / "README.md", *_tracked_files(repo, "docs"), *_tracked_files(repo, "freq/data/conf-templates")]
    for path in sorted({path for path in docs if path.name == "README.md" or path.suffix == ".md" or "example" in path.name}):
        rel = path.relative_to(repo).as_posix()
        rows.append(_row("docs-example", rel, evidence=[rel]))
    rows.append(
        _row(
            "cross-repo-consumer",
            "external-and-saved-automation",
            evidence=["repo silence is not retirement evidence", "explicit Sonny approval required"],
            availability="UNKNOWN",
        )
    )
    return rows


def _entry_points(repo: Path) -> list[dict]:
    pyproject = tomllib.loads((repo / "pyproject.toml").read_text())
    return [
        _row("entry-point", name, handler, ["pyproject.toml:project.scripts"])
        for name, handler in sorted(pyproject.get("project", {}).get("scripts", {}).items())
    ]


def _module_contract(repo: Path, surfaces: list[dict]) -> list[dict]:
    module_paths = sorted(
        path.relative_to(repo).as_posix()
        for path in _tracked_files(repo, "freq")
        if path.suffix == ".py"
    )
    text = "\n".join(str(row.get("handler") or "") + " " + " ".join(row["evidence"]) for row in surfaces)
    rows = []
    for path in module_paths:
        dotted = path[:-3].replace("/", ".")
        directly_named = dotted in text or path in text
        rows.append(
            {
                "path": path,
                "classification": "RETAINED" if directly_named or path in CRITICAL_MODULES else "UNKNOWN_KEEP",
                "critical": path in CRITICAL_MODULES,
                "branch_floor": 0.60 if path in CRITICAL_MODULES else 0.40,
                "zero_branch_statement_floor": 0.70,
                "evidence": ["public-surface/lifecycle direct reference"] if directly_named else ["UNKNOWN defaults KEEP"],
            }
        )
    return rows


def inventory(repo: Path, source_sha: str | None = None) -> dict:
    sys.path.insert(0, str(repo))
    from freq.cli import _build_parser

    parser = _build_parser()
    rows = _walk_parser(parser) + _api_surfaces() + _entry_points(repo) + _config_surfaces(repo)
    cli_roots = {row["name"].split()[0] for row in rows if row["kind"] == "cli-command"}
    rows += _web_surfaces(repo) + _tui_surfaces(repo, cli_roots) + _non_python_surfaces(repo)
    rows.sort(key=lambda item: (item["kind"], item["name"]))
    keys = [(item["kind"], item["name"]) for item in rows]
    if len(keys) != len(set(keys)):
        duplicates = sorted(key for key in set(keys) if keys.count(key) > 1)
        raise RuntimeError(f"duplicate public surfaces: {duplicates[:20]}")
    counts = {kind: sum(item["kind"] == kind for item in rows) for kind in sorted({item["kind"] for item in rows})}
    missing = sorted(REQUIRED_CATEGORIES - counts.keys())
    if missing:
        raise RuntimeError(f"public surface category matrix incomplete: {missing}")
    if source_sha is None:
        source_sha = subprocess.check_output(
            ["git", "-c", f"safe.directory={repo}", "rev-parse", "HEAD"], cwd=repo, text=True
        ).strip()
    return {
        "schema_version": SCHEMA_VERSION,
        "source_sha": source_sha,
        "classification_policy": {
            "default": "UNKNOWN",
            "unknown_means": "KEEP until complete retirement evidence and Sonny approval",
        },
        "completeness_matrix": {
            kind: {"count": counts[kind], "covered": True} for kind in sorted(REQUIRED_CATEGORIES)
        },
        "counts": counts,
        "module_contract": _module_contract(repo, rows),
        "surfaces": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--source-sha")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = inventory(args.repo.resolve(), args.source_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(json.dumps(data["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
