# Security Policy

## Reporting Vulnerabilities

If you find a security vulnerability in PVE FREQ, please report it through [GitHub's private vulnerability reporting](https://github.com/Low-Freq-Labs/pve-freq/security/advisories/new).

Do not open a public issue for security vulnerabilities.

## Scope

Security-relevant areas in FREQ:

- **Vault** (`freq/modules/vault.py`) — AES-256-CBC encrypted credential storage in `data/vault/`
- **SSH key management** (`freq/core/ssh.py`, `freq/modules/fleet.py`) — fleet-wide SSH key deployment and rotation
- **Fleet access** (`freq/modules/init_cmd.py`) — service account creation and SSH key distribution
- **RBAC** (`freq/modules/users.py`) — role-based access control (viewer/operator/admin/protected)
- **Fleet boundaries** (`freq/core/types.py`) — permission tiers controlling what actions are allowed per VM category

## Design Principles

- **Credentials by path, never inline.** SSH passwords use `sshpass -f /path/to/file`, never command-line arguments. Vault keys are read from files, never echoed.
- **Vault encryption.** All stored credentials use AES-256-CBC encryption. The vault master key is generated during `freq init`.
- **Restrictive file permissions.** `data/vault/` and `data/keys/` are `chmod 600`. The installer enforces this.
- **No credential logging.** The logging system (`freq/core/log.py`) never logs credential values, vault contents, or SSH passwords.
- **No network exfiltration.** FREQ never phones home, transmits telemetry, or contacts external services without explicit user action. It works fully offline.

## What FREQ Stores

| Location | Contents | Permissions |
|----------|----------|-------------|
| `data/vault/` | AES-256-CBC encrypted credentials | 600 |
| `data/keys/` | SSH keys for fleet access | 600 |
| `conf/freq.toml` | Configuration (no secrets) | 644 |
| `conf/hosts.conf` | Fleet host IPs and labels | 644 |

## What FREQ Never Does

- Stores passwords in configuration files
- Logs credentials or vault contents
- Transmits credentials over unencrypted channels
- Runs with more privileges than necessary (commands use `sudo` only when required)
- Includes credentials in error messages or stack traces
