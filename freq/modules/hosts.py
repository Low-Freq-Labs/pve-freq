"""Host management for FREQ.

Commands: hosts list, hosts add, hosts remove, hosts sync, discover, groups
"""
import json
import os

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import resolve
from freq.core import validate


def cmd_hosts(cfg: FreqConfig, pack, args) -> int:
    """List, add, remove, or sync fleet hosts."""
    action = getattr(args, "action", "list")

    if action == "list":
        return _hosts_list(cfg)
    elif action == "add":
        return _hosts_add(cfg)
    elif action == "remove":
        return _hosts_remove(cfg)
    elif action == "sync":
        dry_run = getattr(args, "dry_run", False)
        return _hosts_sync(cfg, dry_run=dry_run)
    else:
        return _hosts_list(cfg)


def cmd_groups(cfg: FreqConfig, pack, args) -> int:
    """List, add, or remove host groups."""
    action = getattr(args, "action", "list")

    if action == "list":
        return _groups_list(cfg)
    else:
        fmt.warn(f"Groups '{action}' not yet implemented.")
        return 0


def _hosts_list(cfg: FreqConfig) -> int:
    """Display all registered fleet hosts."""
    fmt.header("Fleet Hosts")
    fmt.blank()

    hosts = cfg.hosts
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

    # Write to hosts.conf
    line = f"{ip}  {label}  {htype}"
    if groups:
        line += f"  {groups}"

    with open(cfg.hosts_file, "a") as f:
        f.write(f"{line}\n")

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

    # Rewrite hosts.conf without this host
    lines = []
    with open(cfg.hosts_file) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                lines.append(line)
                continue
            parts = stripped.split()
            if len(parts) >= 2 and (parts[0] == host.ip or parts[1] == host.label):
                continue  # Skip this host
            lines.append(line)

    with open(cfg.hosts_file, "w") as f:
        f.writelines(lines)

    fmt.success(f"Host '{host.label}' removed from fleet.")
    return 0


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
            "label": h.label, "htype": h.htype,
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
            connect_timeout=5, command_timeout=15,
            htype="pve", use_sudo=True,
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
            connect_timeout=3, command_timeout=10,
            htype="pve", use_sudo=True,
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
        elif "docker" in name_lower or "plex" in name_lower or "arr" in name_lower or "qbit" in name_lower or "tdarr" in name_lower or "sabnzbd" in name_lower:
            htype = "docker"
        elif "truenas" in name_lower or "freenas" in name_lower:
            htype = "truenas"
        elif "pfsense" in name_lower or "opnsense" in name_lower:
            htype = "pfsense"

        # Filter all_ips: skip Docker bridge IPs, keep real NICs
        real_all_ips = [ip for ip in all_ips if not _is_docker_bridge_ip(ip)]

        # Preserve existing label/groups/type if already known
        if chosen_ip in existing:
            e = existing[chosen_ip]
            discovered[chosen_ip] = {
                "label": e["label"], "htype": e["htype"],
                "groups": e["groups"], "vmid": vmid, "source": "pve",
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
            discovered[chosen_ip] = {
                "label": name, "htype": htype,
                "groups": groups, "vmid": vmid, "source": "pve",
                "all_ips": real_all_ips,
            }

    fmt.step_ok(f"Resolved {len(discovered)} VM IPs")
    if unresolved:
        fmt.step_warn(f"{len(unresolved)} VMs skipped (no guest agent or no IP)")

    # ── Step 4: Add PVE nodes themselves ──
    for i, node_ip in enumerate(cfg.pve_nodes):
        name = cfg.pve_node_names[i] if i < len(cfg.pve_node_names) else f"pve{i+1:02d}"
        if node_ip in existing:
            e = existing[node_ip]
            discovered[node_ip] = {
                "label": e["label"], "htype": e["htype"],
                "groups": e["groups"], "vmid": 0, "source": "pve-node",
                "all_ips": e.get("all_ips", []),
            }
        elif node_ip not in discovered:
            discovered[node_ip] = {
                "label": name, "htype": "pve",
                "groups": "prod,cluster", "vmid": 0, "source": "pve-node",
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
                    "label": e["label"], "htype": e["htype"],
                    "groups": e["groups"], "vmid": 0, "source": "fleet-boundaries",
                    "all_ips": e.get("all_ips", []),
                }
            elif ip not in discovered:
                # Sanitize label — hosts.conf uses whitespace as delimiter
                safe_label = dev.label.replace(" ", "-").lower()
                discovered[ip] = {
                    "label": safe_label, "htype": dev.device_type,
                    "groups": "prod,network" if dev.device_type in ("pfsense", "switch") else "prod",
                    "vmid": 0, "source": "fleet-boundaries",
                    "all_ips": [],
                }
        fmt.step_ok(f"Fleet boundaries: {len(fb.physical)} physical devices")

    # ── Step 6: Preserve manually-added hosts not in PVE or boundaries ──
    for ip, e in existing.items():
        if ip not in discovered:
            discovered[ip] = {
                "label": e["label"], "htype": e["htype"],
                "groups": e["groups"], "vmid": 0, "source": "manual",
                "all_ips": e.get("all_ips", []),
            }

    # ── Step 7: Diff and report ──
    new_hosts = [ip for ip in discovered if ip not in existing]
    removed_hosts = [ip for ip in existing if ip not in discovered]

    fmt.blank()
    fmt.line(f"  {fmt.C.BOLD}Sync Summary:{fmt.C.RESET}")
    fmt.line(f"    Existing: {len(existing)}  |  Discovered: {len(discovered)}  |  New: {fmt.C.GREEN}{len(new_hosts)}{fmt.C.RESET}  |  Removed: {fmt.C.RED}{len(removed_hosts)}{fmt.C.RESET}")
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
        fmt.blank()
        fmt.footer()
        return 0

    if dry_run:
        fmt.line(f"  {fmt.C.YELLOW}Dry run — no changes written.{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}Run without --dry-run to apply.{fmt.C.RESET}")
        fmt.blank()
        fmt.footer()
        return 0

    # ── Step 8: Write updated hosts.conf ──
    # Preserve comments from original file, then write all hosts
    lines = []
    lines.append("# FREQ Fleet Registry — auto-synced from PVE + fleet-boundaries\n")
    lines.append("# Format: IP  LABEL  TYPE  [GROUPS]  [ALL_IPS]\n")
    lines.append("# Types: linux, pve, truenas, pfsense, docker, idrac, switch\n")
    lines.append("#\n")
    lines.append("# Synced by: freq hosts sync\n")
    lines.append("# Manual edits preserved on next sync.\n")
    lines.append("\n")

    # Group by VLAN/category
    prod_hosts = [(ip, d) for ip, d in discovered.items() if "prod" in d.get("groups", "")]
    lab_hosts = [(ip, d) for ip, d in discovered.items() if "lab" in d.get("groups", "")]
    other_hosts = [(ip, d) for ip, d in discovered.items()
                   if "prod" not in d.get("groups", "") and "lab" not in d.get("groups", "")]

    def _write_section(section_hosts, header):
        if not section_hosts:
            return
        lines.append(f"# {header}\n")
        # Sort: PVE nodes first, then by IP
        section_hosts.sort(key=lambda x: (
            0 if x[1]["htype"] == "pve" else
            1 if x[1]["htype"] == "docker" else
            2 if x[1]["htype"] == "truenas" else
            3 if x[1]["htype"] in ("pfsense", "switch") else
            4 if x[1]["htype"] == "idrac" else 5,
            x[0],
        ))
        for ip, d in section_hosts:
            parts = [f"{ip:<16}", f"{d['label']:<15}", f"{d['htype']:<10}"]
            if d["groups"] or d.get("all_ips"):
                parts.append(f"{d['groups']:<20}" if d.get("all_ips") else d["groups"])
            if d.get("all_ips"):
                parts.append(",".join(d["all_ips"]))
            lines.append("  ".join(parts).rstrip() + "\n")
        lines.append("\n")

    _write_section(prod_hosts, "Production Fleet")
    _write_section(lab_hosts, "Lab Fleet")
    _write_section(other_hosts, "Other Hosts")

    # Backup existing
    if os.path.isfile(cfg.hosts_file):
        backup = cfg.hosts_file + ".bak"
        import shutil
        shutil.copy2(cfg.hosts_file, backup)
        fmt.step_ok(f"Backed up to {backup}")

    with open(cfg.hosts_file, "w") as f:
        f.writelines(lines)

    fmt.step_ok(f"hosts.conf updated: {len(discovered)} hosts ({len(new_hosts)} new)")
    fmt.blank()
    fmt.footer()
    return 0


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
