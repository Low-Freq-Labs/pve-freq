"""Durable non-secret state for the browser-only setup workflow."""

import json
import os
import secrets
import time

SCHEMA = "zero-state-web-v1"
SETUP_TTL_SECONDS = 3600
_STATE_FILENAME = "zero-state-web.json"
_PHASES = {
    "collecting",
    "discovering",
    "selecting",
    "credentials",
    "ready",
    "initializing",
    "blocked",
}


def setup_state_path(cfg) -> str:
    return os.path.join(cfg.data_dir, "setup", _STATE_FILENAME)


def _atomic_write(path: str, payload: dict) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    os.chmod(tmp, 0o600)
    if os.path.exists(path):
        try:
            stat = os.stat(path)
            os.chown(tmp, stat.st_uid, stat.st_gid)
        except OSError:
            pass
    os.replace(tmp, path)


def clear_setup_state(cfg) -> None:
    path = setup_state_path(cfg)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def load_setup_state(cfg, *, now: float | None = None) -> dict:
    """Load active state, deleting expired or malformed state fail-closed."""
    path = setup_state_path(cfg)
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        clear_setup_state(cfg)
        return {}
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        clear_setup_state(cfg)
        return {}
    clock = time.time() if now is None else now
    last_activity = float(state.get("last_activity_at") or state.get("created_at") or 0)
    if not last_activity or clock - last_activity > SETUP_TTL_SECONDS:
        clear_setup_state(cfg)
        return {}
    return state


def ensure_setup_state(cfg, username: str, *, now: float | None = None) -> dict:
    """Return the active setup identity, creating it when absent or expired."""
    clock = time.time() if now is None else now
    state = load_setup_state(cfg, now=clock)
    if state:
        if state.get("username") != username:
            raise ValueError("setup state belongs to another operator")
        return state
    state = {
        "schema": SCHEMA,
        "setup_id": secrets.token_urlsafe(24),
        "username": username,
        "phase": "collecting",
        "created_at": clock,
        "updated_at": clock,
        "last_activity_at": clock,
        "active_discovery_id": None,
        "active_contract_id": None,
        "active_init_job_id": None,
    }
    _atomic_write(setup_state_path(cfg), state)
    return state


def update_setup_state(cfg, *, now: float | None = None, **updates) -> dict:
    """Update allowlisted setup metadata without accepting arbitrary phases."""
    clock = time.time() if now is None else now
    state = load_setup_state(cfg, now=clock)
    if not state:
        raise ValueError("setup state is missing or expired")
    if "phase" in updates and updates["phase"] not in _PHASES:
        raise ValueError(f"invalid setup phase: {updates['phase']}")
    allowed = {
        "phase",
        "active_discovery_id",
        "active_contract_id",
        "active_init_job_id",
        "last_error_code",
    }
    unknown = set(updates) - allowed
    if unknown:
        raise ValueError(f"unsupported setup state fields: {', '.join(sorted(unknown))}")
    state.update(updates)
    state["updated_at"] = clock
    state["last_activity_at"] = clock
    _atomic_write(setup_state_path(cfg), state)
    return state


def touch_setup_state(cfg, *, now: float | None = None) -> dict:
    return update_setup_state(cfg, now=now)
