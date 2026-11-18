"""Runtime device credential resolver.

Device credentials are deployment/runtime inputs, not general config values.
This module reads the staged device-credentials TOML without logging or
returning secret material unless the caller explicitly needs a file path.
"""

import os
import re
import tomllib

from freq.core.config import validated_runtime_service_account

DEVICE_CREDENTIAL_CANDIDATES = (
    "/etc/freq/credentials/device-credentials.toml",
)


_BARE_COLON_SECTION = re.compile(
    r"^(?P<indent>\s*)\[(?P<section>[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+)\](?P<suffix>\s*(?:#.*)?)$",
    re.MULTILINE,
)


def device_credentials_section_header(section: str) -> str:
    """Return a valid TOML table header for a credential section name."""
    name = str(section or "").strip()
    if ":" not in name:
        return f"[{name}]"
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    return f'["{escaped}"]'


def _normalize_legacy_colon_sections(text: str) -> str:
    """Make previously generated bare colon table names valid TOML."""

    def _quoted(match: re.Match) -> str:
        return (
            f"{match.group('indent')}"
            f"{device_credentials_section_header(match.group('section'))}"
            f"{match.group('suffix')}"
        )

    return _BARE_COLON_SECTION.sub(_quoted, text)


def load_device_credentials_toml(path: str) -> dict:
    """Load a credential document while preserving real TOML value types.

    Older freq releases emitted bare ``[category:vendor]`` table headers.
    Normalize only that historical header spelling before stdlib TOML parsing;
    valid quoted headers and all scalar/list values otherwise pass through.
    """
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        return tomllib.loads(_normalize_legacy_colon_sections(text))
    except (OSError, tomllib.TOMLDecodeError):
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
    user = validated_runtime_service_account(cfg)
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
    data = load_device_credentials_toml(device_credentials_path(cfg))
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
    user = entry.get("user") or entry.get("username") or validated_runtime_service_account(cfg)
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
    data = load_device_credentials_toml(device_credentials_path(cfg))
    entry = _entry_for(data, htype)
    if htype in {"pfsense", "idrac", "switch", "truenas"}:
        auth = _service_account_ssh_auth(cfg, htype, data, source="service-account")
        auth.pop("sudo_password_file", None)
        return auth
    user = entry.get("user") or entry.get("username") or validated_runtime_service_account(cfg)
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


def _read_secret(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def resolve_device_api_auth(cfg, htype: str, include_secret: bool = False) -> dict:
    """Resolve path-backed credentials for non-SSH device APIs.

    This is for REST/SNMP style probes that need a username plus one or more
    secret file paths. The default return shape never includes secret values.
    Callers that need to execute the probe may opt in with include_secret=True;
    they must not log or expose the returned secret fields.
    """
    htype = (htype or "").lower()
    data = load_device_credentials_toml(device_credentials_path(cfg))
    entry = _entry_for(data, htype)
    if htype == "snmp":
        entry = data.get("snmp") if isinstance(data.get("snmp"), dict) else entry
    user = (
        entry.get("user")
        or entry.get("username")
        or entry.get("v3_username")
        or entry.get("snmpv3_user")
        or ""
    )
    password_file = entry.get("password_file") or ""
    auth_password_file = (
        entry.get("auth_password_file")
        or entry.get("auth_passphrase_file")
        or entry.get("auth_file")
        or password_file
    )
    priv_password_file = (
        entry.get("priv_password_file")
        or entry.get("privacy_password_file")
        or entry.get("priv_passphrase_file")
        or entry.get("privacy_file")
        or password_file
    )
    auth = {
        "user": user,
        "password_file": password_file,
        "auth_password_file": auth_password_file,
        "priv_password_file": priv_password_file,
        "auth_protocol": (entry.get("auth_protocol") or entry.get("auth_type") or "SHA").upper(),
        "priv_protocol": (entry.get("priv_protocol") or entry.get("privacy_protocol") or "AES").upper(),
        "version": str(entry.get("version") or entry.get("snmp_version") or ("3" if htype == "snmp" and user else "")).lower(),
        "security_level": entry.get("security_level") or "authPriv",
        "source": "device-credentials" if entry else "config",
    }
    if include_secret:
        auth["password"] = _read_secret(password_file)
        auth["auth_password"] = _read_secret(auth_password_file)
        auth["priv_password"] = _read_secret(priv_password_file)
    return auth
