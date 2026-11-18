"""Pure fleet-status classification and summary contracts.

The CLI owns probing, cache freshness, timing, and rendering.  This module
only turns already-collected probe results into deterministic status data so
the machine and human count contracts can be tested without SSH or terminal
I/O.
"""

from freq.core.health_state import (
    STATE_AUTH_FAILED,
    STATE_DEGRADED,
    STATE_LIVE,
    aggregate_probe_state,
    classify_probe_failure,
)


def classify_fleet_results(probes, dashboard_health: dict, probed_at: float) -> list[dict]:
    """Classify one already-looked-up result for each host, preserving order."""
    classified = []
    for host, result in probes:
        returncode = result.returncode if result else 1
        stderr = (result.stderr or "") if result else "no response"
        stdout = (result.stdout or "") if result else ""
        duration = round(result.duration, 2) if result else None

        if result and returncode == 0:
            classified.append(
                {
                    "label": host.label,
                    "ip": host.ip,
                    "type": host.htype,
                    "state": STATE_LIVE,
                    "reason": "probe OK",
                    "uptime": stdout.strip(),
                    "probed_at": probed_at,
                    "duration": duration,
                    "status": "online",
                }
            )
            continue

        state, reason = classify_probe_failure(returncode, stderr, stdout)
        is_legacy = host.htype in ("idrac", "switch")
        stderr_lower = stderr.lower()
        stdout_lower = stdout.lower()
        operator_auth_issue = is_legacy and (
            "permission denied" in stderr_lower
            or "publickey" in stderr_lower
            or "permission denied" in stdout_lower
            or "publickey" in stdout_lower
            or state == STATE_AUTH_FAILED
        )

        cached = dashboard_health.get(host.ip) if operator_auth_issue else None
        cached_live = bool(
            cached and (cached.get("state") in (STATE_LIVE, "live") or cached.get("status") == "healthy")
        )
        if cached_live:
            detail = cached.get("load", "") or cached.get("ram", "") or "healthy"
            classified.append(
                {
                    "label": host.label,
                    "ip": host.ip,
                    "type": host.htype,
                    "state": STATE_LIVE,
                    "reason": f"via dashboard cache: {detail}",
                    "uptime": f"via dashboard: {detail}",
                    "probed_at": probed_at,
                    "duration": duration,
                    "status": "online",
                }
            )
            continue

        classified.append(
            {
                "label": host.label,
                "ip": host.ip,
                "type": host.htype,
                "state": state,
                "reason": reason,
                "uptime": "",
                "probed_at": probed_at,
                "duration": duration,
                "status": "offline",
                "operator_auth_issue": operator_auth_issue,
            }
        )

    return classified


def machine_status_counts(classified: list[dict]) -> dict:
    """Count machine status: every non-live entry is offline."""
    online = sum(1 for entry in classified if entry["state"] == STATE_LIVE)
    return {"online": online, "offline": len(classified) - online}


def human_status_counts(classified: list[dict]) -> dict:
    """Count the legacy human table/exit contract without flattening it."""
    counts = {"up": 0, "down": 0, "na": 0, "degraded": 0, "auth_failed": 0}
    for entry in classified:
        state = entry["state"]
        if state == STATE_LIVE:
            counts["up"] += 1
        elif state == STATE_AUTH_FAILED:
            if entry.get("operator_auth_issue"):
                counts["na"] += 1
            else:
                counts["auth_failed"] += 1
                counts["down"] += 1
        elif state == STATE_DEGRADED:
            counts["degraded"] += 1
        else:
            counts["down"] += 1
    return counts


def build_machine_status_payload(classified: list[dict], total_duration: float) -> dict:
    """Build the stable JSON payload without leaking renderer-only metadata."""
    probe_state, probe_reason = aggregate_probe_state(classified)
    counts = machine_status_counts(classified)
    hosts = []
    for entry in classified:
        item = {
            "label": entry["label"],
            "ip": entry["ip"],
            "type": entry["type"],
            "state": entry["state"],
            "reason": entry["reason"],
            "probed_at": entry["probed_at"],
            "duration": entry["duration"],
            "status": entry["status"],
        }
        if entry["state"] == STATE_LIVE:
            item["uptime"] = entry.get("uptime", "")
        else:
            item["error"] = entry["reason"]
        hosts.append(item)

    return {
        "hosts": hosts,
        "total": len(classified),
        "online": counts["online"],
        "offline": counts["offline"],
        "probe_state": probe_state,
        "probe_reason": probe_reason,
        "duration": round(total_duration, 2),
    }
