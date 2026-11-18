"""Dependency-clean PVE API-first transport with SSH fallback."""

import hashlib
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

PVE_CMD_TIMEOUT = 30
PVE_QUICK_TIMEOUT = 10
PVE_API_PORT = 8006
PVE_API_TIMEOUT = 15


@dataclass(frozen=True)
class PveMetricsRuntime:
    """Live dependencies required to resolve dashboard PVE metrics."""

    load_config: Callable[[], Any]
    pve_api_call: Callable[..., tuple]
    now: Callable[[], float]


@dataclass(frozen=True)
class PveMetricsResolution:
    """Transport-free result of one cached PVE metrics lookup."""

    payload: dict
    cache_hit: bool
    cache_timestamp: float | None


def resolve_pve_metrics(
    cached_payload,
    cached_at,
    last_seen_by_ip,
    *,
    runtime: PveMetricsRuntime,
):
    """Resolve one PVE metrics snapshot without performing HTTP transport."""
    now = runtime.now()
    if cached_payload and (now - cached_at) < 4:
        return PveMetricsResolution(
            payload=cached_payload,
            cache_hit=True,
            cache_timestamp=None,
        )

    cfg = runtime.load_config()
    nodes = []
    for i, ip in enumerate(cfg.pve_nodes):
        name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"pve{i + 1:02d}"
        data, ok = runtime.pve_api_call(
            cfg,
            ip,
            f"/nodes/{name}/status",
            timeout=5,
        )
        if ok and isinstance(data, dict):
            cpu_pct = round((data.get("cpu", 0)) * 100, 1)
            mem = data.get("memory", {})
            mem_used = mem.get("used", 0)
            mem_total = mem.get("total", 1)
            mem_pct = round(mem_used / mem_total * 100, 1) if mem_total else 0
            root = data.get("rootfs", {})
            disk_used = root.get("used", 0)
            disk_total = root.get("total", 1)
            disk_pct = round(disk_used / disk_total * 100, 1) if disk_total else 0
            cpuinfo = data.get("cpuinfo", {})
            load = data.get("loadavg", ["0", "0", "0"])
            storage_pools = []
            st_data, st_ok = runtime.pve_api_call(
                cfg,
                ip,
                f"/nodes/{name}/storage",
                timeout=3,
            )
            if st_ok and isinstance(st_data, list):
                for pool in st_data:
                    if not pool.get("active"):
                        continue
                    p_total = pool.get("total", 0)
                    p_used = pool.get("used", 0)
                    p_pct = round(p_used / p_total * 100, 1) if p_total else 0
                    storage_pools.append(
                        {
                            "name": pool.get("storage", ""),
                            "type": pool.get("type", ""),
                            "used_gb": round(p_used / 1024**3, 1),
                            "total_gb": round(p_total / 1024**3, 1),
                            "pct": p_pct,
                        }
                    )

            iowait = round(data.get("wait", 0) * 100, 1)
            now_wall = runtime.now()
            last_seen_by_ip[ip] = now_wall
            nodes.append(
                {
                    "name": name,
                    "ip": ip,
                    "online": True,
                    "state": "live",
                    "reason": "PVE API responded",
                    "last_seen_ts": now_wall,
                    "age_seconds": 0,
                    "cpu_pct": cpu_pct,
                    "cores": cpuinfo.get("cpus", 0),
                    "model": cpuinfo.get("model", ""),
                    "ram_used_gb": round(mem_used / 1024**3, 1),
                    "ram_total_gb": round(mem_total / 1024**3, 1),
                    "ram_pct": mem_pct,
                    "iowait": iowait,
                    "disk_pct": disk_pct,
                    "disk_used_gb": round(disk_used / 1024**3, 1),
                    "disk_total_gb": round(disk_total / 1024**3, 1),
                    "uptime": data.get("uptime", 0),
                    "load": load,
                    "storage": storage_pools,
                }
            )
        else:
            last_seen = last_seen_by_ip.get(ip)
            age = round(runtime.now() - last_seen, 1) if last_seen else None
            nodes.append(
                {
                    "name": name,
                    "ip": ip,
                    "online": False,
                    "state": "unreachable" if last_seen is None else "stale",
                    "reason": (
                        "PVE API did not respond — node never seen alive"
                        if last_seen is None
                        else f"PVE API did not respond; last seen {age}s ago"
                    ),
                    "last_seen_ts": last_seen,
                    "age_seconds": age,
                }
            )

    result = {"nodes": nodes, "ts": runtime.now()}
    return PveMetricsResolution(
        payload=result,
        cache_hit=False,
        cache_timestamp=runtime.now(),
    )


@dataclass(frozen=True)
class PveRrdRuntime:
    """Live dependencies required to resolve dashboard PVE RRD data."""

    load_config: Callable[[], Any]
    pve_api_call: Callable[..., tuple]
    now: Callable[[], float]


@dataclass(frozen=True)
class PveRrdResolution:
    """Transport-free result of one cached PVE RRD lookup."""

    payload: dict
    cache_hit: bool
    cache_timestamp: float | None


def resolve_pve_rrd(
    cached_payload,
    cached_at,
    *,
    runtime: PveRrdRuntime,
):
    """Resolve one hourly PVE RRD snapshot without HTTP transport."""
    now = runtime.now()
    if cached_payload and (now - cached_at) < 60:
        return PveRrdResolution(
            payload=cached_payload,
            cache_hit=True,
            cache_timestamp=None,
        )

    cfg = runtime.load_config()
    nodes = []
    for i, ip in enumerate(cfg.pve_nodes):
        name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"pve{i + 1:02d}"
        data, ok = runtime.pve_api_call(
            cfg,
            ip,
            f"/nodes/{name}/rrddata?timeframe=hour",
            timeout=5,
        )
        if ok and isinstance(data, list):
            cpu = []
            ram = []
            iowait = []
            for point in data:
                if not isinstance(point, dict):
                    continue
                timestamp = point.get("time", 0)
                cpu_value = point.get("cpu")
                memory_used = point.get("memused")
                memory_total = point.get("memtotal")
                io_value = point.get("iowait")
                if cpu_value is not None:
                    cpu.append({"t": timestamp, "v": round(cpu_value * 100, 1)})
                if memory_used is not None and memory_total and memory_total > 0:
                    ram.append(
                        {
                            "t": timestamp,
                            "v": round(memory_used / memory_total * 100, 1),
                        }
                    )
                if io_value is not None:
                    iowait.append({"t": timestamp, "v": round(io_value * 100, 1)})
            nodes.append(
                {
                    "name": name,
                    "cpu": cpu[-70:],
                    "ram": ram[-70:],
                    "iowait": iowait[-70:],
                }
            )
        else:
            nodes.append({"name": name, "cpu": [], "ram": [], "iowait": []})

    result = {"nodes": nodes, "ts": runtime.now()}
    return PveRrdResolution(
        payload=result,
        cache_hit=False,
        cache_timestamp=runtime.now(),
    )


def _pve_node_token_suffix(node_ip: str) -> str:
    """Return the stable, non-secret suffix for one node-scoped token."""
    return hashlib.sha256(str(node_ip).encode("utf-8")).hexdigest()[:12]


def _pve_node_token_name(node_ip: str) -> str:
    """Return the deterministic PVE token name used for one independent node."""
    return f"freq-rw-{_pve_node_token_suffix(node_ip)}"


def _pve_node_token_path(cfg: FreqConfig, node_ip: str) -> str:
    """Return the credential path for a node-scoped PVE API token."""
    cred_dir = getattr(cfg, "credentials_dir", "") or "/etc/freq/credentials"
    return os.path.join(
        cred_dir,
        f"pve-token-rw-{_pve_node_token_suffix(node_ip)}",
    )


def _runtime_pve_api_token_secret(cfg: FreqConfig) -> str:
    """Return configured PVE API token secret, with runtime credential fallback."""
    secret = getattr(cfg, "pve_api_token_secret", "") or ""
    if secret:
        return secret
    cred_dir = getattr(cfg, "credentials_dir", "") or "/etc/freq/credentials"
    path = f"{cred_dir.rstrip('/')}/pve-token-rw"
    try:
        with open(path) as file_handle:
            return file_handle.read().strip()
    except OSError:
        return ""


def _pve_api_credentials(cfg: FreqConfig, node_ip: str) -> tuple[str, str]:
    """Resolve the token pair for a node, falling back to the legacy shared pair.

    A Proxmox cluster replicates token state, but separately configured PVE
    nodes do not.  Init therefore writes a deterministic node-scoped secret
    only when the shared token is rejected by that node.  The public config
    keeps the principal and shared-token fallback; the node credential never
    leaves the credential directory.
    """
    shared_id = getattr(cfg, "pve_api_token_id", "") or ""
    shared_secret = _runtime_pve_api_token_secret(cfg)
    principal = shared_id.split("!", 1)[0]
    node_path = _pve_node_token_path(cfg, node_ip)
    if principal:
        try:
            with open(node_path) as file_handle:
                node_secret = file_handle.read().strip()
        except OSError:
            node_secret = ""
        if node_secret:
            return f"{principal}!{_pve_node_token_name(node_ip)}", node_secret
    return shared_id, shared_secret


def _has_pve_api_token(cfg: FreqConfig) -> bool:
    """Return true when PVE API token auth is usable from config or credential file."""
    return bool((getattr(cfg, "pve_api_token_id", "") or "") and _runtime_pve_api_token_secret(cfg))


def _pve_api_call(
    cfg: FreqConfig,
    node_ip: str,
    endpoint: str,
    method: str = "GET",
    data: dict = None,
    timeout: int = PVE_API_TIMEOUT,
) -> tuple:
    """Call the PVE REST API with token authentication."""
    token_id, token_secret = _pve_api_credentials(cfg, node_ip)
    if not token_id or not token_secret:
        return "", False

    url = f"https://{node_ip}:{PVE_API_PORT}/api2/json{endpoint}"
    auth = f"PVEAPIToken={token_id}={token_secret}"
    headers = {"Authorization": auth, "Accept": "application/json"}

    request_data = None
    if data:
        request_data = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    request = urllib.request.Request(url, data=request_data, headers=headers, method=method)

    context = ssl.create_default_context()
    if not getattr(cfg, "pve_api_verify_ssl", False):
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            body = json.loads(response.read().decode())
            return body.get("data", body), True
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError, TimeoutError) as error:
        logger.debug(f"PVE API call failed ({node_ip}{endpoint}): {error}")
        return str(error), False


def _pve_call(
    cfg: FreqConfig,
    node_ip: str,
    api_endpoint: str,
    ssh_command: str,
    timeout: int = PVE_CMD_TIMEOUT,
    method: str = "GET",
    data: dict = None,
    *,
    has_token=None,
    api_call=None,
    pve_cmd=None,
) -> tuple:
    """Try the PVE REST API first, then fall back to SSH."""
    has_token = _has_pve_api_token if has_token is None else has_token
    api_call = _pve_api_call if api_call is None else api_call
    pve_cmd = _pve_cmd if pve_cmd is None else pve_cmd
    if has_token(cfg):
        result, ok = api_call(
            cfg,
            node_ip,
            api_endpoint,
            method=method,
            data=data,
            timeout=min(timeout, PVE_API_TIMEOUT),
        )
        if ok:
            return result, True
    return pve_cmd(cfg, node_ip, ssh_command, timeout=timeout)


def _pve_cmd(
    cfg: FreqConfig,
    node_ip: str,
    command: str,
    timeout: int = PVE_CMD_TIMEOUT,
    *,
    ssh_runner=None,
) -> tuple:
    """Execute a command on a PVE node through SSH and sudo."""
    ssh_runner = ssh_run if ssh_runner is None else ssh_runner
    result = ssh_runner(
        host=node_ip,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pve",
        use_sudo=True,
        cfg=cfg,
    )
    output = result.stdout
    if result.returncode != 0 and result.stderr and not result.stdout.strip():
        output = result.stderr
    return output, result.returncode == 0
