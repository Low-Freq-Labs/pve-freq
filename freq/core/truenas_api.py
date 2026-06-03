"""TrueNAS API-key helpers.

TrueNAS is not treated like a generic Linux host here. In DC01 ground
truth, the FREQ service account is intentionally not present on TrueNAS,
and TrueNAS sshd may restrict allowed users. Read-only dashboard data
therefore uses the TrueNAS API key path when configured, while SSH remains
an explicit diagnostic/fallback path elsewhere.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any

from freq.core.config import load_toml
from freq.modules.vault import vault_get


def settings(cfg, target) -> dict[str, str]:
    """Resolve TrueNAS API settings from freq.toml and the vault.

    Supported config:

        [truenas]
        type = "api_key"
        url = "https://10.25.255.25/api/v2.0"
        api_key_file = "/opt/pve-freq/data/secrets/truenas-prod.key"
        api_key_ref = "secrets://truenas-prod"

    ``api_key_file`` is preferred when present because it lets operators
    stage one-shot TrueNAS API secrets by path without putting them in
    config or chat logs. Otherwise the secret is read as
    ``vault_get(cfg, "truenas-prod", "api_key")``.
    If no section exists, the core TrueNAS defaults to namespace
    ``truenas`` and URL ``https://<target.ip>/api/v2.0``.
    """
    data = load_toml(os.path.join(cfg.conf_dir, "freq.toml"))
    label_key = f"{getattr(target, 'label', '')} {getattr(target, 'key', '')}".lower()
    section_name = "truenas-lab" if "lab" in label_key else "truenas"
    section = data.get(section_name, {})
    if not isinstance(section, dict):
        section = {}

    api_type = section.get("type", section.get("auth_type", "")) or "api_key"
    url = str(section.get("url") or f"https://{target.ip}/api/v2.0").rstrip("/")
    ref = section.get("api_key_ref", "")
    if isinstance(ref, str) and ref.startswith("secrets://"):
        secret_ns = ref.split("secrets://", 1)[1].strip()
    elif isinstance(ref, str) and ref:
        secret_ns = ref.strip()
    else:
        secret_ns = section.get("vault_namespace", "") or section_name

    key_file = str(section.get("api_key_file") or section.get("api_key_path") or "").strip()
    api_key = ""
    if key_file:
        try:
            with open(os.path.expanduser(key_file), encoding="utf-8") as f:
                api_key = f.read().strip()
        except OSError:
            api_key = ""
    if not api_key:
        api_key = vault_get(cfg, secret_ns, "api_key") if secret_ns else ""
    if not api_key:
        api_key = vault_get(cfg, section_name, "api_key")

    return {
        "section": section_name,
        "type": str(api_type),
        "url": url,
        "api_key": api_key,
        "secret_ns": secret_ns,
        "api_key_file": key_file,
    }


def action_endpoint(action: str) -> tuple[str, str] | None:
    endpoints = {
        "status": ("GET", "/system/info"),
        "pools": ("GET", "/pool"),
        "health": ("GET", "/pool"),
        "datasets": ("GET", "/pool/dataset"),
        "shares": ("GET", "/sharing/smb"),
        "alerts": ("GET", "/alert/list"),
        "smart": ("GET", "/disk"),
        "snapshots": ("GET", "/zfs/snapshot"),
        "replication": ("GET", "/replication"),
        "services": ("GET", "/service"),
        "network": ("GET", "/interface"),
    }
    return endpoints.get(action)


def request(api_settings: dict[str, str], action: str, timeout: int = 15) -> tuple[Any, dict[str, str] | None]:
    api_action = action_endpoint(action)
    if not api_action:
        return None, {"error": f"TrueNAS API action unsupported: {action}"}
    if not api_settings.get("api_key"):
        ns = api_settings.get("secret_ns") or api_settings.get("section") or "truenas"
        return None, {"error": f"TrueNAS API key missing. Set vault key {ns}:api_key"}

    method, endpoint = api_action
    req = urllib.request.Request(
        api_settings["url"] + endpoint,
        method=method,
        headers={
            "Authorization": "Bearer " + api_settings["api_key"],
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as res:
            raw = res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:1000]
        return None, {"error": f"TrueNAS API HTTP {e.code}: {body}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, {"error": f"TrueNAS API unavailable: {e}"}

    try:
        return json.loads(raw or "null"), None
    except json.JSONDecodeError:
        return raw, None


def format_output(action: str, data: Any) -> str:
    if action == "status" and isinstance(data, dict):
        keys = ("hostname", "version", "uptime", "system_product", "physmem")
        return "\n".join(f"{k}: {data.get(k)}" for k in keys if k in data)
    if action in ("pools", "health") and isinstance(data, list):
        lines = []
        for pool in data:
            name = pool.get("name") or pool.get("id") or "pool"
            healthy = pool.get("healthy")
            status = pool.get("status") or ("ONLINE" if healthy is True else "UNKNOWN")
            size = pool.get("size") or pool.get("size_str") or ""
            used = pool.get("allocated") or pool.get("allocated_str") or ""
            lines.append(f"{name}\t{status}\tsize={size}\tused={used}")
        return "\n".join(lines) or "No pools returned"
    return json.dumps(data, indent=2, sort_keys=True)[:12000]


def pool_metrics(pools: Any) -> dict[str, Any]:
    """Convert TrueNAS pool API output into dashboard card metrics."""
    metrics: dict[str, Any] = {}
    if not isinstance(pools, list):
        return metrics

    simplified = []
    total_size = 0
    total_used = 0
    healths = []
    for pool in pools:
        if not isinstance(pool, dict):
            continue
        name = pool.get("name") or pool.get("id") or "pool"
        healthy = pool.get("healthy")
        status = pool.get("status") or ("ONLINE" if healthy is True else "UNKNOWN")
        size = int(pool.get("size") or 0)
        used = int(pool.get("allocated") or 0)
        total_size += size
        total_used += used
        healths.append(status)
        simplified.append(
            {
                "name": name,
                "size": _fmt_bytes(size),
                "alloc": _fmt_bytes(used),
                "free": _fmt_bytes(max(size - used, 0)),
                "health": status,
            }
        )
    if simplified:
        metrics["pools"] = simplified
        metrics["pool_health"] = (
            "FAULTED" if "FAULTED" in healths else "DEGRADED" if "DEGRADED" in healths else "ONLINE"
        )
    if total_size > 0:
        metrics["capacity_pct"] = f"{round(total_used / total_size * 100)}%"
        metrics["total_size"] = _fmt_bytes(total_size)
    return metrics


def _fmt_bytes(value: int) -> str:
    if value <= 0:
        return "0B"
    units = ["B", "K", "M", "G", "T", "P"]
    n = float(value)
    unit = units[0]
    for unit in units:
        if n < 1024 or unit == units[-1]:
            break
        n /= 1024
    return f"{n:.1f}{unit}" if unit not in ("B", "K") else f"{int(n)}{unit}"
