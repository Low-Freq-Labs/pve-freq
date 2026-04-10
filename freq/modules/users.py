"""User and RBAC management for FREQ.

Domain: freq user <list|new-user|passwd|roles|promote|demote|install-user>

Fleet-wide user management with role-based access control. Four roles:
viewer (read-only), operator (run commands), admin (full access), protected
(system accounts, cannot be demoted). Users defined centrally, deployed
across the fleet via SSH.

Replaces: Manual useradd scripts, Ansible user playbooks,
          FreeIPA ($0 but massive infrastructure overhead)

Architecture:
    - User definitions in freq.toml [users] or legacy conf/users.conf
    - Fleet deployment via parallel SSH (useradd, usermod, passwd)
    - Role enforcement at CLI dispatch level (checked before command exec)
    - Validation via freq/core/validate.py (username format, role validity)

Design decisions:
    - Central definition, fleet deployment. Users are defined once in FREQ
      config and pushed to hosts. No per-host user management.
"""

import getpass
import os
import re
import shlex

from freq.core import fmt
from freq.core import validate
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run_many as ssh_run_many, result_for

# User management timeouts
USER_CMD_TIMEOUT = 15


# --- User Data ---


def _load_users(cfg: FreqConfig) -> list:
    """Load users. Prefers freq.toml [users], then users.conf, then roles.conf."""
    # TOML users take priority if defined
    if cfg._toml_users:
        return list(cfg._toml_users)
    # Primary: load from users.conf (space-delimited: USERNAME ROLE [GROUPS])
    users = []
    path = os.path.join(cfg.conf_dir, "users.conf")
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    users.append(
                        {
                            "username": parts[0],
                            "role": parts[1],
                            "groups": parts[2] if len(parts) > 2 else "",
                        }
                    )
    except FileNotFoundError:
        pass
    if users:
        return users
    # Fallback: load from roles.conf (colon-delimited: USERNAME:ROLE)
    # Init writes roles.conf but not users.conf — this bridges the gap.
    roles_path = os.path.join(cfg.conf_dir, "roles.conf")
    try:
        with open(roles_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    parts = line.split(":", 1)
                    users.append(
                        {"username": parts[0].strip(), "role": parts[1].strip(), "groups": ""}
                    )
    except FileNotFoundError:
        pass
    return users


def _save_users(cfg: FreqConfig, users: list) -> bool:
    """Save users to users.conf."""
    path = os.path.join(cfg.conf_dir, "users.conf")
    try:
        with open(path, "w") as f:
            f.write("# FREQ Users — USERNAME ROLE [GROUPS]\n")
            for u in sorted(users, key=lambda x: x["username"]):
                groups = u.get("groups", "")
                if groups:
                    f.write(f"{u['username']} {u['role']} {groups}\n")
                else:
                    f.write(f"{u['username']} {u['role']}\n")
        return True
    except OSError:
        return False


def _valid_username(username: str) -> bool:
    """Check if a username is valid (alphanumeric, hyphens, underscores, 1-32 chars)."""
    return bool(re.match(r"^[a-z_][a-z0-9_-]{0,31}$", username))


ROLE_HIERARCHY = ["viewer", "operator", "admin", "protected"]


def _role_level(role: str) -> int:
    """Get numeric level for a role."""
    try:
        return ROLE_HIERARCHY.index(role.lower())
    except ValueError:
        return 0


# --- Commands ---


def cmd_users(cfg: FreqConfig, pack, args) -> int:
    """List all FREQ users."""
    fmt.header("Users")
    fmt.blank()

    users = _load_users(cfg)
    if not users:
        fmt.line(f"{fmt.C.YELLOW}No users registered.{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Add users with: freq new-user <username>{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    fmt.table_header(
        ("USERNAME", 20),
        ("ROLE", 12),
        ("GROUPS", 24),
    )

    role_colors = {
        "admin": fmt.C.RED,
        "operator": fmt.C.YELLOW,
        "viewer": fmt.C.GREEN,
        "protected": fmt.C.PURPLE,
    }

    for u in users:
        role = u["role"]
        color = role_colors.get(role.lower(), fmt.C.GRAY)
        fmt.table_row(
            (f"{fmt.C.BOLD}{u['username']}{fmt.C.RESET}", 20),
            (f"{color}{role}{fmt.C.RESET}", 12),
            (f"{fmt.C.DIM}{u.get('groups', '')}{fmt.C.RESET}", 24),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}{len(users)} user(s){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def cmd_new_user(cfg: FreqConfig, pack, args) -> int:
    """Create a new FREQ user."""
    username = getattr(args, "username", None)
    if not username:
        try:
            username = input(f"  {fmt.C.CYAN}Username:{fmt.C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1

    if not username or not _valid_username(username):
        fmt.error(f"Invalid username: {username}")
        return 1

    fmt.header(f"New User: {username}")
    fmt.blank()

    users = _load_users(cfg)
    if any(u["username"] == username for u in users):
        fmt.error(f"User '{username}' already exists.")
        fmt.blank()
        fmt.footer()
        return 1

    # Default role
    role = getattr(args, "role", None) or "operator"
    if role not in ROLE_HIERARCHY:
        fmt.error(f"Invalid role: {role}. Valid: {', '.join(ROLE_HIERARCHY)}")
        return 1

    users.append({"username": username, "role": role, "groups": ""})

    if _save_users(cfg, users):
        fmt.step_ok(f"User '{username}' created with role '{role}'")
        logger.info(f"user created: {username} ({role})")
    else:
        fmt.step_fail("Failed to save user.")
        return 1

    fmt.blank()
    fmt.line(f"{fmt.C.GRAY}Deploy to fleet with: freq install-user {username}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def cmd_roles(cfg: FreqConfig, pack, args) -> int:
    """Show FREQ RBAC roles."""
    fmt.header("Roles")
    fmt.blank()

    roles = [
        ("viewer", "Read-only access. Can view fleet status, host info, and logs."),
        ("operator", "Operational access. Can run commands, manage VMs, deploy keys."),
        ("admin", "Full access. Can manage users, vault, configuration, and infrastructure."),
        ("protected", "System accounts. Cannot be modified or demoted."),
    ]

    for role, desc in roles:
        color = {
            "viewer": fmt.C.GREEN,
            "operator": fmt.C.YELLOW,
            "admin": fmt.C.RED,
            "protected": fmt.C.PURPLE,
        }.get(role, fmt.C.GRAY)

        fmt.line(f"  {color}{fmt.C.BOLD}{role:<12}{fmt.C.RESET} {desc}")

    fmt.blank()

    # Show current users per role
    users = _load_users(cfg)
    if users:
        fmt.divider("Current Assignments")
        fmt.blank()
        for role, _ in roles:
            role_users = [u["username"] for u in users if u["role"] == role]
            if role_users:
                fmt.line(f"  {role}: {', '.join(role_users)}")
        fmt.blank()

    fmt.footer()
    return 0


def cmd_promote(cfg: FreqConfig, pack, args) -> int:
    """Promote a user to the next role level."""
    username = getattr(args, "username", None)
    if not username:
        fmt.error("Usage: freq promote <username>")
        return 1

    users = _load_users(cfg)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        fmt.error(f"User not found: {username}")
        return 1

    current_level = _role_level(user["role"])
    if user["role"] == "protected":
        fmt.error(f"Cannot promote protected user '{username}'.")
        return 1
    if current_level >= _role_level("admin"):
        fmt.error(f"User '{username}' is already at maximum role (admin).")
        return 1

    new_role = ROLE_HIERARCHY[current_level + 1]
    old_role = user["role"]
    user["role"] = new_role

    if _save_users(cfg, users):
        fmt.success(f"{username}: {old_role} -> {new_role}")
        logger.info(f"user promoted: {username} {old_role} -> {new_role}")
        return 0
    else:
        fmt.error("Failed to save.")
        return 1


def cmd_demote(cfg: FreqConfig, pack, args) -> int:
    """Demote a user to the previous role level."""
    username = getattr(args, "username", None)
    if not username:
        fmt.error("Usage: freq demote <username>")
        return 1

    users = _load_users(cfg)
    user = next((u for u in users if u["username"] == username), None)
    if not user:
        fmt.error(f"User not found: {username}")
        return 1

    if user["role"] == "protected":
        fmt.error(f"Cannot demote protected user '{username}'.")
        return 1

    current_level = _role_level(user["role"])
    if current_level <= 0:
        fmt.error(f"User '{username}' is already at minimum role (viewer).")
        return 1

    new_role = ROLE_HIERARCHY[current_level - 1]
    old_role = user["role"]
    user["role"] = new_role

    if _save_users(cfg, users):
        fmt.success(f"{username}: {old_role} -> {new_role}")
        logger.info(f"user demoted: {username} {old_role} -> {new_role}")
        return 0
    else:
        fmt.error("Failed to save.")
        return 1


def cmd_passwd(cfg: FreqConfig, pack, args) -> int:
    """Change a user's password on fleet hosts."""
    username = getattr(args, "username", None)
    if not username:
        fmt.error("Usage: freq passwd <username>")
        return 1

    if not validate.username(username):
        fmt.error(f"Invalid username: {username}")
        return 1

    fmt.header(f"Change Password: {username}")
    fmt.blank()

    try:
        new_pass = getpass.getpass(f"  New password for '{username}': ")
        confirm = getpass.getpass(f"  Confirm password: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    if new_pass != confirm:
        fmt.error("Passwords do not match.")
        return 1

    if len(new_pass) < 8:
        fmt.error("Password must be at least 8 characters.")
        return 1

    # Deploy to all hosts
    hosts = cfg.hosts
    if not hosts:
        fmt.error("No hosts registered.")
        return 1

    fmt.line(f"{fmt.C.BOLD}Changing password on {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    # Use chpasswd via SSH (requires sudo, full path for non-login shells)
    escaped_pass = new_pass.replace("'", "'\\''")
    safe_user = shlex.quote(username)
    results = ssh_run_many(
        hosts=hosts,
        command=f"echo {safe_user}':'{shlex.quote(new_pass)} | sudo /usr/sbin/chpasswd",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=USER_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    ok = 0
    fail = 0
    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode == 0:
            ok += 1
            fmt.step_ok(f"{h.label}")
        else:
            fail += 1
            err = r.stderr[:40] if r else "no response"
            fmt.step_fail(f"{h.label}: {err}")

    fmt.blank()
    fmt.line(f"  {fmt.C.GREEN}{ok}{fmt.C.RESET} updated  {fmt.C.RED}{fail}{fmt.C.RESET} failed")
    fmt.blank()
    fmt.footer()
    return 0 if fail == 0 else 1


def cmd_install_user(cfg: FreqConfig, pack, args) -> int:
    """Create a user account across all fleet hosts."""
    username = getattr(args, "username", None)
    if not username:
        fmt.error("Usage: freq install-user <username>")
        return 1

    if not validate.username(username):
        fmt.error(f"Invalid username: {username}")
        return 1

    fmt.header(f"Install User: {username}")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.error("No hosts registered.")
        return 1

    fmt.line(f"{fmt.C.BOLD}Creating '{username}' on {len(hosts)} hosts...{fmt.C.RESET}")
    fmt.blank()

    # Create user with home directory
    safe_user = shlex.quote(username)
    results = ssh_run_many(
        hosts=hosts,
        command=f"id {safe_user} >/dev/null 2>&1 && echo 'EXISTS' || useradd -m -s /bin/bash {safe_user}",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=USER_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=True,
    )

    ok = 0
    exists = 0
    fail = 0
    for h in hosts:
        r = result_for(results, h)
        if r and r.returncode == 0:
            if "EXISTS" in (r.stdout or ""):
                exists += 1
                fmt.step_info(f"{h.label}: already exists")
            else:
                ok += 1
                fmt.step_ok(f"{h.label}: created")
        else:
            fail += 1
            err = r.stderr[:40] if r else "no response"
            fmt.step_fail(f"{h.label}: {err}")

    fmt.blank()
    fmt.line(
        f"  {fmt.C.GREEN}{ok}{fmt.C.RESET} created  "
        f"{fmt.C.CYAN}{exists}{fmt.C.RESET} existing  "
        f"{fmt.C.RED}{fail}{fmt.C.RESET} failed"
    )
    fmt.blank()
    fmt.footer()
    return 0 if fail == 0 else 1
