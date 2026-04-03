"""Incident playbook runner for FREQ.

Domain: freq auto playbook <list|run>

Loads TOML-defined playbooks from conf/playbooks/ and executes them step by
step via SSH. Each step is a check (verify state) or action (change state)
with optional confirmation gates.

Replaces: Rundeck / PagerDuty runbooks ($10k+/yr)

Architecture:
    - Playbooks loaded from TOML with [playbook] metadata and [[step]] list
    - run_step() resolves target host, SSHes command, checks expected output
    - Confirmation steps skip in CLI mode (designed for interactive UI use)

Design decisions:
    - TOML playbooks are git-trackable and human-editable, not stored in a DB
    - Steps run sequentially, not in parallel — incident response needs order
"""
import os
import time
from dataclasses import dataclass, field

from freq.core import log as logger


@dataclass
class PlaybookStep:
    """A single step in a playbook."""
    name: str
    step_type: str  # "check" or "action"
    command: str
    target: str = ""  # host label
    expect: str = ""  # expected output for checks
    confirm: bool = False  # require user confirmation before executing
    timeout: int = 30


@dataclass
class Playbook:
    """A complete incident playbook."""
    filename: str
    name: str
    description: str = ""
    trigger: str = ""  # alert rule name or condition that triggers this
    steps: list = field(default_factory=list)


@dataclass
class StepResult:
    """Result of executing a single step."""
    step_name: str
    step_type: str
    status: str  # "pass", "fail", "skipped", "pending_confirm"
    output: str = ""
    error: str = ""
    duration: float = 0.0


def load_playbooks(conf_dir: str) -> list:
    """Load all playbooks from conf/playbooks/."""
    pb_dir = os.path.join(conf_dir, "playbooks")
    if not os.path.isdir(pb_dir):
        return []

    playbooks = []
    for fname in sorted(os.listdir(pb_dir)):
        if not fname.endswith(".toml"):
            continue
        path = os.path.join(pb_dir, fname)
        try:
            import tomllib
            with open(path, "rb") as f:
                data = tomllib.load(f)
            pb_meta = data.get("playbook", {})
            steps = []
            for s in data.get("step", []):
                steps.append(PlaybookStep(
                    name=s.get("name", ""),
                    step_type=s.get("type", "check"),
                    command=s.get("command", ""),
                    target=s.get("target", ""),
                    expect=s.get("expect", ""),
                    confirm=s.get("confirm", False),
                    timeout=int(s.get("timeout", 30)),
                ))
            playbooks.append(Playbook(
                filename=fname,
                name=pb_meta.get("name", fname),
                description=pb_meta.get("description", ""),
                trigger=pb_meta.get("trigger", ""),
                steps=steps,
            ))
        except Exception as e:
            logger.warn(f"Failed to load playbook {fname}: {e}")

    return playbooks


def playbooks_to_dicts(playbooks: list) -> list:
    """Convert playbooks to JSON-serializable dicts."""
    return [
        {
            "filename": pb.filename,
            "name": pb.name,
            "description": pb.description,
            "trigger": pb.trigger,
            "steps": [
                {
                    "name": s.name,
                    "type": s.step_type,
                    "command": s.command,
                    "target": s.target,
                    "expect": s.expect,
                    "confirm": s.confirm,
                    "timeout": s.timeout,
                }
                for s in pb.steps
            ],
        }
        for pb in playbooks
    ]


def run_step(step: PlaybookStep, ssh_func, cfg) -> StepResult:
    """Execute a single playbook step via SSH.

    ssh_func should be freq.core.ssh.run (synchronous).
    Returns a StepResult.
    """
    from freq.core import resolve as res

    start = time.monotonic()

    # Resolve target host
    host = res.by_target(cfg.hosts, step.target) if step.target else None
    if not host and step.target:
        return StepResult(
            step_name=step.name, step_type=step.step_type, status="fail",
            error=f"Host '{step.target}' not found",
            duration=time.monotonic() - start,
        )

    if not host:
        return StepResult(
            step_name=step.name, step_type=step.step_type, status="fail",
            error="No target host specified",
            duration=time.monotonic() - start,
        )

    # Execute command
    r = ssh_func(
        host=host.ip, command=step.command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=step.timeout,
        htype=host.htype, use_sudo=True, cfg=cfg,
    )

    duration = time.monotonic() - start
    output = r.stdout.strip() if r.stdout else ""
    error = r.stderr.strip() if r.stderr else ""

    if r.returncode != 0:
        return StepResult(
            step_name=step.name, step_type=step.step_type, status="fail",
            output=output, error=error or f"exit code {r.returncode}",
            duration=duration,
        )

    # For checks, verify expected output
    if step.step_type == "check" and step.expect:
        if step.expect.lower() in output.lower():
            status = "pass"
        else:
            status = "fail"
            error = f"Expected '{step.expect}' in output"
    else:
        status = "pass"

    return StepResult(
        step_name=step.name, step_type=step.step_type, status=status,
        output=output, error=error, duration=duration,
    )


def result_to_dict(result: StepResult) -> dict:
    """Convert StepResult to JSON-serializable dict."""
    return {
        "step_name": result.step_name,
        "step_type": result.step_type,
        "status": result.status,
        "output": result.output[:200],
        "error": result.error[:200],
        "duration": round(result.duration, 2),
    }


# ── CLI Command ────────────────────────────────────────────────────────

def cmd_playbook(cfg, pack, args) -> int:
    """List and run incident playbooks."""
    from freq.core import fmt
    from freq.core.ssh import run as ssh_run

    action = getattr(args, "action", "list")
    name = getattr(args, "name", None)

    playbooks = load_playbooks(cfg.conf_dir)

    if action == "list":
        fmt.header("Playbooks")
        fmt.blank()
        if not playbooks:
            fmt.line(f"  {fmt.C.DIM}No playbooks found in conf/playbooks/.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Create .toml files with [playbook] and [[step]] sections.{fmt.C.RESET}")
        else:
            for pb in playbooks:
                trigger = f" → trigger: {pb.trigger}" if pb.trigger else ""
                fmt.line(f"  {fmt.C.BOLD}{pb.name}{fmt.C.RESET}  {fmt.C.DIM}({pb.filename}){trigger}{fmt.C.RESET}")
                if pb.description:
                    fmt.line(f"    {pb.description}")
                fmt.line(f"    {len(pb.steps)} steps: {', '.join(s.name for s in pb.steps)}")
                fmt.blank()
        fmt.footer()
        return 0

    elif action == "run":
        if not name:
            fmt.error("Usage: freq playbook run <filename>")
            return 1
        pb = next((p for p in playbooks if p.filename == name or p.name == name), None)
        if not pb:
            fmt.error(f"Playbook not found: {name}")
            return 1

        fmt.header(f"Playbook: {pb.name}")
        fmt.blank()
        ok = 0
        fail = 0
        for i, step in enumerate(pb.steps, 1):
            if step.confirm:
                fmt.line(f"  {fmt.C.YELLOW}Step {i} requires confirmation — skipping in CLI mode{fmt.C.RESET}")
                continue
            fmt.line(f"  {fmt.C.DIM}[{i}/{len(pb.steps)}]{fmt.C.RESET} {step.name} ({step.step_type}) → {step.target}")
            result = run_step(step, ssh_run, cfg)
            if result.status == "pass":
                fmt.step_ok(f"{step.name}: {result.output[:80]}" if result.output else step.name)
                ok += 1
            else:
                fmt.error(f"{step.name}: {result.error[:80]}")
                fail += 1
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Results: {ok} passed, {fail} failed{fmt.C.RESET}")
        fmt.footer()
        return 0 if fail == 0 else 1

    fmt.error(f"Unknown action: {action}")
    return 1
