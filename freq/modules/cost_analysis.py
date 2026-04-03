"""On-prem FinOps and cost optimization for FREQ.

Domain: freq hw <cost-waste|cost-density|cost-optimize|cost-compare>

Per-VM cost attribution based on power draw estimates, waste detection for
oversized VMs, host density analysis, and cloud cost comparison ("what would
this fleet cost in AWS?"). Nobody does on-prem FinOps. Now FREQ does.

Replaces: CloudHealth ($50K+/yr), Kubecost ($30K/yr, K8s-only),
          spreadsheet-based capacity planning

Architecture:
    - Power cost model: watts-per-vCPU + watts-per-GB-RAM * PUE * kWh rate
    - AWS pricing table for side-by-side cloud comparison (t3/m5 instances)
    - PVE API queries for VM resource allocation across cluster
    - Fleet SSH for live resource utilization metrics

Design decisions:
    - Cost model uses power consumption, not license fees. On-prem cost is
      electricity, not per-seat pricing. This is the honest comparison.
"""

import json

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many

COST_CMD_TIMEOUT = 15
PVE_CMD_TIMEOUT = 30
PVE_QUICK_TIMEOUT = 10

# AWS on-demand pricing (rough, us-east-1, 2026)
AWS_PRICING = {
    # (vcpu, ram_gb): monthly_cost
    (1, 1): 8.50,  # t3.micro
    (1, 2): 15.00,  # t3.small
    (2, 4): 30.00,  # t3.medium
    (2, 8): 60.00,  # t3.large
    (4, 16): 120.00,  # t3.xlarge
    (8, 32): 240.00,  # t3.2xlarge
    (16, 64): 480.00,  # m5.4xlarge
    (32, 128): 960.00,  # m5.8xlarge
    (48, 192): 1440.00,  # m5.12xlarge
}

# Estimated watts per resource
WATTS_PER_VCPU = 10
WATTS_PER_GB_RAM = 3
HOURS_PER_MONTH = 730


def _estimate_vm_monthly_cost(vcpu: int, ram_gb: float, rate_kwh: float = 0.12, pue: float = 1.2) -> float:
    """Estimate monthly cost for a VM based on resource allocation."""
    watts = (vcpu * WATTS_PER_VCPU) + (ram_gb * WATTS_PER_GB_RAM)
    kwh_monthly = (watts * HOURS_PER_MONTH) / 1000
    return round(kwh_monthly * rate_kwh * pue, 2)


def _estimate_aws_cost(vcpu: int, ram_gb: float) -> float:
    """Estimate equivalent AWS cost for a VM."""
    # Find closest matching instance
    best_match = None
    best_price = 0
    for (aws_cpu, aws_ram), price in sorted(AWS_PRICING.items()):
        if aws_cpu >= vcpu and aws_ram >= ram_gb:
            if best_match is None or price < best_price:
                best_match = (aws_cpu, aws_ram)
                best_price = price
    return best_price if best_match else max(AWS_PRICING.values())


def _gather_vm_resources(cfg: FreqConfig) -> list:
    """Gather VM resource allocation from PVE."""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip,
            command="pvesh get /cluster/resources --type vm --output-format json 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=PVE_CMD_TIMEOUT,
            htype="pve",
            use_sudo=True,
        )
        if r.returncode == 0:
            try:
                vms = json.loads(r.stdout)
                return [
                    {
                        "vmid": v.get("vmid", 0),
                        "name": v.get("name", ""),
                        "status": v.get("status", ""),
                        "node": v.get("node", ""),
                        "vcpu": v.get("maxcpu", 0),
                        "ram_mb": round(v.get("maxmem", 0) / 1048576),
                        "disk_gb": round(v.get("maxdisk", 0) / 1073741824),
                        "cpu_usage": round(v.get("cpu", 0) * 100, 1),
                        "mem_usage": round(v.get("mem", 0) / max(v.get("maxmem", 1), 1) * 100, 1)
                        if v.get("maxmem", 0) > 0
                        else 0,
                    }
                    for v in vms
                ]
            except json.JSONDecodeError:
                pass
    return []


def cmd_cost_analysis(cfg: FreqConfig, pack, args) -> int:
    """Cost analysis dispatch."""
    action = getattr(args, "action", None) or "waste"
    routes = {
        "waste": _cmd_waste,
        "density": _cmd_density,
        "optimize": _cmd_optimize,
        "compare": _cmd_compare,
    }
    handler = routes.get(action)
    if handler:
        return handler(cfg, args)
    fmt.error(f"Unknown cost-analysis action: {action}")
    fmt.info("Available: waste, density, optimize, compare")
    return 1


def _cmd_waste(cfg: FreqConfig, args) -> int:
    """Find overprovisioned VMs wasting resources."""
    fmt.header("Resource Waste Analysis")
    fmt.blank()

    fmt.step_start("Analyzing VM resource usage")
    vms = _gather_vm_resources(cfg)
    if not vms:
        fmt.step_fail("No VM data available")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok(f"Analyzed {len(vms)} VMs")
    fmt.blank()

    running = [v for v in vms if v["status"] == "running"]
    waste_candidates = []

    for v in running:
        issues = []
        # CPU waste: allocated > 2 cores but using < 10%
        if v["vcpu"] > 2 and v["cpu_usage"] < 10:
            issues.append(f"CPU: {v['cpu_usage']:.0f}% of {v['vcpu']} cores")
        # RAM waste: allocated > 2GB but using < 20%
        if v["ram_mb"] > 2048 and v["mem_usage"] < 20:
            issues.append(f"RAM: {v['mem_usage']:.0f}% of {v['ram_mb']}MB")

        if issues:
            waste_candidates.append({**v, "issues": issues})

    # Stopped VMs are also waste
    stopped = [v for v in vms if v["status"] != "running"]

    if not waste_candidates and not stopped:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} No significant waste detected.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    if waste_candidates:
        fmt.divider(f"Overprovisioned VMs ({len(waste_candidates)})")
        fmt.blank()
        fmt.table_header(("VMID", 8), ("NAME", 16), ("ISSUE", 30), ("SAVINGS", 10))

        total_savings = 0
        for v in waste_candidates:
            # Estimate savings from right-sizing
            current_cost = _estimate_vm_monthly_cost(v["vcpu"], v["ram_mb"] / 1024)
            right_cost = _estimate_vm_monthly_cost(max(v["vcpu"] // 2, 1), max(v["ram_mb"] // 2048, 1))
            savings = current_cost - right_cost
            total_savings += savings

            fmt.table_row(
                (str(v["vmid"]), 8),
                (f"{fmt.C.BOLD}{v['name']}{fmt.C.RESET}", 16),
                ("; ".join(v["issues"])[:30], 30),
                (f"${savings:.2f}/mo", 10),
            )

        fmt.blank()
        fmt.line(f"  {fmt.C.YELLOW}Potential savings: ${total_savings:.2f}/month{fmt.C.RESET}")

    if stopped:
        fmt.blank()
        fmt.divider(f"Stopped VMs ({len(stopped)})")
        fmt.blank()
        for v in stopped[:10]:
            cost = _estimate_vm_monthly_cost(v["vcpu"], v["ram_mb"] / 1024)
            fmt.line(
                f"  {fmt.C.DIM}VM {v['vmid']} ({v['name']}) — {v['vcpu']} CPU, "
                f"{v['ram_mb']}MB RAM — allocated but idle{fmt.C.RESET}"
            )

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_density(cfg: FreqConfig, args) -> int:
    """Show host utilization density."""
    fmt.header("Host Density Analysis")
    fmt.blank()

    hosts = cfg.hosts
    if not hosts:
        fmt.line(f"  {fmt.C.YELLOW}No hosts.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    command = (
        "echo \"$(nproc)|$(free -m | awk '/Mem:/ {printf \"%d|%d\", $3, $2}')|$(cat /proc/loadavg | awk '{print $1}')\""
    )

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=COST_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    fmt.table_header(("HOST", 14), ("CORES", 6), ("RAM", 10), ("USED%", 8), ("LOAD", 8), ("DENSITY", 10))

    for h in hosts:
        r = results.get(h.label)
        if not r or r.returncode != 0:
            continue

        parts = r.stdout.strip().split("|")
        if len(parts) < 4:
            continue

        try:
            cores = int(parts[0])
            ram_used = int(parts[1])
            ram_total = int(parts[2])
            load = float(parts[3])
        except ValueError:
            continue

        ram_pct = round(ram_used / max(ram_total, 1) * 100, 1)
        load_ratio = load / max(cores, 1)

        # Density score: average of RAM% and load ratio (normalized to 100)
        density = round((ram_pct + min(load_ratio * 100, 100)) / 2, 1)
        density_color = fmt.C.GREEN if density >= 60 else fmt.C.YELLOW if density >= 30 else fmt.C.RED
        density_label = "HIGH" if density >= 60 else ("MED" if density >= 30 else "LOW")

        fmt.table_row(
            (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 14),
            (str(cores), 6),
            (f"{ram_total}M", 10),
            (f"{ram_pct:.0f}%", 8),
            (f"{load:.1f}", 8),
            (f"{density_color}{density_label} ({density:.0f}%){fmt.C.RESET}", 10),
        )

    fmt.blank()
    fmt.footer()
    return 0


def _cmd_optimize(cfg: FreqConfig, args) -> int:
    """Generate cost optimization recommendations."""
    fmt.header("Cost Optimization")
    fmt.blank()

    vms = _gather_vm_resources(cfg)
    if not vms:
        fmt.line(f"  {fmt.C.DIM}No VM data available.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    recommendations = []
    for v in vms:
        if v["status"] != "running":
            recommendations.append(
                {
                    "vmid": v["vmid"],
                    "name": v["name"],
                    "type": "decommission",
                    "message": f"VM {v['vmid']} ({v['name']}) is stopped — consider removing",
                }
            )
        elif v["vcpu"] > 2 and v["cpu_usage"] < 5:
            recommendations.append(
                {
                    "vmid": v["vmid"],
                    "name": v["name"],
                    "type": "rightsize-cpu",
                    "message": f"VM {v['vmid']} ({v['name']}): reduce from {v['vcpu']} to {max(v['vcpu'] // 2, 1)} cores",
                }
            )
        elif v["ram_mb"] > 4096 and v["mem_usage"] < 15:
            recommendations.append(
                {
                    "vmid": v["vmid"],
                    "name": v["name"],
                    "type": "rightsize-ram",
                    "message": f"VM {v['vmid']} ({v['name']}): reduce from {v['ram_mb']}MB to {v['ram_mb'] // 2}MB",
                }
            )

    if not recommendations:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} No optimizations recommended — fleet is well-sized.{fmt.C.RESET}")
    else:
        for i, rec in enumerate(recommendations[:10], 1):
            icon = f"{fmt.C.YELLOW}{fmt.S.WARN}" if rec["type"].startswith("rightsize") else f"{fmt.C.RED}{fmt.S.CROSS}"
            fmt.line(f"  {icon}{fmt.C.RESET} {rec['message']}")

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}{len(recommendations)} recommendation(s){fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0


def _cmd_compare(cfg: FreqConfig, args) -> int:
    """Compare on-prem cost to cloud equivalent."""
    fmt.header("On-Prem vs Cloud Cost Comparison")
    fmt.blank()

    vms = _gather_vm_resources(cfg)
    if not vms:
        fmt.line(f"  {fmt.C.DIM}No VM data available.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    running = [v for v in vms if v["status"] == "running"]
    rate = getattr(args, "rate", 0.12) or 0.12

    total_onprem = 0
    total_aws = 0

    fmt.table_header(("VMID", 8), ("NAME", 16), ("SPECS", 14), ("ON-PREM", 10), ("AWS", 10), ("SAVINGS", 10))

    for v in running:
        vcpu = v["vcpu"]
        ram_gb = v["ram_mb"] / 1024

        onprem = _estimate_vm_monthly_cost(vcpu, ram_gb, rate)
        aws = _estimate_aws_cost(vcpu, ram_gb)
        savings = aws - onprem

        total_onprem += onprem
        total_aws += aws

        fmt.table_row(
            (str(v["vmid"]), 8),
            (f"{fmt.C.BOLD}{v['name']}{fmt.C.RESET}", 16),
            (f"{vcpu}c/{ram_gb:.0f}G", 14),
            (f"${onprem:.2f}", 10),
            (f"${aws:.2f}", 10),
            (f"{fmt.C.GREEN}${savings:.2f}{fmt.C.RESET}", 10),
        )

    fmt.blank()
    fmt.divider("Total Monthly Cost")
    fmt.blank()
    fmt.line(f"  On-prem:  ${total_onprem:.2f}/mo (power only, @${rate}/kWh)")
    fmt.line(f"  AWS:      {fmt.C.RED}${total_aws:.2f}/mo{fmt.C.RESET}")
    fmt.line(
        f"  Savings:  {fmt.C.GREEN}{fmt.C.BOLD}${total_aws - total_onprem:.2f}/mo{fmt.C.RESET} "
        f"({fmt.C.GREEN}{round((1 - total_onprem / max(total_aws, 1)) * 100)}% cheaper on-prem{fmt.C.RESET})"
    )
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Annual savings: ${(total_aws - total_onprem) * 12:.2f}{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
