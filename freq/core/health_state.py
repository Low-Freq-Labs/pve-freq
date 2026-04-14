"""Six-state fleet health contract.

Shared classifier so the /api/health background probe (serve.py
_bg_probe_health) and the cold-cache fallback (api/fleet.py
handle_health_api) can't drift and can't collapse real failure
classes into a mute boolean.

Product law (pve-freq-product-law.md):
  - probes must encode expected state, not only current state
  - health/recovery contracts must distinguish:
      live / stale / degraded / auth_failed / unreachable / recovering
  - remediation paths must capture evidence before acting
  - no boolean-only "healthy" abstractions where reason/timestamp/
    last-success are required

Design:
  - `state` (the new canonical field) is always one of the six tokens.
  - `status` is kept as a legacy alias ("healthy"|"unreachable") so the
    existing frontend (~20+ `h.status==='healthy'` checks in app.js)
    does not break. Morty's migration flips readers to `state` when
    convenient. Both fields emit from the same source of truth.
  - Every probe result carries `reason` (one-line operator-readable),
    `probed_at` (unix ts), `last_success_at` (unix ts or None),
    `failure_count` (consecutive failures).
  - Stale entries (reused cache because the probe was skipped) flip to
    state='stale' with `age_seconds` so a tired operator at 2am does
    not confuse a 10-minute-old cache for a fresh measurement.
"""
from __future__ import annotations

from typing import Optional


STATE_LIVE = "live"
STATE_STALE = "stale"
STATE_DEGRADED = "degraded"
STATE_AUTH_FAILED = "auth_failed"
STATE_UNREACHABLE = "unreachable"
STATE_RECOVERING = "recovering"

ALL_STATES = frozenset({
    STATE_LIVE,
    STATE_STALE,
    STATE_DEGRADED,
    STATE_AUTH_FAILED,
    STATE_UNREACHABLE,
    STATE_RECOVERING,
})


def legacy_status_for(state: str) -> str:
    """Map a six-state token to the legacy 'healthy'|'unreachable' alias.

    Frontend compat: app.js treats 'healthy' as up, everything else as
    down. live + recovering = up; stale + degraded + auth_failed +
    unreachable = down. Stale on its own is still honest: the cache may
    be old, so we refuse to report it as 'healthy'. Degraded likewise
    (partial probe success is not full success — the product law says
    do not collapse partial failure into fake green).
    """
    if state in (STATE_LIVE, STATE_RECOVERING):
        return "healthy"
    return "unreachable"


def classify_probe_failure(returncode: int, stderr: str, stdout: str) -> tuple[str, str]:
    """Classify a failed probe by inspecting ssh exit code + stderr.

    Returns a (state, reason) pair. The reason is an operator-facing
    one-liner — should be copyable into a findings note without edits.

    Pattern-match priority:
      1. GNU-timeout rc=124 (our _run_bounded process-group kill) →
         unreachable (wall-clock kill is definitively a dead handshake)
      2. ssh exit 255 with BatchMode publickey / permission denied →
         auth_failed
      3. 'Connection refused' / 'No route to host' / 'Network is
         unreachable' / 'Host is down' → unreachable (kernel-level)
      4. 'Connection timed out during banner exchange' / 'ssh:
         connect to host ... Connection timed out' → unreachable
      5. anything else non-zero with stdout empty → degraded (probe
         ran but produced no usable metrics — could be missing command,
         PAM quirk, wrong shell). The operator should look.
    """
    err = (stderr or "").strip()
    err_low = err.lower()
    out = (stdout or "").strip()

    if returncode == 124 or "timed out after" in err_low:
        return STATE_UNREACHABLE, f"probe command timed out ({err[:120] or 'no stderr'})"

    auth_markers = (
        "permission denied",
        "publickey",
        "no supported authentication methods",
        "too many authentication failures",
    )
    if any(m in err_low for m in auth_markers):
        return STATE_AUTH_FAILED, f"ssh auth rejected: {err[:120] or 'no stderr'}"

    reach_markers = (
        "connection refused",
        "no route to host",
        "network is unreachable",
        "host is down",
        "connection timed out",
        "connection closed",
        "connection reset",
        "name or service not known",
        "could not resolve hostname",
        "banner exchange",
    )
    if any(m in err_low for m in reach_markers):
        return STATE_UNREACHABLE, f"host unreachable: {err[:120] or 'no stderr'}"

    # Probe ran (ssh connected) but returned no usable stdout. Command
    # missing, shell quirk, PAM stall, racadm in a weird state — the
    # operator should investigate. Refuse to mark as live OR unreachable.
    if returncode != 0 and not out:
        return STATE_DEGRADED, (
            f"probe exit {returncode}, no output ({err[:80] or 'no stderr'})"
        )

    # Fall-through: returncode==0 but caller still classified as failed
    # (e.g. parse error after successful exec). Partial success → degraded.
    return STATE_DEGRADED, f"probe parse error (exit {returncode})"


def entry_base(
    h,
    state: str,
    reason: str,
    probed_at: float,
    last_success_at: Optional[float] = None,
    failure_count: int = 0,
    groups: str = "",
) -> dict:
    """Build the common header fields for any health entry.

    Callers add per-type metrics (cores/ram/disk/load/docker) on top.
    """
    if state not in ALL_STATES:
        # Never silently accept a bogus state — crash the probe so the
        # bug surfaces at the source instead of lying to the dashboard.
        raise ValueError(f"invalid health state: {state!r}")
    return {
        "label": h.label,
        "ip": h.ip,
        "type": h.htype,
        "groups": groups,
        # New canonical six-state field.
        "state": state,
        "reason": reason,
        "probed_at": probed_at,
        "last_success_at": last_success_at,
        "failure_count": failure_count,
        # Legacy compat alias for the frontend. Flipped via
        # legacy_status_for so it can't drift out of sync.
        "status": legacy_status_for(state),
    }


def mark_stale(cached_entry: dict, now: float, reason: str) -> dict:
    """Flip a previously-fresh entry to state='stale' and attach age.

    The entry keeps its metrics (cores/ram/etc.) so the dashboard has
    something to show, but the state and legacy status both flip to
    reflect that this data is old. Operator sees 'STALE (age 180s)'
    instead of a lying green badge.

    The cache may be old-shape (no `probed_at`) — fall back to
    `age_seconds = 0` in that case so we don't emit NaN.
    """
    entry = dict(cached_entry)
    probed_at = entry.get("probed_at") or 0.0
    try:
        age = max(0.0, round(now - float(probed_at), 1)) if probed_at else 0.0
    except (TypeError, ValueError):
        age = 0.0
    entry["state"] = STATE_STALE
    entry["status"] = legacy_status_for(STATE_STALE)
    entry["reason"] = reason
    entry["age_seconds"] = age
    return entry


def aggregate_probe_state(host_entries: list) -> tuple[str, str]:
    """Derive a top-level probe_state + reason from per-host entries.

    Used by /api/health (and later /api/fleet/overview) so Morty's
    silent-refresh banner does not have to guess whether the fleet is
    healthy by counting undefined fields.

    Priority (worst wins):
      auth_failed > unreachable > degraded > stale > recovering > live

    Reason is a short operator-readable rollup: 'N of M unreachable
    (worst: host-a publickey rejected)' or 'all 12 live'.
    """
    if not host_entries:
        return STATE_DEGRADED, "no hosts in fleet"
    priority = [
        STATE_AUTH_FAILED,
        STATE_UNREACHABLE,
        STATE_DEGRADED,
        STATE_STALE,
        STATE_RECOVERING,
        STATE_LIVE,
    ]
    counts: dict[str, int] = {s: 0 for s in priority}
    worst_reason = ""
    worst_host = ""
    for e in host_entries:
        s = e.get("state") or legacy_back_to_state(e.get("status"))
        counts[s] = counts.get(s, 0) + 1
    top = STATE_LIVE
    for s in priority:
        if counts.get(s, 0) > 0:
            top = s
            break
    if top == STATE_LIVE:
        return STATE_LIVE, f"all {len(host_entries)} hosts live"
    # Find the first host matching the worst state for the reason.
    for e in host_entries:
        if (e.get("state") or legacy_back_to_state(e.get("status"))) == top:
            worst_reason = e.get("reason") or ""
            worst_host = e.get("label") or e.get("ip") or ""
            break
    bad = counts.get(top, 0)
    total = len(host_entries)
    suffix = f" (worst: {worst_host} — {worst_reason})" if worst_reason else ""
    return top, f"{bad}/{total} {top}{suffix}"


def legacy_back_to_state(status: Optional[str]) -> str:
    """Fallback for cache entries predating the six-state contract.

    Old cache entries only carry legacy `status`; treat 'healthy' as
    live and everything else as unreachable so the aggregator does not
    crash on mixed-shape data during a dashboard upgrade.
    """
    if status == "healthy":
        return STATE_LIVE
    return STATE_UNREACHABLE
