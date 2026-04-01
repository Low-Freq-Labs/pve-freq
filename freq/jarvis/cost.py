"""Fleet power cost estimation for FREQ.

Domain: freq hw cost

Calculates per-host and fleet-wide monthly electricity costs using iDRAC
sensor data (actual watts) or resource-based estimates (vCPU, RAM, disk)
with user-configured rate and PUE.

Replaces: Spreadsheet cost tracking + iDRAC manual readings ($0 — time savings)

Architecture:
    - iDRAC sensor data preferred; falls back to resource-based estimation
    - PUE multiplier accounts for cooling/overhead in real datacenter costs
    - Integrates with capacity planner for cost-aware migration recommendations

Design decisions:
    - Clamped watts (5W-2000W) and rates prevent nonsensical estimates
    - iDRAC vs estimate flagged per-host so operators know data quality
"""
import json
import math
import os
import re
import time
from dataclasses import dataclass, field

from freq.core import log as logger


COST_STATE_FILE = "cost_state.json"

# Estimated power draw per resource unit (when no iDRAC data available)
WATTS_PER_VCPU = 10     # rough estimate per vCPU
WATTS_PER_GB_RAM = 3    # rough estimate per GB RAM
WATTS_PER_TB_DISK = 6   # rough estimate per TB spinning disk
HOURS_PER_MONTH = 730   # average


@dataclass
class CostConfig:
    """Cost tracking configuration."""
    rate_per_kwh: float = 0.12
    currency: str = "USD"
    pue: float = 1.2  # Power Usage Effectiveness


@dataclass
class HostCost:
    """Cost estimate for a single host."""
    label: str
    watts: float = 0.0
    watts_source: str = "estimate"  # "idrac", "estimate"
    kwh_month: float = 0.0
    cost_month: float = 0.0
    vcpus: int = 0
    ram_gb: float = 0.0
    vms: int = 0


def load_cost_config(conf_dir: str) -> CostConfig:
    """Load cost configuration from freq.toml."""
    toml_path = os.path.join(conf_dir, "freq.toml")
    if not os.path.isfile(toml_path):
        return CostConfig()
    try:
        import tomllib
        with open(toml_path, "rb") as f:
            data = tomllib.load(f)
        cc = data.get("cost", {})
        return CostConfig(
            rate_per_kwh=float(cc.get("rate_per_kwh", 0.12)),
            currency=cc.get("currency", "USD"),
            pue=float(cc.get("pue", 1.2)),
        )
    except Exception as e:
        logger.warn(f"Failed to load cost config: {e}")
        return CostConfig()


def parse_idrac_power(sensor_output: str) -> float:
    """Extract current power draw in watts from racadm getsensorinfo output."""
    # Look for "System Board Pwr Consumption" or "PS.*Input.*Watt" patterns
    for line in sensor_output.split("\n"):
        low = line.lower()
        if "pwr consumption" in low or "power consumption" in low:
            m = re.search(r'(\d+)\s*[Ww]', line)
            if m:
                return float(m.group(1))
        if "input wattage" in low or "input power" in low:
            m = re.search(r'(\d+)\s*[Ww]', line)
            if m:
                return float(m.group(1))
    return 0.0


def _parse_ram_mb(ram_str: str) -> float:
    """Parse RAM string like '4096/8192MB' → used MB."""
    m = re.match(r'(\d+)/(\d+)', ram_str)
    if m:
        return float(m.group(2))  # total
    return 0.0


def estimate_host_watts(host_data: dict) -> float:
    """Estimate power draw from resource allocation when no iDRAC data."""
    watts = 0.0

    # RAM contribution
    ram_str = host_data.get("ram", "")
    ram_mb = _parse_ram_mb(ram_str)
    if ram_mb > 0:
        watts += (ram_mb / 1024) * WATTS_PER_GB_RAM

    # Load/CPU contribution (use load as proxy for active cores)
    try:
        load = float(host_data.get("load", "0"))
        if not math.isfinite(load) or load < 0:
            load = 1
        watts += max(load, 1) * WATTS_PER_VCPU
    except (ValueError, TypeError):
        watts += WATTS_PER_VCPU  # at least 1 vCPU

    # Docker containers add some overhead
    try:
        containers = int(host_data.get("docker", "0"))
        watts += containers * 2  # ~2W per container baseline
    except (ValueError, TypeError):
        pass

    return min(max(watts, 5.0), 2000.0)  # clamp 5W-2000W


def compute_costs(health_data: dict, idrac_data: dict, cost_cfg: CostConfig) -> list:
    """Compute cost estimates for all hosts.

    health_data: from /api/health (bg cache)
    idrac_data: dict of {label: watts} from iDRAC sensor probes
    cost_cfg: user's cost configuration

    Returns list of HostCost objects.
    """
    costs = []
    pue = max(1.0, min(cost_cfg.pue, 3.0))
    rate = max(0.0, min(cost_cfg.rate_per_kwh, 2.0))

    for h in health_data.get("hosts", []):
        label = h.get("label", "")
        if not label:
            continue
        if h.get("status", "") == "unreachable":
            continue

        hc = HostCost(label=label)

        # Try iDRAC data first
        if label in idrac_data and idrac_data[label] > 0:
            hc.watts = idrac_data[label]
            hc.watts_source = "idrac"
        else:
            hc.watts = estimate_host_watts(h)
            hc.watts_source = "estimate"

        # Apply PUE (clamped)
        effective_watts = hc.watts * pue

        # Calculate monthly cost (clamped rate)
        hc.kwh_month = round(effective_watts * HOURS_PER_MONTH / 1000, 2)
        hc.cost_month = round(hc.kwh_month * rate, 2)

        # Resource info
        try:
            hc.vms = int(h.get("docker", "0"))
        except (ValueError, TypeError):
            pass

        ram_mb = _parse_ram_mb(h.get("ram", ""))
        hc.ram_gb = round(ram_mb / 1024, 1) if ram_mb > 0 else 0

        costs.append(hc)

    return sorted(costs, key=lambda c: c.cost_month, reverse=True)


def costs_to_dicts(costs: list) -> list:
    """Convert HostCost list to JSON-serializable dicts."""
    return [
        {
            "label": c.label,
            "watts": round(c.watts, 1),
            "watts_source": c.watts_source,
            "kwh_month": c.kwh_month,
            "cost_month": c.cost_month,
            "vcpus": c.vcpus,
            "ram_gb": c.ram_gb,
            "vms": c.vms,
        }
        for c in costs
    ]


def fleet_summary(costs: list, cost_cfg: CostConfig) -> dict:
    """Compute fleet-wide cost summary."""
    total_watts = sum(c.watts for c in costs)
    total_kwh = sum(c.kwh_month for c in costs)
    total_cost = sum(c.cost_month for c in costs)
    idrac_count = sum(1 for c in costs if c.watts_source == "idrac")

    return {
        "total_watts": round(total_watts, 1),
        "total_kwh_month": round(total_kwh, 2),
        "total_cost_month": round(total_cost, 2),
        "total_cost_year": round(total_cost * 12, 2),
        "host_count": len(costs),
        "idrac_measured": idrac_count,
        "estimated": len(costs) - idrac_count,
        "currency": cost_cfg.currency,
        "rate_per_kwh": cost_cfg.rate_per_kwh,
        "pue": cost_cfg.pue,
    }


# ── CLI Command ────────────────────────────────────────────────────────

def cmd_cost(cfg, pack, args) -> int:
    """Show fleet power cost estimates."""
    from freq.core import fmt

    fmt.header("Fleet Power Costs")
    fmt.blank()

    # Load cost config
    cost_cfg = load_cost_config(cfg.conf_dir)

    # Get health data from cache or live probe
    health = None
    try:
        from freq.modules.serve import _bg_cache, _bg_lock
        with _bg_lock:
            health = _bg_cache.get("health")
    except (ImportError, AttributeError):
        pass

    if not health or not health.get("hosts"):
        fmt.line(f"  {fmt.C.YELLOW}No health data available.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run freq serve first, or use freq health to collect data.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Get iDRAC data if available
    idrac_data = {}
    try:
        from freq.modules.serve import _bg_cache as bgc, _bg_lock as bgl
        with bgl:
            infra = bgc.get("infra_quick")
        if infra:
            for dev in infra.get("devices", []):
                if dev.get("type") == "idrac" and dev.get("power_watts"):
                    idrac_data[dev["label"]] = dev["power_watts"]
    except (ImportError, AttributeError):
        pass

    costs = compute_costs(health, idrac_data, cost_cfg)
    if not costs:
        fmt.line(f"  {fmt.C.DIM}No hosts to estimate costs for.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Per-host table
    fmt.line(f"  {'HOST':<20} {'WATTS':>8} {'SOURCE':>10} {'kWh/mo':>10} {cost_cfg.currency + '/mo':>10}")
    fmt.line(f"  {'─' * 62}")
    for c in costs:
        fmt.line(f"  {c.label:<20} {c.watts:>7.0f}W {c.watts_source:>10} {c.kwh_month:>9.1f} {c.cost_month:>9.2f}")
    fmt.blank()

    # Summary
    summary = fleet_summary(costs, cost_cfg)
    fmt.line(f"  {fmt.C.BOLD}Fleet Total{fmt.C.RESET}")
    fmt.line(f"    Power:      {summary['total_watts']:.0f}W")
    fmt.line(f"    Monthly:    {summary['currency']} {summary['total_cost_month']:.2f}")
    fmt.line(f"    Annual:     {summary['currency']} {summary['total_cost_year']:.2f}")
    fmt.line(f"    Rate:       {summary['rate_per_kwh']:.3f}/kWh  PUE: {summary['pue']:.1f}")
    fmt.line(f"    Sources:    {summary['idrac_measured']} iDRAC, {summary['estimated']} estimated")
    fmt.blank()
    fmt.footer()
    return 0
