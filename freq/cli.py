"""FREQ CLI dispatcher.

Routes all 55+ commands through argparse. This is the entry point.
Every command that FREQ supports is registered here.

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
from freq.core.personality import load_pack, show_vibe, splash


def main(argv: list = None) -> int:
    """Main entry point for FREQ CLI."""
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
                    p = sub.add_parser(plugin["name"],
                                       help=f"[plugin] {plugin['description']}")
                    p.add_argument("plugin_args", nargs="*", help="Plugin arguments")
                    h = plugin["handler"]
                    p.set_defaults(func=lambda c, pk, a, _h=h: _h(c, pk, a))
                except Exception as e:
                    logger.warn(f"failed to register plugin {plugin.get('name', '?')}: {e}")

    args = parser.parse_args(argv)

    # Init logging
    logger.init(cfg.log_file)

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
    logger.info(f"command: {args.command}", user=os.environ.get("USER", "unknown"))

    try:
        result = args.func(cfg, pack, args)
    except KeyboardInterrupt:
        print()
        fmt.warn("Interrupted.")
        return 130
    except Exception as e:
        fmt.error(f"Command failed: {e}")
        logger.error(f"command failed: {e}", command=getattr(args, "command", "unknown"))
        if cfg.debug:
            import traceback
            traceback.print_exc()
        return 1

    # Vibe check after successful commands
    if result == 0:
        show_vibe(pack)

    return result or 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all commands."""
    parser = argparse.ArgumentParser(
        prog="freq",
        description="PVE FREQ — Datacenter management CLI for homelabbers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"PVE FREQ v{freq.__version__}")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmations")
    parser.add_argument("--json", action="store_true", help="JSON output mode")
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")

    sub = parser.add_subparsers(dest="command")

    # --- Utilities ---
    p = sub.add_parser("version", help="Show version and branding")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("help", help="Show all commands")
    p.set_defaults(func=cmd_help)

    p = sub.add_parser("doctor", help="Self-diagnostic")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("why", help="Explain VM permissions and protections")
    p.add_argument("target", nargs="?", help="VMID to explain")
    p.set_defaults(func=_cmd_why)

    p = sub.add_parser("test-connection", help="Test host connectivity (TCP + SSH + sudo)")
    p.add_argument("target", nargs="?", help="Host IP or label")
    p.set_defaults(func=_cmd_test_connection)

    p = sub.add_parser("menu", help="Interactive TUI menu")
    p.set_defaults(func=cmd_menu)

    p = sub.add_parser("demo", help="Interactive demo — no fleet required")
    p.set_defaults(func=_cmd_demo)

    # --- Fleet Operations ---
    p = sub.add_parser("status", help="Fleet health summary")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("dashboard", help="Fleet dashboard overview")
    p.set_defaults(func=_cmd_dashboard)

    p = sub.add_parser("exec", help="Run command across fleet")
    p.add_argument("target", nargs="?", help="Host label, group, or 'all'")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute")
    p.set_defaults(func=_cmd_exec)

    p = sub.add_parser("info", help="System info for a host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_info)

    p = sub.add_parser("detail", help="Deep host inventory (full system detail)")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_detail)

    p = sub.add_parser("boundaries", help="Fleet boundary tiers and VM categories")
    p.add_argument("action", nargs="?", default="show", choices=["show", "lookup"],
                   help="Action (default: show)")
    p.add_argument("target", nargs="?", help="VMID (for lookup)")
    p.set_defaults(func=_cmd_boundaries)

    p = sub.add_parser("diagnose", help="Deep diagnostic for a host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_diagnose)

    p = sub.add_parser("ssh", help="SSH to a fleet host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_ssh)

    p = sub.add_parser("docker", help="Container discovery and management")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_docker)

    p = sub.add_parser("log", help="View logs for a host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.add_argument("--lines", "-n", type=int, default=30, help="Number of log lines")
    p.add_argument("--unit", "-u", help="Systemd unit to filter")
    p.set_defaults(func=_cmd_log)

    p = sub.add_parser("keys", help="SSH key management")
    p.add_argument("action", nargs="?", choices=["deploy", "list", "rotate"], help="Key action")
    p.add_argument("--target", help="Host label for deploy")
    p.set_defaults(func=_cmd_keys)

    # --- Host Management ---
    p = sub.add_parser("hosts", help="List and manage hosts")
    p.add_argument("action", nargs="?", choices=["list", "add", "remove", "edit", "sync"], default="list")
    p.add_argument("--dry-run", action="store_true", help="Show what sync would change without writing")
    p.set_defaults(func=_cmd_hosts)

    p = sub.add_parser("discover", help="Discover hosts on the network")
    p.add_argument("subnet", nargs="?", help="Subnet to scan (e.g. 192.168.1 or 192.168.1.0/24)")
    p.set_defaults(func=_cmd_discover)

    p = sub.add_parser("groups", help="Manage host groups")
    p.add_argument("action", nargs="?", choices=["list", "add", "remove"], default="list")
    p.set_defaults(func=_cmd_groups)

    p = sub.add_parser("bootstrap", help="Bootstrap a new host")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_bootstrap)

    p = sub.add_parser("onboard", help="Onboard a host to the fleet")
    p.add_argument("target", nargs="?", help="Host label or IP")
    p.set_defaults(func=_cmd_onboard)

    # --- VM Management ---
    p = sub.add_parser("list", help="List VMs across PVE cluster")
    p.add_argument("--node", help="Filter by PVE node")
    p.add_argument("--status", help="Filter by status (running/stopped)")
    p.set_defaults(func=_cmd_list)

    p = sub.add_parser("create", help="Create a new VM")
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

    p = sub.add_parser("clone", help="Clone a VM with optional network config")
    p.add_argument("source", nargs="?", help="Source VMID or name")
    p.add_argument("--name", help="New VM hostname")
    p.add_argument("--vmid", type=int, help="New VMID")
    p.add_argument("--node", help="Target PVE node")
    p.add_argument("--ip", help="Static IP (triggers disk mount network config)")
    p.add_argument("--vlan", help="VLAN name (dirty/clean/dev/mgmt)")
    p.add_argument("--start", action="store_true", help="Start VM after clone")
    p.set_defaults(func=_cmd_clone)

    p = sub.add_parser("destroy", help="Destroy a VM")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--dry-run", action="store_true", help="Show what would be destroyed without executing")
    p.set_defaults(func=_cmd_destroy)

    p = sub.add_parser("resize", help="Resize a VM")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--cores", type=int, help="New CPU cores")
    p.add_argument("--ram", type=int, help="New RAM in MB")
    p.add_argument("--disk", type=int, help="Add disk in GB")
    p.set_defaults(func=_cmd_resize)

    p = sub.add_parser("snapshot", help="Snapshot management (create/list/delete)")
    p.add_argument("snap_action", nargs="?", choices=["create", "list", "delete"], default="create",
                   help="Action: create (default), list, delete")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--name", help="Snapshot name (for create/delete)")
    p.set_defaults(func=_cmd_snapshot)

    p = sub.add_parser("power", help="VM power control (start/stop/reboot/shutdown/status)")
    p.add_argument("action", choices=["start", "stop", "reboot", "shutdown", "status"],
                   help="Power action")
    p.add_argument("target", help="VMID")
    p.set_defaults(func=_cmd_power)

    p = sub.add_parser("nic", help="VM NIC management (add/clear/change-ip/change-id/check-ip)")
    p.add_argument("action", choices=["add", "clear", "change-ip", "change-id", "check-ip"],
                   help="NIC action")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("--ip", help="IP address (CIDR or bare)")
    p.add_argument("--gw", help="Gateway IP")
    p.add_argument("--vlan", help="VLAN ID")
    p.add_argument("--nic-index", type=int, default=0, help="NIC index (default: 0)")
    p.add_argument("--new-id", help="New VMID (for change-id)")
    p.set_defaults(func=_cmd_nic)

    p = sub.add_parser("import", help="Import a cloud image as a VM")
    p.add_argument("--image", help="Cloud image (debian-13, ubuntu-2404, etc.)")
    p.add_argument("--name", help="VM hostname")
    p.add_argument("--vmid", type=int, help="Specific VMID")
    p.set_defaults(func=_cmd_import)

    p = sub.add_parser("migrate", help="Migrate a VM between nodes")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.add_argument("--node", help="Target PVE node")
    p.add_argument("--storage", help="Target storage pool (auto-detected if omitted)")
    p.add_argument("--yes", "-y", action="store_true", help="Skip confirmations (auto-delete snapshots)")
    p.add_argument("--dry-run", action="store_true", help="Show migration plan without executing")
    p.set_defaults(func=_cmd_migrate)

    p = sub.add_parser("template", help="Convert a VM to a template")
    p.add_argument("target", nargs="?", help="VMID")
    p.set_defaults(func=_cmd_template)

    p = sub.add_parser("rename", help="Rename a VM")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("--name", help="New hostname")
    p.set_defaults(func=_cmd_rename)

    p = sub.add_parser("add-disk", help="Add disk(s) to a VM")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("--size", type=int, help="Disk size in GB")
    p.add_argument("--count", type=int, default=1, help="Number of disks")
    p.set_defaults(func=_cmd_add_disk)

    p = sub.add_parser("tag", help="Set/view PVE tags on a VM")
    p.add_argument("target", nargs="?", help="VMID")
    p.add_argument("tags", nargs="?", help="Tags (comma-separated)")
    p.set_defaults(func=_cmd_tag)

    p = sub.add_parser("pool", help="PVE pool management")
    p.add_argument("action", nargs="?", choices=["list", "create", "add"], default="list")
    p.add_argument("--name", help="Pool name")
    p.add_argument("--target", help="VMID to add to pool")
    p.set_defaults(func=_cmd_pool)

    p = sub.add_parser("sandbox", help="Spawn a VM from template")
    p.add_argument("source", nargs="?", help="Template VMID")
    p.add_argument("--name", help="New VM hostname")
    p.add_argument("--vmid", type=int, help="New VMID")
    p.add_argument("--ip", help="Static IP address")
    p.set_defaults(func=_cmd_sandbox)

    p = sub.add_parser("file", help="Send files to fleet hosts")
    p.add_argument("file_action", nargs="?", choices=["send"], default="send")
    p.add_argument("source", nargs="?", help="Local file path")
    p.add_argument("destination", nargs="?", help="host:remote_path")
    p.set_defaults(func=_cmd_file_send)

    # --- Proxmox ---
    p = sub.add_parser("vm-overview", help="VM inventory across cluster")
    p.set_defaults(func=_cmd_vm_overview)

    p = sub.add_parser("vmconfig", help="View/edit VM configuration")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.set_defaults(func=_cmd_vmconfig)

    p = sub.add_parser("rescue", help="Rescue a stuck VM")
    p.add_argument("target", nargs="?", help="VMID or name")
    p.set_defaults(func=_cmd_rescue)

    # --- User Management ---
    p = sub.add_parser("users", help="List users")
    p.set_defaults(func=_cmd_users)

    p = sub.add_parser("new-user", help="Create a new user")
    p.add_argument("username", nargs="?", help="Username")
    p.add_argument("--role", choices=["viewer", "operator", "admin"], help="Initial role")
    p.set_defaults(func=_cmd_new_user)

    p = sub.add_parser("passwd", help="Change user password")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_passwd)

    p = sub.add_parser("roles", help="View role assignments")
    p.set_defaults(func=_cmd_roles)

    p = sub.add_parser("promote", help="Promote user to higher role")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_promote)

    p = sub.add_parser("demote", help="Demote user to lower role")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_demote)

    p = sub.add_parser("install-user", help="Install user across fleet")
    p.add_argument("username", nargs="?", help="Username")
    p.set_defaults(func=_cmd_install_user)

    # --- Security ---
    p = sub.add_parser("vault", help="Encrypted credential store")
    p.add_argument("action", nargs="?", choices=["init", "set", "get", "delete", "list", "import"])
    p.add_argument("key", nargs="?", help="Vault key name")
    p.add_argument("value", nargs="?", help="Vault value (for set)")
    p.add_argument("--host", help="Host scope (default: DEFAULT)")
    p.set_defaults(func=_cmd_vault)

    p = sub.add_parser("audit", help="Security audit")
    p.add_argument("--fix", action="store_true", help="Auto-fix findings")
    p.set_defaults(func=_cmd_audit)

    p = sub.add_parser("harden", help="Apply security hardening")
    p.add_argument("target", nargs="?", help="Host label or 'all'")
    p.set_defaults(func=_cmd_harden)

    # --- Infrastructure ---
    p = sub.add_parser("pfsense", help="pfSense management")
    p.add_argument("action", nargs="?", help="Subcommand (status/rules/nat/states/interfaces)")
    p.set_defaults(func=_cmd_pfsense)

    p = sub.add_parser("truenas", help="TrueNAS management")
    p.add_argument("action", nargs="?", help="Subcommand (status/pools/health/datasets/shares/alerts)")
    p.set_defaults(func=_cmd_truenas)

    p = sub.add_parser("zfs", help="ZFS operations")
    p.add_argument("action", nargs="?", help="Subcommand")
    p.set_defaults(func=_cmd_zfs)

    p = sub.add_parser("switch", help="Network switch management")
    p.add_argument("action", nargs="?", help="Subcommand (status/vlans/interfaces/mac/trunk)")
    p.set_defaults(func=_cmd_switch)

    p = sub.add_parser("idrac", help="Dell iDRAC management")
    p.add_argument("action", nargs="?", help="Subcommand (status/sensors/power/sel/info)")
    p.set_defaults(func=_cmd_idrac)

    p = sub.add_parser("media", help="Media stack management")
    p.add_argument("action", nargs="?", help="Subcommand (status/restart/stop/start/logs/stats/"
                   "update/prune/backup/restore/health/doctor/queue/streams/vpn/disk/"
                   "missing/search/scan/activity/wanted/indexers/downloads/"
                   "transcode/subtitles/requests/nuke/export/dashboard/report/"
                   "compose/mounts/cleanup/gpu)")
    p.add_argument("service", nargs="?", help="Service name or sub-action")
    p.add_argument("--check", action="store_true", help="Check mode (for update)")
    p.add_argument("--list", action="store_true", help="List mode (for backup)")
    p.add_argument("--lines", "-n", type=int, default=50, help="Number of log lines")
    p.add_argument("--errors", action="store_true", help="Show only errors/warnings (for logs)")
    p.add_argument("--since", help="Show logs since duration (e.g., 1h, 30m, 2d)")
    p.set_defaults(func=_cmd_media)

    # --- Specialist ---
    p = sub.add_parser("specialist", help="Specialist VM workspace deployment")
    p.add_argument("action", nargs="?", choices=["create", "health", "status", "list", "roles"],
                   default="list")
    p.add_argument("target", nargs="?", help="Host IP or label")
    p.add_argument("--role", choices=["sandbox", "dev", "infra", "security", "media"],
                   help="Specialist role")
    p.add_argument("--name", help="Specialist name")
    p.set_defaults(func=_cmd_specialist)

    # --- Lab ---
    p = sub.add_parser("lab", help="Lab environment management")
    p.add_argument("action", nargs="?", choices=["status", "media", "deploy", "resize", "rebuild"],
                   default="status")
    p.add_argument("service", nargs="?", help="Sub-action (deploy/status for media)")
    p.add_argument("target", nargs="?", help="VMID (for resize/rebuild)")
    p.add_argument("--min", action="store_true", help="Set minimum viable specs")
    p.add_argument("--template", type=int, help="Template VMID for rebuild")
    p.add_argument("--cores", type=int, default=2, help="CPU cores")
    p.add_argument("--ram", type=int, default=2048, help="RAM in MB")
    p.set_defaults(func=_cmd_lab)

    # --- Fleet Extended ---
    p = sub.add_parser("ntp", help="Fleet NTP check/fix")
    p.add_argument("action", nargs="?", choices=["check", "fix"], default="check")
    p.set_defaults(func=_cmd_ntp)

    p = sub.add_parser("fleet-update", help="Fleet OS update check/apply")
    p.add_argument("action", nargs="?", choices=["check", "apply"], default="check")
    p.set_defaults(func=_cmd_fleet_update)

    p = sub.add_parser("comms", help="Inter-VM communication")
    p.add_argument("action", nargs="?", choices=["setup", "send", "check", "read"],
                   default="check")
    p.add_argument("--target", help="Destination host")
    p.add_argument("--message", "-m", help="Message text")
    p.set_defaults(func=_cmd_comms)

    # --- Monitoring ---
    p = sub.add_parser("health", help="Comprehensive fleet health")
    p.set_defaults(func=_cmd_health)

    p = sub.add_parser("watch", help="Monitoring daemon")
    p.set_defaults(func=_cmd_watch)

    # --- Engine ---
    p = sub.add_parser("check", help="Check policy compliance (dry run)")
    p.add_argument("policy", nargs="?", help="Policy name")
    p.add_argument("--hosts", help="Comma-separated host labels")
    p.set_defaults(func=_cmd_check)

    p = sub.add_parser("fix", help="Apply policy remediation")
    p.add_argument("policy", nargs="?", help="Policy name")
    p.add_argument("--hosts", help="Comma-separated host labels")
    p.set_defaults(func=_cmd_fix)

    p = sub.add_parser("diff", help="Show policy drift as git-style diff")
    p.add_argument("policy", nargs="?", help="Policy name")
    p.add_argument("--hosts", help="Comma-separated host labels")
    p.set_defaults(func=_cmd_diff)

    p = sub.add_parser("policies", help="List available policies")
    p.set_defaults(func=_cmd_policies)

    # --- Deployment ---
    p = sub.add_parser("init", help="First-run setup wizard")
    p.add_argument("--check", action="store_true", help="Validate init state — local files + remote host SSH")
    p.add_argument("--fix", action="store_true", help="Scan fleet, find broken hosts, redeploy freq-admin")
    p.add_argument("--reset", action="store_true", help="Wipe vault, roles, .initialized (fresh start)")
    p.add_argument("--uninstall", action="store_true", help="Remove FREQ service account from all hosts")
    p.add_argument("--dry-run", action="store_true", help="Show what init would do (or would remove with --uninstall)")
    p.add_argument("--headless", action="store_true", help="Non-interactive mode (no prompts)")
    p.add_argument("--bootstrap-key", help="SSH key for initial auth to fleet hosts")
    p.add_argument("--bootstrap-user", default="root", help="SSH user for initial auth — root or sudo account (default: root)")
    p.add_argument("--password-file", help="Read service account password from file")
    p.add_argument("--pve-nodes", help="PVE node IPs (space-separated, e.g. '10.0.0.1 10.0.0.2')")
    p.add_argument("--pve-node-names", help="PVE node names (space-separated, same order as --pve-nodes)")
    p.add_argument("--gateway", help="Network gateway IP for VM networking")
    p.add_argument("--nameserver", help="DNS nameserver IP (default: 1.1.1.1)")
    p.add_argument("--cluster-name", help="Cluster name (e.g. dc01, homelab)")
    p.add_argument("--ssh-mode", choices=["sudo", "root"], help="SSH mode: sudo (recommended) or root")
    p.add_argument("--hosts-file", help="Path to hosts.conf to import fleet hosts from")
    p.add_argument("--device-credentials", help="TOML file with per-device-type auth (user + password_file per section)")
    p.add_argument("--device-password-file", help="(deprecated) Single password file for all devices — use --device-credentials instead")
    p.add_argument("--device-user", default="root", help="(deprecated) Single SSH user for all devices — use --device-credentials instead")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("configure", help="Reconfigure FREQ settings")
    p.set_defaults(func=_cmd_configure)

    # --- Agent Platform ---
    p = sub.add_parser("agent", help="AI specialist management")
    p.add_argument("action", nargs="?", choices=["templates", "create", "list", "start", "stop", "destroy", "status", "ssh"])
    p.add_argument("name", nargs="?", help="Agent name or template")
    p.add_argument("--agent-name", help="Custom agent name (for create)")
    p.add_argument("--image", help="Cloud image (debian-13, ubuntu-2404, rocky-9, etc.)")
    p.add_argument("--no-cloud-init", action="store_true", help="Create empty VM without cloud-init")
    p.set_defaults(func=_cmd_agent)

    # --- JARVIS (Smart Commands) ---
    p = sub.add_parser("learn", help="Search Proxmox operational knowledge base")
    p.add_argument("query", nargs="*", help="Search terms")
    p.set_defaults(func=_cmd_learn)

    p = sub.add_parser("risk", help="Kill-chain blast radius analysis")
    p.add_argument("target", nargs="?", help="Infrastructure target (pfsense/truenas/switch/all)")
    p.set_defaults(func=_cmd_risk)

    p = sub.add_parser("sweep", help="Full audit + policy check pipeline")
    p.add_argument("--fix", action="store_true", help="Apply fixes (default: dry run)")
    p.set_defaults(func=_cmd_sweep)

    p = sub.add_parser("patrol", help="Continuous monitoring + drift detection")
    p.add_argument("--interval", type=int, default=30, help="Check interval in seconds")
    p.add_argument("--auto-fix", action="store_true", help="Auto-remediate drift")
    p.set_defaults(func=_cmd_patrol)

    # --- Remaining ---
    p = sub.add_parser("distros", help="List available cloud images")
    p.set_defaults(func=_cmd_distros)

    p = sub.add_parser("provision", help="Cloud-init VM provisioning")
    p.set_defaults(func=_cmd_provision)

    p = sub.add_parser("notify", help="Send notifications to Discord/Slack")
    p.add_argument("message", nargs="*", help="Notification message")
    p.set_defaults(func=_cmd_notify)

    p = sub.add_parser("backup", help="VM snapshots, config export, retention")
    p.add_argument("action", nargs="?", choices=["list", "create", "export", "status", "prune"],
                   default="list")
    p.add_argument("target", nargs="?", help="VMID (for create)")
    p.set_defaults(func=_cmd_backup)

    p = sub.add_parser("journal", help="Operation history")
    p.add_argument("--lines", "-n", type=int, default=20, help="Number of entries")
    p.add_argument("--search", "-s", help="Search filter")
    p.set_defaults(func=_cmd_journal)

    p = sub.add_parser("deploy-agent", help="Deploy metrics collector to fleet")
    p.add_argument("target", nargs="?", help="Host label or 'all'")
    p.set_defaults(func=_cmd_deploy_agent)

    p = sub.add_parser("agent-status", help="Check metrics agent status across fleet")
    p.set_defaults(func=_cmd_agent_status)

    p = sub.add_parser("gwipe", help="FREQ WIPE — drive sanitization station")
    p.add_argument("action", nargs="?", default="status",
                   help="Subcommand (status/bays/history/test/wipe/full-send/pause/resume/connect)")
    p.add_argument("target", nargs="?", help="Bay device (e.g. sdb) for per-bay actions")
    p.add_argument("--host", help="GWIPE station IP (overrides vault)")
    p.add_argument("--key", help="API key (overrides vault)")
    p.set_defaults(func=_cmd_gwipe)

    p = sub.add_parser("serve", help="Start web dashboard")
    p.add_argument("--port", type=int, default=None, help="Port number (default: from freq.toml or 8888)")
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser("update", help="Check for updates and upgrade FREQ")
    p.set_defaults(func=_cmd_update)

    return parser


# --- Built-in Commands ---

def cmd_version(cfg: FreqConfig, pack, args) -> int:
    """Show version with branding."""
    from freq.core.personality import splash
    splash(pack, cfg.version)
    return 0


def cmd_help(cfg: FreqConfig, pack, args) -> int:
    """Show all commands organized by category."""
    fmt.header("Command Reference")
    fmt.blank()

    categories = [
        ("Utilities", [
            ("version", "Show version and branding"),
            ("help", "This command reference"),
            ("doctor", "Self-diagnostic"),
            ("why <vmid>", "Explain VM permissions and protections"),
            ("test-connection <host>", "Test host connectivity (TCP + SSH + sudo)"),
            ("menu", "Interactive TUI menu"),
            ("demo", "Interactive demo (no fleet required)"),
        ]),
        ("Fleet Operations", [
            ("status", "Fleet health summary"),
            ("dashboard", "Fleet dashboard overview"),
            ("exec <target> <cmd>", "Run command across fleet"),
            ("info <host>", "System info for a host"),
            ("diagnose <host>", "Deep diagnostic"),
            ("ssh <host>", "SSH to a fleet host"),
            ("docker <host>", "Container management"),
            ("log <host>", "View host logs"),
            ("keys <action>", "SSH key management"),
        ]),
        ("Host Management", [
            ("hosts [list|add|remove]", "Manage fleet hosts"),
            ("discover", "Discover hosts on network"),
            ("groups [list|add|remove]", "Manage host groups"),
            ("bootstrap <host>", "Bootstrap a new host"),
            ("onboard <host>", "Onboard to fleet"),
        ]),
        ("VM Management", [
            ("list [--node] [--status]", "List VMs across cluster"),
            ("create [--name --image ...]", "Create a new VM"),
            ("clone <source> [--name]", "Clone an existing VM"),
            ("destroy <target>", "Destroy a VM"),
            ("resize <target> [--cores --ram]", "Resize a VM"),
            ("power <action> <vmid>", "Power control (start/stop/reboot/shutdown)"),
            ("snapshot [create|list|delete]", "Snapshot management"),
            ("nic <action> <vmid>", "NIC management (add/clear/change-ip/change-id)"),
            ("migrate <target> --node", "Migrate between nodes"),
            ("import", "Import VM from backup"),
            ("template <vmid>", "Convert VM to template"),
            ("rename <vmid> --name", "Rename a VM"),
            ("add-disk <vmid> --size", "Add disk(s) to a VM"),
            ("tag <vmid> [tags]", "Set/view PVE tags"),
            ("pool [list|create|add]", "Pool management"),
            ("sandbox <template>", "Spawn from template"),
            ("file send <src> <host:dst>", "SCP file to host"),
        ]),
        ("Proxmox", [
            ("vm-overview", "VM inventory across cluster"),
            ("vmconfig <target>", "View/edit VM configuration"),
            ("rescue <target>", "Rescue a stuck VM"),
        ]),
        ("User Management", [
            ("users", "List users"),
            ("new-user <username>", "Create user"),
            ("passwd <username>", "Change password"),
            ("roles", "View role assignments"),
            ("promote <user>", "Promote to higher role"),
            ("demote <user>", "Demote to lower role"),
            ("install-user <user>", "Install user across fleet"),
        ]),
        ("Security", [
            ("vault <action> [key]", "Encrypted credential store"),
            ("audit [--fix]", "Security audit"),
            ("harden <target>", "Apply hardening"),
        ]),
        ("Infrastructure", [
            ("pfsense <action>", "pfSense management"),
            ("truenas <action>", "TrueNAS management"),
            ("zfs <action>", "ZFS operations"),
            ("switch <action>", "Network switch"),
            ("idrac <action>", "Dell iDRAC"),
            ("media <action> [svc]", "Media stack (40+ subcommands)"),
        ]),
        ("Specialist & Lab", [
            ("specialist create <host>", "Deploy Claude Code workspace"),
            ("specialist health <host>", "Check specialist VM health"),
            ("specialist roles", "List available roles"),
            ("lab status", "Lab fleet overview"),
            ("lab media deploy", "Deploy test media stack"),
            ("lab resize <vmid> --min", "Set minimum specs"),
            ("lab rebuild <vmid>", "Destroy and recreate from template"),
        ]),
        ("Fleet Extended", [
            ("ntp [check|fix]", "Fleet NTP check/fix"),
            ("fleet-update [check|apply]", "Fleet OS updates"),
            ("comms [setup|send|check]", "Inter-VM mailbox"),
            ("backup status", "Backup retention status"),
            ("backup prune", "Remove old backups"),
        ]),
        ("Monitoring", [
            ("health", "Comprehensive fleet health"),
            ("watch", "Monitoring daemon"),
        ]),
        ("Engine", [
            ("check <policy>", "Check compliance (dry run)"),
            ("fix <policy>", "Apply remediation"),
            ("diff <policy>", "Show drift as git diff"),
            ("policies", "List available policies"),
        ]),
        ("Agent Platform", [
            ("agent templates", "List specialist templates"),
            ("agent create <template>", "Create a new AI specialist"),
            ("agent list", "Show registered agents"),
            ("agent start/stop <name>", "Manage agent sessions"),
            ("agent destroy <name>", "Remove agent + VM"),
        ]),
        ("Smart Commands", [
            ("learn <query>", "Search Proxmox operational knowledge"),
            ("risk <target>", "Kill-chain blast radius analysis"),
            ("sweep [--fix]", "Full audit + policy sweep pipeline"),
            ("patrol [--interval N]", "Continuous monitoring + drift detection"),
        ]),
        ("Deployment", [
            ("init", "First-run setup wizard"),
            ("configure", "Reconfigure settings"),
        ]),
    ]

    for category, commands in categories:
        fmt.line(f"{fmt.C.PURPLE_BOLD}{category}{fmt.C.RESET}")
        for cmd_name, desc in commands:
            fmt.line(f"  {fmt.C.CYAN}freq {cmd_name:<30}{fmt.C.RESET} {desc}")
        fmt.blank()

    fmt.footer()
    return 0


def cmd_doctor(cfg: FreqConfig, pack, args) -> int:
    """Run self-diagnostic."""
    from freq.core.doctor import run
    return run(cfg)


def cmd_menu(cfg: FreqConfig, pack, args) -> int:
    """Launch interactive TUI menu."""
    from freq.tui.menu import run as tui_run
    return tui_run(cfg, pack)


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


def _cmd_switch(cfg: FreqConfig, pack, args) -> int:
    from freq.modules.infrastructure import cmd_switch
    return cmd_switch(cfg, pack, args)


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


def _cmd_hosts(cfg: FreqConfig, pack, args) -> int:
    """Route to hosts module."""
    from freq.modules.hosts import cmd_hosts
    return cmd_hosts(cfg, pack, args)


def _cmd_groups(cfg: FreqConfig, pack, args) -> int:
    """Route to groups module."""
    from freq.modules.hosts import cmd_groups
    return cmd_groups(cfg, pack, args)


