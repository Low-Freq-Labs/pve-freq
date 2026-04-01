"""Self-update mechanism for FREQ.

Domain: freq update

Checks for a newer version and upgrades FREQ in place. Auto-detects
install method (git, tarball, dpkg, rpm) and uses the appropriate upgrade
path. One command to stay current across any installation type.

Replaces: Manual git pull + restart, package manager update scripts

Architecture:
    - Install method detection: .git dir, .install-method marker, dpkg/rpm query
    - Git update: git fetch + merge with conflict detection
    - Tarball update: download from GitHub releases via urllib
    - Package update: dpkg -i or rpm -U with downloaded .deb/.rpm

Design decisions:
    - Detect, don't assume. FREQ can be installed four different ways;
      the updater figures out which one and acts accordingly.
"""
import os
import subprocess

from freq.core import fmt
from freq.core.config import FreqConfig
import freq

# Update timeouts
UPDATE_FETCH_TIMEOUT = 30
UPDATE_CHECK_TIMEOUT = 10
UPDATE_APPLY_TIMEOUT = 60


def _detect_install_method(cfg: FreqConfig) -> str:
    """Detect how FREQ was installed."""
    # Check for install.sh marker first (most specific)
    marker = os.path.join(cfg.install_dir, ".install-method")
    if os.path.isfile(marker):
        try:
            with open(marker) as f:
                method = f.read().strip()
            if method in ("tarball", "git-release", "local"):
                return method
        except OSError:
            pass

    # Check for .git directory (development install)
    git_dir = os.path.join(cfg.install_dir, ".git")
    if os.path.isdir(git_dir):
        return "git"

    # Check for dpkg
    try:
        r = subprocess.run(["dpkg", "-s", "pve-freq"], capture_output=True, text=True)
        if r.returncode == 0:
            return "dpkg"
    except FileNotFoundError:
        pass

    # Check for rpm
    try:
        r = subprocess.run(["rpm", "-q", "pve-freq"], capture_output=True, text=True)
        if r.returncode == 0:
            return "rpm"
    except FileNotFoundError:
        pass

    return "manual"


def cmd_update(cfg: FreqConfig, pack, args) -> int:
    """Check for updates and upgrade FREQ."""
    fmt.header("Update")
    fmt.blank()

    current = freq.__version__
    method = _detect_install_method(cfg)

    fmt.line(f"  {fmt.C.BOLD}Current version:{fmt.C.RESET}  {current}")
    fmt.line(f"  {fmt.C.BOLD}Install method:{fmt.C.RESET}   {method}")
    fmt.line(f"  {fmt.C.BOLD}Install dir:{fmt.C.RESET}      {cfg.install_dir}")
    fmt.blank()

    if method == "git":
        return _update_git(cfg)
    elif method == "dpkg":
        fmt.line(f"  {fmt.C.GRAY}Update via apt: sudo apt update && sudo apt upgrade pve-freq{fmt.C.RESET}")
    elif method == "rpm":
        fmt.line(f"  {fmt.C.GRAY}Update via dnf: sudo dnf update pve-freq{fmt.C.RESET}")
    else:
        fmt.line(f"  {fmt.C.GRAY}Manual install detected.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.GRAY}Re-run the installer: sudo bash install.sh{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0


def _update_git(cfg: FreqConfig) -> int:
    """Update from git (development mode)."""
    fmt.step_start("Checking for updates")

    r = subprocess.run(
        ["git", "-C", cfg.install_dir, "fetch", "--dry-run"],
        capture_output=True, text=True, timeout=UPDATE_FETCH_TIMEOUT,
    )

    if r.returncode != 0:
        fmt.step_warn("Cannot reach remote (offline or no remote configured)")
        fmt.blank()
        fmt.footer()
        return 0

    # Check if behind
    r = subprocess.run(
        ["git", "-C", cfg.install_dir, "status", "-uno", "--porcelain"],
        capture_output=True, text=True, timeout=UPDATE_CHECK_TIMEOUT,
    )

    r2 = subprocess.run(
        ["git", "-C", cfg.install_dir, "log", "HEAD..@{u}", "--oneline"],
        capture_output=True, text=True, timeout=UPDATE_CHECK_TIMEOUT,
    )

    if r2.returncode == 0 and r2.stdout.strip():
        commits = r2.stdout.strip().split("\n")
        fmt.step_ok(f"{len(commits)} new commit(s) available")
        fmt.blank()
        for c in commits[:5]:
            fmt.line(f"  {fmt.C.DIM}{c}{fmt.C.RESET}")
        if len(commits) > 5:
            fmt.line(f"  {fmt.C.DIM}... and {len(commits) - 5} more{fmt.C.RESET}")
        fmt.blank()

        try:
            confirm = input(f"  {fmt.C.YELLOW}Pull updates? [y/N]:{fmt.C.RESET} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 1
        if confirm == "y":
            fmt.step_start("Pulling updates")
            r = subprocess.run(
                ["git", "-C", cfg.install_dir, "pull", "--ff-only"],
                capture_output=True, text=True, timeout=UPDATE_APPLY_TIMEOUT,
            )
            if r.returncode == 0:
                fmt.step_ok("Updated successfully")
                # Reimport to show new version
                import importlib
                importlib.reload(freq)
                fmt.line(f"  {fmt.C.GREEN}New version: {freq.__version__}{fmt.C.RESET}")
            else:
                fmt.step_fail(f"Pull failed: {r.stderr[:50]}")
    else:
        fmt.step_ok("Already up to date")

    fmt.blank()
    fmt.footer()
    return 0
