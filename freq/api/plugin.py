"""Plugin management API endpoints.

Routes:
    GET  /api/v1/plugin/list     — list installed plugins
    GET  /api/v1/plugin/info     — plugin details
    GET  /api/v1/plugin/types    — available plugin types
    POST /api/v1/plugin/install  — install from URL
    POST /api/v1/plugin/remove   — remove a plugin
"""

from freq.api.helpers import json_response, get_param, get_cfg


def register(routes):
    """Register plugin API routes."""
    routes["/api/v1/plugin/list"] = handle_plugin_list
    routes["/api/v1/plugin/info"] = handle_plugin_info
    routes["/api/v1/plugin/types"] = handle_plugin_types


def handle_plugin_list(handler):
    """GET /api/v1/plugin/list — list installed plugins."""
    from freq.modules.plugin_manager import _load_registry
    from freq.core.plugins import discover_plugins
    import os

    cfg = get_cfg()
    plugin_dir = os.path.join(cfg.conf_dir, "plugins")
    discovered = discover_plugins(plugin_dir)
    registry = _load_registry(cfg)

    plugins = []
    for p in discovered:
        name = p["name"]
        reg = registry["plugins"].get(name, {})
        plugins.append(
            {
                "name": name,
                "description": p["description"],
                "type": reg.get("type", "command"),
                "version": reg.get("version", "local"),
                "source": reg.get("source", "local"),
            }
        )

    # Add deployer plugins from registry not in discovery
    for name, info in registry["plugins"].items():
        if info.get("type") == "deployer":
            plugins.append(
                {
                    "name": name,
                    "description": info.get("description", ""),
                    "type": "deployer",
                    "version": info.get("version", "local"),
                    "category": info.get("category", ""),
                }
            )

    json_response(handler, {"plugins": plugins})


def handle_plugin_info(handler):
    """GET /api/v1/plugin/info — plugin details."""
    from freq.modules.plugin_manager import _load_registry

    cfg = get_cfg()
    name = get_param(handler, "name")
    if not name:
        json_response(handler, {"error": "name required"}, 400)
        return

    registry = _load_registry(cfg)
    info = registry["plugins"].get(name)

    if not info:
        json_response(handler, {"error": f"plugin {name} not found"}, 404)
        return

    json_response(handler, {"plugin": {name: info}})


def handle_plugin_types(handler):
    """GET /api/v1/plugin/types — available plugin types."""
    from freq.modules.plugin_manager import PLUGIN_TYPES

    json_response(handler, {"types": PLUGIN_TYPES})
