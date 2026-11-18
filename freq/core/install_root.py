"""Install-root access invariants shared by installer, init, and doctor."""

import grp
import os
import pwd
import stat
import sys
from pathlib import Path


def _identity(username: str) -> tuple[int, set[int]]:
    account = pwd.getpwnam(username)
    gids = {account.pw_gid}
    for group in grp.getgrall():
        if username in group.gr_mem:
            gids.add(group.gr_gid)
    return account.pw_uid, gids


def _permission_class(mode: int, owner: int, group: int, uid: int, gids: set[int]) -> int:
    if uid == owner:
        return (mode >> 6) & 0o7
    if group in gids:
        return (mode >> 3) & 0o7
    return mode & 0o7


def runtime_path_access_issue(path: str, username: str) -> str:
    """Return why ``username`` cannot traverse/read ``path``, or an empty string."""
    try:
        uid, gids = _identity(username)
    except KeyError:
        # A pre-init/manual profile can legitimately precede account creation.
        # The installer enforces portable access independently; doctor cannot
        # evaluate a kernel identity that does not exist yet.
        return ""

    target = Path(path).resolve(strict=False)
    current = Path(target.anchor)
    components = [current]
    for part in target.parts[1:]:
        current /= part
        components.append(current)

    for component in components:
        try:
            info = component.stat()
        except OSError as exc:
            return f"cannot inspect {component}: {exc}"
        if not stat.S_ISDIR(info.st_mode):
            return f"path component is not a directory: {component}"
        granted = _permission_class(
            stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid, uid, gids
        )
        required = 0o5 if component == target else 0o1
        if granted & required != required:
            action = "read and traverse" if component == target else "traverse"
            return f"runtime account {username} cannot {action} {component}"
    return ""


def _portable_path_access_issue(path: str) -> str:
    """Check access for a service identity that may not exist during install."""
    target = Path(path).resolve(strict=False)
    current = Path(target.anchor)
    components = [current]
    for part in target.parts[1:]:
        current /= part
        components.append(current)
    for component in components:
        try:
            info = component.stat()
        except OSError as exc:
            return f"cannot inspect {component}: {exc}"
        if not stat.S_ISDIR(info.st_mode):
            return f"path component is not a directory: {component}"
        mode = stat.S_IMODE(info.st_mode)
        required = 0o5 if component == target else 0o1
        if mode & required != required:
            action = "read and traverse" if component == target else "traverse"
            return f"managed service account cannot {action} {component}"
    return ""


def normalize_owned_install_root(path: str) -> None:
    """Make the product-owned root portable across restrictive caller umasks."""
    from freq.core.read_source_epoch import source_write

    with source_write():
        if not os.path.isdir(path):
            raise NotADirectoryError(path)
        os.chmod(path, 0o755)
        issue = _portable_path_access_issue(path)
        if issue:
            raise PermissionError(issue)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python -m freq.core.install_root INSTALL_DIR", file=sys.stderr)
        return 2
    try:
        normalize_owned_install_root(args[0])
    except OSError as exc:
        print(f"install root is not service-accessible: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
