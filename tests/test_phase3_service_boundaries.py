"""Architecture guards for the Phase-3 service strangler."""

from ast import Attribute, Call, FunctionDef, Import, ImportFrom, Name, parse, walk
from pathlib import Path

API_ROOT = Path(__file__).parents[1] / "freq" / "api"
MODULES_ROOT = API_ROOT.parent / "modules"
AUTO_PATH = API_ROOT / "auto.py"
CAPACITY_PATH = API_ROOT.parent / "jarvis" / "capacity.py"
COST_PATH = API_ROOT.parent / "jarvis" / "cost.py"
DOCKER_API_PATH = API_ROOT / "docker_api.py"
DASHBOARD_STATE_PATH = API_ROOT.parent / "services" / "dashboard_state.py"
DASHBOARD_EVENTS_PATH = API_ROOT.parent / "services" / "dashboard_events.py"
IDRAC_SESSION_PATH = API_ROOT.parent / "services" / "idrac_session.py"
PVE_DISCOVERY_PATH = API_ROOT.parent / "services" / "pve_discovery.py"
PVE_INVENTORY_PATH = API_ROOT.parent / "services" / "pve_inventory.py"
PVE_PATH = API_ROOT.parent / "services" / "pve.py"
PVE_TAGS_PATH = API_ROOT.parent / "services" / "pve_tags.py"
PVE_TRANSPORT_PATH = API_ROOT.parent / "services" / "pve_transport.py"
VM_VISIBILITY_PATH = API_ROOT.parent / "services" / "vm_visibility.py"
SERVE_PATH = MODULES_ROOT / "serve.py"
DASHBOARD_STATE_NAMES = {
    "_SERVER_START_TIME",
    "_activity_feed",
    "_activity_lock",
    "_bg_cache",
    "_bg_cache_errors",
    "_bg_cache_from_disk",
    "_bg_cache_ts",
    "_bg_lock",
}
DASHBOARD_EVENT_NAMES = {
    "_sse_clients",
    "_sse_lock",
    "_sse_subscribe",
    "_sse_unsubscribe",
    "_sse_broadcast",
    "_activity_add",
}
PVE_DISCOVERY_NAMES = {
    "_bg_discover_pve_nodes",
    "_find_reachable_pve_node",
    "_get_discovered_node_ips",
    "_get_discovered_nodes",
}
PVE_TAG_NAMES = {"_bg_fetch_vm_tags", "get_vm_tags", "is_vm_tagged"}
PVE_TRANSPORT_NAMES = {
    "_runtime_pve_api_token_secret",
    "_has_pve_api_token",
    "_pve_api_call",
    "_pve_call",
    "_pve_cmd",
}
VM_VISIBILITY_NAMES = {
    "_label_key",
    "_managed_dashboard_vm_identities",
    "_category_vmids",
    "_dashboard_vm_scope",
    "_dashboard_vm_visible",
}


def _attribute_path(node):
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Attribute):
        parent = _attribute_path(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _serve_dependency_paths(source: str) -> list[str]:
    """Resolve import aliases and return every dependency on the serve module."""
    tree = parse(source)
    aliases = {}
    offenders = set()
    for node in walk(tree):
        if isinstance(node, Import):
            for imported in node.names:
                bound = imported.asname or imported.name.split(".", 1)[0]
                aliases[bound] = imported.name if imported.asname else bound
                if imported.name == "freq.modules.serve" or imported.name.startswith(
                    "freq.modules.serve."
                ):
                    offenders.add(imported.name)
        elif isinstance(node, ImportFrom) and node.module:
            for imported in node.names:
                qualified = f"{node.module}.{imported.name}"
                aliases[imported.asname or imported.name] = qualified
                if qualified == "freq.modules.serve" or qualified.startswith(
                    "freq.modules.serve."
                ):
                    offenders.add(qualified)

    for node in walk(tree):
        if not isinstance(node, Attribute):
            continue
        raw = _attribute_path(node)
        head, separator, tail = raw.partition(".")
        expanded = aliases.get(head, head) + (separator + tail if separator else "")
        if expanded == "freq.modules.serve" or expanded.startswith("freq.modules.serve."):
            offenders.add(expanded)
    return sorted(offenders)


def test_api_auth_consumers_import_auth_service_directly():
    """Domain APIs must not route authorization upward through serve.py."""
    consumers = set()
    direct_importers = set()
    upward_auth_imports = []

    for path in sorted(API_ROOT.glob("*.py")):
        tree = parse(path.read_text())
        for node in walk(tree):
            if (
                isinstance(node, Call)
                and isinstance(node.func, Name)
                and node.func.id == "_check_session_role"
            ):
                consumers.add(path.name)
            if not isinstance(node, ImportFrom):
                continue
            for imported in node.names:
                if node.module == "freq.modules.serve" and imported.name == "_check_session_role":
                    upward_auth_imports.append(f"{path.name}:{node.lineno}")
                if (
                    node.module == "freq.api.auth"
                    and imported.name == "check_session_role"
                    and imported.asname == "_check_session_role"
                ):
                    direct_importers.add(path.name)

    assert not upward_auth_imports
    assert consumers == direct_importers


def test_serve_auth_alias_remains_the_same_compatibility_callable():
    """Legacy serve handlers keep the existing auth compatibility surface."""
    from freq.api.auth import check_session_role
    from freq.modules.serve import _check_session_role

    assert _check_session_role is check_session_role


def test_api_dashboard_state_does_not_route_through_serve():
    """API state consumers must import the state service, including module aliases."""
    offenders = []

    for path in sorted(API_ROOT.glob("*.py")):
        tree = parse(path.read_text())
        serve_aliases = set()
        for node in walk(tree):
            if isinstance(node, ImportFrom) and node.module == "freq.modules":
                for imported in node.names:
                    if imported.name == "serve":
                        serve_aliases.add(imported.asname or imported.name)
            if isinstance(node, Import):
                for imported in node.names:
                    if imported.name == "freq.modules.serve":
                        serve_aliases.add(imported.asname or imported.name)

        for node in walk(tree):
            if isinstance(node, ImportFrom) and node.module == "freq.modules.serve":
                for imported in node.names:
                    if imported.name in DASHBOARD_STATE_NAMES:
                        offenders.append(f"{path.name}:{node.lineno}:{imported.name}")
            if not isinstance(node, Attribute) or node.attr not in DASHBOARD_STATE_NAMES:
                continue
            owner = _attribute_path(node.value)
            if owner == "freq.modules.serve" or owner in serve_aliases:
                offenders.append(f"{path.name}:{node.lineno}:{owner}.{node.attr}")

    assert not offenders
    assert not _serve_dependency_paths(AUTO_PATH.read_text())
    assert not _serve_dependency_paths(CAPACITY_PATH.read_text())
    assert not _serve_dependency_paths(COST_PATH.read_text())
    assert not _serve_dependency_paths(DOCKER_API_PATH.read_text())


def test_dashboard_state_is_single_owner_with_compatibility_identity():
    """Transport and API aliases must share the service's exact mutable objects."""
    from freq.api import fleet, hw, observe, vm
    from freq.modules import serve
    from freq.services import dashboard_state

    assert dashboard_state.background_cache is serve._bg_cache
    assert dashboard_state.background_cache is fleet._bg_cache
    assert dashboard_state.background_cache is hw._bg_cache
    assert dashboard_state.background_cache is observe._bg_cache
    assert dashboard_state.background_cache is vm._bg_cache
    assert dashboard_state.background_cache_timestamps is serve._bg_cache_ts
    assert dashboard_state.background_cache_timestamps is fleet._bg_cache_ts
    assert dashboard_state.background_cache_timestamps is hw._bg_cache_ts
    assert dashboard_state.background_cache_timestamps is vm._bg_cache_ts
    assert dashboard_state.background_cache_errors is serve._bg_cache_errors
    assert dashboard_state.background_cache_errors is fleet._bg_cache_errors
    assert dashboard_state.background_cache_from_disk is serve._bg_cache_from_disk
    assert dashboard_state.background_cache_from_disk is fleet._bg_cache_from_disk
    assert dashboard_state.background_cache_lock is serve._bg_lock
    assert dashboard_state.background_cache_lock is fleet._bg_lock
    assert dashboard_state.background_cache_lock is hw._bg_lock
    assert dashboard_state.background_cache_lock is observe._bg_lock
    assert dashboard_state.background_cache_lock is vm._bg_lock
    assert dashboard_state.activity_feed is serve._activity_feed
    assert dashboard_state.activity_feed is fleet._activity_feed
    assert dashboard_state.activity_feed.maxlen == 200
    assert dashboard_state.activity_lock is serve._activity_lock
    assert dashboard_state.activity_lock is fleet._activity_lock
    assert dashboard_state.server_start_time is serve._SERVER_START_TIME
    assert dashboard_state.server_start_time is observe._SERVER_START_TIME


def test_dashboard_state_service_has_only_stdlib_dependencies():
    tree = parse(DASHBOARD_STATE_PATH.read_text())
    imported_modules = set()
    for node in walk(tree):
        if isinstance(node, Import):
            imported_modules.update(imported.name.split(".", 1)[0] for imported in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            imported_modules.add(node.module.split(".", 1)[0])

    assert imported_modules == {"collections", "threading", "time"}


def test_fleet_percentage_parser_preserves_metric_and_failure_truth():
    """Fleet summaries must keep exact percent, ratio, and invalid-input behavior."""
    from freq.api.fleet import _parse_pct
    from freq.core.health_state import parse_metric_percentage
    from freq.modules.serve import _parse_pct as serve_parse_pct

    cases = (
        ("", 0.0),
        (None, 0.0),
        ("45%", 45.0),
        ("45% busy", 45.0),
        ("4096/8192MB", 50.0),
        ("1/3GB", 33.3),
        ("1/0MB", 0.0),
        ("101%", 101.0),
        ("45.5%", 0.0),
        (" 45%", 0.0),
        ("unknown", 0.0),
    )
    assert [(raw, _parse_pct(raw)) for raw, _expected in cases] == [
        (raw, expected) for raw, expected in cases
    ]
    assert _parse_pct is parse_metric_percentage
    assert serve_parse_pct is parse_metric_percentage

    assert not _serve_dependency_paths((API_ROOT / "fleet.py").read_text())

    forbidden_shapes = {
        "direct from import": "from freq.modules.serve import _parse_pct",
        "direct from alias": "from freq.modules.serve import _parse_pct as parse_pct",
        "from-module alias": (
            "from freq.modules import serve as transport\n"
            "_parse_pct = transport._parse_pct"
        ),
        "import-module alias": (
            "import freq.modules.serve as transport\n"
            "_parse_pct = transport._parse_pct"
        ),
        "modules attribute alias": (
            "import freq.modules as modules\n"
            "_parse_pct = modules.serve._parse_pct"
        ),
        "root attribute alias": (
            "import freq as package\n"
            "_parse_pct = package.modules.serve._parse_pct"
        ),
        "from-root attribute alias": (
            "from freq import modules as modules\n"
            "_parse_pct = modules.serve._parse_pct"
        ),
    }
    for name, source in forbidden_shapes.items():
        assert _serve_dependency_paths(source), name

    allowed_shapes = {
        "core owner": "from freq.core.health_state import parse_metric_percentage as _parse_pct",
        "neighbor from import": "from freq.modules import pve as pve_module",
        "neighbor module alias": "import freq.modules.pve as pve_module",
        "unrelated attribute": "import freq.modules as modules\nowner = modules.pve._pve_cmd",
    }
    for name, source in allowed_shapes.items():
        assert not _serve_dependency_paths(source), name


def test_api_dashboard_events_do_not_route_through_serve():
    """API event consumers must import the event service directly."""
    offenders = []

    for path in sorted(API_ROOT.glob("*.py")):
        tree = parse(path.read_text())
        serve_aliases = set()
        for node in walk(tree):
            if isinstance(node, ImportFrom) and node.module == "freq.modules":
                for imported in node.names:
                    if imported.name == "serve":
                        serve_aliases.add(imported.asname or imported.name)
            if isinstance(node, Import):
                for imported in node.names:
                    if imported.name == "freq.modules.serve":
                        serve_aliases.add(imported.asname or imported.name)

        for node in walk(tree):
            if isinstance(node, ImportFrom) and node.module == "freq.modules.serve":
                for imported in node.names:
                    if imported.name in DASHBOARD_EVENT_NAMES:
                        offenders.append(f"{path.name}:{node.lineno}:{imported.name}")
            if not isinstance(node, Attribute) or node.attr not in DASHBOARD_EVENT_NAMES:
                continue
            owner = _attribute_path(node.value)
            if owner == "freq.modules.serve" or owner in serve_aliases:
                offenders.append(f"{path.name}:{node.lineno}:{owner}.{node.attr}")

    assert not offenders


def test_dashboard_events_have_one_service_owner_and_exact_consumer_identity():
    from freq.api import vm
    from freq.modules import serve
    from freq.services import dashboard_events, dashboard_state

    for name in DASHBOARD_EVENT_NAMES:
        assert getattr(serve, name) is getattr(dashboard_events, name)
    assert vm._sse_broadcast is dashboard_events._sse_broadcast
    assert dashboard_events.dashboard_state.activity_feed is dashboard_state.activity_feed
    assert dashboard_events.dashboard_state.activity_lock is dashboard_state.activity_lock

    service_tree = parse(DASHBOARD_EVENTS_PATH.read_text())
    serve_tree = parse(SERVE_PATH.read_text())
    service_defs = {node.name for node in service_tree.body if hasattr(node, "name")}
    serve_defs = {node.name for node in serve_tree.body if hasattr(node, "name")}
    assert {"_sse_subscribe", "_sse_unsubscribe", "_sse_broadcast", "_activity_add"} <= service_defs
    assert not ({"_sse_subscribe", "_sse_unsubscribe", "_sse_broadcast", "_activity_add"} & serve_defs)


def test_dashboard_events_dependency_direction_is_cycle_clean():
    tree = parse(DASHBOARD_EVENTS_PATH.read_text())
    imports = []
    for node in walk(tree):
        if isinstance(node, Import):
            imports.extend(imported.name for imported in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            imports.append(node.module)

    assert imports == ["queue", "threading", "time", "freq.services"]


def test_idrac_session_service_is_cycle_clean_and_consumed_directly():
    from freq.api import hw, terminal
    from freq.modules import serve
    from freq.services import idrac_session

    assert serve.IDRAC_SESSION_LOCK is idrac_session.IDRAC_SESSION_LOCK
    assert serve._run_idrac_session is idrac_session._run_idrac_session
    assert serve._run_idrac_subprocess is idrac_session._run_idrac_subprocess
    assert hw._run_idrac_session is idrac_session._run_idrac_session
    assert terminal._run_idrac_session is idrac_session._run_idrac_session
    assert "freq.modules.serve" not in IDRAC_SESSION_PATH.read_text()
    assert "from freq.modules import serve" not in (API_ROOT / "hw.py").read_text()
    assert "from freq.modules import serve" not in (API_ROOT / "terminal.py").read_text()


def test_api_idrac_session_access_is_symbol_aware_and_service_has_one_owner():
    owned = {"IDRAC_SESSION_LOCK", "IDRAC_SESSION_GAP_SECONDS", "_idrac_last_session_at", "_run_idrac_session", "_run_idrac_subprocess"}
    offenders = []
    for path in sorted(API_ROOT.glob("*.py")):
        tree = parse(path.read_text())
        serve_aliases = set()
        for node in walk(tree):
            if isinstance(node, Import):
                for imported in node.names:
                    if imported.name == "freq.modules.serve":
                        serve_aliases.add(imported.asname or imported.name)
            if isinstance(node, ImportFrom) and node.module == "freq.modules.serve":
                for imported in node.names:
                    if imported.name in owned:
                        offenders.append(f"{path.name}:{node.lineno}:{imported.name}")
            if isinstance(node, ImportFrom) and node.module == "freq.modules":
                serve_aliases.update((item.asname or item.name) for item in node.names if item.name == "serve")
        for node in walk(tree):
            if (
                isinstance(node, Attribute)
                and node.attr in owned
                and _attribute_path(node.value) in (serve_aliases | {"freq.modules.serve"})
            ):
                offenders.append(f"{path.name}:{node.lineno}:{node.attr}")
    assert not offenders

    tree = parse(IDRAC_SESSION_PATH.read_text())
    imports = []
    for node in walk(tree):
        if isinstance(node, Import):
            imports.extend(item.name for item in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            imports.append(node.module)
    assert imports == ["subprocess", "threading", "time"]
    serve_source = SERVE_PATH.read_text()
    assert "_idrac_last_session_at =" not in serve_source
    serve_tree = parse(serve_source)
    serve_defs = {node.name for node in serve_tree.body if hasattr(node, "name")}
    assert "_run_idrac_session" not in serve_defs
    assert "_run_idrac_subprocess" not in serve_defs


def test_api_pve_discovery_does_not_route_through_serve():
    """PVE discovery consumers must not route the three owned calls upward."""
    offenders = []

    for path in sorted(API_ROOT.glob("*.py")):
        tree = parse(path.read_text())
        serve_aliases = set()
        for node in walk(tree):
            if isinstance(node, ImportFrom) and node.module == "freq.modules":
                for imported in node.names:
                    if imported.name == "serve":
                        serve_aliases.add(imported.asname or imported.name)
            if isinstance(node, Import):
                for imported in node.names:
                    if imported.name == "freq.modules.serve":
                        serve_aliases.add(imported.asname or imported.name)

        for node in walk(tree):
            if isinstance(node, ImportFrom) and node.module == "freq.modules.serve":
                for imported in node.names:
                    if imported.name in PVE_DISCOVERY_NAMES:
                        offenders.append(f"{path.name}:{node.lineno}:{imported.name}")
            if not isinstance(node, Attribute) or node.attr not in PVE_DISCOVERY_NAMES:
                continue
            owner = _attribute_path(node.value)
            if owner == "freq.modules.serve" or owner in serve_aliases:
                offenders.append(f"{path.name}:{node.lineno}:{owner}.{node.attr}")

    assert not offenders


def test_pve_discovery_has_compatibility_and_consumer_identity():
    """Serve compatibility and API-local aliases are the service callables."""
    from freq.api import fleet, terminal, vm
    from freq.modules import serve
    from freq.services import dashboard_state, pve_discovery

    assert serve._bg_discover_pve_nodes is pve_discovery._bg_discover_pve_nodes
    assert serve._find_reachable_pve_node is pve_discovery.find_reachable_pve_node
    assert serve._get_discovered_node_ips is pve_discovery._get_discovered_node_ips
    assert serve._get_discovered_nodes is pve_discovery._get_discovered_nodes
    assert fleet._get_discovered_node_ips is pve_discovery._get_discovered_node_ips
    assert fleet._get_discovered_nodes is pve_discovery._get_discovered_nodes
    assert vm._get_discovered_node_ips is pve_discovery._get_discovered_node_ips
    assert terminal._get_discovered_nodes is pve_discovery._get_discovered_nodes
    assert pve_discovery._bg_cache is dashboard_state.background_cache
    assert pve_discovery._bg_cache_ts is dashboard_state.background_cache_timestamps
    assert pve_discovery._bg_lock is dashboard_state.background_cache_lock
    assert serve.NODE_DISCOVERY_INTERVAL == pve_discovery.NODE_DISCOVERY_INTERVAL == 300
    serve_tree = parse(SERVE_PATH.read_text())
    serve_functions = [node for node in walk(serve_tree) if isinstance(node, FunctionDef)]
    serve_defs = {node.name for node in serve_functions}
    service_defs = {
        node.name
        for node in walk(parse(PVE_DISCOVERY_PATH.read_text()))
        if isinstance(node, FunctionDef)
    }
    assert "_find_reachable_pve_node" not in serve_defs
    assert "find_reachable_pve_node" in service_defs
    assert "read_backup_schedules" in service_defs

    backup_handler = next(node for node in serve_functions if node.name == "_serve_backup_schedules")
    assert len(backup_handler.body) == 2
    assert [
        _attribute_path(node.func)
        for node in walk(backup_handler)
        if isinstance(node, Call)
    ] == [
        "self._json_response",
        "_pve_discovery.read_backup_schedules",
        "load_config",
    ]


def test_pve_discovery_service_has_no_transport_or_router_dependency():
    tree = parse(PVE_DISCOVERY_PATH.read_text())
    service_package = ("freq", "services")
    imported_modules = set()
    for node in walk(tree):
        if isinstance(node, Import):
            imported_modules.update(imported.name for imported in node.names)
        elif isinstance(node, ImportFrom):
            resolved_parts = []
            if node.level:
                keep = len(service_package) - node.level + 1
                resolved_parts.extend(service_package[:max(keep, 0)])
            if node.module:
                resolved_parts.extend(node.module.split("."))
            resolved_base = ".".join(resolved_parts)
            if resolved_base:
                imported_modules.add(resolved_base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                imported_modules.add(
                    ".".join(part for part in (resolved_base, alias.name) if part)
                )

    assert not any(
        module == "freq.api"
        or module.startswith("freq.api.")
        or module == "freq.modules"
        or module.startswith("freq.modules.")
        for module in imported_modules
    )


def test_pve_tag_consumers_do_not_route_through_serve():
    """API and CLI consumers must not route the owned tag calls upward."""
    offenders = []

    for root in (API_ROOT, MODULES_ROOT):
        for path in sorted(root.glob("*.py")):
            if path.name == "serve.py":
                continue
            tree = parse(path.read_text())
            serve_aliases = set()
            for node in walk(tree):
                if isinstance(node, ImportFrom) and node.module == "freq.modules":
                    for imported in node.names:
                        if imported.name == "serve":
                            serve_aliases.add(imported.asname or imported.name)
                if isinstance(node, Import):
                    for imported in node.names:
                        if imported.name == "freq.modules.serve":
                            serve_aliases.add(imported.asname or imported.name)

            for node in walk(tree):
                if isinstance(node, ImportFrom) and node.module == "freq.modules.serve":
                    for imported in node.names:
                        if imported.name in PVE_TAG_NAMES:
                            offenders.append(f"{path.name}:{node.lineno}:{imported.name}")
                if not isinstance(node, Attribute) or node.attr not in PVE_TAG_NAMES:
                    continue
                owner = _attribute_path(node.value)
                if owner == "freq.modules.serve" or owner in serve_aliases:
                    offenders.append(f"{path.name}:{node.lineno}:{owner}.{node.attr}")

    assert not offenders


def test_pve_tags_have_compatibility_consumer_and_state_identity():
    """All stable names share the service callables and dashboard state."""
    from freq.api import vm as api_vm
    from freq.modules import pve, serve, vm
    from freq.services import dashboard_state, pve_tags

    assert serve._bg_fetch_vm_tags is pve_tags._bg_fetch_vm_tags
    assert serve.get_vm_tags is pve_tags.get_vm_tags
    assert serve.is_vm_tagged is pve_tags.is_vm_tagged
    assert api_vm.get_vm_tags is pve_tags.get_vm_tags
    assert vm.get_vm_tags is pve_tags.get_vm_tags
    assert pve.get_vm_tags is pve_tags.get_vm_tags
    assert pve_tags._bg_cache is dashboard_state.background_cache
    assert pve_tags._bg_cache_ts is dashboard_state.background_cache_timestamps
    assert pve_tags._bg_lock is dashboard_state.background_cache_lock
    assert serve.VM_TAGS_INTERVAL == pve_tags.VM_TAGS_INTERVAL == 300


def test_pve_tags_service_has_no_transport_router_or_api_dependency():
    tree = parse(PVE_TAGS_PATH.read_text())
    imported_modules = set()
    for node in walk(tree):
        if isinstance(node, Import):
            imported_modules.update(imported.name for imported in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert not any(
        module == "freq.api"
        or module.startswith("freq.api.")
        or module == "freq.modules.serve"
        or module.startswith("freq.modules.serve.")
        for module in imported_modules
    )


def test_vm_visibility_is_owned_by_dependency_clean_service():
    from ast import FunctionDef

    service_tree = parse(VM_VISIBILITY_PATH.read_text())
    serve_tree = parse(SERVE_PATH.read_text())
    service_definitions = {
        node.name for node in walk(service_tree) if isinstance(node, FunctionDef)
    }
    serve_definitions = {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    imported_modules = set()
    for node in walk(service_tree):
        if isinstance(node, Import):
            imported_modules.update(imported.name for imported in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            imported_modules.add(node.module)

    assert VM_VISIBILITY_NAMES <= service_definitions
    assert not VM_VISIBILITY_NAMES & serve_definitions
    assert imported_modules == set()


def test_vm_visibility_has_exact_serve_compatibility_identity():
    from freq.modules import serve
    from freq.services import vm_visibility

    for name in VM_VISIBILITY_NAMES:
        assert getattr(serve, name) is getattr(vm_visibility, name)


def test_pve_inventory_dependencies_are_patchable_at_service_owner(monkeypatch):
    from types import SimpleNamespace

    from freq.modules import serve
    from freq.services import pve_inventory

    cfg = SimpleNamespace(
        fleet_boundaries=SimpleNamespace(
            categorize=lambda vmid: ("production", "operator"),
            allowed_actions=lambda vmid: ["view"],
            is_prod=lambda vmid: False,
        )
    )
    scope = {"marker": "scope"}
    seen = []
    monkeypatch.setattr(pve_inventory, "_dashboard_vm_scope", lambda value: scope)
    monkeypatch.setattr(
        pve_inventory,
        "_dashboard_vm_visible",
        lambda vm, value: seen.append((vm["vmid"], value)) or True,
    )
    monkeypatch.setattr(pve_inventory, "_get_discovered_node_ips", lambda: ["192.0.2.10"])
    monkeypatch.setattr(pve_inventory, "get_vm_tags", lambda vmid: [])
    monkeypatch.setattr(
        pve_inventory,
        "_pve_call",
        lambda *args, **kwargs: (
            [{"vmid": 101, "name": "plex", "node": "pve01", "type": "qemu"}],
            True,
        ),
    )

    assert [vm["vmid"] for vm in serve._get_fleet_vms(cfg)] == [101]
    assert seen == [(101, scope)]


def test_pve_inventory_is_single_owner_with_direct_consumer_identity():
    from ast import FunctionDef

    from freq.api import fleet, terminal, vm
    from freq.modules import serve
    from freq.services import pve_inventory

    service_tree = parse(PVE_INVENTORY_PATH.read_text())
    serve_tree = parse(SERVE_PATH.read_text())
    assert {
        node.name for node in walk(service_tree) if isinstance(node, FunctionDef)
    } == {"_get_fleet_vms"}
    assert "_get_fleet_vms" not in {
        node.name for node in walk(serve_tree) if isinstance(node, FunctionDef)
    }
    assert serve._get_fleet_vms is pve_inventory._get_fleet_vms
    assert vm._get_fleet_vms is pve_inventory._get_fleet_vms
    assert fleet._get_fleet_vms is pve_inventory._get_fleet_vms
    assert terminal._get_fleet_vms is pve_inventory._get_fleet_vms


def test_pve_inventory_has_only_named_service_dependencies():
    tree = parse(PVE_INVENTORY_PATH.read_text())
    imports = set()
    imported_names = {}
    for node in walk(tree):
        if isinstance(node, Import):
            imports.update(imported.name for imported in node.names)
        elif isinstance(node, ImportFrom) and node.module:
            imports.add(node.module)
            imported_names[node.module] = {imported.name for imported in node.names}

    assert imports == {
        "json",
        "freq.services.pve_discovery",
        "freq.services.pve_tags",
        "freq.services.pve_transport",
        "freq.services.vm_visibility",
    }
    assert imported_names == {
        "freq.services.pve_discovery": {"_get_discovered_node_ips"},
        "freq.services.pve_tags": {"get_vm_tags"},
        "freq.services.pve_transport": {"_pve_call"},
        "freq.services.vm_visibility": {"_dashboard_vm_scope", "_dashboard_vm_visible"},
    }


def test_pve_inventory_api_consumers_do_not_route_upward_through_serve():
    offenders = []
    for name in ("vm.py", "fleet.py", "terminal.py"):
        path = API_ROOT / name
        tree = parse(path.read_text())
        serve_aliases = set()
        for node in walk(tree):
            if isinstance(node, ImportFrom) and node.module == "freq.modules":
                for imported in node.names:
                    if imported.name == "serve":
                        serve_aliases.add(imported.asname or imported.name)
            if isinstance(node, Import):
                for imported in node.names:
                    if imported.name == "freq.modules.serve":
                        serve_aliases.add(imported.asname or imported.name)
            if isinstance(node, ImportFrom) and node.module == "freq.modules.serve":
                if any(imported.name == "_get_fleet_vms" for imported in node.names):
                    offenders.append(f"{name}:{node.lineno}:direct")
            if isinstance(node, Attribute) and node.attr == "_get_fleet_vms":
                owner = _attribute_path(node.value)
                if owner == "freq.modules.serve" or owner in serve_aliases:
                    offenders.append(f"{name}:{node.lineno}:{owner}")

    assert not offenders


def test_pve_transport_service_owns_foundation_without_upward_dependencies():
    from ast import FunctionDef

    transport_tree = parse(PVE_TRANSPORT_PATH.read_text())
    service_tree = parse(PVE_PATH.read_text())
    module_tree = parse((MODULES_ROOT / "pve.py").read_text())
    transport_definitions = {
        node.name for node in walk(transport_tree) if isinstance(node, FunctionDef)
    }
    service_definitions = {
        node.name for node in walk(service_tree) if isinstance(node, FunctionDef)
    }
    module_definitions = {
        node.name for node in walk(module_tree) if isinstance(node, FunctionDef)
    }
    imported_modules = set()
    for tree in (transport_tree, service_tree):
        for node in walk(tree):
            if isinstance(node, Import):
                imported_modules.update(imported.name for imported in node.names)
            elif isinstance(node, ImportFrom) and node.module:
                imported_modules.add(node.module)

    assert PVE_TRANSPORT_NAMES <= transport_definitions
    assert {"_pve_call", "_pve_cmd", "_find_reachable_node", "_find_vm_node"} <= service_definitions
    assert not module_definitions
    assert not any(
        module == "freq.api"
        or module.startswith("freq.api.")
        or module == "freq.modules"
        or module.startswith("freq.modules.")
        for module in imported_modules
    )


def test_pve_transport_exact_aliases_constants_and_patch_objects():
    from freq.modules import pve as legacy_pve
    from freq.services import pve, pve_transport

    assert legacy_pve is pve
    assert pve.PVE_CMD_TIMEOUT == pve_transport.PVE_CMD_TIMEOUT == 30
    assert pve.PVE_QUICK_TIMEOUT == pve_transport.PVE_QUICK_TIMEOUT == 10
    assert pve.PVE_API_PORT == pve_transport.PVE_API_PORT == 8006
    assert pve.PVE_API_TIMEOUT == pve_transport.PVE_API_TIMEOUT == 15
    assert pve._runtime_pve_api_token_secret is pve_transport._runtime_pve_api_token_secret
    assert pve._has_pve_api_token is pve_transport._has_pve_api_token
    assert pve._pve_api_call is pve_transport._pve_api_call
    assert pve.urllib is pve_transport.urllib
