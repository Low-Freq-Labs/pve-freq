"""Plugin lifecycle management for FREQ.

Domain: freq plugin <list|install|remove|create|search|info|update>

Manages first-party and community plugins — device deployers, CLI commands,
importers, exporters, notification channels, dashboard widgets, and policy
checks. Users install plugins by URL or name; FREQ handles discovery,
validation, and registration.

Replaces: Writing custom scripts with no tool integration ($0 but fragile)

Architecture:
    - Plugin registry stored in conf/plugins/registry.json (installed plugins)
    - Plugin files live in conf/plugins/ (.py for commands, subdirs for complex)
    - Deployer plugins drop into freq/deployers/{category}/{vendor}.py
    - Uses urllib.request (stdlib) for remote install — no pip, no dependencies
    - Plugin scaffold via freq plugin create — generates correct interface

Design decisions:
    - Plugin types formalize what already works (conf/plugins/ + deployers/).
      This is standardization, not invention.
    - Install from URL downloads a single .py file or .tar.gz archive.
      No package manager — FREQ stays zero-dependency.
    - Plugins cannot override built-in commands. Name collision = rejected.
    - Registry tracks what was installed, from where, and when. Uninstall
      reverses exactly what install did.
"""
import json
import os
import shutil
import tarfile
import tempfile
import time

from freq.core import fmt

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

REGISTRY_FILE = "plugins/registry.json"       # Relative to conf_dir
PLUGIN_DIR = "plugins"                        # Relative to conf_dir
DEPLOYER_BASE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "deployers")

# Valid plugin types — each maps to a different install location
PLUGIN_TYPES = {
    "command":      "CLI command plugin — adds freq <name> top-level command",
    "deployer":     "Device deployer — adds freq init support for new vendor",
    "importer":     "Data importer — pulls data from external tools into FREQ",
    "exporter":     "Data exporter — pushes FREQ data to external systems",
    "notification": "Notification channel — adds alert delivery target",
    "widget":       "Dashboard widget — adds visualization to web UI",
    "policy":       "Compliance policy — custom security/audit checks",
}

# Scaffold templates per plugin type
SCAFFOLD_TEMPLATES = {
    "command": '''\
"""FREQ plugin — {name}.

Drop this in conf/plugins/ and it's automatically available as: freq {name} [args]
"""

NAME = "{name}"
DESCRIPTION = "{description}"
PLUGIN_TYPE = "command"
VERSION = "0.1.0"
AUTHOR = ""


def run(cfg, pack, args):
    """Main handler — receives config, personality pack, and parsed args."""
    from freq.core import fmt

    plugin_args = getattr(args, "plugin_args", [])

    fmt.header("{name}")
    fmt.blank()
    fmt.info("Plugin is working. Edit this file to add your logic.")
    fmt.blank()
    fmt.footer()
    return 0
''',
    "deployer": '''\
"""FREQ deployer — {name}.

Vendor: {name}
Platforms: (list supported hardware/software)
Auth: SSH with key auth after initial deploy

Getter interface:
    get_facts()        → hostname, model, serial, uptime, version

Setter interface:
    push_config(lines) → apply configuration lines
    save_config()      → persist running config
"""

CATEGORY = "{category}"
VENDOR = "{name}"
NEEDS_PASSWORD = False
NEEDS_RSA = False
PLUGIN_TYPE = "deployer"
VERSION = "0.1.0"


def deploy(ip, ctx, auth_pass, auth_key, auth_user):
    """Deploy FREQ service account to device."""
    raise NotImplementedError("Implement deploy() for {name}")


def remove(ip, svc_name, key_path, rsa_key_path=None):
    """Remove FREQ service account from device."""
    raise NotImplementedError("Implement remove() for {name}")


def get_facts(ip, cfg):
    """Return dict with hostname, model, serial, uptime, version."""
    raise NotImplementedError("Implement get_facts() for {name}")
''',
    "notification": '''\
"""FREQ notification plugin — {name}.

Sends alerts to {name} when FREQ events fire.
"""

NAME = "{name}"
DESCRIPTION = "Send notifications to {name}"
PLUGIN_TYPE = "notification"
VERSION = "0.1.0"


def send(message, severity="info", config=None):
    """Send a notification.

    Args:
        message: The alert text
        severity: info, warning, critical
        config: Dict of plugin-specific settings (API keys, URLs, etc.)
    Returns:
        True on success, False on failure
    """
    raise NotImplementedError("Implement send() for {name}")
''',
    "policy": '''\
"""FREQ compliance policy — {name}.

Custom policy check that runs during freq secure comply.
"""

NAME = "{name}"
DESCRIPTION = "{description}"
PLUGIN_TYPE = "policy"
VERSION = "0.1.0"


def check(host_ip, cfg):
    """Run compliance check against a host.

    Returns:
        list of dicts: [{{"rule": "...", "status": "pass|fail|skip", "detail": "..."}}]
    """
    return [
        {{"rule": "{name}-example", "status": "skip", "detail": "Not yet implemented"}},
    ]
''',
}

# Default scaffold for types without a specific template
DEFAULT_SCAFFOLD = '''\
"""FREQ {plugin_type} plugin — {name}.

Type: {plugin_type}
"""

NAME = "{name}"
DESCRIPTION = "{description}"
PLUGIN_TYPE = "{plugin_type}"
VERSION = "0.1.0"


def run(cfg, pack, args):
    """Main handler."""
    raise NotImplementedError("Implement run() for {name}")
'''


# ─────────────────────────────────────────────────────────────
# REGISTRY MANAGEMENT
# ─────────────────────────────────────────────────────────────

def _registry_path(cfg):
    """Full path to plugin registry JSON."""
    return os.path.join(cfg.conf_dir, REGISTRY_FILE)


def _load_registry(cfg):
    """Load or create plugin registry."""
    path = _registry_path(cfg)
    if os.path.isfile(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"plugins": {}}
    return {"plugins": {}}


def _save_registry(cfg, registry):
    """Persist plugin registry to disk."""
    path = _registry_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(registry, f, indent=2, sort_keys=True)


# ─────────────────────────────────────────────────────────────
# PLUGIN COMMANDS
# ─────────────────────────────────────────────────────────────

def cmd_plugin_list(cfg, pack, args):
    """List installed plugins."""
    from freq.core.plugins import discover_plugins

    plugin_dir = os.path.join(cfg.conf_dir, PLUGIN_DIR)
    plugins = discover_plugins(plugin_dir)
    registry = _load_registry(cfg)

    fmt.header("Installed Plugins")
    fmt.blank()

    if not plugins and not registry["plugins"]:
        fmt.info("No plugins installed.")
        fmt.info("  Install:  freq plugin install <url>")
        fmt.info("  Create:   freq plugin create --name my-plugin")
        fmt.blank()
        fmt.footer()
        return 0

    # Show command plugins from discovery
    if plugins:
        fmt.line(f"  {fmt.C.PURPLE_BOLD}Command Plugins{fmt.C.RESET}")
        for p in plugins:
            name = p["name"]
            desc = p["description"]
            reg_info = registry["plugins"].get(name, {})
            version = reg_info.get("version", "local")
            ptype = reg_info.get("type", "command")
            fmt.line(f"    {fmt.C.CYAN}{name:<20}{fmt.C.RESET} "
                     f"{fmt.C.DIM}v{version:<8}{fmt.C.RESET} "
                     f"{fmt.C.DIM}[{ptype}]{fmt.C.RESET}  {desc}")
        fmt.blank()

    # Show deployer plugins from registry
    deployer_plugins = {k: v for k, v in registry["plugins"].items()
                        if v.get("type") == "deployer"}
    if deployer_plugins:
        fmt.line(f"  {fmt.C.PURPLE_BOLD}Deployer Plugins{fmt.C.RESET}")
        for name, info in sorted(deployer_plugins.items()):
            cat = info.get("category", "unknown")
            ver = info.get("version", "local")
            fmt.line(f"    {fmt.C.CYAN}{cat}:{name:<15}{fmt.C.RESET} "
                     f"{fmt.C.DIM}v{ver}{fmt.C.RESET}  "
                     f"{info.get('description', '')}")
        fmt.blank()

    # Show other plugin types
    other = {k: v for k, v in registry["plugins"].items()
             if v.get("type") not in ("command", "deployer")}
    if other:
        fmt.line(f"  {fmt.C.PURPLE_BOLD}Other Plugins{fmt.C.RESET}")
        for name, info in sorted(other.items()):
            ptype = info.get("type", "unknown")
            ver = info.get("version", "local")
            fmt.line(f"    {fmt.C.CYAN}{name:<20}{fmt.C.RESET} "
                     f"{fmt.C.DIM}v{ver:<8}{fmt.C.RESET} "
                     f"{fmt.C.DIM}[{ptype}]{fmt.C.RESET}  "
                     f"{info.get('description', '')}")
        fmt.blank()

    fmt.footer()
    return 0


def cmd_plugin_info(cfg, pack, args):
    """Show details about a specific plugin."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq plugin info <name>")
        return 1

    registry = _load_registry(cfg)
    info = registry["plugins"].get(name)

    # Check plugin files directly
    plugin_file = os.path.join(cfg.conf_dir, PLUGIN_DIR, f"{name}.py")
    file_exists = os.path.isfile(plugin_file)

    if not info and not file_exists:
        fmt.error(f"Plugin not found: {name}")
        fmt.info("Run freq plugin list to see installed plugins")
        return 1

    fmt.header(f"Plugin: {name}")
    fmt.blank()

    if info:
        fmt.line(f"  {'Type:':<16} {info.get('type', 'command')}")
        fmt.line(f"  {'Version:':<16} {info.get('version', 'unknown')}")
        fmt.line(f"  {'Source:':<16} {info.get('source', 'local')}")
        fmt.line(f"  {'Installed:':<16} {info.get('installed_at', 'unknown')}")
        if info.get("author"):
            fmt.line(f"  {'Author:':<16} {info['author']}")
        if info.get("category"):
            fmt.line(f"  {'Category:':<16} {info['category']}")
        if info.get("description"):
            fmt.blank()
            fmt.line(f"  {info['description']}")

    if file_exists:
        fmt.blank()
        fmt.line(f"  {'File:':<16} {plugin_file}")

    fmt.blank()
    fmt.footer()
    return 0


def cmd_plugin_install(cfg, pack, args):
    """Install a plugin from URL or local path."""
    source = getattr(args, "source", None)
    if not source:
        fmt.error("Usage: freq plugin install <url-or-path>")
        fmt.info("  URL:   freq plugin install https://example.com/my-plugin.py")
        fmt.info("  Local: freq plugin install /path/to/plugin.py")
        return 1

    plugin_dir = os.path.join(cfg.conf_dir, PLUGIN_DIR)
    os.makedirs(plugin_dir, exist_ok=True)

    # Determine if source is URL or local file
    is_url = source.startswith("http://") or source.startswith("https://")

    if is_url:
        return _install_from_url(cfg, source, plugin_dir)
    elif os.path.isfile(source):
        return _install_from_file(cfg, source, plugin_dir)
    else:
        fmt.error(f"Source not found: {source}")
        fmt.info("Provide a URL (https://...) or a local file path")
        return 1


def _install_from_url(cfg, url, plugin_dir):
    """Download and install plugin from URL."""
    import urllib.request
    import urllib.error

    filename = url.rsplit("/", 1)[-1]
    if not filename.endswith((".py", ".tar.gz")):
        fmt.error("Plugin URL must end in .py or .tar.gz")
        return 1

    fmt.info(f"Downloading: {url}")

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=filename) as tmp:
            urllib.request.urlretrieve(url, tmp.name)
            tmp_path = tmp.name
    except urllib.error.URLError as e:
        fmt.error(f"Download failed: {e}")
        return 1

    try:
        if filename.endswith(".tar.gz"):
            return _install_archive(cfg, tmp_path, plugin_dir, source=url)
        else:
            return _install_single_file(cfg, tmp_path, plugin_dir, source=url)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _install_from_file(cfg, path, plugin_dir):
    """Install plugin from local file."""
    if path.endswith(".tar.gz"):
        return _install_archive(cfg, path, plugin_dir, source=path)
    elif path.endswith(".py"):
        return _install_single_file(cfg, path, plugin_dir, source=path)
    else:
        fmt.error("Plugin file must be .py or .tar.gz")
        return 1


def _install_single_file(cfg, src_path, plugin_dir, source="local"):
    """Install a single .py plugin file."""
    import importlib.util

    # Validate plugin before installing
    try:
        spec = importlib.util.spec_from_file_location("_validate", src_path)
        if spec is None or spec.loader is None:
            fmt.error("Invalid Python file")
            return 1
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        fmt.error(f"Plugin validation failed: {e}")
        return 1

    name = getattr(mod, "NAME", None)
    if not name:
        fmt.error("Plugin missing NAME constant")
        return 1

    ptype = getattr(mod, "PLUGIN_TYPE", "command")
    version = getattr(mod, "VERSION", "0.1.0")
    description = getattr(mod, "DESCRIPTION", "")
    author = getattr(mod, "AUTHOR", "")

    # Install based on type
    if ptype == "deployer":
        category = getattr(mod, "CATEGORY", None)
        if not category:
            fmt.error("Deployer plugin missing CATEGORY constant")
            return 1
        dest = os.path.join(DEPLOYER_BASE, category, f"{name}.py")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
    else:
        dest = os.path.join(plugin_dir, f"{name}.py")

    shutil.copy2(src_path, dest)

    # Register
    registry = _load_registry(cfg)
    registry["plugins"][name] = {
        "type": ptype,
        "version": version,
        "description": description,
        "author": author,
        "source": source,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "file": dest,
    }
    if ptype == "deployer":
        registry["plugins"][name]["category"] = getattr(mod, "CATEGORY", "")
        registry["plugins"][name]["vendor"] = getattr(mod, "VENDOR", name)
    _save_registry(cfg, registry)

    fmt.success(f"Installed: {name} v{version} [{ptype}]")
    fmt.info(f"  File: {dest}")
    if ptype == "command":
        fmt.info(f"  Usage: freq {name}")
    elif ptype == "deployer":
        fmt.info(f"  Usage: freq init (now supports {name} devices)")
    return 0


def _install_archive(cfg, archive_path, plugin_dir, source="local"):
    """Install plugin from .tar.gz archive."""
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with tarfile.open(archive_path, "r:gz") as tf:
                # Security: reject paths that escape the extract dir
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in member.name:
                        fmt.error(f"Unsafe archive path: {member.name}")
                        return 1
                tf.extractall(tmpdir)
        except tarfile.TarError as e:
            fmt.error(f"Invalid archive: {e}")
            return 1

        # Find the plugin entry point (plugin.py or __init__.py)
        entries = os.listdir(tmpdir)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmpdir, entries[0])):
            root = os.path.join(tmpdir, entries[0])
        else:
            root = tmpdir

        entry = None
        for candidate in ("plugin.py", "__init__.py"):
            path = os.path.join(root, candidate)
            if os.path.isfile(path):
                entry = path
                break

        if not entry:
            # Try any .py file
            py_files = [f for f in os.listdir(root) if f.endswith(".py")]
            if len(py_files) == 1:
                entry = os.path.join(root, py_files[0])
            else:
                fmt.error("Archive must contain plugin.py or a single .py file")
                return 1

        return _install_single_file(cfg, entry, plugin_dir, source=source)


def cmd_plugin_remove(cfg, pack, args):
    """Remove an installed plugin."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq plugin remove <name>")
        return 1

    registry = _load_registry(cfg)
    info = registry["plugins"].get(name)

    # Try to find and remove the file
    removed = False

    if info and info.get("file") and os.path.isfile(info["file"]):
        os.unlink(info["file"])
        removed = True
    else:
        # Try default locations
        plugin_file = os.path.join(cfg.conf_dir, PLUGIN_DIR, f"{name}.py")
        if os.path.isfile(plugin_file):
            os.unlink(plugin_file)
            removed = True

    if info:
        del registry["plugins"][name]
        _save_registry(cfg, registry)
        removed = True

    if removed:
        fmt.success(f"Removed: {name}")
        fmt.info("Restart FREQ for changes to take effect")
        return 0
    else:
        fmt.error(f"Plugin not found: {name}")
        return 1


def cmd_plugin_create(cfg, pack, args):
    """Scaffold a new plugin from template."""
    name = getattr(args, "name", None)
    ptype = getattr(args, "type", "command") or "command"
    description = getattr(args, "description", None) or f"A {ptype} plugin"

    if not name:
        fmt.error("Usage: freq plugin create --name my-plugin [--type command]")
        fmt.blank()
        fmt.line("  Available types:")
        for t, desc in PLUGIN_TYPES.items():
            fmt.line(f"    {fmt.C.CYAN}{t:<16}{fmt.C.RESET} {desc}")
        return 1

    if ptype not in PLUGIN_TYPES:
        fmt.error(f"Unknown plugin type: {ptype}")
        fmt.line("  Valid types: " + ", ".join(PLUGIN_TYPES.keys()))
        return 1

    # Choose template
    template = SCAFFOLD_TEMPLATES.get(ptype, DEFAULT_SCAFFOLD)

    # Determine output path
    if ptype == "deployer":
        category = getattr(args, "category", None) or "custom"
        content = template.format(name=name, description=description, category=category)
        dest_dir = os.path.join(DEPLOYER_BASE, category)
        dest = os.path.join(dest_dir, f"{name}.py")
    else:
        content = template.format(name=name, description=description, plugin_type=ptype)
        dest_dir = os.path.join(cfg.conf_dir, PLUGIN_DIR)
        dest = os.path.join(dest_dir, f"{name}.py")

    if os.path.exists(dest):
        fmt.error(f"Plugin already exists: {dest}")
        return 1

    os.makedirs(dest_dir, exist_ok=True)
    with open(dest, "w") as f:
        f.write(content)

    fmt.success(f"Created: {name} [{ptype}]")
    fmt.info(f"  File: {dest}")
    fmt.blank()
    fmt.info("Next steps:")
    fmt.info(f"  1. Edit {dest}")
    fmt.info(f"  2. Test: freq {name}" if ptype == "command" else f"  2. Test with freq init")
    fmt.blank()
    fmt.footer()
    return 0


def cmd_plugin_search(cfg, pack, args):
    """Search for available plugins (community index)."""
    query = getattr(args, "query", None) or ""

    fmt.header("Plugin Search")
    fmt.blank()

    # Community plugin index — will be populated when FREQ Hub launches
    fmt.info("Community plugin index not yet available.")
    fmt.blank()
    fmt.info("To find plugins:")
    fmt.info("  - GitHub: search 'freq-plugin' topics")
    fmt.info("  - Docs:   https://freq.dev/plugins (coming soon)")
    fmt.blank()
    fmt.info("To install a plugin you've found:")
    fmt.info("  freq plugin install <url-to-plugin.py>")
    fmt.blank()
    fmt.footer()
    return 0


def cmd_plugin_update(cfg, pack, args):
    """Update installed plugins from their original source."""
    name = getattr(args, "name", None)
    registry = _load_registry(cfg)

    if name:
        plugins_to_update = {name: registry["plugins"].get(name)}
        if not plugins_to_update[name]:
            fmt.error(f"Plugin not found in registry: {name}")
            return 1
    else:
        plugins_to_update = registry["plugins"]

    if not plugins_to_update:
        fmt.info("No plugins to update.")
        return 0

    fmt.header("Plugin Update")
    fmt.blank()

    updated = 0
    for pname, info in plugins_to_update.items():
        source = info.get("source", "")
        if not source or source == "local" or not source.startswith("http"):
            fmt.line(f"  {fmt.C.DIM}{pname}: local plugin — skipped{fmt.C.RESET}")
            continue

        fmt.info(f"Updating {pname} from {source}...")
        plugin_dir = os.path.join(cfg.conf_dir, PLUGIN_DIR)
        result = _install_from_url(cfg, source, plugin_dir)
        if result == 0:
            updated += 1

    fmt.blank()
    fmt.info(f"Updated {updated} plugin(s)")
    fmt.footer()
    return 0


def cmd_plugin_types(cfg, pack, args):
    """List available plugin types and their interfaces."""
    fmt.header("Plugin Types")
    fmt.blank()

    for ptype, description in PLUGIN_TYPES.items():
        fmt.line(f"  {fmt.C.CYAN}{ptype:<16}{fmt.C.RESET} {description}")

    fmt.blank()
    fmt.info("Create a new plugin: freq plugin create --name <name> --type <type>")
    fmt.blank()
    fmt.footer()
    return 0
