"""Incident playbook runner for FREQ.

Playbooks are TOML files in conf/playbooks/. Each playbook defines a
sequence of steps (checks + actions) with optional confirm gates.

Example playbook (conf/playbooks/plex-down.toml):
  [playbook]
  name = "Plex Down Recovery"
  description = "Restart Plex container and verify"
  trigger = "docker_down"

  [[step]]
  name = "Check container status"
  type = "check"
  command = "docker ps -a --filter name=plex --format '{{.Status}}'"
  target = "docker-media"
  expect = "Up"

  [[step]]
  name = "Restart Plex container"
  type = "action"
  command = "docker restart plex"
  target = "docker-media"
  confirm = true

  [[step]]
  name = "Verify Plex is responding"
  type = "check"
  command = "curl -sf http://localhost:32400/web/index.html -o /dev/null && echo ok"
  target = "docker-media"
  expect = "ok"
"""
import json
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
