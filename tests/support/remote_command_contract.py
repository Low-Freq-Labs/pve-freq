"""AST owner for governed POSIX remote-command construction.

The inventory is intentionally independent of the product implementation.  It
counts transport invocations first, then proves whether each command is fixed,
constructed through the shared serializer, or belongs to a separately named
raw-command boundary.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SinkSpec:
    command_position: int


@dataclass(frozen=True)
class SinkCall:
    path: str
    function: str
    lineno: int
    sink: str
    command: ast.expr
    scope: ast.FunctionDef | ast.AsyncFunctionDef

    @property
    def label(self) -> str:
        return f"{self.path}:{self.lineno} {self.function}->{self.sink}"


GOVERNED_SINKS: dict[str, dict[str, SinkSpec]] = {
    "freq/api/store.py": {"_truenas_ssh": SinkSpec(1)},
    "freq/api/fw.py": {"_pf_ssh": SinkSpec(1)},
    "freq/api/backup_verify.py": {"_pve_ssh": SinkSpec(2)},
    "freq/api/ct.py": {"_pve_cmd": SinkSpec(2)},
    "freq/api/dr.py": {"_pve_cmd": SinkSpec(2)},
    "freq/api/vm.py": {"_pve_cmd": SinkSpec(2), "ssh_single": SinkSpec(1)},
    "freq/api/docker_api.py": {
        "ssh_single": SinkSpec(1),
        "ssh_run_many": SinkSpec(1),
    },
    "freq/api/logs.py": {"_log_query": SinkSpec(1)},
    "freq/api/fleet.py": {
        "ssh_single": SinkSpec(1),
        "ssh_run_many": SinkSpec(1),
        "ssh_run_many_fn": SinkSpec(1),
    },
}

EXPECTED_COUNTS = {
    "freq/api/store.py": 17,
    "freq/api/fw.py": 18,
    "freq/api/backup_verify.py": 4,
    "freq/api/ct.py": 24,
    "freq/api/dr.py": 4,
    "freq/api/vm.py": 54,
    "freq/api/docker_api.py": 6,
    "freq/api/logs.py": 4,
    "freq/api/fleet.py": 13,
}

EXPECTED_TOTAL = 144
FIXED_WRAPPER_CALLS = 24
RAW_OPERATOR_BOUNDARY = ("freq/api/fleet.py", "handle_exec", "ssh_run_many")
CROSS_SCOPE_FIXED_COMMANDS = {
    ("freq/api/fleet.py", "_run_idrac_health_probe", "ssh_single", "cmd"),
    ("freq/api/fleet.py", "_probe_host", "ssh_single", "cmd"),
}


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    result: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            result[child] = node
    return result


def _scope_for(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = parents.get(current)
    raise AssertionError(f"governed sink at line {getattr(node, 'lineno', '?')} is outside a function")


def _command_argument(call: ast.Call, spec: SinkSpec) -> ast.expr:
    for keyword in call.keywords:
        if keyword.arg == "command":
            return keyword.value
    if len(call.args) > spec.command_position:
        return call.args[spec.command_position]
    raise AssertionError(f"{_call_name(call.func)} at line {call.lineno} has no command argument")


def inventory(repo_root: Path) -> tuple[list[SinkCall], dict[str, ast.Module]]:
    calls: list[SinkCall] = []
    trees: dict[str, ast.Module] = {}
    for relpath, sink_specs in GOVERNED_SINKS.items():
        tree = ast.parse((repo_root / relpath).read_text(), filename=relpath)
        trees[relpath] = tree
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            sink = _call_name(node.func)
            if sink not in sink_specs:
                continue
            scope = _scope_for(node, parents)
            calls.append(
                SinkCall(
                    path=relpath,
                    function=scope.name,
                    lineno=node.lineno,
                    sink=sink,
                    command=_command_argument(node, sink_specs[sink]),
                    scope=scope,
                )
            )
    return sorted(calls, key=lambda item: (item.path, item.lineno, item.sink)), trees


def count_by_path(calls: list[SinkCall]) -> dict[str, int]:
    counts = {path: 0 for path in GOVERNED_SINKS}
    for call in calls:
        counts[call.path] += 1
    return counts


def _assigned_values(scope: ast.AST, name: str, before: int) -> list[ast.expr]:
    values: list[tuple[int, ast.expr]] = []
    for node in ast.walk(scope):
        if getattr(node, "lineno", before) >= before:
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    values.append((node.lineno, node.value))
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name and node.value:
                values.append((node.lineno, node.value))
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                values.append((node.lineno, node.value))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == name:
                if node.func.attr == "append" and len(node.args) == 1:
                    values.append((node.lineno, node.args[0]))
                elif node.func.attr == "extend" and len(node.args) == 1:
                    values.append((node.lineno, node.args[0]))
    return [value for _line, value in sorted(values, key=lambda item: item[0])]


def _loop_sources(scope: ast.AST, name: str, before: int) -> list[ast.expr]:
    sources: list[ast.expr] = []
    for node in ast.walk(scope):
        if not isinstance(node, (ast.For, ast.comprehension)):
            continue
        if getattr(node, "lineno", before) >= before:
            continue
        names = [item.id for item in ast.walk(node.target) if isinstance(item, ast.Name)]
        if name in names:
            sources.append(node.iter)
    return sources


def _is_fixed(
    expr: ast.expr,
    scope: ast.AST,
    before: int,
    seen: frozenset[str] = frozenset(),
) -> bool:
    if isinstance(expr, ast.Constant):
        return isinstance(expr.value, (str, int, float, bool, type(None)))
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_fixed(item, scope, before, seen) for item in expr.elts)
    if isinstance(expr, ast.Dict):
        return all(
            key is not None
            and _is_fixed(key, scope, before, seen)
            and _is_fixed(value, scope, before, seen)
            for key, value in zip(expr.keys, expr.values)
        )
    if isinstance(expr, ast.IfExp):
        return _is_fixed(expr.body, scope, before, seen) and _is_fixed(expr.orelse, scope, before, seen)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _is_fixed(expr.left, scope, before, seen) and _is_fixed(expr.right, scope, before, seen)
    if isinstance(expr, ast.JoinedStr):
        return all(isinstance(item, ast.Constant) for item in expr.values)
    if isinstance(expr, ast.Name):
        if expr.id in seen:
            return False
        next_seen = seen | {expr.id}
        values = _assigned_values(scope, expr.id, before)
        if values:
            return all(_is_fixed(value, scope, before, next_seen) for value in values)
        sources = _loop_sources(scope, expr.id, before)
        return bool(sources) and all(_is_fixed(source, scope, before, next_seen) for source in sources)
    if isinstance(expr, ast.Subscript):
        return _is_fixed(expr.value, scope, before, seen)
    if isinstance(expr, ast.Call):
        if _call_name(expr.func) == "remote_command":
            script_values = [keyword.value for keyword in expr.keywords if keyword.arg == "script"]
            if not script_values:
                return True
            return len(script_values) == 1 and isinstance(script_values[0], ast.Constant) and isinstance(
                script_values[0].value, str
            ) and bool(script_values[0].value)
        if isinstance(expr.func, ast.Attribute) and expr.func.attr in {"get", "items", "values"}:
            return _is_fixed(expr.func.value, scope, before, seen)
    return False


def _nested_function(scope: ast.AST, name: str) -> ast.FunctionDef | None:
    return next(
        (
            node
            for node in ast.walk(scope)
            if isinstance(node, ast.FunctionDef) and node.name == name
        ),
        None,
    )


def fixed_wrapper_errors(tree: ast.Module) -> list[str]:
    host_detail = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "handle_host_detail"
    )
    wrapper = _nested_function(host_detail, "_cmd")
    if wrapper is None:
        return ["fleet handle_host_detail._cmd wrapper is missing"]
    wrapper_calls = [
        node
        for node in ast.walk(host_detail)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_cmd"
        and node is not next(
            (candidate for candidate in ast.walk(wrapper) if candidate is node),
            None,
        )
    ]
    errors = []
    if len(wrapper_calls) != FIXED_WRAPPER_CALLS:
        errors.append(
            f"fleet fixed wrapper call count changed: {len(wrapper_calls)} != {FIXED_WRAPPER_CALLS}"
        )
    for call in wrapper_calls:
        if len(call.args) != 1 or not _is_fixed(call.args[0], host_detail, call.lineno):
            errors.append(f"fleet.py:{call.lineno} _cmd no longer receives one fixed command")
    return errors


def raw_boundary_errors(calls: list[SinkCall], tree: ast.Module) -> list[str]:
    boundaries = [
        call
        for call in calls
        if (call.path, call.function, call.sink) == RAW_OPERATOR_BOUNDARY
    ]
    if len(boundaries) != 1:
        return [f"raw operator-command boundary count changed: {len(boundaries)} != 1"]
    call = boundaries[0]
    errors = []
    if not isinstance(call.command, ast.Name) or call.command.id != "cmd":
        errors.append(f"{call.label} no longer carries the declared raw cmd value")
    has_admin_check = any(
        isinstance(node, ast.Call)
        and _call_name(node.func) == "_check_session_role"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "admin"
        for node in ast.walk(call.scope)
    )
    if not has_admin_check:
        errors.append(f"{call.label} lost its explicit admin-role boundary")
    has_operator_cmd = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "cmd" for target in node.targets)
        and isinstance(node.value, ast.Subscript)
        and isinstance(node.value.value, ast.Call)
        and isinstance(node.value.value.func, ast.Attribute)
        and node.value.value.func.attr == "get"
        and node.value.value.args
        and isinstance(node.value.value.args[0], ast.Constant)
        and node.value.value.args[0].value == "cmd"
        for node in ast.walk(call.scope)
    )
    if not has_operator_cmd:
        errors.append(f"{call.label} is no longer the explicit operator-supplied command API")
    return errors


def _remote_command_policy_errors(call: SinkCall) -> list[str]:
    errors = []
    for node in ast.walk(call.command):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) == "remote_command":
            scripts = [keyword.value for keyword in node.keywords if keyword.arg == "script"]
            if scripts and not (
                len(scripts) == 1
                and isinstance(scripts[0], ast.Constant)
                and isinstance(scripts[0].value, str)
                and scripts[0].value
            ):
                errors.append(f"{call.label}: remote_command script must be one fixed literal")
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "shlex"
            and node.func.attr in {"join", "quote"}
        ):
            errors.append(f"{call.label}: caller-local shlex.{node.func.attr} bypasses serializer ownership")
    return errors


def serializer_call_errors(trees: dict[str, ast.Module]) -> list[str]:
    """Require an auditable literal shape at every serializer call site."""
    errors: list[str] = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node.func) != "remote_command":
                continue
            label = f"{path}:{node.lineno} remote_command"
            keywords = {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg}
            argv_values = ([node.args[0]] if node.args else []) + (
                [keywords["argv"]] if "argv" in keywords else []
            )
            script_values = [keywords["script"]] if "script" in keywords else []
            if len(node.args) > 1:
                errors.append(f"{label}: only argv may be positional")
            if len(argv_values) + len(script_values) != 1:
                errors.append(f"{label}: choose exactly one argv or script mode")
                continue
            if argv_values:
                argv = argv_values[0]
                if "args" in keywords and not (
                    isinstance(keywords["args"], (ast.Tuple, ast.List))
                    and not keywords["args"].elts
                ):
                    errors.append(f"{label}: argv mode cannot carry args")
                if not isinstance(argv, (ast.Tuple, ast.List)) or not argv.elts:
                    errors.append(f"{label}: argv must be one explicit non-empty tuple/list")
                else:
                    first = argv.elts[0]
                    if not (
                        isinstance(first, ast.Constant)
                        and isinstance(first.value, str)
                        and first.value
                    ):
                        errors.append(f"{label}: argv executable must be one fixed non-empty literal")
                    if (
                        len(argv.elts) >= 2
                        and isinstance(first, ast.Constant)
                        and first.value == "sh"
                        and isinstance(argv.elts[1], ast.Constant)
                        and argv.elts[1].value == "-c"
                    ):
                        errors.append(f"{label}: sh -c belongs in fixed-script mode")
            else:
                script = script_values[0]
                if node.args or "argv" in keywords:
                    errors.append(f"{label}: script mode cannot carry argv")
                if not (
                    isinstance(script, ast.Constant)
                    and isinstance(script.value, str)
                    and script.value
                ):
                    errors.append(f"{label}: script must be one fixed non-empty literal")
                args = keywords.get("args", ast.Tuple(elts=[], ctx=ast.Load()))
                if not isinstance(args, (ast.Tuple, ast.List)):
                    errors.append(f"{label}: script args must be one explicit tuple/list")
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and isinstance(child.func.value, ast.Name)
                    and child.func.value.id == "shlex"
                    and child.func.attr in {"join", "quote"}
                ):
                    errors.append(f"{label}: caller-local shlex.{child.func.attr} is forbidden")
    return errors


def construction_errors(calls: list[SinkCall], fleet_tree: ast.Module) -> list[str]:
    errors: list[str] = []
    for call in calls:
        if (call.path, call.function, call.sink) == RAW_OPERATOR_BOUNDARY:
            continue
        if call.path == "freq/api/fleet.py" and call.function == "_cmd":
            continue
        if (
            isinstance(call.command, ast.Name)
            and (call.path, call.function, call.sink, call.command.id) in CROSS_SCOPE_FIXED_COMMANDS
        ):
            continue
        errors.extend(_remote_command_policy_errors(call))
        if not _is_fixed(call.command, call.scope, call.lineno):
            errors.append(f"{call.label}: {ast.unparse(call.command)}")
    errors.extend(fixed_wrapper_errors(fleet_tree))
    errors.extend(raw_boundary_errors(calls, fleet_tree))
    return errors
