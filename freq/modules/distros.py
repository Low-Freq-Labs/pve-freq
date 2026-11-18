"""Cloud image catalog for FREQ.

Domain: freq distros

Lists available cloud images for VM provisioning with freq vm create --image.
Images are defined in conf/distros.toml with download URLs, checksums, and
family/tier classifications (priority, supported, rolling, best-effort).

Replaces: Manual image downloads, bookmarked cloud-image URLs per distro

Architecture:
    - Image definitions loaded from conf/distros.toml via FreqConfig
    - Grouped display by tier (priority → supported → rolling → best-effort)
    - Table rendering via freq/core/fmt.py

Design decisions:
    - Images are config, not code. Adding a new distro means one TOML entry,
      not a code change. Keeps the image catalog user-extensible.
"""

from freq.core import fmt
from freq.core.config import FreqConfig


def cmd_distros(cfg: FreqConfig, pack, args) -> int:
    """List available cloud images."""
    fmt.header("Cloud Images")
    fmt.blank()

    if not cfg.distros:
        fmt.line(f"{fmt.C.YELLOW}No cloud images defined.{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Add images to conf/distros.toml{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Group by tier
    tiers = {"priority": [], "supported": [], "rolling": [], "besteffort": []}
    for d in cfg.distros:
        tier = d.tier if d.tier in tiers else "supported"
        tiers[tier].append(d)

    tier_labels = {
        "priority": f"{fmt.C.GREEN}Priority{fmt.C.RESET} — LTS/stable, recommended",
        "supported": f"{fmt.C.CYAN}Supported{fmt.C.RESET} — older LTS, available",
        "rolling": f"{fmt.C.YELLOW}Rolling{fmt.C.RESET} — snapshot-based, latest",
        "besteffort": f"{fmt.C.GRAY}Best Effort{fmt.C.RESET} — EOL or niche",
    }

    total = len(cfg.distros)
    fmt.line(f"{fmt.C.BOLD}{total} cloud images available{fmt.C.RESET}")
    fmt.line(f"{fmt.C.DIM}Use with: freq vm create --image <key>{fmt.C.RESET}")
    fmt.blank()

    for tier_name, tier_distros in tiers.items():
        if not tier_distros:
            continue

        fmt.divider(tier_labels.get(tier_name, tier_name))
        fmt.blank()

        fmt.table_header(
            ("KEY", 18),
            ("NAME", 28),
            ("FAMILY", 8),
            ("ALIASES", 12),
        )

        for d in tier_distros:
            family_color = {
                "debian": fmt.C.GREEN,
                "rhel": fmt.C.RED,
                "arch": fmt.C.CYAN,
                "suse": fmt.C.GREEN,
            }.get(d.family, fmt.C.GRAY)

            aliases = ", ".join(d.aliases) if d.aliases else f"{fmt.C.DIM}—{fmt.C.RESET}"

            fmt.table_row(
                (f"{fmt.C.BOLD}{d.key}{fmt.C.RESET}", 18),
                (d.name, 28),
                (f"{family_color}{d.family}{fmt.C.RESET}", 8),
                (aliases, 12),
            )

        fmt.blank()

    fmt.footer()
    return 0
