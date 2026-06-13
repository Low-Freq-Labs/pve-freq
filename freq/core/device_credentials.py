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


def _infer_local_user_for_key(key_path: str) -> str:
    if not key_path:
        return ""
    parts = os.path.normpath(key_path).split(os.sep)
    if len(parts) >= 4 and parts[1] == "home" and parts[3] == ".ssh":
        return parts[2]
    return ""


def _service_account_entry(data: dict) -> dict:
    entry = data.get("service_account")
    return entry if isinstance(entry, dict) else {}


def _service_account_ssh_auth(cfg, htype: str, data: dict | None = None, source: str = "service-account") -> dict:
    """Return post-init runtime auth for the configured service account.

    Per-device credential sections can carry bootstrap material used by init,
    but runtime probes/actions/terminals must not keep using that bootstrap
    username after the managed service account exists.
    """
    data = data or {}
    svc_entry = _service_account_entry(data)
    user = getattr(cfg, "ssh_service_account", "") or svc_entry.get("user") or svc_entry.get("username") or "freq-admin"
    key_path = getattr(cfg, "ssh_key_path", "") or svc_entry.get("ssh_key_file") or svc_entry.get("key_file") or svc_entry.get("key_path") or ""
    if (htype or "").lower() in {"idrac", "switch"}:
        key_path = getattr(cfg, "ssh_rsa_key_path", "") or key_path
    if key_path and not os.path.isfile(key_path):
        key_path = ""
    password_file = ""
    if (htype or "").lower() in {"idrac", "switch"}:
        password_file = getattr(cfg, "legacy_password_file", "") or ""
    if key_path and (htype or "").lower() == "truenas":
        password_file = ""
    if not password_file and not key_path:
        password_file = svc_entry.get("password_file") or ""
    if password_file and not os.path.isfile(password_file):
        password_file = ""
    return {
        "user": user,
        "key_path": key_path,
        "password_file": password_file,
        "sudo_password_file": False,
        "local_user": "",
        "source": source,
    }


def resolve_staged_device_ssh_auth(cfg, htype: str) -> dict:
    """Resolve staged runtime SSH auth for physical devices.

    Unlike resolve_device_ssh_auth(), this preserves root-owned password
    file paths and marks them for sudo-backed sshpass. That lets a
    systemd service account use secrets staged under /etc/freq/credentials
    without broadening file permissions.
    """
    htype = (htype or "").lower()
    data = _load(device_credentials_path(cfg))
    entry = _entry_for(data, htype)
    if htype in {"pfsense", "idrac", "switch"}:
        return _service_account_ssh_auth(cfg, htype, data, source="service-account")
    if (
        htype == "truenas"
        and (
            _service_account_entry(data)
            or os.path.isfile(getattr(cfg, "ssh_key_path", "") or "")
            or (entry.get("user") or entry.get("username") or "") not in {"", getattr(cfg, "ssh_service_account", "")}
        )
    ):
        return _service_account_ssh_auth(cfg, htype, data, source="service-account")
    if htype == "truenas":
        svc_entry = data.get("service_account")
        if isinstance(svc_entry, dict) and (
            svc_entry.get("password_file")
            or svc_entry.get("ssh_key_file")
            or svc_entry.get("key_file")
            or svc_entry.get("key_path")
        ):
            svc_key = getattr(cfg, "ssh_key_path", "") or svc_entry.get("ssh_key_file") or svc_entry.get("key_file") or svc_entry.get("key_path") or ""
            entry = dict(svc_entry)
            if svc_key and os.path.isfile(svc_key):
                entry["ssh_key_file"] = svc_key
                entry.pop("password_file", None)
    user = entry.get("user") or entry.get("username") or getattr(cfg, "ssh_service_account", "") or "freq-admin"
    key_path = entry.get("ssh_key_file") or entry.get("key_file") or entry.get("key_path") or ""
    password_file = entry.get("password_file") or ""
    local_user = entry.get("local_user") or entry.get("run_as_user") or entry.get("run_as") or ""

    if key_path and not local_user:
        local_user = _infer_local_user_for_key(key_path)
    if key_path and not os.path.isfile(key_path):
        # A dashboard/service process may not be able to traverse another
        # user's 700 home directory. Keep declared home-key paths when we
        # know the local user so freq.core.ssh can run the probe via
        # `sudo -u <local_user>` instead of falling back to the service
        # account and reporting a false auth failure.
        if not local_user:
            key_path = ""

    if password_file and os.path.isfile(password_file):
        return {
            "user": user,
            "key_path": "",
            "password_file": password_file,
            "sudo_password_file": not os.access(password_file, os.R_OK),
            "local_user": "",
            "source": "device-credentials",
        }

    if key_path:
        return {
            "user": user,
            "key_path": key_path,
            "password_file": "",
            "sudo_password_file": False,
            "local_user": local_user,
            "source": "device-credentials",
        }

    key_path = getattr(cfg, "ssh_key_path", "")
    if htype in {"idrac", "switch"}:
        key_path = getattr(cfg, "ssh_rsa_key_path", "") or key_path
    password_file = ""
    if htype == "switch":
        password_file = getattr(cfg, "legacy_password_file", "") or ""
    return {
        "user": user,
        "key_path": key_path,
        "password_file": password_file,
        "sudo_password_file": False,
        "local_user": "",
        "source": "config",
    }


def resolve_device_ssh_auth(cfg, htype: str) -> dict:
    """Resolve runtime SSH user/key/password-file for a device type.

    Falls back to the managed service-account config when no staged
    device credentials exist, so generic installs keep working.
    """
    htype = (htype or "").lower()
    data = _load(device_credentials_path(cfg))
    entry = _entry_for(data, htype)
    if htype in {"pfsense", "idrac", "switch", "truenas"}:
        auth = _service_account_ssh_auth(cfg, htype, data, source="service-account")
        auth.pop("sudo_password_file", None)
        return auth
    user = entry.get("user") or entry.get("username") or getattr(cfg, "ssh_service_account", "")
    key_path = entry.get("ssh_key_file") or entry.get("key_file") or entry.get("key_path") or ""
    password_file = entry.get("password_file") or ""
    local_user = entry.get("local_user") or entry.get("run_as_user") or entry.get("run_as") or ""
    if key_path and not local_user:
        local_user = _infer_local_user_for_key(key_path)
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
