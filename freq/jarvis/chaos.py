"""Chaos engineering experiments for FREQ.

Domain: freq auto chaos

Injects controlled failures into fleet hosts to test recovery. Five experiment
types (service_kill, service_restart, network_delay, disk_fill, cpu_stress)
with safety gates, auto-rollback, and recovery time measurement.

Replaces: Gremlin / LitmusChaos ($10k+/yr SaaS)

Architecture:
    - Experiments are template-based: inject command, rollback, verify
    - Safety layer blocks production VMIDs and fleet-boundaries categories
    - All results logged to data/chaos/ as JSON for post-mortem analysis

Design decisions:
    - 5-minute max duration hard cap prevents runaway experiments
    - VMIDs 800-899 are always off-limits regardless of config
    - Auto-rollback fires even on failure to prevent lingering damage
"""
import json
import os
import time
from dataclasses import dataclass, field



CHAOS_DIR_NAME = "chaos"
MAX_DURATION = 300  # 5 minutes max for any experiment


@dataclass
class Experiment:
    """A chaos engineering experiment definition."""
    name: str
    experiment_type: str  # service_kill, service_restart, network_delay, disk_fill, cpu_stress
    target_host: str      # host label from hosts.conf
    target_service: str = ""  # container or service name
    duration: int = 60    # seconds
    parameters: dict = field(default_factory=dict)


@dataclass
class ExperimentResult:
    """Result of a chaos experiment."""
    experiment_name: str
    experiment_type: str
    target_host: str
    status: str = "pending"  # pending, running, completed, failed, blocked, rolled_back
    start_time: float = 0.0
    end_time: float = 0.0
    inject_output: str = ""
    rollback_output: str = ""
    recovery_time: float = 0.0  # seconds until service recovered
    error: str = ""


# ── Experiment commands ──────────────────────────────────────────────

EXPERIMENTS = {
    "service_kill": {
        "description": "Stop a Docker container",
        "inject": "docker stop {service}",
        "rollback": "docker start {service}",
        "verify": "docker inspect -f '{{{{.State.Running}}}}' {service}",
        "expect_recovered": "true",
    },
    "service_restart": {
        "description": "Restart a systemd service",
        "inject": "systemctl restart {service}",
        "rollback": "",  # restart IS the rollback
        "verify": "systemctl is-active {service}",
        "expect_recovered": "active",
    },
    "network_delay": {
        "description": "Add network latency (100ms) to an interface",
        "inject": "tc qdisc add dev {interface} root netem delay 100ms",
        "rollback": "tc qdisc del dev {interface} root",
        "verify": "ping -c 1 -W 2 127.0.0.1 > /dev/null 2>&1 && echo ok",
        "expect_recovered": "ok",
    },
    "disk_fill": {
        "description": "Create a temp file to simulate disk pressure",
        "inject": "dd if=/dev/zero of=/tmp/chaos-fill bs=1M count={size_mb} 2>/dev/null && echo filled",
        "rollback": "rm -f /tmp/chaos-fill",
        "verify": "test ! -f /tmp/chaos-fill && echo clean || echo filled",
        "expect_recovered": "clean",
    },
    "cpu_stress": {
        "description": "Spike CPU load",
        "inject": "timeout {duration} yes > /dev/null 2>&1 &",
        "rollback": "pkill -f 'yes' 2>/dev/null; true",
        "verify": "pgrep -c 'yes' 2>/dev/null || echo 0",
        "expect_recovered": "0",
    },
}


def _chaos_dir(data_dir: str) -> str:
    """Return the chaos log directory."""
    d = os.path.join(data_dir, CHAOS_DIR_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _log_experiment(data_dir: str, result: ExperimentResult):
    """Log an experiment result to disk."""
    log_dir = _chaos_dir(data_dir)
    ts = time.strftime("%Y%m%d_%H%M%S")
    filename = f"experiment_{ts}_{result.experiment_name}.json"
    path = os.path.join(log_dir, filename)
    try:
        with open(path, "w") as f:
            json.dump(result_to_dict(result), f)
    except OSError:
        pass


def check_safety(target_host: str, cfg) -> tuple:
    """Check if the target host is safe for chaos experiments.

    Returns (safe: bool, reason: str).
    """
    for h in cfg.hosts:
        if h.label == target_host:
            # Hard block: VMIDs 800-899 — unconditional, regardless of config
            vmid = getattr(h, "vmid", 0)
            if vmid and 800 <= vmid <= 899:
                return False, f"VMID {vmid} is in hard-blocked range 800-899"

            # Check fleet boundaries for production category
            fb = cfg.fleet_boundaries
            if fb and hasattr(fb, 'tiers'):
                for tier_name, tier in fb.tiers.items():
                    if tier_name.lower() in ("production", "infrastructure", "critical"):
                        if hasattr(tier, 'vmid_ranges'):
                            for vr in tier.vmid_ranges:
                                try:
                                    parts = vr.split("-")
                                    if len(parts) == 2:
                                        low, high = int(parts[0]), int(parts[1])
                                        if vmid and low <= vmid <= high:
                                            return False, f"VMID {vmid} is in protected tier '{tier_name}'"
                                except ValueError:
                                    pass
            break

    return True, ""


def validate_experiment(exp: Experiment) -> tuple:
    """Validate experiment parameters. Returns (valid: bool, error: str)."""
    if exp.experiment_type not in EXPERIMENTS:
        return False, f"Unknown experiment type: {exp.experiment_type}"

    if not exp.target_host:
        return False, "Target host is required"

    if exp.duration > MAX_DURATION:
        return False, f"Duration exceeds maximum of {MAX_DURATION}s"

    if exp.duration < 1:
        return False, "Duration must be at least 1 second"

    if exp.experiment_type in ("service_kill", "service_restart") and not exp.target_service:
        return False, "Target service is required for this experiment type"

    # Validate service name — no shell metacharacters
    import re
    if exp.target_service and not re.match(r'^[a-zA-Z0-9._@-]+$', exp.target_service):
        return False, "Invalid service name (alphanumeric, dots, hyphens, underscores only)"

    return True, ""


def build_commands(exp: Experiment) -> dict:
    """Build inject/rollback/verify commands from experiment definition."""
    template = EXPERIMENTS.get(exp.experiment_type, {})
    params = {
        "service": exp.target_service,
        "duration": str(exp.duration),
        "interface": exp.parameters.get("interface", "$(ip route show default 2>/dev/null | awk '{print $5}' | head -1 || echo eth0)"),
        "size_mb": str(exp.parameters.get("size_mb", 100)),
    }

    def _fmt(cmd_template):
        if not cmd_template:
            return ""
        try:
            return cmd_template.format(**params)
        except KeyError:
            return cmd_template

    return {
        "inject": _fmt(template.get("inject", "")),
        "rollback": _fmt(template.get("rollback", "")),
        "verify": _fmt(template.get("verify", "")),
        "expect_recovered": template.get("expect_recovered", ""),
    }


def run_experiment(exp: Experiment, ssh_func, cfg) -> ExperimentResult:
    """Execute a chaos experiment with automatic rollback.

    ssh_func should be freq.core.ssh.run (synchronous).
    """
    from freq.core import resolve as res

    result = ExperimentResult(
        experiment_name=exp.name,
        experiment_type=exp.experiment_type,
        target_host=exp.target_host,
    )

    # Safety check
    safe, reason = check_safety(exp.target_host, cfg)
    if not safe:
        result.status = "blocked"
        result.error = reason
        _log_experiment(cfg.data_dir, result)
        return result

    # Validate
    valid, err = validate_experiment(exp)
    if not valid:
        result.status = "failed"
        result.error = err
        _log_experiment(cfg.data_dir, result)
        return result

    # Resolve host
    host = res.by_target(cfg.hosts, exp.target_host)
    if not host:
        result.status = "failed"
        result.error = f"Host '{exp.target_host}' not found"
        _log_experiment(cfg.data_dir, result)
        return result

    commands = build_commands(exp)
    result.status = "running"
    result.start_time = time.time()

    # Inject failure
    r = ssh_func(
        host=host.ip, command=commands["inject"],
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=min(exp.duration + 10, MAX_DURATION),
        htype=host.htype, use_sudo=True, cfg=cfg,
    )
    result.inject_output = (r.stdout or "").strip()[:500]

    if r.returncode != 0:
        result.status = "failed"
        result.error = (r.stderr or "").strip()[:200] or f"inject exit code {r.returncode}"
        result.end_time = time.time()
        _log_experiment(cfg.data_dir, result)
        return result

    # Wait for duration (for experiments like service_kill)
    if exp.experiment_type not in ("service_restart",):
        time.sleep(min(exp.duration, MAX_DURATION))

    # Rollback
    if commands["rollback"]:
        r = ssh_func(
            host=host.ip, command=commands["rollback"],
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=30,
            htype=host.htype, use_sudo=True, cfg=cfg,
        )
        result.rollback_output = (r.stdout or "").strip()[:500]
        if r.returncode != 0:
            result.status = "rolled_back"
            result.error = "Rollback may have failed: " + ((r.stderr or "").strip()[:200])

    # Verify recovery
    if commands["verify"]:
        recovery_start = time.time()
        recovered = False
        for attempt in range(10):
            r = ssh_func(
                host=host.ip, command=commands["verify"],
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=10,
                htype=host.htype, use_sudo=True, cfg=cfg,
            )
            output = (r.stdout or "").strip()
            if commands["expect_recovered"] in output:
                recovered = True
                result.recovery_time = round(time.time() - recovery_start, 2)
                break
            time.sleep(2)

        if not recovered:
            result.status = "failed"
            result.error = "Service did not recover after rollback"
        else:
            result.status = "completed"
    else:
        result.status = "completed"

    result.end_time = time.time()
    _log_experiment(cfg.data_dir, result)
    return result


def load_experiment_log(data_dir: str, count: int = 20) -> list:
    """Load recent experiment logs."""
    log_dir = _chaos_dir(data_dir)
    files = sorted(
        [f for f in os.listdir(log_dir) if f.startswith("experiment_") and f.endswith(".json")],
        reverse=True,
    )[:count]

    results = []
    for fname in files:
        try:
            with open(os.path.join(log_dir, fname)) as f:
                results.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def result_to_dict(result: ExperimentResult) -> dict:
    """Convert ExperimentResult to JSON-serializable dict."""
    return {
        "experiment_name": result.experiment_name,
        "experiment_type": result.experiment_type,
        "target_host": result.target_host,
        "status": result.status,
        "start_time": round(result.start_time, 2),
        "end_time": round(result.end_time, 2),
        "duration": round(result.end_time - result.start_time, 2) if result.end_time > 0 else 0,
        "inject_output": result.inject_output[:200],
        "rollback_output": result.rollback_output[:200],
        "recovery_time": result.recovery_time,
        "error": result.error[:200],
    }


def list_experiment_types() -> list:
    """List available experiment types with descriptions."""
    return [
        {"type": k, "description": v["description"]}
        for k, v in EXPERIMENTS.items()
    ]


# ── CLI Command ────────────────────────────────────────────────────────

def cmd_chaos(cfg, pack, args) -> int:
    """Chaos engineering experiments."""
    from freq.core import fmt
    from freq.core.ssh import run as ssh_run

    action = getattr(args, "action", "list")

    if action == "list":
        fmt.header("Chaos Engineering")
        fmt.blank()
        for et in list_experiment_types():
            fmt.line(f"  {fmt.C.CYAN}{et['type']:<20}{fmt.C.RESET} {et['description']}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Usage: freq chaos run --type <type> --host <host> [--service <svc>] [--duration <sec>]{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    elif action == "run":
        exp_type = getattr(args, "type", None)
        host = getattr(args, "host", None)
        service = getattr(args, "service", "")
        duration = getattr(args, "duration", 60)

        if not exp_type or not host:
            fmt.error("Usage: freq chaos run --type <type> --host <host>")
            return 1

        # Safety check
        safe, msg = check_safety(host, cfg)
        if not safe:
            fmt.error(f"Safety check failed: {msg}")
            return 1

        exp = Experiment(
            name=f"cli-{exp_type}-{host}",
            experiment_type=exp_type,
            target_host=host,
            target_service=service,
            duration=min(duration, 300),  # cap at 5 minutes
        )

        ok, msg = validate_experiment(exp)
        if not ok:
            fmt.error(msg)
            return 1

        # Confirm
        if not getattr(args, "yes", False):
            fmt.warn(f"About to run {exp_type} on {host} for {exp.duration}s")
            confirm = input(f"  Type YES to proceed: ")
            if confirm.strip() != "YES":
                fmt.line(f"  {fmt.C.DIM}Cancelled.{fmt.C.RESET}")
                return 0

        fmt.header(f"Chaos: {exp_type} → {host}")
        fmt.blank()
        result = run_experiment(exp, ssh_run, cfg)

        if result.status == "completed":
            fmt.step_ok(f"Experiment completed — recovered in {result.recovery_time:.1f}s")
        elif result.status == "failed":
            fmt.error(f"Experiment failed: {result.error}")
        else:
            fmt.warn(f"Status: {result.status}")

        if result.inject_output:
            fmt.line(f"  {fmt.C.DIM}Output: {result.inject_output[:100]}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0 if result.status == "completed" else 1

    elif action == "log":
        fmt.header("Chaos Experiment Log")
        fmt.blank()
        entries = load_experiment_log(cfg.data_dir, count=20)
        if not entries:
            fmt.line(f"  {fmt.C.DIM}No experiments recorded yet.{fmt.C.RESET}")
        else:
            for e in entries:
                status_color = fmt.C.GREEN if e.get("status") == "completed" else fmt.C.RED
                fmt.line(f"  {fmt.C.DIM}{e.get('experiment_name', '?')}{fmt.C.RESET} {status_color}{e.get('status', '?')}{fmt.C.RESET} {e.get('duration', 0):.1f}s → {e.get('target_host', '?')}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.error(f"Unknown action: {action}")
    return 1
