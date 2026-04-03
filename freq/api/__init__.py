"""Domain-based REST API router for FREQ.

Maps URL prefixes to domain handler modules. Each domain module exports a
`register(routes: dict)` function that adds its routes to the master table.

serve.py calls `build_routes()` once at startup to populate the route table,
then dispatches each request to the appropriate handler method.

Architecture:
    - Every CLI domain has a matching API module: freq/api/vm.py, etc.
    - API endpoints follow CLI structure: /api/v1/<domain>/<action>
    - Handlers receive (request_handler, cfg) and use _json_response()
    - Legacy /api/ routes remain in serve.py during migration, new routes go here
"""

# Domain modules register their routes here
_DOMAIN_ROUTES: dict = {}


def build_routes() -> dict:
    """Build the master route table by collecting routes from all domain modules.

    Returns a dict of {"/api/v1/path": "handler_method_name"} for serve.py
    to merge into its _ROUTES dict.
    """
    routes = {}

    # Import each domain module and collect routes
    # Modules are imported on demand — missing modules don't break the API
    _domains = [
        "freq.api.vm",
        "freq.api.ct",
        "freq.api.fleet",
        "freq.api.host",
        "freq.api.secure",
        "freq.api.observe",
        "freq.api.state",
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
        "freq.api.v1_stubs",
        "freq.api.fw",
        "freq.api.opnsense",
        "freq.api.ipmi",
        "freq.api.redfish",
        "freq.api.bench",
        "freq.api.synology",
        "freq.api.logs",
        "freq.api.backup_verify",
    ]

    for module_path in _domains:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            if hasattr(mod, "register"):
                mod.register(routes)
        except ImportError:
            pass  # Domain module not yet created — that's fine during migration

    return routes
