"""FREQ CLI dispatcher — v3.0.0 Domain Architecture.

Routes commands through `freq <domain> <action>` two-level dispatch.
25 domains, ~88 existing actions, room for 810+.

Architecture: Python is primary. Modules are imported on demand.
If a module is missing, the command reports the error and FREQ keeps running.
This is the "muscles can be missing" principle from the Convergence.
"""

import argparse
import os

import freq
from freq.core.config import load_config, FreqConfig
from freq.core import fmt
from freq.core import log as logger
from freq.core.personality import load_pack, show_vibe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_action(handler, action_value):
    """Wrap a handler to inject args.action before calling."""

    def wrapper(cfg, pack, args):
        args.action = action_value
        return handler(cfg, pack, args)

    return wrapper


def _domain_help(parser):
    """Set default func to print help when domain is invoked without action."""
    parser.set_defaults(func=lambda cfg, pack, args: parser.print_help() or 0)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list = None) -> int:
    """Main entry point for FREQ CLI."""
    # Handle --version before config (no dirs needed)
    check_args = argv if argv is not None else os.sys.argv[1:]
    if "--version" in check_args:
        print(f"PVE FREQ v{freq.__version__}")
        return 0

    # Load config first (needed for plugin discovery)
    cfg = load_config()

    # Build parser with plugins
    parser = _build_parser()

    # Discover and register plugins before parsing
    from freq.core.plugins import discover_plugins

    plugin_dir = os.path.join(cfg.conf_dir, "plugins")
    plugins = discover_plugins(plugin_dir)
    if plugins:
        sub = parser._subparsers._group_actions[0] if parser._subparsers else None
        if sub:
            for plugin in plugins:
                try:
                    p = sub.add_parser(plugin["name"], help=f"[plugin] {plugin['description']}")
                    p.add_argument("plugin_args", nargs="*", help="Plugin arguments")
                    h = plugin["handler"]
                    p.set_defaults(func=lambda c, pk, a, _h=h: _h(c, pk, a))
                except Exception as e:
                    logger.warn(f"failed to register plugin {plugin.get('name', '?')}: {e}")

    args = parser.parse_args(argv)

    # Init logging, audit trail, and performance tracking
    log_dir = os.path.dirname(cfg.log_file)
    logger.init(cfg.log_file)
    logger.init_perf(log_dir)
    from freq.core import audit
    audit.init(log_dir)

    # Set ASCII mode from config
    fmt.S.set_ascii(cfg.ascii_mode)

    # Load personality pack
    pack = load_pack(cfg.conf_dir, cfg.build)

    # Handle global flags
    if hasattr(args, "debug") and args.debug:
        cfg.debug = True
    if hasattr(args, "yes") and args.yes:
        pass  # Will be passed to commands that need confirmation

    # No command = interactive menu
    if not hasattr(args, "func"):
        return cmd_menu(cfg, pack, args)

    # Dispatch to command handler
    domain = getattr(args, "domain", "?")
    subcmd = getattr(args, "subcmd", "")
    logger.info(f"command: {domain} {subcmd}".strip(), user=os.environ.get("USER", "unknown"))

    try:
        result = args.func(cfg, pack, args)
    except KeyboardInterrupt:
        print()
        fmt.warn("Interrupted.")
        return 130
    except Exception as e:
        fmt.error(f"Command failed: {e}")
        logger.error(f"command failed: {e}", command=f"{domain} {subcmd}".strip())
        if cfg.debug:
            import traceback

            traceback.print_exc()
        return 1

    # Vibe check after successful commands
    if result == 0:
        show_vibe(pack)

    return result or 0


# ---------------------------------------------------------------------------
# Parser builder
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with domain-based command dispatch."""
    parser = argparse.ArgumentParser(
        prog="freq",
        description="PVE FREQ — Datacenter management CLI for homelabbers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"PVE FREQ v{freq.__version__}")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmations")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")

    sub = parser.add_subparsers(dest="domain")

    # Top-level utilities (not under a domain)
    _register_utilities(sub)

    # Domains
    _register_vm(sub)
    _register_fleet(sub)
    _register_host(sub)
    _register_docker(sub)
    _register_secure(sub)
    _register_observe(sub)
    _register_state(sub)
    _register_auto(sub)
    _register_ops(sub)
    _register_hw(sub)
    _register_store(sub)
    _register_dr(sub)
    _register_net(sub)
    _register_fw(sub)
    _register_cert(sub)
    _register_dns(sub)
    _register_proxy(sub)
    _register_media(sub)
    _register_user(sub)
    _register_event(sub)
    _register_vpn(sub)
    _register_plugin(sub)
    _register_config(sub)

    return parser


# ---------------------------------------------------------------------------
# Top-level utilities (no domain prefix)
# ---------------------------------------------------------------------------


def _register_utilities(sub):
    """Register commands that stay top-level: freq <cmd>."""
    p = sub.add_parser("version", help="Show version and branding")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("help", help="Show all commands")
    p.set_defaults(func=cmd_help)

    p = sub.add_parser("doctor", help="Self-diagnostic")
    p.add_argument("--json", dest="json_output", action="store_true", help="Output results as JSON")
    p.add_argument("--history", action="store_true", help="Show health check history")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("perf", help="Performance metrics")
    p.add_argument("--last", type=int, default=100, help="Number of entries to analyze (default: 100)")
    p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_perf)

    p = sub.add_parser("audit", help="Infrastructure change audit trail")
    au_sub = p.add_subparsers(dest="action")
    p_log = au_sub.add_parser("log", help="Show audit log")
    p_log.add_argument("--host", help="Filter by host IP")
    p_log.add_argument("--action", dest="filter_action", help="Filter by action type")
    p_log.add_argument("--last", type=int, default=20, help="Number of entries (default: 20)")
    p_log.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    p_log.set_defaults(func=cmd_audit_log)

    p = sub.add_parser("menu", help="Interactive TUI menu")
    p.set_defaults(func=cmd_menu)

    p = sub.add_parser("demo", help="Interactive demo — no fleet required")
    p.set_defaults(func=_cmd_demo)

    p = sub.add_parser("init", help="First-run setup wizard")
    p.add_argument("--check", action="store_true", help="Validate init state — local files + remote host SSH")
    p.add_argument("--json", dest="json_output", action="store_true", help="Output results as JSON")
    p.add_argument("--fix", action="store_true", help="Scan fleet, find broken hosts, redeploy freq-admin")
    p.add_argument("--reset", action="store_true", help="Wipe vault, roles, .initialized (fresh start)")
    p.add_argument("--uninstall", action="store_true", help="Remove FREQ service account from all hosts")
    p.add_argument("--dry-run", action="store_true", help="Show what init would do (or would remove with --uninstall)")
    p.add_argument("--headless", action="store_true", help="Non-interactive mode (no prompts)")
    p.add_argument("--bootstrap-key", help="SSH key for initial auth to fleet hosts")
    p.add_argument(
        "--bootstrap-user", default="root", help="SSH user for initial auth — root or sudo account (default: root)"
    )
    p.add_argument(
        "--bootstrap-password-file",
        help="Password file for initial auth to PVE nodes (via sshpass, when no bootstrap key)",
    )
    p.add_argument("--password-file", help="Read service account password from file")
    p.add_argument("--pve-nodes", help="PVE node IPs (comma or space-separated)")
    p.add_argument("--pve-node-names", help="PVE node names (comma or space-separated, same order as --pve-nodes)")
    p.add_argument("--gateway", help="Network gateway IP for VM networking")
    p.add_argument("--nameserver", help="DNS nameserver IP (default: 1.1.1.1)")
    p.add_argument("--cluster-name", help="Cluster name (e.g. dc01, homelab)")
    p.add_argument("--ssh-mode", choices=["sudo", "root"], help="SSH mode: sudo (recommended) or root")
    p.add_argument("--hosts-file", help="Path to hosts file to import fleet hosts from")
    p.add_argument("--device-credentials", help="TOML file with per-device-type auth")
    p.add_argument("--device-password-file", help="(deprecated) Single password file for all devices")
    p.add_argument("--device-user", default="root", help="(deprecated) Single SSH user for all devices")
    p.add_argument("--install-pdm", action="store_true", help="Install Proxmox Datacenter Manager")
    p.add_argument("--pdm-pass", help="Password file for PDM root@pam auth")
    p.add_argument("--pdm-remote-name", help="PDM remote name for PVE cluster")
    p.add_argument("--skip-pdm", action="store_true", help="Skip PDM detection and setup entirely")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("configure", help="Reconfigure FREQ settings")
    p.set_defaults(func=_cmd_configure)

    p = sub.add_parser("serve", help="Start web dashboard")
    p.add_argument("--port", type=int, default=None, help="Port number (default: from freq.toml or 8888)")
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser("update", help="Check for updates and upgrade FREQ")
    p.set_defaults(func=_cmd_update)

    p = sub.add_parser("learn", help="Search Proxmox operational knowledge base")
    p.add_argument("query", nargs="*", help="Search terms")
    p.set_defaults(func=_cmd_learn)

    p = sub.add_parser("docs", help="Auto-generated infrastructure documentation")
    p.add_argument(
        "action",
        nargs="?",
        choices=["generate", "export", "verify", "runbook"],
        default="generate",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Runbook name (for runbook action)")
    p.add_argument("--format", default="md", choices=["md", "html"], help="Export format")
    p.set_defaults(func=_cmd_docs)

    p = sub.add_parser("distros", help="List available cloud images")
    p.set_defaults(func=_cmd_distros)

    p = sub.add_parser("notify", help="Send notifications to Discord/Slack")
    p.add_argument("message", nargs="*", help="Notification message")
    p.set_defaults(func=_cmd_notify)

    p = sub.add_parser("agent", help="AI specialist management")
    p.add_argument(
        "action", nargs="?", choices=["templates", "create", "list", "start", "stop", "destroy", "status", "ssh"]
    )
    p.add_argument("name", nargs="?", help="Agent name or template")
    p.add_argument("--agent-name", help="Custom agent name (for create)")
    p.add_argument("--image", help="Cloud image (debian-13, ubuntu-2404, rocky-9, etc.)")
    p.add_argument("--no-cloud-init", action="store_true", help="Create empty VM without cloud-init")
    p.set_defaults(func=_cmd_agent)

    p = sub.add_parser("specialist", help="Specialist VM workspace deployment")
    p.add_argument("action", nargs="?", choices=["create", "health", "status", "list", "roles"], default="list")
    p.add_argument("target", nargs="?", help="Host IP or label")
    p.add_argument("--role", choices=["sandbox", "dev", "infra", "security", "media"], help="Specialist role")
    p.add_argument("--name", help="Specialist name")
    p.set_defaults(func=_cmd_specialist)

    p = sub.add_parser("lab", help="Lab environment management")
    p.add_argument("action", nargs="?", choices=["status", "media", "deploy", "resize", "rebuild"], default="status")
    p.add_argument("service", nargs="?", help="Sub-action (deploy/status for media)")
    p.add_argument("target", nargs="?", help="VMID (for resize/rebuild)")
    p.add_argument("--min", action="store_true", help="Set minimum viable specs")
    p.add_argument("--template", type=int, help="Template VMID for rebuild")
    p.add_argument("--cores", type=int, default=2, help="CPU cores")
    p.add_argument("--ram", type=int, default=2048, help="RAM in MB")
    p.set_defaults(func=_cmd_lab)


# ---------------------------------------------------------------------------
# freq vm — Virtual Machine Lifecycle
# ---------------------------------------------------------------------------


def _register_vm(sub):
    """Register freq vm subcommands."""
    vm = sub.add_parser("vm", help="Virtual machine lifecycle")
    _domain_help(vm)
    vm_sub = vm.add_subparsers(dest="subcmd")

    p = vm_sub.add_parser("list", help="List VMs across PVE cluster")
    p.add_argument("--node", help="Filter by PVE node")
    p.add_argument("--status", help="Filter by status (running/stopped)")
    p.set_defaults(func=_cmd_list)

    p = vm_sub.add_parser("create", help="Create a new VM")
    p.add_argument("--name", help="VM hostname")
    p.add_argument("--image", help="Cloud image (e.g., debian-13, ubuntu-2404)")
    p.add_argument("--node", help="PVE node to create on")
    p.add_argument("--cores", type=int, help="CPU cores")
    p.add_argument("--ram", type=int, help="RAM in MB")
    p.add_argument("--disk", type=int, help="Disk in GB")
    p.add_argument("--vmid", type=int, help="Specific VMID")
    p.add_argument("--nic", action="append", help="NIC profile or VLAN (repeatable)")
    p.add_argument("--ip", action="append", help="Static IP per NIC (repeatable)")
    p.set_defaults(func=_cmd_create)

    p = vm_sub.add_parser("clone", help="Clone a VM with optional network config")
    p.add_argument("source", nargs="?", help="Source VMID or name")
    p.add_argument("--name", help="New VM hostname")
    p.add_argument("--vmid", type=int, help="New VMID")
    p.add_argument("--node", help="Target PVE node")
    p.add_argument("--ip", help="Static IP (triggers disk mount network config)")
    p.add_argument("--vlan", help="VLAN name (dirty/clean/dev/mgmt)")
    p.add_argument("--start", action="store_true", help="Start VM after clone")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    p.set_defaults(func=_cmd_clone)

    p = vm_sub.add_parser("destroy", help="Destroy a VM")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--dry-run", action="store_true", help="Show what would be destroyed without executing")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    p.set_defaults(func=_cmd_destroy)

    p = vm_sub.add_parser("resize", help="Resize a VM")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--cores", type=int, help="New CPU cores")
    p.add_argument("--ram", type=int, help="New RAM in MB")
    p.add_argument("--disk", type=int, help="Add disk in GB")
    p.set_defaults(func=_cmd_resize)

    p = vm_sub.add_parser("snapshot", help="Snapshot management (create/list/delete)")
    p.add_argument(
        "snap_action",
        nargs="?",
        choices=["create", "list", "delete"],
        default="create",
        help="Action: create (default), list, delete",
    )
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--name", help="Snapshot name (for create/delete)")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation for delete")
    p.set_defaults(func=_cmd_snapshot)

    p = vm_sub.add_parser("power", help="VM power control (start/stop/reboot/shutdown/status)")
    p.add_argument("action", choices=["start", "stop", "reboot", "shutdown", "status"], help="Power action")
    p.add_argument("target", help="VMID")
    p.set_defaults(func=_cmd_power)

    p = vm_sub.add_parser("nic", help="VM NIC management (add/clear/change-ip/change-id/check-ip)")
    p.add_argument("action", choices=["add", "clear", "change-ip", "change-id", "check-ip"], help="NIC action")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("--ip", help="IP address (CIDR or bare)")
    p.add_argument("--gw", help="Gateway IP")
    p.add_argument("--vlan", help="VLAN ID")
    p.add_argument("--nic-index", type=int, default=0, help="NIC index (default: 0)")
    p.add_argument("--new-id", help="New VMID (for change-id)")
    p.set_defaults(func=_cmd_nic)

    p = vm_sub.add_parser("import", help="Import a cloud image as a VM")
    p.add_argument("--image", help="Cloud image (debian-13, ubuntu-2404, etc.)")
    p.add_argument("--name", help="VM hostname")
    p.add_argument("--vmid", type=int, help="Specific VMID")
    p.set_defaults(func=_cmd_import)

    p = vm_sub.add_parser("migrate", help="Migrate a VM between nodes")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--node", help="Target PVE node")
    p.add_argument("--storage", help="Target storage pool (auto-detected if omitted)")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmations (auto-delete snapshots)")
    p.add_argument("--dry-run", action="store_true", help="Show migration plan without executing")
    p.set_defaults(func=_cmd_migrate)

    p = vm_sub.add_parser("template", help="Convert a VM to a template")
    p.add_argument("target", nargs="?", help="VMID")
    p.set_defaults(func=_cmd_template)

    p = vm_sub.add_parser("rename", help="Rename a VM")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("--name", help="New hostname")
    p.set_defaults(func=_cmd_rename)

    p = vm_sub.add_parser("disk", help="Add disk(s) to a VM")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("--size", type=int, help="Disk size in GB")
    p.add_argument("--count", type=int, default=1, help="Number of disks")
    p.set_defaults(func=_cmd_add_disk)

    p = vm_sub.add_parser("tag", help="Set/view PVE tags on a VM")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("tags", nargs="?", help="Tags (comma-separated)")
    p.set_defaults(func=_cmd_tag)

    p = vm_sub.add_parser("pool", help="PVE pool management")
    p.add_argument("action", nargs="?", choices=["list", "create", "add"], default="list")
    p.add_argument("--name", help="Pool name")
    p.add_argument("--target", help="VMID to add to pool")
    p.set_defaults(func=_cmd_pool)

    p = vm_sub.add_parser("sandbox", help="Spawn a VM from template")
    p.add_argument("source", nargs="?", help="Template VMID")
    p.add_argument("--name", help="New VM hostname")
    p.add_argument("--vmid", type=int, help="New VMID")
    p.add_argument("--ip", help="Static IP address")
    p.set_defaults(func=_cmd_sandbox)

    p = vm_sub.add_parser("overview", help="VM inventory across cluster")
    p.set_defaults(func=_cmd_vm_overview)

    p = vm_sub.add_parser("config", help="View/edit VM configuration")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.set_defaults(func=_cmd_vmconfig)

    p = vm_sub.add_parser("rescue", help="Rescue a stuck VM")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.set_defaults(func=_cmd_rescue)

    p = vm_sub.add_parser("why", help="Explain VM permissions and protections")
    p.add_argument("target", nargs="?", help="VMID to explain")
    p.set_defaults(func=_cmd_why)

    p = vm_sub.add_parser("rollback", help="Roll back a VM to its latest snapshot")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("--name", help="Specific snapshot name (default: most recent)")
    p.add_argument("--no-start", action="store_true", help="Don't start VM after rollback")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    p.set_defaults(func=_cmd_rollback)

    p = vm_sub.add_parser("provision", help="Cloud-init VM provisioning")
    p.set_defaults(func=_cmd_provision)

    p = vm_sub.add_parser("file", help="Send files to fleet hosts")
    p.add_argument("file_action", nargs="?", choices=["send"], default="send")
    p.add_argument("source", nargs="?", help="Local file path")
    p.add_argument("destination", nargs="?", help="host:remote_path")
    p.set_defaults(func=_cmd_file_send)


# ---------------------------------------------------------------------------
# freq fleet — Fleet Operations
# ---------------------------------------------------------------------------


def _register_fleet(sub):
    """Register freq fleet subcommands."""
    fleet = sub.add_parser("fleet", help="Fleet-wide operations and diagnostics")
    _domain_help(fleet)
    fleet_sub = fleet.add_subparsers(dest="subcmd")

    p = fleet_sub.add_parser("status", help="Fleet health summary")
    p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    p.set_defaults(func=_cmd_status)

    p = fleet_sub.add_parser("dashboard", help="Fleet dashboard overview")
    p.set_defaults(func=_cmd_dashboard)

    p = fleet_sub.add_parser("exec", help="Run command across fleet")
    p.add_argument("target", nargs="?", help="Host label, group, or 'all'")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute")
    p.set_defaults(func=_cmd_exec)

    p = fleet_sub.add_parser("info", help="System info for a host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_info)

    p = fleet_sub.add_parser("detail", help="Deep host inventory (full system detail)")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_detail)

    p = fleet_sub.add_parser("boundaries", help="Fleet boundary tiers and VM categories")
    p.add_argument("action", nargs="?", default="show", choices=["show", "lookup"], help="Action (default: show)")
    p.add_argument("target", nargs="?", help="VMID (for lookup)")
    p.set_defaults(func=_cmd_boundaries)

    p = fleet_sub.add_parser("diagnose", help="Deep diagnostic for a host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_diagnose)

    p = fleet_sub.add_parser("ssh", help="SSH to a fleet host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_ssh)

    p = fleet_sub.add_parser("docker", help="Container discovery and management")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_docker)

    p = fleet_sub.add_parser("log", help="View logs for a host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.add_argument("--lines", "-n", type=int, default=30, help="Number of log lines")
    p.add_argument("--unit", "-u", help="Systemd unit to filter")
    p.set_defaults(func=_cmd_log)

    p = fleet_sub.add_parser("compare", help="Compare two hosts side-by-side")
    p.add_argument("target_a", nargs="?", help="First host label or IP")
    p.add_argument("target_b", nargs="?", help="Second host label or IP")
    p.set_defaults(func=_cmd_compare)

    p = fleet_sub.add_parser("health", help="Comprehensive fleet health")
    p.set_defaults(func=_cmd_health)

    p = fleet_sub.add_parser("report", help="Generate fleet health report")
    p.add_argument("action", nargs="?", choices=["generate"], default="generate", help="Action to perform")
    p.add_argument("--markdown", action="store_true", help="Markdown output")
    p.set_defaults(func=_cmd_report)

    p = fleet_sub.add_parser("ntp", help="Fleet NTP check/fix")
    p.add_argument("action", nargs="?", choices=["check", "fix"], default="check")
    p.set_defaults(func=_cmd_ntp)

    p = fleet_sub.add_parser("update", help="Fleet OS update check/apply")
    p.add_argument("action", nargs="?", choices=["check", "apply"], default="check")
    p.set_defaults(func=_cmd_fleet_update)

    p = fleet_sub.add_parser("comms", help="Inter-VM communication")
    p.add_argument("action", nargs="?", choices=["setup", "send", "check", "read"], default="check")
    p.add_argument("--target", help="Destination host")
    p.add_argument("--message", "-m", help="Message text")
    p.set_defaults(func=_cmd_comms)

    p = fleet_sub.add_parser("inventory", help="Full fleet inventory export (hosts/VMs/containers)")
    p.add_argument(
        "section",
        nargs="?",
        choices=["all", "hosts", "vms", "containers"],
        default="all",
        help="Section to export (default: all)",
    )
    p.add_argument("--csv", action="store_true", help="CSV output")
    p.set_defaults(func=_cmd_inventory)

    p = fleet_sub.add_parser("federation", help="Multi-site federation")
    p.add_argument(
        "action", nargs="?", choices=["list", "register", "remove", "poll"], default="list", help="Action to perform"
    )
    p.add_argument("--name", help="Site name")
    p.add_argument("--url", help="Site URL")
    p.add_argument("--secret", default="", help="Shared secret")
    p.set_defaults(func=_cmd_federation)

    p = fleet_sub.add_parser("deploy-agent", help="Deploy metrics collector to fleet")
    p.add_argument("target", nargs="?", help="Host label or 'all'")
    p.set_defaults(func=_cmd_deploy_agent)

    p = fleet_sub.add_parser("agent-status", help="Check metrics agent status across fleet")
    p.set_defaults(func=_cmd_agent_status)

    p = fleet_sub.add_parser("test", help="Test host connectivity (TCP + SSH + sudo)")
    p.add_argument("target", nargs="?", help="Host IP or label")
    p.set_defaults(func=_cmd_test_connection)


# ---------------------------------------------------------------------------
# freq host — Host Registry
# ---------------------------------------------------------------------------


def _register_host(sub):
    """Register freq host subcommands."""
    host = sub.add_parser("host", help="Host registry and management")
    _domain_help(host)
    host_sub = host.add_subparsers(dest="subcmd")

    p = host_sub.add_parser("list", help="List fleet hosts")
    p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    p.set_defaults(func=_set_action(_cmd_hosts, "list"))

    p = host_sub.add_parser("add", help="Add a host to the fleet")
    p.set_defaults(func=_set_action(_cmd_hosts, "add"))

    p = host_sub.add_parser("remove", help="Remove a host from the fleet")
    p.set_defaults(func=_set_action(_cmd_hosts, "remove"))

    p = host_sub.add_parser("edit", help="Edit host configuration")
    p.set_defaults(func=_set_action(_cmd_hosts, "edit"))

    p = host_sub.add_parser("sync", help="Sync host list from PVE cluster")
    p.add_argument("--dry-run", action="store_true", help="Show what sync would change without writing")
    p.set_defaults(func=_set_action(_cmd_hosts, "sync"))

    p = host_sub.add_parser("discover", help="Discover hosts on the network")
    p.add_argument("subnet", nargs="?", help="Subnet to scan (e.g. 192.168.1 or 192.168.1.0/24)")
    p.set_defaults(func=_cmd_discover)

    p = host_sub.add_parser("groups", help="Manage host groups")
    p.add_argument("action", nargs="?", choices=["list", "add", "remove"], default="list")
    p.set_defaults(func=_cmd_groups)

    p = host_sub.add_parser("bootstrap", help="Bootstrap a new host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_bootstrap)

    p = host_sub.add_parser("onboard", help="Onboard a host to the fleet")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_onboard)

    p = host_sub.add_parser("keys", help="SSH key management")
    p.add_argument("action", nargs="?", choices=["deploy", "list", "rotate"], help="Key action")
    p.add_argument("--target", help="Host label for deploy")
    p.set_defaults(func=_cmd_keys)


# ---------------------------------------------------------------------------
# freq docker — Container Management
# ---------------------------------------------------------------------------


def _register_docker(sub):
    """Register freq docker subcommands."""
    docker = sub.add_parser("docker", help="Container and stack management")
    _domain_help(docker)
    docker_sub = docker.add_subparsers(dest="subcmd")

    p = docker_sub.add_parser("containers", help="Container discovery on a host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_docker)

    p = docker_sub.add_parser("fleet", help="Fleet-wide Docker operations (ps/logs/stats)")
    p.add_argument(
        "docker_action",
        nargs="?",
        choices=["ps", "logs", "stats"],
        default="ps",
        help="Action: ps (default), logs, stats",
    )
    p.add_argument("service", nargs="?", help="Service name (for logs)")
    p.add_argument("--lines", "-n", type=int, default=20, help="Log lines (for logs)")
    p.set_defaults(func=_cmd_docker_fleet)

    p = docker_sub.add_parser("stack", help="Docker Compose stack management")
    p.add_argument(
        "action",
        nargs="?",
        choices=["status", "update", "health", "logs", "restart", "template"],
        default="status",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Stack name")
    p.add_argument("--host", dest="target_host", help="Target host")
    p.add_argument("--lines", type=int, default=30, help="Log lines")
    p.set_defaults(func=_cmd_stack)

    p = docker_sub.add_parser("monitor", help="Check HTTP endpoints defined in config")
    p.set_defaults(func=_cmd_monitor)

    # Fleet Docker management (WS13)
    p = docker_sub.add_parser("list", help="List containers across fleet")
    p.set_defaults(func=_cmd_docker_containers)
    p = docker_sub.add_parser("images", help="List images across fleet")
    p.set_defaults(func=_cmd_docker_images)
    p = docker_sub.add_parser("prune", help="Clean up unused resources fleet-wide")
    p.set_defaults(func=_cmd_docker_prune)
    p = docker_sub.add_parser("update-check", help="Check for image updates")
    p.set_defaults(func=_cmd_docker_update_check)


# ---------------------------------------------------------------------------
# freq secure — Security & Compliance
# ---------------------------------------------------------------------------


def _register_secure(sub):
    """Register freq secure subcommands."""
    secure = sub.add_parser("secure", help="Security auditing, compliance, and hardening")
    _domain_help(secure)
    secure_sub = secure.add_subparsers(dest="subcmd")

    p = secure_sub.add_parser("vault", help="Encrypted credential store")
    p.add_argument("action", nargs="?", choices=["init", "set", "get", "delete", "list", "import"])
    p.add_argument("key", nargs="?", help="Vault key name")
    p.add_argument("value", nargs="?", help="Vault value (for set)")
    p.add_argument("--host", help="Host scope (default: DEFAULT)")
    p.set_defaults(func=_cmd_vault)

    p = secure_sub.add_parser("audit", help="Security audit")
    p.add_argument("target", nargs="?", help="Host label or 'all'")
    p.add_argument("--fix", action="store_true", help="Auto-fix findings")
    p.set_defaults(func=_cmd_audit)

    p = secure_sub.add_parser("harden", help="Apply security hardening")
    p.add_argument("target", nargs="?", help="Host label or 'all'")
    p.set_defaults(func=_cmd_harden)

    p = secure_sub.add_parser("comply", help="CIS/STIG compliance scanning")
    p.add_argument(
        "action",
        nargs="?",
        choices=["scan", "status", "report", "exceptions"],
        default="scan",
        help="Action to perform",
    )
    p.set_defaults(func=_cmd_comply)

    p = secure_sub.add_parser("patch", help="Fleet patch management (status/check/apply/hold)")
    p.add_argument(
        "action",
        nargs="?",
        choices=["status", "check", "apply", "hold", "history", "compliance"],
        default="status",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Package name (for hold)")
    p.add_argument("--target-host", help="Target specific host")
    p.add_argument("--lines", type=int, default=20, help="History lines")
    p.set_defaults(func=_cmd_patch)

    p = secure_sub.add_parser("secrets", help="Secret rotation, scanning, and lifecycle")
    p.add_argument(
        "action",
        nargs="?",
        choices=["list", "scan", "audit", "generate", "rotate", "lease"],
        default="list",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Secret/lease name")
    p.add_argument("--secret-type", default="password", choices=["password", "token"], help="Type for generate")
    p.add_argument("--length", type=int, default=32, help="Secret length (default: 32)")
    p.add_argument("--expires", default="90d", help="Lease expiry (e.g., 90d, 24h)")
    p.set_defaults(func=_cmd_secrets)

    p = secure_sub.add_parser("sweep", help="Full audit + policy check pipeline")
    p.add_argument("--fix", action="store_true", help="Apply fixes (default: dry run)")
    p.set_defaults(func=_cmd_sweep)

    # Vulnerability scanning (WS11)
    vuln = secure_sub.add_parser("vuln", help="Vulnerability scanning")
    vuln_sub = vuln.add_subparsers(dest="action")
    p = vuln_sub.add_parser("scan", help="Scan fleet for vulnerabilities")
    p.set_defaults(func=_cmd_vuln_scan)
    p = vuln_sub.add_parser("results", help="Show last scan results")
    p.set_defaults(func=_cmd_vuln_results)
    vuln.set_defaults(func=_cmd_vuln_scan)

    # File integrity monitoring (WS11)
    fim = secure_sub.add_parser("fim", help="File integrity monitoring")
    fim_sub = fim.add_subparsers(dest="action")
    p = fim_sub.add_parser("baseline", help="Create file integrity baseline")
    p.set_defaults(func=_cmd_fim_baseline)
    p = fim_sub.add_parser("check", help="Check against baseline")
    p.set_defaults(func=_cmd_fim_check)
    p = fim_sub.add_parser("status", help="Show baseline status")
    p.set_defaults(func=_cmd_fim_status)
    fim.set_defaults(func=_cmd_fim_status)


# ---------------------------------------------------------------------------
# freq observe — Observability Platform
# ---------------------------------------------------------------------------


def _register_observe(sub):
    """Register freq observe subcommands."""
    observe = sub.add_parser("observe", help="Monitoring, alerting, logs, and trends")
    _domain_help(observe)
    observe_sub = observe.add_subparsers(dest="subcmd")

    p = observe_sub.add_parser("alert", help="Alert management (create/list/delete/history/test/silence/check)")
    p.add_argument(
        "action",
        nargs="?",
        choices=["list", "create", "delete", "history", "test", "silence", "check"],
        default="list",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Alert rule name (for create/delete/silence)")
    p.add_argument(
        "--condition", help="Alert condition (host_down, cpu_above, ram_above, disk_above, docker_down, load_spike)"
    )
    p.add_argument("--threshold", type=float, default=0, help="Threshold value")
    p.add_argument(
        "--alert-severity", default="warning", choices=["info", "warning", "critical"], help="Alert severity"
    )
    p.add_argument("--target-host", default="*", help="Target host pattern (* for all)")
    p.add_argument("--cooldown", type=int, default=300, help="Seconds between re-alerts (default: 300)")
    p.add_argument("--duration", type=int, default=60, help="Silence duration in minutes (default: 60)")
    p.add_argument("--reason", default="", help="Silence reason")
    p.add_argument("--lines", type=int, default=20, help="History lines to show")
    p.set_defaults(func=_cmd_alert)

    p = observe_sub.add_parser("logs", help="Fleet-wide log search and aggregation")
    p.add_argument(
        "action", nargs="?", choices=["tail", "search", "stats", "export"], default="tail", help="Action to perform"
    )
    p.add_argument("pattern", nargs="?", help="Search pattern (for search)")
    p.add_argument("--host", dest="target_host", help="Target specific host")
    p.add_argument("--since", default="1h", help="Time range (default: 1h)")
    p.add_argument("--lines", type=int, default=20, help="Lines to show")
    p.add_argument("--unit", help="Systemd unit filter")
    p.set_defaults(func=_cmd_logs)

    p = observe_sub.add_parser("trend", help="Fleet capacity trends over time")
    p.add_argument(
        "action", nargs="?", choices=["show", "snapshot", "history"], default="show", help="Action to perform"
    )
    p.add_argument("--lines", type=int, default=20, help="History lines to show")
    p.set_defaults(func=_cmd_trend)

    p = observe_sub.add_parser("capacity", help="Fleet capacity projections")
    p.add_argument(
        "action", nargs="?", choices=["show", "snapshot"], default="show", help="show projections or force a snapshot"
    )
    p.set_defaults(func=_cmd_capacity)

    p = observe_sub.add_parser("sla", help="Fleet uptime SLA tracking")
    p.add_argument("action", nargs="?", choices=["show", "check", "reset"], default="show", help="Action to perform")
    p.add_argument("--days", type=int, default=30, help="SLA period in days (default: 30)")
    p.set_defaults(func=_cmd_sla)

    p = observe_sub.add_parser("watch", help="Monitoring daemon")
    p.set_defaults(func=_cmd_watch)

    p = observe_sub.add_parser("db", help="Fleet-wide database health (status/health/size)")
    p.add_argument(
        "action", nargs="?", choices=["status", "health", "size"], default="status", help="Action to perform"
    )
    p.set_defaults(func=_cmd_db)

    # Metrics (WS10)
    met = observe_sub.add_parser("metrics", help="Time-series metrics collection")
    met_sub = met.add_subparsers(dest="action")
    p = met_sub.add_parser("collect", help="Collect metrics from fleet")
    p.set_defaults(func=_cmd_metrics_collect)
    p = met_sub.add_parser("show", help="Show latest metrics")
    p.add_argument("target", nargs="?", help="Host label")
    p.set_defaults(func=_cmd_metrics_show)
    p = met_sub.add_parser("top", help="Top resource consumers")
    p.set_defaults(func=_cmd_metrics_top)
    met.set_defaults(func=_cmd_metrics_show)

    # Monitors (WS10)
    mon = observe_sub.add_parser("monitor", help="Synthetic endpoint monitoring")
    mon_sub = mon.add_subparsers(dest="action")
    p = mon_sub.add_parser("list", help="List monitors")
    p.set_defaults(func=_cmd_monitor_list)
    p = mon_sub.add_parser("add", help="Add a monitor")
    p.add_argument("--name", required=True, help="Monitor name")
    p.add_argument("--type", required=True, choices=["http", "tcp", "dns", "ssl"], help="Check type")
    p.add_argument("--target", required=True, help="URL or host:port")
    p.add_argument("--interval", default="5m", help="Check interval")
    p.set_defaults(func=_cmd_monitor_add)
    p = mon_sub.add_parser("run", help="Execute all checks")
    p.set_defaults(func=_cmd_monitor_run)
    p = mon_sub.add_parser("remove", help="Remove a monitor")
    p.add_argument("--name", required=True, help="Monitor name")
    p.set_defaults(func=_cmd_monitor_remove)
    mon.set_defaults(func=_cmd_monitor_list)


# ---------------------------------------------------------------------------
# freq state — Desired State & Drift Management
# ---------------------------------------------------------------------------


def _register_state(sub):
    """Register freq state subcommands."""
    state = sub.add_parser("state", help="Baselines, plans, policies, drift detection")
    _domain_help(state)
    state_sub = state.add_subparsers(dest="subcmd")

    p = state_sub.add_parser("baseline", help="Configuration baseline and drift detection")
    p.add_argument(
        "action", nargs="?", choices=["capture", "compare", "list", "delete"], default="list", help="Action to perform"
    )
    p.add_argument("name", nargs="?", help="Baseline name")
    p.set_defaults(func=_cmd_baseline)

    p = state_sub.add_parser("plan", help="Show fleet plan diff (desired vs actual)")
    p.add_argument("--file", help="Path to fleet plan TOML (default: conf/fleet-plan.toml)")
    p.set_defaults(func=_cmd_plan)

    p = state_sub.add_parser("apply", help="Apply fleet plan (execute creates/resizes)")
    p.add_argument("--file", help="Path to fleet plan TOML (default: conf/fleet-plan.toml)")
    p.add_argument("--dry-run", action="store_true", help="Show what would change without executing")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmations")
    p.set_defaults(func=_cmd_apply)

    p = state_sub.add_parser("check", help="Check policy compliance (dry run)")
    p.add_argument("policy", nargs="?", help="Policy name")
    p.add_argument("--hosts", help="Comma-separated host labels")
    p.set_defaults(func=_cmd_check)

    p = state_sub.add_parser("fix", help="Apply policy remediation")
    p.add_argument("policy", nargs="?", help="Policy name")
    p.add_argument("--hosts", help="Comma-separated host labels")
    p.set_defaults(func=_cmd_fix)

    p = state_sub.add_parser("diff", help="Show policy drift as git-style diff")
    p.add_argument("policy", nargs="?", help="Policy name")
    p.add_argument("--hosts", help="Comma-separated host labels")
    p.set_defaults(func=_cmd_diff)

    p = state_sub.add_parser("policies", help="List available policies")
    p.set_defaults(func=_cmd_policies)

    p = state_sub.add_parser("gitops", help="GitOps config sync")
    p.add_argument(
        "action",
        nargs="?",
        choices=["status", "sync", "apply", "diff", "log"],
        default="status",
        help="Action to perform",
    )
    p.set_defaults(func=_cmd_gitops)

    # IaC extensions (WS15)
    p = state_sub.add_parser("export", help="Export infrastructure state snapshot")
    p.set_defaults(func=_cmd_state_export)

    p = state_sub.add_parser("drift", help="Detect configuration drift")
    p.set_defaults(func=_cmd_state_drift)

    p = state_sub.add_parser("history", help="State snapshot history")
    p.set_defaults(func=_cmd_state_history)


# ---------------------------------------------------------------------------
# freq auto — Automation & Scheduling
# ---------------------------------------------------------------------------


def _register_auto(sub):
    """Register freq auto subcommands."""
    auto = sub.add_parser("auto", help="Rules, scheduling, playbooks, webhooks, automation")
    _domain_help(auto)
    auto_sub = auto.add_subparsers(dest="subcmd")

    p = auto_sub.add_parser("rules", help="Alert rule management")
    p.add_argument(
        "action", nargs="?", choices=["list", "create", "delete", "history"], default="list", help="Action to perform"
    )
    p.add_argument("name", nargs="?", help="Rule name (for create/delete)")
    p.add_argument(
        "--condition", help="Rule condition (host_unreachable, cpu_above, ram_above, disk_above, docker_down)"
    )
    p.add_argument("--threshold", type=float, default=0, help="Threshold value")
    p.add_argument("--severity", default="warning", help="Alert severity (info/warning/critical)")
    p.add_argument("--target-host", default="*", help="Target host pattern")
    p.add_argument("--duration", type=int, default=0, help="Seconds before alerting")
    p.add_argument("--cooldown", type=int, default=300, help="Seconds between re-alerts")
    p.set_defaults(func=_cmd_rules)

    p = auto_sub.add_parser("schedule", help="Job scheduler (create/list/delete/run/templates)")
    p.add_argument(
        "action",
        nargs="?",
        choices=["list", "create", "delete", "run", "enable", "disable", "log", "templates", "install"],
        default="list",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Job name")
    p.add_argument("--command", help="Command to schedule")
    p.add_argument("--interval", help="Run interval (5m, 2h, 1d)")
    p.add_argument("--lines", type=int, default=20, help="Log lines to show")
    p.set_defaults(func=_cmd_schedule)

    p = auto_sub.add_parser("playbook", help="Incident playbook runner")
    p.add_argument("action", nargs="?", choices=["list", "run"], default="list", help="List playbooks or run one")
    p.add_argument("name", nargs="?", help="Playbook filename or name")
    p.set_defaults(func=_cmd_playbook)

    p = auto_sub.add_parser("webhook", help="Inbound webhook management (create/list/test)")
    p.add_argument(
        "action",
        nargs="?",
        choices=["list", "create", "delete", "test", "log"],
        default="list",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Webhook name")
    p.add_argument("--command", help="Command to execute on trigger")
    p.add_argument("--secret", help="HMAC secret for signature verification")
    p.add_argument("--lines", type=int, default=20, help="Log lines to show")
    p.set_defaults(func=_cmd_webhook)

    p = auto_sub.add_parser("chaos", help="Chaos engineering experiments")
    p.add_argument("action", nargs="?", choices=["list", "run", "log"], default="list", help="Action to perform")
    p.add_argument("--type", help="Experiment type")
    p.add_argument("--host", help="Target host label")
    p.add_argument("--service", default="", help="Target service name")
    p.add_argument("--duration", type=int, default=60, help="Duration in seconds (max 300)")
    p.set_defaults(func=_cmd_chaos)

    p = auto_sub.add_parser("patrol", help="Continuous monitoring + drift detection")
    p.add_argument("--interval", type=int, default=30, help="Check interval in seconds")
    p.add_argument("--auto-fix", action="store_true", help="Auto-remediate drift")
    p.set_defaults(func=_cmd_patrol)

    # Reactor (WS16)
    react = auto_sub.add_parser("react", help="Event-driven automation reactors")
    react_sub = react.add_subparsers(dest="action")
    p = react_sub.add_parser("list", help="List reactors")
    p.set_defaults(func=_cmd_react_list)
    p = react_sub.add_parser("add", help="Add a reactor")
    p.add_argument("--name", required=True, help="Reactor name")
    p.add_argument("--trigger", required=True, help="Trigger event")
    p.add_argument("--action", required=True, dest="react_action", help="Action command")
    p.add_argument("--cooldown", type=int, default=300, help="Cooldown seconds")
    p.set_defaults(func=_cmd_react_add)
    p = react_sub.add_parser("disable", help="Disable a reactor")
    p.add_argument("name", help="Reactor name")
    p.set_defaults(func=_cmd_react_disable)
    react.set_defaults(func=_cmd_react_list)

    # Workflow (WS16)
    wf = auto_sub.add_parser("workflow", help="Automation workflows")
    wf_sub = wf.add_subparsers(dest="action")
    p = wf_sub.add_parser("list", help="List workflows")
    p.set_defaults(func=_cmd_workflow_list)
    p = wf_sub.add_parser("create", help="Create a workflow")
    p.add_argument("name", help="Workflow name")
    p.add_argument("--description", default="", help="Description")
    p.set_defaults(func=_cmd_workflow_create)
    wf.set_defaults(func=_cmd_workflow_list)

    # Job (WS16)
    p = auto_sub.add_parser("job", help="Named job operations")
    p.set_defaults(func=_cmd_job_list)


# ---------------------------------------------------------------------------
# freq ops — Operations
# ---------------------------------------------------------------------------


def _register_ops(sub):
    """Register freq ops subcommands."""
    ops = sub.add_parser("ops", help="On-call rotation and risk analysis")
    _domain_help(ops)
    ops_sub = ops.add_subparsers(dest="subcmd")

    p = ops_sub.add_parser("oncall", help="On-call rotation and incident management")
    p.add_argument(
        "action",
        nargs="?",
        choices=["whoami", "schedule", "alert", "ack", "escalate", "resolve", "history"],
        default="whoami",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Incident ID (for ack/escalate/resolve)")
    p.add_argument("--users", help="Comma-separated user list (for schedule)")
    p.add_argument("--rotation", choices=["daily", "weekly", "biweekly"], help="Rotation period")
    p.add_argument("--message", default="", help="Incident message (for alert)")
    p.add_argument("--alert-severity", default="warning", choices=["info", "warning", "critical"])
    p.add_argument("--host", dest="target_host", help="Affected host")
    p.add_argument("--note", default="", help="Resolution note")
    p.add_argument("--lines", type=int, default=20, help="History lines")
    p.set_defaults(func=_cmd_oncall)

    p = ops_sub.add_parser("risk", help="Kill-chain blast radius analysis")
    p.add_argument("target", nargs="?", help="Infrastructure target (pfsense/truenas/switch/all)")
    p.set_defaults(func=_cmd_risk)

    # Incident management (WS12)
    inc = ops_sub.add_parser("incident", help="Incident tracking")
    inc_sub = inc.add_subparsers(dest="action")
    p = inc_sub.add_parser("create", help="Create incident")
    p.add_argument("title", help="Incident title")
    p.add_argument("--severity", default="warning", choices=["info", "warning", "critical"])
    p.set_defaults(func=_cmd_incident_create)
    p = inc_sub.add_parser("list", help="List incidents")
    p.set_defaults(func=_cmd_incident_list)
    p = inc_sub.add_parser("update", help="Update incident")
    p.add_argument("id", help="Incident ID (e.g. INC-1)")
    p.add_argument("--status", required=True, choices=["investigating", "resolved", "closed"])
    p.add_argument("--note", default="")
    p.set_defaults(func=_cmd_incident_update)
    inc.set_defaults(func=_cmd_incident_list)

    # Change management (WS12)
    chg = ops_sub.add_parser("change", help="Change request management")
    chg_sub = chg.add_subparsers(dest="action")
    p = chg_sub.add_parser("create", help="Create change request")
    p.add_argument("title", help="Change title")
    p.add_argument("--risk", default="low", choices=["low", "medium", "high", "critical"])
    p.set_defaults(func=_cmd_change_create)
    p = chg_sub.add_parser("list", help="List changes")
    p.set_defaults(func=_cmd_change_list)
    chg.set_defaults(func=_cmd_change_list)


# ---------------------------------------------------------------------------
# freq hw — Hardware & Cost
# ---------------------------------------------------------------------------


def _register_hw(sub):
    """Register freq hw subcommands."""
    hw = sub.add_parser("hw", help="Hardware management and cost analysis")
    _domain_help(hw)
    hw_sub = hw.add_subparsers(dest="subcmd")

    p = hw_sub.add_parser("idrac", help="Dell iDRAC management")
    p.add_argument("action", nargs="?", help="Subcommand (status/sensors/power/sel/info)")
    p.set_defaults(func=_cmd_idrac)

    p = hw_sub.add_parser("cost", help="Fleet power cost estimates")
    p.set_defaults(func=_cmd_cost)

    p = hw_sub.add_parser("cost-analysis", help="On-prem FinOps and cost optimization")
    p.add_argument(
        "action",
        nargs="?",
        choices=["waste", "density", "optimize", "compare"],
        default="waste",
        help="Action to perform",
    )
    p.add_argument("--rate", type=float, default=0.12, help="Electricity rate $/kWh (default: 0.12)")
    p.set_defaults(func=_cmd_cost_analysis)

    p = hw_sub.add_parser("gwipe", help="FREQ WIPE — drive sanitization station")
    p.add_argument(
        "action",
        nargs="?",
        default="status",
        help="Subcommand (status/bays/history/test/wipe/full-send/pause/resume/connect)",
    )
    p.add_argument("target", nargs="?", help="Bay device (e.g. sdb) for per-bay actions")
    p.add_argument("--host", help="GWIPE station IP (overrides vault)")
    p.add_argument("--key", help="API key (overrides vault)")
    p.set_defaults(func=_cmd_gwipe)

    # Hardware monitoring (WS14)
    p = hw_sub.add_parser("smart", help="Fleet-wide SMART health check")
    p.set_defaults(func=_cmd_hw_smart)
    p = hw_sub.add_parser("ups", help="UPS status via NUT")
    p.set_defaults(func=_cmd_hw_ups)
    p = hw_sub.add_parser("power", help="Fleet power consumption estimates")
    p.set_defaults(func=_cmd_hw_power)
    p = hw_sub.add_parser("inventory", help="Hardware inventory across fleet")
    p.set_defaults(func=_cmd_hw_inventory)


# ---------------------------------------------------------------------------
# freq store — Storage Management
# ---------------------------------------------------------------------------


def _register_store(sub):
    """Register freq store subcommands."""
    store = sub.add_parser("store", help="TrueNAS, ZFS, and storage management")
    _domain_help(store)
    store_sub = store.add_subparsers(dest="subcmd")

    p = store_sub.add_parser("status", help="TrueNAS system status")
    p.set_defaults(func=_cmd_store_status)

    p = store_sub.add_parser("pools", help="ZFS pool details")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_store_pools)

    p = store_sub.add_parser("datasets", help="ZFS datasets")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_store_datasets)

    p = store_sub.add_parser("snapshots", help="ZFS snapshots")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_store_snapshots)

    p = store_sub.add_parser("smart", help="SMART drive health")
    p.set_defaults(func=_cmd_store_smart)

    p = store_sub.add_parser("shares", help="NFS/SMB shares")
    p.set_defaults(func=_cmd_store_shares)

    p = store_sub.add_parser("alerts", help="TrueNAS alerts")
    p.set_defaults(func=_cmd_store_alerts)

    # Legacy
    p = store_sub.add_parser("nas", help="TrueNAS management (legacy)")
    p.add_argument("action", nargs="?", help="Subcommand")
    p.set_defaults(func=_cmd_truenas)

    store.set_defaults(func=_cmd_store_status)


# ---------------------------------------------------------------------------
# freq dr — Disaster Recovery & Backup
# ---------------------------------------------------------------------------


def _register_dr(sub):
    """Register freq dr subcommands."""
    dr = sub.add_parser("dr", help="Backup, recovery, and SLA")
    _domain_help(dr)
    dr_sub = dr.add_subparsers(dest="subcmd")

    p = dr_sub.add_parser("backup", help="VM snapshots, config export, retention")
    p.add_argument("action", nargs="?", choices=["list", "create", "export", "status", "prune"], default="list")
    p.add_argument("target", nargs="?", help="VMID (for create)")
    p.set_defaults(func=_cmd_backup)

    p = dr_sub.add_parser("policy", help="Declarative backup rules (create/list/apply)")
    p.add_argument(
        "action",
        nargs="?",
        choices=["list", "create", "delete", "apply", "status"],
        default="list",
        help="Action to perform",
    )
    p.add_argument("name", nargs="?", help="Policy name")
    p.add_argument("--target", help="Target selector (tag name, vmid range, or *)")
    p.add_argument("--target-type", default="tag", choices=["tag", "vmid_range", "all"], help="Target type")
    p.add_argument("--interval", default="24h", help="Snapshot interval (default: 24h)")
    p.add_argument("--retention", type=int, default=7, help="Days to retain (default: 7)")
    p.set_defaults(func=_cmd_backup_policy)

    p = dr_sub.add_parser("journal", help="Operation history")
    p.add_argument("--lines", "-n", type=int, default=20, help="Number of entries")
    p.add_argument("--search", "-s", help="Search filter")
    p.set_defaults(func=_cmd_journal)

    p = dr_sub.add_parser("migrate-plan", help="Load-aware migration recommendations")
    p.add_argument("action", nargs="?", choices=["show"], default="show", help="Action to perform")
    p.set_defaults(func=_cmd_migrate_plan)

    p = dr_sub.add_parser("migrate-vmware", help="VMware ESXi to Proxmox migration")
    p.add_argument(
        "action", nargs="?", choices=["scan", "import", "convert", "status"], default="scan", help="Action to perform"
    )
    p.add_argument("target", nargs="?", help="OVA/VMDK file or directory path")
    p.add_argument("--vmid", type=int, help="Target VMID for import")
    p.add_argument("--node", help="Target PVE node")
    p.add_argument("--storage", default="local-lvm", help="Target storage (default: local-lvm)")
    p.set_defaults(func=_cmd_migrate_vmware)

    # DR orchestration (new)
    p = dr_sub.add_parser("status", help="DR readiness overview")
    p.set_defaults(func=_cmd_dr_status)

    p = dr_sub.add_parser("verify", help="Verify backup coverage against SLA")
    p.set_defaults(func=_cmd_dr_backup_verify)

    # SLA subcommands
    sla = dr_sub.add_parser("sla", help="SLA target management")
    sla_sub = sla.add_subparsers(dest="sla_action")

    p = sla_sub.add_parser("list", help="List SLA targets")
    p.set_defaults(func=_cmd_dr_sla_list)

    p = sla_sub.add_parser("set", help="Set SLA target for a VM")
    p.add_argument("vmid", help="VM ID")
    p.add_argument("--rpo", type=int, default=24, help="RPO in hours")
    p.add_argument("--rto", type=int, default=4, help="RTO in hours")
    p.add_argument("--name", help="VM name")
    p.add_argument("--tier", default="standard", help="Service tier")
    p.add_argument("--priority", type=int, default=50, help="Recovery priority (1=highest)")
    p.set_defaults(func=_cmd_dr_sla_set)

    sla.set_defaults(func=_cmd_dr_sla_list)

    # Runbook subcommands
    rb = dr_sub.add_parser("runbook", help="DR runbook management")
    rb_sub = rb.add_subparsers(dest="rb_action")

    p = rb_sub.add_parser("list", help="List runbooks")
    p.set_defaults(func=_cmd_dr_runbook_list)

    p = rb_sub.add_parser("create", help="Create a runbook")
    p.add_argument("name", help="Runbook name")
    p.add_argument("--description", default="", help="Description")
    p.set_defaults(func=_cmd_dr_runbook_create)

    p = rb_sub.add_parser("show", help="Show runbook steps")
    p.add_argument("name", help="Runbook name")
    p.set_defaults(func=_cmd_dr_runbook_show)

    rb.set_defaults(func=_cmd_dr_runbook_list)


# ---------------------------------------------------------------------------
# freq net — Network Intelligence & Switch Management
# ---------------------------------------------------------------------------


def _register_net(sub):
    """Register freq net subcommands."""
    net = sub.add_parser("net", help="Network monitoring, switches, and IPAM")
    _domain_help(net)
    net_sub = net.add_subparsers(dest="subcmd")

    # freq net switch <action> — graduated to switch_orchestration module
    sw = net_sub.add_parser("switch", help="Network switch management")
    sw_sub = sw.add_subparsers(dest="action")

    p = sw_sub.add_parser("show", help="Switch overview (facts + interface summary)")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_switch_show)

    p = sw_sub.add_parser("facts", help="Device facts: hostname, model, serial, OS, uptime")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_switch_facts)

    p = sw_sub.add_parser("interfaces", help="Interface table with status, speed, VLAN")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_switch_interfaces)

    p = sw_sub.add_parser("vlans", help="VLAN table with port membership")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_switch_vlans)

    p = sw_sub.add_parser("mac", help="MAC address table")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("--vlan", help="Filter by VLAN ID")
    p.set_defaults(func=_cmd_switch_mac)

    p = sw_sub.add_parser("arp", help="ARP table")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_switch_arp)

    p = sw_sub.add_parser("neighbors", help="LLDP/CDP neighbor table")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_switch_neighbors)

    p = sw_sub.add_parser("config", help="Display or backup running configuration")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("--backup", action="store_true", help="Save config to conf/switch-configs/")
    p.set_defaults(func=_cmd_switch_config)

    p = sw_sub.add_parser("environment", help="Temperature, fans, PSU, CPU, memory")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_switch_environment)

    p = sw_sub.add_parser("exec", help="Run arbitrary show command")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("command", nargs="?", help="Command to execute")
    p.add_argument("--all", action="store_true", help="Run on all switches")
    p.set_defaults(func=_cmd_switch_exec)

    # freq net switch profile <action>
    prof = sw_sub.add_parser("profile", help="Port profile management")
    prof_sub = prof.add_subparsers(dest="profile_action")

    p = prof_sub.add_parser("list", help="List all port profiles")
    p.set_defaults(func=_cmd_profile_list)

    p = prof_sub.add_parser("show", help="Show profile details")
    p.add_argument("name", help="Profile name")
    p.set_defaults(func=_cmd_profile_show)

    p = prof_sub.add_parser("apply", help="Apply profile to port(s)")
    p.add_argument("name", help="Profile name")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("--ports", required=True, help="Port range (e.g. Gi1/0/1-24)")
    p.set_defaults(func=_cmd_profile_apply)

    p = prof_sub.add_parser("create", help="Create a new profile")
    p.add_argument("name", help="Profile name")
    p.add_argument("--description", help="Profile description")
    p.add_argument("--mode", choices=["access", "trunk"], help="Port mode")
    p.add_argument("--vlan", help="VLAN ID")
    p.add_argument("--shutdown", action="store_true", help="Shutdown port")
    p.set_defaults(func=_cmd_profile_create)

    p = prof_sub.add_parser("delete", help="Delete a profile")
    p.add_argument("name", help="Profile name")
    p.set_defaults(func=_cmd_profile_delete)

    prof.set_defaults(func=_cmd_profile_list)

    # Default: freq net switch (no action) -> show
    sw.set_defaults(func=_cmd_switch_show)

    # freq net port <action> — port management
    port = net_sub.add_parser("port", help="Switch port management")
    port_sub = port.add_subparsers(dest="action")

    p = port_sub.add_parser("status", help="Per-port status with PoE info")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.set_defaults(func=_cmd_port_status)

    p = port_sub.add_parser("configure", help="Configure a port")
    p.add_argument("target", help="Switch IP or label")
    p.add_argument("port", help="Port name (e.g. Gi1/0/5)")
    p.add_argument("--vlan", help="Set VLAN ID")
    p.add_argument("--mode", choices=["access", "trunk"], help="Port mode")
    p.add_argument("--shutdown", action="store_true", help="Shutdown port")
    p.add_argument("--no-shutdown", action="store_true", help="Enable port")
    p.set_defaults(func=_cmd_port_configure)

    p = port_sub.add_parser("desc", help="Set port description")
    p.add_argument("target", help="Switch IP or label")
    p.add_argument("port", help="Port name (e.g. Gi1/0/5)")
    p.add_argument("--description", required=True, help="Description text")
    p.set_defaults(func=_cmd_port_desc)

    p = port_sub.add_parser("poe", help="PoE status or toggle")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("--port", help="Port name for toggle")
    p.add_argument("--on", action="store_true", help="Enable PoE")
    p.add_argument("--off", action="store_true", help="Disable PoE")
    p.set_defaults(func=_cmd_port_poe)

    p = port_sub.add_parser("find", help="Find which port a MAC is on")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("--mac", required=True, help="MAC address to find")
    p.set_defaults(func=_cmd_port_find)

    p = port_sub.add_parser("flap", help="Bounce a port (shut/no shut)")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("--port", required=True, help="Port name (e.g. Gi1/0/5)")
    p.set_defaults(func=_cmd_port_flap)

    port.set_defaults(func=_cmd_port_status)

    # freq net config <action> — device configuration management
    ncfg = net_sub.add_parser("config", help="Device config backup, diff, and restore")
    ncfg_sub = ncfg.add_subparsers(dest="action")

    p = ncfg_sub.add_parser("backup", help="Pull and store running-config")
    p.add_argument("target", nargs="?", help="Switch IP or label")
    p.add_argument("--all", action="store_true", help="Backup all switches")
    p.set_defaults(func=_cmd_config_backup)

    p = ncfg_sub.add_parser("history", help="Config backup history")
    p.add_argument("target", nargs="?", help="Device label (omit for all)")
    p.set_defaults(func=_cmd_config_history)

    p = ncfg_sub.add_parser("diff", help="Diff running config vs last backup")
    p.add_argument("target", help="Switch IP or label")
    p.add_argument("--version", type=int, help="Compare against version N")
    p.set_defaults(func=_cmd_config_diff)

    p = ncfg_sub.add_parser("search", help="Search across all stored configs")
    p.add_argument("pattern", help="Search pattern (regex)")
    p.set_defaults(func=_cmd_config_search)

    p = ncfg_sub.add_parser("restore", help="Restore a previous config version")
    p.add_argument("target", help="Switch IP or label")
    p.add_argument("--version", type=int, help="Version number to restore")
    p.set_defaults(func=_cmd_config_restore)

    ncfg.set_defaults(func=_cmd_config_history)

    # freq net snmp <action> — SNMP polling
    snmp = net_sub.add_parser("snmp", help="SNMP device polling")
    snmp_sub = snmp.add_subparsers(dest="action")

    p = snmp_sub.add_parser("poll", help="Full SNMP poll (system, interfaces, CPU)")
    p.add_argument("target", nargs="?", help="Device IP or label")
    p.add_argument("--all", action="store_true", help="Poll all switches")
    p.add_argument("--community", help="SNMP community string")
    p.set_defaults(func=_cmd_snmp_poll)

    p = snmp_sub.add_parser("interfaces", help="SNMP interface table with counters")
    p.add_argument("target", help="Device IP or label")
    p.add_argument("--community", help="SNMP community string")
    p.set_defaults(func=_cmd_snmp_interfaces)

    p = snmp_sub.add_parser("errors", help="Interfaces with errors")
    p.add_argument("target", help="Device IP or label")
    p.add_argument("--community", help="SNMP community string")
    p.set_defaults(func=_cmd_snmp_errors)

    p = snmp_sub.add_parser("cpu", help="CPU utilization via SNMP")
    p.add_argument("target", help="Device IP or label")
    p.add_argument("--community", help="SNMP community string")
    p.set_defaults(func=_cmd_snmp_cpu)

    snmp.set_defaults(func=_cmd_snmp_poll)

    # freq net topology <action> — LLDP/CDP topology
    topo = net_sub.add_parser("topology", help="Network topology via LLDP/CDP")
    topo_sub = topo.add_subparsers(dest="action")

    p = topo_sub.add_parser("discover", help="Crawl switches for neighbors")
    p.set_defaults(func=_cmd_topology_discover)

    p = topo_sub.add_parser("show", help="Show latest topology")
    p.set_defaults(func=_cmd_topology_show)

    p = topo_sub.add_parser("export", help="Export as DOT or JSON")
    p.add_argument("--format", default="dot", choices=["dot", "json"], help="Export format")
    p.add_argument("--output", "-o", help="Output file path")
    p.set_defaults(func=_cmd_topology_export)

    p = topo_sub.add_parser("diff", help="Compare against previous snapshot")
    p.set_defaults(func=_cmd_topology_diff)

    topo.set_defaults(func=_cmd_topology_show)

    # freq net find-mac / find-ip / troubleshoot
    p = net_sub.add_parser("find-mac", help="Find MAC across all switches")
    p.add_argument("mac", help="MAC address to find")
    p.set_defaults(func=_cmd_find_mac)

    p = net_sub.add_parser("find-ip", help="Find IP in ARP tables across switches")
    p.add_argument("ip", help="IP address to find")
    p.set_defaults(func=_cmd_find_ip)

    p = net_sub.add_parser("troubleshoot", help="Automated network troubleshooting")
    p.add_argument("target", help="IP, MAC, or hostname to trace")
    p.set_defaults(func=_cmd_troubleshoot)

    # freq net ip-util / ip-conflict
    p = net_sub.add_parser("ip-util", help="Subnet utilization per VLAN")
    p.set_defaults(func=_cmd_ip_utilization)

    p = net_sub.add_parser("ip-conflict", help="Detect duplicate IP addresses")
    p.set_defaults(func=_cmd_ip_conflict)

    p = net_sub.add_parser("netmon", help="Network monitoring and interface tracking")
    p.add_argument(
        "action",
        nargs="?",
        choices=["interfaces", "poll", "bandwidth", "topology"],
        default="interfaces",
        help="Action to perform",
    )
    p.set_defaults(func=_cmd_netmon)

    p = net_sub.add_parser("map", help="Dependency discovery and impact analysis")
    p.add_argument(
        "action",
        nargs="?",
        choices=["discover", "show", "impact", "export"],
        default="discover",
        help="Action to perform",
    )
    p.add_argument("target", nargs="?", help="Host label (for impact)")
    p.add_argument("--format", default="json", choices=["json", "dot"], help="Export format")
    p.set_defaults(func=_cmd_map)

    p = net_sub.add_parser("ip", help="IP address management (next/list/check)")
    p.add_argument(
        "action",
        nargs="?",
        choices=["next", "list", "check"],
        default="next",
        help="Action: next (default), list, check",
    )
    p.add_argument("target", nargs="?", help="IP address (for check)")
    p.add_argument("--vlan", help="VLAN name to search")
    p.add_argument("--count", type=int, default=1, help="Number of IPs to find (for next)")
    p.set_defaults(func=_cmd_ip)


# ---------------------------------------------------------------------------
# freq fw — Firewall & Gateway
# ---------------------------------------------------------------------------


def _register_fw(sub):
    """Register freq fw subcommands."""
    fw = sub.add_parser("fw", help="Firewall management (pfSense/OPNsense)")
    _domain_help(fw)
    fw_sub = fw.add_subparsers(dest="subcmd")

    p = fw_sub.add_parser("status", help="Firewall system status")
    p.set_defaults(func=_cmd_fw_status)

    p = fw_sub.add_parser("rules", help="List, export, or audit firewall rules")
    p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "export", "audit"],
        help="Action: list (default), export, audit",
    )
    p.set_defaults(func=_cmd_fw_rules)

    p = fw_sub.add_parser("nat", help="NAT/port forward rules")
    p.set_defaults(func=_cmd_fw_nat)

    p = fw_sub.add_parser("states", help="Active connection states")
    p.add_argument("--limit", type=int, default=20, help="Number of states to show")
    p.set_defaults(func=_cmd_fw_states)

    p = fw_sub.add_parser("interfaces", help="Firewall network interfaces")
    p.set_defaults(func=_cmd_fw_interfaces)

    p = fw_sub.add_parser("gateways", help="Gateway status and routing")
    p.set_defaults(func=_cmd_fw_gateways)

    p = fw_sub.add_parser("dhcp", help="DHCP lease management")
    p.add_argument("action", nargs="?", default="leases", help="Action: leases")
    p.set_defaults(func=_cmd_fw_dhcp)

    fw.set_defaults(func=_cmd_fw_status)


# ---------------------------------------------------------------------------
# freq cert — Certificate & PKI
# ---------------------------------------------------------------------------


def _register_cert(sub):
    """Register freq cert subcommands."""
    cert = sub.add_parser("cert", help="TLS certificate inventory and monitoring")
    _domain_help(cert)
    cert_sub = cert.add_subparsers(dest="subcmd")

    p = cert_sub.add_parser("scan", help="Scan fleet for TLS certificates")
    p.set_defaults(func=_cmd_cert)

    p = cert_sub.add_parser("list", help="List certificate inventory")
    p.set_defaults(func=_cmd_cert)

    p = cert_sub.add_parser("check", help="Check a single endpoint")
    p.add_argument("target", nargs="?", help="Host:port")
    p.set_defaults(func=_cmd_cert)

    p = cert_sub.add_parser("inspect", help="Inspect TLS certificate details")
    p.add_argument("target", help="Host:port to inspect")
    p.set_defaults(func=_cmd_cert_inspect)

    p = cert_sub.add_parser("fleet-check", help="Check certs across all fleet hosts")
    p.set_defaults(func=_cmd_cert_fleet_check)

    p = cert_sub.add_parser("acme", help="ACME (Let's Encrypt) status")
    p.set_defaults(func=_cmd_cert_acme_status)

    p = cert_sub.add_parser("issued", help="List tracked issued certificates")
    p.set_defaults(func=_cmd_cert_issued_list)

    cert.set_defaults(func=_cmd_cert)


# ---------------------------------------------------------------------------
# freq dns — DNS Management
# ---------------------------------------------------------------------------


def _register_dns(sub):
    """Register freq dns subcommands."""
    dns = sub.add_parser("dns", help="DNS record tracking and validation")
    _domain_help(dns)
    dns_sub = dns.add_subparsers(dest="subcmd")

    p = dns_sub.add_parser("scan", help="Fleet-wide DNS validation")
    p.set_defaults(func=_cmd_dns)

    p = dns_sub.add_parser("check", help="Check a single host's DNS")
    p.add_argument("target", nargs="?", help="Hostname or IP")
    p.set_defaults(func=_cmd_dns)

    p = dns_sub.add_parser("list", help="DNS inventory")
    p.set_defaults(func=_cmd_dns)

    # Internal DNS management
    int_dns = dns_sub.add_parser("internal", help="Internal DNS record management")
    int_sub = int_dns.add_subparsers(dest="action")

    p = int_sub.add_parser("list", help="List internal DNS records")
    p.set_defaults(func=_cmd_dns_internal_list)

    p = int_sub.add_parser("add", help="Add a DNS record")
    p.add_argument("hostname", help="Hostname")
    p.add_argument("ip", help="IP address")
    p.set_defaults(func=_cmd_dns_internal_add)

    p = int_sub.add_parser("remove", help="Remove a DNS record")
    p.add_argument("hostname", help="Hostname to remove")
    p.set_defaults(func=_cmd_dns_internal_remove)

    p = int_sub.add_parser("sync", help="Sync DNS from hosts.conf")
    p.set_defaults(func=_cmd_dns_internal_sync)

    p = int_sub.add_parser("audit", help="Audit DNS resolution")
    p.set_defaults(func=_cmd_dns_internal_audit)

    int_dns.set_defaults(func=_cmd_dns_internal_list)

    dns.set_defaults(func=_cmd_dns)


# ---------------------------------------------------------------------------
# freq proxy — Reverse Proxy
# ---------------------------------------------------------------------------


def _register_proxy(sub):
    """Register freq proxy subcommands."""
    proxy = sub.add_parser("proxy", help="Reverse proxy management")
    _domain_help(proxy)
    proxy_sub = proxy.add_subparsers(dest="subcmd")

    p = proxy_sub.add_parser("status", help="Detect and show proxy status")
    p.set_defaults(func=_cmd_proxy_status)

    p = proxy_sub.add_parser("hosts", help="List proxy hosts from backend")
    p.set_defaults(func=_cmd_proxy_hosts)

    p = proxy_sub.add_parser("health", help="Health check proxy backends")
    p.set_defaults(func=_cmd_proxy_health)

    # Legacy commands
    p = proxy_sub.add_parser("list", help="List managed routes")
    p.set_defaults(func=_cmd_proxy)

    p = proxy_sub.add_parser("add", help="Add a proxy route")
    p.add_argument("--domain", help="Domain name")
    p.add_argument("--upstream", help="Upstream target (host:port)")
    p.set_defaults(func=_cmd_proxy)

    p = proxy_sub.add_parser("remove", help="Remove a proxy route")
    p.add_argument("--domain", help="Domain to remove")
    p.set_defaults(func=_cmd_proxy)

    proxy.set_defaults(func=_cmd_proxy_status)


# ---------------------------------------------------------------------------
# freq media — Media Stack
# ---------------------------------------------------------------------------


def _register_media(sub):
    """Register freq media subcommands."""
    media = sub.add_parser("media", help="Media stack management (Plex/Sonarr/Radarr/Tdarr)")
    media.add_argument(
        "action",
        nargs="?",
        help="Subcommand (status/restart/stop/start/logs/stats/"
        "update/prune/backup/restore/health/doctor/queue/streams/vpn/disk/"
        "missing/search/scan/activity/wanted/indexers/downloads/"
        "transcode/subtitles/requests/nuke/export/dashboard/report/"
        "compose/mounts/cleanup/gpu)",
    )
    media.add_argument("service", nargs="?", help="Service name or sub-action")
    media.add_argument("--check", action="store_true", help="Check mode (for update)")
    media.add_argument("--list", action="store_true", help="List mode (for backup)")
    media.add_argument("--lines", "-n", type=int, default=50, help="Number of log lines")
    media.add_argument("--errors", action="store_true", help="Show only errors/warnings (for logs)")
    media.add_argument("--since", help="Show logs since duration (e.g., 1h, 30m, 2d)")
    media.set_defaults(func=_cmd_media)


# ---------------------------------------------------------------------------
# freq user — User Management
# ---------------------------------------------------------------------------


def _register_user(sub):
    """Register freq user subcommands."""
    user = sub.add_parser("user", help="User accounts, roles, and RBAC")
    _domain_help(user)
    user_sub = user.add_subparsers(dest="subcmd")

    p = user_sub.add_parser("list", help="List users")
    p.set_defaults(func=_cmd_users)

    p = user_sub.add_parser("create", help="Create a new user")
    p.add_argument("username", nargs="?", help="Username")
    p.add_argument("--role", choices=["viewer", "operator", "admin"], help="Initial role")
    p.set_defaults(func=_cmd_new_user)

    p = user_sub.add_parser("passwd", help="Change user password")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_passwd)

    p = user_sub.add_parser("roles", help="View role assignments")
    p.set_defaults(func=_cmd_roles)

    p = user_sub.add_parser("promote", help="Promote user to higher role")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_promote)

    p = user_sub.add_parser("demote", help="Demote user to lower role")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_demote)

    p = user_sub.add_parser("install", help="Install user across fleet")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_install_user)


# ---------------------------------------------------------------------------
# freq vpn — VPN Management
# ---------------------------------------------------------------------------


def _register_vpn(sub):
    """Register freq vpn subcommands."""
    vpn = sub.add_parser("vpn", help="VPN tunnel management (WireGuard/OpenVPN)")
    _domain_help(vpn)
    vpn_sub = vpn.add_subparsers(dest="subcmd")

    # WireGuard
    wg = vpn_sub.add_parser("wg", help="WireGuard management")
    wg_sub = wg.add_subparsers(dest="action")

    p = wg_sub.add_parser("status", help="WireGuard tunnel status")
    p.set_defaults(func=_cmd_vpn_wg_status)

    p = wg_sub.add_parser("peers", help="List peers with details")
    p.set_defaults(func=_cmd_vpn_wg_peers)

    p = wg_sub.add_parser("audit", help="Find stale/inactive peers")
    p.set_defaults(func=_cmd_vpn_wg_audit)

    wg.set_defaults(func=_cmd_vpn_wg_status)

    # OpenVPN
    ovpn = vpn_sub.add_parser("ovpn", help="OpenVPN management")
    ovpn_sub = ovpn.add_subparsers(dest="action")

    p = ovpn_sub.add_parser("status", help="OpenVPN server status")
    p.set_defaults(func=_cmd_vpn_ovpn_status)

    ovpn.set_defaults(func=_cmd_vpn_ovpn_status)

    vpn.set_defaults(func=_cmd_vpn_wg_status)


# ---------------------------------------------------------------------------
# freq event — Event Network Lifecycle
# ---------------------------------------------------------------------------


def _register_event(sub):
    """Register freq event subcommands."""
    ev = sub.add_parser("event", help="Event network lifecycle management")
    _domain_help(ev)
    ev_sub = ev.add_subparsers(dest="subcmd")

    p = ev_sub.add_parser("create", help="Create a new event project")
    p.add_argument("name", help="Event name")
    p.set_defaults(func=_cmd_event_create)

    p = ev_sub.add_parser("list", help="List all events")
    p.set_defaults(func=_cmd_event_list)

    p = ev_sub.add_parser("show", help="Show event details")
    p.add_argument("name", help="Event name")
    p.set_defaults(func=_cmd_event_show)

    p = ev_sub.add_parser("plan", help="Generate IP plan and VLAN allocation")
    p.add_argument("name", help="Event name")
    p.set_defaults(func=_cmd_event_plan)

    p = ev_sub.add_parser("deploy", help="Push configs to all event switches")
    p.add_argument("name", help="Event name")
    p.set_defaults(func=_cmd_event_deploy)

    p = ev_sub.add_parser("verify", help="Verify deployed event matches template")
    p.add_argument("name", help="Event name")
    p.set_defaults(func=_cmd_event_verify)

    p = ev_sub.add_parser("wipe", help="Reset switches to clean state")
    p.add_argument("name", help="Event name")
    p.add_argument("--confirm", action="store_true", help="Required — confirms destructive wipe")
    p.set_defaults(func=_cmd_event_wipe)

    p = ev_sub.add_parser("archive", help="Archive event configs and remove template")
    p.add_argument("name", help="Event name")
    p.set_defaults(func=_cmd_event_archive)

    p = ev_sub.add_parser("delete", help="Delete event template")
    p.add_argument("name", help="Event name")
    p.add_argument("--yes", "-y", action="store_true", help="Required — confirms deletion")
    p.set_defaults(func=_cmd_event_delete)

    ev.set_defaults(func=_cmd_event_list)


# ---------------------------------------------------------------------------
# freq plugin — Plugin Ecosystem
# ---------------------------------------------------------------------------


def _register_plugin(sub):
    """Register freq plugin subcommands."""
    pl = sub.add_parser("plugin", help="Plugin management (install, create, remove)")
    _domain_help(pl)
    pl_sub = pl.add_subparsers(dest="subcmd")

    p = pl_sub.add_parser("list", help="List installed plugins")
    p.set_defaults(func=_cmd_plugin_list)

    p = pl_sub.add_parser("info", help="Show plugin details")
    p.add_argument("name", help="Plugin name")
    p.set_defaults(func=_cmd_plugin_info)

    p = pl_sub.add_parser("install", help="Install a plugin from URL or path")
    p.add_argument("source", help="URL or local path to plugin file")
    p.set_defaults(func=_cmd_plugin_install)

    p = pl_sub.add_parser("remove", help="Remove an installed plugin")
    p.add_argument("name", help="Plugin name")
    p.set_defaults(func=_cmd_plugin_remove)

    p = pl_sub.add_parser("create", help="Scaffold a new plugin from template")
    p.add_argument("--name", required=True, help="Plugin name")
    p.add_argument(
        "--type", dest="type", default="command", help="Plugin type (command, deployer, notification, policy, etc.)"
    )
    p.add_argument("--description", help="Short description")
    p.add_argument("--category", help="Deployer category (for deployer type)")
    p.set_defaults(func=_cmd_plugin_create)

    p = pl_sub.add_parser("search", help="Search community plugin index")
    p.add_argument("query", nargs="?", default="", help="Search query")
    p.set_defaults(func=_cmd_plugin_search)

    p = pl_sub.add_parser("update", help="Update plugins from original source")
    p.add_argument("name", nargs="?", help="Plugin name (or all if omitted)")
    p.set_defaults(func=_cmd_plugin_update)

    p = pl_sub.add_parser("types", help="List available plugin types")
    p.set_defaults(func=_cmd_plugin_types)

    pl.set_defaults(func=_cmd_plugin_list)


# ---------------------------------------------------------------------------
# freq config — Configuration Management
# ---------------------------------------------------------------------------


def _register_config(sub):
    """Register freq config subcommands."""
    cfg_parser = sub.add_parser("config", help="Configuration management and validation")
    _domain_help(cfg_parser)
    cfg_sub = cfg_parser.add_subparsers(dest="subcmd")

    p = cfg_sub.add_parser("validate", help="Validate FREQ configuration")
    p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    p.set_defaults(func=_cmd_config_validate)

    cfg_parser.set_defaults(func=lambda c, pk, a: cfg_parser.print_help() or 0)


# ---------------------------------------------------------------------------
# Help command — domain-based reference
# ---------------------------------------------------------------------------


def cmd_help(cfg: FreqConfig, pack, args) -> int:
    """Show all commands organized by domain."""
    fmt.header("Command Reference — freq <domain> <action>")
    fmt.blank()

    categories = [
        (
            "Utilities (top-level)",
            [
                ("version", "Show version and branding"),
                ("help", "This command reference"),
                ("doctor", "Self-diagnostic"),
                ("menu", "Interactive TUI menu"),
                ("demo", "Interactive demo (no fleet required)"),
                ("init", "First-run setup wizard"),
                ("configure", "Reconfigure settings"),
                ("serve", "Start web dashboard"),
                ("update", "Check for updates"),
                ("learn <query>", "Search operational knowledge"),
                ("docs [generate|verify|runbook]", "Auto-generated docs"),
                ("distros", "List cloud images"),
                ("notify <message>", "Send notification"),
                ("agent <action>", "AI specialist management"),
            ],
        ),
        (
            "freq vm — Virtual Machine Lifecycle",
            [
                ("vm list [--node] [--status]", "List VMs across cluster"),
                ("vm create [--name --image ...]", "Create a new VM"),
                ("vm clone <source> [--name]", "Clone an existing VM"),
                ("vm destroy <target>", "Destroy a VM"),
                ("vm resize <target> [--cores --ram]", "Resize a VM"),
                ("vm power <start/stop/reboot> <vmid>", "Power control"),
                ("vm snapshot [create|list|delete]", "Snapshot management"),
                ("vm rollback <vmid>", "Roll back to snapshot"),
                ("vm nic <action> <vmid>", "NIC management"),
                ("vm migrate <target> --node", "Migrate between nodes"),
                ("vm import --image", "Import cloud image"),
                ("vm template <vmid>", "Convert to template"),
                ("vm rename <vmid> --name", "Rename a VM"),
                ("vm disk <vmid> --size", "Add disk(s)"),
                ("vm tag <vmid> [tags]", "PVE tags"),
                ("vm pool [list|create|add]", "Pool management"),
                ("vm sandbox <template>", "Spawn from template"),
                ("vm overview", "VM inventory across cluster"),
                ("vm config <target>", "View/edit VM configuration"),
                ("vm rescue <target>", "Rescue a stuck VM"),
                ("vm why <vmid>", "Explain protections"),
                ("vm provision", "Cloud-init provisioning"),
                ("vm file send <src> <host:dst>", "SCP file to host"),
            ],
        ),
        (
            "freq fleet — Fleet Operations",
            [
                ("fleet status", "Fleet health summary"),
                ("fleet dashboard", "Dashboard overview"),
                ("fleet exec <target> <cmd>", "Run command across fleet"),
                ("fleet info <host>", "System info"),
                ("fleet detail <host>", "Deep host inventory"),
                ("fleet diagnose <host>", "Deep diagnostic"),
                ("fleet ssh <host>", "SSH to host"),
                ("fleet docker <host>", "Container discovery"),
                ("fleet log <host>", "View host logs"),
                ("fleet compare <a> <b>", "Side-by-side compare"),
                ("fleet health", "Comprehensive health"),
                ("fleet report [--markdown]", "Fleet health report"),
                ("fleet ntp [check|fix]", "NTP management"),
                ("fleet update [check|apply]", "OS updates"),
                ("fleet comms [setup|send|check]", "Inter-VM mailbox"),
                ("fleet inventory [hosts|vms|containers]", "CMDB export"),
                ("fleet federation [list|register|poll]", "Multi-site"),
                ("fleet test <host>", "Test connectivity"),
            ],
        ),
        (
            "freq host — Host Registry",
            [
                ("host list", "List fleet hosts"),
                ("host add", "Add a host"),
                ("host remove", "Remove a host"),
                ("host discover", "Discover on network"),
                ("host groups [list|add|remove]", "Manage groups"),
                ("host bootstrap <host>", "Bootstrap new host"),
                ("host onboard <host>", "Onboard to fleet"),
                ("host keys [deploy|list|rotate]", "SSH key management"),
            ],
        ),
        (
            "freq docker — Container Management",
            [
                ("docker containers <host>", "Container discovery"),
                ("docker fleet [ps|logs|stats]", "Fleet-wide operations"),
                ("docker stack [status|update|health]", "Compose stacks"),
                ("docker monitor", "HTTP endpoint checks"),
            ],
        ),
        (
            "freq secure — Security & Compliance",
            [
                ("secure vault <action> [key]", "Encrypted credential store"),
                ("secure audit [--fix]", "Security audit"),
                ("secure harden <target>", "Apply hardening"),
                ("secure comply [scan|report]", "CIS/STIG compliance"),
                ("secure patch [status|check|apply]", "Patch management"),
                ("secure secrets [scan|audit|generate]", "Secret lifecycle"),
                ("secure sweep [--fix]", "Full audit pipeline"),
            ],
        ),
        (
            "freq observe — Observability",
            [
                ("observe alert [list|create|check|test]", "Alert management"),
                ("observe logs [tail|search|stats]", "Fleet log aggregation"),
                ("observe trend [show|snapshot]", "Capacity trends"),
                ("observe capacity [show|snapshot]", "Capacity projections"),
                ("observe sla [show|check]", "Uptime SLA tracking"),
                ("observe watch", "Monitoring daemon"),
                ("observe db [status|health|size]", "Database health"),
            ],
        ),
        (
            "freq state — Desired State",
            [
                ("state baseline [capture|compare|list]", "Config baselines"),
                ("state plan [--file]", "Fleet plan diff"),
                ("state apply [--file]", "Apply fleet plan"),
                ("state check <policy>", "Check compliance"),
                ("state fix <policy>", "Apply remediation"),
                ("state diff <policy>", "Show drift"),
                ("state policies", "List policies"),
                ("state gitops [status|sync|diff]", "GitOps config sync"),
            ],
        ),
        (
            "freq auto — Automation",
            [
                ("auto rules [list|create|delete]", "Alert rules"),
                ("auto schedule [list|create|run]", "Job scheduler"),
                ("auto playbook [list|run]", "Incident playbooks"),
                ("auto webhook [list|create|test]", "Inbound webhooks"),
                ("auto chaos [list|run|log]", "Chaos engineering"),
                ("auto patrol [--interval N]", "Continuous monitoring"),
            ],
        ),
        (
            "freq ops — Operations",
            [
                ("ops oncall [whoami|schedule|alert|ack]", "On-call rotation"),
                ("ops risk <target>", "Blast radius analysis"),
            ],
        ),
        (
            "freq hw — Hardware & Cost",
            [
                ("hw idrac <action>", "Dell iDRAC management"),
                ("hw cost", "Power cost estimates"),
                ("hw cost-analysis [waste|density|compare]", "FinOps analysis"),
                ("hw gwipe [status|bays|wipe]", "Drive sanitization"),
            ],
        ),
        (
            "freq store — Storage",
            [
                ("store nas <action>", "TrueNAS management"),
            ],
        ),
        (
            "freq dr — Disaster Recovery",
            [
                ("dr backup [list|create|export|prune]", "Backup management"),
                ("dr policy [list|create|apply]", "Backup policies"),
                ("dr journal [--lines N]", "Operation history"),
                ("dr migrate-plan", "Migration recommendations"),
                ("dr migrate-vmware [scan|import]", "VMware migration"),
            ],
        ),
        (
            "freq net — Network",
            [
                ("net switch <action>", "Switch management"),
                ("net netmon [interfaces|poll|bandwidth]", "Network monitoring"),
                ("net map [discover|impact|export]", "Dependency mapping"),
                ("net ip [next|list|check]", "IPAM"),
            ],
        ),
        (
            "Standalone Domains",
            [
                ("fw <action>", "Firewall (pfSense/OPNsense)"),
                ("cert [scan|list|check]", "TLS certificates"),
                ("dns [scan|check|list]", "DNS validation"),
                ("proxy [status|list|add|remove]", "Reverse proxy"),
                ("media <action> [service]", "Media stack (40+ subcommands)"),
            ],
        ),
        (
            "freq user — User Management",
            [
                ("user list", "List users"),
                ("user create <username>", "Create user"),
                ("user passwd <username>", "Change password"),
                ("user roles", "View role assignments"),
                ("user promote <username>", "Promote to higher role"),
                ("user demote <username>", "Demote to lower role"),
                ("user install <username>", "Install across fleet"),
            ],
        ),
        (
            "freq vpn — VPN Management",
            [
                ("vpn list", "List VPN peers"),
                ("vpn add <name>", "Add VPN peer"),
                ("vpn remove <name>", "Remove VPN peer"),
            ],
        ),
        (
            "freq event — Event Network",
            [
                ("event list", "List event networks"),
                ("event create <name>", "Create event network"),
                ("event remove <name>", "Remove event network"),
            ],
        ),
        (
            "freq specialist — Specialist Ops",
            [
                ("specialist <action>", "Specialist operations"),
            ],
        ),
        (
            "freq lab — Lab Management",
            [
                ("lab list", "List lab environments"),
                ("lab tool <action>", "Lab tool management"),
            ],
        ),
        (
            "freq engine — Policy Engine",
            [
                ("engine run", "Run policy checks"),
                ("engine list", "List available policies"),
            ],
        ),
        (
            "freq plugin — Plugin Ecosystem",
            [
                ("plugin list", "List installed plugins"),
                ("plugin info <name>", "Show plugin details"),
                ("plugin install <url-or-path>", "Install a plugin"),
                ("plugin remove <name>", "Remove a plugin"),
                ("plugin create --name <n> --type <t>", "Scaffold new plugin"),
                ("plugin search [query]", "Search community index"),
                ("plugin update [name]", "Update from source"),
                ("plugin types", "List plugin types"),
            ],
        ),
        (
            "freq config — Configuration Management",
            [
                ("config validate", "Validate configuration"),
                ("config validate --json", "Validate (JSON output)"),
            ],
        ),
    ]

    for category, commands in categories:
        fmt.line(f"{fmt.C.PURPLE_BOLD}{category}{fmt.C.RESET}")
        for cmd_name, desc in commands:
            fmt.line(f"  {fmt.C.CYAN}freq {cmd_name:<40}{fmt.C.RESET} {desc}")
        fmt.blank()

    fmt.footer()
    return 0


# ---------------------------------------------------------------------------
# Built-in commands (no lazy loading needed)
# ---------------------------------------------------------------------------


def cmd_version(cfg: FreqConfig, pack, args) -> int:
    """Show version with branding."""
    from freq.core.personality import splash

    splash(pack, cfg.version)
    return 0


def cmd_doctor(cfg: FreqConfig, pack, args) -> int:
    """Run self-diagnostic."""
    from freq.core.doctor import run, show_history

    if getattr(args, "history", False):
        return show_history(cfg)
    return run(cfg, json_output=getattr(args, "json_output", False))


def cmd_perf(cfg: FreqConfig, pack, args) -> int:
    """Show performance metrics."""
    import json as _json

    entries = logger.read_perf(last=getattr(args, "last", 100))

    if getattr(args, "json_output", False):
        print(_json.dumps(entries, indent=2))
        return 0

    if not entries:
        fmt.line("No performance data. Run freq commands to generate timing data.")
        return 0

    fmt.header("Performance Metrics")
    fmt.blank()

    # Group SSH timings by host
    ssh_by_host = {}
    for e in entries:
        if e.get("op") in ("ssh", "ssh_async"):
            host = e.get("host", "?")
            ssh_by_host.setdefault(host, []).append(e.get("duration", 0))

    if ssh_by_host:
        fmt.line(f"  {fmt.C.BOLD}SSH Timing (last {len(entries)} ops){fmt.C.RESET}")
        fmt.blank()
        fmt.line(f"  {'Host':<22} {'Count':>6} {'Avg':>8} {'p95':>8} {'Max':>8}")
        fmt.line(f"  {'─'*22} {'─'*6} {'─'*8} {'─'*8} {'─'*8}")

        for host in sorted(ssh_by_host, key=lambda h: sum(ssh_by_host[h]) / len(ssh_by_host[h]), reverse=True):
            times = sorted(ssh_by_host[host])
            count = len(times)
            avg = sum(times) / count
            p95 = times[int(count * 0.95)] if count > 1 else times[0]
            mx = times[-1]
            fmt.line(f"  {host:<22} {count:>6} {avg:>7.2f}s {p95:>7.2f}s {mx:>7.2f}s")

    # Phase timings
    phases = [e for e in entries if e.get("op") == "init_phase"]
    if phases:
        fmt.blank()
        fmt.line(f"  {fmt.C.BOLD}Init Phase Timing{fmt.C.RESET}")
        fmt.blank()
        for p in phases:
            name = p.get("name", "?")
            dur = p.get("duration", 0)
            fmt.line(f"  Phase {p.get('phase', '?'):>2}: {name:<30} {dur:.1f}s")

    fmt.blank()
    fmt.line(f"  {len(entries)} total entries")
    fmt.blank()
    return 0


def cmd_audit_log(cfg: FreqConfig, pack, args) -> int:
    """Show infrastructure audit trail."""
    import json as _json
    from freq.core import audit

    host = getattr(args, "host", "") or ""
    action = getattr(args, "filter_action", "") or ""
    last = getattr(args, "last", 20)

    entries = audit.read_log(host=host, action=action, last=last)

    if getattr(args, "json_output", False):
        print(_json.dumps(entries, indent=2))
        return 0

    if not entries:
        fmt.line("No audit entries found. Infrastructure changes are recorded here.")
        return 0

    fmt.header("Audit Trail")
    fmt.blank()

    for e in entries:
        ts = e.get("ts", "?")[:19].replace("T", " ")
        act = e.get("action", "?")
        target = e.get("target", "?")
        result = e.get("result", "?")

        if result == "success":
            color = fmt.C.GREEN
        elif result == "failed":
            color = fmt.C.RED
        elif result == "dry_run":
            color = fmt.C.YELLOW
        else:
            color = fmt.C.DIM

        fmt.line(f"  {ts}  {color}{result:<8}{fmt.C.RESET}  {act:<20}  {target}")

        # Show extra details
        skip = {"ts", "action", "target", "result"}
        extras = {k: v for k, v in e.items() if k not in skip}
        if extras:
            fmt.line(f"  {'':>19}  {fmt.C.DIM}{extras}{fmt.C.RESET}")

    fmt.blank()
    fmt.line(f"  {len(entries)} entries shown")
    fmt.blank()
    return 0


def cmd_menu(cfg: FreqConfig, pack, args) -> int:
    """Launch interactive TUI menu."""
    from freq.tui.menu import run as tui_run

    return tui_run(cfg, pack)


# ---------------------------------------------------------------------------
# Command wrappers — lazy module loading
# ---------------------------------------------------------------------------


def _cmd_demo(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.demo import run

    return run(cfg, pack, args)


def _cmd_why(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.why import cmd_why

    return cmd_why(cfg, pack, args)


def _cmd_test_connection(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_test_connection

    return cmd_test_connection(cfg, pack, args)


def _cmd_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_status

    return cmd_status(cfg, pack, args)


def _cmd_dashboard(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_dashboard

    return cmd_dashboard(cfg, pack, args)


def _cmd_exec(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_exec

    return cmd_exec(cfg, pack, args)


def _cmd_info(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_info

    return cmd_info(cfg, pack, args)


def _cmd_detail(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_detail

    return cmd_detail(cfg, pack, args)


def _cmd_boundaries(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_boundaries

    return cmd_boundaries(cfg, pack, args)


def _cmd_diagnose(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_diagnose

    return cmd_diagnose(cfg, pack, args)


def _cmd_ssh(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_ssh_host

    return cmd_ssh_host(cfg, pack, args)


def _cmd_docker(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_docker

    return cmd_docker(cfg, pack, args)


def _cmd_log(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_log

    return cmd_log(cfg, pack, args)


def _cmd_keys(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_keys

    return cmd_keys(cfg, pack, args)


def _cmd_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.pve import cmd_list

    return cmd_list(cfg, pack, args)


def _cmd_vm_overview(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.pve import cmd_vm_overview

    return cmd_vm_overview(cfg, pack, args)


def _cmd_vmconfig(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.pve import cmd_vmconfig

    return cmd_vmconfig(cfg, pack, args)


def _cmd_snapshot(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.pve import cmd_snapshot

    return cmd_snapshot(cfg, pack, args)


def _cmd_power(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.pve import cmd_power

    return cmd_power(cfg, pack, args)


def _cmd_nic(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_nic

    return cmd_nic(cfg, pack, args)


def _cmd_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_create

    return cmd_create(cfg, pack, args)


def _cmd_clone(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_clone

    return cmd_clone(cfg, pack, args)


def _cmd_destroy(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_destroy

    return cmd_destroy(cfg, pack, args)


def _cmd_resize(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_resize

    return cmd_resize(cfg, pack, args)


def _cmd_migrate(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_migrate

    return cmd_migrate(cfg, pack, args)


def _cmd_template(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_template

    return cmd_template(cfg, pack, args)


def _cmd_rename(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_rename

    return cmd_rename(cfg, pack, args)


def _cmd_add_disk(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_add_disk

    return cmd_add_disk(cfg, pack, args)


def _cmd_tag(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_tag

    return cmd_tag(cfg, pack, args)


def _cmd_pool(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_pool

    return cmd_pool(cfg, pack, args)


def _cmd_sandbox(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_sandbox

    return cmd_sandbox(cfg, pack, args)


def _cmd_file_send(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vm import cmd_file_send

    return cmd_file_send(cfg, pack, args)


def _cmd_specialist(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.specialist import cmd_specialist

    return cmd_specialist(cfg, pack, args)


def _cmd_lab(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.lab import cmd_lab

    return cmd_lab(cfg, pack, args)


def _cmd_ntp(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_ntp

    return cmd_ntp(cfg, pack, args)


def _cmd_fleet_update(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_fleet_update

    return cmd_fleet_update(cfg, pack, args)


def _cmd_comms(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.comms import cmd_comms

    return cmd_comms(cfg, pack, args)


def _cmd_discover(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.discover import cmd_discover

    return cmd_discover(cfg, pack, args)


def _cmd_distros(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.distros import cmd_distros

    return cmd_distros(cfg, pack, args)


def _cmd_media(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.media import cmd_media

    return cmd_media(cfg, pack, args)


def _cmd_health(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.health import cmd_health

    return cmd_health(cfg, pack, args)


def _cmd_users(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.users import cmd_users

    return cmd_users(cfg, pack, args)


def _cmd_new_user(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.users import cmd_new_user

    return cmd_new_user(cfg, pack, args)


def _cmd_passwd(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.users import cmd_passwd

    return cmd_passwd(cfg, pack, args)


def _cmd_roles(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.users import cmd_roles

    return cmd_roles(cfg, pack, args)


def _cmd_promote(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.users import cmd_promote

    return cmd_promote(cfg, pack, args)


def _cmd_demote(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.users import cmd_demote

    return cmd_demote(cfg, pack, args)


def _cmd_install_user(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.users import cmd_install_user

    return cmd_install_user(cfg, pack, args)


def _cmd_vault(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vault import cmd_vault

    return cmd_vault(cfg, pack, args)


def _cmd_audit(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.audit import cmd_audit

    return cmd_audit(cfg, pack, args)


def _cmd_bootstrap(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.bootstrap import cmd_bootstrap

    return cmd_bootstrap(cfg, pack, args)


def _cmd_onboard(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.bootstrap import cmd_onboard

    return cmd_onboard(cfg, pack, args)


def _cmd_rescue(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_rescue

    return cmd_rescue(cfg, pack, args)


def _cmd_harden(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.harden import cmd_harden

    return cmd_harden(cfg, pack, args)


def _cmd_pfsense(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_pfsense

    return cmd_pfsense(cfg, pack, args)


def _cmd_truenas(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_truenas

    return cmd_truenas(cfg, pack, args)


def _cmd_zfs(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_truenas

    return cmd_truenas(cfg, pack, args)


def _cmd_switch_show(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_show

    return cmd_switch_show(cfg, pack, args)


def _cmd_switch_facts(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_facts

    return cmd_switch_facts(cfg, pack, args)


def _cmd_switch_interfaces(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_interfaces

    return cmd_switch_interfaces(cfg, pack, args)


def _cmd_switch_vlans(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_vlans

    return cmd_switch_vlans(cfg, pack, args)


def _cmd_switch_mac(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_mac

    return cmd_switch_mac(cfg, pack, args)


def _cmd_switch_arp(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_arp

    return cmd_switch_arp(cfg, pack, args)


def _cmd_switch_neighbors(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_neighbors

    return cmd_switch_neighbors(cfg, pack, args)


def _cmd_switch_config(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_config

    return cmd_switch_config(cfg, pack, args)


def _cmd_switch_environment(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_environment

    return cmd_switch_environment(cfg, pack, args)


def _cmd_switch_exec(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_switch_exec

    return cmd_switch_exec(cfg, pack, args)


# --- Port Management ---


def _cmd_port_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_port_status

    return cmd_port_status(cfg, pack, args)


def _cmd_port_configure(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_port_configure

    return cmd_port_configure(cfg, pack, args)


def _cmd_port_desc(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_port_desc

    return cmd_port_desc(cfg, pack, args)


def _cmd_port_poe(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_port_poe

    return cmd_port_poe(cfg, pack, args)


def _cmd_port_find(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_port_find

    return cmd_port_find(cfg, pack, args)


def _cmd_port_flap(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_port_flap

    return cmd_port_flap(cfg, pack, args)


# --- Port Profiles ---


def _cmd_profile_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_profile_list

    return cmd_profile_list(cfg, pack, args)


def _cmd_profile_show(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_profile_show

    return cmd_profile_show(cfg, pack, args)


def _cmd_profile_apply(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_profile_apply

    return cmd_profile_apply(cfg, pack, args)


def _cmd_profile_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_profile_create

    return cmd_profile_create(cfg, pack, args)


def _cmd_profile_delete(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.switch_orchestration import cmd_profile_delete

    return cmd_profile_delete(cfg, pack, args)


# --- Config Management ---


def _cmd_config_backup(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.config_management import cmd_config_backup

    return cmd_config_backup(cfg, pack, args)


def _cmd_config_history(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.config_management import cmd_config_history

    return cmd_config_history(cfg, pack, args)


def _cmd_config_diff(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.config_management import cmd_config_diff

    return cmd_config_diff(cfg, pack, args)


def _cmd_config_search(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.config_management import cmd_config_search

    return cmd_config_search(cfg, pack, args)


def _cmd_config_restore(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.config_management import cmd_config_restore

    return cmd_config_restore(cfg, pack, args)


# --- SNMP ---


def _cmd_snmp_poll(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.snmp import cmd_snmp_poll

    return cmd_snmp_poll(cfg, pack, args)


def _cmd_snmp_interfaces(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.snmp import cmd_snmp_interfaces

    return cmd_snmp_interfaces(cfg, pack, args)


def _cmd_snmp_errors(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.snmp import cmd_snmp_errors

    return cmd_snmp_errors(cfg, pack, args)


def _cmd_snmp_cpu(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.snmp import cmd_snmp_cpu

    return cmd_snmp_cpu(cfg, pack, args)


# --- Topology ---


def _cmd_topology_discover(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.topology import cmd_topology_discover

    return cmd_topology_discover(cfg, pack, args)


def _cmd_topology_show(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.topology import cmd_topology_show

    return cmd_topology_show(cfg, pack, args)


def _cmd_topology_export(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.topology import cmd_topology_export

    return cmd_topology_export(cfg, pack, args)


def _cmd_topology_diff(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.topology import cmd_topology_diff

    return cmd_topology_diff(cfg, pack, args)


# --- Network Intelligence ---


def _cmd_find_mac(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.net_intelligence import cmd_find_mac

    return cmd_find_mac(cfg, pack, args)


def _cmd_find_ip(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.net_intelligence import cmd_find_ip

    return cmd_find_ip(cfg, pack, args)


def _cmd_troubleshoot(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.net_intelligence import cmd_troubleshoot

    return cmd_troubleshoot(cfg, pack, args)


def _cmd_ip_utilization(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.net_intelligence import cmd_ip_utilization

    return cmd_ip_utilization(cfg, pack, args)


def _cmd_ip_conflict(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.net_intelligence import cmd_ip_conflict

    return cmd_ip_conflict(cfg, pack, args)


# --- Docker Fleet (WS13) ---


def _cmd_docker_containers(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.docker_mgmt import cmd_docker_containers

    return cmd_docker_containers(cfg, pack, args)


def _cmd_docker_images(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.docker_mgmt import cmd_docker_images

    return cmd_docker_images(cfg, pack, args)


def _cmd_docker_prune(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.docker_mgmt import cmd_docker_prune

    return cmd_docker_prune(cfg, pack, args)


def _cmd_docker_update_check(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.docker_mgmt import cmd_docker_update_check

    return cmd_docker_update_check(cfg, pack, args)


# --- Hardware (WS14) ---


def _cmd_hw_smart(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.hardware import cmd_hw_smart

    return cmd_hw_smart(cfg, pack, args)


def _cmd_hw_ups(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.hardware import cmd_hw_ups

    return cmd_hw_ups(cfg, pack, args)


def _cmd_hw_power(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.hardware import cmd_hw_power

    return cmd_hw_power(cfg, pack, args)


def _cmd_hw_inventory(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.hardware import cmd_hw_inventory

    return cmd_hw_inventory(cfg, pack, args)


# --- Incident/Change (WS12) ---


def _cmd_incident_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.incident import cmd_incident_create

    return cmd_incident_create(cfg, pack, args)


def _cmd_incident_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.incident import cmd_incident_list

    return cmd_incident_list(cfg, pack, args)


def _cmd_incident_update(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.incident import cmd_incident_update

    return cmd_incident_update(cfg, pack, args)


def _cmd_change_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.incident import cmd_change_create

    return cmd_change_create(cfg, pack, args)


def _cmd_change_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.incident import cmd_change_list

    return cmd_change_list(cfg, pack, args)


# --- IaC (WS15) ---


def _cmd_state_export(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.iac import cmd_state_export

    return cmd_state_export(cfg, pack, args)


def _cmd_state_drift(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.iac import cmd_state_drift

    return cmd_state_drift(cfg, pack, args)


def _cmd_state_history(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.iac import cmd_state_history

    return cmd_state_history(cfg, pack, args)


# --- Automation (WS16) ---


def _cmd_react_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.automation import cmd_react_list

    return cmd_react_list(cfg, pack, args)


def _cmd_react_add(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.automation import cmd_react_add

    args.action = getattr(args, "react_action", None)
    return cmd_react_add(cfg, pack, args)


def _cmd_react_disable(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.automation import cmd_react_disable

    return cmd_react_disable(cfg, pack, args)


def _cmd_workflow_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.automation import cmd_workflow_list

    return cmd_workflow_list(cfg, pack, args)


def _cmd_workflow_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.automation import cmd_workflow_create

    return cmd_workflow_create(cfg, pack, args)


def _cmd_job_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.automation import cmd_job_list

    return cmd_job_list(cfg, pack, args)


# --- Metrics + Monitors (WS10) ---


def _cmd_metrics_collect(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.metrics import cmd_metrics_collect

    return cmd_metrics_collect(cfg, pack, args)


def _cmd_metrics_show(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.metrics import cmd_metrics_show

    return cmd_metrics_show(cfg, pack, args)


def _cmd_metrics_top(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.metrics import cmd_metrics_top

    return cmd_metrics_top(cfg, pack, args)


def _cmd_monitor_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.synthetic_monitors import cmd_monitor_list

    return cmd_monitor_list(cfg, pack, args)


def _cmd_monitor_add(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.synthetic_monitors import cmd_monitor_add

    return cmd_monitor_add(cfg, pack, args)


def _cmd_monitor_run(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.synthetic_monitors import cmd_monitor_run

    return cmd_monitor_run(cfg, pack, args)


def _cmd_monitor_remove(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.synthetic_monitors import cmd_monitor_remove

    return cmd_monitor_remove(cfg, pack, args)


# --- Vuln + FIM (WS11) ---


def _cmd_vuln_scan(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vuln import cmd_vuln_scan

    return cmd_vuln_scan(cfg, pack, args)


def _cmd_vuln_results(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vuln import cmd_vuln_results

    return cmd_vuln_results(cfg, pack, args)


def _cmd_fim_baseline(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fim import cmd_fim_baseline

    return cmd_fim_baseline(cfg, pack, args)


def _cmd_fim_check(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fim import cmd_fim_check

    return cmd_fim_check(cfg, pack, args)


def _cmd_fim_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fim import cmd_fim_status

    return cmd_fim_status(cfg, pack, args)


# --- Storage (new) ---


def _cmd_store_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.storage import cmd_store_status

    return cmd_store_status(cfg, pack, args)


def _cmd_store_pools(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.storage import cmd_store_pools

    return cmd_store_pools(cfg, pack, args)


def _cmd_store_datasets(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.storage import cmd_store_datasets

    return cmd_store_datasets(cfg, pack, args)


def _cmd_store_snapshots(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.storage import cmd_store_snapshots

    return cmd_store_snapshots(cfg, pack, args)


def _cmd_store_smart(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.storage import cmd_store_smart

    return cmd_store_smart(cfg, pack, args)


def _cmd_store_shares(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.storage import cmd_store_shares

    return cmd_store_shares(cfg, pack, args)


def _cmd_store_alerts(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.storage import cmd_store_alerts

    return cmd_store_alerts(cfg, pack, args)


# --- DR (new) ---


def _cmd_dr_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dr import cmd_dr_status

    return cmd_dr_status(cfg, pack, args)


def _cmd_dr_backup_verify(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dr import cmd_dr_backup_verify

    return cmd_dr_backup_verify(cfg, pack, args)


def _cmd_dr_sla_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dr import cmd_dr_sla_list

    return cmd_dr_sla_list(cfg, pack, args)


def _cmd_dr_sla_set(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dr import cmd_dr_sla_set

    return cmd_dr_sla_set(cfg, pack, args)


def _cmd_dr_runbook_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dr import cmd_dr_runbook_list

    return cmd_dr_runbook_list(cfg, pack, args)


def _cmd_dr_runbook_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dr import cmd_dr_runbook_create

    return cmd_dr_runbook_create(cfg, pack, args)


def _cmd_dr_runbook_show(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dr import cmd_dr_runbook_show

    return cmd_dr_runbook_show(cfg, pack, args)


# --- Firewall ---


def _cmd_fw_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.firewall import cmd_fw_status

    return cmd_fw_status(cfg, pack, args)


def _cmd_fw_rules(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.firewall import cmd_fw_rules

    return cmd_fw_rules(cfg, pack, args)


def _cmd_fw_nat(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.firewall import cmd_fw_nat

    return cmd_fw_nat(cfg, pack, args)


def _cmd_fw_states(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.firewall import cmd_fw_states

    return cmd_fw_states(cfg, pack, args)


def _cmd_fw_interfaces(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.firewall import cmd_fw_interfaces

    return cmd_fw_interfaces(cfg, pack, args)


def _cmd_fw_gateways(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.firewall import cmd_fw_gateways

    return cmd_fw_gateways(cfg, pack, args)


def _cmd_fw_dhcp(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.firewall import cmd_fw_dhcp

    return cmd_fw_dhcp(cfg, pack, args)


# --- DNS Internal ---


def _cmd_dns_internal_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dns_management import cmd_dns_internal_list

    return cmd_dns_internal_list(cfg, pack, args)


def _cmd_dns_internal_add(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dns_management import cmd_dns_internal_add

    return cmd_dns_internal_add(cfg, pack, args)


def _cmd_dns_internal_remove(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dns_management import cmd_dns_internal_remove

    return cmd_dns_internal_remove(cfg, pack, args)


def _cmd_dns_internal_sync(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dns_management import cmd_dns_internal_sync

    return cmd_dns_internal_sync(cfg, pack, args)


def _cmd_dns_internal_audit(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dns_management import cmd_dns_internal_audit

    return cmd_dns_internal_audit(cfg, pack, args)


# --- VPN ---


def _cmd_vpn_wg_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vpn import cmd_vpn_wg_status

    return cmd_vpn_wg_status(cfg, pack, args)


def _cmd_vpn_wg_peers(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vpn import cmd_vpn_wg_peers

    return cmd_vpn_wg_peers(cfg, pack, args)


def _cmd_vpn_wg_audit(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vpn import cmd_vpn_wg_audit

    return cmd_vpn_wg_audit(cfg, pack, args)


def _cmd_vpn_ovpn_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.vpn import cmd_vpn_ovpn_status

    return cmd_vpn_ovpn_status(cfg, pack, args)


# --- Cert Management ---


def _cmd_cert_inspect(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.cert_management import cmd_cert_inspect

    return cmd_cert_inspect(cfg, pack, args)


def _cmd_cert_fleet_check(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.cert_management import cmd_cert_fleet_check

    return cmd_cert_fleet_check(cfg, pack, args)


def _cmd_cert_acme_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.cert_management import cmd_cert_acme_status

    return cmd_cert_acme_status(cfg, pack, args)


def _cmd_cert_issued_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.cert_management import cmd_cert_issued_list

    return cmd_cert_issued_list(cfg, pack, args)


# --- Proxy Management ---


def _cmd_proxy_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.proxy_management import cmd_proxy_status

    return cmd_proxy_status(cfg, pack, args)


def _cmd_proxy_hosts(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.proxy_management import cmd_proxy_hosts

    return cmd_proxy_hosts(cfg, pack, args)


def _cmd_proxy_health(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.proxy_management import cmd_proxy_health

    return cmd_proxy_health(cfg, pack, args)


# --- Event Network ---


def _cmd_event_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_create

    return cmd_event_create(cfg, pack, args)


def _cmd_event_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_list

    return cmd_event_list(cfg, pack, args)


def _cmd_event_show(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_show

    return cmd_event_show(cfg, pack, args)


def _cmd_event_plan(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_plan

    return cmd_event_plan(cfg, pack, args)


def _cmd_event_deploy(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_deploy

    return cmd_event_deploy(cfg, pack, args)


def _cmd_event_verify(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_verify

    return cmd_event_verify(cfg, pack, args)


def _cmd_event_wipe(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_wipe

    return cmd_event_wipe(cfg, pack, args)


def _cmd_event_archive(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_archive

    return cmd_event_archive(cfg, pack, args)


def _cmd_event_delete(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.event_network import cmd_event_delete

    return cmd_event_delete(cfg, pack, args)


def _cmd_idrac(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_idrac

    return cmd_idrac(cfg, pack, args)


def _cmd_watch(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_watch

    return cmd_watch(cfg, pack, args)


def _cmd_init(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.init_cmd import cmd_init

    return cmd_init(cfg, pack, args)


def _cmd_configure(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.init_cmd import cmd_configure

    return cmd_configure(cfg, pack, args)


def _cmd_check(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.engine_cmds import cmd_check

    return cmd_check(cfg, pack, args)


def _cmd_fix(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.engine_cmds import cmd_fix

    return cmd_fix(cfg, pack, args)


def _cmd_diff(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.engine_cmds import cmd_diff

    return cmd_diff(cfg, pack, args)


def _cmd_policies(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.engine_cmds import cmd_policies

    return cmd_policies(cfg, pack, args)


def _cmd_notify(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.notify import cmd_notify

    return cmd_notify(cfg, pack, args)


def _cmd_backup(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.backup import cmd_backup

    return cmd_backup(cfg, pack, args)


def _cmd_journal(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.journal import cmd_journal

    return cmd_journal(cfg, pack, args)


def _cmd_deploy_agent(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.deploy_agent import cmd_deploy_agent

    return cmd_deploy_agent(cfg, pack, args)


def _cmd_agent_status(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.deploy_agent import cmd_agent_status

    return cmd_agent_status(cfg, pack, args)


def _cmd_gwipe(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.gwipe import cmd_gwipe

    return cmd_gwipe(cfg, pack, args)


def _cmd_serve(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.serve import cmd_serve

    return cmd_serve(cfg, pack, args)


def _cmd_update(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.selfupdate import cmd_update

    return cmd_update(cfg, pack, args)


def _cmd_import(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.provision import cmd_import

    return cmd_import(cfg, pack, args)


def _cmd_provision(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.provision import cmd_provision

    return cmd_provision(cfg, pack, args)


def _cmd_agent(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.agent import cmd_agent

    return cmd_agent(cfg, pack, args)


def _cmd_learn(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.learn import cmd_learn

    return cmd_learn(cfg, pack, args)


def _cmd_risk(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.risk import cmd_risk

    return cmd_risk(cfg, pack, args)


def _cmd_sweep(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.sweep import cmd_sweep

    return cmd_sweep(cfg, pack, args)


def _cmd_patrol(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.patrol import cmd_patrol

    return cmd_patrol(cfg, pack, args)


def _cmd_playbook(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.playbook import cmd_playbook

    return cmd_playbook(cfg, pack, args)


def _cmd_federation(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.federation import cmd_federation

    return cmd_federation(cfg, pack, args)


def _cmd_gitops(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.gitops import cmd_gitops

    return cmd_gitops(cfg, pack, args)


def _cmd_chaos(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.chaos import cmd_chaos

    return cmd_chaos(cfg, pack, args)


def _cmd_capacity(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.capacity import cmd_capacity

    return cmd_capacity(cfg, pack, args)


def _cmd_cost(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.cost import cmd_cost

    return cmd_cost(cfg, pack, args)


def _cmd_rules(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.rules import cmd_rules

    return cmd_rules(cfg, pack, args)


def _cmd_docker_fleet(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.fleet import cmd_docker_fleet

    return cmd_docker_fleet(cfg, pack, args)


def _cmd_monitor(cfg: FreqConfig, pack, args) -> int:
    from freq.jarvis.patrol import check_http_monitors

    fmt.header("HTTP Endpoint Checks")
    fmt.blank()
    if not cfg.monitors:
        fmt.info("No [[monitor]] entries in freq.toml")
        fmt.blank()
        fmt.line(f"  {fmt.C.DIM}Add to freq.toml:{fmt.C.RESET}")
        fmt.line(f"  {fmt.C.DIM}[[monitor]]{fmt.C.RESET}")
        fmt.line(f'  {fmt.C.DIM}name = "Dashboard"{fmt.C.RESET}')
        fmt.line(f'  {fmt.C.DIM}url = "http://10.0.0.50:8888/healthz"{fmt.C.RESET}')
        fmt.blank()
        fmt.footer()
        return 0
    results = check_http_monitors(cfg.monitors)
    for r in results:
        if r["ok"]:
            print(f"  {fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET} {r['name']:<20} {r['status']} ({r['latency_ms']}ms)")
        else:
            err = r["error"] or f"HTTP {r['status']}"
            print(f"  {fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET} {r['name']:<20} {err} ({r['latency_ms']}ms)")
    ok = sum(1 for r in results if r["ok"])
    fmt.blank()
    fmt.line(f"  {ok}/{len(results)} endpoints healthy")
    fmt.blank()
    fmt.footer()
    return 0 if ok == len(results) else 1


def _cmd_ip(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.ipam import cmd_ip

    return cmd_ip(cfg, pack, args)


def _cmd_plan(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plan import cmd_plan

    return cmd_plan(cfg, pack, args)


def _cmd_apply(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plan import cmd_apply

    return cmd_apply(cfg, pack, args)


def _cmd_alert(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.alert import cmd_alert

    return cmd_alert(cfg, pack, args)


def _cmd_rollback(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.rollback import cmd_rollback

    # Handle --no-start flag
    if getattr(args, "no_start", False):
        args.start = False
    else:
        args.start = True
    return cmd_rollback(cfg, pack, args)


def _cmd_inventory(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.inventory import cmd_inventory

    return cmd_inventory(cfg, pack, args)


def _cmd_compare(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.compare import cmd_compare

    return cmd_compare(cfg, pack, args)


def _cmd_baseline(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.baseline import cmd_baseline

    return cmd_baseline(cfg, pack, args)


def _cmd_report(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.report import cmd_report

    return cmd_report(cfg, pack, args)


def _cmd_trend(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.trend import cmd_trend

    return cmd_trend(cfg, pack, args)


def _cmd_sla(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.sla import cmd_sla

    return cmd_sla(cfg, pack, args)


def _cmd_cert(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.cert import cmd_cert

    return cmd_cert(cfg, pack, args)


def _cmd_dns(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.dns import cmd_dns

    return cmd_dns(cfg, pack, args)


def _cmd_schedule(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.schedule import cmd_schedule

    return cmd_schedule(cfg, pack, args)


def _cmd_backup_policy(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.backup_policy import cmd_backup_policy

    return cmd_backup_policy(cfg, pack, args)


def _cmd_webhook(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.webhook import cmd_webhook

    return cmd_webhook(cfg, pack, args)


def _cmd_migrate_plan(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.migrate_plan import cmd_migrate_plan

    return cmd_migrate_plan(cfg, pack, args)


def _cmd_migrate_vmware(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.migrate_vmware import cmd_migrate_vmware

    return cmd_migrate_vmware(cfg, pack, args)


def _cmd_patch(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.patch import cmd_patch

    return cmd_patch(cfg, pack, args)


def _cmd_stack(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.stack import cmd_stack

    return cmd_stack(cfg, pack, args)


def _cmd_docs(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.docs import cmd_docs

    return cmd_docs(cfg, pack, args)


def _cmd_db(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.db import cmd_db

    return cmd_db(cfg, pack, args)


def _cmd_proxy(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.proxy import cmd_proxy

    return cmd_proxy(cfg, pack, args)


def _cmd_secrets(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.secrets import cmd_secrets

    return cmd_secrets(cfg, pack, args)


def _cmd_logs(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.logs import cmd_logs

    return cmd_logs(cfg, pack, args)


def _cmd_oncall(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.oncall import cmd_oncall

    return cmd_oncall(cfg, pack, args)


def _cmd_comply(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.comply import cmd_comply

    return cmd_comply(cfg, pack, args)


def _cmd_map(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.depmap import cmd_map

    return cmd_map(cfg, pack, args)


def _cmd_netmon(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.netmon import cmd_netmon

    return cmd_netmon(cfg, pack, args)


def _cmd_cost_analysis(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.cost_analysis import cmd_cost_analysis

    return cmd_cost_analysis(cfg, pack, args)


def _cmd_hosts(cfg: FreqConfig, pack, args) -> int:
    """Route to hosts module."""
    from freq.modules.hosts import cmd_hosts

    return cmd_hosts(cfg, pack, args)


def _cmd_groups(cfg: FreqConfig, pack, args) -> int:
    """Route to groups module."""
    from freq.modules.hosts import cmd_groups

    return cmd_groups(cfg, pack, args)


# ---------------------------------------------------------------------------
# Plugin commands
# ---------------------------------------------------------------------------


def _cmd_plugin_list(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_list

    return cmd_plugin_list(cfg, pack, args)


def _cmd_plugin_info(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_info

    return cmd_plugin_info(cfg, pack, args)


def _cmd_plugin_install(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_install

    return cmd_plugin_install(cfg, pack, args)


def _cmd_plugin_remove(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_remove

    return cmd_plugin_remove(cfg, pack, args)


def _cmd_plugin_create(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_create

    return cmd_plugin_create(cfg, pack, args)


def _cmd_plugin_search(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_search

    return cmd_plugin_search(cfg, pack, args)


def _cmd_plugin_update(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_update

    return cmd_plugin_update(cfg, pack, args)


def _cmd_plugin_types(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.plugin_manager import cmd_plugin_types

    return cmd_plugin_types(cfg, pack, args)


def _cmd_config_validate(cfg: FreqConfig, pack, args) -> int:
    """Validate FREQ configuration."""
    from freq.core.config import validate_config

    issues = validate_config(cfg)

    if getattr(args, "json_output", False):
        import json
        print(json.dumps({"valid": len(issues) == 0, "issues": issues}, indent=2))
        return 0 if not issues else 1

    if not issues:
        fmt.step_ok("Configuration is valid")
        return 0

    fmt.step_fail(f"Configuration has {len(issues)} issue(s):")
    for issue in issues:
        fmt.line(f"    {fmt.C.RED}•{fmt.C.RESET} {issue}")
    return 1
