"""Web UI asset loader for FREQ.

Domain: (internal — used by freq serve, not a user command)

Loads HTML, CSS, and JS assets from freq/data/web/ at runtime via
importlib.resources. Public loader functions always return fresh content and
apply one cache identity covering the complete shipped frontend bundle.

Replaces: Inline HTML string constants (unmaintainable at scale)

Architecture:
    - Assets stored as separate files in freq/data/web/ package
    - importlib.resources.files() for reliable path resolution
    - One explicit manifest covers both templates and every linked asset
    - Public fresh-read functions; no module attribute compatibility aliases

Design decisions:
    - Lazy loading, not eager. Importing web_ui should not trigger file I/O.
      Only the serve module actually needs the HTML; other importers skip it.
"""

import hashlib
import importlib.resources

FRONTEND_ASSET_MANIFEST = (
    "app.html",
    "setup.html",
    "css/app.css",
    "css/cockpit.css",
    "css/cockpit-workspaces.css",
    "css/registered-lab-panel.css",
    "css/lab-window-panel.css",
    "css/setup.css",
    "vendor/xterm/xterm.min.css",
    "vendor/xterm/xterm.min.js",
    "vendor/xterm/addon-fit.min.js",
    "vendor/xterm/addon-clipboard.min.js",
    "js/router.js",
    "js/presentation.js",
    "js/quick-ct.js",
    "js/pve-inventory.js",
    "js/pve-source-config.js",
    "js/cockpit-workspaces.js",
    "js/registered-lab-panel.js",
    "js/registered-lab-controller.js",
    "js/lab-window-panel.js",
    "js/lab-window-controller.js",
    "js/playbooks-admission.js",
    "js/app.js",
    "js/cluster-report/display.mjs",
    "js/cluster-report/decoder.mjs",
    "js/setup.js",
)


def read_asset(filename: str) -> str:
    """Read a web asset file from freq.data.web package."""
    ref = importlib.resources.files("freq.data.web").joinpath(filename)
    return ref.read_text(encoding="utf-8")


def _read_frontend_snapshot() -> dict[str, str]:
    """Read one coherent snapshot of every shipped frontend asset."""
    return {asset: read_asset(asset) for asset in FRONTEND_ASSET_MANIFEST}


def _frontend_asset_token(snapshot: dict[str, str]) -> str:
    from freq import __version__

    digest = hashlib.sha256()
    for asset in FRONTEND_ASSET_MANIFEST:
        digest.update(asset.encode("utf-8"))
        digest.update(b"\0")
        digest.update(snapshot[asset].encode("utf-8"))
        digest.update(b"\0")
    return f"{__version__}-{digest.hexdigest()[:12]}"


def frontend_asset_token() -> str:
    """Return a fresh cache identity for the complete shipped web bundle."""
    return _frontend_asset_token(_read_frontend_snapshot())


def _load_versioned_html(filename: str) -> str:
    snapshot = _read_frontend_snapshot()
    return snapshot[filename].replace("{{VERSION}}", _frontend_asset_token(snapshot))


def load_setup_html() -> str:
    """Load the fresh setup wizard with the current frontend cache identity."""
    return _load_versioned_html("setup.html")


def load_app_html() -> str:
    """Load main dashboard — HTML with linked CSS and JS.

    Substitutes {{VERSION}} placeholders in asset cache-bust tokens with
    the product version plus a short hash of the actual frontend assets.
    The product version keeps view-source honest; the asset hash prevents
    dev/deploy UI ghosts when app.css/app.js change without a package
    version bump.
    """
    return _load_versioned_html("app.html")
