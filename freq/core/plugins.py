"""Plugin system for FREQ.

Drop a .py file in conf/plugins/ and FREQ auto-loads it as a command.

Each plugin must define:
  NAME = "my-command"          # command name
  DESCRIPTION = "What it does"  # help text
  def run(cfg, pack, args):     # handler function, returns exit code

Usage:
  mkdir -p conf/plugins/
  # Create conf/plugins/my_plugin.py with NAME, DESCRIPTION, run()
  freq my-command               # it just works

Plugins are loaded after built-in commands. They cannot override built-ins.
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


