"""Inbound webhook receiver for FREQ.

Commands: webhook (list/create/delete/test/log)

External systems talk TO freq. GitHub push → auto-deploy.
PVE event → trigger playbook. Monitoring alert → escalate.

Define webhooks that map inbound HTTP POSTs to freq commands.

Kills: Ansible Tower ($$$) webhook integrations.
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig

# Storage
WEBHOOK_DIR = "webhooks"
WEBHOOK_FILE = "hooks.json"
WEBHOOK_LOG = "webhook-log.json"
MAX_LOG = 200


def _webhook_dir(cfg: FreqConfig) -> str:
    """Get or create webhook directory."""
    path = os.path.join(cfg.conf_dir, WEBHOOK_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_hooks(cfg: FreqConfig) -> list:
    """Load webhook definitions."""
    filepath = os.path.join(_webhook_dir(cfg), WEBHOOK_FILE)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_hooks(cfg: FreqConfig, hooks: list):
    """Save webhook definitions."""
    filepath = os.path.join(_webhook_dir(cfg), WEBHOOK_FILE)
    with open(filepath, "w") as f:
        json.dump(hooks, f, indent=2)


def _load_log(cfg: FreqConfig) -> list:
    """Load webhook execution log."""
    filepath = os.path.join(_webhook_dir(cfg), WEBHOOK_LOG)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_log(cfg: FreqConfig, log_entries: list):
    """Save webhook execution log."""
    filepath = os.path.join(_webhook_dir(cfg), WEBHOOK_LOG)
    with open(filepath, "w") as f:
        json.dump(log_entries[-MAX_LOG:], f, indent=2)


def _generate_token() -> str:
    """Generate a random webhook token."""
    return hashlib.sha256(os.urandom(32)).hexdigest()[:32]


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 signature (GitHub-style)."""
    if not secret or not signature:
        return True  # No secret configured
    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def cmd_webhook(cfg: FreqConfig, pack, args) -> int:
    """Webhook management."""
    action = getattr(args, "action", None) or "list"

    routes = {
        "list": _cmd_list,
        "create": _cmd_create,
        "delete": _cmd_delete,
        "test": _cmd_test,
        "log": _cmd_log,
    }

    handler = routes.get(action)
    if handler:
        return handler(cfg, args)

    fmt.error(f"Unknown webhook action: {action}")
    fmt.info("Available: list, create, delete, test, log")
    return 1


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List configured webhooks."""
    fmt.header("Webhooks")
    fmt.blank()

    hooks = _load_hooks(cfg)
    if not hooks:
        fmt.line(f"  {fmt.C.DIM}No webhooks configured.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Create one:{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}  freq webhook create deploy-hook --command 'freq gitops sync'{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("NAME", 18), ("COMMAND", 30), ("TOKEN", 12), ("STATUS", 8),
    )

    for hook in hooks:
        enabled = hook.get("enabled", True)
        status = fmt.badge("on") if enabled else f"{fmt.C.RED}OFF{fmt.C.RESET}"
        token = hook.get("token", "")[:8] + "..."
        fmt.table_row(
            (f"{fmt.C.BOLD}{hook['name']}{fmt.C.RESET}", 18),
            (hook.get("command", "")[:30], 30),
            (token, 12),
            (status, 8),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Endpoint: POST /api/webhook/<name>?token=<token>{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}{len(hooks)} webhook(s){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_create(cfg: FreqConfig, args) -> int:
    """Create a new webhook."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq webhook create <name> --command '<cmd>'")
        return 1

    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        fmt.error("Webhook name must be alphanumeric with hyphens/underscores.")
        return 1

    command = getattr(args, "command", None)
    if not command:
        fmt.error("--command is required")
        return 1

    secret = getattr(args, "secret", None) or ""
    token = _generate_token()

    hooks = _load_hooks(cfg)
    if any(h["name"] == name for h in hooks):
        fmt.error(f"Webhook '{name}' already exists.")
        return 1

    hook = {
        "name": name,
        "command": command,
        "token": token,
        "secret": secret,
        "enabled": True,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "fire_count": 0,
    }

    hooks.append(hook)
    _save_hooks(cfg, hooks)

    fmt.header("Webhook Created")
    fmt.blank()
    fmt.step_ok(f"Webhook: {name}")
    fmt.line(f"  Command: {command}")
    fmt.line(f"  Token:   {token}")
    if secret:
        fmt.line(f"  Secret:  (configured for HMAC verification)")
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Trigger URL:{fmt.C.RESET}")
    fmt.line(f"  POST http://<freq-host>:8888/api/webhook/{name}?token={token}")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Test it: freq webhook test {name}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_delete(cfg: FreqConfig, args) -> int:
    """Delete a webhook."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq webhook delete <name>")
        return 1

    hooks = _load_hooks(cfg)
    original = len(hooks)
    hooks = [h for h in hooks if h["name"] != name]
    if len(hooks) == original:
        fmt.error(f"No webhook named '{name}'")
        return 1

    _save_hooks(cfg, hooks)
    fmt.step_ok(f"Deleted webhook: {name}")
    return 0


def _cmd_test(cfg: FreqConfig, args) -> int:
    """Test a webhook by firing it locally."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq webhook test <name>")
        return 1

    hooks = _load_hooks(cfg)
    hook = next((h for h in hooks if h["name"] == name), None)
    if not hook:
        fmt.error(f"No webhook named '{name}'")
        return 1

    fmt.header(f"Testing Webhook: {name}")
    fmt.blank()

    command = hook["command"]
    fmt.step_start(f"Executing: {command}")

    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            fmt.step_ok(f"Success (exit 0)")
        else:
            fmt.step_fail(f"Failed (exit {result.returncode})")
            if result.stderr:
                fmt.line(f"  {fmt.C.DIM}{result.stderr[:200]}{fmt.C.RESET}")
    except subprocess.TimeoutExpired:
        fmt.step_fail("Timed out")
    except Exception as e:
        fmt.step_fail(f"Error: {e}")

    # Log
    log_entries = _load_log(cfg)
    log_entries.append({
        "webhook": name, "source": "test",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "command": command,
    })
    _save_log(cfg, log_entries)

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_log(cfg: FreqConfig, args) -> int:
    """Show webhook execution log."""
    fmt.header("Webhook Log")
    fmt.blank()

    log_entries = _load_log(cfg)
    if not log_entries:
        fmt.line(f"  {fmt.C.DIM}No webhook events.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    lines = getattr(args, "lines", 20) or 20
    recent = log_entries[-lines:]

    fmt.table_header(("TIME", 20), ("WEBHOOK", 18), ("SOURCE", 12))

    for entry in reversed(recent):
        fmt.table_row(
            (entry.get("timestamp", "")[:19], 20),
            (entry.get("webhook", ""), 18),
            (entry.get("source", ""), 12),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(log_entries)} total events ({len(recent)} shown){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


# Webhook handler for serve.py integration
def handle_webhook_request(cfg: FreqConfig, name: str, token: str,
                           payload: bytes = b"", signature: str = "") -> dict:
    """Handle an inbound webhook request. Called by serve.py."""
    hooks = _load_hooks(cfg)
    hook = next((h for h in hooks if h["name"] == name), None)

    if not hook:
        return {"error": f"Unknown webhook: {name}", "status": 404}

    if not hook.get("enabled", True):
        return {"error": f"Webhook '{name}' is disabled", "status": 403}

    # Verify token
    if hook.get("token") and hook["token"] != token:
        return {"error": "Invalid token", "status": 401}

    # Verify signature if secret is configured
    if hook.get("secret") and not _verify_signature(payload, signature, hook["secret"]):
        return {"error": "Invalid signature", "status": 401}

    # Execute command
    command = hook["command"]
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=120,
        )
        exit_code = result.returncode
    except (subprocess.TimeoutExpired, Exception) as e:
        exit_code = 1

    # Update fire count
    hook["fire_count"] = hook.get("fire_count", 0) + 1
    hook["last_fired"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    _save_hooks(cfg, hooks)

    # Log
    log_entries = _load_log(cfg)
    log_entries.append({
        "webhook": name, "source": "http",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "command": command, "exit_code": exit_code,
    })
    _save_log(cfg, log_entries)

    return {"ok": exit_code == 0, "exit_code": exit_code, "webhook": name}
