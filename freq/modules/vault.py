"""Encrypted credential vault for FREQ.

AES-256-CBC encryption via OpenSSL. Key derived from /etc/machine-id.
Format: HOST|KEY|VALUE (pipe-delimited), encrypted at rest.

Compatible with v1.0.0 vault files — same algorithm, same key derivation.
"""
import hashlib
import os
import subprocess
from pathlib import Path

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig


def _vault_key() -> str:
    """Derive encryption key from machine-id (SHA256 hex digest).

    Same derivation as v1.0.0 bash: cat /etc/machine-id | openssl dgst -sha256
    """
    for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
        try:
            with open(path) as f:
                machine_id = f.read().strip()
                return hashlib.sha256(machine_id.encode()).hexdigest()
        except FileNotFoundError:
            continue
    return ""


def _encrypt(plaintext: str, key: str, vault_path: str) -> bool:
    """Encrypt plaintext and write to vault file."""
    try:
        r = subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2",
             "-pass", f"pass:{key}", "-out", vault_path],
            input=plaintext.encode(),
            capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            os.chmod(vault_path, 0o600)
            return True
        logger.error(f"vault encrypt failed: {r.stderr.decode()}")
        return False
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error(f"vault encrypt error: {e}")
        return False


def _decrypt(key: str, vault_path: str) -> str:
    """Decrypt vault file and return plaintext."""
    if not os.path.exists(vault_path):
        return ""
    try:
        r = subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-d", "-salt", "-pbkdf2",
             "-pass", f"pass:{key}", "-in", vault_path],
            capture_output=True, timeout=10,
        )
        if r.returncode == 0:
            return r.stdout.decode()
        return ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def _parse_entries(plaintext: str) -> list:
    """Parse vault plaintext into list of (host, key, value) tuples."""
    entries = []
    for line in plaintext.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) == 3:
            entries.append((parts[0], parts[1], parts[2]))
    return entries


def _serialize_entries(entries: list) -> str:
    """Serialize entries back to pipe-delimited format."""
    lines = ["# FREQ Vault — encrypted credential store"]
    for host, key, value in sorted(entries, key=lambda e: (e[0], e[1])):
        lines.append(f"{host}|{key}|{value}")
    return "\n".join(lines) + "\n"


def vault_init(cfg: FreqConfig) -> bool:
    """Initialize an empty vault."""
    key = _vault_key()
    if not key:
        return False

    vault_dir = cfg.vault_dir
    vault_path = cfg.vault_file

    os.makedirs(vault_dir, mode=0o700, exist_ok=True)
    return _encrypt("# FREQ Vault — initialized\n", key, vault_path)


def vault_set(cfg: FreqConfig, host: str, cred_key: str, value: str) -> bool:
    """Store a credential in the vault."""
    key = _vault_key()
    if not key:
        return False

    plaintext = _decrypt(key, cfg.vault_file)
    entries = _parse_entries(plaintext)

    # Remove existing entry with same host+key
    entries = [(h, k, v) for h, k, v in entries if not (h == host and k == cred_key)]
    entries.append((host, cred_key, value))

    return _encrypt(_serialize_entries(entries), key, cfg.vault_file)


def vault_get(cfg: FreqConfig, host: str, cred_key: str) -> str:
    """Retrieve a credential from the vault.

    Tries exact host match first, falls back to DEFAULT.
    """
    key = _vault_key()
    if not key:
        return ""

    plaintext = _decrypt(key, cfg.vault_file)
    entries = _parse_entries(plaintext)

    # Exact match
    for h, k, v in entries:
        if h == host and k == cred_key:
            return v

    # Fallback to DEFAULT
    for h, k, v in entries:
        if h == "DEFAULT" and k == cred_key:
            return v

    return ""


def vault_delete(cfg: FreqConfig, host: str, cred_key: str) -> bool:
    """Delete a credential from the vault."""
    key = _vault_key()
    if not key:
        return False

    plaintext = _decrypt(key, cfg.vault_file)
    entries = _parse_entries(plaintext)
    new_entries = [(h, k, v) for h, k, v in entries if not (h == host and k == cred_key)]

    if len(new_entries) == len(entries):
        return False  # Nothing was deleted

    return _encrypt(_serialize_entries(new_entries), key, cfg.vault_file)


def vault_list(cfg: FreqConfig) -> list:
    """List all vault entries (values masked for passwords)."""
    key = _vault_key()
    if not key:
        return []

    plaintext = _decrypt(key, cfg.vault_file)
    return _parse_entries(plaintext)


def cmd_vault(cfg: FreqConfig, pack, args) -> int:
    """Vault command dispatcher."""
    action = getattr(args, "action", None)

    if not action:
        fmt.error("Usage: freq vault <init|set|get|delete|list> [key] [value]")
        fmt.info("  freq vault init                    Initialize vault")
        fmt.info("  freq vault list                    List stored credentials")
        fmt.info("  freq vault set <key> <value>       Store a credential")
        fmt.info("  freq vault get <key>               Retrieve a credential")
        fmt.info("  freq vault delete <key>            Delete a credential")
        return 1

    if action == "init":
        return _vault_cmd_init(cfg)
    elif action == "list":
        return _vault_cmd_list(cfg)
    elif action == "set":
        return _vault_cmd_set(cfg, args)
    elif action == "get":
        return _vault_cmd_get(cfg, args)
    elif action == "delete":
        return _vault_cmd_delete(cfg, args)
    else:
        fmt.error(f"Unknown vault action: {action}")
        return 1


def _vault_cmd_init(cfg: FreqConfig) -> int:
    """Initialize the vault."""
    fmt.header("Vault Init")
    fmt.blank()

    if os.path.exists(cfg.vault_file):
        fmt.line(f"{fmt.C.YELLOW}Vault already exists at: {cfg.vault_file}{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Use 'freq vault list' to see contents.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.step_start("Initializing encrypted vault")
    if vault_init(cfg):
        fmt.step_ok(f"Vault created at {cfg.vault_file}")
        logger.info("vault initialized", path=cfg.vault_file)
    else:
        fmt.step_fail("Failed to initialize vault")
        fmt.blank()
        fmt.footer()
        return 1

    fmt.blank()
    fmt.footer()
    return 0


def _vault_cmd_list(cfg: FreqConfig) -> int:
    """List all vault entries."""
    fmt.header("Vault")
    fmt.blank()

    if not os.path.exists(cfg.vault_file):
        fmt.line(f"{fmt.C.YELLOW}Vault not initialized. Run: freq vault init{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    entries = vault_list(cfg)
    if not entries:
        fmt.line(f"{fmt.C.GRAY}Vault is empty.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("HOST", 16),
        ("KEY", 24),
        ("VALUE", 20),
    )

    for host, key, value in entries:
        # Mask passwords
        if "pass" in key.lower() or "secret" in key.lower() or "token" in key.lower():
            display_value = "********"
        else:
            display_value = value if len(value) <= 20 else value[:17] + "..."

        fmt.table_row(
            (host, 16),
            (f"{fmt.C.CYAN}{key}{fmt.C.RESET}", 24),
            (f"{fmt.C.DIM}{display_value}{fmt.C.RESET}", 20),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}{len(entries)} credential(s) stored{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _vault_cmd_set(cfg: FreqConfig, args) -> int:
    """Store a credential."""
    cred_key = getattr(args, "key", None)
    value = getattr(args, "value", None)
    host = getattr(args, "host", None) or "DEFAULT"

    if not cred_key:
        fmt.error("Usage: freq vault set <key> <value> [--host <host>]")
        return 1

    # Prompt for value if not provided (for passwords)
    if not value:
        import getpass
        try:
            value = getpass.getpass(f"  Value for '{cred_key}': ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if not value:
            fmt.error("Value cannot be empty.")
            return 1

    # Ensure vault exists
    if not os.path.exists(cfg.vault_file):
        vault_init(cfg)

    if vault_set(cfg, host, cred_key, value):
        fmt.success(f"Stored: {host}|{cred_key}")
        logger.info(f"vault set: {host}|{cred_key}")
        return 0
    else:
        fmt.error("Failed to store credential.")
        return 1


def _vault_cmd_get(cfg: FreqConfig, args) -> int:
    """Retrieve a credential."""
    cred_key = getattr(args, "key", None)
    host = getattr(args, "host", None) or "DEFAULT"

    if not cred_key:
        fmt.error("Usage: freq vault get <key> [--host <host>]")
        return 1

    value = vault_get(cfg, host, cred_key)
    if value:
        print(value)
        return 0
    else:
        fmt.error(f"Not found: {host}|{cred_key}")
        return 1


def _vault_cmd_delete(cfg: FreqConfig, args) -> int:
    """Delete a credential."""
    cred_key = getattr(args, "key", None)
    host = getattr(args, "host", None) or "DEFAULT"

    if not cred_key:
        fmt.error("Usage: freq vault delete <key> [--host <host>]")
        return 1

    if vault_delete(cfg, host, cred_key):
        fmt.success(f"Deleted: {host}|{cred_key}")
        logger.info(f"vault delete: {host}|{cred_key}")
        return 0
    else:
        fmt.error(f"Not found: {host}|{cred_key}")
        return 1
