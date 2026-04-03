"""Interactive demo mode for FREQ.

Domain: freq demo

Experience FREQ without a fleet. Shows splash screen, simulated 13-point
diagnostic, mock fleet status, and personality showcase. Zero SSH calls,
zero subprocess, zero external deps. Works on any machine with Python.

Replaces: Nothing — this is the "try before you deploy" experience

Architecture:
    - Pure in-process rendering, no SSH or subprocess calls
    - Uses freq/core/personality.py for splash, taglines, celebrations
    - Simulated data demonstrates real output formatting
    - Timed delays for visual pacing (configurable step/section delays)

Design decisions:
    - Demo must work with zero config. No freq.toml, no hosts, no SSH keys.
      If someone clones the repo and runs freq demo, it must work instantly.
"""

import platform
import random
import sys
import time

from freq.core import fmt
from freq.core.personality import (
    quote,
    splash,
)


# Demo timing (seconds between visual steps)
_STEP_DELAY = 0.08
_SECTION_DELAY = 0.4


def _pause(seconds=_STEP_DELAY):
    """Small delay for visual pacing."""
    time.sleep(seconds)


def _demo_splash(pack, version):
    """Show the FREQ splash screen."""
    splash(pack, version)
    _pause(_SECTION_DELAY)


def _demo_doctor():
    """Simulated 13-point diagnostic — all passing."""
    fmt.header("Doctor", "PVE FREQ")
    fmt.blank()
    fmt.line("{bold}Self-Diagnostic{reset}".format(bold=fmt.C.BOLD, reset=fmt.C.RESET))
    fmt.blank()

    # System
    fmt.line("  {p}System{r}".format(p=fmt.C.PURPLE_BOLD, r=fmt.C.RESET))
    _pause()

    py_ver = "{}.{}.{}".format(sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    fmt.step_ok("Python {} ({})".format(py_ver, platform.python_implementation()))
    _pause()

    plat = platform.system()
    if plat == "Linux":
        try:
            import distro_detect

            plat_str = plat
        except ImportError:
            plat_str = plat
        # Try to get distro info
        try:
            with open("/etc/os-release") as f:
                for ln in f:
                    if ln.startswith("PRETTY_NAME="):
                        plat_str = ln.split("=", 1)[1].strip().strip('"')
                        break
        except (IOError, OSError):
            pass
        fmt.step_ok("Platform: {} ({})".format(plat_str, platform.machine()))
    else:
        fmt.step_ok("Platform: {} {}".format(plat, platform.machine()))
    _pause()

    fmt.step_ok("Prerequisites: all found")
    _pause()
    print()

    # Installation
    fmt.line("  {p}Installation{r}".format(p=fmt.C.PURPLE_BOLD, r=fmt.C.RESET))
    _pause()
    fmt.step_ok("Install dir: /opt/pve-freq")
    _pause()
    fmt.step_ok("Config: freq.toml loaded")
    _pause()
    fmt.step_ok("Data directories")
    _pause()
    fmt.step_ok("Personality: personal pack")
    _pause()
    print()

    # SSH & Connectivity
    fmt.line("  {p}SSH & Connectivity{r}".format(p=fmt.C.PURPLE_BOLD, r=fmt.C.RESET))
    _pause()
    fmt.step_ok("SSH: OpenSSH_9.7p1")
    _pause()
    fmt.step_ok("SSH key: id_rsa (600)")
    _pause()
    fmt.step_ok("Fleet SSH: 3/3 sample hosts reachable")
    _pause()
    print()

    # Fleet Data
    fmt.line("  {p}Fleet Data{r}".format(p=fmt.C.PURPLE_BOLD, r=fmt.C.RESET))
    _pause()
    fmt.step_ok("Fleet: 12 hosts (4 linux, 2 pve, 3 docker, 1 truenas, 1 pfsense, 1 switch)")
    _pause()
    fmt.step_ok("Fleet data: no duplicates, all IPs valid")
    _pause()
    fmt.step_ok("VLANs: 5 defined")
    _pause()
    fmt.step_ok("Distros: 8 cloud images defined")
    _pause()
    print()

    # PVE Cluster
    fmt.line("  {p}PVE Cluster{r}".format(p=fmt.C.PURPLE_BOLD, r=fmt.C.RESET))
    _pause()
    fmt.step_ok("PVE cluster: 2/2 nodes (PVE 8.3.2)")
    _pause()
    print()

    # Summary
    fmt.divider("Summary")
    fmt.blank()
    fmt.line(
        "  {g}16{r} passed  {y}0{r} warnings  {red}0{r} failed  (16 total)".format(
            g=fmt.C.GREEN, y=fmt.C.YELLOW, red=fmt.C.RED, r=fmt.C.RESET
        )
    )
    fmt.blank()
    fmt.line("{g}FREQ is healthy. All systems nominal.{r}".format(g=fmt.C.GREEN, r=fmt.C.RESET))
    fmt.blank()
    fmt.footer()
    _pause(_SECTION_DELAY)


def _demo_fleet_status():
    """Simulated fleet status with mock hosts."""
    fmt.header("Fleet Status")
    fmt.blank()

    mock_hosts = [
        ("pve01", "pve", "up 47 days, 3:22"),
        ("pve02", "pve", "up 47 days, 3:21"),
        ("docker-prod", "docker", "up 31 days, 12:05"),
        ("docker-media", "docker", "up 31 days, 12:04"),
        ("truenas", "truenas", "up 90 days, 6:14"),
        ("pfsense", "pfsense", "up 120 days, 18:47"),
    ]

    fmt.line("{b}Checking {n} hosts...{r}".format(b=fmt.C.BOLD, n=len(mock_hosts), r=fmt.C.RESET))
    fmt.blank()

    fmt.table_header(
        ("HOST", 16),
        ("STATUS", 10),
        ("UPTIME", 30),
        ("TIME", 6),
    )

    for label, htype, uptime in mock_hosts:
        _pause(0.05)
        fmt.table_row(
            ("{b}{label}{r}".format(b=fmt.C.BOLD, label=label, r=fmt.C.RESET), 16),
            (fmt.badge("up"), 10),
            (uptime, 30),
            ("0.1s", 6),
        )

    print()
    fmt.line(
        "  {g}6{r} up  {red}0{r} down  |  {dim}6 hosts in 0.4s{r}".format(
            g=fmt.C.GREEN, red=fmt.C.RED, dim=fmt.C.DIM, r=fmt.C.RESET
        )
    )
    fmt.blank()
    fmt.footer()
    _pause(_SECTION_DELAY)


def _demo_commands():
    """Show command count summary."""
    fmt.header("Command Reference")
    fmt.blank()

    categories = [
        ("Fleet Operations", 11),
        ("VM Management", 16),
        ("Security", 3),
        ("Infrastructure", 6),
        ("Media Stack", 40),
        ("Monitoring", 4),
        ("Engine", 4),
        ("Smart Commands", 4),
        ("Deployment", 2),
    ]

    fmt.line("{b}65+ commands across {n} categories{r}".format(b=fmt.C.BOLD, n=len(categories), r=fmt.C.RESET))
    fmt.blank()

    for name, count in categories:
        fmt.line(
            "  {p}{name:<24}{r} {dim}{count} commands{r}".format(
                p=fmt.C.PURPLE, name=name, dim=fmt.C.DIM, count=count, r=fmt.C.RESET
            )
        )
        _pause(0.03)

    fmt.blank()
    fmt.line("{dim}Run 'freq help' for the full command reference.{r}".format(dim=fmt.C.DIM, r=fmt.C.RESET))
    fmt.blank()
    fmt.footer()
    _pause(_SECTION_DELAY)


def _demo_personality(pack):
    """Showcase the personality system — the secret weapon."""
    fmt.header("Personality System")
    fmt.blank()
    fmt.line("{b}What makes FREQ different{r}".format(b=fmt.C.BOLD, r=fmt.C.RESET))
    fmt.blank()

    # Celebrations
    fmt.line(
        "  {p}Celebrations{r} {dim}(after every successful command){r}".format(
            p=fmt.C.PURPLE_BOLD, dim=fmt.C.DIM, r=fmt.C.RESET
        )
    )
    if pack.celebrations:
        shown = random.sample(pack.celebrations, min(3, len(pack.celebrations)))
        for msg in shown:
            fmt.line("    {g}{msg}{r}".format(g=fmt.C.GREEN, msg=msg, r=fmt.C.RESET))
            _pause(0.1)
    else:
        fmt.line("    {g}Done.{r}".format(g=fmt.C.GREEN, r=fmt.C.RESET))
    fmt.blank()

    # Taglines
    fmt.line("  {p}Taglines{r} {dim}(splash screen){r}".format(p=fmt.C.PURPLE_BOLD, dim=fmt.C.DIM, r=fmt.C.RESET))
    if pack.taglines:
        tl = random.choice(pack.taglines)
        fmt.line("    {gray}{tl}{r}".format(gray=fmt.C.GRAY, tl=tl, r=fmt.C.RESET))
    else:
        fmt.line("    {gray}Full frequency. Full efficiency.{r}".format(gray=fmt.C.GRAY, r=fmt.C.RESET))
    _pause(0.15)
    fmt.blank()

    # Vibe drops
    fmt.line(
        "  {p}Vibe Drops{r} {dim}(1/{prob} chance per command){r}".format(
            p=fmt.C.PURPLE_BOLD, dim=fmt.C.DIM, prob=pack.vibe_probability, r=fmt.C.RESET
        )
    )
    fmt.blank()

    if pack.vibe_common:
        fmt.line("    {cyan}Common (60%):{r}".format(cyan=fmt.C.CYAN, r=fmt.C.RESET))
        vibe = random.choice(pack.vibe_common)
        fmt.line("      {dim}{v}{r}".format(dim=fmt.C.DIM, v=vibe, r=fmt.C.RESET))
        _pause(0.15)

    if pack.vibe_rare:
        fmt.line("    {yellow}Rare (25%):{r}".format(yellow=fmt.C.YELLOW, r=fmt.C.RESET))
        vibe = random.choice(pack.vibe_rare)
        fmt.line("      {dim}{v}{r}".format(dim=fmt.C.DIM, v=vibe, r=fmt.C.RESET))
        _pause(0.15)

    if pack.vibe_legendary:
        fmt.line("    {mag}Legendary (15%):{r}".format(mag=fmt.C.MAGENTA, r=fmt.C.RESET))
        vibe = random.choice(pack.vibe_legendary)
        # Legendary vibes can be multi-line
        for vl in vibe.split("\n"):
            fmt.line("      {dim}{v}{r}".format(dim=fmt.C.DIM, v=vl, r=fmt.C.RESET))
        _pause(0.2)

    fmt.blank()

    # Quotes
    if pack.quotes:
        fmt.line("  {p}Quotes{r}".format(p=fmt.C.PURPLE_BOLD, r=fmt.C.RESET))
        qt = random.choice(pack.quotes)
        fmt.line("    {dim}{qt}{r}".format(dim=fmt.C.DIM, qt=qt, r=fmt.C.RESET))
        fmt.blank()

    fmt.footer()
    _pause(_SECTION_DELAY)


def _demo_dashboard():
    """Tease the web dashboard."""
    print()
    fmt.line("{p}Web Dashboard{r}".format(p=fmt.C.PURPLE_BOLD, r=fmt.C.RESET))
    print()
    fmt.line(
        "  {b}89 API endpoints{r}  |  {b}7 views{r}  |  {b}Zero JS dependencies{r}".format(b=fmt.C.BOLD, r=fmt.C.RESET)
    )
    fmt.line("  {dim}Single-file SPA served by Python's http.server{r}".format(dim=fmt.C.DIM, r=fmt.C.RESET))
    print()
    fmt.line("  {cyan}Start it:{r}  freq serve".format(cyan=fmt.C.CYAN, r=fmt.C.RESET))
    fmt.line("  {cyan}Open:{r}      http://localhost:8888".format(cyan=fmt.C.CYAN, r=fmt.C.RESET))
    print()
    _pause(_SECTION_DELAY)


def _demo_closing(pack):
    """Final message."""
    print()
    qt = quote(pack)
    print("  {dim}{qt}{r}".format(dim=fmt.C.DIM, qt=qt, r=fmt.C.RESET))
    print()
    print(
        "  {p}PVE FREQ{r} {dim}— full frequency, full efficiency.{r}".format(
            p=fmt.C.PURPLE_BOLD, dim=fmt.C.DIM, r=fmt.C.RESET
        )
    )
    print("  {dim}https://github.com/Low-Freq-Labs/pve-freq{r}".format(dim=fmt.C.DIM, r=fmt.C.RESET))
    print()


def run(cfg, pack, args) -> int:
    """Run the interactive demo. No fleet required."""
    _demo_splash(pack, cfg.version)
    _demo_doctor()
    _demo_fleet_status()
    _demo_commands()
    _demo_personality(pack)
    _demo_dashboard()
    _demo_closing(pack)
    return 0
