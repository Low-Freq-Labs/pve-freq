"""Compatibility layer — Python version gate.

Provides: check_python() → error message or None

FREQ requires Python 3.11+ for tomllib (TOML parsing), modern typing syntax,
and performance improvements. Runs on 3.11-3.13 with zero external deps.

Support matrix:
    Debian 13/12:    3.13/3.11    native
    Ubuntu 24.04:    3.12         native
    Ubuntu 22.04:    3.10         needs deadsnakes PPA for 3.11+
    Rocky/RHEL 9:    3.9          dnf install python3.11
    AlmaLinux 9:     3.9          dnf install python3.11
    Fedora 41:       3.13         native
    Arch:            3.13         native
    Alpine 3.21:     3.12         native
    openSUSE 15.6:   3.6          zypper install python311

Replaces: Nothing — this is a gate, not a feature.

Architecture:
    - Called once at startup by __main__.py before any imports
    - Returns error string if Python is too old, None if OK
    - Does NOT import any FREQ modules — must work on ancient Python

Design decisions:
    - 3.11 minimum, not 3.12. Debian 12 and Proxmox VE 8 ship 3.11.
      Supporting them is non-negotiable for a Proxmox management tool.
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
