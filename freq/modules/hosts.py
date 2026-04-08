"""Fleet host registry management for FREQ.

Domain: freq host <list|add|remove|sync|groups-list|groups-add|groups-remove>

Manages the fleet host registry (hosts.conf). Add, remove, list, and group
hosts. Sync auto-discovers hosts from PVE cluster API and agent endpoints.
Groups enable targeted operations (e.g., freq fleet exec --group prod).

Replaces: Ansible inventory files ($0 but hand-maintained YAML/INI),
          /etc/hosts management scripts

Architecture:
    - Host registry stored in conf/hosts.conf (label|ip|type|groups format)
    - PVE sync queries pvesh for VM/container IPs on cluster nodes
    - Agent sync polls freq-agent endpoints for self-reported hosts
    - Validation via freq/core/validate.py (IP format, label uniqueness)

Design decisions:
    - hosts.conf is a flat file, not TOML/YAML. Easy to grep, easy to edit
      by hand, easy to version control. Structured formats add no value here.
"""

import json
import os
import shutil

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import resolve
from freq.core import validate

# ─────────────────────────────────────────────────────────────
# CONSTANTS — Timeouts for PVE and agent sync operations
# ─────────────────────────────────────────────────────────────

HOSTS_PVE_TIMEOUT = 15
HOSTS_AGENT_TIMEOUT = 10


# ─────────────────────────────────────────────────────────────
# HOST REGISTRY — List, add, remove fleet hosts
# ─────────────────────────────────────────────────────────────


def cmd_hosts(cfg: FreqConfig, pack, args) -> int:
    """List, add, remove, or sync fleet hosts."""
    action = getattr(args, "action", "list")

    if action == "list":
        return _hosts_list(cfg, args)
    elif action == "add":
        return _hosts_add(cfg)
    elif action == "remove":
        return _hosts_remove(cfg)
    elif action == "sync":
        dry_run = getattr(args, "dry_run", False)
        return _hosts_sync(cfg, dry_run=dry_run)
    else:
        fmt.error(f"Unknown host action: {action}. Available: list, add, remove, sync")
        return 1


def cmd_groups(cfg: FreqConfig, pack, args) -> int:
    """List, add, or remove host groups."""
    action = getattr(args, "action", "list")

    if action == "list":
        return _groups_list(cfg)
    elif action == "add":
        return _groups_add(cfg, args)
    elif action == "remove":
        return _groups_remove(cfg, args)
    else:
        fmt.error(f"Unknown groups action: {action}")
        fmt.info("Usage: freq groups [list|add|remove] --target <host> --group <name>")
        return 1


def _hosts_list(cfg: FreqConfig, args=None) -> int:
    """Display all registered fleet hosts."""
    hosts = cfg.hosts

    # JSON output mode
    if getattr(args, "json_output", False):
        import json as _json

        data = [{"label": h.label, "ip": h.ip, "type": h.htype,
                 "groups": h.groups, "vmid": getattr(h, "vmid", 0),
                 "all_ips": getattr(h, "all_ips", [])} for h in hosts]
        print(_json.dumps({"hosts": data, "count": len(data)}, indent=2))
        return 0

    fmt.header("Fleet Hosts")
    fmt.blank()

    if not hosts:
        fmt.line(f"{fmt.C.YELLOW}No hosts registered.{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Add hosts with: freq hosts add{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Or discover with: freq discover{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # Summary
    types = resolve.all_types(hosts)
    type_str = "  ".join(f"{fmt.C.CYAN}{t}{fmt.C.RESET}: {c}" for t, c in sorted(types.items()))
    fmt.line(f"{fmt.C.BOLD}{len(hosts)} hosts{fmt.C.RESET}  ({type_str})")
    fmt.blank()

    # Table
    # Check if any host has multi-IP data
    has_multi_ip = any(getattr(h, "all_ips", []) for h in hosts)

    if has_multi_ip:
        fmt.table_header(
            ("LABEL", 18),
            ("IP", 17),
            ("TYPE", 10),
            ("GROUPS", 20),
            ("ALL IPs", 40),
        )
    else:
        fmt.table_header(
            ("LABEL", 18),
            ("IP", 17),
            ("TYPE", 10),
            ("GROUPS", 25),
        )

    for h in hosts:
        type_color = {
            "pve": fmt.C.PURPLE,
            "linux": fmt.C.GREEN,
            "truenas": fmt.C.BLUE,
            "pfsense": fmt.C.ORANGE,
            "docker": fmt.C.CYAN,
            "idrac": fmt.C.YELLOW,
            "switch": fmt.C.MAGENTA,
        }.get(h.htype, fmt.C.GRAY)

        all_ips = getattr(h, "all_ips", []) or []
        # Show additional IPs (skip the primary — it's already in column 2)
        extra_ips = [ip for ip in all_ips if ip != h.ip]

        if has_multi_ip:
            ips_str = ", ".join(extra_ips) if extra_ips else ""
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 18),
                (h.ip, 17),
                (f"{type_color}{h.htype}{fmt.C.RESET}", 10),
                (f"{fmt.C.DIM}{h.groups}{fmt.C.RESET}" if h.groups else f"{fmt.C.DARK_GRAY}—{fmt.C.RESET}", 20),
                (f"{fmt.C.DIM}{ips_str}{fmt.C.RESET}" if ips_str else "", 40),
            )
        else:
            fmt.table_row(
                (f"{fmt.C.BOLD}{h.label}{fmt.C.RESET}", 18),
                (h.ip, 17),
                (f"{type_color}{h.htype}{fmt.C.RESET}", 10),
                (f"{fmt.C.DIM}{h.groups}{fmt.C.RESET}" if h.groups else f"{fmt.C.DARK_GRAY}—{fmt.C.RESET}", 25),
            )

    fmt.blank()
    fmt.footer()
    return 0


def _hosts_add(cfg: FreqConfig) -> int:
    """Interactive host addition."""
    fmt.header("Add Host")
    fmt.blank()

    # Get IP
    try:
        ip = input(f"  {fmt.C.CYAN}IP address:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    if not validate.ip(ip):
        fmt.error(f"Invalid IP address: {ip}")
        return 1

    # Check for duplicates
    if resolve.by_ip(cfg.hosts, ip):
        fmt.error(f"Host with IP {ip} already registered.")
        return 1

    # Get label
    try:
        label = input(f"  {fmt.C.CYAN}Label:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    if not validate.label(label):
        fmt.error(f"Invalid label: {label}")
        return 1

    if resolve.by_label(cfg.hosts, label):
        fmt.error(f"Host with label '{label}' already registered.")
        return 1

    # Get type
    valid_types = ["linux", "pve", "truenas", "pfsense", "docker", "idrac", "switch"]
    try:
        htype = input(f"  {fmt.C.CYAN}Type ({', '.join(valid_types)}):{fmt.C.RESET} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    if htype not in valid_types:
        fmt.error(f"Invalid type: {htype}. Must be one of: {', '.join(valid_types)}")
        return 1

    # Get groups (optional)
    try:
        groups = input(f"  {fmt.C.CYAN}Groups (comma-separated, optional):{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    # Write to fleet registry
    from freq.core.config import Host, append_host_toml

    host = Host(ip=ip, label=label, htype=htype, groups=groups)
    append_host_toml(cfg.hosts_file, host)
    cfg.hosts.append(host)

    fmt.success(f"Host '{label}' ({ip}) added to fleet as {htype}")
    return 0


def _hosts_remove(cfg: FreqConfig) -> int:
    """Remove a host from the fleet."""
    fmt.header("Remove Host")
    fmt.blank()

    try:
        target = input(f"  {fmt.C.CYAN}Host label or IP to remove:{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    # Confirm
    try:
        confirm = input(f"  {fmt.C.YELLOW}Remove '{host.label}' ({host.ip})? [y/N]:{fmt.C.RESET} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    if confirm != "y":
        fmt.info("Cancelled.")
        return 0

    # Remove from hosts list and rewrite
    from freq.core.config import save_hosts_toml

    cfg.hosts = [h for h in cfg.hosts if h.ip != host.ip and h.label != host.label]
    save_hosts_toml(cfg.hosts_file, cfg.hosts)

    fmt.success(f"Host '{host.label}' removed from fleet.")
    return 0


# ─────────────────────────────────────────────────────────────
# HOST SYNC — Auto-discover hosts from PVE API and fleet-boundaries
# ─────────────────────────────────────────────────────────────


def _is_docker_bridge_ip(ip):
    """Check if IP is a Docker bridge address (172.17-31.x.x).

    Docker allocates bridge networks in 172.17.0.0/16 through 172.31.0.0/16.
    Does NOT filter 172.16.x.x or other legitimate 172.x addresses.
    """
    parts = ip.split(".")
    if len(parts) != 4 or parts[0] != "172":
        return False
    try:
        return 17 <= int(parts[1]) <= 31
    except ValueError:
        return False


def _hosts_sync(cfg: FreqConfig, dry_run: bool = False) -> int:
    """Sync hosts.conf from PVE API + fleet-boundaries.

    Queries PVE for all running VMs, gets IPs via qm agent, classifies type,
    merges physical devices from fleet-boundaries.toml, and updates hosts.conf.

    Preserves: comments, manual group assignments, manually-added hosts.
    Adds: new VMs discovered in PVE, physical devices from fleet-boundaries.
    Flags: hosts that disappeared from PVE (but doesn't remove — user decides).
    """
    from freq.core.ssh import run as ssh_single

    fmt.header("Hosts Sync")
    fmt.blank()

    # ── Step 1: Read existing hosts.conf ──
    existing = {}  # ip -> {label, htype, groups, all_ips}
    for h in cfg.hosts:
        existing[h.ip] = {
            "label": h.label,
            "htype": h.htype,
            "groups": getattr(h, "groups", "") or "",
            "all_ips": getattr(h, "all_ips", []) or [],
        }

    fmt.step_ok(f"Current hosts.conf: {len(existing)} hosts")

    # ── Step 2: Query PVE API for all VMs ──
    fmt.step_start("Querying PVE cluster")
    pve_vms = []
    for node_ip in cfg.pve_nodes:
        r = ssh_single(
            host=node_ip,
            command="pvesh get /cluster/resources --type vm --output-format json",
            key_path=cfg.ssh_key_path,
            command_timeout=HOSTS_PVE_TIMEOUT,
            htype="pve",
            use_sudo=True,
            cfg=cfg,
        )
        if r.returncode == 0 and r.stdout:
            try:
                vms = json.loads(r.stdout)
                pve_vms.extend(vms)
            except json.JSONDecodeError:
                pass
        break  # Cluster API returns all VMs from any node

    if not pve_vms:
        fmt.step_warn("No VMs returned from PVE API")
    else:
        fmt.step_ok(f"PVE cluster: {len(pve_vms)} VMs found")

    # ── Step 3: Get IPs for running VMs via qm agent ──
    discovered = {}  # ip -> {label, htype, groups, vmid, source}
    running_vms = [v for v in pve_vms if v.get("status") == "running" and v.get("type") == "qemu"]
    fmt.step_start(f"Resolving IPs for {len(running_vms)} running VMs")

    # Derive management VLAN prefix from PVE node IPs (they're on the mgmt VLAN)
    # This avoids hardcoding site-specific subnet prefixes
    mgmt_prefixes = set()
    for nip in cfg.pve_nodes:
        parts = nip.rsplit(".", 1)
        if len(parts) == 2:
            mgmt_prefixes.add(parts[0] + ".")
    # VLAN prefixes from config
    vlan_prefixes = {}
    for vlan in getattr(cfg, "vlans", []):
        if vlan.prefix:
            vlan_prefixes[vlan.prefix] = vlan.name.lower()
    unresolved = []  # VMs where guest agent didn't return IPs

    for v in running_vms:
        vmid = v.get("vmid", 0)
        name = v.get("name", "")
        node = v.get("node", "")

        # Skip templates and CTs for now
        if not name or vmid < 100:
            continue

        # Find which PVE node this VM is on
        node_ip = None
        for i, pn in enumerate(cfg.pve_node_names):
            if pn == node and i < len(cfg.pve_nodes):
                node_ip = cfg.pve_nodes[i]
                break
        if not node_ip:
            # Try all nodes
            node_ip = cfg.pve_nodes[0] if cfg.pve_nodes else None
        if not node_ip:
            continue

        # Get ALL IPs from QEMU guest agent — raw JSON, parse locally
        r = ssh_single(
            host=node_ip,
            command=f"qm agent {vmid} network-get-interfaces 2>/dev/null",
            key_path=cfg.ssh_key_path,
            connect_timeout=3,
            command_timeout=HOSTS_AGENT_TIMEOUT,
            htype="pve",
            use_sudo=True,
        )

        if r.returncode != 0 or not r.stdout.strip():
            unresolved.append((vmid, name, "no guest agent response"))
            continue

        # Parse qm agent JSON locally — handles both dict and list formats
        try:
            data = json.loads(r.stdout)
            ifaces = data.get("result", data) if isinstance(data, dict) else data
        except (json.JSONDecodeError, ValueError):
            unresolved.append((vmid, name, "invalid JSON from guest agent"))
            continue

        # Extract all IPv4 addresses (skip loopback)
        all_ips = []
        for iface in ifaces:
            for addr in iface.get("ip-addresses", []):
                if addr.get("ip-address-type") == "ipv4":
                    ip = addr.get("ip-address", "")
                    if ip and not ip.startswith("127.") and validate.ip(ip):
                        all_ips.append(ip)

        if not all_ips:
            unresolved.append((vmid, name, "no IPv4 addresses"))
            continue

        # Smart IP selection:
        # 1. If any IP matches an existing hosts.conf entry, use that (avoid duplicates)
        # 2. Prefer management VLAN (same subnet as PVE nodes)
        # 3. Fall back to any known VLAN prefix
        # 4. Last resort: first non-Docker-bridge IP
        chosen_ip = None

        # Check for existing match first
        for ip in all_ips:
            if ip in existing:
                chosen_ip = ip
                break

        if not chosen_ip:
            # Prefer management VLAN (same subnet as PVE nodes)
            mgmt_ips = [ip for ip in all_ips if any(ip.startswith(p) for p in mgmt_prefixes)]
            # Skip Docker bridge IPs (172.17-31.x.x)
            real_ips = [ip for ip in all_ips if not _is_docker_bridge_ip(ip)]

            if mgmt_ips:
                chosen_ip = mgmt_ips[0]
            elif real_ips:
                chosen_ip = real_ips[0]
            else:
                chosen_ip = all_ips[0]

        # Auto-classify type based on name/vmid
        htype = "linux"
        name_lower = name.lower()
        if "pve" in name_lower or "proxmox" in name_lower:
            htype = "pve"
        elif (
            "docker" in name_lower
            or "plex" in name_lower
            or "arr" in name_lower
            or "qbit" in name_lower
            or "tdarr" in name_lower
            or "sabnzbd" in name_lower
        ):
            htype = "docker"
        elif "truenas" in name_lower or "freenas" in name_lower:
            htype = "truenas"
        elif "pfsense" in name_lower or "opnsense" in name_lower:
            htype = "pfsense"

        # Filter all_ips: skip Docker bridge IPs, keep real NICs
        real_all_ips = [ip for ip in all_ips if not _is_docker_bridge_ip(ip)]

        # PVE name is source of truth for label — always sync it.
        # Preserve groups and type from existing entry (user may have customized).
        safe_label = validate.sanitize_label(name)
        if chosen_ip in existing:
            e = existing[chosen_ip]
            discovered[chosen_ip] = {
                "label": safe_label,
                "htype": e["htype"],
                "groups": e["groups"],
                "vmid": vmid,
                "source": "pve",
                "all_ips": real_all_ips,
            }
        else:
            # Default group based on VLAN — mgmt VLAN = prod, other = derive from VLAN name
            if any(chosen_ip.startswith(p) for p in mgmt_prefixes):
                groups = "prod"
            else:
                # Check known VLANs for a group hint
                groups = ""
                ip_prefix = chosen_ip.rsplit(".", 1)[0] + "."
                vlan_name = vlan_prefixes.get(ip_prefix.rstrip("."), "")
                if "lab" in vlan_name or "dev" in vlan_name:
                    groups = "lab"
            safe_label = validate.sanitize_label(name)
            discovered[chosen_ip] = {
                "label": safe_label,
                "htype": htype,
                "groups": groups,
                "vmid": vmid,
                "source": "pve",
                "all_ips": real_all_ips,
            }

    fmt.step_ok(f"Resolved {len(discovered)} VM IPs")
    if unresolved:
        fmt.step_warn(f"{len(unresolved)} VMs skipped (no guest agent or no IP)")

    # ── Step 4: Add PVE nodes themselves ──
    for i, node_ip in enumerate(cfg.pve_nodes):
        name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"pve{i + 1:02d}"
        if node_ip in existing:
            e = existing[node_ip]
            discovered[node_ip] = {
                "label": e["label"],
                "htype": e["htype"],
                "groups": e["groups"],
                "vmid": 0,
                "source": "pve-node",
                "all_ips": e.get("all_ips", []),
            }
        elif node_ip not in discovered:
            discovered[node_ip] = {
                "label": name,
                "htype": "pve",
                "groups": "prod,cluster",
                "vmid": 0,
                "source": "pve-node",
                "all_ips": [],
            }

    # ── Step 5: Merge physical devices from fleet-boundaries ──
    fb = cfg.fleet_boundaries
    if fb and hasattr(fb, "physical"):
        for dev in fb.physical.values():
            ip = dev.ip
            if ip in existing:
                e = existing[ip]
                discovered[ip] = {
                    "label": e["label"],
                    "htype": e["htype"],
                    "groups": e["groups"],
                    "vmid": 0,
                    "source": "fleet-boundaries",
                    "all_ips": e.get("all_ips", []),
                }
            elif ip not in discovered:
                # Sanitize label — hosts.conf uses whitespace as delimiter
                safe_label = dev.label.replace(" ", "-").lower()
                discovered[ip] = {
                    "label": safe_label,
                    "htype": dev.device_type,
                    "groups": "prod,network" if dev.device_type in ("pfsense", "switch") else "prod",
                    "vmid": 0,
                    "source": "fleet-boundaries",
                    "all_ips": [],
                }
        fmt.step_ok(f"Fleet boundaries: {len(fb.physical)} physical devices")

    # ── Step 6: Preserve manually-added hosts not in PVE or boundaries ──
    for ip, e in existing.items():
        if ip not in discovered:
            discovered[ip] = {
                "label": e["label"],
                "htype": e["htype"],
                "groups": e["groups"],
                "vmid": 0,
                "source": "manual",
                "all_ips": e.get("all_ips", []),
            }

    # ── Step 7: Diff and report ──
    new_hosts = [ip for ip in discovered if ip not in existing]
    removed_hosts = [ip for ip in existing if ip not in discovered]

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Sync Summary:{fmt.C.RESET}")
    fmt.line(
        f"    Existing: {len(existing)}  |  Discovered: {len(discovered)}  |  New: {fmt.C.GREEN}{len(new_hosts)}{fmt.C.RESET}  |  Removed: {fmt.C.RED}{len(removed_hosts)}{fmt.C.RESET}"
    )
    fmt.blank()

    if new_hosts:
        fmt.line(f"  {fmt.C.GREEN}New hosts to add:{fmt.C.RESET}")
        for ip in sorted(new_hosts):
            d = discovered[ip]
            fmt.line(f"    {fmt.C.GREEN}+{fmt.C.RESET} {ip}  {d['label']}  [{d['htype']}]  (from {d['source']})")
        fmt.blank()

    if removed_hosts:
        fmt.line(f"  {fmt.C.RED}Hosts no longer in PVE (kept in hosts.conf):{fmt.C.RESET}")
        for ip in sorted(removed_hosts):
            e = existing[ip]
            fmt.line(f"    {fmt.C.YELLOW}?{fmt.C.RESET} {ip}  {e['label']}  [{e['htype']}]")
        fmt.blank()

    if unresolved:
        fmt.line(f"  {fmt.C.DIM}Unresolved VMs (no guest agent or unreachable):{fmt.C.RESET}")
        for vmid, vname, reason in sorted(unresolved):
            fmt.line(f"    {fmt.C.DIM}-{fmt.C.RESET} {vmid}  {vname}  ({reason})")
        fmt.blank()

    if not new_hosts and not removed_hosts:
        fmt.step_ok("hosts.conf is up to date — no changes needed")
        _auto_populate_fleet_boundaries(cfg, discovered)
        fmt.blank()
        fmt.footer()
        return 0

    if dry_run:
        fmt.line(f"  {fmt.C.YELLOW}Dry run — no changes written.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run without --dry-run to apply.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # ── Step 8: Write updated hosts.toml ──
    from freq.core.config import Host, save_hosts_toml

    # Build Host list from discovered data, sorted by type then IP
    all_hosts = []
    for ip, d in sorted(
        discovered.items(),
        key=lambda x: (
            0
            if x[1]["htype"] == "pve"
            else 1
            if x[1]["htype"] == "docker"
            else 2
            if x[1]["htype"] == "truenas"
            else 3
            if x[1]["htype"] in ("pfsense", "switch")
            else 4
            if x[1]["htype"] == "idrac"
            else 5,
            x[0],
        ),
    ):
        all_ips = d.get("all_ips", [])
        if isinstance(all_ips, str):
            all_ips = [a for a in all_ips.split(",") if a]
        all_hosts.append(
            Host(
                ip=ip,
                label=d["label"],
                htype=d["htype"],
                groups=d.get("groups", ""),
                vmid=d.get("vmid", 0),
                all_ips=all_ips,
            )
        )

    # Backup existing
    if os.path.isfile(cfg.hosts_file):
        backup = cfg.hosts_file + ".bak"
        shutil.copy2(cfg.hosts_file, backup)
        fmt.step_ok(f"Backed up to {backup}")

    save_hosts_toml(cfg.hosts_file, all_hosts)
    cfg.hosts = all_hosts

    fmt.step_ok(f"Fleet registry updated: {len(discovered)} hosts ({len(new_hosts)} new)")

    # ── Step 9: Auto-populate fleet-boundaries.toml with discovered devices ──
    _auto_populate_fleet_boundaries(cfg, discovered)

    fmt.blank()
    fmt.footer()
    return 0


def _auto_populate_fleet_boundaries(cfg, discovered: dict):
    """Auto-populate fleet-boundaries.toml physical section from discovered hosts.

    Only adds devices that aren't already defined. Never overwrites user config.
    """
    fb_path = os.path.join(cfg.conf_dir, "fleet-boundaries.toml")

    # Device types that are "physical infrastructure" (not VMs/containers)
    INFRA_TYPES = {"pfsense", "opnsense", "truenas", "synology", "switch", "idrac", "ilo", "ipmi"}

    # Find infra devices in discovered hosts (skip lab VMs — they're VMs, not physical infra)
    lab_vmids = set()
    for cat_info in cfg.fleet_boundaries.categories.values():
        if cat_info.get("tier") == "admin":  # lab tier
            lab_vmids.update(cat_info.get("vmids", []))
    infra_devices = {}
    for ip, d in discovered.items():
        if d["htype"] in INFRA_TYPES:
            # Skip VMs categorized as lab (e.g., truenas-lab, pfsense-lab)
            if d.get("vmid", 0) in lab_vmids:
                continue
            key = d["label"].replace("-", "_").replace(" ", "_")
            infra_devices[key] = {"ip": ip, "label": d["label"], "type": d["htype"]}

    # Also add infrastructure devices from freq.toml config
    _cfg_devices = [
        (cfg.pfsense_ip, "pfsense", "pfsense"),
        (cfg.truenas_ip, "truenas", "truenas"),
        (cfg.switch_ip, "switch", "switch"),
    ]
    for ip, dtype, key in _cfg_devices:
        if ip and key not in infra_devices:
            infra_devices[key] = {"ip": ip, "label": key, "type": dtype}

    # Auto-detect gateway as pfSense/firewall if not already known
    gw = cfg.vm_gateway or ""
    if gw and "pfsense" not in infra_devices and "opnsense" not in infra_devices and "firewall" not in infra_devices:
        # Probe gateway — if it responds, assume firewall
        import subprocess
        try:
            r = subprocess.run(["ping", "-c", "1", "-W", "1", gw], capture_output=True, timeout=3)
            if r.returncode == 0:
                # Check if it's FreeBSD (pfSense) via SSH banner
                gw_type = "pfsense"
                try:
                    from freq.core.ssh import run as ssh_run
                    probe = ssh_run(
                        host=gw, command="uname -s",
                        key_path=cfg.ssh_key_path,
                        connect_timeout=3, command_timeout=5,
                        htype="pfsense", use_sudo=False,
                    )
                    if probe.returncode == 0 and "FreeBSD" in probe.stdout:
                        gw_type = "pfsense"
                    elif probe.returncode == 0 and "Linux" in probe.stdout:
                        gw_type = "opnsense"  # OPNsense runs on Linux too
                except Exception:
                    pass  # Can't SSH — still likely a firewall at the gateway
                infra_devices["firewall"] = {"ip": gw, "label": "firewall", "type": gw_type}
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Find PVE nodes
    pve_nodes = {}
    for ip, d in discovered.items():
        if d["htype"] == "pve" and d.get("source") == "pve-node":
            key = d["label"].replace("-", "_").replace(" ", "_")
            pve_nodes[key] = {"ip": ip}

    if not infra_devices and not pve_nodes:
        return

    # Load existing file to avoid overwriting user config
    import tomllib

    existing_data = {}
    try:
        with open(fb_path, "rb") as f:
            existing_data = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        pass

    existing_physical = existing_data.get("physical", {})
    existing_pve = existing_data.get("pve_nodes", {})

    # Only add new devices not already defined (dedup by IP, not key name)
    existing_ips = {v.get("ip", "") for v in existing_physical.values() if isinstance(v, dict)}
    existing_pve_ips = {v.get("ip", "") for v in existing_pve.values() if isinstance(v, dict)}
    new_physical = {k: v for k, v in infra_devices.items() if k not in existing_physical and v.get("ip", "") not in existing_ips}
    new_pve = {k: v for k, v in pve_nodes.items() if k not in existing_pve and v.get("ip", "") not in existing_pve_ips}

    if not new_physical and not new_pve:
        return

    # Rebuild the physical and pve_nodes sections to avoid duplicate TOML headers.
    # Merge existing + new, then rewrite the file with a single [physical] and [pve_nodes].
    merged_physical = {**existing_physical, **new_physical}
    merged_pve = {**existing_pve, **new_pve}

    # Read the file, strip old [physical] and [pve_nodes] sections, rewrite cleanly
    try:
        with open(fb_path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        lines = []

    # Remove existing [physical] and [pve_nodes] blocks (including their entries)
    cleaned = []
    skip_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == "[physical]" or stripped == "[pve_nodes]":
            skip_section = True
            continue
        if skip_section:
            # Stop skipping at the next section header or blank line before a header
            if stripped.startswith("[") and stripped != "[physical]" and stripped != "[pve_nodes]":
                skip_section = False
                cleaned.append(line)
            elif stripped.startswith("#") or stripped == "":
                # Skip comments/blanks that belong to the removed section
                continue
            else:
                continue  # Skip entries in the removed section
        else:
            cleaned.append(line)

    with open(fb_path, "w") as f:
        f.writelines(cleaned)
        if merged_physical:
            f.write("\n# Auto-discovered physical devices\n[physical]\n")
            for key, dev in sorted(merged_physical.items()):
                if isinstance(dev, dict):
                    detail_map = {"pfsense": "Firewall", "opnsense": "Firewall", "truenas": "NAS",
                                  "synology": "NAS", "switch": "Switch", "idrac": "BMC", "ilo": "BMC", "ipmi": "BMC"}
                    ip = dev.get("ip", "")
                    label = dev.get("label", key)
                    dtype = dev.get("type", "unknown")
                    detail = dev.get("detail", detail_map.get(dtype, dtype.upper()))
                    tier = dev.get("tier", "probe")
                    f.write(f'{key} = {{ ip = "{ip}", label = "{label}", type = "{dtype}", tier = "{tier}", detail = "{detail}" }}\n')

        if merged_pve:
            f.write("\n# Auto-discovered PVE nodes\n[pve_nodes]\n")
            for key, node in sorted(merged_pve.items()):
                if isinstance(node, dict):
                    ip = node.get("ip", "")
                    detail = node.get("detail", "")
                    f.write(f'{key} = {{ ip = "{ip}", detail = "{detail}" }}\n')

    count = len(new_physical) + len(new_pve)
    fmt.step_ok(f"Fleet boundaries: auto-added {len(new_physical)} physical + {len(new_pve)} PVE nodes")


# ─────────────────────────────────────────────────────────────
# HOST HELPERS — Label updates, IP resolution utilities
# ─────────────────────────────────────────────────────────────


def update_host_label(cfg: FreqConfig, target_ip: str, new_label: str) -> bool:
    """Update a single host's label in hosts.toml by IP match.

    Used by cmd_rename() to immediately sync the label after a PVE rename,
    instead of waiting for the hourly background sync.
    Returns True if the entry was found and updated.
    """
    updated = False
    for h in cfg.hosts:
        if h.ip == target_ip:
            h.label = new_label
            updated = True
            break

    if updated:
        from freq.core.config import save_hosts_toml

        save_hosts_toml(cfg.hosts_file, cfg.hosts)

    return updated


def resolve_host_ip(cfg: FreqConfig, label: str) -> str:
    """Look up a host's IP from hosts.conf by label.

    Used by container probing to resolve label → IP at probe time
    instead of relying on hardcoded IPs in containers.toml.
    Returns IP string or empty string if not found.
    """
    for h in cfg.hosts:
        if h.label == label:
            return h.ip
    return ""


# ─────────────────────────────────────────────────────────────
# GROUP MANAGEMENT — List, add, remove host group memberships
# ─────────────────────────────────────────────────────────────


def _groups_list(cfg: FreqConfig) -> int:
    """List all host groups and their members."""
    fmt.header("Host Groups")
    fmt.blank()

    groups = resolve.all_groups(cfg.hosts)
    if not groups:
        fmt.line(f"{fmt.C.YELLOW}No groups defined.{fmt.C.RESET}")
        fmt.line(f"{fmt.C.GRAY}Assign groups when adding hosts: freq hosts add{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    for group_name, members in sorted(groups.items()):
        fmt.line(f"{fmt.C.PURPLE_BOLD}{group_name}{fmt.C.RESET} ({len(members)} hosts)")
        for h in members:
            fmt.line(f"    {fmt.C.DIM}{h.label} ({h.ip}) [{h.htype}]{fmt.C.RESET}")
        fmt.blank()

    fmt.footer()
    return 0


def _groups_add(cfg: FreqConfig, args) -> int:
    """Add a host to a group."""
    target = getattr(args, "target", None)
    group = getattr(args, "group", None)

    if not target or not group:
        fmt.error("Usage: freq groups add --target <host> --group <name>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    existing = [g.strip() for g in host.groups.split(",") if g.strip()] if host.groups else []
    if group in existing:
        fmt.info(f"{host.label} is already in group '{group}'.")
        return 0

    existing.append(group)
    new_groups = ",".join(existing)

    # Update in-memory and rewrite
    host.groups = new_groups
    from freq.core.config import save_hosts_toml

    save_hosts_toml(cfg.hosts_file, cfg.hosts)
    fmt.info(f"Added {host.label} to group '{group}'.")

    return 0


def _groups_remove(cfg: FreqConfig, args) -> int:
    """Remove a host from a group."""
    target = getattr(args, "target", None)
    group = getattr(args, "group", None)

    if not target or not group:
        fmt.error("Usage: freq groups remove --target <host> --group <name>")
        return 1

    host = resolve.by_target(cfg.hosts, target)
    if not host:
        fmt.error(f"Host not found: {target}")
        return 1

    existing = [g.strip() for g in host.groups.split(",") if g.strip()] if host.groups else []
    if group not in existing:
        fmt.info(f"{host.label} is not in group '{group}'.")
        return 0

    existing.remove(group)
    new_groups = ",".join(existing)

    # Update in-memory and rewrite
    host.groups = new_groups
    from freq.core.config import save_hosts_toml

    save_hosts_toml(cfg.hosts_file, cfg.hosts)
    fmt.info(f"Removed {host.label} from group '{group}'.")

    return 0
