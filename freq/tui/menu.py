"""Interactive TUI menu for FREQ.

Renders menus with ANSI colors, reads single keystrokes, dispatches commands.
No external dependencies — works in PuTTY, xterm, any terminal.

Design: reimagined from v1.0.0 menu.sh (890 lines, 14 submenus).
"""
import os
import sys
import termios
import tty

from freq.core import fmt
from freq.core.personality import splash


# --- Terminal Helpers ---

def _clear():
    """Clear screen using ANSI escape."""
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _getch():
    """Read a single keypress without echo."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return ch


def _pause():
    """Wait for any key."""
    print(f"\n  {fmt.C.DIM}Press any key to continue...{fmt.C.RESET}", end="", flush=True)
    _getch()
    print()


def _input(prompt: str) -> str:
    """Read a line of input with prompt."""
    try:
        return input(f"  {fmt.C.CYAN}{prompt}{fmt.C.RESET} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def _confirm(msg: str, default_yes: bool = False) -> bool:
    """Ask yes/no confirmation."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    try:
        answer = input(f"  {fmt.C.YELLOW}{msg} {suffix}:{fmt.C.RESET} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default_yes
    return answer in ("y", "yes")


# --- Risk Tags ---

class Tag:
    """Risk/status tags for menu items."""
    SAFE = f"{fmt.C.GREEN}{fmt.S.TICK}{fmt.C.RESET}"
    CHANGES = f"{fmt.C.YELLOW}{fmt.S.WARN}{fmt.C.RESET}"
    RISKY = f"{fmt.C.RED}{fmt.S.WARN}{fmt.C.RESET}"
    DESTRUCTIVE = f"{fmt.C.RED}{fmt.S.CROSS}{fmt.C.RESET}"
    COMING = f"{fmt.C.DIM}...{fmt.C.RESET}"


# --- Menu Rendering ---

def _render_menu(title: str, items: list, breadcrumb: list = None):
    """Render a menu screen.

    items: list of (key, label, description, tag) tuples.
    """
    _clear()

    # Breadcrumb
    trail = " > ".join(breadcrumb or ["PVE FREQ"])
    print(f"  {fmt.C.PURPLE}{trail}{fmt.C.RESET}")
    print(f"  {fmt.C.DARK_GRAY}{'─' * (fmt.term_width() - 4)}{fmt.C.RESET}")
    print()

    # Title
    print(f"  {fmt.C.PURPLE_BOLD}{title}{fmt.C.RESET}")
    print()

    # Items
    for item in items:
        if item is None:
            # Section divider
            print()
            continue
        if isinstance(item, str):
            # Section header
            print(f"  {fmt.C.PURPLE_BOLD}{item}{fmt.C.RESET}")
            continue

        key, label, desc, tag = item
        tag_str = f" {tag}" if tag else ""
        print(
            f"  {fmt.C.CYAN}[{key}]{fmt.C.RESET}  "
            f"{fmt.C.BOLD}{label:<16}{fmt.C.RESET} "
            f"{fmt.C.DIM}{desc}{fmt.C.RESET}"
            f"{tag_str}"
        )

    print()
    print(f"  {fmt.C.DARK_GRAY}{'─' * (fmt.term_width() - 4)}{fmt.C.RESET}")
    print(f"  {fmt.C.DIM}Select an option:{fmt.C.RESET} ", end="", flush=True)


def _run_command(cfg, pack, cmd_name: str, args_override: dict = None):
    """Execute a FREQ command and return to menu."""
    from freq.cli import _build_parser
    import argparse

    print()

    # Build args
    argv = [cmd_name]
    if args_override:
        for k, v in args_override.items():
            if v is True:
                argv.append(f"--{k}")
            elif v is not None:
                argv.append(f"--{k}")
                argv.append(str(v))

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return

    if hasattr(args, "func"):
        try:
            args.func(cfg, pack, args)
        except KeyboardInterrupt:
            print(f"\n  {fmt.C.YELLOW}Interrupted.{fmt.C.RESET}")
        except Exception as e:
            fmt.error(f"Command failed: {e}")
            if cfg.debug:
                import traceback
                traceback.print_exc()


def _run_argv(cfg, pack, argv: list):
    """Run a FREQ command with raw argv list."""
    from freq.cli import _build_parser

    print()
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return

    if hasattr(args, "func"):
        try:
            args.func(cfg, pack, args)
        except KeyboardInterrupt:
            print(f"\n  {fmt.C.YELLOW}Interrupted.{fmt.C.RESET}")
        except Exception as e:
            fmt.error(f"Command failed: {e}")


def _run_with_target(cfg, pack, cmd_name: str, prompt: str = "Target:"):
    """Run a command that needs a target argument."""
    target = _input(prompt)
    if not target:
        return

    from freq.cli import _build_parser

    print()
    argv = [cmd_name, target]
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return

    if hasattr(args, "func"):
        try:
            args.func(cfg, pack, args)
        except KeyboardInterrupt:
            print(f"\n  {fmt.C.YELLOW}Interrupted.{fmt.C.RESET}")
        except Exception as e:
            fmt.error(f"Command failed: {e}")


# --- Submenus ---

def _menu_quick_actions(cfg, pack):
    """Quick Actions submenu."""
    crumb = ["PVE FREQ", "Quick Actions"]
    while True:
        _render_menu("Quick Actions", [
            ("1", "dashboard", "Fleet-wide monitoring overview", ""),
            ("2", "health", "Infrastructure dashboard", ""),
            ("3", "vm-overview", "Cluster-wide VM inventory", ""),
            ("4", "docker", "Container status across fleet", ""),
            ("5", "exec", "Run command on all hosts", Tag.RISKY),
            ("6", "info", "Deep dive on a single host", ""),
            ("7", "diagnose", "Find problems on a host", ""),
            ("8", "audit", "Security scan", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "dashboard")
        elif ch == "2":
            _run_command(cfg, pack, "health")
        elif ch == "3":
            _run_command(cfg, pack, "list")
        elif ch == "4":
            print()
            _run_with_target(cfg, pack, "docker", "Host (Enter=auto):")
        elif ch == "5":
            print()
            target = _input("Target (host/group/all):")
            if target:
                cmd = _input("Command:")
                if cmd:
                    from freq.cli import _build_parser
                    argv = ["exec", target] + cmd.split()
                    parser = _build_parser()
                    args = parser.parse_args(argv)
                    if hasattr(args, "func"):
                        args.func(cfg, pack, args)
        elif ch == "6":
            print()
            _run_with_target(cfg, pack, "info", "Host:")
        elif ch == "7":
            print()
            _run_with_target(cfg, pack, "diagnose", "Host:")
        elif ch == "8":
            _run_command(cfg, pack, "audit")
        else:
            continue
        _pause()


def _menu_vm_lifecycle(cfg, pack):
    """VM Lifecycle submenu."""
    crumb = ["PVE FREQ", "VM Lifecycle"]
    while True:
        _render_menu("VM Lifecycle", [
            "Core Operations",
            ("1", "create", "Launch the creation wizard", Tag.CHANGES),
            ("2", "clone", "Full clone an existing VM", Tag.CHANGES),
            ("3", "resize", "Change CPU/RAM/disk", Tag.CHANGES),
            ("4", "list", "Live cluster VM inventory", ""),
            ("5", "vmconfig", "View VM configuration", ""),
            ("6", "snapshot", "Take a quick snapshot", Tag.CHANGES),
            ("7", "migrate", "Move VM between nodes", Tag.RISKY),
            ("8", "destroy", "Safely remove a VM", Tag.DESTRUCTIVE),
            None,
            "Extended Operations",
            ("t", "template", "Convert VM to template", Tag.CHANGES),
            ("r", "rename", "Rename a VM", Tag.CHANGES),
            ("d", "add-disk", "Add disk to a VM", Tag.CHANGES),
            ("g", "tag", "Set/view PVE tags", ""),
            ("p", "pool", "PVE pool management", ""),
            None,
            "Power & NIC",
            ("w", "power", "Start/stop/reboot a VM", Tag.CHANGES),
            ("s", "snapshot list", "List VM snapshots", ""),
            ("x", "snapshot delete", "Delete a snapshot", Tag.DESTRUCTIVE),
            ("n", "nic", "NIC management submenu", Tag.CHANGES),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "create")
        elif ch == "2":
            print()
            _run_with_target(cfg, pack, "clone", "Source VMID:")
        elif ch == "3":
            print()
            _run_with_target(cfg, pack, "resize", "VMID:")
        elif ch == "4":
            _run_command(cfg, pack, "list")
        elif ch == "5":
            print()
            _run_with_target(cfg, pack, "vmconfig", "VMID:")
        elif ch == "6":
            print()
            _run_with_target(cfg, pack, "snapshot", "VMID:")
        elif ch == "7":
            print()
            _run_with_target(cfg, pack, "migrate", "VMID:")
        elif ch == "8":
            print()
            _run_with_target(cfg, pack, "destroy", "VMID:")
        elif ch == "t":
            print()
            _run_with_target(cfg, pack, "template", "VMID:")
        elif ch == "r":
            print()
            _run_with_target(cfg, pack, "rename", "VMID:")
        elif ch == "d":
            print()
            _run_with_target(cfg, pack, "add-disk", "VMID:")
        elif ch == "g":
            print()
            _run_with_target(cfg, pack, "tag", "VMID:")
        elif ch == "p":
            _run_command(cfg, pack, "pool")
        elif ch == "w":
            print()
            action = _input("Action (start/stop/reboot/shutdown/status):")
            if action:
                vmid = _input("VMID:")
                if vmid:
                    _run_argv(cfg, pack, ["power", action, vmid])
        elif ch == "s":
            print()
            vmid = _input("VMID:")
            if vmid:
                _run_argv(cfg, pack, ["snapshot", "list", vmid])
        elif ch == "x":
            print()
            vmid = _input("VMID:")
            if vmid:
                name = _input("Snapshot name:")
                if name:
                    _run_argv(cfg, pack, ["snapshot", "delete", vmid, "--name", name])
        elif ch == "n":
            _menu_nic(cfg, pack)
            continue
        else:
            continue
        _pause()


def _menu_nic(cfg, pack):
    """NIC Management submenu."""
    crumb = ["PVE FREQ", "VM Lifecycle", "NIC Management"]
    while True:
        _render_menu("NIC Management", [
            ("1", "nic add", "Add a NIC to a VM", Tag.CHANGES),
            ("2", "nic clear", "Remove all NICs from a VM", Tag.DESTRUCTIVE),
            ("3", "nic change-ip", "Change VM IP config", Tag.CHANGES),
            ("4", "nic change-id", "Change VMID (clone + destroy)", Tag.RISKY),
            ("5", "nic check-ip", "Check if IP is available", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            print()
            vmid = _input("VMID:")
            if vmid:
                ip = _input("IP address:")
                if ip:
                    gw = _input("Gateway (optional):")
                    vlan = _input("VLAN (optional):")
                    argv = ["nic", "add", vmid, "--ip", ip]
                    if gw:
                        argv += ["--gw", gw]
                    if vlan:
                        argv += ["--vlan", vlan]
                    _run_argv(cfg, pack, argv)
        elif ch == "2":
            print()
            vmid = _input("VMID:")
            if vmid:
                _run_argv(cfg, pack, ["nic", "clear", vmid])
        elif ch == "3":
            print()
            vmid = _input("VMID:")
            if vmid:
                ip = _input("New IP address:")
                if ip:
                    gw = _input("Gateway (optional):")
                    argv = ["nic", "change-ip", vmid, "--ip", ip]
                    if gw:
                        argv += ["--gw", gw]
                    _run_argv(cfg, pack, argv)
        elif ch == "4":
            print()
            vmid = _input("Current VMID:")
            if vmid:
                newid = _input("New VMID:")
                if newid:
                    _run_argv(cfg, pack, ["nic", "change-id", vmid, "--new-id", newid])
        elif ch == "5":
            print()
            ip = _input("IP to check:")
            if ip:
                _run_argv(cfg, pack, ["nic", "check-ip", "--ip", ip])
        else:
            continue
        _pause()


def _menu_fleet_info(cfg, pack):
    """Fleet Info submenu."""
    crumb = ["PVE FREQ", "Fleet Info"]
    while True:
        _render_menu("Fleet Info", [
            ("1", "dashboard", "Monitoring overview", ""),
            ("2", "status", "SSH ping all hosts", ""),
            ("3", "info", "Detailed info for one host", ""),
            ("4", "diagnose", "Deep diagnostic scan", ""),
            ("5", "docker", "Container status", ""),
            ("6", "log", "View host logs", ""),
            ("7", "keys", "SSH key status", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "dashboard")
        elif ch == "2":
            _run_command(cfg, pack, "status")
        elif ch == "3":
            print()
            _run_with_target(cfg, pack, "info", "Host:")
        elif ch == "4":
            print()
            _run_with_target(cfg, pack, "diagnose", "Host:")
        elif ch == "5":
            print()
            _run_with_target(cfg, pack, "docker", "Host (Enter=auto):")
        elif ch == "6":
            print()
            _run_with_target(cfg, pack, "log", "Host:")
        elif ch == "7":
            _run_command(cfg, pack, "keys")
        else:
            continue
        _pause()


def _menu_host_setup(cfg, pack):
    """Host Setup submenu."""
    crumb = ["PVE FREQ", "Host Setup"]
    while True:
        _render_menu("Host Setup", [
            ("1", "discover", "Scan network for hosts", ""),
            ("2", "bootstrap", "Deploy SSH keys to a host", Tag.CHANGES),
            ("3", "onboard", "Add host to fleet", Tag.CHANGES),
            ("4", "hosts", "Manage fleet hosts", ""),
            ("5", "groups", "View host groups", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "discover")
        elif ch == "2":
            _run_command(cfg, pack, "bootstrap")
        elif ch == "3":
            _run_command(cfg, pack, "onboard")
        elif ch == "4":
            _run_command(cfg, pack, "hosts")
        elif ch == "5":
            _run_command(cfg, pack, "groups")
        else:
            continue
        _pause()


def _menu_user_mgmt(cfg, pack):
    """User Management submenu."""
    crumb = ["PVE FREQ", "User Management"]
    while True:
        _render_menu("User Management", [
            ("1", "users", "List registered users", ""),
            ("2", "new-user", "Create a new user", Tag.CHANGES),
            ("3", "passwd", "Change password fleet-wide", Tag.CHANGES),
            ("4", "roles", "View role assignments", ""),
            ("5", "promote", "Elevate user role", Tag.CHANGES),
            ("6", "demote", "Lower user role", Tag.CHANGES),
            ("7", "install-user", "Deploy user to fleet", Tag.CHANGES),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "users")
        elif ch == "2":
            print()
            _run_with_target(cfg, pack, "new-user", "Username:")
        elif ch == "3":
            print()
            _run_with_target(cfg, pack, "passwd", "Username:")
        elif ch == "4":
            _run_command(cfg, pack, "roles")
        elif ch == "5":
            print()
            _run_with_target(cfg, pack, "promote", "Username:")
        elif ch == "6":
            print()
            _run_with_target(cfg, pack, "demote", "Username:")
        elif ch == "7":
            print()
            _run_with_target(cfg, pack, "install-user", "Username:")
        else:
            continue
        _pause()


def _menu_run_commands(cfg, pack):
    """Run Commands submenu."""
    crumb = ["PVE FREQ", "Run Commands"]
    while True:
        _render_menu("Run Commands", [
            ("1", "exec all", "Run command on all hosts", Tag.RISKY),
            ("2", "exec single", "Run command on one host", ""),
            ("3", "keys deploy", "Deploy SSH keys", Tag.CHANGES),
            ("4", "keys list", "Audit SSH key status", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            print()
            cmd = _input("Command:")
            if cmd:
                from freq.cli import _build_parser
                argv = ["exec", "all"] + cmd.split()
                parser = _build_parser()
                args = parser.parse_args(argv)
                if hasattr(args, "func"):
                    args.func(cfg, pack, args)
        elif ch == "2":
            print()
            host = _input("Host:")
            if host:
                cmd = _input("Command:")
                if cmd:
                    from freq.cli import _build_parser
                    argv = ["exec", host] + cmd.split()
                    parser = _build_parser()
                    args = parser.parse_args(argv)
                    if hasattr(args, "func"):
                        args.func(cfg, pack, args)
        elif ch == "3":
            _run_command(cfg, pack, "keys")
        elif ch == "4":
            _run_command(cfg, pack, "keys")
        else:
            continue
        _pause()


def _menu_proxmox(cfg, pack):
    """Proxmox submenu."""
    crumb = ["PVE FREQ", "Proxmox"]
    while True:
        _render_menu("Proxmox", [
            ("1", "vm-overview", "Cluster-wide VM inventory", ""),
            ("2", "vmconfig", "View VM configuration", ""),
            ("3", "migrate", "Move VM between nodes", Tag.RISKY),
            ("4", "rescue", "Boot from rescue ISO", Tag.RISKY),
            ("5", "distros", "Supported cloud images", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "list")
        elif ch == "2":
            print()
            _run_with_target(cfg, pack, "vmconfig", "VMID:")
        elif ch == "3":
            print()
            _run_with_target(cfg, pack, "migrate", "VMID:")
        elif ch == "4":
            _run_command(cfg, pack, "rescue")
        elif ch == "5":
            _run_command(cfg, pack, "distros")
        else:
            continue
        _pause()


def _menu_security(cfg, pack):
    """Security & Vault submenu."""
    crumb = ["PVE FREQ", "Security"]
    while True:
        _render_menu("Security & Vault", [
            ("1", "audit", "Security scan", ""),
            ("2", "harden", "Apply hardening", Tag.CHANGES),
            None,
            ("3", "vault list", "Show stored credentials", ""),
            ("4", "vault set", "Store a credential", Tag.CHANGES),
            ("5", "vault get", "Retrieve a credential", ""),
            ("6", "vault init", "Initialize vault", Tag.CHANGES),
            None,
            "Policy Engine",
            ("7", "check", "Check policy compliance (dry run)", ""),
            ("8", "fix", "Apply policy remediation", Tag.CHANGES),
            ("9", "diff", "Show policy drift", ""),
            ("c", "policies", "List available policies", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "audit")
        elif ch == "2":
            _run_command(cfg, pack, "harden")
        elif ch == "3":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["vault", "list"])
            args.func(cfg, pack, args)
        elif ch == "4":
            from freq.cli import _build_parser
            print()
            key = _input("Key name:")
            if key:
                parser = _build_parser()
                args = parser.parse_args(["vault", "set", key])
                args.func(cfg, pack, args)
        elif ch == "5":
            from freq.cli import _build_parser
            print()
            key = _input("Key name:")
            if key:
                parser = _build_parser()
                args = parser.parse_args(["vault", "get", key])
                args.func(cfg, pack, args)
        elif ch == "6":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["vault", "init"])
            args.func(cfg, pack, args)
        elif ch == "7":
            _run_command(cfg, pack, "check")
        elif ch == "8":
            _run_command(cfg, pack, "fix")
        elif ch == "9":
            _run_command(cfg, pack, "diff")
        elif ch == "c":
            _run_command(cfg, pack, "policies")
        else:
            continue
        _pause()


def _menu_media_stack(cfg, pack):
    """Media Stack submenu — full media management."""
    crumb = ["PVE FREQ", "Media Stack"]
    while True:
        _render_menu("Media Stack", [
            "Status & Health",
            ("1", "status", "Container status across all VMs", ""),
            ("2", "health", "API health checks", ""),
            ("3", "dashboard", "Aggregate media dashboard", ""),
            ("4", "doctor", "Comprehensive diagnostic", ""),
            None,
            "Downloads & Library",
            ("5", "queue", "Download queue (qBit + SABnzbd)", ""),
            ("6", "streams", "Active Plex streams", ""),
            ("7", "missing", "Missing episodes/movies", ""),
            ("8", "downloads", "Download management", ""),
            None,
            "Container Ops",
            ("9", "restart", "Restart a container", Tag.CHANGES),
            ("a", "logs", "View container logs", ""),
            ("b", "update", "Update container images", Tag.CHANGES),
            ("c", "stats", "Container resource stats", ""),
            None,
            "Advanced",
            ("d", "indexers", "Prowlarr indexer status", ""),
            ("e", "transcode", "Tdarr transcode status", ""),
            ("f", "vpn", "VPN/Gluetun status", ""),
            ("g", "disk", "Disk usage across VMs", ""),
            ("h", "compose", "Compose file audit", ""),
            ("i", "mounts", "NFS mount check", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "q", "\x1b"):
            return
        elif ch == "1":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "status"])
            args.func(cfg, pack, args)
        elif ch == "2":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "health"])
            args.func(cfg, pack, args)
        elif ch == "3":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "dashboard"])
            args.func(cfg, pack, args)
        elif ch == "4":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "doctor"])
            args.func(cfg, pack, args)
        elif ch == "5":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "queue"])
            args.func(cfg, pack, args)
        elif ch == "6":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "streams"])
            args.func(cfg, pack, args)
        elif ch == "7":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "missing"])
            args.func(cfg, pack, args)
        elif ch == "8":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "downloads"])
            args.func(cfg, pack, args)
        elif ch == "9":
            print()
            svc = _input("Service to restart:")
            if svc:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["media", "restart", svc])
                args.func(cfg, pack, args)
        elif ch == "a":
            print()
            svc = _input("Service:")
            if svc:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["media", "logs", svc])
                args.func(cfg, pack, args)
        elif ch == "b":
            print()
            svc = _input("Service (or 'all'):")
            if svc:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["media", "update", svc])
                args.func(cfg, pack, args)
        elif ch == "c":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "stats"])
            args.func(cfg, pack, args)
        elif ch == "d":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "indexers"])
            args.func(cfg, pack, args)
        elif ch == "e":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "transcode"])
            args.func(cfg, pack, args)
        elif ch == "f":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "vpn"])
            args.func(cfg, pack, args)
        elif ch == "g":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "disk"])
            args.func(cfg, pack, args)
        elif ch == "h":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "compose", "audit"])
            args.func(cfg, pack, args)
        elif ch == "i":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "mounts"])
            args.func(cfg, pack, args)
        else:
            continue
        _pause()


def _menu_lab(cfg, pack):
    """Lab submenu — sandbox spawning, specialists, lab management."""
    crumb = ["PVE FREQ", "Lab"]
    while True:
        _render_menu("Lab & Specialists", [
            "Lab VMs",
            ("1", "lab status", "Lab fleet overview", ""),
            ("2", "sandbox", "Spawn VM from template", Tag.CHANGES),
            ("3", "template", "Convert VM to template", Tag.CHANGES),
            ("4", "lab media", "Lab media stack status", ""),
            ("5", "lab rebuild", "Destroy and recreate VM", Tag.DESTRUCTIVE),
            None,
            "Specialists",
            ("6", "create", "Deploy specialist workspace", Tag.CHANGES),
            ("7", "health", "Check specialist health", ""),
            ("8", "roles", "List specialist roles", ""),
            None,
            "Fleet",
            ("9", "ntp", "Check fleet NTP sync", ""),
            ("a", "updates", "Check OS updates", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "lab")
        elif ch == "2":
            print()
            tmpl = _input("Template VMID:")
            if tmpl:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["sandbox", tmpl])
                args.func(cfg, pack, args)
        elif ch == "3":
            print()
            _run_with_target(cfg, pack, "template", "VMID:")
        elif ch == "4":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["lab", "media"])
            args.func(cfg, pack, args)
        elif ch == "5":
            print()
            vmid = _input("VMID to rebuild:")
            if vmid:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["lab", "rebuild", vmid])
                args.func(cfg, pack, args)
        elif ch == "6":
            print()
            host = _input("Host IP:")
            if host:
                role = _input("Role (sandbox/dev/infra/security/media):")
                if role:
                    from freq.cli import _build_parser
                    parser = _build_parser()
                    args = parser.parse_args(["specialist", "create", host, "--role", role])
                    args.func(cfg, pack, args)
        elif ch == "7":
            print()
            _run_with_target(cfg, pack, "specialist", "Host:")
        elif ch == "8":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["specialist", "roles"])
            args.func(cfg, pack, args)
        elif ch == "9":
            _run_command(cfg, pack, "ntp")
        elif ch == "a":
            _run_command(cfg, pack, "fleet-update")
        else:
            continue
        _pause()


def _menu_monitoring(cfg, pack):
    """Monitoring submenu."""
    crumb = ["PVE FREQ", "Monitoring"]
    while True:
        _render_menu("Monitoring", [
            ("1", "health", "Infrastructure dashboard", ""),
            ("2", "media dash", "Media stack dashboard", ""),
            ("3", "watch", "Monitoring daemon", ""),
            ("4", "doctor", "Self-diagnostic", ""),
            ("5", "compose", "Compose file audit", ""),
            ("6", "ntp", "Fleet NTP status", ""),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "health")
        elif ch == "2":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "dashboard"])
            args.func(cfg, pack, args)
        elif ch == "3":
            _run_command(cfg, pack, "watch")
        elif ch == "4":
            _run_command(cfg, pack, "doctor")
        elif ch == "5":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["media", "compose", "audit"])
            args.func(cfg, pack, args)
        elif ch == "6":
            _run_command(cfg, pack, "ntp")
        else:
            continue
        _pause()


def _menu_infrastructure(cfg, pack):
    """Infrastructure submenu."""
    crumb = ["PVE FREQ", "Infrastructure"]
    while True:
        _render_menu("Infrastructure", [
            ("1", "pfSense", "Firewall rules, NAT, logs", ""),
            ("2", "TrueNAS", "Pools, shares, alerts", ""),
            ("3", "Switch", "Cisco Catalyst VLANs/ports", ""),
            ("4", "iDRAC", "Server BMC management", ""),
            ("5", "VPN", "WireGuard tunnels", Tag.COMING),
            None,
            "Fleet Operations",
            ("6", "NTP", "Fleet time sync check/fix", ""),
            ("7", "Updates", "Fleet OS updates", ""),
            ("8", "Comms", "Inter-VM mailbox", ""),
            ("9", "ZFS", "ZFS pool operations", ""),
            ("a", "Backup", "VM backup management", ""),
            ("j", "Journal", "Operation history", ""),
            ("n", "Notify", "Send notification", Tag.CHANGES),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            _run_command(cfg, pack, "pfsense")
        elif ch == "2":
            _run_command(cfg, pack, "truenas")
        elif ch == "3":
            _run_command(cfg, pack, "switch")
        elif ch == "4":
            _run_command(cfg, pack, "idrac")
        elif ch == "5":
            _run_command(cfg, pack, "vpn")
        elif ch == "6":
            _run_command(cfg, pack, "ntp")
        elif ch == "7":
            _run_command(cfg, pack, "fleet-update")
        elif ch == "8":
            _run_command(cfg, pack, "comms")
        elif ch == "9":
            _run_command(cfg, pack, "zfs")
        elif ch == "a":
            _run_command(cfg, pack, "backup")
        elif ch == "j":
            _run_command(cfg, pack, "journal")
        elif ch == "n":
            _run_command(cfg, pack, "notify")
        else:
            continue
        _pause()


def _menu_agents(cfg, pack):
    """Agent Platform submenu."""
    crumb = ["PVE FREQ", "Agent Platform"]
    while True:
        _render_menu("Agent Platform", [
            ("1", "templates", "Browse specialist templates", ""),
            ("2", "create", "Create a new AI specialist", Tag.CHANGES),
            ("3", "list", "Show registered agents", ""),
            ("4", "status", "Live health check on all agents", ""),
            ("5", "start", "Start an agent session", ""),
            ("6", "stop", "Stop an agent session", ""),
            ("7", "destroy", "Remove agent + VM", Tag.DESTRUCTIVE),
            ("0", "Back", "", ""),
        ], crumb)

        ch = _getch()
        if ch in ("0", "b", "q", "\x1b"):
            return
        elif ch == "1":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["agent", "templates"])
            args.func(cfg, pack, args)
        elif ch == "2":
            print()
            template = _input("Template (infra-manager/security-ops/dev/media-ops/blank):")
            if template:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["agent", "create", template])
                args.func(cfg, pack, args)
        elif ch == "3":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["agent", "list"])
            args.func(cfg, pack, args)
        elif ch == "4":
            from freq.cli import _build_parser
            parser = _build_parser()
            args = parser.parse_args(["agent", "status"])
            args.func(cfg, pack, args)
        elif ch == "5":
            print()
            name = _input("Agent name:")
            if name:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["agent", "start", name])
                args.func(cfg, pack, args)
        elif ch == "6":
            print()
            name = _input("Agent name:")
            if name:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["agent", "stop", name])
                args.func(cfg, pack, args)
        elif ch == "7":
            print()
            name = _input("Agent name:")
            if name:
                from freq.cli import _build_parser
                parser = _build_parser()
                args = parser.parse_args(["agent", "destroy", name])
                args.func(cfg, pack, args)
        else:
            continue
        _pause()


def _gwipe_cmd(cfg, pack, *argv):
    """Run a freq gwipe subcommand."""
    from freq.cli import _build_parser
    print()
    try:
        parser = _build_parser()
        args = parser.parse_args(["gwipe"] + list(argv))
        if hasattr(args, "func"):
            args.func(cfg, pack, args)
    except Exception as e:
        print(f"  {fmt.C.RED}Error: {e}{fmt.C.RESET}")


def _menu_freq_wipe(cfg, pack):
    """FREQ WIPE submenu — drive sanitization station."""
    crumb = ["PVE FREQ", "FREQ WIPE"]
    while True:
        _render_menu("FREQ WIPE — Drive Sanitization", [
            "Station",
            ("1", "Status", "Station overview", ""),
            ("2", "Bays", "All drive bays + progress", ""),
            ("3", "History", "Wipe history log", ""),
            None,
            "Actions",
            ("4", "Full Send", "SMART all + auto-wipe", ""),
            ("5", "Wipe Bay", "Wipe a specific drive", ""),
            ("6", "SMART Test", "Test a bay or all", ""),
            ("7", "Pause", "Pause all active wipes", ""),
            ("8", "Resume", "Resume all paused wipes", ""),
            None,
            "Config",
            ("9", "Connect", "Set station host + API key", ""),
        ], crumb)

        ch = _getch()
        if ch in ("\x1b", "0", "q"):
            return
        elif ch == "1":
            _gwipe_cmd(cfg, pack, "status")
        elif ch == "2":
            _gwipe_cmd(cfg, pack, "bays")
        elif ch == "3":
            _gwipe_cmd(cfg, pack, "history")
        elif ch == "4":
            _gwipe_cmd(cfg, pack, "full-send")
        elif ch == "5":
            print()
            bay = _input("Bay device (e.g. sdb):")
            if bay:
                _gwipe_cmd(cfg, pack, "wipe", bay)
        elif ch == "6":
            print()
            bay = _input("Bay device (blank=all):")
            if bay:
                _gwipe_cmd(cfg, pack, "test", bay)
            else:
                _gwipe_cmd(cfg, pack, "test")
        elif ch == "7":
            _gwipe_cmd(cfg, pack, "pause")
        elif ch == "8":
            _gwipe_cmd(cfg, pack, "resume")
        elif ch == "9":
            print()
            host = _input("FREQ WIPE station IP:")
            key = _input("API key:")
            if host and key:
                _gwipe_cmd(cfg, pack, "connect", "--host", host, "--key", key)
        else:
            continue
        _pause()


# --- Main Menu ---

def run(cfg, pack) -> int:
    """Launch the interactive TUI menu."""
    first_run = True

    while True:
        _clear()

        if first_run:
            # Show splash on first render
            splash(pack, cfg.version)
            print()

            # Quick stats
            host_count = len(cfg.hosts)
            pve_count = sum(1 for h in cfg.hosts if h.htype == "pve")
            print(f"  {fmt.C.DIM}{fmt.S.DOT} Hosts: {host_count}    "
                  f"{fmt.S.DOT} PVE nodes: {pve_count}    "
                  f"{fmt.S.DOT} User: {os.environ.get('USER', 'unknown')}{fmt.C.RESET}")
            print()
            first_run = False

        # Render main menu
        print(f"  {fmt.C.PURPLE_BOLD}PVE FREQ{fmt.C.RESET}")
        print(f"  {fmt.C.DARK_GRAY}{'─' * (fmt.term_width() - 4)}{fmt.C.RESET}")
        print()

        sections = [
            "Quick Access",
            ("!", "Quick Actions", "Top daily commands", ""),
            None,
            "VM Operations",
            ("v", "VM Lifecycle", "Create, clone, resize, template, tag", ""),
            ("k", "Lab", "Sandbox spawn, templates, NTP", ""),
            None,
            "Media",
            ("g", "Media Stack", "40+ commands for Plex/Arr/qBit", ""),
            None,
            "Fleet",
            ("f", "Fleet Info", "Dashboard, status, diagnose", ""),
            ("b", "Host Setup", "Discover, bootstrap, onboard", ""),
            ("u", "User Mgmt", "Users, roles, passwords", ""),
            ("x", "Run Commands", "Fleet exec, SSH keys", ""),
            None,
            "Proxmox & Infrastructure",
            ("p", "Proxmox", "VM overview, config, migrate", ""),
            ("n", "Hosts & Groups", "Host registry, groups", ""),
            ("i", "Infrastructure", "pfSense, TrueNAS, iDRAC, NTP", ""),
            None,
            "Smart Commands",
            ("l", "Learn", "Search the knowledge base", ""),
            ("r", "Risk", "Kill-chain blast radius analysis", ""),
            ("w", "Sweep", "Full audit + policy pipeline", ""),
            None,
            "Agent Platform",
            ("a", "Agents", "Create & manage AI specialists", ""),
            None,
            "Monitoring & Security",
            ("m", "Monitoring", "Health, media, doctor, NTP", ""),
            ("s", "Security", "Audit, vault, harden", ""),
            None,
            "Lab Tools",
            ("z", "FREQ WIPE", "Drive sanitization station", ""),
            None,
            ("d", "Doctor", "Self-diagnostic", ""),
            ("e", "Version", "Build info", ""),
            ("h", "Help", "Command reference", ""),
            ("q", "Quit", "", ""),
        ]

        for item in sections:
            if item is None:
                print()
                continue
            if isinstance(item, str):
                print(f"  {fmt.C.PURPLE_BOLD}{item}{fmt.C.RESET}")
                continue

            key, label, desc, tag = item
            tag_str = f" {tag}" if tag else ""
            print(
                f"  {fmt.C.CYAN}[{key}]{fmt.C.RESET}  "
                f"{fmt.C.BOLD}{label:<16}{fmt.C.RESET} "
                f"{fmt.C.DIM}{desc}{fmt.C.RESET}"
                f"{tag_str}"
            )

        print()
        print(f"  {fmt.C.DARK_GRAY}{'─' * (fmt.term_width() - 4)}{fmt.C.RESET}")
        print(f"  {fmt.C.DIM}Select:{fmt.C.RESET} ", end="", flush=True)

        # Read selection
        try:
            ch = _getch()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        # Handle Ctrl+C and Ctrl+D
        if ch in ("\x03", "\x04"):
            print()
            return 0

        ch_lower = ch.lower()

        # Dispatch
        if ch_lower == "q":
            _clear()
            print(f"\n  {fmt.C.PURPLE}freq out.{fmt.C.RESET}\n")
            return 0
        elif ch_lower == "!":
            _menu_quick_actions(cfg, pack)
        elif ch_lower == "v":
            _menu_vm_lifecycle(cfg, pack)
        elif ch_lower == "k":
            _menu_lab(cfg, pack)
        elif ch_lower == "g":
            _menu_media_stack(cfg, pack)
        elif ch_lower == "f":
            _menu_fleet_info(cfg, pack)
        elif ch_lower == "b":
            _menu_host_setup(cfg, pack)
        elif ch_lower == "u":
            _menu_user_mgmt(cfg, pack)
        elif ch_lower == "x":
            _menu_run_commands(cfg, pack)
        elif ch_lower == "p":
            _menu_proxmox(cfg, pack)
        elif ch_lower == "n":
            _run_command(cfg, pack, "hosts")
            _pause()
        elif ch_lower == "i":
            _menu_infrastructure(cfg, pack)
        elif ch_lower == "l":
            print()
            query = _input("Search knowledge base:")
            if query:
                from freq.cli import _build_parser
                argv = ["learn"] + query.split()
                parser = _build_parser()
                args = parser.parse_args(argv)
                if hasattr(args, "func"):
                    args.func(cfg, pack, args)
            else:
                _run_command(cfg, pack, "learn")
            _pause()
        elif ch_lower == "r":
            print()
            target = _input("Target (pfsense/truenas/switch/all):")
            if target:
                _run_with_target(cfg, pack, "risk", "")
            else:
                _run_command(cfg, pack, "risk")
            _pause()
        elif ch_lower == "w":
            _run_command(cfg, pack, "sweep")
            _pause()
        elif ch_lower == "a":
            _menu_agents(cfg, pack)
        elif ch_lower == "m":
            _menu_monitoring(cfg, pack)
        elif ch_lower == "s":
            _menu_security(cfg, pack)
        elif ch_lower == "z":
            _menu_freq_wipe(cfg, pack)
        elif ch_lower == "d":
            _run_command(cfg, pack, "doctor")
            _pause()
        elif ch_lower == "e":
            _run_command(cfg, pack, "version")
            _pause()
        elif ch_lower == "h":
            _run_command(cfg, pack, "help")
            _pause()
        # Enter = redraw
        elif ch in ("\r", "\n"):
            continue
