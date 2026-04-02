"""Plugin management API endpoints.

Routes:
    GET  /api/v1/plugin/list     — list installed plugins
    GET  /api/v1/plugin/info     — plugin details
    GET  /api/v1/plugin/types    — available plugin types
    POST /api/v1/plugin/install  — install from URL
    POST /api/v1/plugin/remove   — remove a plugin
"""
from freq.api.helpers import json_response, get_param


def register(dispatch):
    """Register plugin API routes."""
    dispatch["plugin/list"] = _api_list
    dispatch["plugin/info"] = _api_info
    dispatch["plugin/types"] = _api_types


def _api_list(handler, params, cfg):
    """List installed plugins."""
    from freq.modules.plugin_manager import _load_registry
    from freq.core.plugins import discover_plugins
    import os

    plugin_dir = os.path.join(cfg.conf_dir, "plugins")
    discovered = discover_plugins(plugin_dir)
    registry = _load_registry(cfg)

    plugins = []
    for p in discovered:
        name = p["name"]
        reg = registry["plugins"].get(name, {})
        plugins.append({
            "name": name,
            "description": p["description"],
            "type": reg.get("type", "command"),
            "version": reg.get("version", "local"),
            "source": reg.get("source", "local"),
        })

    # Add deployer plugins from registry not in discovery
    for name, info in registry["plugins"].items():
        if info.get("type") == "deployer":
            plugins.append({
                "name": name,
                "description": info.get("description", ""),
                "type": "deployer",
                "version": info.get("version", "local"),
                "category": info.get("category", ""),
            })

    return json_response(handler, {"plugins": plugins})


def _api_info(handler, params, cfg):
    """Plugin details."""
    from freq.modules.plugin_manager import _load_registry

    name = get_param(params, "name")
    if not name:
        return json_response(handler, {"error": "name required"}, code=400)

    registry = _load_registry(cfg)
    info = registry["plugins"].get(name)

    if not info:
        return json_response(handler, {"error": f"plugin {name} not found"}, code=404)

    return json_response(handler, {"plugin": {name: info}})


def _api_types(handler, params, cfg):
    """Available plugin types."""
    from freq.modules.plugin_manager import PLUGIN_TYPES
    return json_response(handler, {"types": PLUGIN_TYPES})
