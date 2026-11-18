"""Domain-based REST API router for FREQ.

Maps URL prefixes to domain handler modules. Each domain module exports a
`register(routes: dict)` function that adds its routes to the master table.

serve.py calls `build_route_registry()` once before startup side effects, then
dispatches every request through that one complete registry.

Architecture:
    - Every CLI domain has a matching API module: freq/api/vm.py, etc.
    - API endpoints retain their established public paths
    - Handlers receive the request handler and use _json_response()
    - Transport-local handlers and domain handlers share one collision-free registry
"""

from collections.abc import MutableMapping

from freq.core import log as logger

class RouteRegistrationError(RuntimeError):
    """Raised when the route registry cannot be built without ambiguity."""


class _StrictRouteMap(MutableMapping):
    """Add-only registrar that rejects shadowing through every mutation API."""

    def __init__(self):
        self._routes = {}

    def __getitem__(self, path):
        return self._routes[path]

    def __iter__(self):
        return iter(self._routes)

    def __len__(self):
        return len(self._routes)

    def __setitem__(self, path, handler):
        if path in self._routes:
            raise RouteRegistrationError(f"duplicate route registration: {path}")
        self._routes[path] = handler

    def __delitem__(self, path):
        raise RouteRegistrationError(f"route registrations are add-only: {path}")

    def update(self, other=(), /, **kwargs):
        if hasattr(other, "keys"):
            items = [(path, other[path]) for path in other.keys()]
        else:
            items = list(other)
        items.extend(kwargs.items())

        seen = set()
        for path, _handler in items:
            if path in self._routes or path in seen:
                raise RouteRegistrationError(f"duplicate route registration: {path}")
            seen.add(path)
        for path, handler in items:
            self._routes[path] = handler

    def __ior__(self, other):
        self.update(other)
        return self

    def setdefault(self, path, default=None):
        if path in self._routes:
            raise RouteRegistrationError(f"duplicate route registration: {path}")
        self._routes[path] = default
        return default


_DOMAIN_MODULES = (
    "freq.api.vm",
    "freq.api.cluster_report",
    "freq.api.ct",
    "freq.api.fleet",
    "freq.api.host",
    "freq.api.pve_read",
    "freq.api.lab_guest",
    "freq.api.lab_qualification",
    "freq.api.secure",
    "freq.api.observe",
    "freq.api.state",
    "freq.api.v1_stubs",
    "freq.api.net",
    "freq.api.docker_api",
    "freq.api.hw",
    "freq.api.store",
    "freq.api.dr",
    "freq.api.auto",
    "freq.api.ops",
    "freq.api.user",
    "freq.api.plugin",
    "freq.api.terminal",
    "freq.api.fw",
    "freq.api.opnsense",
    "freq.api.ipmi",
    "freq.api.redfish",
    "freq.api.bench",
    "freq.api.synology",
    "freq.api.logs",
    "freq.api.backup_verify",
    "freq.api.cert_lifecycle",
    "freq.api.snmp",
)


def _register_domain_routes(routes: dict) -> None:
    """Register every expected domain atomically into the caller-owned map."""
    import importlib

    import_errors = []
    for module_path in _DOMAIN_MODULES:
        try:
            mod = importlib.import_module(module_path)
        except ImportError as e:
            import_errors.append(f"{module_path}: {e}")
            continue
        register = getattr(mod, "register", None)
        if not callable(register):
            raise RouteRegistrationError(f"route module has no register() callable: {module_path}")
        register(routes)

    if import_errors:
        logger.error("api_route_import_failed", count=len(import_errors), modules="; ".join(import_errors))
        raise ImportError("API route import failures: " + "; ".join(import_errors))


def build_routes() -> dict:
    """Build the collision-free domain route declarations.

    This public helper remains the domain-only view used by contract tooling.
    Runtime dispatch uses :func:`build_route_registry` below.
    """
    routes = _StrictRouteMap()
    _register_domain_routes(routes)
    return dict(routes)


def build_route_registry(local_routes: dict) -> dict:
    """Build one atomic registry from transport-local and domain declarations."""
    routes = _StrictRouteMap()
    for path, handler in local_routes.items():
        routes[path] = handler
    _register_domain_routes(routes)
    return dict(routes)
