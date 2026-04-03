"""Benchmark and Wake-on-LAN API handlers — /api/bench/*, /api/wol.

Who:   New domain module for system benchmarking and WoL.
What:  REST endpoints for CPU/memory/disk/network benchmarks and Wake-on-LAN.
Why:   Exposes benchmark and WoL functionality to the web dashboard.
Where: Routes registered at /api/bench/* and /api/wol.
When:  Called by serve.py dispatcher via domain route registration.

Maps to freq/modules/benchmark.py and freq/modules/wol.py.
Benchmark results are stored in conf/bench/ for historical comparison.
"""

import json
import os
import time

from freq.api.helpers import json_response, get_json_body, get_param
from freq.modules.serve import _check_session_role
from freq.core.config import load_config
from freq.core import resolve as res


# -- Helpers ----------------------------------------------------------------


def _resolve_host_ip(cfg, host_str: str) -> str:
    """Resolve a host label or IP to an IP address.

    Tries label lookup first (via resolve.by_target), falls back to
    treating the string as a raw IP if no match is found.

    Returns:
        IP address string, or empty string if unresolvable.
    """
    if not host_str:
        return ""

    # Try resolving via config hosts (label or IP match)
    host = res.by_target(cfg.hosts, host_str)
    if host:
        return host.ip

    # If it looks like an IP already, use it directly
    parts = host_str.split(".")
    if len(parts) == 4:
        try:
            if all(0 <= int(p) <= 255 for p in parts):
                return host_str
        except ValueError:
            pass

    return ""


def _bench_results_dir(cfg) -> str:
    """Return the path to the benchmark results directory, creating it if needed."""
    bench_dir = os.path.join(cfg.conf_dir, "bench")
    os.makedirs(bench_dir, exist_ok=True)
    return bench_dir


def _save_bench_result(cfg, host_ip: str, bench_type: str, result: dict):
    """Save a benchmark result to conf/bench/ for historical tracking.

    File naming: {host_ip}_{bench_type}_{timestamp}.json
    """
    bench_dir = _bench_results_dir(cfg)
    ts = time.strftime("%Y%m%d_%H%M%S")
    # Sanitize IP for filename (replace dots with dashes)
    safe_ip = host_ip.replace(".", "-")
    filename = f"{safe_ip}_{bench_type}_{ts}.json"
    filepath = os.path.join(bench_dir, filename)

    data = {
        "host": host_ip,
        "type": bench_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "result": result,
    }

    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # Non-fatal — results are still returned in the response


def _load_bench_results(cfg, host_filter: str = "", type_filter: str = "") -> list:
    """Load stored benchmark results from conf/bench/.

    Args:
        cfg: FreqConfig.
        host_filter: Filter by host IP (optional, substring match).
        type_filter: Filter by benchmark type (optional, exact match).

    Returns:
        List of result dicts, sorted by timestamp descending (newest first).
    """
    bench_dir = _bench_results_dir(cfg)
    results = []

    try:
        files = sorted(os.listdir(bench_dir), reverse=True)
    except OSError:
        return []

    for filename in files:
        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(bench_dir, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        # Apply filters
        if host_filter and host_filter not in data.get("host", ""):
            continue
        if type_filter and data.get("type") != type_filter:
            continue

        results.append(data)

    return results


# -- WoL Handler ------------------------------------------------------------


def handle_wol(handler):
    """POST /api/wol — send a Wake-on-LAN magic packet (admin only).

    Request body:
        {"mac": "AA:BB:CC:DD:EE:FF", "broadcast": "255.255.255.255"}

    The broadcast field is optional (defaults to 255.255.255.255).
    Use a directed broadcast for cross-VLAN WoL (e.g., 10.25.10.255).
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    body = get_json_body(handler)
    mac = body.get("mac", "").strip()
    broadcast = body.get("broadcast", "255.255.255.255").strip()

    if not mac:
        json_response(handler, {"error": "MAC address required"}, 400)
        return

    from freq.modules.wol import send_wol, parse_mac

    # Validate MAC before sending
    try:
        parse_mac(mac)
    except ValueError as e:
        json_response(handler, {"error": str(e)}, 400)
        return

    try:
        send_wol(mac, broadcast=broadcast)
        json_response(
            handler,
            {
                "ok": True,
                "mac": mac,
                "broadcast": broadcast,
                "message": f"Magic packet sent to {mac}",
            },
        )
    except OSError as e:
        json_response(
            handler,
            {
                "error": f"Failed to send WoL packet: {e}",
            },
            500,
        )


# -- Benchmark Handlers -----------------------------------------------------


def handle_bench_run(handler):
    """POST /api/bench/run — run a benchmark on a host (admin only).

    Request body:
        {"host": "label-or-ip", "type": "cpu|memory|disk|all"}

    Type defaults to "all" if not specified.
    Results are stored in conf/bench/ and returned in the response.
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    body = get_json_body(handler)
    host_str = body.get("host", "").strip()
    bench_type = body.get("type", "all").strip().lower()

    if not host_str:
        json_response(handler, {"error": "Host required (label or IP)"}, 400)
        return

    host_ip = _resolve_host_ip(cfg, host_str)
    if not host_ip:
        json_response(handler, {"error": f"Cannot resolve host: {host_str}"}, 400)
        return

    valid_types = ("cpu", "memory", "disk", "all")
    if bench_type not in valid_types:
        json_response(
            handler,
            {
                "error": f"Invalid benchmark type: {bench_type}. Valid: {', '.join(valid_types)}",
            },
            400,
        )
        return

    from freq.modules.benchmark import (
        bench_cpu,
        bench_memory,
        bench_disk,
        bench_all,
    )

    try:
        if bench_type == "all":
            result = bench_all(host_ip, cfg=cfg)
            _save_bench_result(cfg, host_ip, "all", result)
        elif bench_type == "cpu":
            result = bench_cpu(host_ip, cfg=cfg)
            _save_bench_result(cfg, host_ip, "cpu", result)
        elif bench_type == "memory":
            result = bench_memory(host_ip, cfg=cfg)
            _save_bench_result(cfg, host_ip, "memory", result)
        elif bench_type == "disk":
            result = bench_disk(host_ip, cfg=cfg)
            _save_bench_result(cfg, host_ip, "disk", result)

        json_response(
            handler,
            {
                "ok": True,
                "host": host_ip,
                "type": bench_type,
                "result": result,
            },
        )
    except Exception as e:
        json_response(
            handler,
            {
                "error": f"Benchmark failed on {host_ip}: {e}",
            },
            500,
        )


def handle_bench_results(handler):
    """GET /api/bench/results — return stored benchmark results.

    Query parameters:
        host: Filter by host IP (substring match, optional)
        type: Filter by benchmark type (exact match, optional)
        limit: Maximum results to return (default: 50)
    """
    cfg = load_config()
    host_filter = get_param(handler, "host", "")
    type_filter = get_param(handler, "type", "")
    limit_str = get_param(handler, "limit", "50")

    try:
        limit = int(limit_str)
        limit = max(1, min(limit, 500))
    except ValueError:
        limit = 50

    results = _load_bench_results(cfg, host_filter=host_filter, type_filter=type_filter)

    json_response(
        handler,
        {
            "results": results[:limit],
            "total": len(results),
            "filters": {
                "host": host_filter or None,
                "type": type_filter or None,
            },
        },
    )


def handle_bench_netspeed(handler):
    """POST /api/bench/netspeed — run iperf3 network test between two hosts (admin only).

    Request body:
        {"source": "host-a-label-or-ip", "target": "host-b-label-or-ip"}

    Starts iperf3 server on target, runs client from source.
    Results are stored in conf/bench/ and returned in the response.
    """
    role, err = _check_session_role(handler, "admin")
    if err:
        json_response(handler, {"error": err}, 403)
        return

    cfg = load_config()
    body = get_json_body(handler)
    source_str = body.get("source", "").strip()
    target_str = body.get("target", "").strip()

    if not source_str or not target_str:
        json_response(handler, {"error": "Both source and target hosts required"}, 400)
        return

    source_ip = _resolve_host_ip(cfg, source_str)
    if not source_ip:
        json_response(handler, {"error": f"Cannot resolve source host: {source_str}"}, 400)
        return

    target_ip = _resolve_host_ip(cfg, target_str)
    if not target_ip:
        json_response(handler, {"error": f"Cannot resolve target host: {target_str}"}, 400)
        return

    if source_ip == target_ip:
        json_response(handler, {"error": "Source and target must be different hosts"}, 400)
        return

    from freq.modules.benchmark import bench_network

    try:
        result = bench_network(source_ip, target_ip, cfg=cfg)
        _save_bench_result(cfg, f"{source_ip}_to_{target_ip}", "network", result)
        json_response(
            handler,
            {
                "ok": result.get("ok", False),
                "source": source_ip,
                "target": target_ip,
                "result": result,
            },
        )
    except Exception as e:
        json_response(
            handler,
            {
                "error": f"Network benchmark failed: {e}",
            },
            500,
        )


def handle_bench_tools(handler):
    """GET /api/bench/tools?host=X — check which benchmark tools are installed.

    Query parameters:
        host: Host label or IP (required)

    Returns which of sysbench, fio, iperf3 are available on the target host.
    """
    cfg = load_config()
    host_str = get_param(handler, "host", "")

    if not host_str:
        json_response(handler, {"error": "Host parameter required (?host=label-or-ip)"}, 400)
        return

    host_ip = _resolve_host_ip(cfg, host_str)
    if not host_ip:
        json_response(handler, {"error": f"Cannot resolve host: {host_str}"}, 400)
        return

    from freq.modules.benchmark import check_tools

    try:
        tools = check_tools(host_ip, cfg=cfg)
        available = [name for name, path in tools.items() if path]
        missing = [name for name, path in tools.items() if not path]

        json_response(
            handler,
            {
                "host": host_ip,
                "tools": tools,
                "available": available,
                "missing": missing,
                "ready": len(missing) == 0,
            },
        )
    except Exception as e:
        json_response(
            handler,
            {
                "error": f"Tool check failed on {host_ip}: {e}",
            },
            500,
        )


# -- Registration ------------------------------------------------------------


def register(routes: dict):
    """Register benchmark and WoL API routes into the master route table."""
    # Wake-on-LAN
    routes["/api/wol"] = handle_wol

    # Benchmarks
    routes["/api/bench/run"] = handle_bench_run
    routes["/api/bench/results"] = handle_bench_results
    routes["/api/bench/netspeed"] = handle_bench_netspeed
    routes["/api/bench/tools"] = handle_bench_tools
