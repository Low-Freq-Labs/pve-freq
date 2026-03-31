"""FREQ Web UI — Diamond Standard.

Web assets live in freq/data/web/ as separate HTML, CSS, and JS files.
This module loads them at runtime via importlib.resources and exposes
SETUP_HTML and APP_HTML as assembled strings for backward compatibility.

"the bass is the foundation. so is this tool. so is this friendship."
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
