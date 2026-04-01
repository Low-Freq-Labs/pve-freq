"""Full fleet inventory export for FREQ.

Commands: inventory

Auto-discovered CMDB. Every VM, every host, every IP, every container —
one structured output. JSON, CSV, or table. Feed it to anything.

Kills: ServiceNow ($50K/yr), Device42 ($1.5K/yr), Snipe-IT (manual entry)
"""
import csv
import io
import json
import time

from freq.core import fmt
from freq.core import log as logger
from freq.core.config import FreqConfig
from freq.core.ssh import run as ssh_run, run_many as ssh_run_many

# Timeouts
INV_CMD_TIMEOUT = 15
INV_PVE_TIMEOUT = 30
INV_QUICK_TIMEOUT = 10


def _gather_hosts(cfg: FreqConfig) -> list:
    """Gather host inventory from fleet."""
    hosts = cfg.hosts
    if not hosts:
        return []

    # Single compound SSH command to get everything
    command = (
        'echo "$('
        'hostname -f 2>/dev/null || hostname'
        ')|$('
        'cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d \'"\\"\''
        ')|$('
        'nproc'
        ')|$('
        "free -m | awk '/Mem:/ {print $2}'"
        ')|$('
        "df -BG / | awk 'NR==2 {print $2}' | tr -d 'G'"
        ')|$('
        'cat /proc/uptime | awk \'{d=int($1/86400); h=int(($1%86400)/3600); printf "%dd %dh", d, h}\''
        ')|$('
        'ip -4 addr show | grep "inet " | grep -v "127.0.0.1" | awk \'{print $2}\' | tr "\\n" "," | sed "s/,$//"'
        ')|$('
        'docker ps -q 2>/dev/null | wc -l || echo 0'
        ')|$('
        'uname -r'
        ')"'
    )

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=INV_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    inventory = []
    for h in hosts:
        r = results.get(h.label)
        entry = {
            "label": h.label,
            "ip": h.ip,
            "type": h.htype,
            "status": "down",
            "hostname": "",
            "os": "",
            "cores": 0,
            "ram_mb": 0,
            "disk_gb": 0,
            "uptime": "",
            "ips": "",
            "containers": 0,
            "kernel": "",
        }

        if r and r.returncode == 0:
            entry["status"] = "up"
            parts = r.stdout.strip().split("|")
            if len(parts) >= 9:
                entry["hostname"] = parts[0]
                entry["os"] = parts[1]
                try:
                    entry["cores"] = int(parts[2])
                except ValueError:
                    pass
                try:
                    entry["ram_mb"] = int(parts[3])
                except ValueError:
                    pass
                try:
                    entry["disk_gb"] = int(parts[4])
                except ValueError:
                    pass
                entry["uptime"] = parts[5]
                entry["ips"] = parts[6]
                try:
                    entry["containers"] = int(parts[7])
                except ValueError:
                    pass
                entry["kernel"] = parts[8]

        inventory.append(entry)

    return inventory


def _gather_vms(cfg: FreqConfig) -> list:
    """Gather VM inventory from PVE cluster."""
    if not cfg.pve_nodes:
        return []

    # Find a reachable PVE node
    node_ip = ""
    for ip in cfg.pve_nodes:
        r = ssh_run(
            host=ip, command="pvesh get /version --output-format json",
            key_path=cfg.ssh_key_path, connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=INV_QUICK_TIMEOUT, htype="pve", use_sudo=True,
        )
        if r.returncode == 0:
            node_ip = ip
            break

    if not node_ip:
        return []

    # Get all VMs across cluster
    r = ssh_run(
        host=node_ip,
        command="pvesh get /cluster/resources --type vm --output-format json 2>/dev/null",
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=INV_PVE_TIMEOUT,
        htype="pve", use_sudo=True,
    )

    if r.returncode != 0:
        return []

    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []

    vms = []
    for vm in data:
        vms.append({
            "vmid": vm.get("vmid", 0),
            "name": vm.get("name", ""),
            "status": vm.get("status", "unknown"),
            "node": vm.get("node", ""),
            "type": vm.get("type", "qemu"),
            "cores": vm.get("maxcpu", 0),
            "ram_mb": round(vm.get("maxmem", 0) / 1048576),
            "disk_gb": round(vm.get("maxdisk", 0) / 1073741824),
            "uptime": vm.get("uptime", 0),
            "tags": vm.get("tags", ""),
        })

    return sorted(vms, key=lambda v: v.get("vmid", 0))


def _gather_containers(cfg: FreqConfig) -> list:
    """Gather Docker container inventory from fleet hosts."""
    hosts = cfg.hosts
    if not hosts:
        return []

    command = (
        "docker ps -a --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}' 2>/dev/null || true"
    )

    results = ssh_run_many(
        hosts=hosts,
        command=command,
        key_path=cfg.ssh_key_path,
        connect_timeout=cfg.ssh_connect_timeout,
        command_timeout=INV_CMD_TIMEOUT,
        max_parallel=cfg.ssh_max_parallel,
        use_sudo=False,
    )

    containers = []
    for h in hosts:
        r = results.get(h.label)
        if r and r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().split("\n"):
                parts = line.split("|", 3)
                if len(parts) >= 3:
                    containers.append({
                        "host": h.label,
                        "name": parts[0],
                        "image": parts[1],
                        "status": parts[2],
                        "ports": parts[3] if len(parts) > 3 else "",
                    })

    return containers


def _to_csv(data: list) -> str:
    """Convert list of dicts to CSV string."""
    if not data:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)
    return output.getvalue()


def cmd_inventory(cfg: FreqConfig, pack, args) -> int:
    """Full fleet inventory export."""
    section = getattr(args, "section", None) or "all"
    output_format = "json" if getattr(args, "json", False) else "table"
    export_csv = getattr(args, "csv", False)

    if export_csv:
        output_format = "csv"

    fmt.header("Fleet Inventory")
    fmt.blank()

    start = time.monotonic()
    host_data = []
    vm_data = []
    container_data = []

    # Gather data based on section
    if section in ("all", "hosts"):
        fmt.step_start("Scanning fleet hosts")
        host_data = _gather_hosts(cfg)
        up = sum(1 for h in host_data if h["status"] == "up")
        fmt.step_ok(f"{len(host_data)} hosts ({up} up)")

    if section in ("all", "vms"):
        fmt.step_start("Scanning PVE cluster")
        vm_data = _gather_vms(cfg)
        running = sum(1 for v in vm_data if v["status"] == "running")
        fmt.step_ok(f"{len(vm_data)} VMs ({running} running)")

    if section in ("all", "containers"):
        fmt.step_start("Scanning Docker containers")
        container_data = _gather_containers(cfg)
        fmt.step_ok(f"{len(container_data)} containers")

    duration = time.monotonic() - start
    fmt.blank()

    # Output based on format
    if output_format == "json":
        result = {}
        if host_data:
            result["hosts"] = host_data
        if vm_data:
            result["vms"] = vm_data
        if container_data:
            result["containers"] = container_data
        result["meta"] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "duration": round(duration, 1),
            "host_count": len(host_data),
            "vm_count": len(vm_data),
            "container_count": len(container_data),
        }
        print(json.dumps(result, indent=2))
        return 0

    if output_format == "csv":
        if host_data:
            print("# HOSTS")
            print(_to_csv(host_data))
        if vm_data:
            print("# VMS")
            print(_to_csv(vm_data))
        if container_data:
            print("# CONTAINERS")
            print(_to_csv(container_data))
        return 0

    # Table output
    if host_data:
        fmt.divider(f"Fleet Hosts ({len(host_data)})")
        fmt.blank()
        fmt.table_header(
            ("LABEL", 14),
            ("IP", 16),
            ("TYPE", 8),
            ("STATUS", 8),
            ("OS", 22),
            ("CORES", 6),
            ("RAM", 8),
            ("DISK", 8),
            ("DOCKER", 8),
        )
        for h in host_data:
            status_badge = fmt.badge("up") if h["status"] == "up" else fmt.badge("down")
            ram_str = f"{h['ram_mb']}M" if h["ram_mb"] else "-"
            disk_str = f"{h['disk_gb']}G" if h["disk_gb"] else "-"
            fmt.table_row(
                (f"{fmt.C.BOLD}{h['label']}{fmt.C.RESET}", 14),
                (h["ip"], 16),
                (h["type"], 8),
                (status_badge, 8),
                (h["os"][:22], 22),
                (str(h["cores"]) if h["cores"] else "-", 6),
                (ram_str, 8),
                (disk_str, 8),
                (str(h["containers"]) if h["status"] == "up" else "-", 8),
            )
        fmt.blank()

    if vm_data:
        fmt.divider(f"Virtual Machines ({len(vm_data)})")
        fmt.blank()
        fmt.table_header(
            ("VMID", 8),
            ("NAME", 20),
            ("STATUS", 10),
            ("NODE", 10),
            ("CORES", 6),
            ("RAM", 8),
            ("DISK", 8),
            ("TAGS", 16),
        )
        for v in vm_data:
            status_color = fmt.C.GREEN if v["status"] == "running" else fmt.C.RED
            ram_str = f"{v['ram_mb']}M" if v["ram_mb"] else "-"
            disk_str = f"{v['disk_gb']}G" if v["disk_gb"] else "-"
            fmt.table_row(
                (str(v["vmid"]), 8),
                (f"{fmt.C.BOLD}{v['name']}{fmt.C.RESET}", 20),
                (f"{status_color}{v['status']}{fmt.C.RESET}", 10),
                (v["node"], 10),
                (str(v["cores"]), 6),
                (ram_str, 8),
                (disk_str, 8),
                (v.get("tags", "")[:16], 16),
            )
        fmt.blank()

    if container_data:
        fmt.divider(f"Docker Containers ({len(container_data)})")
        fmt.blank()
        fmt.table_header(
            ("HOST", 14),
            ("NAME", 22),
            ("IMAGE", 24),
            ("STATUS", 20),
        )
        for c in container_data:
            status = c["status"]
            color = fmt.C.GREEN if "Up" in status else fmt.C.RED
            fmt.table_row(
                (c["host"], 14),
                (f"{fmt.C.BOLD}{c['name']}{fmt.C.RESET}", 22),
                (c["image"][:24], 24),
                (f"{color}{status[:20]}{fmt.C.RESET}", 20),
            )
        fmt.blank()

    # Summary
    fmt.divider("Summary")
    fmt.blank()
    total = len(host_data) + len(vm_data) + len(container_data)
    fmt.line(f"  {fmt.C.BOLD}{total}{fmt.C.RESET} total assets  "
             f"({len(host_data)} hosts, {len(vm_data)} VMs, {len(container_data)} containers)")
    fmt.line(f"  Scanned in {duration:.1f}s")
    fmt.blank()
    fmt.line(f"  {fmt.C.DIM}Export: freq inventory --json | freq inventory --csv{fmt.C.RESET}")
    fmt.blank()
    fmt.footer()
    return 0
