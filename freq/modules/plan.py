"""Declarative fleet management — freq plan / freq apply.

Reads a TOML fleet plan, compares against PVE cluster state,
and generates a terraform-style diff. Apply executes the changes.
"""
import os
import tomllib

from freq.core.config import FreqConfig
from freq.core import fmt
from freq.core import log as logger


# --- Plan Data Structures ---

def _load_plan(plan_path: str) -> list:
    """Load VM definitions from a TOML plan file.

    Expected format:
        [[vm]]
        name = "web-01"
        cores = 4
        ram = 4096
        disk = 64
        node = "pve01"
        image = "debian-13"
        vlan = "lan"
        ip = "10.0.0.100/24"
        start = true

    Returns list of dicts, each representing a desired VM.
    """
    if not os.path.isfile(plan_path):
        return []

    with open(plan_path, "rb") as f:
        data = tomllib.load(f)

    vms = data.get("vm", [])
    # Normalize: ensure each VM has required fields with defaults
    result = []
    for vm in vms:
        entry = {
            "name": vm.get("name", ""),
            "cores": vm.get("cores", 2),
            "ram": vm.get("ram", 2048),
            "disk": vm.get("disk", 32),
            "node": vm.get("node", ""),
            "image": vm.get("image", ""),
            "vlan": vm.get("vlan", ""),
            "ip": vm.get("ip", ""),
            "start": vm.get("start", True),
            "tags": vm.get("tags", ""),
            "profile": vm.get("profile", ""),
        }
        if entry["name"]:
            result.append(entry)
    return result


def _query_cluster_vms(cfg: FreqConfig) -> list:
    """Query PVE cluster for all VMs.

    Returns list of dicts: {vmid, name, status, cores, ram, disk, node}
    """
    from freq.core.ssh import run as ssh_run

    vms = []
    for i, node_ip in enumerate(cfg.pve_nodes):
        node_name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"node{i}"

        r = ssh_run(
            host=node_ip,
            command="sudo qm list 2>/dev/null | tail -n +2",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=30,
            htype="pve",
            use_sudo=False,
        )
        if r.returncode != 0:
            continue

        for line in r.stdout.strip().split("\n"):
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                vmid = int(parts[0])
            except ValueError:
                continue

            name = parts[1]
            status = parts[2]

            # Get config for cores/ram
            cr = ssh_run(
                host=node_ip,
                command=f"sudo qm config {vmid} 2>/dev/null | grep -E '^(cores|memory|scsi0):' ",
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=15,
                htype="pve",
                use_sudo=False,
            )
            cores = 0
            ram = 0
            disk = 0
            if cr.returncode == 0:
                for cline in cr.stdout.strip().split("\n"):
                    if cline.startswith("cores:"):
                        try:
                            cores = int(cline.split(":")[1].strip())
                        except ValueError:
                            pass
                    elif cline.startswith("memory:"):
                        try:
                            ram = int(cline.split(":")[1].strip())
                        except ValueError:
                            pass
                    elif cline.startswith("scsi0:"):
                        # Extract disk size from scsi0 line
                        import re
                        m = re.search(r"size=(\d+)([GT])", cline)
                        if m:
                            disk = int(m.group(1))
                            if m.group(2) == "T":
                                disk *= 1024

            vms.append({
                "vmid": vmid,
                "name": name,
                "status": status,
                "cores": cores,
                "ram": ram,
                "disk": disk,
                "node": node_name,
            })

    return vms


def _compute_diff(desired: list, current: list) -> dict:
    """Compare desired VMs against current cluster state.

    Returns:
        {
            "create": [list of VMs to create],
            "resize": [list of {vm, changes}],
            "unchanged": [list of VMs that match],
            "unmanaged": [list of current VMs not in plan],
        }
    """
    # Index current VMs by name
    current_by_name = {}
    for vm in current:
        current_by_name[vm["name"]] = vm

    # Track which current VMs are accounted for
    matched_names = set()

    create = []
    resize = []
    unchanged = []

    for desired_vm in desired:
        name = desired_vm["name"]
        if name not in current_by_name:
            create.append(desired_vm)
            continue

        matched_names.add(name)
        cur = current_by_name[name]

        # Check for differences
        changes = {}
        if desired_vm["cores"] and desired_vm["cores"] != cur.get("cores", 0):
            changes["cores"] = {"from": cur.get("cores", 0), "to": desired_vm["cores"]}
        if desired_vm["ram"] and desired_vm["ram"] != cur.get("ram", 0):
            changes["ram"] = {"from": cur.get("ram", 0), "to": desired_vm["ram"]}
        # Disk can only grow
        if desired_vm["disk"] and desired_vm["disk"] > cur.get("disk", 0) and cur.get("disk", 0) > 0:
            changes["disk"] = {"from": cur.get("disk", 0), "to": desired_vm["disk"]}

        if changes:
            resize.append({"vm": desired_vm, "current": cur, "changes": changes})
        else:
            unchanged.append({"desired": desired_vm, "current": cur})

    # Find unmanaged VMs (in cluster but not in plan)
    unmanaged = [vm for vm in current if vm["name"] not in matched_names]

    return {
        "create": create,
        "resize": resize,
        "unchanged": unchanged,
        "unmanaged": unmanaged,
    }


def _render_plan(diff: dict, dry_run: bool = True) -> None:
    """Render terraform-style plan output."""
    creates = diff["create"]
    resizes = diff["resize"]
    unchanged = diff["unchanged"]
    unmanaged = diff["unmanaged"]

    if not creates and not resizes:
        fmt.line(f"  {fmt.C.GREEN}No changes.{fmt.C.RESET} Fleet matches plan.")
        fmt.blank()
        fmt.line(f"  {len(unchanged)} managed VM(s) up to date")
        fmt.line(f"  {len(unmanaged)} unmanaged VM(s) in cluster")
        return

    # Creates
    for vm in creates:
        fmt.line(f"  {fmt.C.GREEN}+ {vm['name']}{fmt.C.RESET}")
        fmt.line(f"      cores: {vm['cores']}")
        fmt.line(f"      ram:   {vm['ram']}MB")
        fmt.line(f"      disk:  {vm['disk']}GB")
        if vm.get("node"):
            fmt.line(f"      node:  {vm['node']}")
        if vm.get("image"):
            fmt.line(f"      image: {vm['image']}")
        if vm.get("ip"):
            fmt.line(f"      ip:    {vm['ip']}")
        fmt.blank()

    # Resizes
    for entry in resizes:
        vm = entry["vm"]
        changes = entry["changes"]
        fmt.line(f"  {fmt.C.YELLOW}~ {vm['name']}{fmt.C.RESET}")
        for key, vals in changes.items():
            unit = "MB" if key == "ram" else "GB" if key == "disk" else ""
            fmt.line(f"      {key}: {vals['from']}{unit} -> {vals['to']}{unit}")
        fmt.blank()

    # Summary
    fmt.line(f"  {fmt.C.BOLD}Plan:{fmt.C.RESET} "
             f"{fmt.C.GREEN}{len(creates)} to create{fmt.C.RESET}, "
             f"{fmt.C.YELLOW}{len(resizes)} to resize{fmt.C.RESET}, "
             f"{len(unchanged)} unchanged, "
             f"{len(unmanaged)} unmanaged")


def cmd_plan(cfg: FreqConfig, pack, args) -> int:
    """Show execution plan — compare fleet plan against cluster state."""
    fmt.header("Fleet Plan")
    fmt.blank()

    # Find plan file
    plan_path = getattr(args, "file", None) or os.path.join(cfg.conf_dir, "fleet-plan.toml")

    if not os.path.isfile(plan_path):
        fmt.error(f"No plan file found at {plan_path}")
        fmt.info("Create a fleet plan: conf/fleet-plan.toml")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Example:{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}[[vm]]{fmt.C.RESET}")
        fmt.line(f'  {fmt.C.DIM}name = "web-01"{fmt.C.RESET}')
        fmt.line(f"  {fmt.C.DIM}cores = 4{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}ram = 4096{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}disk = 64{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 1

    # Load plan
    fmt.step_start("Loading fleet plan")
    desired = _load_plan(plan_path)
    if not desired:
        fmt.step_fail("No VMs defined in plan")
        fmt.footer()
        return 1
    fmt.step_ok(f"Loaded {len(desired)} VM definition(s)")

    # Query cluster
    fmt.step_start("Querying PVE cluster")
    if not cfg.pve_nodes:
        fmt.step_fail("No PVE nodes configured")
        fmt.footer()
        return 1
    current = _query_cluster_vms(cfg)
    fmt.step_ok(f"Found {len(current)} VM(s) in cluster")

    fmt.blank()

    # Compute and render diff
    diff = _compute_diff(desired, current)
    _render_plan(diff)

    # Store diff for apply (non-fatal if dir not writable)
    try:
        _save_plan_cache(cfg, diff, plan_path)
    except OSError:
        pass

    fmt.blank()
    fmt.footer()
    return 0


def cmd_apply(cfg: FreqConfig, pack, args) -> int:
    """Apply fleet plan — execute creates and resizes."""
    fmt.header("Fleet Apply")
    fmt.blank()

    # Load cached plan or recompute
    plan_path = getattr(args, "file", None) or os.path.join(cfg.conf_dir, "fleet-plan.toml")
    dry_run = getattr(args, "dry_run", False)

    if not os.path.isfile(plan_path):
        fmt.error(f"No plan file found at {plan_path}")
        fmt.footer()
        return 1

    desired = _load_plan(plan_path)
    if not desired:
        fmt.error("No VMs defined in plan")
        fmt.footer()
        return 1

    if not cfg.pve_nodes:
        fmt.error("No PVE nodes configured")
        fmt.footer()
        return 1

    # Always recompute for safety
    fmt.step_start("Computing changes")
    current = _query_cluster_vms(cfg)
    diff = _compute_diff(desired, current)
    fmt.step_ok("Done")

    creates = diff["create"]
    resizes = diff["resize"]

    if not creates and not resizes:
        fmt.blank()
        fmt.line(f"  {fmt.C.GREEN}Nothing to do.{fmt.C.RESET} Fleet matches plan.")
        fmt.blank()
        fmt.footer()
        return 0

    # Show plan
    fmt.blank()
    _render_plan(diff)
    fmt.blank()

    if dry_run:
        fmt.info("Dry run — no changes made.")
        fmt.footer()
        return 0

    # Confirm
    if not getattr(args, "yes", False):
        answer = input("  Apply these changes? [y/N]: ").strip().lower()
        if answer != "y":
            fmt.info("Cancelled.")
            fmt.footer()
            return 0

    fmt.blank()

    from freq.core.ssh import run as ssh_run

    errors = 0

    # Execute creates
    for vm in creates:
        fmt.step_start(f"Creating {vm['name']}")

        # Pick target node
        node_ip = ""
        if vm.get("node"):
            for i, nn in enumerate(cfg.pve_node_names):
                if nn == vm["node"] and i < len(cfg.pve_nodes):
                    node_ip = cfg.pve_nodes[i]
                    break
        if not node_ip and cfg.pve_nodes:
            node_ip = cfg.pve_nodes[0]

        if not node_ip:
            fmt.step_fail(f"No node found for {vm['name']}")
            errors += 1
            continue

        # Get next VMID
        r = ssh_run(
            host=node_ip,
            command="sudo pvesh get /cluster/nextid 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=15,
            htype="pve",
            use_sudo=False,
        )
        vmid = r.stdout.strip().strip('"') if r.returncode == 0 else ""
        if not vmid:
            fmt.step_fail(f"Cannot get next VMID for {vm['name']}")
            errors += 1
            continue

        # Build create command
        parts = [
            f"sudo qm create {vmid}",
            f"--name {vm['name']}",
            f"--cores {vm['cores']}",
            f"--memory {vm['ram']}",
            f"--cpu {cfg.vm_cpu}",
            f"--machine {cfg.vm_machine}",
            f"--scsihw {getattr(cfg, 'vm_scsihw', 'virtio-scsi-single')}",
        ]

        # Add NIC
        bridge = cfg.nic_bridge or "vmbr0"
        vlan_tag = ""
        if vm.get("vlan"):
            for v in cfg.vlans:
                if v.name.lower() == vm["vlan"].lower():
                    vlan_tag = f",tag={v.id}"
                    break
        parts.append(f"--net0 virtio,bridge={bridge}{vlan_tag}")

        cmd = " ".join(parts)
        r = ssh_run(
            host=node_ip,
            command=cmd,
            key_path=cfg.ssh_key_path,
            connect_timeout=cfg.ssh_connect_timeout,
            command_timeout=120,
            htype="pve",
            use_sudo=False,
        )

        if r.returncode == 0:
            fmt.step_ok(f"Created VM {vmid} '{vm['name']}'")
            logger.info(f"plan-apply: created VM {vmid} {vm['name']}", node=node_ip)

            # Start if requested
            if vm.get("start", True):
                ssh_run(
                    host=node_ip,
                    command=f"sudo qm start {vmid} 2>/dev/null",
                    key_path=cfg.ssh_key_path,
                    connect_timeout=cfg.ssh_connect_timeout,
                    command_timeout=30,
                    htype="pve",
                    use_sudo=False,
                )
        else:
            fmt.step_fail(f"Failed to create {vm['name']}: {r.stdout.strip()}")
            errors += 1

    # Execute resizes
    for entry in resizes:
        vm = entry["vm"]
        cur = entry["current"]
        changes = entry["changes"]
        vmid = cur["vmid"]

        fmt.step_start(f"Resizing {vm['name']} (VM {vmid})")

        node_ip = ""
        for i, nn in enumerate(cfg.pve_node_names):
            if nn == cur.get("node", "") and i < len(cfg.pve_nodes):
                node_ip = cfg.pve_nodes[i]
                break
        if not node_ip and cfg.pve_nodes:
            node_ip = cfg.pve_nodes[0]

        if not node_ip:
            fmt.step_fail(f"No node found for {vm['name']}")
            errors += 1
            continue

        # CPU/RAM changes
        set_parts = []
        if "cores" in changes:
            set_parts.append(f"--cores {changes['cores']['to']}")
        if "ram" in changes:
            set_parts.append(f"--memory {changes['ram']['to']}")

        if set_parts:
            cmd = f"sudo qm set {vmid} {' '.join(set_parts)}"
            r = ssh_run(
                host=node_ip,
                command=cmd,
                key_path=cfg.ssh_key_path,
                connect_timeout=cfg.ssh_connect_timeout,
                command_timeout=30,
                htype="pve",
                use_sudo=False,
            )
            if r.returncode != 0:
                fmt.step_fail(f"Failed to resize CPU/RAM: {r.stdout.strip()}")
                errors += 1
                continue

        # Disk expand
        if "disk" in changes:
            grow = changes["disk"]["to"] - changes["disk"]["from"]
            if grow > 0:
                cmd = f"sudo qm disk resize {vmid} scsi0 +{grow}G"
                r = ssh_run(
                    host=node_ip,
                    command=cmd,
                    key_path=cfg.ssh_key_path,
                    connect_timeout=cfg.ssh_connect_timeout,
                    command_timeout=60,
                    htype="pve",
                    use_sudo=False,
                )
                if r.returncode != 0:
                    fmt.step_fail(f"Failed to expand disk: {r.stdout.strip()}")
                    errors += 1
                    continue

        fmt.step_ok(f"Resized {vm['name']} (VM {vmid})")
        logger.info(f"plan-apply: resized VM {vmid} {vm['name']}", changes=str(changes))

    fmt.blank()
    if errors:
        fmt.warn(f"{errors} operation(s) failed")
    else:
        fmt.line(f"  {fmt.C.GREEN}All changes applied successfully.{fmt.C.RESET}")

    fmt.blank()
    fmt.footer()
    return 1 if errors else 0


def _save_plan_cache(cfg: FreqConfig, diff: dict, plan_path: str) -> None:
    """Cache the computed diff for quick apply."""
    import json

    cache_dir = os.path.join(cfg.data_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    cache = {
        "plan_path": plan_path,
        "create_count": len(diff["create"]),
        "resize_count": len(diff["resize"]),
        "unchanged_count": len(diff["unchanged"]),
        "unmanaged_count": len(diff["unmanaged"]),
    }

    with open(os.path.join(cache_dir, "last_plan.json"), "w") as f:
        json.dump(cache, f)
