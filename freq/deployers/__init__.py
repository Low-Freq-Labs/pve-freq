"""Pluggable deployer registry.

Deployers live at freq/deployers/{category}/{vendor}.py.
Each module exports deploy() and remove() with standard signatures.
New vendor = new file, no core changes needed.

Usage:
    from freq.deployers import get_deployer, resolve_htype

    category, vendor = resolve_htype("pfsense")  # -> ("firewall", "pfsense")
    deployer = get_deployer(category, vendor)
    if deployer:
        deployer.deploy(ip, ctx, auth_pass, auth_key, auth_user)
"""

import importlib


# Backward-compat mapping: old htype string -> (category, vendor)
HTYPE_COMPAT = {
    "linux": ("server", "linux"),
    "pve": ("server", "linux"),
    "docker": ("server", "linux"),
    "truenas": ("nas", "truenas"),
    "pfsense": ("firewall", "pfsense"),
    "idrac": ("bmc", "idrac"),
    "switch": ("switch", "cisco"),
}

# Categories that require password auth for initial deploy (can't bootstrap with SSH key)
PASSWORD_AUTH_CATEGORIES = {"firewall", "switch", "bmc"}

# Categories that require RSA keys (don't support ed25519)
RSA_REQUIRED_CATEGORIES = {"bmc", "switch"}

# All known categories
CATEGORIES = ("server", "firewall", "switch", "bmc", "nas")


def resolve_htype(htype_str):
    """Convert htype string to (category, vendor) tuple.

    Handles both legacy ('pfsense') and new ('firewall:pfsense') formats.
    Returns ('unknown', htype_str) for unrecognized types.
    """
    if ":" in htype_str:
        parts = htype_str.split(":", 1)
        return parts[0], parts[1]
    return HTYPE_COMPAT.get(htype_str, ("unknown", htype_str))


def get_deployer(category, vendor):
    """Load a deployer module by category:vendor.

    Lookup order:
    1. freq.deployers.{category}.{vendor}  (exact match)
    2. freq.deployers.{category}.generic   (category fallback)

    Returns the module or None if not found.
    """
    for mod_name in (
        f"freq.deployers.{category}.{vendor}",
        f"freq.deployers.{category}.generic",
    ):
        try:
            return importlib.import_module(mod_name)
        except ImportError:
            continue
    return None


def list_deployers():
    """Return list of available (category, vendor) pairs."""
    import pkgutil

    result = []
    for category in CATEGORIES:
        try:
            cat_mod = importlib.import_module(f"freq.deployers.{category}")
            for importer, name, ispkg in pkgutil.iter_modules(cat_mod.__path__):
                if name != "__init__" and name != "generic":
                    result.append((category, name))
        except ImportError:
            continue
    return result
