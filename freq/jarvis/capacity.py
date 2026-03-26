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
