"""Personality system for FREQ — celebrations, vibes, and branding.

Provides: load_pack(), show_vibe(), splash(), celebrate()

The personality isn't decoration — it's the product. Celebrations on success,
vibes on random commands, splash screen at startup, taglines in headers.
What makes someone choose FREQ over Ansible.

Packs live in conf/personality/<name>.toml. Loaded at startup based on the
`build` field in freq.toml. Default pack is built-in.

Replaces: Nothing — no infrastructure tool has personality. That's the point.

Architecture:
    - PersonalityPack dataclass holds vibes, celebrations, taglines, quotes
    - TOML files for custom packs, built-in defaults for out-of-box experience
    - show_vibe() fires randomly (1/47 probability) after successful commands
    - splash() renders the ASCII art banner with version info

Design decisions:
    - Vibes fire at 1/47 probability — frequent enough to notice, rare enough
      to feel special. Empirically tuned.
    - Pack is loaded once and passed through the call chain, not re-read.
"""
import logging
import os
import random
from dataclasses import dataclass, field

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

_logger = logging.getLogger(__name__)
from typing import Optional

from freq.core.fmt import C, S, B_H, B_V, B_TL, B_TR, B_BL, B_BR, term_width


@dataclass
class PersonalityPack:
    """A loaded personality pack."""
    name: str = "default"
    subtitle: str = "P V E  F R E Q"
    vibe_enabled: bool = True
    vibe_probability: int = 47  # 1/N chance per command (prime = less predictable)

    celebrations: list = field(default_factory=list)
    premier: dict = field(default_factory=dict)
    taglines: list = field(default_factory=list)
    quotes: list = field(default_factory=list)
    vibe_common: list = field(default_factory=list)
    vibe_rare: list = field(default_factory=list)
    vibe_legendary: list = field(default_factory=list)
    dashboard_header: str = "PVE FREQ Dashboard"


def load_pack(conf_dir: str, pack_name: str = "default") -> PersonalityPack:
    """Load a personality pack from conf/personality/<name>.toml."""
    path = os.path.join(conf_dir, "personality", f"{pack_name}.toml")
    pack = PersonalityPack(name=pack_name)

    try:
        if tomllib is not None:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        else:
            from freq.core.config import load_toml
            data = load_toml(path)
    except FileNotFoundError:
        return pack  # Pack file doesn't exist — use defaults
    except Exception as e:
        _logger.warning("failed to load personality pack %s: %s", pack_name, e)
        return pack

    pack.subtitle = data.get("subtitle", pack.subtitle)
    pack.vibe_enabled = data.get("vibe_enabled", pack.vibe_enabled)
    pack.vibe_probability = data.get("vibe_probability", pack.vibe_probability)
    pack.dashboard_header = data.get("dashboard_header", pack.dashboard_header)

    pack.celebrations = data.get("celebrations", [])
    pack.premier = data.get("premier", {})
    pack.taglines = data.get("taglines", [])
    pack.quotes = data.get("quotes", [])

    vibes = data.get("vibes", {})
    pack.vibe_common = vibes.get("common", [])
    pack.vibe_rare = vibes.get("rare", [])
    pack.vibe_legendary = vibes.get("legendary", [])

    return pack


def celebrate(pack: PersonalityPack, operation: Optional[str] = None) -> str:
    """Pick a celebration message. Premier messages for specific operations."""
    if operation and operation in pack.premier:
        return pack.premier[operation]
    if pack.celebrations:
        return random.choice(pack.celebrations)
    return "Done."


def tagline(pack: PersonalityPack) -> str:
    """Pick a random tagline for the splash screen."""
    if pack.taglines:
        return random.choice(pack.taglines)
    return "Full frequency. Full efficiency."


def quote(pack: PersonalityPack) -> str:
    """Pick a random quote for the MOTD."""
    if pack.quotes:
        return random.choice(pack.quotes)
    return '"configure once. deploy everywhere." -- freq'


def vibe_check(pack: PersonalityPack) -> Optional[str]:
    """Roll for a vibe drop. Returns message or None.

    1/N chance per command. When triggered:
    - 60% common (tips)
    - 25% rare (artist references)
    - 15% legendary (multi-line stories)
    """
    if not pack.vibe_enabled:
        return None

    if random.randint(1, pack.vibe_probability) != 1:
        return None

    roll = random.randint(1, 100)
    if roll <= 60 and pack.vibe_common:
        return random.choice(pack.vibe_common)
    elif roll <= 85 and pack.vibe_rare:
        return random.choice(pack.vibe_rare)
    elif pack.vibe_legendary:
        return random.choice(pack.vibe_legendary)
    elif pack.vibe_common:
        return random.choice(pack.vibe_common)
    return None


def show_vibe(pack: PersonalityPack) -> None:
    """Print a vibe drop if one triggers."""
    msg = vibe_check(pack)
    if msg:
        print(f"\n{C.DIM}{msg}{C.RESET}\n")


# --- Logo ---

LOGO = f"""{C.PURPLE_BOLD}
    ██████╗ ██╗   ██╗███████╗    ███████╗██████╗ ███████╗ ██████╗
    ██╔══██╗██║   ██║██╔════╝    ██╔════╝██╔══██╗██╔════╝██╔═══██╗
    ██████╔╝██║   ██║█████╗      █████╗  ██████╔╝█████╗  ██║   ██║
    ██╔═══╝ ╚██╗ ██╔╝██╔══╝      ██╔══╝  ██╔══██╗██╔══╝  ██║▄▄ ██║
    ██║      ╚████╔╝ ███████╗    ██║     ██║  ██║███████╗╚██████╔╝
    ╚═╝       ╚═══╝  ╚══════╝    ╚═╝     ╚═╝  ╚═╝╚══════╝ ╚══▀▀═╝{C.RESET}"""


LOGO_SMALL = f"""{C.PURPLE_BOLD}  ╔═╗╦  ╦╔═╗  ╔═╗╦═╗╔═╗╔═╗
  ╠═╝╚╗╔╝║╣   ╠╣ ╠╦╝║╣ ║═╬╗
  ╩   ╚╝ ╚═╝  ╚  ╩╚═╚═╝╚═╝╚{C.RESET}"""


def splash(pack: PersonalityPack, version: str) -> None:
    """Show the FREQ splash screen with logo, tagline, and quote."""
    w = term_width()

    print(LOGO if w >= 72 else LOGO_SMALL)
    print(f"{C.PURPLE}  {pack.subtitle}{C.RESET}")
    print(f"{C.DIM}  v{version}{C.RESET}")
    print()

    tl = tagline(pack)
    print(f"  {C.GRAY}{tl}{C.RESET}")

    qt = quote(pack)
    print(f"\n  {C.DIM}{qt}{C.RESET}")
    print()
