"""Compatibility layer — Python version checks and support matrix.

FREQ requires Python 3.11+ (for tomllib, modern typing, performance).
Runs on 3.11-3.13 with zero external dependencies.

Support matrix (current + 1 version back):
  Debian:     13, 12             — ships 3.13, 3.11    — all native
  Ubuntu LTS: 24.04, 22.04       — ships 3.12, 3.10    — 22.04: deadsnakes PPA
  Rocky/RHEL: 9                  — ships 3.9            — dnf install python3.11
  AlmaLinux:  9                  — ships 3.9            — dnf install python3.11
  openSUSE:   15.6               — ships 3.6            — zypper install python311
"""
import sys

MIN_PYTHON = (3, 11)


def check_python():
    """Check Python version at startup. Returns error message or None."""
    if sys.version_info < MIN_PYTHON:
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        return (
            f"FREQ requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, "
            f"but found {ver}.\n"
            f"Install a newer Python:\n"
            f"  Debian/Ubuntu: apt install python3\n"
            f"  RHEL/Rocky/Alma 9: dnf install python3.11\n"
            f"  openSUSE: zypper install python311"
        )
    return None
