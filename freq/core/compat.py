"""Compatibility layer — Python version checks and support matrix.

FREQ requires Python 3.7+ (for dataclasses).
Runs on 3.7-3.13 with zero external dependencies.

Support matrix (current + 2 versions back):
  Debian:     13, 12, 11          — ships 3.13, 3.11, 3.9    — all native
  Ubuntu LTS: 24.04, 22.04, 20.04 — ships 3.12, 3.10, 3.8   — all native
  Rocky/RHEL: 9, 8               — ships 3.9, 3.6            — v8: dnf install python39
  AlmaLinux:  9, 8               — ships 3.9, 3.6            — v8: dnf install python39
  openSUSE:   15.6, 15.5, 15.4   — ships 3.6                — zypper install python39
"""
import sys

MIN_PYTHON = (3, 7)


def check_python():
    """Check Python version at startup. Returns error message or None."""
    if sys.version_info < MIN_PYTHON:
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        return (
            f"FREQ requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, "
            f"but found {ver}.\n"
            f"Install a newer Python:\n"
            f"  Debian/Ubuntu: apt install python3\n"
            f"  RHEL/Rocky/Alma 8: dnf install python39\n"
            f"  openSUSE: zypper install python39"
        )
    return None
