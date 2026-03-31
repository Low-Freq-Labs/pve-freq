"""Fleet capacity planner for FREQ.

Stores weekly health snapshots in data/capacity/. After 4+ weeks of data,
projects trend lines for RAM, disk, and CPU. Helps predict when hosts
will hit capacity limits.

"At current growth, pve01 hits 80% RAM in 23 days."
"""
import json
import os
import re
import time
from datetime import datetime, timedelta

from freq.core import log as logger


CAPACITY_DIR_NAME = "capacity"
SNAPSHOT_PREFIX = "snapshot_"
MIN_WEEKS_FOR_PROJECTION = 2


def _capacity_dir(data_dir: str) -> str:
    """Return the capacity data directory path."""
    return os.path.join(data_dir, CAPACITY_DIR_NAME)


def save_snapshot(data_dir: str, health_data: dict) -> str:
    """Save a health snapshot to the capacity directory.

    Called periodically (weekly) from the background loop.
    Returns the snapshot filename.
    """
    cap_dir = _capacity_dir(data_dir)
    os.makedirs(cap_dir, exist_ok=True)

    ts = datetime.now()
    filename = f"{SNAPSHOT_PREFIX}{ts.strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(cap_dir, filename)

    # Extract per-host metrics from health data
    hosts = {}
    for h in health_data.get("hosts", []):
        label = h.get("label", "")
        if not label:
            continue
        hosts[label] = {
            "ram": h.get("ram", ""),
            "disk": h.get("disk", ""),
            "load": h.get("load", ""),
            "status": h.get("status", ""),
            "docker": h.get("docker", "0"),
        }

    snapshot = {
        "timestamp": ts.isoformat(),
        "epoch": time.time(),
        "hosts": hosts,
    }

    try:
        with open(path, "w") as f:
            json.dump(snapshot, f)
        return filename
    except OSError as e:
        logger.warn(f"Failed to save capacity snapshot: {e}")
        return ""


def load_snapshots(data_dir: str) -> list:
    """Load all capacity snapshots, sorted by timestamp."""
    cap_dir = _capacity_dir(data_dir)
    if not os.path.isdir(cap_dir):
        return []

    snapshots = []
    for fname in sorted(os.listdir(cap_dir)):
        if not fname.startswith(SNAPSHOT_PREFIX) or not fname.endswith(".json"):
            continue
        path = os.path.join(cap_dir, fname)
        try:
            with open(path) as f:
                snapshots.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue

    return snapshots


def _parse_ram_pct(ram_str: str) -> float:
    """Parse RAM string '1234/8192MB' into percentage."""
    m = re.match(r'(\d+)/(\d+)', ram_str)
    if m:
        used, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            return round((used / total) * 100, 1)
    return -1


def _parse_disk_pct(disk_str: str) -> float:
    """Parse disk string '45%' into float."""
    m = re.match(r'(\d+)%', disk_str)
    if m:
        return float(m.group(1))
    return -1


def _linear_regression(points: list) -> tuple:
    """Simple linear regression on (x, y) points. Returns (slope, intercept)."""
    n = len(points)
    if n < 2:
        return (0, 0)
    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_xx = sum(p[0] * p[0] for p in points)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return (0, sum_y / n)
    slope = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    import math
    if not math.isfinite(slope) or not math.isfinite(intercept):
        return (0, sum_y / n if n > 0 else 0)
    return (slope, intercept)


def compute_projections(snapshots: list) -> dict:
    """Compute trend projections for each host.

    Returns dict of {host_label: {metric: {current, trend, days_to_threshold}}}
    """
    if len(snapshots) < MIN_WEEKS_FOR_PROJECTION:
        return {}

    # Collect time-series per host per metric
    host_series = {}  # host -> metric -> [(epoch, value)]
    for snap in snapshots:
        epoch = snap.get("epoch", 0)
        for label, data in snap.get("hosts", {}).items():
            if label not in host_series:
                host_series[label] = {"ram": [], "disk": [], "load": []}

            ram_pct = _parse_ram_pct(data.get("ram", ""))
            if ram_pct >= 0:
                host_series[label]["ram"].append((epoch, ram_pct))

            disk_pct = _parse_disk_pct(data.get("disk", ""))
            if disk_pct >= 0:
                host_series[label]["disk"].append((epoch, disk_pct))

            try:
                load = float(data.get("load", "0"))
                host_series[label]["load"].append((epoch, load))
            except (ValueError, TypeError):
                pass

    # Compute projections
    projections = {}
    now = time.time()

    for label, metrics in host_series.items():
        host_proj = {}
        for metric, points in metrics.items():
            if len(points) < MIN_WEEKS_FOR_PROJECTION:
                continue

            # Normalize time to days from first snapshot
            t0 = points[0][0]
            normalized = [(((p[0] - t0) / 86400), p[1]) for p in points]
            slope, intercept = _linear_regression(normalized)

            current = points[-1][1]
            days_now = (now - t0) / 86400
            trend_value = slope * days_now + intercept

            # Days to threshold (80% for RAM/disk)
            threshold = 80 if metric in ("ram", "disk") else 0
            days_to_threshold = -1
            if slope > 0 and threshold > 0:
                days_at_threshold = (threshold - intercept) / slope
                remaining = days_at_threshold - days_now
                if remaining > 0:
                    days_to_threshold = min(round(remaining), 3650)  # cap at 10 years

            host_proj[metric] = {
                "current": round(current, 1),
                "trend": round(slope, 3),  # per day
                "trend_direction": "rising" if slope > 0.01 else "falling" if slope < -0.01 else "stable",
                "days_to_80pct": days_to_threshold if threshold > 0 else -1,
                "sparkline": [round(p[1], 1) for p in points[-12:]],  # last 12 data points
            }

        if host_proj:
            projections[label] = host_proj

    return projections


def should_snapshot(data_dir: str, interval_hours: int = 168) -> bool:
    """Check if enough time has passed since the last snapshot. Default: weekly (168h)."""
    cap_dir = _capacity_dir(data_dir)
    if not os.path.isdir(cap_dir):
        return True

    files = sorted(f for f in os.listdir(cap_dir) if f.startswith(SNAPSHOT_PREFIX))
    if not files:
        return True

    # Parse timestamp from latest filename
    latest = files[-1]
    try:
        path = os.path.join(cap_dir, latest)
        with open(path) as f:
            data = json.load(f)
        last_epoch = data.get("epoch", 0)
        return (time.time() - last_epoch) > (interval_hours * 3600)
    except (json.JSONDecodeError, OSError):
        return True


def recommend_migrations(projections: dict, costs: list = None) -> list:
    """Generate migration recommendations based on capacity + cost data.

    Finds hosts approaching limits and suggests migrating workloads
    to hosts with more headroom.

    Returns list of recommendation dicts:
        {
            "type": "migrate" | "alert" | "optimize",
            "source": host_label,
            "target": host_label or "",
            "reason": str,
            "metric": "ram" | "disk",
            "urgency": "critical" | "warning" | "info",
            "savings_month": float (from cost data, if available),
            "days_extended": int (estimated),
        }
    """
    recommendations = []

    if not projections:
        return recommendations

    # Classify hosts by resource pressure
    hosts_at_risk = []   # approaching 80% within 90 days
    hosts_stable = []    # stable or declining usage

    for label, metrics in projections.items():
        for metric in ("ram", "disk"):
            if metric not in metrics:
                continue
            data = metrics[metric]
            current = data.get("current", 0)
            days = data.get("days_to_80pct", -1)
            direction = data.get("trend_direction", "stable")

            if current >= 80:
                hosts_at_risk.append({
                    "label": label,
                    "metric": metric,
                    "current": current,
                    "days": 0,
                    "direction": direction,
                    "urgency": "critical",
                })
            elif 0 < days <= 30:
                hosts_at_risk.append({
                    "label": label,
                    "metric": metric,
                    "current": current,
                    "days": days,
                    "direction": direction,
                    "urgency": "warning",
                })
            elif 0 < days <= 90:
                hosts_at_risk.append({
                    "label": label,
                    "metric": metric,
                    "current": current,
                    "days": days,
                    "direction": direction,
                    "urgency": "info",
                })
            elif direction in ("stable", "falling") and current < 50:
                hosts_stable.append({
                    "label": label,
                    "metric": metric,
                    "current": current,
                })

    # Build cost lookup
    cost_by_label = {}
    if costs:
        for c in costs:
            cost_by_label[c.label] = c

    # Generate recommendations
    for risk in hosts_at_risk:
        # Find a stable target for migration
        targets = [
            s for s in hosts_stable
            if s["label"] != risk["label"] and s["metric"] == risk["metric"]
        ]
        # Sort by most headroom
        targets.sort(key=lambda t: t["current"])

        if risk["urgency"] == "critical":
            reason = (f"{risk['label']} {risk['metric'].upper()} at {risk['current']:.0f}% — "
                      f"over threshold")
        elif risk["days"] > 0:
            reason = (f"{risk['label']} {risk['metric'].upper()} at {risk['current']:.0f}% — "
                      f"hits 80% in {risk['days']} days")
        else:
            reason = f"{risk['label']} {risk['metric'].upper()} trending {risk['direction']}"

        rec = {
            "type": "migrate" if targets else "alert",
            "source": risk["label"],
            "target": targets[0]["label"] if targets else "",
            "reason": reason,
            "metric": risk["metric"],
            "urgency": risk["urgency"],
            "savings_month": 0.0,
            "days_extended": 0,
        }

        if targets:
            # Estimate extension: if target has 50% headroom and source is at 80%,
            # migrating some load could extend by ~2x the current runway
            target_headroom = 80 - targets[0]["current"]
            if risk["days"] > 0 and target_headroom > 20:
                rec["days_extended"] = min(risk["days"] * 2, 365)
            rec["reason"] += f" → migrate to {targets[0]['label']} ({targets[0]['current']:.0f}% used)"

        # Add cost savings estimate if we have cost data
        if rec["target"] and rec["target"] in cost_by_label and risk["label"] in cost_by_label:
            # If we can move load off, savings come from potential right-sizing
            target_cost = cost_by_label[rec["target"]]
            if target_cost.watts_source == "estimate":
                # Conservative: 10% of target host monthly cost
                rec["savings_month"] = round(target_cost.cost_month * 0.1, 2)

        recommendations.append(rec)

    # Add optimization recommendations for very idle hosts
    for stable in hosts_stable:
        if stable["current"] < 20 and stable["label"] in cost_by_label:
            cost = cost_by_label[stable["label"]]
            if cost.cost_month > 5:  # Only flag if meaningful cost
                recommendations.append({
                    "type": "optimize",
                    "source": stable["label"],
                    "target": "",
                    "reason": f"{stable['label']} is only {stable['current']:.0f}% "
                              f"{stable['metric'].upper()} — consider consolidation "
                              f"(saves ~{cost.cost_month:.2f}/mo)",
                    "metric": stable["metric"],
                    "urgency": "info",
                    "savings_month": round(cost.cost_month, 2),
                    "days_extended": 0,
                })

    # Sort by urgency: critical > warning > info
    urgency_order = {"critical": 0, "warning": 1, "info": 2}
    recommendations.sort(key=lambda r: urgency_order.get(r["urgency"], 3))

    return recommendations


# ── CLI Command ────────────────────────────────────────────────────────

def cmd_capacity(cfg, pack, args) -> int:
    """Show fleet capacity projections."""
    from freq.core import fmt

    action = getattr(args, "action", "show")

    if action == "snapshot":
        # Force a snapshot now
        from freq.modules.serve import _bg_cache, _bg_lock
        with _bg_lock:
            health = _bg_cache.get("health")
        if not health:
            fmt.error("No health data available. Is freq serve running?")
            return 1
        fname = save_snapshot(cfg.data_dir, health)
        if fname:
            fmt.header("Capacity Snapshot")
            fmt.step_ok(f"Saved: {fname}")
            fmt.footer()
        return 0

    # Show projections
    fmt.header("Fleet Capacity")
    fmt.blank()

    snapshots = load_snapshots(cfg.data_dir)
    if len(snapshots) < MIN_WEEKS_FOR_PROJECTION:
        fmt.line(f"  {fmt.C.YELLOW}Need {MIN_WEEKS_FOR_PROJECTION}+ weeks of data for projections.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Snapshots collected: {len(snapshots)}{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Data is collected automatically when freq serve is running.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    projections = compute_projections(snapshots)
    if not projections:
        fmt.line(f"  {fmt.C.DIM}No projection data available.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    for label, metrics in sorted(projections.items()):
        fmt.line(f"  {fmt.C.BOLD}{label}{fmt.C.RESET}")
        for metric, data in metrics.items():
            current = data["current"]
            direction = data["trend_direction"]
            days = data.get("days_to_80pct", -1)

            if metric in ("ram", "disk"):
                color = fmt.C.RED if current >= 80 else fmt.C.YELLOW if current >= 60 else fmt.C.GREEN
                val = f"{current}%"
                if days > 0:
                    warn = f" → 80% in {days} days" if days < 90 else ""
                else:
                    warn = ""
            else:
                color = fmt.C.GREEN
                val = str(current)
                warn = ""

            arrow = "↑" if direction == "rising" else "↓" if direction == "falling" else "→"
            fmt.line(f"    {metric:<6} {color}{val:>6}{fmt.C.RESET} {arrow} {fmt.C.DIM}{direction}{warn}{fmt.C.RESET}")
        fmt.blank()

    # Show recommendations if available
    recs = recommend_migrations(projections)
    if recs:
        fmt.divider("Recommendations")
        fmt.blank()
        for rec in recs:
            if rec["urgency"] == "critical":
                icon = f"{fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET}"
            elif rec["urgency"] == "warning":
                icon = f"{fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}"
            else:
                icon = f"{fmt.C.CYAN}i{fmt.C.RESET}"

            fmt.line(f"  {icon} {rec['reason']}")
            if rec.get("days_extended") and rec["days_extended"] > 0:
                fmt.line(f"    {fmt.C.DIM}Extends runway by ~{rec['days_extended']} days{fmt.C.RESET}")
            if rec.get("savings_month") and rec["savings_month"] > 0:
                fmt.line(f"    {fmt.C.DIM}Est. savings: ~${rec['savings_month']:.2f}/mo{fmt.C.RESET}")
        fmt.blank()

    fmt.footer()
    return 0
