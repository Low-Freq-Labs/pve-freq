"""Notification rules engine for FREQ.

Evaluates alert rules against health data from the background cache.
Fires notifications when conditions are met, with cooldown tracking
to prevent alert storms.

Rule types:
  host_unreachable — host down for N seconds
  cpu_above        — load average exceeds threshold
  ram_above        — RAM usage exceeds threshold %
  disk_above       — disk usage exceeds threshold %
  docker_down      — Docker container count drops to 0
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

from freq.core import log as logger


# ── Data Types ──────────────────────────────────────────────────────────

@dataclass
class Rule:
    """A single alert rule."""
    name: str
    condition: str          # host_unreachable, cpu_above, ram_above, disk_above, docker_down
    target: str = "*"       # host label glob or "*" for all
    threshold: float = 0.0  # numeric threshold (%, load avg, count)
    duration: int = 0       # seconds condition must persist before firing
    severity: str = "warning"  # info, warning, critical
    cooldown: int = 300     # seconds between repeated alerts for same rule+host
    enabled: bool = True


@dataclass
class Alert:
    """A fired alert."""
    rule_name: str
    host: str
    message: str
    severity: str
    fired_at: float = 0.0


# ── Rule Loading ────────────────────────────────────────────────────────

def load_rules(conf_dir: str) -> list:
    """Load rules from conf/rules.toml. Returns list of Rule objects."""
    path = os.path.join(conf_dir, "rules.toml")
    if not os.path.isfile(path):
        return _default_rules()

    try:
        import tomllib
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        logger.warn(f"Failed to load rules.toml: {e}")
        return _default_rules()

    rules = []
    for name, cfg in data.get("rule", {}).items():
        rules.append(Rule(
            name=name,
            condition=cfg.get("condition", ""),
            target=cfg.get("target", "*"),
            threshold=float(cfg.get("threshold", 0)),
            duration=int(cfg.get("duration", 0)),
            severity=cfg.get("severity", "warning"),
            cooldown=int(cfg.get("cooldown", 300)),
            enabled=cfg.get("enabled", True),
        ))

    return rules if rules else _default_rules()


def save_rules(conf_dir: str, rules: list) -> bool:
    """Save rules to conf/rules.toml."""
    path = os.path.join(conf_dir, "rules.toml")
    os.makedirs(conf_dir, exist_ok=True)
    try:
        lines = ["# FREQ Alert Rules\n"]
        for r in rules:
            lines.append(f'[rule."{r.name}"]')
            lines.append(f'condition = "{r.condition}"')
            lines.append(f'target = "{r.target}"')
            lines.append(f"threshold = {r.threshold}")
            lines.append(f"duration = {r.duration}")
            lines.append(f'severity = "{r.severity}"')
            lines.append(f"cooldown = {r.cooldown}")
            lines.append(f"enabled = {'true' if r.enabled else 'false'}")
            lines.append("")
        with open(path, "w") as f:
            f.write("\n".join(lines))
        return True
    except OSError as e:
        logger.error(f"Failed to save rules: {e}")
        return False


def _default_rules() -> list:
    """Built-in default rules shipped with FREQ."""
    return [
        Rule(name="host-unreachable", condition="host_unreachable",
             target="*", threshold=0, duration=300, severity="critical", cooldown=600),
        Rule(name="disk-critical", condition="disk_above",
             target="*", threshold=90, duration=0, severity="warning", cooldown=3600),
        Rule(name="ram-pressure", condition="ram_above",
             target="*", threshold=95, duration=0, severity="warning", cooldown=3600),
    ]


# ── Rule State ──────────────────────────────────────────────────────────

def load_rule_state(cache_dir: str) -> dict:
    """Load persistent rule state (cooldowns, durations) from disk."""
    path = os.path.join(cache_dir, "rule_state.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_rule_state(cache_dir: str, state: dict) -> None:
    """Save rule state to disk."""
    path = os.path.join(cache_dir, "rule_state.json")
    os.makedirs(cache_dir, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(state, f)
    except OSError as e:
        logger.warn(f"Failed to save rule state: {e}")


# ── Alert History ───────────────────────────────────────────────────────

MAX_HISTORY = 100

def load_alert_history(cache_dir: str) -> list:
    """Load alert history from disk."""
    path = os.path.join(cache_dir, "alert_history.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_alert_history(cache_dir: str, history: list) -> None:
    """Save alert history (capped at MAX_HISTORY entries)."""
    path = os.path.join(cache_dir, "alert_history.json")
    os.makedirs(cache_dir, exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(history[-MAX_HISTORY:], f)
    except OSError as e:
        logger.warn(f"Failed to save alert history: {e}")


# ── Evaluation ──────────────────────────────────────────────────────────

def _matches_target(host_label: str, target: str) -> bool:
    """Check if a host label matches a target pattern (* = all, or prefix*)."""
    if target == "*":
        return True
    if target.endswith("*"):
        return host_label.startswith(target[:-1])
    return host_label == target


def _parse_ram_percent(ram_str: str) -> Optional[float]:
    """Parse RAM string like '1234/8192MB' into percent used."""
    m = re.match(r'(\d+)/(\d+)', ram_str)
    if m:
        used, total = int(m.group(1)), int(m.group(2))
        if total > 0:
            return (used / total) * 100
    return None


def _parse_disk_percent(disk_str: str) -> Optional[float]:
    """Parse disk string like '45%' into float."""
    m = re.match(r'(\d+)%', disk_str)
    if m:
        return float(m.group(1))
    return None


def evaluate_rules(health_data: dict, rules: list, state: dict) -> list:
    """Evaluate all rules against current health data.

    Args:
        health_data: The health cache dict with "hosts" list
        rules: List of Rule objects
        state: Mutable dict for tracking durations and cooldowns

    Returns:
        List of Alert objects that should be fired (passed duration + cooldown checks)
    """
    now = time.time()
    alerts = []
    hosts = health_data.get("hosts", [])

    for rule in rules:
        if not rule.enabled:
            continue

        for host in hosts:
            label = host.get("label", "")
            if not _matches_target(label, rule.target):
                continue

            triggered = _check_condition(rule, host)
            state_key = f"{rule.name}:{label}"

            if triggered:
                # Track when condition first started
                if state_key not in state:
                    state[state_key] = {"first_seen": now, "last_alerted": 0}
                elif "first_seen" not in state[state_key]:
                    state[state_key]["first_seen"] = now

                entry = state[state_key]
                elapsed = now - entry["first_seen"]

                # Duration gate
                if elapsed < rule.duration:
                    continue

                # Cooldown gate
                if entry.get("last_alerted", 0) > 0:
                    since_last = now - entry["last_alerted"]
                    if since_last < rule.cooldown:
                        continue

                # Fire alert
                msg = _build_message(rule, host)
                alerts.append(Alert(
                    rule_name=rule.name,
                    host=label,
                    message=msg,
                    severity=rule.severity,
                    fired_at=now,
                ))
                entry["last_alerted"] = now
            else:
                # Condition cleared — reset tracking
                if state_key in state:
                    del state[state_key]

    return alerts


def _check_condition(rule: Rule, host: dict) -> bool:
    """Check if a single rule condition is met for a host."""
    status = host.get("status", "")
    cond = rule.condition

    if cond == "host_unreachable":
        return status == "unreachable"

    if cond == "cpu_above":
        try:
            load = float(host.get("load", "0"))
            return load > rule.threshold
        except (ValueError, TypeError):
            return False

    if cond == "ram_above":
        pct = _parse_ram_percent(host.get("ram", ""))
        if pct is not None:
            return pct > rule.threshold
        return False

    if cond == "disk_above":
        pct = _parse_disk_percent(host.get("disk", ""))
        if pct is not None:
            return pct > rule.threshold
        return False

    if cond == "docker_down":
        htype = host.get("type", "")
        if htype == "docker":
            try:
                count = int(host.get("docker", "0"))
                return count == 0
            except (ValueError, TypeError):
                return False
        return False

    return False


def _build_message(rule: Rule, host: dict) -> str:
    """Build a human-readable alert message."""
    label = host.get("label", "unknown")
    cond = rule.condition

    if cond == "host_unreachable":
        return f"Host **{label}** ({host.get('ip', '?')}) is unreachable"

    if cond == "cpu_above":
        return f"Host **{label}** CPU load {host.get('load', '?')} exceeds threshold {rule.threshold}"

    if cond == "ram_above":
        return f"Host **{label}** RAM usage {host.get('ram', '?')} exceeds {rule.threshold}%"

    if cond == "disk_above":
        return f"Host **{label}** disk usage {host.get('disk', '?')} exceeds {rule.threshold}%"

    if cond == "docker_down":
        return f"Host **{label}** has 0 running Docker containers"

    return f"Alert rule '{rule.name}' triggered on {label}"


# ── Serialization ───────────────────────────────────────────────────────

def rules_to_dicts(rules: list) -> list:
    """Convert Rule objects to JSON-serializable dicts."""
    return [
        {
            "name": r.name,
            "condition": r.condition,
            "target": r.target,
            "threshold": r.threshold,
            "duration": r.duration,
            "severity": r.severity,
            "cooldown": r.cooldown,
            "enabled": r.enabled,
        }
        for r in rules
    ]


def alert_to_dict(alert: Alert) -> dict:
    """Convert an Alert to a JSON-serializable dict."""
    return {
        "rule_name": alert.rule_name,
        "host": alert.host,
        "message": alert.message,
        "severity": alert.severity,
        "fired_at": alert.fired_at,
    }
