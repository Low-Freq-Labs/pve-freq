"""GitOps configuration sync for FREQ.

Domain: freq state gitops

Points FREQ at a git repo holding config files (freq.toml, hosts.conf,
rules.toml, playbooks/). Auto-pulls on a schedule, shows diffs, and supports
rollback to any commit.

Replaces: ArgoCD / Flux for infrastructure config ($0 — git-native)

Architecture:
    - Repo cloned into data/gitops/, synced via fetch + rev-list count
    - SyncState persisted to data/gitops_state.json between restarts
    - apply_changes() does git pull; rollback() does git checkout <hash>

Design decisions:
    - Fetch-then-count before pull lets operators review diffs first
    - auto_apply defaults to false — changes require explicit approval
"""

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass

from freq.core import log as logger


GITOPS_DIR_NAME = "gitops"
STATE_FILE = "gitops_state.json"


@dataclass
class GitOpsConfig:
    """GitOps sync configuration."""

    repo_url: str = ""
    branch: str = "main"
    sync_interval: int = 300  # seconds
    auto_apply: bool = False
    enabled: bool = False


@dataclass
class SyncState:
    """Current state of the gitops sync."""

    last_sync: float = 0.0
    last_commit: str = ""
    last_message: str = ""
    last_error: str = ""
    pending_changes: int = 0
    status: str = "idle"  # idle, syncing, error, changes_pending


def _gitops_dir(data_dir: str) -> str:
    """Return the gitops working directory path."""
    return os.path.join(data_dir, GITOPS_DIR_NAME)


def _state_path(data_dir: str) -> str:
    """Return the state file path."""
    return os.path.join(data_dir, STATE_FILE)


def _run_git(cwd: str, *args, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    cmd = ["git"] + list(args)
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def load_gitops_config(conf_dir: str) -> GitOpsConfig:
    """Load gitops configuration from freq.toml."""
    toml_path = os.path.join(conf_dir, "freq.toml")
    if not os.path.isfile(toml_path):
        return GitOpsConfig()

    try:
        import tomllib

        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        go = data.get("gitops", {})
        return GitOpsConfig(
            repo_url=go.get("repo_url", ""),
            branch=go.get("branch", "main"),
            sync_interval=int(go.get("sync_interval", 300)),
            auto_apply=go.get("auto_apply", False),
            enabled=bool(go.get("repo_url", "")),
        )
    except Exception as e:
        logger.warn(f"Failed to load gitops config: {e}")
        return GitOpsConfig()


def load_state(data_dir: str) -> SyncState:
    """Load the current sync state from disk."""
    path = _state_path(data_dir)
    if not os.path.isfile(path):
        return SyncState()
    try:
        with open(path) as f:
            d = json.load(f)
        return SyncState(
            last_sync=d.get("last_sync", 0.0),
            last_commit=d.get("last_commit", ""),
            last_message=d.get("last_message", ""),
            last_error=d.get("last_error", ""),
            pending_changes=d.get("pending_changes", 0),
            status=d.get("status", "idle"),
        )
    except (json.JSONDecodeError, OSError):
        return SyncState()


def save_state(data_dir: str, state: SyncState):
    """Persist sync state to disk."""
    path = _state_path(data_dir)
    try:
        with open(path, "w") as f:
            json.dump(
                {
                    "last_sync": state.last_sync,
                    "last_commit": state.last_commit,
                    "last_message": state.last_message,
                    "last_error": state.last_error,
                    "pending_changes": state.pending_changes,
                    "status": state.status,
                },
                f,
            )
    except OSError as e:
        logger.warn(f"Failed to save gitops state: {e}")


def init_repo(data_dir: str, repo_url: str, branch: str = "main") -> tuple:
    """Clone the config repo into data/gitops/. Returns (success, message)."""
    go_dir = _gitops_dir(data_dir)
    if os.path.isdir(os.path.join(go_dir, ".git")):
        return True, "Repository already initialized"

    os.makedirs(go_dir, exist_ok=True)
    r = _run_git(data_dir, "clone", "-b", branch, "--single-branch", repo_url, GITOPS_DIR_NAME, timeout=60)
    if r.returncode != 0:
        return False, r.stderr.strip() or f"git clone failed (exit {r.returncode})"
    return True, "Repository cloned successfully"


def sync(data_dir: str, branch: str = "main") -> SyncState:
    """Pull latest changes from remote. Returns updated SyncState."""
    go_dir = _gitops_dir(data_dir)
    state = load_state(data_dir)
    state.status = "syncing"
    save_state(data_dir, state)

    if not os.path.isdir(os.path.join(go_dir, ".git")):
        state.status = "error"
        state.last_error = "Repository not initialized"
        state.last_sync = time.time()
        save_state(data_dir, state)
        return state

    # Fetch
    r = _run_git(go_dir, "fetch", "origin", branch, timeout=30)
    if r.returncode != 0:
        state.status = "error"
        state.last_error = r.stderr.strip() or "git fetch failed"
        state.last_sync = time.time()
        save_state(data_dir, state)
        return state

    # Check for changes
    r = _run_git(go_dir, "rev-list", "--count", f"HEAD..origin/{branch}")
    behind = int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip().isdigit() else 0

    if behind > 0:
        state.pending_changes = behind
        state.status = "changes_pending"
    else:
        state.pending_changes = 0
        state.status = "idle"

    # Get current commit info
    r = _run_git(go_dir, "log", "-1", "--format=%H|%s")
    if r.returncode == 0 and "|" in r.stdout:
        parts = r.stdout.strip().split("|", 1)
        state.last_commit = parts[0][:12]
        state.last_message = parts[1][:100]

    state.last_error = ""
    state.last_sync = time.time()
    save_state(data_dir, state)
    return state


def apply_changes(data_dir: str, branch: str = "main") -> tuple:
    """Pull and apply pending changes. Returns (success, message)."""
    go_dir = _gitops_dir(data_dir)
    if not os.path.isdir(os.path.join(go_dir, ".git")):
        return False, "Repository not initialized"

    r = _run_git(go_dir, "pull", "origin", branch, timeout=30)
    if r.returncode != 0:
        return False, r.stderr.strip() or "git pull failed"

    state = load_state(data_dir)
    state.pending_changes = 0
    state.status = "idle"
    state.last_sync = time.time()

    # Update commit info
    r = _run_git(go_dir, "log", "-1", "--format=%H|%s")
    if r.returncode == 0 and "|" in r.stdout:
        parts = r.stdout.strip().split("|", 1)
        state.last_commit = parts[0][:12]
        state.last_message = parts[1][:100]

    save_state(data_dir, state)
    return True, "Changes applied successfully"


def get_diff(data_dir: str, branch: str = "main") -> str:
    """Get the diff between local and remote. Returns diff text."""
    go_dir = _gitops_dir(data_dir)
    if not os.path.isdir(os.path.join(go_dir, ".git")):
        return ""

    r = _run_git(go_dir, "diff", f"HEAD..origin/{branch}", "--stat")
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def get_diff_full(data_dir: str, branch: str = "main") -> str:
    """Get the full diff between local and remote."""
    go_dir = _gitops_dir(data_dir)
    if not os.path.isdir(os.path.join(go_dir, ".git")):
        return ""

    r = _run_git(go_dir, "diff", f"HEAD..origin/{branch}")
    if r.returncode != 0:
        return ""
    return r.stdout[:5000]  # Cap at 5KB


def get_log(data_dir: str, count: int = 20) -> list:
    """Get recent commit history. Returns list of {hash, message, date, author}."""
    go_dir = _gitops_dir(data_dir)
    if not os.path.isdir(os.path.join(go_dir, ".git")):
        return []

    r = _run_git(go_dir, "log", f"-{count}", "--format=%H|%s|%ai|%an")
    if r.returncode != 0:
        return []

    commits = []
    for line in r.stdout.strip().split("\n"):
        if not line or "|" not in line:
            continue
        parts = line.split("|", 3)
        if len(parts) >= 4:
            commits.append(
                {
                    "hash": parts[0][:12],
                    "message": parts[1][:100],
                    "date": parts[2],
                    "author": parts[3],
                }
            )
    return commits


def rollback(data_dir: str, commit_hash: str) -> tuple:
    """Rollback to a specific commit. Returns (success, message)."""
    go_dir = _gitops_dir(data_dir)
    if not os.path.isdir(os.path.join(go_dir, ".git")):
        return False, "Repository not initialized"

    # Validate hash format (prevent injection)
    if not re.match(r"^[a-f0-9]{7,40}$", commit_hash):
        return False, "Invalid commit hash"

    r = _run_git(go_dir, "checkout", commit_hash, "--", ".")
    if r.returncode != 0:
        return False, r.stderr.strip() or "git checkout failed"

    # Commit the rollback to keep working tree clean
    _run_git(go_dir, "add", "-A")
    _run_git(go_dir, "commit", "-m", f"rollback to {commit_hash[:12]}")

    state = load_state(data_dir)
    state.last_commit = commit_hash[:12]
    state.pending_changes = 0
    state.status = "idle"
    state.last_sync = time.time()
    save_state(data_dir, state)
    return True, f"Rolled back to {commit_hash[:12]}"


def should_sync(data_dir: str, interval: int = 300) -> bool:
    """Check if enough time has passed since last sync."""
    state = load_state(data_dir)
    return (time.time() - state.last_sync) > interval


def state_to_dict(state: SyncState) -> dict:
    """Convert SyncState to JSON-serializable dict."""
    return {
        "last_sync": round(state.last_sync),
        "last_commit": state.last_commit,
        "last_message": state.last_message,
        "last_error": state.last_error,
        "pending_changes": state.pending_changes,
        "status": state.status,
    }


# ── CLI Command ────────────────────────────────────────────────────────


def cmd_gitops(cfg, pack, args) -> int:
    """GitOps config sync management."""
    from freq.core import fmt

    action = getattr(args, "action", "status")

    if action == "status":
        fmt.header("GitOps Config Sync")
        fmt.blank()
        gcfg = load_gitops_config(cfg.conf_dir)
        if not gcfg.repo_url:
            fmt.line(f"  {fmt.C.YELLOW}GitOps not configured.{fmt.C.RESET}")
            fmt.line(f"  {fmt.C.DIM}Add [gitops] section to freq.toml with repo_url.{fmt.C.RESET}")
            fmt.blank()
            fmt.footer()
            return 0
        state = load_state(cfg.data_dir)
        sd = state_to_dict(state)
        fmt.line(f"  Repo:     {gcfg.repo_url}")
        fmt.line(f"  Branch:   {gcfg.branch}")
        fmt.line(f"  Status:   {sd['status']}")
        fmt.line(f"  Commit:   {sd['last_commit'] or 'none'}")
        if sd["last_message"]:
            fmt.line(f"  Message:  {sd['last_message']}")
        fmt.line(f"  Pending:  {sd['pending_changes']} changes")
        if sd["last_error"]:
            fmt.line(f"  {fmt.C.RED}Error: {sd['last_error']}{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    elif action == "sync":
        fmt.header("GitOps Sync")
        gcfg = load_gitops_config(cfg.conf_dir)
        state = sync(cfg.data_dir, gcfg.branch)
        sd = state_to_dict(state)
        if sd["last_error"]:
            fmt.error(sd["last_error"])
            return 1
        fmt.step_ok(f"Synced — {sd['pending_changes']} pending changes, commit: {sd['last_commit']}")
        fmt.footer()
        return 0

    elif action == "apply":
        fmt.header("GitOps Apply")
        gcfg = load_gitops_config(cfg.conf_dir)
        ok, msg = apply_changes(cfg.data_dir, gcfg.branch)
        if ok:
            fmt.step_ok(msg)
        else:
            fmt.error(msg)
        fmt.footer()
        return 0 if ok else 1

    elif action == "diff":
        diff_text = get_diff(cfg.data_dir)
        if diff_text:
            print(diff_text)
        else:
            print("No changes.")
        return 0

    elif action == "log":
        fmt.header("GitOps Log")
        fmt.blank()
        entries = get_log(cfg.data_dir, count=20)
        if not entries:
            fmt.line(f"  {fmt.C.DIM}No commits yet.{fmt.C.RESET}")
        else:
            for e in entries:
                fmt.line(
                    f"  {fmt.C.DIM}{e.get('date', '')}{fmt.C.RESET} {fmt.C.CYAN}{e.get('hash', '')[:8]}{fmt.C.RESET} {e.get('message', '')}"
                )
        fmt.blank()
        fmt.footer()
        return 0

    fmt.error(f"Unknown action: {action}")
    return 1
