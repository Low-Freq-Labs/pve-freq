"""Runtime device credential resolver.

Device credentials are deployment/runtime inputs, not general config values.
This module reads the staged device-credentials TOML without logging or
returning secret material unless the caller explicitly needs a file path.
"""

import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ in product
    tomllib = None


DEVICE_CREDENTIAL_CANDIDATES = (
    "/etc/freq/credentials/device-credentials.toml",
)


def _manual_toml(path: str) -> dict:
    data = {}
    section = None
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip().strip('"').strip("'").lower()
                data.setdefault(section, {})
                continue
            if section and "=" in line:
                key, value = line.split("=", 1)
                data[section][key.strip()] = value.strip().strip('"').strip("'")
    return data


def _load(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    if tomllib is not None:
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except Exception:
            pass
    try:
        return _manual_toml(path)
    except OSError:
        return {}


def device_credentials_path(cfg=None) -> str:
    """Return the first readable staged device-credentials file."""
    candidates = list(DEVICE_CREDENTIAL_CANDIDATES)
    if cfg is not None:
        conf_dir = getattr(cfg, "conf_dir", "") or ""
        install_dir = getattr(cfg, "install_dir", "") or ""
        if conf_dir:
            candidates.append(os.path.join(os.path.dirname(conf_dir), "credentials", "device-credentials.toml"))
            candidates.append(os.path.join(conf_dir, "device-credentials.toml"))
        if install_dir:
            candidates.append(os.path.join(install_dir, "credentials", "device-credentials.toml"))
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.R_OK):
            return path
    return ""


def _entry_for(data: dict, htype: str) -> dict:
    htype = (htype or "").lower()
    aliases = {
        "pfsense": ("firewall:pfsense", "firewall", "pfsense"),
        "opnsense": ("firewall:opnsense", "firewall", "opnsense"),
        "truenas": ("nas:truenas", "storage:truenas", "nas", "storage", "truenas"),
        "switch": ("switch:cisco", "switch"),
        "idrac": ("bmc:idrac", "bmc", "idrac"),
    }
    for key in aliases.get(htype, (htype,)):
        entry = data.get(key)
        if isinstance(entry, dict):
            return entry
    return {}


def resolve_device_ssh_auth(cfg, htype: str) -> dict:
    """Resolve runtime SSH user/key/password-file for a device type.

    Falls back to the managed service-account config when no staged
    device credentials exist, so generic installs keep working.
    """
    entry = _entry_for(_load(device_credentials_path(cfg)), htype)
    user = entry.get("user") or entry.get("username") or getattr(cfg, "ssh_service_account", "")
    key_path = entry.get("ssh_key_file") or entry.get("key_file") or entry.get("key_path") or ""
    password_file = entry.get("password_file") or ""
    local_user = entry.get("local_user") or entry.get("run_as_user") or entry.get("run_as") or ""
    if key_path and not local_user:
        parts = os.path.normpath(key_path).split(os.sep)
        if len(parts) >= 4 and parts[1] == "home" and parts[3] == ".ssh":
            local_user = parts[2]
    if key_path and not local_user and (not os.path.isfile(key_path) or not os.access(key_path, os.R_OK)):
        key_path = ""
    if password_file and (not os.path.isfile(password_file) or not os.access(password_file, os.R_OK)):
        password_file = ""
    return {
        "user": user,
        "key_path": key_path or getattr(cfg, "ssh_key_path", ""),
        "password_file": password_file,
        "local_user": local_user,
        "source": "device-credentials" if entry else "config",
    }
