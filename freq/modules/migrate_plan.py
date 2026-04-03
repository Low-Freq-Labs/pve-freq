"""Load-aware VM migration planning for FREQ.

Domain: freq dr <migrate-plan-show|migrate-plan-apply>

Analyzes PVE cluster resource usage and recommends VM migrations to balance
load across nodes. "pve02 is at 90% RAM, move VM 302 to pve03." Not just
data — actionable proposals with one-command execution.

Replaces: Nutanix ($$$) auto-balancing, Scale Computing ($$$),
          manual spreadsheet capacity planning

Architecture:
    - Resource gathering via PVE API (pvesh /cluster/resources)
    - Per-node CPU/RAM/disk utilization calculated from cluster data
    - Migration candidates selected by resource pressure delta
    - Apply executes qm migrate via SSH on the source PVE node

Design decisions:
    - Plan is advisory by default; apply requires explicit confirmation.
      Migrations move live VMs — never auto-execute without human intent.
"""

import json

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run

PVE_CMD_TIMEOUT = 30
PVE_QUICK_TIMEOUT = 10


def _find_reachable_node(cfg: FreqConfig) -> str:
    """Find a reachable PVE node."""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip,
            command="pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=PVE_QUICK_TIMEOUT,
            htype="pve",
            use_sudo=True,
        )
        if r.returncode == 0:
            return ip
    return ""


def _pve_cmd(cfg, node_ip, command, timeout=PVE_CMD_TIMEOUT):
    """Execute PVE command."""
    r = ssh_run(
        host=node_ip,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=timeout,
        htype="pve",
        use_sudo=True,
    )
    return r.stdout, r.returncode == 0


def _gather_node_resources(cfg: FreqConfig, node_ip: str) -> list:
    """Get resource usage per PVE node."""
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/resources --type node --output-format json")
    if not ok:
        return []

    try:
        nodes = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    result = []
    for node in nodes:
        if node.get("status") != "online":
            continue
        result.append(
            {
                "node": node.get("node", ""),
                "maxcpu": node.get("maxcpu", 0),
                "cpu_used": round(node.get("cpu", 0) * 100, 1),
                "maxmem": node.get("maxmem", 0),
                "mem_used": node.get("mem", 0),
                "mem_pct": round(node.get("mem", 0) / max(node.get("maxmem", 1), 1) * 100, 1),
                "maxdisk": node.get("maxdisk", 0),
                "disk_used": node.get("disk", 0),
            }
        )

    return result


def _gather_vm_resources(cfg: FreqConfig, node_ip: str) -> list:
    """Get per-VM resource allocation."""
    stdout, ok = _pve_cmd(cfg, node_ip, "pvesh get /cluster/resources --type vm --output-format json")
    if not ok:
        return []

    try:
        vms = json.loads(stdout)
    except json.JSONDecodeError:
        return []

    result = []
    for vm in vms:
        if vm.get("status") != "running":
            continue
        result.append(
            {
                "vmid": vm.get("vmid", 0),
                "name": vm.get("name", ""),
                "node": vm.get("node", ""),
                "cpu": vm.get("maxcpu", 0),
                "mem_bytes": vm.get("maxmem", 0),
                "mem_mb": round(vm.get("maxmem", 0) / 1048576),
                "disk_bytes": vm.get("maxdisk", 0),
                "actual_cpu_pct": round(vm.get("cpu", 0) * 100, 1),
                "actual_mem_pct": round(vm.get("mem", 0) / max(vm.get("maxmem", 1), 1) * 100, 1)
                if vm.get("maxmem", 0) > 0
                else 0,
            }
        )

    return sorted(result, key=lambda v: v.get("mem_mb", 0), reverse=True)


def _generate_recommendations(nodes: list, vms: list) -> list:
    """Generate migration recommendations based on load imbalance."""
    if len(nodes) < 2:
        return []

    # Find imbalanced nodes
    avg_mem = sum(n["mem_pct"] for n in nodes) / len(nodes)
    recommendations = []

    # Find overloaded and underloaded nodes
    overloaded = [n for n in nodes if n["mem_pct"] > avg_mem + 10]
    underloaded = sorted([n for n in nodes if n["mem_pct"] < avg_mem - 5], key=lambda n: n["mem_pct"])

    if not overloaded or not underloaded:
        return []

    for hot_node in overloaded:
        # Find VMs on this node, sorted by RAM (smallest first — easier to move)
        node_vms = sorted(
            [v for v in vms if v["node"] == hot_node["node"]],
            key=lambda v: v["mem_mb"],
        )

        for vm in node_vms:
            # Skip very small VMs (not worth migrating)
            if vm["mem_mb"] < 256:
                continue

            # Find best target node
            for target in underloaded:
                if target["node"] == hot_node["node"]:
                    continue

                # Check if target has enough headroom
                vm_mem_fraction = vm["mem_bytes"] / max(target["maxmem"], 1) * 100
                projected_mem = target["mem_pct"] + vm_mem_fraction

                if projected_mem < 85:  # Don't overload the target
                    savings = vm["mem_bytes"] / max(hot_node["maxmem"], 1) * 100

                    recommendations.append(
                        {
                            "vmid": vm["vmid"],
                            "vm_name": vm["name"],
                            "vm_ram_mb": vm["mem_mb"],
                            "from_node": hot_node["node"],
                            "from_mem_pct": hot_node["mem_pct"],
                            "to_node": target["node"],
                            "to_mem_pct": target["mem_pct"],
                            "projected_from": round(hot_node["mem_pct"] - savings, 1),
                            "projected_to": round(projected_mem, 1),
                            "impact": f"Frees ~{savings:.1f}% RAM on {hot_node['node']}",
                        }
                    )
                    break  # One recommendation per VM

            if len(recommendations) >= 5:  # Cap at 5 suggestions
                break

    return recommendations


def cmd_migrate_plan(cfg: FreqConfig, pack, args) -> int:
    """Load-aware migration planning."""
    action = getattr(args, "action", None) or "show"

    if action == "show":
        return _cmd_show(cfg, args)

    fmt.error(f"Unknown migrate-plan action: {action}")
    return 1


def _cmd_show(cfg: FreqConfig, args) -> int:
    """Show migration recommendations."""
    fmt.header("Migration Planner")
    fmt.blank()

    fmt.step_start("Connecting to PVE cluster")
    node_ip = _find_reachable_node(cfg)
    if not node_ip:
        fmt.step_fail("Cannot reach any PVE node")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok(f"Connected to {node_ip}")

    # Gather data
    fmt.step_start("Analyzing node resources")
    nodes = _gather_node_resources(cfg, node_ip)
    if not nodes:
        fmt.step_fail("No node data available")
        fmt.blank()
        fmt.footer()
        return 1
    fmt.step_ok(f"{len(nodes)} nodes online")

    fmt.step_start("Analyzing VM allocation")
    vms = _gather_vm_resources(cfg, node_ip)
    fmt.step_ok(f"{len(vms)} running VMs")
    fmt.blank()

    # Node overview
    fmt.divider("Node Resources")
    fmt.blank()

    avg_mem = sum(n["mem_pct"] for n in nodes) / len(nodes) if nodes else 0

    fmt.table_header(
        ("NODE", 12),
        ("CPU", 8),
        ("RAM %", 10),
        ("RAM USED", 12),
        ("RAM TOTAL", 12),
        ("BALANCE", 10),
    )

    for node in sorted(nodes, key=lambda n: n["mem_pct"], reverse=True):
        mem_color = fmt.C.RED if node["mem_pct"] > 85 else fmt.C.YELLOW if node["mem_pct"] > 70 else ""
        diff = node["mem_pct"] - avg_mem
        balance = (
            f"{fmt.C.RED}+{diff:.1f}%{fmt.C.RESET}"
            if diff > 5
            else f"{fmt.C.GREEN}{diff:+.1f}%{fmt.C.RESET}"
            if diff < -5
            else f"{fmt.C.DIM}{diff:+.1f}%{fmt.C.RESET}"
        )

        mem_used_gb = round(node["mem_used"] / 1073741824, 1)
        mem_total_gb = round(node["maxmem"] / 1073741824, 1)

        fmt.table_row(
            (f"{fmt.C.BOLD}{node['node']}{fmt.C.RESET}", 12),
            (f"{node['cpu_used']:.0f}%", 8),
            (f"{mem_color}{node['mem_pct']:.1f}%{fmt.C.RESET}" if mem_color else f"{node['mem_pct']:.1f}%", 10),
            (f"{mem_used_gb}G", 12),
            (f"{mem_total_gb}G", 12),
            (balance, 10),
        )

    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Fleet average RAM: {avg_mem:.1f}%{fmt.C.RESET}")
    fmt.blank()

    # Recommendations
    recommendations = _generate_recommendations(nodes, vms)

    fmt.divider("Recommendations")
    fmt.blank()

    if not recommendations:
        fmt.line(f"  {fmt.C.GREEN}{fmt.S.TICK} Fleet is balanced — no migrations needed.{fmt.C.RESET}")
    else:
        for i, rec in enumerate(recommendations, 1):
            fmt.line(
                f"  {fmt.C.CYAN}{i}.{fmt.C.RESET} Move "
                f"{fmt.C.BOLD}VM {rec['vmid']} ({rec['vm_name']}){fmt.C.RESET} "
                f"[{rec['vm_ram_mb']}MB RAM]"
            )
            fmt.line(
                f"     {rec['from_node']} ({rec['from_mem_pct']:.1f}% → "
                f"{rec['projected_from']:.1f}%) → "
                f"{rec['to_node']} ({rec['to_mem_pct']:.1f}% → "
                f"{rec['projected_to']:.1f}%)"
            )
            fmt.line(f"     {fmt.C.DIM}{rec['impact']}{fmt.C.RESET}")
            fmt.blank()

        fmt.line(f"  {fmt.C.DIM}Execute: freq migrate <vmid> --node <target>{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 0
