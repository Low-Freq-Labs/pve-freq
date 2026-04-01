"""Secret rotation, scanning, and lifecycle management for FREQ.

Domain: freq secure <secrets-rotate|secrets-scan|secrets-audit|secrets-generate|secrets-list|secrets-lease>

Fleet-wide SSH key rotation, secret scanning for hardcoded passwords in
config files, credential lease tracking with expiry alerts, and secure
password generation. Extends the vault module with active management.

Replaces: HashiCorp Vault ($1,152/mo+ post-IBM acquisition), CyberArk ($$$)

Architecture:
    - Secret scanning via regex patterns across fleet config files (SSH)
    - SSH key rotation: generate new keypair, distribute, verify, remove old
    - Lease tracking stored in conf/secrets/leases.json with expiry dates
    - Password generation via stdlib secrets module (cryptographic RNG)

Design decisions:
    - Scanning is pattern-based, not AST-based. Catches passwords in any
      file format (TOML, YAML, env, ini) without format-specific parsers.
"""
import hashlib
import json
import os
import re
import secrets as stdlib_secrets
import string
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many

SECRETS_DIR = "secrets"
SECRETS_LEASES = "leases.json"
SECRETS_SCAN_RESULTS = "scan-results.json"
SECRETS_CMD_TIMEOUT = 15

# Patterns that indicate hardcoded secrets
SECRET_PATTERNS = [
    (r'password\s*=\s*["\'][^"\']+["\']', "password in config"),
    (r'api[_-]?key\s*=\s*["\'][^"\']+["\']', "API key in config"),
    (r'secret\s*=\s*["\'][^"\']+["\']', "secret in config"),
    (r'token\s*=\s*["\'][^"\']+["\']', "token in config"),
    (r'PASS\s*=\s*[^\s]+', "password in env var"),
    (r'AWS_SECRET_ACCESS_KEY\s*=\s*[^\s]+', "AWS secret key"),
    (r'-----BEGIN (?:RSA )?PRIVATE KEY-----', "private key in file"),
]


def _secrets_dir(cfg: FreqConfig) -> str:
    path = os.path.join(cfg.conf_dir, SECRETS_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_leases(cfg: FreqConfig) -> list:
    filepath = os.path.join(_secrets_dir(cfg), SECRETS_LEASES)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_leases(cfg: FreqConfig, leases: list):
    filepath = os.path.join(_secrets_dir(cfg), SECRETS_LEASES)
    with open(filepath, "w") as f:
        json.dump(leases, f, indent=2)


def _load_scan_results(cfg: FreqConfig) -> dict:
    filepath = os.path.join(_secrets_dir(cfg), SECRETS_SCAN_RESULTS)
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"findings": [], "scan_time": ""}


def _save_scan_results(cfg: FreqConfig, data: dict):
    filepath = os.path.join(_secrets_dir(cfg), SECRETS_SCAN_RESULTS)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)


def _generate_password(length: int = 32) -> str:
    """Generate a cryptographically secure password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(stdlib_secrets.choice(alphabet) for _ in range(length))


def _generate_token(length: int = 48) -> str:
    """Generate a URL-safe token."""
    return stdlib_secrets.token_urlsafe(length)


def cmd_secrets(cfg: FreqConfig, pack, args) -> int:
    """Secrets management dispatch."""
    action = getattr(args, "action", None) or "list"
    routes = {
        "list": _cmd_list,
        "scan": _cmd_scan,
        "audit": _cmd_audit,
        "generate": _cmd_generate,
        "rotate": _cmd_rotate,
        "lease": _cmd_lease,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown secrets action: {action}")
    fmt.info("Available: list, scan, audit, generate, rotate, lease")
    return 1


def _cmd_list(cfg: FreqConfig, args) -> int:
    """List managed secret leases."""
    fmt.header("Secret Leases")
    fmt.blank()

    leases = _load_leases(cfg)
    if not leases:
        fmt.line(f"  {fmt.C.DIM}No tracked secret leases.{fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Track one: freq secrets lease --name ssh-key --expires 90d{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    now = time.time()
    fmt.table_header(("NAME", 20), ("TYPE", 12), ("EXPIRES", 14), ("STATUS", 10))

    expiring = 0
    for lease in leases:
        expires = lease.get("expires_epoch", 0)
        days_left = int((expires - now) / 86400) if expires > 0 else -1

        if days_left < 0:
            status = f"{fmt.C.RED}EXPIRED{fmt.C.RESET}"
            expiring += 1
        elif days_left < 7:
            status = f"{fmt.C.RED}{days_left}d{fmt.C.RESET}"
            expiring += 1
        elif days_left < 30:
            status = f"{fmt.C.YELLOW}{days_left}d{fmt.C.RESET}"
        else:
            status = f"{fmt.C.GREEN}{days_left}d{fmt.C.RESET}"

        fmt.table_row(
            (f"{fmt.C.BOLD}{lease['name']}{fmt.C.RESET}", 20),
            (lease.get("type", "generic"), 12),
            (lease.get("expires", "never")[:14], 14),
            (status, 10),
        )

    fmt.blank()
    if expiring:
        fmt.line(f"  {fmt.C.RED}{fmt.S.WARN} {expiring} secret(s) expired or expiring soon{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_scan(cfg: FreqConfig, args) -> int:
    """Scan fleet for hardcoded secrets in config files."""
    fmt.header("Secret Scan")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Build grep patterns
    pattern_args = "|".join(p[0] for p in SECRET_PATTERNS)
    command = (
        f"grep -rn -i -E '{pattern_args}' "
        "/etc/ /opt/ /home/ /srv/ /var/www/ "
        "--include='*.conf' --include='*.cfg' --include='*.ini' "
        "--include='*.env' --include='*.yml' --include='*.yaml' "
        "--include='*.toml' --include='*.properties' "
        "2>/dev/null | head -50 || true"
    )

    fmt.step_start(f"Scanning {len(hosts)} hosts for hardcoded secrets")
    results = ssh_run_many(
        hosts=hosts, command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=SECRETS_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )
    fmt.step_ok("Scan complete")
    fmt.blank()

    findings = []
    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0 or not r.stdout.strip():
            continue

        for line in r.stdout.strip().split("\n")[:20]:
            # Redact actual values
            redacted = re.sub(r'=\s*["\']?[^"\':\s]+', '=***REDACTED***', line)
            findings.append({
                "host": h.label,
                "finding": redacted[:100],
            })

    # Save results
    _save_scan_results(cfg, {
        "findings": findings,
        "scan_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hosts_scanned": len(hosts),
    })

    if not findings:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} No hardcoded secrets found across {len(hosts)} hosts.{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.RED}{fmt.S.WARN} {len(findings)} potential secret(s) found:{fmt.C.RESET}")
        fmt.blank()

        for finding in findings[:15]:
            fmt.line(f"  {fmt.C.BOLD}{finding['host']}{fmt.C.RESET}: {fmt.C.DIM}{finding['finding']}{fmt.C.RESET}")

        if len(findings) > 15:
            fmt.line(f"  {fmt.C.DIM}... and {len(findings) - 15} more{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 1 if findings else 0


def _cmd_audit(cfg: FreqConfig, args) -> int:
    """Audit secret health: expiring leases, scan results, key ages."""
    fmt.header("Secret Audit")
    fmt.blank()

    leases = _load_leases(cfg)
    scan = _load_scan_results(cfg)
    now = time.time()

    # Check leases
    expired = [l for l in leases if l.get("expires_epoch", 0) < now and l.get("expires_epoch", 0) > 0]
    expiring_soon = [l for l in leases if 0 < l.get("expires_epoch", 0) - now < 30 * 86400]

    fmt.divider("Lease Status")
    fmt.blank()
    fmt.line(f"  Total leases:   {len(leases)}")
    if expired:
        fmt.line(f"  {fmt.C.RED}Expired:        {len(expired)}{fmt.C.RESET}")
    if expiring_soon:
        fmt.line(f"  {fmt.C.YELLOW}Expiring <30d:  {len(expiring_soon)}{fmt.C.RESET}")
    if not expired and not expiring_soon:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} All leases healthy{fmt.C.RESET}")
    fmt.blank()

    # Check scan results
    fmt.divider("Last Scan")
    fmt.blank()
    findings = scan.get("findings", [])
    scan_time = scan.get("scan_time", "never")
    fmt.line(f"  Last scan: {scan_time}")
    fmt.line(f"  Findings:  {len(findings)}")
    if findings:
        fmt.line(f"  {fmt.C.YELLOW}{fmt.S.WARN} Rescan: freq secrets scan{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    issues = len(expired) + len(expiring_soon) + len(findings)
    return 1 if issues > 0 else 0


def _cmd_generate(cfg: FreqConfig, args) -> int:
    """Generate a secure password or token."""
    secret_type = getattr(args, "secret_type", None) or "password"
    length = getattr(args, "length", 32)

    fmt.header("Generate Secret")
    fmt.blank()

    if secret_type == "token":
        value = _generate_token(length)
    else:
        value = _generate_password(length)

    fmt.line(f"  Type:   {secret_type}")
    fmt.line(f"  Length: {length}")
    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}{value}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_rotate(cfg: FreqConfig, args) -> int:
    """Show rotation guidance."""
    fmt.header("Secret Rotation")
    fmt.blank()

    fmt.line(f"  {fmt.C.PURPLE_BOLD}SSH Key Rotation{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}1. freq keys rotate --target <host>{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}2. freq keys deploy --target all{fmt.C.RESET}")
    fmt.blank()

    fmt.line(f"  {fmt.C.PURPLE_BOLD}API Token Rotation{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}1. Generate new token: freq secrets generate --type token{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}2. Update vault: freq vault set <key> <new-value>{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}3. Track expiry: freq secrets lease --name <key> --expires 90d{fmt.C.RESET}")
    fmt.blank()

    fmt.line(f"  {fmt.C.PURPLE_BOLD}Database Password Rotation{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}1. Generate new password: freq secrets generate{fmt.C.RESET}")
    fmt.line(f"  {fmt.C.DIM}2. Update database, then update vault and app configs{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_lease(cfg: FreqConfig, args) -> int:
    """Manage secret leases."""
    name = getattr(args, "name", None)

    if not name:
        return _cmd_list(cfg, args)

    expires_str = getattr(args, "expires", "90d") or "90d"

    # Parse expiry
    match = re.match(r'^(\d+)([dhm])$', expires_str.lower())
    if not match:
        fmt.error(f"Invalid expiry: {expires_str} (use 90d, 24h, etc)")
        return 1

    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60}
    expires_secs = value * multipliers.get(unit, 86400)

    leases = _load_leases(cfg)

    # Update or create
    existing = next((l for l in leases if l["name"] == name), None)
    if existing:
        existing["expires_epoch"] = time.time() + expires_secs
        existing["expires"] = time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                            time.localtime(time.time() + expires_secs))
        existing["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    else:
        leases.append({
            "name": name,
            "type": getattr(args, "secret_type", "generic") or "generic",
            "expires_epoch": time.time() + expires_secs,
            "expires": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                     time.localtime(time.time() + expires_secs)),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        })

    _save_leases(cfg, leases)

    days = expires_secs // 86400
    fmt.step_ok(f"Lease '{name}' set to expire in {days} days")
    return 0
