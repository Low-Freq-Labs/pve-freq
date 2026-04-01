"""Web UI asset loader for FREQ.

Domain: (internal — used by freq serve, not a user command)

Loads HTML, CSS, and JS assets from freq/data/web/ at runtime via
importlib.resources. Exposes SETUP_HTML and APP_HTML as lazy-loaded
module-level constants for backward compatibility with serve.py.

Replaces: Inline HTML string constants (unmaintainable at scale)

Architecture:
    - Assets stored as separate files in freq/data/web/ package
    - importlib.resources.files() for reliable path resolution
    - Lazy descriptor (_LazyHTML) defers file I/O until first access
    - Module-level SETUP_HTML/APP_HTML for backward compat imports

Design decisions:
    - Lazy loading, not eager. Importing web_ui should not trigger file I/O.
      Only the serve module actually needs the HTML; other importers skip it.
"""

import importlib.resources


def _read_asset(filename: str) -> str:
    """Read a web asset file from freq.data.web package."""
    ref = importlib.resources.files("freq.data.web").joinpath(filename)
    return ref.read_text(encoding="utf-8")


def _load_setup_html() -> str:
    """Load setup wizard — HTML with linked CSS and JS."""
    return _read_asset("setup.html")


def _load_app_html() -> str:
    """Load main dashboard — HTML with linked CSS and JS."""
    return _read_asset("app.html")


# Lazy-loaded module-level constants for backward compatibility.
# Tests and serve.py can still do: from freq.modules.web_ui import APP_HTML
class _LazyHTML:
    """Descriptor that loads HTML on first access, not at import time."""

    def __init__(self, loader):
        self._loader = loader
        self._cache = None

    def __get__(self, obj, objtype=None):
        if self._cache is None:
            self._cache = self._loader()
        return self._cache


class _Module:
    SETUP_HTML = _LazyHTML(_load_setup_html)
    APP_HTML = _LazyHTML(_load_app_html)


_mod = _Module()


def __getattr__(name: str):
    """Module-level __getattr__ for lazy loading SETUP_HTML and APP_HTML."""
    if name == "SETUP_HTML":
        return _mod.SETUP_HTML
    if name == "APP_HTML":
        return _mod.APP_HTML
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
