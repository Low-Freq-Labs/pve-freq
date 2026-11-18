"""User authorization registry storage, policy, and validation.

Domain: freq user <list|create|promote|demote>
Replaces: shared users.conf and role primitives formerly owned by
freq.modules.users.
"""

import os
import re
import tempfile

from freq.core import log as logger
from freq.core.config import FreqConfig


def _load_users(cfg: FreqConfig) -> list:
    """Load users. Prefers freq.toml [users], then users.conf, then roles.conf."""
    if cfg._toml_users:
        return list(cfg._toml_users)
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


def _serialize_users(users: list) -> str:
    lines = ["# FREQ Users — USERNAME ROLE [GROUPS]"]
    for user in sorted(users, key=lambda item: item["username"]):
        groups = user.get("groups", "")
        suffix = f" {groups}" if groups else ""
        lines.append(f"{user['username']} {user['role']}{suffix}")
    return "\n".join(lines) + "\n"


def _first_save_failure(first, later):
    """First Control, then MemoryError, then ordinary received failure."""
    if later is None:
        return first
    if first is None or issubclass(type(first), Exception) and (
            not issubclass(type(later), Exception)
            or not issubclass(type(first), MemoryError)
            and issubclass(type(later), MemoryError)):
        return later
    return first


def _save_users_error(cfg: FreqConfig, users: list) -> str:
    """Atomically save a private users.conf and return an error string on failure."""
    from freq.core.read_source_epoch import source_write

    body_failure = descriptor_failure = unlink_failure = None
    with source_write():
        path = os.path.join(cfg.conf_dir, "users.conf")
        tmp_path = ""
        fd = -1
        try:
            os.makedirs(cfg.conf_dir, mode=0o700, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".users.conf.", dir=cfg.conf_dir)
            os.fchmod(fd, 0o600)
            file_body_failure = None
            try:
                with os.fdopen(fd, "w") as file_obj:
                    fd = -1
                    try:
                        file_obj.write(_serialize_users(users))
                        file_obj.flush()
                        os.fsync(file_obj.fileno())
                    except BaseException as failure:
                        # Preserve the body before the original context exits;
                        # rethrow so __exit__ receives its original raw failure.
                        file_body_failure = failure
                        raise
            except BaseException as failure:
                raise _first_save_failure(file_body_failure, failure) from None
            os.replace(tmp_path, path)
            tmp_path = ""
            try:
                if hasattr(os, "O_DIRECTORY"):
                    directory_fd = os.open(cfg.conf_dir, os.O_RDONLY | os.O_DIRECTORY)
                    directory_failure = directory_close_failure = None
                    try:
                        os.fsync(directory_fd)
                    except BaseException as failure:
                        directory_failure = failure
                    try:
                        os.close(directory_fd)
                    except BaseException as failure:
                        directory_close_failure = failure
                    first = _first_save_failure(directory_failure, directory_close_failure)
                    if first is not None:
                        raise first from None
            except OSError as exc:
                logger.warn(f"users.conf committed but directory sync failed at {path}: {exc}")
        except BaseException as failure:
            body_failure = failure
        # Independent known outer duties precede classification and logging.
        # Losing a close return never licenses a retry or skipping unlink.
        if fd >= 0:
            try:
                os.close(fd)
            except BaseException as failure:
                descriptor_failure = failure
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            except BaseException as failure:
                unlink_failure = failure
        first = _first_save_failure(body_failure, descriptor_failure)
        first = _first_save_failure(first, unlink_failure)
        if descriptor_failure is not None or unlink_failure is not None:
            # An uncertain cleanup cannot become an ordinary returned string.
            raise first from None
        if body_failure is not None:
            if (not issubclass(type(body_failure), Exception)
                    or issubclass(type(body_failure), MemoryError)):
                raise body_failure from None
            logger.error(f"failed to save users.conf at {path}: {body_failure}")
            return str(body_failure)
        return ""


def _save_users(cfg: FreqConfig, users: list) -> bool:
    """Save users to users.conf."""
    return not _save_users_error(cfg, users)


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
