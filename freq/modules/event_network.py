"""Event network lifecycle management for FREQ.

Domain: freq event <action>
What: Create, plan, deploy, verify, and wipe entire event networks.
      Sonny programmed hundreds of switches weekly for NFL, FIFA, F1, USGA,
      LIV — built entire event networks from ISP handoff to every endpoint in
      3 weeks, then wiped and repeated. This module automates that lifecycle.
Replaces: Manual switch-by-switch configuration, spreadsheet-based IP plans,
          no-tool event network teardown
Architecture:
    - Event templates stored as TOML in conf/event-templates/<name>.toml
    - Each template defines: name, VLANs, switch assignments, port profiles
    - Deploy pushes profile configs to switches via deployer push_config()
    - Verify pulls live state and compares against template
    - Wipe resets switches to a clean baseline
    - Archive saves configs + verification reports
Design decisions:
    - TOML templates, not YAML. Consistent with freq.toml and vlans.toml.
    - One template per event. Events are isolated, never share config state.
    - Deploy is idempotent — running it twice produces the same result.
    - Wipe requires --confirm flag. No accidental network teardowns.
"""

import json
import os
import time

from freq.core import fmt
from freq.core.config import FreqConfig
from freq.core import log as logger


# ─────────────────────────────────────────────────────────────
# CONSTANTS — Directory names for templates and archives
# ─────────────────────────────────────────────────────────────

TEMPLATES_DIR = "event-templates"
ARCHIVES_DIR = "event-archives"


# ─────────────────────────────────────────────────────────────
# TEMPLATE STORAGE — Load, save, list event templates as TOML
# ─────────────────────────────────────────────────────────────


def _templates_dir(cfg):
    """Return path to event templates directory, creating if needed."""
    path = os.path.join(cfg.conf_dir, TEMPLATES_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _archives_dir(cfg):
    """Return path to event archives directory, creating if needed."""
    path = os.path.join(cfg.conf_dir, ARCHIVES_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def _load_template(cfg, name):
    """Load an event template by name. Returns dict or None."""
    filepath = os.path.join(_templates_dir(cfg), f"{name}.toml")
    if not os.path.exists(filepath):
        return None
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(filepath, "rb") as f:
        return tomllib.load(f)


def _list_templates(cfg):
    """List all event template names."""
    path = _templates_dir(cfg)
    templates = []
    for f in sorted(os.listdir(path)):
        if f.endswith(".toml"):
            templates.append(f[:-5])  # strip .toml
    return templates


def _save_template(cfg, name, data):
    """Save an event template as TOML."""
    filepath = os.path.join(_templates_dir(cfg), f"{name}.toml")
    lines = [f"# FREQ Event Template: {name}", f"# Created: {time.strftime('%Y-%m-%d %H:%M:%S')}", ""]

    for section, content in data.items():
        if isinstance(content, dict):
            lines.append(f"[{section}]")
            for key, val in content.items():
                lines.append(f"{key} = {_toml_val(val)}")
            lines.append("")
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    # Array of tables: [[section]]
                    lines.append(f"[[{section}]]")
                    for key, val in item.items():
                        lines.append(f"{key} = {_toml_val(val)}")
                    lines.append("")
        else:
            lines.append(f"{section} = {_toml_val(content)}")

    with open(filepath, "w") as f:
        f.write("\n".join(lines) + "\n")
    return filepath


def _toml_val(v):
    """Format a Python value as TOML."""
    if isinstance(v, str):
        return f'"{v}"'
    elif isinstance(v, bool):
        return "true" if v else "false"
    elif isinstance(v, list):
        items = ", ".join(_toml_val(i) for i in v)
        return f"[{items}]"
    return str(v)


# ─────────────────────────────────────────────────────────────
# COMMANDS — Event lifecycle: create, list, show, plan, deploy, verify, wipe
# ─────────────────────────────────────────────────────────────


def cmd_event_create(cfg: FreqConfig, pack, args) -> int:
    """Create a new event project with a template."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq event create <name>")
        return 1

    # Check if already exists
    existing = _load_template(cfg, name)
    if existing:
        fmt.error(f"Event '{name}' already exists. Delete or archive it first.")
        return 1

    fmt.header(f"Create Event: {name}", breadcrumb="FREQ > Event")
    fmt.blank()

    # Build skeleton template
    template = {
        "event": {
            "name": name,
            "created": time.strftime("%Y-%m-%d"),
            "status": "draft",
            "description": "",
        },
        "switches": [],
        "vlans": [],
    }

    # Pull switches from hosts.conf
    from freq.modules.switch_orchestration import _get_switch_hosts

    switches = _get_switch_hosts(cfg)
    for sw in switches:
        template["switches"].append(
            {
                "label": sw.label,
                "ip": sw.ip,
                "role": "access",
            }
        )

    # Pull VLANs from vlans.toml
    vlans_path = os.path.join(cfg.conf_dir, "vlans.toml")
    if os.path.exists(vlans_path):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with open(vlans_path, "rb") as f:
            vlan_data = tomllib.load(f)
        for vname, vinfo in vlan_data.get("vlan", {}).items():
            template["vlans"].append(
                {
                    "name": vname,
                    "id": vinfo.get("id", 0),
                    "subnet": vinfo.get("subnet", ""),
                }
            )

    filepath = _save_template(cfg, name, template)

    fmt.step_ok(f"Template created: {filepath}")
    fmt.blank()
    fmt.line(f"{fmt.C.BOLD}Switches:{fmt.C.RESET} {len(template['switches'])}")
    fmt.line(f"{fmt.C.BOLD}VLANs:{fmt.C.RESET}    {len(template['vlans'])}")
    fmt.blank()
    fmt.info(f"Edit the template to define port profiles per switch, then deploy.")
    logger.info("event_create", name=name)
    fmt.footer()
    return 0


def cmd_event_list(cfg: FreqConfig, pack, args) -> int:
    """List all event templates."""
    templates = _list_templates(cfg)

    fmt.header("Events", breadcrumb="FREQ > Event")
    fmt.blank()

    if not templates:
        fmt.warn("No event templates found")
        fmt.info("Create one: freq event create <name>")
        fmt.footer()
        return 0

    fmt.table_header(("Name", 24), ("Status", 10), ("Created", 12), ("Switches", 10))
    for name in templates:
        tmpl = _load_template(cfg, name)
        if tmpl:
            event = tmpl.get("event", {})
            switches = tmpl.get("switches", [])
            fmt.table_row(
                (name, 24),
                (event.get("status", "?"), 10),
                (event.get("created", "?"), 12),
                (str(len(switches)), 10),
            )

    fmt.blank()
    fmt.info(f"{len(templates)} event(s)")
    fmt.footer()
    return 0


def cmd_event_show(cfg: FreqConfig, pack, args) -> int:
    """Show details of an event template."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq event show <name>")
        return 1

    tmpl = _load_template(cfg, name)
    if not tmpl:
        fmt.error(f"Event '{name}' not found")
        return 1

    event = tmpl.get("event", {})

    fmt.header(f"Event: {name}", breadcrumb="FREQ > Event")
    fmt.blank()

    fmt.line(f"{fmt.C.BOLD}Status:{fmt.C.RESET}      {event.get('status', '?')}")
    fmt.line(f"{fmt.C.BOLD}Created:{fmt.C.RESET}     {event.get('created', '?')}")
    if event.get("description"):
        fmt.line(f"{fmt.C.BOLD}Description:{fmt.C.RESET} {event['description']}")
    fmt.blank()

    # Switches
    switches = tmpl.get("switches", [])
    if switches:
        fmt.line(f"{fmt.C.BOLD}Switches ({len(switches)}):{fmt.C.RESET}")
        for sw in switches:
            profile = sw.get("profile", "—")
            ports = sw.get("ports", "—")
            fmt.line(
                f"  {fmt.C.CYAN}{sw.get('label', '?'):<16}{fmt.C.RESET} "
                f"{sw.get('ip', '?'):<16} role={sw.get('role', '?'):<8} "
                f"profile={profile}  ports={ports}"
            )
        fmt.blank()

    # VLANs
    vlans = tmpl.get("vlans", [])
    if vlans:
        fmt.line(f"{fmt.C.BOLD}VLANs ({len(vlans)}):{fmt.C.RESET}")
        for v in vlans:
            fmt.line(
                f"  {fmt.C.CYAN}{v.get('id', '?'):>5}{fmt.C.RESET}  {v.get('name', '?'):<16} {v.get('subnet', '')}"
            )
        fmt.blank()

    # Port assignments
    assignments = tmpl.get("port_assignments", [])
    if assignments:
        fmt.line(f"{fmt.C.BOLD}Port Assignments ({len(assignments)}):{fmt.C.RESET}")
        for a in assignments:
            fmt.line(f"  {a.get('switch', '?')} {a.get('ports', '?')} -> profile={a.get('profile', '?')}")
        fmt.blank()

    fmt.footer()
    return 0


def cmd_event_plan(cfg: FreqConfig, pack, args) -> int:
    """Generate IP plan and VLAN allocation for an event."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq event plan <name>")
        return 1

    tmpl = _load_template(cfg, name)
    if not tmpl:
        fmt.error(f"Event '{name}' not found")
        return 1

    fmt.header(f"Event Plan: {name}", breadcrumb="FREQ > Event")
    fmt.blank()

    vlans = tmpl.get("vlans", [])
    switches = tmpl.get("switches", [])

    if not vlans:
        fmt.warn("No VLANs defined in template")
        fmt.footer()
        return 1

    fmt.line(f"{fmt.C.BOLD}Network Plan{fmt.C.RESET}")
    fmt.blank()

    # VLAN allocation summary
    fmt.table_header(("VLAN", 6), ("Name", 16), ("Subnet", 20), ("Hosts", 8))
    for v in vlans:
        subnet = v.get("subnet", "")
        # Estimate usable hosts from subnet
        hosts = "—"
        if "/" in subnet:
            prefix = int(subnet.split("/")[1])
            hosts = str(2 ** (32 - prefix) - 2) if prefix <= 30 else "1"
        fmt.table_row(
            (str(v.get("id", "?")), 6),
            (v.get("name", ""), 16),
            (subnet, 20),
            (hosts, 8),
        )

    fmt.blank()

    # Switch assignment summary
    fmt.line(f"{fmt.C.BOLD}Switch Assignments{fmt.C.RESET}")
    fmt.blank()
    for sw in switches:
        role = sw.get("role", "access")
        profile = sw.get("profile", "not assigned")
        ports = sw.get("ports", "not assigned")
        fmt.line(f"  {fmt.C.CYAN}{sw.get('label', '?')}{fmt.C.RESET} ({sw.get('ip', '?')})")
        fmt.line(f"    Role: {role}  Profile: {profile}  Ports: {ports}")

    fmt.blank()
    fmt.info(f"{len(vlans)} VLANs, {len(switches)} switches")
    logger.info("event_plan", name=name, vlans=len(vlans), switches=len(switches))
    fmt.footer()
    return 0


def cmd_event_deploy(cfg: FreqConfig, pack, args) -> int:
    """Deploy event configs to all assigned switches."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq event deploy <name>")
        return 1

    tmpl = _load_template(cfg, name)
    if not tmpl:
        fmt.error(f"Event '{name}' not found")
        return 1

    assignments = tmpl.get("port_assignments", [])
    if not assignments:
        fmt.warn(f"No port assignments in template '{name}'")
        fmt.info("Add [[port_assignments]] sections to the template with switch, ports, and profile fields")
        return 1

    from freq.modules.switch_orchestration import (
        _resolve_target,
        _get_deployer,
        _load_profiles,
        _expand_port_range,
    )

    fmt.header(f"Deploy Event: {name}", breadcrumb="FREQ > Event")
    fmt.blank()

    profiles = _load_profiles(cfg)
    ok_count = 0
    total_ports = 0

    for assignment in assignments:
        switch_target = assignment.get("switch", "")
        port_range = assignment.get("ports", "")
        profile_name = assignment.get("profile", "")

        if not switch_target or not port_range or not profile_name:
            fmt.step_warn(f"Incomplete assignment: {assignment}")
            continue

        profile = profiles.get(profile_name)
        if not profile:
            fmt.step_fail(f"Profile '{profile_name}' not found")
            continue

        ip, label, vendor = _resolve_target(switch_target, cfg)
        if not ip:
            fmt.step_fail(f"Switch '{switch_target}' not found")
            continue

        deployer = _get_deployer(vendor)
        if not deployer:
            fmt.step_fail(f"No deployer for {vendor}")
            continue

        # Generate config lines from profile
        if hasattr(deployer, "profile_to_config_lines"):
            config_lines = deployer.profile_to_config_lines(profile)
        else:
            from freq.deployers.switch.cisco import profile_to_config_lines

            config_lines = profile_to_config_lines(profile)

        ports = _expand_port_range(port_range)
        total_ports += len(ports)

        fmt.line(f"{fmt.C.BOLD}{label}{fmt.C.RESET} — {profile_name} -> {port_range} ({len(ports)} ports)")

        port_ok = 0
        for port in ports:
            if deployer.apply_profile_lines(ip, cfg, port, config_lines):
                port_ok += 1

        if port_ok == len(ports):
            fmt.step_ok(f"{port_ok}/{len(ports)} ports configured")
            deployer.save_config(ip, cfg)
            ok_count += 1
        else:
            fmt.step_warn(f"{port_ok}/{len(ports)} ports configured (some failed)")

    fmt.blank()
    fmt.info(f"{ok_count}/{len(assignments)} assignments deployed, {total_ports} total ports")
    logger.info("event_deploy", name=name, assignments=len(assignments), ok=ok_count)
    fmt.footer()
    return 0


def cmd_event_verify(cfg: FreqConfig, pack, args) -> int:
    """Verify deployed event matches template."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq event verify <name>")
        return 1

    tmpl = _load_template(cfg, name)
    if not tmpl:
        fmt.error(f"Event '{name}' not found")
        return 1

    assignments = tmpl.get("port_assignments", [])
    if not assignments:
        fmt.warn(f"No port assignments to verify in '{name}'")
        return 1

    from freq.modules.switch_orchestration import (
        _resolve_target,
        _get_deployer,
        _load_profiles,
    )

    fmt.header(f"Verify Event: {name}", breadcrumb="FREQ > Event")
    fmt.blank()

    profiles = _load_profiles(cfg)
    pass_count = 0
    fail_count = 0

    for assignment in assignments:
        switch_target = assignment.get("switch", "")
        profile_name = assignment.get("profile", "")

        ip, label, vendor = _resolve_target(switch_target, cfg)
        if not ip:
            fmt.step_fail(f"Switch '{switch_target}' unreachable")
            fail_count += 1
            continue

        deployer = _get_deployer(vendor)
        if not deployer:
            fmt.step_fail(f"No deployer for {vendor}")
            fail_count += 1
            continue

        profile = profiles.get(profile_name, {})
        expected_vlan = str(profile.get("vlan", ""))

        # Pull live interface data
        interfaces = deployer.get_interfaces(ip, cfg)
        if not interfaces:
            fmt.step_fail(f"{label}: could not retrieve interfaces")
            fail_count += 1
            continue

        # Check that ports assigned to this profile have the right VLAN
        port_range = assignment.get("ports", "")
        from freq.modules.switch_orchestration import _expand_port_range

        ports = _expand_port_range(port_range)

        mismatches = []
        for port in ports:
            iface = next((i for i in interfaces if i.get("name") == port), None)
            if not iface:
                mismatches.append((port, "not found", expected_vlan))
            elif expected_vlan and iface.get("vlan", "") != expected_vlan:
                mismatches.append((port, iface.get("vlan", "?"), expected_vlan))

        if mismatches:
            fmt.step_warn(f"{label}: {len(mismatches)}/{len(ports)} ports mismatched")
            for port, actual, expected in mismatches[:5]:
                fmt.line(f"    {port}: vlan={actual} (expected {expected})")
            fail_count += 1
        else:
            fmt.step_ok(f"{label}: {len(ports)} ports verified")
            pass_count += 1

    fmt.blank()
    total = pass_count + fail_count
    if fail_count == 0:
        fmt.success(f"All {total} assignment(s) verified")
    else:
        fmt.warn(f"{pass_count}/{total} passed, {fail_count} failed")

    logger.info("event_verify", name=name, passed=pass_count, failed=fail_count)
    fmt.footer()
    return 0 if fail_count == 0 else 1


def cmd_event_wipe(cfg: FreqConfig, pack, args) -> int:
    """Reset switches to clean state — removes all event config."""
    name = getattr(args, "name", None)
    confirm = getattr(args, "confirm", False)

    if not name:
        fmt.error("Usage: freq event wipe <name> --confirm")
        return 1

    if not confirm:
        fmt.error("Wipe requires --confirm flag. This resets switch configs!")
        fmt.info("Usage: freq event wipe <name> --confirm")
        return 1

    tmpl = _load_template(cfg, name)
    if not tmpl:
        fmt.error(f"Event '{name}' not found")
        return 1

    assignments = tmpl.get("port_assignments", [])
    if not assignments:
        fmt.warn(f"No port assignments to wipe in '{name}'")
        return 0

    from freq.modules.switch_orchestration import (
        _resolve_target,
        _get_deployer,
        _expand_port_range,
    )

    fmt.header(f"Wipe Event: {name}", breadcrumb="FREQ > Event")
    fmt.blank()

    ok_count = 0
    for assignment in assignments:
        switch_target = assignment.get("switch", "")
        port_range = assignment.get("ports", "")

        ip, label, vendor = _resolve_target(switch_target, cfg)
        if not ip:
            fmt.step_fail(f"Switch '{switch_target}' not found")
            continue

        deployer = _get_deployer(vendor)
        if not deployer:
            fmt.step_fail(f"No deployer for {vendor}")
            continue

        ports = _expand_port_range(port_range)

        # Reset each port to default (access vlan 1, no shutdown, no description)
        default_lines = [
            "no description",
            "switchport mode access",
            "switchport access vlan 1",
            "no switchport port-security",
            "power inline auto",
            "spanning-tree portfast",
            "no shutdown",
        ]

        port_ok = 0
        for port in ports:
            if deployer.apply_profile_lines(ip, cfg, port, default_lines):
                port_ok += 1

        if port_ok > 0:
            deployer.save_config(ip, cfg)

        fmt.step_ok(f"{label}: {port_ok}/{len(ports)} ports reset")
        ok_count += 1

    fmt.blank()
    fmt.info(f"{ok_count}/{len(assignments)} switches wiped")
    logger.info("event_wipe", name=name, ok=ok_count)
    fmt.footer()
    return 0


# ─────────────────────────────────────────────────────────────
# ARCHIVE & CLEANUP — Archive completed events, delete templates
# ─────────────────────────────────────────────────────────────


def cmd_event_archive(cfg: FreqConfig, pack, args) -> int:
    """Archive an event — save configs and reports, then remove template."""
    name = getattr(args, "name", None)
    if not name:
        fmt.error("Usage: freq event archive <name>")
        return 1

    tmpl = _load_template(cfg, name)
    if not tmpl:
        fmt.error(f"Event '{name}' not found")
        return 1

    fmt.header(f"Archive Event: {name}", breadcrumb="FREQ > Event")
    fmt.blank()

    # Create archive directory
    ts = time.strftime("%Y%m%d-%H%M%S")
    archive_path = os.path.join(_archives_dir(cfg), f"{name}-{ts}")
    os.makedirs(archive_path, exist_ok=True)

    # Copy template
    import shutil

    src_template = os.path.join(_templates_dir(cfg), f"{name}.toml")
    shutil.copy2(src_template, os.path.join(archive_path, f"{name}.toml"))
    fmt.step_ok("Template archived")

    # Backup current configs from all switches in the event
    from freq.modules.switch_orchestration import _resolve_target, _get_deployer

    switches = tmpl.get("switches", [])
    config_count = 0
    for sw in switches:
        ip, label, vendor = _resolve_target(sw.get("label") or sw.get("ip"), cfg)
        if not ip:
            continue
        deployer = _get_deployer(vendor)
        if not deployer:
            continue
        config_text = deployer.get_config(ip, cfg)
        if config_text:
            config_file = os.path.join(archive_path, f"{label or sw.get('label', 'unknown')}-final.conf")
            with open(config_file, "w") as f:
                f.write(config_text)
            config_count += 1

    if config_count > 0:
        fmt.step_ok(f"{config_count} switch config(s) archived")
    else:
        fmt.step_warn("No switch configs could be pulled (switches may be offline)")

    # Write archive manifest
    manifest = {
        "event": name,
        "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "switches": config_count,
        "template": f"{name}.toml",
    }
    with open(os.path.join(archive_path, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    fmt.step_ok("Manifest written")

    # Remove the active template
    os.remove(src_template)
    fmt.step_ok(f"Template removed from active events")

    fmt.blank()
    fmt.success(f"Event '{name}' archived to {archive_path}")
    logger.info("event_archive", name=name, path=archive_path)
    fmt.footer()
    return 0


def cmd_event_delete(cfg: FreqConfig, pack, args) -> int:
    """Delete an event template (use archive for completed events)."""
    name = getattr(args, "name", None)
    yes = getattr(args, "yes", False)
    if not name:
        fmt.error("Usage: freq event delete <name> --yes")
        return 1
    if not yes:
        fmt.error("Delete requires --yes flag")
        return 1

    filepath = os.path.join(_templates_dir(cfg), f"{name}.toml")
    if not os.path.exists(filepath):
        fmt.error(f"Event '{name}' not found")
        return 1

    os.remove(filepath)
    fmt.success(f"Event '{name}' deleted")
    logger.info("event_delete", name=name)
    return 0
