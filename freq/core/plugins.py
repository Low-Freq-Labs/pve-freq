"""Plugin discovery and registration for FREQ.

Provides: discover_plugins(plugin_dir) → list of plugin dicts

Drop a .py file in conf/plugins/ and FREQ auto-loads it as a CLI command.
Each plugin must define NAME, DESCRIPTION, and run(cfg, pack, args) → int.
Plugins are loaded after built-in commands and cannot override them.

Replaces: Custom scripting with no integration into the tool

Architecture:
    - Scans conf/plugins/ for .py files at startup
    - Uses importlib.util to load modules without polluting sys.modules
    - Returns list of {name, description, handler} dicts for cli.py to register
    - Invalid plugins are logged and skipped — never crash the CLI

Design decisions:
    - Plugins are top-level commands, not domain subcommands. Keep it simple.
    - No hot-reload. Plugins are discovered once at startup.
    - No dependency resolution between plugins. Each plugin is standalone.
"""
import importlib
import importlib.util
import os

from freq.core import log as logger


def discover_plugins(plugin_dir: str) -> list:
    """Find all .py plugins in the plugin directory.

    Returns list of dicts: {name, description, module, handler}
    """
    plugins = []

    if not os.path.isdir(plugin_dir):
        return plugins

    for filename in sorted(os.listdir(plugin_dir)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        filepath = os.path.join(plugin_dir, filename)
        module_name = f"freq_plugin_{filename[:-3]}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Validate plugin interface
            name = getattr(module, "NAME", None)
            description = getattr(module, "DESCRIPTION", "Plugin command")
            handler = getattr(module, "run", None)

            if not name or not handler:
                logger.warn(f"Plugin {filename} missing NAME or run()", plugin=filename)
                continue

            plugins.append({
                "name": name,
                "description": description,
                "module": module,
                "handler": handler,
                "file": filename,
            })

        except Exception as e:
            logger.error(f"Plugin load error: {filename}: {e}", plugin=filename)
            continue

    return plugins


