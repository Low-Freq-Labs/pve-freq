"""Kill-chain blast radius analysis for FREQ.

Domain: freq ops risk <target|all>

Answers "what breaks if X dies?" by mapping infrastructure dependencies
from conf/risk.toml. Shows kill chains, impact lists, recovery procedures,
and upstream/downstream dependency graphs.

Replaces: ServiceNow CMDB dependency maps ($50k+/yr enterprise)

Architecture:
    - Risk map loaded from conf/risk.toml (targets with depends_on/depended_by)
    - Kill chain visualizes the remote access path (Operator -> VPN -> ... -> Target)
    - Partial name matching for quick lookups (freq risk pf matches pfsense)

Design decisions:
    - TOML config over auto-discovery — operators know their dependencies best
    - Risk levels (CRITICAL/HIGH/MEDIUM/LOW) are human-assigned, not computed
"""

import os

from freq.core import fmt
from freq.core.config import FreqConfig, load_toml


def _load_risk_map(cfg: FreqConfig) -> dict:
    """Load infrastructure dependency map from conf/risk.toml."""
    risk_path = os.path.join(cfg.conf_dir, "risk.toml")
    data = load_toml(risk_path)
    targets = data.get("target", {})

    # Normalize: ensure all expected fields exist with defaults
    deps = {}
    for key, info in targets.items():
        deps[key] = {
            "label": info.get("label", key),
            "risk": info.get("risk", "MEDIUM"),
            "impact": info.get("impact", []),
            "recovery": info.get("recovery", "No recovery procedure documented."),
            "depends_on": info.get("depends_on", []),
            "depended_by": info.get("depended_by", []),
        }
    return deps


def _load_kill_chain(cfg: FreqConfig) -> list:
    """Load kill chain from conf/risk.toml. Returns list of chain nodes."""
    risk_path = os.path.join(cfg.conf_dir, "risk.toml")
    data = load_toml(risk_path)
    return data.get("kill_chain", [])


RISK_COLORS = {
    "CRITICAL": fmt.C.RED,
    "HIGH": fmt.C.YELLOW,
    "MEDIUM": fmt.C.CYAN,
    "LOW": fmt.C.GREEN,
}


def cmd_risk(cfg: FreqConfig, pack, args) -> int:
    """Kill-chain blast radius analysis."""
    target = getattr(args, "target", None)
    dependencies = _load_risk_map(cfg)

    if not dependencies:
        fmt.blank()
        fmt.line(f"  {fmt.C.YELLOW}No risk map configured.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Create conf/risk.toml to define your infrastructure dependencies.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}See conf/risk.toml.example for a template.{fmt.C.RESET}")
        fmt.blank()
        return 0

    if not target or target == "all":
        return _risk_map(cfg, dependencies)
    elif target in dependencies:
        return _risk_detail(cfg, dependencies, target)
    else:
        # Try partial match
        for key in dependencies:
            if target.lower() in key.lower():
                return _risk_detail(cfg, dependencies, key)
        fmt.error(f"Unknown target: {target}")
        fmt.info(f"Available: {', '.join(dependencies.keys())}")
        return 1


def _risk_map(cfg: FreqConfig, dependencies: dict) -> int:
    """Show full infrastructure risk map."""
    cluster = cfg.cluster_name or "Infrastructure"
    fmt.header(f"Risk Map — {cluster}")
    fmt.blank()

    # Kill chain
    fmt.line(f"{fmt.C.BOLD}Kill Chain (remote access path):{fmt.C.RESET}")
    fmt.blank()
    chain = _load_kill_chain(cfg) or ["Operator", "VPN", "Firewall", "Switch", "Network", "Target"]
    chain_str = f" {fmt.C.RED}\u2192{fmt.C.RESET} ".join(f"{fmt.C.BOLD}{c}{fmt.C.RESET}" for c in chain)
    print(f"    {chain_str}")
    print(f"    {fmt.C.DIM}Break any link = no remote recovery{fmt.C.RESET}")
    fmt.blank()

    # Risk table
    fmt.table_header(
        ("TARGET", 16),
        ("RISK", 10),
        ("PRIMARY IMPACT", 40),
    )

    for key, info in dependencies.items():
        risk = info["risk"]
        color = RISK_COLORS.get(risk, fmt.C.GRAY)
        impact = info["impact"][0][:40] if info["impact"] else "\u2014"

        fmt.table_row(
            (f"{fmt.C.BOLD}{key}{fmt.C.RESET}", 16),
            (f"{color}[{risk}]{fmt.C.RESET}", 10),
            (f"{fmt.C.DIM}{impact}{fmt.C.RESET}", 40),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.GRAY}Detail: freq risk <target>{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _risk_detail(cfg: FreqConfig, dependencies: dict, target: str) -> int:
    """Show detailed risk analysis for a specific target."""
    info = dependencies[target]
    risk = info["risk"]
    color = RISK_COLORS.get(risk, fmt.C.GRAY)

    fmt.header(f"Risk: {info['label']}")
    fmt.blank()

    # Risk level
    fmt.line(f"  {fmt.C.BOLD}Risk Level:{fmt.C.RESET}  {color}{fmt.C.BOLD}[{risk}]{fmt.C.RESET}")
    fmt.blank()

    # Impact
    fmt.line(f"  {fmt.C.BOLD}If {target} goes down:{fmt.C.RESET}")
    for impact in info["impact"]:
        print(f"    {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {impact}")
    fmt.blank()

    # Dependencies
    if info["depends_on"]:
        fmt.line(f"  {fmt.C.BOLD}Depends on:{fmt.C.RESET}")
        for dep in info["depends_on"]:
            print(f"    {fmt.C.CYAN}{fmt.S.ARROW}{fmt.C.RESET} {dep}")
        fmt.blank()

    if info["depended_by"]:
        fmt.line(f"  {fmt.C.BOLD}Depended by:{fmt.C.RESET}")
        for dep in info["depended_by"]:
            print(f"    {fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}  {dep}")
        fmt.blank()

    # Recovery
    fmt.line(f"  {fmt.C.BOLD}Recovery:{fmt.C.RESET}")
    print(f"    {fmt.C.GREEN}{info['recovery']}{fmt.C.RESET}")
    fmt.blank()

    fmt.footer()
    return 0
